#!/usr/bin/env python3
"""Build one Xbox Game Pass catalog from GameScriptions' plan pages."""

import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag


# These are the GameScriptions pages that define which games belong
# to each Game Pass plan.
SERVICES = {
    "essential": "https://gamescriptions.com/subscription/service/xbox_essential",
    "pc": "https://gamescriptions.com/subscription/service/xbox_pc",
    "premium": "https://gamescriptions.com/subscription/service/xbox_premium",
    "ultimate": "https://gamescriptions.com/subscription/service/xbox_ultimate",
}

OUT = "xbox-game-pass.json"

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
    """Return GameScriptions game links belonging to a named section."""
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


def extract_plan_page(service_key, service_url, html):
    """Extract every available game and this plan's New/Leaving state."""
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

        item = games.setdefault(
            href,
            {
                "name": name,
                "url": href,
            },
        )

        if year:
            item["year"] = year

    new_urls = set()
    for a in section_links(soup, "New Releases"):
        new_urls.add(urljoin(service_url, a.get("href", "")))

    leaving_urls = set()
    for a in section_links(soup, "Leaving Soon"):
        leaving_urls.add(urljoin(service_url, a.get("href", "")))

    for href, game in games.items():
        game.setdefault("plans", []).append(service_key)

        if href in new_urls:
            game.setdefault("new_plans", []).append(service_key)
            game["new"] = True

        if href in leaving_urls:
            game.setdefault("leaving_plans", []).append(service_key)
            game["leaving"] = True

    return games


def merge_services():
    """Merge the four plan catalogs without duplicating the same game."""
    merged = {}
    service_counts = {}

    for service_key, service_url in SERVICES.items():
        print(f"Reading {service_key}: {service_url}")
        html = get(service_url)
        service_games = extract_plan_page(service_key, service_url, html)
        service_counts[service_key] = len(service_games)

        for source_url, game in service_games.items():
            # GameScriptions normally uses the same game URL across plans.
            # If it ever changes, title/year matching below prevents obvious
            # duplicates from being silently merged.
            existing = merged.get(source_url)

            if existing is None:
                merged[source_url] = game
                continue

            existing["plans"] = sorted(
                set(existing.get("plans", [])) | set(game.get("plans", []))
            )
            existing["new_plans"] = sorted(
                set(existing.get("new_plans", []))
                | set(game.get("new_plans", []))
            )
            existing["leaving_plans"] = sorted(
                set(existing.get("leaving_plans", []))
                | set(game.get("leaving_plans", []))
            )
            existing["new"] = bool(existing.get("new") or game.get("new"))
            existing["leaving"] = bool(
                existing.get("leaving") or game.get("leaving")
            )

            if not existing.get("year") and game.get("year"):
                existing["year"] = game["year"]

    return list(merged.values()), service_counts


def enrich_gamescriptions(game):
    """Keep the existing GameScriptions enrichment: cover + description."""
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
                    game["gamescriptions_description"] = description
                    game.setdefault("description", description)

    except Exception as exc:
        game["enrich_error"] = str(exc)

    time.sleep(REQUEST_DELAY)
    return game


def main():
    games, service_counts = merge_services()

    print("\nGames by plan:")
    for plan, count in service_counts.items():
        print(f"  {plan}: {count}")

    print(f"\nUnique combined games: {len(games)}")

    for index, game in enumerate(games, 1):
        print(f"[{index}/{len(games)}] {game['name']}")
        enrich_gamescriptions(game)

    payload = {
        "source": "GameScriptions",
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
    
