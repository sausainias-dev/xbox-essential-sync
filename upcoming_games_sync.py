#!/usr/bin/env python3
"""Dedicated scraper and static HTML builder for Subli.one upcoming Game Pass games."""
from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright
import sync as catalog

SOURCE = "https://gamescriptions.com/subscription/service/xbox_ultimate"
OUT_HTML = Path("upcoming-game-pass-games.html")
OUT_JSON = Path("upcoming-game-pass-games.json")

def find_coming_soon_heading(page):
    """Find the Coming Soon section across the heading layouts used by the source."""
    heading_selector = "h1,h2,h3,h4,h5,h6,[role='heading']"
    headings = page.locator(heading_selector)
    aliases = re.compile(
        r"\b(?:Coming\s+Soon|Upcoming(?:\s+Games?)?|Coming\s+to\s+Game\s+Pass)\b",
        re.I,
    )

    for i in range(headings.count()):
        heading = headings.nth(i)
        try:
            label = catalog.clean(heading.inner_text(timeout=1500))
        except Exception:
            continue
        if aliases.search(label):
            return heading

    # Some responsive layouts render section titles as styled div/span elements
    # instead of semantic headings. Accept a text match only when it is visible
    # and can be anchored to a nearby heading/container.
    matches = page.get_by_text(aliases)
    for i in range(min(matches.count(), 30)):
        candidate = matches.nth(i)
        try:
            if not candidate.is_visible():
                continue
            label = catalog.clean(candidate.inner_text(timeout=1000))
            if len(label) > 100 or not aliases.search(label):
                continue
            ancestor = candidate.locator(
                "xpath=ancestor-or-self::*[self::h1 or self::h2 or self::h3 or self::h4 or self::h5 or self::h6 or @role='heading'][1]"
            )
            if ancestor.count():
                return ancestor.first
            return candidate
        except Exception:
            continue
    return None


def collect_upcoming(page) -> list[dict]:
    target = find_coming_soon_heading(page)
    if target is None:
        visible_headings = []
        headings = page.locator("h1,h2,h3,h4,h5,h6,[role='heading']")
        for i in range(min(headings.count(), 40)):
            try:
                visible_headings.append(catalog.clean(headings.nth(i).inner_text(timeout=1000)))
            except Exception:
                continue
        body_text = catalog.clean(page.locator("body").inner_text(timeout=5000))
        hint = "Coming Soon text is present in body" if re.search(r"Coming\s+Soon", body_text, re.I) else "Coming Soon text is absent from body"
        raise RuntimeError(
            "Could not identify the Coming Soon section; "
            f"{hint}. Headings seen: {visible_headings[:20]!r}. "
            "Refusing to publish an empty or unverified feed."
        )

    start = target.bounding_box()
    if not start:
        try:
            start = target.locator("xpath=..").bounding_box()
        except Exception:
            start = None
    if not start:
        raise RuntimeError("Found Coming Soon text but could not locate its section on the page")

    boundary = re.compile(
        r"^(?:Available\s+Games|Leaving\s+Soon|New\s+Releases|Recently\s+Added)\b",
        re.I,
    )
    headings = page.locator("h1,h2,h3,h4,h5,h6,[role='heading']")
    end_y = float("inf")
    for i in range(headings.count()):
        h = headings.nth(i)
        try:
            label = catalog.clean(h.inner_text(timeout=1000))
            box = h.bounding_box()
        except Exception:
            continue
        if box and box["y"] > start["y"] + 1 and boundary.search(label):
            end_y = min(end_y, box["y"])

    results, seen = [], set()
    links = page.locator('a[href*="/game/"]')
    for i in range(links.count()):
        a = links.nth(i)
        try:
            box = a.bounding_box()
        except Exception:
            box = None
        if not box or not (start["y"] < box["y"] < end_y):
            continue
        href = a.get_attribute("href") or ""
        url = urljoin(page.url, href)
        if "/game/" not in url:
            continue
        name, year = catalog.clean_title(a.inner_text())
        key = url.rstrip("/").casefold()
        if not name or key in seen:
            continue
        seen.add(key)

        date_text = ""
        node = a
        for _ in range(7):
            try:
                text = catalog.clean(node.inner_text(timeout=1200))
            except Exception:
                text = ""
            if re.search(r"(?:Arrives|Added):|\bTBD\b", text, re.I):
                date_text = text
                break
            try:
                node = node.locator("xpath=..")
            except Exception:
                break

        item = {"name": name, "url": url}
        if year:
            item["year"] = year
        match = re.search(r"Arrives:\s*([^\n]+)", date_text, re.I)
        if match:
            item["availability_date"] = catalog.clean(match.group(1))
            item["availability_date_type"] = "arrives"
        elif re.search(r"\bTBD\b", date_text, re.I):
            item["availability_date"] = "TBD"
            item["availability_date_type"] = "tbd"
        results.append(item)

    # Exclude the generic Football Manager 27 entry; the Console edition is
    # listed separately and has its own Game Pass availability.
    results = [
        game for game in results
        if catalog.clean(game.get("name", "")).casefold() != "football manager 27"
    ]
    if not results:
        raise RuntimeError(
            "The Coming Soon section was identified, but no valid game cards were found "
            "inside its boundaries; refusing to overwrite the published feed."
        )
    print(f"Found {len(results)} upcoming Game Pass games after exclusions")
    return results

def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
        page = browser.new_page(user_agent=catalog.USER_AGENT, viewport={"width":1440,"height":1200})
        page.set_default_timeout(15000)
        page.goto(SOURCE, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(1800)
        games = collect_upcoming(page)
        browser.close()

    previous_count = 0
    if OUT_JSON.exists():
        try:
            previous = json.loads(OUT_JSON.read_text(encoding="utf-8"))
            previous_games = previous.get("games", [])
            if not isinstance(previous_games, list):
                raise ValueError("the previous games field is not a list")
            previous_count = len(previous_games)
        except (OSError, json.JSONDecodeError, AttributeError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Cannot validate the existing Upcoming feed ({exc}); "
                "leaving the published JSON and HTML untouched."
            ) from exc

    minimum_expected = max(3, (previous_count + 1) // 2) if previous_count else 1
    if len(games) < minimum_expected:
        raise RuntimeError(
            f"Only {len(games)} upcoming games were extracted, below the safety "
            f"threshold of {minimum_expected} based on the previous {previous_count} "
            "published games. Existing JSON/HTML files were left untouched."
        )

    enriched = []
    for index, item in enumerate(games, 1):
        print(f"[{index}/{len(games)}] Enriching {item['name']}")
        game = dict(item)
        catalog.enrich(game)
        # Never expose internal source detail URLs or community metrics.
        for key in list(game):
            if key == "url" or key.startswith("community_") or key == "enrich_error":
                game.pop(key, None)
        if game.get("screenshot_urls"):
            # The standalone page displays at most eight gallery images per game.
            screenshots = list(dict.fromkeys(game["screenshot_urls"]))[:8]
            if screenshots:
                game["screenshot_urls"] = screenshots
            else:
                game.pop("screenshot_urls", None)
        enriched.append(game)

    if not enriched:
        raise RuntimeError("Refusing to publish an empty upcoming-games feed")

    feed = {
        "source": "Subli.one Xbox Game Pass Ultimate",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(enriched),
        "games": enriched,
    }
    json_tmp = OUT_JSON.with_suffix(".json.tmp")
    html_tmp = OUT_HTML.with_suffix(".html.tmp")
    json_tmp.write_text(json.dumps(feed, ensure_ascii=False, indent=2), encoding="utf-8")
    html_tmp.write_text(catalog.render_upcoming_html(feed), encoding="utf-8")
    json_tmp.replace(OUT_JSON)
    html_tmp.replace(OUT_HTML)
    print(f"Published {len(enriched)} upcoming games to {OUT_HTML} and {OUT_JSON}")

if __name__ == "__main__":
    main()
