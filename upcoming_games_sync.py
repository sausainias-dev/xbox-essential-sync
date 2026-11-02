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
    """Find Coming Soon robustly and stop only at the Available Games section."""
    headings = page.locator("h1,h2,h3,h4")
    candidates = []
    for i in range(headings.count()):
        heading = headings.nth(i)
        label = catalog.clean(heading.inner_text())
        if re.search(r"coming\\s+soon", label, re.I):
            box = heading.bounding_box()
            if box:
                candidates.append((heading, label, box["y"]))

    if not candidates:
        body = catalog.clean(page.locator("body").inner_text())
        # Do not infer an empty feed from a missing selector. The source may have
        # changed markup; keep the existing published JSON/HTML untouched.
        excerpt = body[:1200]
        raise RuntimeError(
            "Coming Soon section not found in visible headings. "
            f"Page title={page.title()!r}; body excerpt={excerpt!r}. Nothing published."
        )

    # Prefer an exact/near-exact section heading over incidental card text.
    target, target_label, start_y = min(
        candidates,
        key=lambda item: (
            0 if re.fullmatch(r"coming\\s+soon(?:\\s*\\(.*\\))?", item[1], re.I) else 1,
            item[2],
        ),
    )
    end_y = float("inf")
    for i in range(headings.count()):
        heading = headings.nth(i)
        label = catalog.clean(heading.inner_text())
        box = heading.bounding_box()
        if box and box["y"] > start_y and re.match(r"^Available\\s+Games\\b", label, re.I):
            end_y = min(end_y, box["y"])

    results, seen = [], set()
    links = page.locator('a[href*="/game/"]')
    for i in range(links.count()):
        anchor = links.nth(i)
        try:
            box = anchor.bounding_box()
        except Exception:
            box = None
        if not box or not (start_y < box["y"] < end_y):
            continue
        href = anchor.get_attribute("href") or ""
        url = urljoin(page.url, href)
        name, year = catalog.clean_title(anchor.inner_text())
        if not name or url in seen:
            continue
        seen.add(url)

        card_text = ""
        node = anchor
        for _ in range(6):
            try:
                candidate = catalog.clean(node.inner_text(timeout=1200))
            except Exception:
                candidate = ""
            if re.search(r"(?:Arrives:|\\bTBD\\b)", candidate, re.I):
                card_text = candidate
                break
            try:
                node = node.locator("xpath=..")
            except Exception:
                break

        item = {"name": name, "url": url}
        if year:
            item["year"] = year
        match = re.search(r"Arrives:\\s*([^\\n]+)", card_text, re.I)
        if match:
            item["availability_date"] = catalog.clean(match.group(1))
            item["availability_date_type"] = "arrives"
        elif re.search(r"\\bTBD\\b", card_text, re.I):
            item["availability_date"] = "TBD"
            item["availability_date_type"] = "tbd"
        results.append(item)

    # A matching heading with no cards may be a temporary source rendering issue.
    if not results:
        raise RuntimeError(
            f"Coming Soon heading {target_label!r} was found but zero games were extracted. "
            "Nothing will be published."
        )

    results = [
        game for game in results
        if catalog.clean(game.get("name", "")).casefold() != "football manager 27"
    ]
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

    enriched = []
    for index, item in enumerate(games, 1):
        print(f"[{index}/{len(games)}] Enriching {item['name']}")
        game = dict(item)
        catalog.enrich(game)
        # Never expose internal source detail URLs or community metrics.
        for key in list(game):
            if key == "url" or key.startswith("community_") or key == "enrich_error":
                game.pop(key, None)
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
