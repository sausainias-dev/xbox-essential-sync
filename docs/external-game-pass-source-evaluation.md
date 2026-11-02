# External Game Pass data sources — evaluation

Date: 2026-11-02

## Decision

Do not merge a third-party feed into the production catalogue yet. The inspected projects do not currently provide a verifiable, continuously available historical source suitable for writing authoritative per-plan Game Pass inclusion dates.

## Source review

### 1. lucasromerodb/xbox-store-api

Repository: https://github.com/lucasromerodb/xbox-store-api

Useful fields documented by the project:
- Store product ID and title
- `dateAdded`
- Xbox One, Xbox Series, Windows and Cloud platform flags
- Current, new, upcoming and leaving lists

Important limitations:
- README documents only a local development URL and says the production URL is deployment-specific; no public production API base URL is supplied.
- Historical snapshots are retained in timestamped output folders, but the README says data older than seven days is automatically deleted.
- The project is marked as under heavy development.

Conclusion: potentially useful as a short-window secondary cross-check after a stable deployment URL and schema are verified. It is not currently a source for reconstructing older historical inclusion dates.

### 2. NikkelM/Game-Pass-API

Repository: https://github.com/NikkelM/Game-Pass-API

Useful as a catalogue/metadata reference (regional catalogue data, product details and game metadata). It is not documented as a historical per-plan inclusion-date archive.

Conclusion: consider later for metadata enrichment only. Do not map its release dates to Game Pass added dates.

### 3. OneBacklog/GamePass and NicoTomasin/Games-available-on-Game-Pass

These are useful as independent catalogue membership cross-checks. A current membership list does not prove when a title entered a specific plan, region or platform.

Conclusion: use only to flag possible catalogue mismatches, not to populate `plan_added_dates`.

## Integration rules

The existing production sync remains unchanged. In particular:
- Never infer Game Pass inclusion dates from original release dates.
- Never assign one plan's or platform's date to another plan.
- Match by Microsoft product ID when available; title-only matches require manual review.
- Preserve source URL, date precision and plan/platform context for every accepted date.
- Treat month/year-only evidence as month/year; do not invent a day.
- Keep unverified candidates separate from production `plan_added_dates`.

## Next safe integration step

If a stable public deployment of xbox-store-api becomes available, run a read-only comparison against the existing catalogue and report exact-ID matches, title-only candidates, platform conflicts and date coverage. Do not publish imported dates until the endpoint response and date semantics are verified.
