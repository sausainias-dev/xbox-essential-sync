#!/usr/bin/env python3
"""Generate a Lithuanian Game Pass Ultimate catalog with translated descriptions baked into HTML."""
from __future__ import annotations
import html
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "xbox-essential.json"
OUTPUT_JSON = ROOT / "xbox-game-pass-ultimate-lt-catalog.json"
OUTPUT_HTML = ROOT / "game-pass-ultimate-zaidimu-katalogas.html"
TRANSLATION_FILES = sorted(ROOT.glob("lt-descriptions-part-*.json"))

def norm(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    value = value.replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "", value)

def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)

def load_translations() -> dict[str, str]:
    result: dict[str, str] = {}
    for path in TRANSLATION_FILES:
        content = json.loads(path.read_text(encoding="utf-8"))
        for name, value in content.items():
            if isinstance(value, str) and value.strip():
                result[norm(name)] = value.strip()
            elif isinstance(value, dict) and value.get("description"):
                result[norm(name)] = str(value["description"]).strip()
    return result

def is_ultimate(game: dict) -> bool:
    plans = game.get("plans") or []
    return bool(game.get("ultimate")) or any(str(plan).casefold() == "ultimate" for plan in plans)

def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"Required source is missing: {SOURCE}")
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    all_games = source.get("games", []) if isinstance(source, dict) else source
    if not isinstance(all_games, list) or not all_games:
        raise SystemExit("Source catalog contains no games; refusing to generate empty output.")
    translations = load_translations()
    games = []
    for raw in all_games:
        if not isinstance(raw, dict) or not is_ultimate(raw):
            continue
        game = dict(raw)
        name = str(game.get("name") or "").strip()
        translation = translations.get(norm(name))
        game["description_original"] = str(raw.get("description") or "")
        game["description_lt"] = translation or ""
        game["description"] = translation or str(raw.get("description") or "")
        game["description_language"] = "lt" if translation else "original"
        games.append(game)
    if not games:
        raise SystemExit("No Ultimate games found; refusing to generate empty output.")
    games.sort(key=lambda g: str(g.get("name", "")).casefold())
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "source": "GameScriptions",
        "generated_at": now,
        "source_updated_at": source.get("updated_at") if isinstance(source, dict) else None,
        "game_count": len(games),
        "translated_count": sum(1 for game in games if game["description_language"] == "lt"),
        "games": games,
    }
    OUTPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    cards = []
    for game in games:
        name = str(game.get("name") or "")
        description = str(game.get("description") or "")
        genres = game.get("genres") if isinstance(game.get("genres"), list) else []
        cover = game.get("cover_url") or game.get("cover") or ""
        year = game.get("year") or ""
        added_dates = game.get("plan_added_dates") if isinstance(game.get("plan_added_dates"), dict) else {}
        added = str(added_dates.get("ultimate") or "")
        cards.append(f"""
<article class="game-card" data-name="{esc(name.casefold())}" data-genre="{esc('|'.join(map(str, genres)).casefold())}" data-added="{esc(added)}">
  <div class="cover">{f'<img loading="lazy" src="{esc(cover)}" alt="Žaidimo {esc(name)} viršelis">' if cover else '<div class="cover-placeholder">Xbox</div>'}</div>
  <div class="game-content">
    <div class="game-heading"><h2>{esc(name)}</h2>{f'<span class="year">{esc(year)}</span>' if year else ''}</div>
    <p class="description">{esc(description)}</p>
    <div class="meta">{''.join(f'<span class="chip">{esc(g)}</span>' for g in genres[:4])}</div>
    <div class="description-source">{'Lietuviškas aprašymas' if game['description_language'] == 'lt' else 'Originalus aprašymas'}</div>
  </div>
</article>""")
    all_genres = sorted({str(g) for game in games for g in (game.get("genres") or []) if str(g).strip()}, key=str.casefold)
    genre_options = ''.join(f'<option value="{esc(g.casefold())}">{esc(g)}</option>' for g in all_genres)
    generated_date = now[:10]
    document = f"""<!doctype html>
<html lang="lt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Xbox Game Pass Ultimate žaidimų katalogas lietuviškai | Subli.one</title>
<meta name="description" content="Peržiūrėkite Xbox Game Pass Ultimate žaidimų katalogą. Lietuviški aprašymai, naujausias žaidimų sąrašas, paieška ir rūšiavimas.">
<link rel="canonical" href="https://subli.one/game-pass-ultimate-zaidimu-katalogas">
<meta name="robots" content="index,follow">
<style>
:root{{color-scheme:dark;--bg:#0b0e14;--panel:#141a23;--line:#2a3443;--text:#f6f7fb;--muted:#aab4c3;--accent:#91e34f}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:16px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1280px;margin:auto;padding:32px 18px 60px}}header{{margin-bottom:24px}}.eyebrow{{color:var(--accent);font-weight:800;letter-spacing:.09em;text-transform:uppercase;font-size:.76rem}}
h1{{font-size:clamp(2rem,5vw,3.1rem);line-height:1.08;margin:.4rem 0 1rem}}.intro{{color:var(--muted);max-width:850px}}.statline{{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0}}.stat{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:9px 13px}}
.controls{{display:grid;grid-template-columns:1fr repeat(2,minmax(160px,220px));gap:10px;margin:24px 0}}input,select{{width:100%;background:var(--panel);border:1px solid var(--line);border-radius:10px;color:var(--text);padding:12px 14px;font:inherit}}.catalog{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}.game-card{{display:grid;grid-template-columns:124px 1fr;gap:16px;min-width:0;background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:14px}}.cover img{{width:100%;aspect-ratio:3/4;object-fit:cover;border-radius:10px;display:block}}.cover-placeholder{{aspect-ratio:3/4;background:#263241;border-radius:10px;display:grid;place-items:center;color:var(--muted);font-weight:800}}.game-heading{{display:flex;gap:8px;align-items:baseline;justify-content:space-between}}h2{{font-size:1.05rem;line-height:1.3;margin:0 0 8px}}.year{{color:var(--muted);font-size:.82rem;white-space:nowrap}}.description{{font-size:.9rem;color:#d8dee8;margin:0 0 12px}}.meta{{display:flex;gap:6px;flex-wrap:wrap}}.chip{{font-size:.72rem;background:#202a37;border:1px solid var(--line);padding:3px 7px;border-radius:99px;color:#dce4ed}}.description-source{{font-size:.72rem;color:var(--accent);margin-top:10px}}.footer{{color:var(--muted);font-size:.8rem;margin-top:28px}}[hidden]{{display:none!important}}
@media(max-width:820px){{.catalog{{grid-template-columns:1fr}}.controls{{grid-template-columns:1fr}}}}@media(max-width:480px){{.game-card{{grid-template-columns:86px 1fr;gap:11px;padding:10px}}.description{{font-size:.84rem}}}}
</style>
</head>
<body><main>
<header><div class="eyebrow">Subli.one · Xbox Game Pass Ultimate</div><h1>Žaidimų katalogas</h1>
<p class="intro">Peržiūrėkite žaidimus, įtrauktus į Xbox Game Pass Ultimate. Jei turime lietuvišką žaidimo aprašymą, rodomas jis; kitu atveju pateikiamas originalus aprašymas. Sąrašas automatiškai atnaujinamas iš pagrindinio žaidimų duomenų šaltinio.</p>
<div class="statline"><div class="stat"><strong>{len(games)}</strong> žaidimų</div><div class="stat"><strong>{payload['translated_count']}</strong> lietuviškų aprašymų</div><div class="stat">Atnaujinta: <strong>{esc(generated_date)}</strong></div></div>
</header>
<div class="controls"><input id="search" type="search" placeholder="Ieškoti žaidimo…" aria-label="Ieškoti žaidimo"><select id="genre" aria-label="Filtruoti pagal žanrą"><option value="">Visi žanrai</option>{genre_options}</select><select id="sort" aria-label="Rūšiuoti katalogą"><option value="name">Pavadinimas: A–Z</option><option value="name-desc">Pavadinimas: Z–A</option><option value="added">Naujausi papildymai</option></select></div>
<p id="result-count" aria-live="polite">{len(games)} žaidimų</p>
<section class="catalog" id="catalog">
{''.join(cards)}
</section>
<p class="footer">Duomenų šaltinis: žaidimų katalogo sinchronizacija. HTML generavimo data: {esc(now)}. Katalogas atnaujinamas automatiškai, kai atnaujinami pagrindiniai duomenys.</p>
</main>
<script>
(function(){{
 const list=document.getElementById('catalog'), cards=[...list.querySelectorAll('.game-card')], search=document.getElementById('search'), genre=document.getElementById('genre'), sort=document.getElementById('sort'), count=document.getElementById('result-count');
 function refresh(){{
  const q=search.value.trim().toLocaleLowerCase('lt'), g=genre.value;
  const shown=cards.filter(c=>c.dataset.name.includes(q)&&(!g||c.dataset.genre.split('|').includes(g)));
  cards.forEach(c=>c.hidden=!shown.includes(c));
  shown.sort((a,b)=>{{
   if(sort.value==='name-desc') return b.dataset.name.localeCompare(a.dataset.name,'lt');
   if(sort.value==='added') return (b.dataset.added||'').localeCompare(a.dataset.added||'');
   return a.dataset.name.localeCompare(b.dataset.name,'lt');
  }});
  shown.forEach(c=>list.appendChild(c));
  count.textContent=shown.length+' iš '+cards.length+' žaidimų';
 }}
 [search,genre,sort].forEach(e=>e.addEventListener('input',refresh));
}})();
</script></body></html>"""
    OUTPUT_HTML.write_text(document, encoding="utf-8")
    print(f"Generated {OUTPUT_HTML.name}: {len(games)} games, {payload['translated_count']} LT descriptions")

if __name__ == "__main__":
    main()
