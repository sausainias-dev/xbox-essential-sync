# Manual sync trigger: 2026-10-31
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
USER_AGENT = "Mozilla/5.0 (compatible; SubliXboxCatalog/5.2; +https://github.com/)"
SERVICES = {
    "essential": "https://gamescriptions.com/subscription/service/xbox_essential",
    "pc": "https://gamescriptions.com/subscription/service/xbox_pc",
    "premium": "https://gamescriptions.com/subscription/service/xbox_premium",
    "ultimate": "https://gamescriptions.com/subscription/service/xbox_ultimate",
    "ea_play": "https://gamescriptions.com/subscription/service/xbox_ea_play",
    "ubisoft_classics": "https://gamescriptions.com/subscription/service/xbox_ubisoft_classics",
}
PLAN_ORDER = ("essential", "pc", "premium", "ultimate", "ea_play", "ubisoft_classics")
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
        if hb and h.evaluate("(el) => el.tagName.toLowerCase()") == "h2" and hb["y"] > y0 + 1:
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


def collect_section_meta(page, heading_name: str) -> dict[str, str]:
    """Return game URL -> Added/Leaves label for a service section."""
    result: dict[str, str] = {}
    headings = page.locator("h2, h3")
    target = None
    for i in range(headings.count()):
        if clean(headings.nth(i).inner_text()).lower() == heading_name.lower():
            target = headings.nth(i)
            break
    if target is None:
        return result

    links = page.locator('a[href*="/game/"]')
    for i in range(links.count()):
        a = links.nth(i)
        try:
            ab = a.bounding_box()
            tb = target.bounding_box()
        except Exception:
            ab = tb = None
        if not ab or not tb or ab["y"] <= tb["y"]:
            continue
        # Stop once the next major heading is reached.
        next_heading_y = float("inf")
        for j in range(headings.count()):
            h = headings.nth(j)
            try:
                hb = h.bounding_box()
            except Exception:
                hb = None
            if hb and hb["y"] > tb["y"] + 1:
                next_heading_y = min(next_heading_y, hb["y"])
        if ab["y"] >= next_heading_y:
            continue
        href = a.get_attribute("href") or ""
        if "/game/" not in href:
            continue
        # Inspect the nearest compact card/list ancestor for the date text.
        node = a
        date_text = ""
        for _ in range(5):
            try:
                text = clean(node.inner_text(timeout=1000))
            except Exception:
                text = ""
            m = re.search(r"(?:Added|Leaves):\s*([^\n]+)", text, re.I)
            if m:
                date_text = clean(m.group(1))
                break
            try:
                node = node.locator("xpath=..")
            except Exception:
                break
        result[urljoin(page.url, href)] = date_text
    return result



def collect_service_section(page, heading_pattern: str) -> list[dict]:
    """Collect cards until the next major service section, allowing month/year subheadings."""
    headings = page.locator("h1, h2, h3, h4")
    target_index = None
    target_text = ""
    for i in range(headings.count()):
        heading = clean(headings.nth(i).inner_text())
        if re.search(heading_pattern, heading, re.I):
            target_index = i
            target_text = heading
            break
    if target_index is None:
        return []

    # Month headings (e.g. "November 2026", "TBD 2027") belong to Coming Soon.
    # Stop only at the next named catalogue section, not at every h2.
    if re.search(r"Coming\s+Soon", target_text, re.I):
        boundary = re.compile(r"^Available\s+Games\b", re.I)
    elif re.search(r"Leaving\s+Soon", target_text, re.I):
        boundary = re.compile(r"^(?:Coming\s+Soon|Available\s+Games)\b", re.I)
    else:
        boundary = re.compile(r"^(?:Leaving\s+Soon|Coming\s+Soon|Available\s+Games)\b", re.I)

    target = headings.nth(target_index)
    try:
        y0 = target.bounding_box()["y"]
    except Exception:
        return []
    next_y = float("inf")
    for i in range(target_index + 1, headings.count()):
        h = headings.nth(i)
        label = clean(h.inner_text())
        if boundary.search(label):
            try:
                box = h.bounding_box()
                if box:
                    next_y = box["y"]
            except Exception:
                pass
            break

    result: list[dict] = []
    seen: set[str] = set()
    links = page.locator('a[href*="/game/"]')
    for i in range(links.count()):
        anchor = links.nth(i)
        try:
            box = anchor.bounding_box()
        except Exception:
            box = None
        if not box or not (y0 < box["y"] < next_y):
            continue
        href = anchor.get_attribute("href") or ""
        full_url = urljoin(page.url, href)
        name, year = clean_title(anchor.inner_text())
        if not name or full_url in seen:
            continue
        seen.add(full_url)

        card_text = ""
        node = anchor
        for _ in range(5):
            try:
                candidate = clean(node.inner_text(timeout=1000))
            except Exception:
                candidate = ""
            if re.search(r"(?:Added|Leaves|Arrives):|\bTBD\b", candidate, re.I):
                card_text = candidate
                break
            try:
                node = node.locator("xpath=..")
            except Exception:
                break

        item = {"name": name, "url": full_url}
        if year:
            item["year"] = year
        date_match = re.search(r"(Arrives|Added|Leaves):\s*([^\n]+)", card_text, re.I)
        if date_match:
            item["date_label"] = clean(date_match.group(2))
            item["date_type"] = date_match.group(1).casefold()
        elif re.search(r"\bTBD\b", card_text, re.I):
            item["date_label"] = "TBD"
            item["date_type"] = "tbd"
        result.append(item)
    print(f"  section {target_text!r}: {len(result)} games")
    return result

def extract_service_page_data(page, plan: str, url: str, available_count: int) -> dict:
    """Capture the useful public content for a standalone subscription page."""
    soup = BeautifulSoup(page.content(), "html.parser")
    h1 = soup.find("h1")
    name = clean(h1.get_text(" ", strip=True)) if h1 else plan.replace("_", " ").title()

    description = ""
    if h1:
        for node in h1.find_all_next(["p"], limit=8):
            candidate = short_description(node.get_text(" ", strip=True))
            if candidate and len(candidate) > 35:
                description = candidate
                break

    genre_counts: dict[str, int] = {}
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        label = clean(anchor.get_text(" ", strip=True))
        if "/genre/" not in href and "genre" not in href.casefold():
            continue
        match = re.match(r"(.+?)\s+(\d+)$", label)
        if match:
            genre_counts[clean(match.group(1))] = int(match.group(2))

    return {
        "slug": plan,
        "name": name,
        "url": url,
        "description": description,
        "available_count": available_count,
        "genre_counts": dict(sorted(genre_counts.items(), key=lambda item: (-item[1], item[0].casefold()))),
        "new_releases": collect_service_section(page, r"^New Releases$"),
        "leaving_soon": collect_service_section(page, r"^Leaving Soon$"),
        "coming_soon": collect_service_section(page, r"^Coming Soon"),
    }


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


def short_description(text: str) -> str:
    text = clean(text)
    # Remove common UI/source boilerplate if it ever leaks into the description.
    text = re.sub(r"\s*(Read More|Game Trailer|Share Game)\s*$", "", text, flags=re.I)
    if not text:
        return ""
    # Keep a useful, compact 1–3 sentence description.
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chosen = " ".join(sentences[:3]).strip()
    if len(chosen) > 480:
        chosen = chosen[:477].rsplit(" ", 1)[0] + "..."
    return chosen


def section_values(soup: BeautifulSoup, *heading_names: str) -> list[str]:
    """Extract values following GameScriptions' inline metadata labels."""
    wanted = {clean(name).rstrip(":").casefold() for name in heading_names}
    labels = {"modes", "play modes", "genres", "themes", "platforms"}

    def add_from(container) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        candidates = list(container.find_all(["a", "button"]))
        candidates.extend(container.select("[role='listitem']"))
        for candidate in candidates:
            value = clean(candidate.get_text(" ", strip=True)).rstrip(":")
            key = value.casefold()
            if value and len(value) <= 80 and key not in seen and key not in labels:
                seen.add(key)
                values.append(value)
        return values

    # Current pages render these as inline labels, not necessarily headings.
    for text_node in soup.find_all(string=True):
        raw_text = clean(str(text_node))
        label = raw_text.rstrip(":").casefold()
        inline_match = re.match(
            r"^(Modes|Play Modes|Genres|Themes|Platforms)\s*:\s*(.+)$",
            raw_text, re.I
        )
        if label not in wanted and not (
            inline_match and inline_match.group(1).casefold() in wanted
        ):
            continue
        ancestor = text_node.parent
        for _ in range(5):
            if ancestor is None:
                break
            container_text = clean(ancestor.get_text(" ", strip=True))
            other_labels = re.findall(
                r"\b(?:Modes|Play Modes|Genres|Themes|Platforms)\s*:",
                container_text, re.I
            )
            if len(other_labels) <= 1:
                values = add_from(ancestor)
                if values:
                    return values
                remainder = re.sub(
                    r"^(?:Modes|Play Modes|Genres|Themes|Platforms)\s*:\s*",
                    "", container_text, flags=re.I
                ).strip()
                if remainder and len(remainder) <= 400:
                    return [remainder]
            ancestor = ancestor.parent

    # Compatibility fallback for older heading-based layouts.
    heading = soup.find(
        lambda tag: tag.name in {"h2", "h3", "h4"}
        and clean(tag.get_text(" ", strip=True)).rstrip(":").casefold() in wanted
    )
    if heading:
        values: list[str] = []
        seen: set[str] = set()
        node = heading
        for _ in range(8):
            node = node.find_next_sibling()
            if node is None or getattr(node, "name", None) in {"h1", "h2", "h3", "h4"}:
                break
            for value in add_from(node):
                if value.casefold() not in seen:
                    seen.add(value.casefold())
                    values.append(value)
        if values:
            return values
    return []


def extract_community_stats(body_text: str) -> dict:
    """Read public aggregate community rating and tracking counts, when present."""
    result: dict = {}
    section = re.search(
        r"\bCommunity(?:\s+Rating)?\b(.*?)(?=\bDescription\b)",
        body_text, re.I
    )
    if not section:
        return result
    text = section.group(1)
    rating = re.search(
        r"\b(\d+(?:\.\d+)?)\s+(.+?)\s+Based on\s+(\d+)\s+ratings?\b",
        text, re.I
    )
    if rating:
        result["community_rating"] = float(rating.group(1))
        result["community_sentiment"] = clean(rating.group(2))
        result["community_rating_count"] = int(rating.group(3))
    total = re.search(r"\b(\d+)\s+Total\b", text, re.I)
    if total:
        result["community_total"] = int(total.group(1))
    status_names = {
        "completed": "completed", "queued": "queued", "playing": "playing",
        "abandoned": "abandoned", "interested": "interested", "no interest": "no_interest",
    }
    statuses = {}
    for label, count in re.findall(
        r"\b(Completed|Queued|Playing|Abandoned|Interested|No Interest)\s+(\d+)\b",
        text, re.I
    ):
        statuses[status_names[label.casefold()]] = int(count)
    if statuses:
        result["community_status_counts"] = statuses
    return result


def extract_related_games(soup: BeautifulSoup, page_url: str) -> list[dict]:
    """Extract linked games from the Related Games section."""
    heading = soup.find(
        lambda tag: tag.name in {"h2", "h3", "h4"}
        and clean(tag.get_text(" ", strip=True)).casefold().startswith("related games")
    )
    if not heading:
        return []
    result: list[dict] = []
    seen: set[str] = set()
    node = heading
    for _ in range(12):
        node = node.find_next_sibling()
        if node is None or getattr(node, "name", None) in {"h1", "h2", "h3", "h4"}:
            break
        for anchor in node.select('a[href*="/game/"]'):
            url = urljoin(page_url, anchor.get("href", ""))
            name, year = clean_title(anchor.get_text(" ", strip=True))
            if not name or url in seen:
                continue
            seen.add(url)
            item = {"name": name, "url": url}
            if year:
                item["year"] = year
            result.append(item)
    return result[:30]



def xbox_pc_platforms(values: list[str]) -> list[str]:
    """Keep useful Xbox/Windows platform distinctions for the catalogue."""
    text = " ".join(values).casefold()
    result: list[str] = []
    if "series x" in text or "series s" in text or "series x|s" in text:
        result.append("Xbox Series X|S")
    if "xbox one" in text:
        result.append("Xbox One")
    if "windows" in text or re.search(r"\bpc\b", text):
        result.append("PC (Microsoft Windows)")
    # Older source pages sometimes expose only the generic Xbox label.
    if not result and "xbox" in text:
        result.append("Xbox")
    return list(dict.fromkeys(result))


def extract_game_media(soup: BeautifulSoup, page_url: str) -> tuple[list[str], str | None, str | None]:
    """Extract gallery screenshots, trailer and gameplay YouTube links."""
    screenshots: list[str] = []
    seen_images: set[str] = set()
    for img in soup.find_all("img"):
        alt = clean(img.get("alt", "")).casefold()
        classes = " ".join(img.get("class", [])).casefold()
        parent = img.find_parent("a")
        parent_classes = " ".join(parent.get("class", [])).casefold() if parent else ""
        context = " ".join((alt, classes, parent_classes))
        if not re.search(r"screenshot|gallery|featured", context):
            continue
        candidates = [
            parent.get("href") if parent else None,
            img.get("data-src"), img.get("data-lazy-src"), img.get("data-original"),
            img.get("src"),
        ]
        srcset = img.get("srcset") or img.get("data-srcset") or ""
        if srcset:
            candidates.extend(
                part.strip().split()[0] for part in srcset.split(",") if part.strip()
            )
        for raw in candidates:
            if not raw or raw.startswith("data:"):
                continue
            url = urljoin(page_url, raw)
            low = url.casefold()
            if not re.search(r"\.(?:jpe?g|png|webp)(?:[?#]|$)", low):
                continue
            if any(token in low for token in ("logo", "avatar", "icon", "flag", "cover_big")):
                continue
            if url not in seen_images:
                seen_images.add(url)
                screenshots.append(url)

    video_urls: dict[str, str] = {}
    url_patterns = [
        re.compile(
            r"(?:youtube(?:-nocookie)?\.com/(?:embed/|shorts/)|youtu\.be/|img\.youtube\.com/vi/)"
            r"([A-Za-z0-9_-]{6,})",
            re.I
        ),
        re.compile(
            r"youtube(?:-nocookie)?\.com/watch\?[^\s]*?v=([A-Za-z0-9_-]{6,})",
            re.I
        ),
    ]

    def find_video_id(value: str) -> str | None:
        for pattern in url_patterns:
            match = pattern.search(value)
            if match:
                return match.group(1)
        return None
    for tag in soup.find_all(["iframe", "a", "img", "source"]):
        attrs = " ".join(
            str(tag.get(key, "")) for key in
            ("src", "data-src", "href", "title", "alt", "class")
        )
        parent_text = clean(tag.parent.get_text(" ", strip=True)) if tag.parent else ""
        context = clean(attrs + " " + parent_text).casefold()
        video_id = find_video_id(attrs)
        if video_id:
            kind = "gameplay_url" if "gameplay" in context else "trailer_url"
            video_urls.setdefault(kind, f"https://www.youtube.com/watch?v={video_id}")

    # Some embeds are stored only in serialized scripts/data attributes.
    html = str(soup)
    for pattern in url_patterns:
        for match in pattern.finditer(html):
            nearby = html[max(0, match.start() - 180):match.end() + 180].casefold()
            kind = "gameplay_url" if "gameplay" in nearby else "trailer_url"
            video_urls.setdefault(kind, f"https://www.youtube.com/watch?v={match.group(1)}")
    return screenshots[:40], video_urls.get("trailer_url"), video_urls.get("gameplay_url")



def parse_release_date(text: str) -> str | None:
    m = re.search(r"Released:\s*([A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?[,]?\s+\d{4})", text, re.I)
    if m:
        return clean(m.group(1))
    return None


def enrich(game: dict) -> None:
    try:
        soup = BeautifulSoup(fetch(game["url"]), "html.parser")
        body_text = clean(soup.get_text(" ", strip=True))

        h1 = soup.find("h1")
        if h1:
            name, year = clean_title(h1.get_text(" ", strip=True))
            if name:
                game["name"] = name
            if year:
                game["year"] = year

        # Cover: prefer the explicit cover-art image.
        img = soup.find("img", alt=re.compile(r"cover art", re.I))
        if img:
            src = img.get("src") or img.get("data-src")
            if src:
                game["cover_url"] = urljoin(game["url"], src)

        # Gallery screenshots and official/embedded YouTube trailer.
        screenshots, trailer_url, gameplay_url = extract_game_media(soup, game["url"])
        if screenshots:
            game["screenshot_urls"] = screenshots
        if trailer_url:
            game["trailer_url"] = trailer_url
        if gameplay_url:
            game["gameplay_url"] = gameplay_url

        # Playtime estimate, e.g. "A Solid Adventure (10-19 Hours)".
        release_marker_for_time = re.search(r"Released:\s*", body_text, re.I)
        time_text = body_text[release_marker_for_time.end():] if release_marker_for_time else body_text
        playtime = re.search(
            r"(?P<label>[A-Z][A-Za-z'’& -]{2,55})\s*\(\s*"
            r"(?P<hours>\d+(?:\s*-\s*\d+)?\s*(?:Hours?|Minutes?))\s*\)",
            time_text
        )
        if playtime:
            game["playtime_category"] = clean(playtime.group("label"))
            game["playtime_hours"] = re.sub(r"\s+", " ", playtime.group("hours")).strip()

        chapters = re.search(r"Story & Campaign\s*\(\s*(\d+)\s+Chapters?\s*\)", body_text, re.I)
        if chapters:
            game["campaign_chapters"] = int(chapters.group(1))

        game.update(extract_community_stats(body_text))
        related_games = extract_related_games(soup, game["url"])
        if related_games:
            game["related_games"] = related_games

        release_date = parse_release_date(body_text)
        if release_date:
            game["release_date"] = release_date

        # Developer and publisher appear immediately before the release date.
        release_marker = re.search(r"Released:\s*", body_text, re.I)
        if release_marker:
            before = body_text[:release_marker.start()].strip()
            if game.get("name"):
                tail = before.rsplit(game["name"], 1)[-1].strip()
                tail = re.sub(r"^\s*\(\s*\d{4}\s*\)\s*", "", tail)
                tail = re.sub(r"^\s*Share Game\s*", "", tail, flags=re.I).strip()
                tail = tail.strip("·/ ")
                if tail and len(tail) <= 220:
                    parts = [clean(x) for x in re.split(r"\s*[·/]\s*", tail) if clean(x)]
                    if parts:
                        game["developer"] = parts[0]
                    if len(parts) > 1:
                        game["publisher"] = parts[1]

        # Description, limited to a short useful summary.
        desc_heading = soup.find(
            lambda tag: tag.name in {"h2", "h3"}
            and clean(tag.get_text(" ", strip=True)).lower() == "description"
        )
        if desc_heading:
            paragraph = desc_heading.find_next("p")
            if paragraph:
                desc = short_description(paragraph.get_text(" ", strip=True))
                if desc:
                    game["description"] = desc

        game["genres"] = section_values(soup, "Genres")
        game["game_modes"] = section_values(soup, "Modes", "Play Modes")
        game["game_style"] = section_values(soup, "Themes")
        raw_platforms = section_values(soup, "Platforms")
        game["platforms"] = xbox_pc_platforms(raw_platforms)

    except Exception as exc:
        game["enrich_error"] = str(exc)
    time.sleep(0.08)

def normalise(game: dict) -> dict:
    for key in ("plans", "new_plans", "leaving_plans"):
        game[key] = sorted(set(game.get(key, [])), key=PLAN_ORDER.index)
    for key in ("genres", "game_modes", "game_style", "platforms"):
        game[key] = list(dict.fromkeys(clean(v) for v in game.get(key, []) if clean(v)))
    game["plan_added_dates"] = {k: v for k, v in game.get("plan_added_dates", {}).items() if k in game["plans"] and v}
    game["leaving_dates"] = {k: v for k, v in game.get("leaving_dates", {}).items() if k in game["leaving_plans"] and v}
    plans = game["plans"]
    game["essential"] = "essential" in plans
    game["pc_game_pass"] = "pc" in plans
    game["premium"] = "premium" in plans
    game["ultimate"] = "ultimate" in plans
    game["ea_play"] = "ea_play" in plans
    game["ubisoft_classics"] = "ubisoft_classics" in plans
    game["new"] = bool(game["new_plans"])
    game["leaving"] = bool(game["leaving_plans"])
    return game


def render_upcoming_html(feed: dict) -> str:
    """Render a complete, self-contained HTML page with all game data embedded."""
    import html

    games = feed.get("games", [])
    def esc(value) -> str:
        return html.escape(str(value), quote=True)

    def format_arrival(value) -> str:
        raw = str(value or "").strip()
        if not raw or raw.upper() in {"TBD", "TBA", "DATE TBA"}:
            return "Date not announced"
        # Source values such as "Nov 2" have no year; never let browsers infer 2001.
        match = re.fullmatch(r"([A-Za-z]{3,9})\s+(\d{1,2})", raw)
        if match:
            try:
                month = datetime.strptime(match.group(1), "%b").month if len(match.group(1)) <= 3 else datetime.strptime(match.group(1), "%B").month
                now = datetime.now(timezone.utc)
                year = now.year
                candidate = datetime(year, month, int(match.group(2)), tzinfo=timezone.utc)
                if (candidate.date() - now.date()).days < -90:
                    year += 1
                return f"{match.group(1)} {int(match.group(2))}, {year}"
            except ValueError:
                pass
        return raw

    cards = []
    schema_items = []
    for index, game in enumerate(games, 1):
        name = esc(game.get("name", "Upcoming game"))
        year = esc(game.get("year", ""))
        description = esc(game.get("description", "Game details will be added soon."))
        release = esc(game.get("release_date", "TBA"))
        availability = esc(format_arrival(game.get("availability_date")))
        genres = game.get("genres", [])
        platforms = game.get("platforms", [])
        modes = game.get("game_modes", [])
        cover = game.get("cover_url", "")
        images = game.get("screenshot_urls", [])
        trailer = game.get("trailer_url") or game.get("gameplay_url")
        title = name + (f" ({year})" if year else "")
        tags = " ".join(esc(x) for x in genres)
        details = []
        if genres:
            details.append("<p><strong>Genres:</strong> " + ", ".join(esc(x) for x in genres) + "</p>")
        if platforms:
            details.append("<p><strong>Platforms:</strong> " + ", ".join(esc(x) for x in platforms) + "</p>")
        if modes:
            details.append("<p><strong>Game modes:</strong> " + ", ".join(esc(x) for x in modes) + "</p>")
        if game.get("developer"):
            details.append("<p><strong>Developer:</strong> " + esc(game["developer"]) + "</p>")
        if game.get("publisher"):
            details.append("<p><strong>Publisher:</strong> " + esc(game["publisher"]) + "</p>")
        media = ""
        if cover:
            media += f'<img class="cover" src="{esc(cover)}" alt="{name} cover art" loading="lazy">'
        if images:
            media += '<div class="gallery">' + "".join(
                f'<img src="{esc(src)}" alt="{name} screenshot {n}" loading="lazy">'
                for n, src in enumerate(images[:8], 1)
            ) + "</div>"
        if trailer:
            video_id = ""
            m = re.search(r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([A-Za-z0-9_-]{6,})", trailer)
            if m:
                video_id = m.group(1)
            if video_id:
                media += f'<div class="video"><iframe loading="lazy" src="https://www.youtube-nocookie.com/embed/{esc(video_id)}" title="{name} trailer" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen></iframe></div>'
            else:
                media += f'<p><a href="{esc(trailer)}" rel="noopener" target="_blank">Watch video</a></p>'
        cards.append(
            f'<article class="game-card" data-title="{name.lower()}" data-genres="{tags.lower()}">'
            f'<div class="game-media">{media}</div><div class="game-info">'
            f'<h2>{title}</h2><p>{description}</p>'
            f'<p><strong>Original release:</strong> {release}</p>'
            f'<p><strong>Expected Game Pass arrival:</strong> {availability}</p>'
            + "".join(details) + "</div></article>"
        )
        schema_items.append({
            "@type": "ListItem", "position": index,
            "item": {
                "@type": "VideoGame", "name": game.get("name", ""),
                "description": game.get("description", ""),
                "datePublished": game.get("release_date", None),
                "genre": genres,
                "image": ([cover] if cover else []) + images[:5],
                "gamePlatform": platforms,
            }
        })

    genres_all = sorted({g for game in games for g in game.get("genres", [])}, key=str.casefold)
    options = '<option value="">All genres</option>' + "".join(
        f'<option value="{esc(g.lower())}">{esc(g)}</option>' for g in genres_all
    )
    updated = esc(feed.get("updated_at", ""))
    schema = json.dumps({
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": "Upcoming Game Pass Games",
        "description": "Discover upcoming Xbox Game Pass games, release dates, trailers, screenshots, genres and platforms.",
        "mainEntity": {"@type": "ItemList", "numberOfItems": len(games), "itemListElement": schema_items}
    }, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Upcoming Game Pass Games | Subli.one</title>
<meta name="description" content="Explore upcoming Xbox Game Pass games, confirmed and expected arrival dates, trailers, screenshots, genres and platforms. Updated regularly on Subli.one.">
<link rel="canonical" href="https://subli.one/upcoming-game-pass-games">
<meta property="og:type" content="website"><meta property="og:title" content="Upcoming Game Pass Games | Subli.one">
<meta property="og:description" content="Discover upcoming Xbox Game Pass releases, dates, trailers and screenshots.">
<meta name="robots" content="index,follow">
<script type="application/ld+json">{schema}</script>
<style>
:root{{--bg:#0d1020;--panel:#171b2d;--text:#f5f6ff;--muted:#b9bfd4;--accent:#5865f2}}
*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(130deg,#29134b,#101b48);color:var(--text);font:16px/1.6 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1180px;margin:auto;padding:36px 20px 64px}}h1{{font-size:clamp(2rem,5vw,3.3rem);line-height:1.1;margin:0 0 16px}}h2{{font-size:1.45rem;margin:0 0 12px}}p{{margin:10px 0}}.intro,.toolbar,.game-card{{background:rgba(18,22,39,.88);border:1px solid #343b60;border-radius:18px;padding:22px;margin-bottom:20px}}.intro p,.muted{{color:var(--muted)}}.toolbar{{display:grid;grid-template-columns:2fr 1fr;gap:14px}}input,select{{width:100%;padding:14px 16px;border-radius:12px;border:1px solid #444b6d;background:#0d1120;color:white;font:inherit}}.count{{color:var(--muted);margin:14px 0}}.game-card{{display:grid;grid-template-columns:minmax(220px,34%) 1fr;gap:22px;overflow:hidden}}.cover{{display:block;width:100%;height:260px;object-fit:contain;object-position:center;background:#101525;border-radius:12px}}.gallery{{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:10px}}.gallery img{{width:100%;border-radius:8px}}.video{{position:relative;aspect-ratio:16/9;margin-top:12px}}.video iframe{{position:absolute;inset:0;width:100%;height:100%;border:0;border-radius:10px}}a{{color:#aab4ff}}footer{{color:var(--muted);font-size:.9rem;margin-top:28px}}@media(max-width:700px){{main{{padding:24px 14px}}.toolbar{{grid-template-columns:1fr}}.game-card{{grid-template-columns:1fr}}.cover{{height:230px;max-height:230px;object-fit:contain;object-position:center}}}}
</style></head>
<body><main>
<header class="intro"><h1>Upcoming Game Pass Games</h1>
<p>Track upcoming titles expected to join Xbox Game Pass. These games are not included in the library yet. Browse release details, expected arrival dates, genres, platforms, screenshots and trailers.</p>
<p class="muted">Expected arrival dates come from the source and may change. An expected date is not an official confirmation.</p></header>
<section class="toolbar" aria-label="Filter upcoming games">
<label>Search games<input id="search" type="search" placeholder="Enter a game title..." autocomplete="off"></label>
<label>Genre<select id="genre">{options}</select></label></section>
<p class="count" id="count">{len(games)} upcoming games · Data updated {updated}</p>
<section id="games" aria-label="Upcoming Game Pass games">{''.join(cards) if cards else '<p>No upcoming games are listed right now. Check back soon.</p>'}</section>
<footer>Last data refresh: <time>{updated}</time>. Game information is provided for discovery purposes and may be updated as release plans change.</footer>
</main><script>
(()=>{{const q=document.getElementById('search'),g=document.getElementById('genre'),cards=[...document.querySelectorAll('.game-card')],count=document.getElementById('count');
function filter(){{let n=0;const term=q.value.trim().toLowerCase(),genre=g.value;cards.forEach(c=>{{const ok=c.dataset.title.includes(term)&&(!genre||c.dataset.genres.split(' ').includes(genre));c.hidden=!ok;if(ok)n++}});count.textContent=n+' of '+cards.length+' games shown · Data updated {updated}'}}
q.addEventListener('input',filter);g.addEventListener('change',filter)}})();
</script></body></html>"""

def main() -> None:
    merged: dict[str, dict] = {}
    service_counts: dict[str, int] = {}
    service_pages: dict[str, dict] = {}

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
            if plan == "ultimate":
                service_pages[plan] = extract_service_page_data(page, plan, url, expected)
                service_pages[plan]["available_games"] = sorted(
                    [{"name": game["name"], **({"year": game["year"]} if game.get("year") else {})}
                     for game in games_by_url.values()],
                    key=lambda item: item["name"].casefold()
                )
                upcoming_details = []
                seen_upcoming = set()
                for upcoming in service_pages[plan].get("coming_soon", []):
                    source_url = upcoming.get("url")
                    if not source_url or source_url in seen_upcoming:
                        continue
                    seen_upcoming.add(source_url)
                    detail = {"name": upcoming["name"], "url": source_url}
                    if upcoming.get("year"):
                        detail["year"] = upcoming["year"]
                    enrich(detail)
                    detail["availability_date"] = upcoming.get("date_label")
                    detail["availability_date_type"] = upcoming.get("date_type", "tbd")
                    for key in list(detail):
                        if key.startswith("community_") or key in {"enrich_error", "url"}:
                            detail.pop(key, None)
                    upcoming_details.append(detail)
                service_pages[plan]["upcoming_games"] = upcoming_details
                for item in service_pages[plan].get("coming_soon", []):
                    item.pop("url", None)
            new_meta = collect_section_meta(page, "New Releases")
            leaving_meta = collect_section_meta(page, "Leaving Soon")
            new_links = set(new_meta)
            leaving_links = set(leaving_meta)
            service_counts[plan] = expected

            for game in games_by_url.values():
                game.setdefault("plans", []).append(plan)
                if game["url"] in new_links:
                    game.setdefault("new_plans", []).append(plan)
                    if new_meta.get(game["url"]):
                        game.setdefault("plan_added_dates", {})[plan] = new_meta[game["url"]]
                if game["url"] in leaving_links:
                    game.setdefault("leaving_plans", []).append(plan)
                    if leaving_meta.get(game["url"]):
                        game.setdefault("leaving_dates", {})[plan] = leaving_meta[game["url"]]
                current = merged.setdefault(game["url"], {"name": game["name"], "url": game["url"]})
                current.update({
                    k: v for k, v in game.items()
                    if k not in {"plans", "new_plans", "leaving_plans", "plan_added_dates", "leaving_dates"}
                })
                for key in ("plans", "new_plans", "leaving_plans"):
                    current.setdefault(key, []).extend(game.get(key, []))
                for key in ("plan_added_dates", "leaving_dates"):
                    current.setdefault(key, {}).update(game.get(key, {}))

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
    genre_counts: dict[str, dict[str, int]] = {}
    for plan in PLAN_ORDER:
        counts: dict[str, int] = {}
        for game in games:
            if plan not in game["plans"]:
                continue
            for genre in game.get("genres", []):
                counts[genre] = counts.get(genre, 0) + 1
        genre_counts[plan] = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower())))

    payload = {
        "source": "GameScriptions",
        "source_pages": SERVICES,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "service_counts": service_counts,
        "genre_counts": genre_counts,
        "service_pages": service_pages,
        "game_count_unique": len(games),
        "games": games,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # Publish a lightweight feed for the Upcoming Game Pass Games page.
    # It deliberately excludes GameScriptions page URLs and community statistics.
    upcoming_fields = (
        "name", "year", "description", "release_date", "genres",
        "platforms", "game_modes", "game_style", "cover_url",
        "screenshot_urls", "trailer_url", "gameplay_url",
        "availability_date", "availability_date_type", "developer",
        "publisher", "playtime_category", "playtime_hours",
        "campaign_chapters",
    )
    upcoming_items = []
    for source_game in service_pages.get("ultimate", {}).get("upcoming_games", []):
        item = {
            key: source_game[key]
            for key in upcoming_fields
            if key in source_game and source_game[key] not in (None, "", [], {})
        }
        if item.get("name"):
            upcoming_items.append(item)

    upcoming_feed = {
        "source": "Subli.one Xbox Game Pass Ultimate",
        "updated_at": payload["updated_at"],
        "count": len(upcoming_items),
        "games": upcoming_items,
    }
    Path("upcoming-game-pass-games.json").write_text(
        json.dumps(upcoming_feed, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    Path("upcoming-game-pass-games.html").write_text(
        render_upcoming_html(upcoming_feed), encoding="utf-8"
    )
    print(f"Wrote {len(games)} unique games to {OUT}")
    print("Service counts:", service_counts)


if __name__ == "__main__":
    main()
