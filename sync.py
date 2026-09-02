#!/usr/bin/env python3
"""
Build the complete Xbox Game Pass catalog used by Subli.one.

Why this version uses Playwright:
GameScriptions renders only the first part of the "Available Games" table in
the initial HTML and exposes a "Load Full Games List" button. A plain
requests/BeautifulSoup scrape therefore publishes a partial catalog.

This script:
- loads all four Game Pass service pages in a real Chromium browser;
- clicks "Load Full Games List" and verifies the full row count;
- merges the four catalogs by GameScriptions game URL;
- records plan membership separately (essential / pc / premium / ultimate);
- marks New Releases and Leaving Soon per plan;
- enriches games with year/cover/description when available;
- refuses to write a partial catalog when a service is not fully loaded.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

OUT = Path("xbox-essential.json")
USER_AGENT = "Mozilla/5.0 (compatible; SubliXboxCatalog/2.0; +https://github.com/)"

SERVICES = {
    "essential": "https://gamescriptions.com/subscription/service/xbox_essential",
    "pc": "https://gamescriptions.com/subscription/service/xbox_pc",
    "premium": "https://gamescriptions.com/subscription/service/xbox_premium",
    "ultimate": "https://gamescriptions.com/subscription/service/xbox_ultimate",
}

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
    # Prefer the explicit "Available Games (N)" heading.
    for heading in page.locator("h2, h3").all():
        text = clean(heading.inner_text())
        match = re.search(r"Available Games\s*\((\d+)\)", text, re.I)
        if match:
            return int(match.group(1))
    # Fallback for markup where the count is not inside the heading.
    match = re.search(r"Available Games\s*\((\d+)\)", page.locator("body").inner_text(), re.I)
    return int(match.group(1)) if match else None


def find_available_section(page):
    """Return the DOM container belonging to the exact Available Games section."""
    headings = page.locator("h2, h3")
    for i in range(headings.count()):
        heading = headings.nth(i)
        text = clean(heading.inner_text())
        if re.match(r"^Available Games\s*\(\d+\)", text, re.I):
            # Walk forward in DOM order until the next h2/h3. This avoids
            # accidentally scraping New Releases / Coming Soon / Leaving Soon.
            return heading
    return None


def extract_available_games(page, expected: int) -> dict[str, dict]:
    heading = find_available_section(page)
    if not heading:
        raise RuntimeError("Available Games section not found")

    # Extract only anchors that live between the Available Games heading and
    # the next h2/h3. Deduplicate by canonical GameScriptions URL.
    hrefs = heading.evaluate(
        """(h) => {
            if (!h) return [];
            const out = [];
            let el = h.nextElementSibling;
            while (el && !el.matches('h2,h3')) {
                for (const a of el.querySelectorAll('a[href*=\"/game/\"]')) {
                    out.push({href: a.href, text: a.textContent});
                }
                if (el.matches('a[href*=\"/game/\"]')) {
                    out.push({href: el.href, text: el.textContent});
                }
                el = el.nextElementSibling;
            }
            return out;
        }"""
    )
    games = {}
    for item in hrefs or []:
        href = urljoin(page.url, item.get("href") or "")
        if "/game/" not in href:
            continue
        name, year = clean_title(clean(item.get("text") or ""))
        if not name:
            continue
        games.setdefault(href, {"name": name, "url": href})
        if year:
            games[href]["year"] = year

    actual = len(games)
    if actual != expected:
        raise RuntimeError(
            f"Available Games mismatch: extracted {actual}, source says {expected}. "
            "Nothing will be published."
        )
    return games


def extract_section_links(page, heading_name: str) -> set[str]:
    links: set[str] = set()
    headings = page.locator("h2, h3")
    for i in range(headings.count()):
        heading = headings.nth(i)
        if clean(heading.inner_text()).lower() != heading_name.lower():
            continue
        # Stop at the next h2/h3. The section normally contains game cards.
        node = heading.locator("xpath=following::*[self::h2 or self::h3][1]")
        boundary = node.first if node.count() else None
        # Use DOM JS to collect anchors between this heading and the next heading.
        found = page.evaluate(
            """({headingName}) => {
                const heads = [...document.querySelectorAll('h2,h3')];
                const h = heads.find(x => x.textContent.trim().toLowerCase() === headingName.toLowerCase());
                if (!h) return [];
                const out = [];
                for (let el = h.nextElementSibling; el; el = el.nextElementSibling) {
                    if (el.matches('h2,h3')) break;
                    for (const a of el.querySelectorAll('a[href*="/game/"]')) out.push(a.href);
                    if (el.matches('a[href*="/game/"]')) out.push(el.href);
                }
                return out;
            }""",
            {"headingName": heading_name},
        )
        for href in found or []:
            links.add(href)
        break
    return links


def scrape_service(page, plan: str, url: str) -> tuple[list[dict], set[str], set[str], int]:
    print(f"Loading {plan}: {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(1200)

    expected = expected_count(page)
    if expected is None:
        raise RuntimeError(f"{plan}: could not read Available Games count")

    # GameScriptions intentionally lazy-loads the full Available Games section.
    for attempt in range(10):
        try:
            games_by_url = extract_available_games(page, expected)
            break
        except RuntimeError as exc:
            button = page.locator("button", has_text=re.compile(r"Load Full Games List", re.I))
            if not button.count():
                button = page.locator("a", has_text=re.compile(r"Load Full Games List", re.I))
            if not button.count():
                if attempt == 9:
                    raise
                page.wait_for_timeout(1000)
                continue
            print(f"  full-list click {attempt + 1}")
            try:
                button.first.click(timeout=10_000)
            except Exception:
                page.evaluate(
                    """() => {
                        const el = [...document.querySelectorAll('button,a')]
                          .find(x => /Load Full Games List/i.test(x.textContent || ''));
                        if (el) el.click();
                    }"""
                )
            page.wait_for_timeout(1500)
    else:
        raise RuntimeError(f"{plan}: unable to extract exact catalog")

    actual = len(games_by_url)

    new_links = extract_section_links(page, "New Releases")
    leaving_links = extract_section_links(page, "Leaving Soon")

    for game in games_by_url.values():
        game.setdefault("plans", []).append(plan)
        if game["url"] in new_links:
            game.setdefault("new_plans", []).append(plan)
        if game["url"] in leaving_links:
            game.setdefault("leaving_plans", []).append(plan)

    print(f"  OK {plan}: {actual} games")
    return list(games_by_url.values()), new_links, leaving_links, expected


def fetch(url: str) -> str:
    response = SESSION.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def enrich(game: dict) -> None:
    try:
        html = fetch(game["url"])
        soup = BeautifulSoup(html, "html.parser")

        h1 = soup.find("h1")
        if h1:
            name, year = clean_title(h1.get_text(" ", strip=True))
            if name:
                game["name"] = name
            if year:
                game["year"] = year

        # Prefer an actual cover image, not a logo/icon.
        img = soup.find("img", alt=re.compile(r"cover art", re.I))
        if img:
            src = img.get("src") or img.get("data-src")
            if src:
                game["cover_url"] = urljoin(game["url"], src)

        desc_heading = soup.find(
            lambda tag: tag.name in {"h2", "h3"}
            and clean(tag.get_text(" ", strip=True)).lower() == "description"
        )
        if desc_heading:
            paragraph = desc_heading.find_next("p")
            if paragraph:
                game["description"] = clean(paragraph.get_text(" ", strip=True))
    except Exception as exc:
        # Metadata enrichment is best-effort; the catalog itself remains valid.
        game["enrich_error"] = str(exc)
    time.sleep(0.08)


def normalise(game: dict) -> dict:
    plans = sorted(set(game.get("plans", [])), key=("essential", "pc", "premium", "ultimate").index)
    new_plans = sorted(set(game.get("new_plans", [])), key=("essential", "pc", "premium", "ultimate").index)
    leaving_plans = sorted(set(game.get("leaving_plans", [])), key=("essential", "pc", "premium", "ultimate").index)
    game["plans"] = plans
    game["new_plans"] = new_plans
    game["leaving_plans"] = leaving_plans
    game["essential"] = "essential" in plans
    game["pc_game_pass"] = "pc" in plans
    game["premium"] = "premium" in plans
    game["ultimate"] = "ultimate" in plans
    game["new"] = bool(new_plans)
    game["leaving"] = bool(leaving_plans)
    return game


def main() -> None:
    merged: dict[str, dict] = {}
    service_counts: dict[str, int] = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT, viewport={"width": 1440, "height": 1000})
        page = context.new_page()

        for plan, url in SERVICES.items():
            games, _, _, expected = scrape_service(page, plan, url)
            service_counts[plan] = expected

            for game in games:
                current = merged.setdefault(game["url"], {"name": game["name"], "url": game["url"]})
                current.update({k: v for k, v in game.items() if k not in {"plans", "new_plans", "leaving_plans"}})
                for key in ("plans", "new_plans", "leaving_plans"):
                    current.setdefault(key, [])
                    current[key].extend(game.get(key, []))

        browser.close()

    games = [normalise(g) for g in merged.values()]

    # Only enrich once per unique GameScriptions URL.
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

    # Final sanity check: every service count must be represented exactly.
    for plan, expected in service_counts.items():
        actual = sum(plan in item["plans"] for item in games)
        if actual != expected:
            raise RuntimeError(f"{plan}: merged plan count {actual} != source count {expected}")

    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(games)} unique games to {OUT}")
    print("Service counts:", service_counts)


if __name__ == "__main__":
    main()
