#!/usr/bin/env python3
"""Build the combined Xbox Game Pass catalog for Subli.one.

The plan membership is taken from GameScriptions' individual service pages.
The same game is merged into one JSON record, with all plans stored in
`plans`. New/Leaving status is also tracked per plan.

The output filename stays `xbox-essential.json` so the existing GitHub Pages
URL and SellAuth integration do not have to change.
"""

import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag


SERVICES = {
    "essential": "https://gamescriptions.com/subscription/service/xbox_essential",
    "pc": "https://gamescriptions.com/subscription/service/xbox_pc",
    "premium": "https://gamescriptions.com/subscription/service/xbox_premium",
    "ultimate": "https://gamescriptions.com/subscription/service/xbox_ultimate",
}

OUT = "xbox-essential.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_DELAY = 0.25


def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()


def clean_title(value):
    value = clean(value)
    match = re.match(r"^(.*?)\s*\(\s*(\d{4})\s*\)\s*$", value)
    if match:
        return clean(match.group(1)), int(match.group(2))
    return value, None


def get(url, timeout=25):
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.text


def section_links(soup, heading_text):
    heading = None

    for tag in soup.find_all(["h2", "h3"]):
        if clean(tag.get_text(" ", strip=True)).lower() == heading_text.lower():
            heading = tag
            break

    if not heading:
        return []

    found = []

    for element in heading.find_all_next():
        if isinstance(element, Tag) and element.name == "h2":
            break

        if (
            isinstance(element, Tag)
            and element.name == "a"
            and "/game/" in (element.get("href") or "")
        ):
            found.append(element)

    return found


def extract_service_games(service_key, service_url, html):
    """Extract all games belonging to one GameScriptions service."""
    soup = BeautifulSoup(html, "html.parser")
    games = {}

    for a in soup.select('a[href*="/game/"]'):
        href = urljoin(service_url, a.get("href", ""))
        if "/game/" not in href:
            continue

        raw_name = clean(a.get_text(" ", strip=True))
        if not raw_name:
            continue

        name, year = clean_title(raw_name)

        game = games.setdefault(
            href,
            {
                "name": name,
                "url": href,
                "plans": [],
                "new_plans": [],
                "leaving_plans": [],
            },
        )

        if year:
            game["year"] = year

    new_urls = {
        urljoin(service_url, a.get("href", ""))
        for a in section_links(soup, "New Releases")
    }

    leaving_urls = {
        urljoin(service_url, a.get("href", ""))
        for a in section_links(soup, "Leaving Soon")
    }

    for href, game in games.items():
        if service_key not in game["plans"]:
            game["plans"].append(service_key)

        if href in new_urls and service_key not in game["new_plans"]:
            game["new_plans"].append(service_key)

        if href in leaving_urls and service_key not in game["leaving_plans"]:
            game["leaving_plans"].append(service_key)

    return games


def merge_plan_catalogs():
    """Read all four plan pages and merge duplicate game records."""
    merged = {}
    service_counts = {}

    for plan, url in SERVICES.items():
        print(f"\nReading {plan}: {url}")
        html = get(url)
        found = extract_service_games(plan, url, html)
        service_counts[plan] = len(found)
        print(f"Found {len(found)} games in {plan}")

        for source_url, incoming in found.items():
            if source_url not in merged:
                merged[source_url] = incoming
                continue

            existing = merged[source_url]

            for field in ("plans", "new_plans", "leaving_plans"):
                existing[field] = sorted(
                    set(existing.get(field, []))
                    | set(incoming.get(field, []))
                )

            if not existing.get("year") and incoming.get("year"):
                existing["year"] = incoming["year"]

    return list(merged.values()), service_counts


def enrich_from_gamescriptions(game):
    """Keep the existing cover/title/year/description enrichment."""
    try:
        html = get(game["url"])
        soup = BeautifulSoup(html, "html.parser")

        h1 = soup.find("h1")
        if h1:
            name, year = clean_title(h1.get_text(" ", strip=True))
            if name:
                game["name"] = name
            if year:
                game["year"] = year

        img = soup.find(
            "img",
            alt=re.compile("cover art", re.I),
        )
        if img:
            src = img.get("src") or img.get("data-src")
            if src:
                game["cover_url"] = urljoin(game["url"], src)

        desc_heading = soup.find(
            lambda tag:
            tag.name in ["h2", "h3"]
            and clean(tag.get_text(" ", strip=True)).lower() == "description"
        )

        if desc_heading:
            paragraph = desc_heading.find_next("p")
            if paragraph:
                description = clean(
                    paragraph.get_text(" ", strip=True)
                )
                if description:
                    game["description"] = description

    except Exception as exc:
        game["enrich_error"] = str(exc)

    time.sleep(REQUEST_DELAY)
    return game


def add_compatibility_flags(game):
    """Add convenient booleans without changing plan membership semantics."""
    plans = set(game.get("plans", []))

    # These are intentionally derived from the actual plan list.
    game["essential"] = "essential" in plans
    game["pc_game_pass"] = "pc" in plans
    game["premium"] = "premium" in plans
    game["ultimate"] = "ultimate" in plans

    # Overall status is true if the game is new/leaving in at least one plan.
    game["new"] = bool(game.get("new_plans"))
    game["leaving"] = bool(game.get("leaving_plans"))

    return game


def main():
    games, service_counts = merge_plan_catalogs()

    print("\nUnique games across all plans:", len(games))

    for index, game in enumerate(games, 1):
        print(f"[{index}/{len(games)}] {game['name']}")
        enrich_from_gamescriptions(game)
        add_compatibility_flags(game)

    payload = {
        "source": "GameScriptions",
        "catalog_type": "xbox_game_pass",
        "services": SERVICES,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "service_counts": service_counts,
        "games": sorted(
            games,
            key=lambda item: item["name"].lower(),
        ),
    }

    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(
            payload,
            handle,
            ensure_ascii=False,
            indent=2,
        )

    print(f"\nWrote {len(games)} unique games to {OUT}")


if __name__ == "__main__":
    main()
    
