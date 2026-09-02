#!/usr/bin/env python3
"""Build the complete Xbox Game Pass catalog for Subli.one."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

OUT = Path("xbox-essential.json")
USER_AGENT = "Mozilla/5.0 (compatible; SubliXboxCatalog/3.4; +https://github.com/)"
SERVICES = {
    "essential": "https://gamescriptions.com/subscription/service/xbox_essential",
    "pc": "https://gamescriptions.com/subscription/service/xbox_pc",
    "premium": "https://gamescriptions.com/subscription/service/xbox_premium",
    "ultimate": "https://gamescriptions.com/subscription/service/xbox_ultimate",
}
PLAN_ORDER = ("essential", "pc", "premium", "ultimate")
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})


def clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def clean_title(value: str) -> tuple[str, int | None]:
    value = clean(value)
    match = re.match(r"^(.*?)\s*\(\s*(\d{4})\s*\)\s*$", value)
    if match:
        return clean(match.group(1)), int(match.group(2))
    return value, None


def expected_count(page) -> int | None:
    headings = page.locator("h2, h3")
    for i in range(headings.count()):
        text = clean(headings.nth(i).inner_text())
        m = re.search(r"^Available Games\s*\((\d+)\)", text, re.I)
        if m:
            return int(m.group(1))
    m = re.search(r"Available Games\s*\((\d+)\)", page.locator("body").inner_text(), re.I)
    return int(m.group(1)) if m else None


def available_heading(page):
    headings = page.locator("h2, h3")
    for i in range(headings.count()):
        h = headings.nth(i)
        if re.match(r"^Available Games\s*\(\d+\)", clean(h.inner_text()), re.I):
            return h
    return None


def best_available_table(page, heading):
    # Prefer the first table after the Available Games heading.
    if heading is not None:
        candidate = heading.locator("xpath=following::table[1]")
        if candidate.count():
            anchors = candidate.locator('a[href*="/game/"]')
            if anchors.count():
                return candidate

    # Fallback: choose the table containing the most game links.
    tables = page.locator("table")
    best = None
    best_count = 0
    for i in range(tables.count()):
        table = tables.nth(i)
        count = table.locator('a[href*="/game/"]').count()
        if count > best_count:
            best = table
            best_count = count
    return best


def collect_table_games(table, page_url: str) -> dict[str, dict]:
    games: dict[str, dict] = {}
    anchors = table.locator('a[href*="/game/"]')
    for i in range(anchors.count()):
        a = anchors.nth(i)
        href = urljoin(page_url, a.get_attribute("href") or "")
        name, year = clean_title(a.inner_text())
        if not href or "/game/" not in href or not name:
            continue
        item = games.setdefault(href, {"name": name, "url": href})
        if year:
            item["year"] = year
    return games


def collect_section_games(page, heading_name: str) -> set[str]:
    headings = page.locator("h2, h3")
    target = None
    for i in range(headings.count()):
        if clean(headings.nth(i).inner_text()).lower() == heading_name.lower():
            target = headings.nth(i)
            break
    if target is None:
        return set()

    # The service pages render these sections as cards/list items. Use the
    # nearest following container/table first, then a bounded DOM fallback.
    container = target.locator("xpath=following::*[self::div or self::section or self::ul or self::table][1]")
    if container.count():
        links = container.locator('a[href*="/game/"]')
        found = set()
        for i in range(links.count()):
            href = links.nth(i).get_attribute("href") or ""
            if "/game/" in href:
                found.add(urljoin(page.url, href))
        if found:
            return found

    # Safe fallback: inspect anchors between this heading and the next h2/h3
    # using browser element positions; no page.evaluate() is required.
    box = target.bounding_box()
    if not box:
        return set()
    y0 = box["y"]
    next_y = float("inf")
    for i in range(headings.count()):
        h = headings.nth(i)
        try:
            hb = h.bounding_box()
        except Exception:
            hb = None
        if hb and hb["y"] > y0 + 1:
            next_y = min(next_y, hb["y"])
    found = set()
    links = page.locator('a[href*="/game/"]')
    for i in range(links.count()):
        a = links.nth(i)
        try:
            ab = a.bounding_box()
        except Exception:
            ab = None
        if not ab or not (y0 < ab["y"] < next_y):
            continue
        href = a.get_attribute("href") or ""
        if "/game/" in href:
            found.add(urljoin(page.url, href))
    return found


def click_full_list(page) -> bool:
    locators = [
        page.get_by_text("Load Full Games List", exact=True),
        page.locator("button", has_text=re.compile(r"Load Full Games List", re.I)),
        page.locator("a", has_text=re.compile(r"Load Full Games List", re.I)),
    ]
    for locator in locators:
        if not locator.count():
            continue
        try:
            locator.first.scroll_into_view_if_needed(timeout=5000)
            locator.first.click(timeout=10000, force=True)
            return True
        except Exception:
            continue
    return False


def extract_available_games(page, expected: int) -> dict[str, dict]:
    heading = available_heading(page)
    if heading is None:
        raise RuntimeError("Available Games section not found")

    last_count = -1
    for attempt in range(12):
        table = best_available_table(page, heading)
        games = collect_table_games(table, page.url) if table is not None else {}
        count = len(games)
        print(f"  available rows: {count}/{expected}")
        if count == expected:
            return games
        if count == last_count and attempt >= 2:
            # Continue trying the full-list control; some pages need a second
            # click after their client-side table refresh.
            pass
        last_count = count
        if not click_full_list(page):
            page.wait_for_timeout(1500)
        else:
            page.wait_for_timeout(1800)

    raise RuntimeError(
        f"Available Games mismatch: extracted {last_count}, source says {expected}. "
        "Nothing will be published."
    )


def fetch(url: str) -> str:
    response = SESSION.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def enrich(game: dict) -> None:
    try:
        soup = BeautifulSoup(fetch(game["url"]), "html.parser")
        h1 = soup.find("h1")
        if h1:
            name, year = clean_title(h1.get_text(" ", strip=True))
            if name:
                game["name"] = name
            if year:
                game["year"] = year

        img = soup.find("img", alt=re.compile(r"cover art", re.I))
        if img:
            src = img.get("src") or img.get("data-src")
            if src:
                game["cover_url"] = urljoin(game["url"], src)

        desc = soup.find(
            lambda tag: tag.name in {"h2", "h3"}
            and clean(tag.get_text(" ", strip=True)).lower() == "description"
        )
        if desc:
            paragraph = desc.find_next("p")
            if paragraph:
                game["description"] = clean(paragraph.get_text(" ", strip=True))
    except Exception as exc:
        game["enrich_error"] = str(exc)
    time.sleep(0.08)


def normalise(game: dict) -> dict:
    for key in ("plans", "new_plans", "leaving_plans"):
        game[key] = sorted(set(game.get(key, [])), key=PLAN_ORDER.index)
    plans = game["plans"]
    game["essential"] = "essential" in plans
    game["pc_game_pass"] = "pc" in plans
    game["premium"] = "premium" in plans
    game["ultimate"] = "ultimate" in plans
    game["new"] = bool(game["new_plans"])
    game["leaving"] = bool(game["leaving_plans"])
    return game


def main() -> None:
    merged: dict[str, dict] = {}
    service_counts: dict[str, int] = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 1200},
        )
        page = context.new_page()
        page.set_default_timeout(15000)

        for plan, url in SERVICES.items():
            print(f"Loading {plan}: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(1500)

            expected = expected_count(page)
            if expected is None:
                raise RuntimeError(f"{plan}: could not read Available Games count")

            games_by_url = extract_available_games(page, expected)
            new_links = collect_section_games(page, "New Releases")
            leaving_links = collect_section_games(page, "Leaving Soon")
            service_counts[plan] = expected

            for game in games_by_url.values():
                game.setdefault("plans", []).append(plan)
                if game["url"] in new_links:
                    game.setdefault("new_plans", []).append(plan)
                if game["url"] in leaving_links:
                    game.setdefault("leaving_plans", []).append(plan)
                current = merged.setdefault(game["url"], {"name": game["name"], "url": game["url"]})
                current.update({k: v for k, v in game.items() if k not in {"plans", "new_plans", "leaving_plans"}})
                for key in ("plans", "new_plans", "leaving_plans"):
                    current.setdefault(key, []).extend(game.get(key, []))

            print(f"OK {plan}: {len(games_by_url)} games")

        browser.close()

    games = [normalise(g) for g in merged.values()]

    # Final count guard BEFORE enrichment and publication.
    for plan, expected in service_counts.items():
        actual = sum(plan in g["plans"] for g in games)
        if actual != expected:
            raise RuntimeError(f"{plan}: merged plan count {actual} != source count {expected}")

    for i, game in enumerate(sorted(games, key=lambda x: x["name"].lower()), 1):
        print(f"[{i}/{len(games)}] {game['name']}")
        enrich(game)

    games.sort(key=lambda x: x["name"].lower())
    payload = {
        "source": "GameScriptions",
        "source_pages": SERVICES,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "service_counts": service_counts,
        "game_count_unique": len(games),
        "games": games,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(games)} unique games to {OUT}")
    print("Service counts:", service_counts)


if __name__ == "__main__":
    main()
