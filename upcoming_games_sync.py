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

def collect_upcoming(page) -> list[dict]:
    headings = page.locator("h1,h2,h3,h4")
    target = None
    for i in range(headings.count()):
        label = catalog.clean(headings.nth(i).inner_text())
        if re.match(r"^Coming\s+Soon\b", label, re.I):
            target = headings.nth(i)
            break
    if target is None:
        raise RuntimeError("Coming Soon section was not found; refusing to publish empty data")

    start = target.bounding_box()
    if not start:
        raise RuntimeError("Could not locate Coming Soon section")
    end_y = float("inf")
    for i in range(headings.count()):
        h = headings.nth(i)
        label = catalog.clean(h.inner_text())
        if re.match(r"^Available\s+Games\b", label, re.I):
            box = h.bounding_box()
            if box and box["y"] > start["y"]:
                end_y = box["y"]
                break

    results, seen = [], set()
    links = page.locator('a[href*="/game/"]')
    for i in range(links.count()):
        a = links.nth(i)
        box = a.bounding_box()
        if not box or not (start["y"] < box["y"] < end_y):
            continue
        href = a.get_attribute("href") or ""
        url = urljoin(page.url, href)
        name, year = catalog.clean_title(a.inner_text())
        if not name or url in seen:
            continue
        seen.add(url)
        date_text = ""
        node = a
        for _ in range(6):
            try:
                text = catalog.clean(node.inner_text(timeout=1200))
            except Exception:
                text = ""
            if re.search(r"Arrives:|\bTBD\b", text, re.I):
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
    if not results:
        raise RuntimeError("Coming Soon was found but zero games were extracted; refusing to overwrite published files")
    print(f"Found {len(results)} upcoming Game Pass games")
    return results

def main() -> None:
    enriched = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
        context = browser.new_context(
            user_agent=catalog.USER_AGENT,
            viewport={"width": 1440, "height": 1200},
        )
        page = context.new_page()
        page.set_default_timeout(20000)
        page.goto(SOURCE, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(1800)
        games = collect_upcoming(page)

        # Visit each game's detail page in Chromium, not requests: GameScriptions
        # builds its screenshot carousel and YouTube player client-side.
        for index, item in enumerate(games, 1):
            print(f"[{index}/{len(games)}] Enriching rendered page: {item['name']}")
            game = dict(item)
            try:
                page.goto(game["url"], wait_until="domcontentloaded", timeout=90000)
                page.wait_for_timeout(1100)
                # Give lazy media a chance to enter the DOM without relying on
                # networkidle (analytics and video players can keep it busy).
                for label in ("Screenshots", "Game Gallery", "Videos", "Trailer"):
                    locator = page.get_by_text(label, exact=False).first
                    try:
                        if locator.count():
                            locator.scroll_into_view_if_needed(timeout=1500)
                    except Exception:
                        pass
                page.wait_for_timeout(450)
                catalog.enrich(game, html=page.content())
            except Exception as exc:
                print(f"  detail-page warning for {item['name']}: {exc}")
                # Keep basic game data even if one detail page fails.
                try:
                    catalog.enrich(game)
                except Exception:
                    pass

            # Never expose internal source detail URLs or community metrics.
            for key in list(game):
                if key == "url" or key.startswith("community_") or key == "enrich_error":
                    game.pop(key, None)
            enriched.append(game)
        browser.close()

    if not enriched:
        raise RuntimeError("Refusing to publish an empty upcoming-games feed")

    screenshot_games = sum(bool(game.get("screenshot_urls")) for game in enriched)
    screenshot_total = sum(len(game.get("screenshot_urls", [])) for game in enriched)
    trailer_games = sum(bool(game.get("trailer_url")) for game in enriched)
    gameplay_games = sum(bool(game.get("gameplay_url")) for game in enriched)
    print(
        "MEDIA COVERAGE: "
        f"{screenshot_games}/{len(enriched)} games with screenshots "
        f"({screenshot_total} images), "
        f"{trailer_games} trailers, {gameplay_games} gameplay videos"
    )

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
