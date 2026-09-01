#!/usr/bin/env python3
"""
Build a JSON catalog from GameScriptions' public Game Pass Essential page.

This is intentionally a small, cacheable scraper. Review the source site's
terms/robots policy before deploying it publicly.
"""
import json, re, time
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

SOURCE = "https://gamescriptions.com/subscription/service/xbox_essential"
OUT = "xbox-essential.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SubliXboxCatalog/1.0; +https://github.com/)"
}

def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()

def get(url):
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    return r.text

def extract_games(source_html):
    soup = BeautifulSoup(source_html, "html.parser")
    games = {}

    # All /game/ links on the service page are the authoritative catalog links.
    for a in soup.select('a[href*="/game/"]'):
        href = urljoin(SOURCE, a.get("href", ""))
        name = clean(a.get_text(" ", strip=True))
        if not name or "/game/" not in href:
            continue
        games[href] = {"name": name, "url": href}

    # Mark new/leaving sections by walking from their headings until the next h2.
    def section_items(title):
        heading = None
        for h in soup.find_all(["h2", "h3"]):
            if clean(h.get_text(" ", strip=True)).lower() == title.lower():
                heading = h
                break
        if not heading:
            return []
        out = []
        node = heading.find_next_sibling()
        while node:
            if node.name == "h2":
                break
            for a in node.select('a[href*="/game/"]') if hasattr(node, "select") else []:
                href = urljoin(SOURCE, a.get("href", ""))
                name = clean(a.get_text(" ", strip=True))
                if href and name:
                    out.append((href, name, clean(node.get_text(" ", strip=True))))
            node = node.find_next_sibling()
        return out

    for href, name, text in section_items("New Releases"):
        if href in games:
            m = re.search(r"Added:\s*([^|]+)$", text, re.I)
            games[href]["added"] = clean(m.group(1)) if m else True

    for href, name, text in section_items("Leaving Soon"):
        if href in games:
            m = re.search(r"Leaves:\s*([^|]+)$", text, re.I)
            games[href]["leaves"] = clean(m.group(1)) if m else True

    return list(games.values())

def enrich(game):
    try:
        html = get(game["url"])
        soup = BeautifulSoup(html, "html.parser")
        h1 = soup.find("h1")
        if h1:
            title = clean(h1.get_text(" ", strip=True))
            m = re.match(r"^(.*?)(?:\s*\((\d{4})\))?$", title)
            if m:
                game["name"] = clean(m.group(1))
                if m.group(2):
                    game["year"] = int(m.group(2))

        # GameScriptions currently exposes IGDB cover art on each game page.
        img = soup.find("img", alt=re.compile("cover art", re.I))
        if img and img.get("src"):
            game["cover_url"] = urljoin(game["url"], img["src"])

        desc = soup.find(lambda tag: tag.name in ["h2","h3"] and clean(tag.get_text()) == "Description")
        if desc:
            p = desc.find_next("p")
            if p:
                game["description"] = clean(p.get_text(" ", strip=True))

    except Exception as exc:
        game["enrich_error"] = str(exc)

    time.sleep(0.15)
    return game

def main():
    source_html = get(SOURCE)
    games = extract_games(source_html)
    for i, game in enumerate(games, 1):
        print(f"[{i}/{len(games)}] {game['name']}")
        enrich(game)

    payload = {
        "source": SOURCE,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "games": sorted(games, key=lambda x: x["name"].lower()),
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(games)} games to {OUT}")

if __name__ == "__main__":
    main()
