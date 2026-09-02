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
from urllib.parse import quote_plus, urljoin, urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup, Tag


SERVICES = {
    "essential": "https://gamescriptions.com/subscription/service/xbox_essential",
    "pc": "https://gamescriptions.com/subscription/service/xbox_pc",
    "premium": "https://gamescriptions.com/subscription/service/xbox_premium",
    "ultimate": "https://gamescriptions.com/subscription/service/xbox_ultimate",
}

OUT = "xbox-essential.json"
XBOX_CACHE_FILE = "xbox-metadata-cache.json"

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



# ---------------------------------------------------------------------------
# Official Xbox metadata enrichment
# ---------------------------------------------------------------------------

XBOX_SEARCH_PROVIDERS = (
    "https://www.google.com/search?q={query}&num=8",
    "https://www.bing.com/search?q={query}&count=8",
)

XBOX_DELAY = 0.5


def normalize_xbox_url(url):
    if not url:
        return None

    url = url.replace("&amp;", "&").strip()

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None

    host = parsed.netloc.lower()
    if host not in {"xbox.com", "www.xbox.com"}:
        return None

    if "/games/" not in parsed.path.lower():
        return None

    # Remove search/tracking parameters. Keep the actual store/detail path.
    return f"https://www.xbox.com{parsed.path.rstrip('/')}"


def unwrap_search_result(url):
    """Unwrap common search-engine redirect URLs."""
    if not url:
        return None

    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    for key in ("q", "url", "u"):
        if key in params and params[key]:
            candidate = unquote(params[key][0])
            normalized = normalize_xbox_url(candidate)
            if normalized:
                return normalized

    return normalize_xbox_url(url)


def xbox_search_candidates(name, year=None):
    """Find official Xbox pages without trusting arbitrary third-party URLs."""
    queries = []

    if year:
        queries.append(
            f'site:xbox.com/en-US/games/store "{name}" "{year}"'
        )

    queries.append(
        f'site:xbox.com/en-US/games/store "{name}"'
    )
    queries.append(
        f'site:xbox.com/en-us/games/store "{name}"'
    )

    found = []
    seen = set()

    for query in queries:
        encoded = quote_plus(query)

        for template in XBOX_SEARCH_PROVIDERS:
            url = template.format(query=encoded)

            try:
                html = get(url, timeout=20)
            except Exception:
                continue

            soup = BeautifulSoup(html, "html.parser")

            # Search engines expose result URLs through <a href>.
            for a in soup.find_all("a", href=True):
                candidate = unwrap_search_result(a.get("href"))
                if not candidate:
                    continue

                if candidate not in seen:
                    seen.add(candidate)
                    found.append(candidate)

            time.sleep(XBOX_DELAY)

            # One provider is usually enough; keep the fallback for failures.
            if found:
                break

        if len(found) >= 8:
            break

    return found[:12]


def visible_text(soup):
    return clean(soup.get_text(" ", strip=True))


def extract_meta_description(soup):
    for attrs in (
        {"property": "og:description"},
        {"name": "description"},
    ):
        meta = soup.find("meta", attrs=attrs)
        if meta and meta.get("content"):
            return clean(meta["content"])
    return None


def extract_jsonld_objects(soup):
    objects = []

    for script in soup.find_all(
        "script",
        attrs={"type": re.compile(r"application/ld\+json", re.I)},
    ):
        raw = script.string or script.get_text()
        raw = raw.strip()

        if not raw:
            continue

        try:
            data = json.loads(raw)
        except Exception:
            continue

        if isinstance(data, list):
            objects.extend(data)
        else:
            objects.append(data)

    return objects


def find_jsonld_game(soup):
    for obj in extract_jsonld_objects(soup):
        if not isinstance(obj, dict):
            continue

        obj_type = obj.get("@type")
        types = obj_type if isinstance(obj_type, list) else [obj_type]

        if any(
            str(item).lower() in {"videojuego", "video game", "product"}
            for item in types
        ):
            return obj

    return None


def extract_xbox_description(soup):
    """Prefer Xbox's real Description block, then metadata/JSON-LD."""
    for heading in soup.find_all(["h2", "h3", "h4"]):
        if clean(heading.get_text(" ", strip=True)).lower() != "description":
            continue

        # Take the first meaningful paragraph before another major heading.
        for element in heading.find_all_next():
            if isinstance(element, Tag) and element.name in {"h2", "h3"}:
                break

            if isinstance(element, Tag) and element.name == "p":
                text = clean(element.get_text(" ", strip=True))
                if text:
                    return text

    obj = find_jsonld_game(soup)
    if isinstance(obj, dict):
        description = clean(obj.get("description"))
        if description:
            return description

    return extract_meta_description(soup)


def extract_after_label(soup, label):
    """Extract the value following an exact Xbox detail label."""
    wanted = label.lower()

    for tag in soup.find_all(["span", "div", "dt", "th", "p", "strong"]):
        text = clean(tag.get_text(" ", strip=True))
        if text.lower() != wanted:
            continue

        # Definition-list / table layouts.
        sibling = tag.find_next_sibling()
        if sibling:
            value = clean(sibling.get_text(" ", strip=True))
            if value and value.lower() != wanted:
                return value

        # Typical Xbox card layout: label and value share a parent.
        parent = tag.parent
        if parent:
            children = [
                clean(child.get_text(" ", strip=True))
                for child in parent.find_all(
                    ["span", "div", "a", "p"],
                    recursive=True,
                )
            ]
            children = [x for x in children if x and x.lower() != wanted]
            if children:
                return children[-1]

        # Text-node fallback: inspect nearby text.
        parent_text = clean(parent.get_text(" ", strip=True)) if parent else ""
        if parent_text and parent_text.lower() != wanted:
            value = re.sub(
                rf"^{re.escape(label)}\s*",
                "",
                parent_text,
                flags=re.I,
            ).strip()
            if value:
                return value

    return None


def extract_xbox_genre(soup):
    # Xbox store pages commonly expose "Publisher•Genre" near the H1.
    h1 = soup.find("h1")
    if h1:
        for element in h1.find_all_next(
            ["p", "div", "span"],
            limit=30,
        ):
            text = clean(element.get_text(" ", strip=True))
            if "•" not in text:
                continue

            parts = [
                clean(part)
                for part in text.split("•")
                if clean(part)
            ]

            if len(parts) >= 2:
                # Avoid accidentally treating a sale/payment string as genre.
                genre = parts[-1]
                if len(genre) <= 80 and not genre.startswith("$"):
                    return genre

    # Explicit Genre heading fallback.
    for heading in soup.find_all(["h2", "h3", "h4"]):
        if clean(heading.get_text(" ", strip=True)).lower() != "genre":
            continue

        value = heading.find_next(["p", "div", "span", "a"])
        if value:
            text = clean(value.get_text(" ", strip=True))
            if text and text.lower() != "genre":
                return text

    return None


def extract_xbox_platforms(soup):
    allowed = {
        "XBOX One",
        "XBOX Series X|S",
        "PC",
        "Windows 10/11",
        "Windows 10",
        "Windows 11",
        "Handheld",
        "Xbox One",
        "Xbox Series X|S",
    }

    platforms = []

    for heading in soup.find_all(["h2", "h3", "h4"]):
        title = clean(heading.get_text(" ", strip=True)).lower()
        if title not in {"play with", "platforms"}:
            continue

        for element in heading.find_all_next():
            if isinstance(element, Tag) and element.name in {"h2", "h3"}:
                break

            if not isinstance(element, Tag):
                continue

            text = clean(element.get_text(" ", strip=True))
            if text in allowed and text not in platforms:
                platforms.append(text)

        if platforms:
            break

    # Normalize spelling while preserving useful Xbox wording.
    normalized = []
    for platform in platforms:
        if platform in {"Xbox One", "XBOX One"}:
            value = "Xbox One"
        elif platform in {"Xbox Series X|S", "XBOX Series X|S"}:
            value = "Xbox Series X|S"
        elif platform in {"Windows 10/11", "Windows 10", "Windows 11"}:
            value = "PC"
        else:
            value = platform

        if value not in normalized:
            normalized.append(value)

    return normalized


def extract_xbox_capabilities(soup):
    capabilities = []

    for heading in soup.find_all(["h2", "h3", "h4"]):
        if clean(heading.get_text(" ", strip=True)).lower() != "capabilities":
            continue

        for element in heading.find_all_next():
            if isinstance(element, Tag) and element.name in {"h2", "h3"}:
                break

            if not isinstance(element, Tag):
                continue

            text = clean(element.get_text(" ", strip=True))
            if text and text in {
                "Xbox Play Anywhere",
                "Xbox One X Enhanced",
                "Handheld Optimized",
                "Xbox presence",
                "Xbox clubs",
            }:
                if text not in capabilities:
                    capabilities.append(text)

        break

    return capabilities


def extract_xbox_trailer(soup, html):
    """Only return a trailer if a public video URL is actually exposed."""
    # OpenGraph video metadata.
    for meta in soup.find_all(
        "meta",
        attrs={"property": re.compile(r"^og:video", re.I)},
    ):
        value = clean(meta.get("content"))
        if value.startswith(("https://", "http://")):
            return value

    # JSON-LD video objects.
    for obj in extract_jsonld_objects(soup):
        if not isinstance(obj, dict):
            continue

        items = []
        if obj.get("@type") == "VideoObject":
            items.append(obj)

        if isinstance(obj.get("video"), dict):
            items.append(obj["video"])

        for item in items:
            for key in ("contentUrl", "embedUrl", "url"):
                value = clean(item.get(key))
                if value.startswith(("https://", "http://")):
                    return value

    # Explicit HTML video/source tags.
    for tag in soup.find_all(["video", "source"]):
        for attr in ("src", "data-src"):
            value = clean(tag.get(attr))
            if value.startswith(("https://", "http://")):
                return value

    # Search page HTML for public YouTube links. Do not invent one.
    patterns = (
        r"https?://(?:www\.)?youtube\.com/watch\?v=[A-Za-z0-9_-]{6,}",
        r"https?://youtu\.be/[A-Za-z0-9_-]{6,}",
        r"https?:\\/\\/(?:www\.)?youtube\\.com\\/watch\?v=[A-Za-z0-9_-]{6,}",
        r"https?:\\/\\/youtu\\.be\\/[A-Za-z0-9_-]{6,}",
    )

    for pattern in patterns:
        match = re.search(pattern, html, re.I)
        if match:
            return match.group(0).replace("\\/", "/")

    return None


def xbox_page_score(soup, game):
    """Reject wrong editions/collections when a search result is ambiguous."""
    h1 = soup.find("h1")
    title = clean(h1.get_text(" ", strip=True)) if h1 else ""

    target = clean(game.get("name", "")).lower()
    candidate = clean_title(title)[0].lower()

    score = 0

    if candidate == target:
        score += 100
    elif target and (
        target in candidate
        or candidate in target
    ):
        score += 45

    if game.get("year") and str(game["year"]) in title:
        score += 20

    if extract_xbox_description(soup):
        score += 10

    if extract_after_label(soup, "Published by"):
        score += 5

    if extract_after_label(soup, "Developed by"):
        score += 5

    if extract_after_label(soup, "Release date"):
        score += 5

    return score


def enrich_from_xbox(game, xbox_cache):
    candidates = xbox_search_candidates(
        game["name"],
        game.get("year"),
    )

    best = None
    best_score = -1

    for candidate in candidates:
        if candidate in xbox_cache:
            html = xbox_cache[candidate]
        else:
            try:
                html = get(candidate)
            except Exception:
                continue

            xbox_cache[candidate] = html
            time.sleep(REQUEST_DELAY)

        soup = BeautifulSoup(html, "html.parser")
        score = xbox_page_score(soup, game)

        if score > best_score:
            best = (candidate, html, soup)
            best_score = score

    # A weak result is not safe enough to attach to a game.
    if not best or best_score < 80:
        return game

    xbox_url, html, soup = best

    game["xbox_url"] = xbox_url

    description = extract_xbox_description(soup)
    if description:
        game["description"] = description
        game["xbox_description"] = description

    publisher = extract_after_label(soup, "Published by")
    developer = extract_after_label(soup, "Developed by")
    release_date = extract_after_label(soup, "Release date")
    genre = extract_xbox_genre(soup)
    platforms = extract_xbox_platforms(soup)
    capabilities = extract_xbox_capabilities(soup)
    trailer = extract_xbox_trailer(soup, html)

    if publisher:
        game["publisher"] = publisher

    if developer:
        game["developer"] = developer

    if release_date:
        game["release_date"] = release_date

    if genre:
        game["genre"] = genre

    if platforms:
        game["platforms"] = platforms

    if capabilities:
        game["capabilities"] = capabilities

    if trailer:
        game["trailer_url"] = trailer

    return game


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
         
