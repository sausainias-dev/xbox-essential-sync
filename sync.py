#!/usr/bin/env python3
"""Build a clean JSON catalog from GameScriptions' Xbox Game Pass Essential page."""
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

SOURCE = "https://gamescriptions.com/subscription/service/xbox_essential"
OUT = "xbox-essential.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SubliXboxCatalog/1.1; +https://github.com/)"
}


def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()


def clean_title(value):
    value = clean(value)

    match = re.match(
        r"^(.*?)\s*\(\s*(\d{4})\s*\)\s*$",
        value
    )

    if match:
        return clean(match.group(1)), int(match.group(2))

    return value, None


def get(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=25
    )
    response.raise_for_status()
    return response.text


def section_links(soup, heading_text):
    heading = None

    for tag in soup.find_all(["h2", "h3"]):
        text = clean(
            tag.get_text(" ", strip=True)
        ).lower()

        if text == heading_text.lower():
            heading = tag
            break

    if not heading:
        return []

    found = []

    for element in heading.find_all_next():
        if (
            isinstance(element, Tag)
            and element.name == "h2"
        ):
            break

        if (
            isinstance(element, Tag)
            and element.name == "a"
            and "/game/" in (element.get("href") or "")
        ):
            found.append(element)

    return found


def extract_games(source_html):
    soup = BeautifulSoup(
        source_html,
        "html.parser"
    )

    games = {}

    for a in soup.select('a[href*="/game/"]'):
        href = urljoin(
            SOURCE,
            a.get("href", "")
        )

        raw_name = clean(
            a.get_text(" ", strip=True)
        )

        if not raw_name:
            continue

        if "/game/" not in href:
            continue

        name, year = clean_title(raw_name)

        if href not in games:
            games[href] = {
                "name": name,
                "url": href
            }

            if year:
                games[href]["year"] = year

    # New Releases
    for a in section_links(
        soup,
        "New Releases"
    ):
        href = urljoin(
            SOURCE,
            a.get("href", "")
        )

        if href in games:
            games[href]["new"] = True

    # Leaving Soon
    for a in section_links(
        soup,
        "Leaving Soon"
    ):
        href = urljoin(
            SOURCE,
            a.get("href", "")
        )

        if href in games:
            games[href]["leaving"] = True

    return list(games.values())


def enrich(game):
    try:
        html = get(game["url"])

        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        h1 = soup.find("h1")

        if h1:
            name, year = clean_title(
                h1.get_text(
                    " ",
                    strip=True
                )
            )

            if name:
                game["name"] = name

            if year:
                game["year"] = year

        img = soup.find(
            "img",
            alt=re.compile(
                "cover art",
                re.I
            )
        )

        if img:
            src = (
                img.get("src")
                or img.get("data-src")
            )

            if src:
                game["cover_url"] = urljoin(
                    game["url"],
                    src
                )

        desc_heading = soup.find(
            lambda tag:
                tag.name in ["h2", "h3"]
                and clean(
                    tag.get_text(
                        " ",
                        strip=True
                    )
                ).lower() == "description"
        )

        if desc_heading:
            paragraph = desc_heading.find_next("p")

            if paragraph:
                game["description"] = clean(
                    paragraph.get_text(
                        " ",
                        strip=True
                    )
                )

    except Exception as exc:
        game["enrich_error"] = str(exc)

    time.sleep(0.15)

    return game


def main():
    source_html = get(SOURCE)

    games = extract_games(
        source_html
    )

    for index, game in enumerate(
        games,
        1
    ):
        print(
            f"[{index}/{len(games)}] "
            f"{game['name']}"
        )

        enrich(game)

    payload = {
        "source": SOURCE,
        "updated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "games": sorted(
            games,
            key=lambda item:
                item["name"].lower()
        )
    }

    with open(
        OUT,
        "w",
        encoding="utf-8"
    ) as handle:
        json.dump(
            payload,
            handle,
            ensure_ascii=False,
            indent=2
        )

    print(
        f"Wrote {len(games)} games "
        f"to {OUT}"
    )


if __name__ == "__main__":
    main()
