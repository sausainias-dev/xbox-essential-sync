# Uploaded catalogue audit — 2026-11-02

A user-provided archive `Subli-one-Game-Pass-Datos-v2-History-Dates.zip` was inspected locally.

## Verified catalogue coverage

The catalogue contains 651 games. 224 have at least one `plan_added_dates` entry. The historical backfill asset records 194 new plan-date fields across 111 games, with existing dates not overwritten.

| Plan | Catalogue games | With date | Missing |
|---|---:|---:|---:|
| Essential | 69 | 16 | 53 |
| PC Game Pass | 572 | 149 | 423 |
| Premium | 422 | 18 | 404 |
| Ultimate | 651 | 177 | 474 |
| EA Play | 92 | 9 | 83 |
| Ubisoft+ Classics | 64 | 18 | 46 |

Plan totals overlap because one game may belong to multiple plans. Missing means no date is currently documented in this catalogue; it does not mean the game has no historical date.

## Archive documentation issue

The archive's `GAME-PASS-ADDED-DATES-README.md` still reported the older values (96 added plan dates; 115 games with dates). The catalogue's `game_pass_date_data` and research asset report the newer values (194 backfilled fields; 224 games with dates). The archive copy was corrected and a machine-readable coverage audit was added.

## Third-party source integration decision

- `lucasromerodb/xbox-store-api`: potentially useful for short-window cross-checks, but README says production URL is deployment-specific and timestamped history older than seven days is deleted. Not a historical backfill source.
- `NikkelM/Game-Pass-API`: useful for current regional catalogue metadata and Microsoft product IDs; supports console, PC and EA Play markets, and can retain complete API responses. Its documented release-date field is the game's store release date, not its Game Pass entry date. Do not map it to `plan_added_dates`.
- Independent current catalogue lists can flag membership mismatches but cannot establish historical entry dates.

## Safe next step

Use NikkelM's tool only as an optional read-only metadata/catalogue comparison (prefer LT market, exact product IDs, and saved raw snapshots). Do not automatically write dates from its release-date field. Historical Game Pass dates still require a source explicitly documenting plan/platform entry.
