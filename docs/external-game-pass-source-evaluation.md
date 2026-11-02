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


## Read-only LT catalogue cross-check (verified configuration)

The current README and `config.schema.json` of `NikkelM/Game-Pass-API` confirm:
- `LT` is an accepted market code.
- `platformsToFetch` accepts `console`, `pc` and `eaPlay`.
- `includedProperties.productId` can be enabled, and `outputFormat: "array"` keeps records easy to compare.
- `keepCompleteProperties: true` preserves the raw per-platform/per-market responses for reproducibility.
- The CLI requires Node.js `>=22.13.0`.

Important localization limitation: `lt-lt` is **not** in the currently documented language enum. A run for market `LT` must therefore use a supported fallback locale (for example `en-gb`); the market and language are separate settings. This is suitable for product-ID matching, not for generating Lithuanian display text.

Suggested read-only configuration (do not write its output into the production catalogue automatically):

```json
{
  "$schema": "config.schema.json",
  "markets": ["LT"],
  "language": "en-gb",
  "platformsToFetch": ["console", "pc", "eaPlay"],
  "outputFormat": "array",
  "includedProperties": {
    "productTitle": true,
    "productId": true,
    "developerName": true,
    "publisherName": true,
    "categories": true,
    "releaseDate": {
      "enabled": true,
      "format": "date"
    }
  },
  "keepCompleteProperties": true,
  "outputDirectory": "output-lt"
}
```

Interpretation constraints:
- This feed describes current catalogue membership at fetch time. It is not an archive of historical additions.
- `console`, `pc` and `eaPlay` are platform/feed partitions, not proof of Essential, Premium or Ultimate entitlement. Do not translate them directly into the site's plan labels.
- `releaseDate` is the original game release date, never a substitute for `plan_added_dates`.
- Use exact Microsoft product IDs as the first matching key. If the production JSON lacks IDs, generate a separate candidate report using normalized titles and require manual review; do not silently merge fuzzy matches.
- Keep the raw response and fetch timestamp so future snapshots can be compared, but record that the first snapshot only establishes an observed baseline, not the historical date a game joined Game Pass.

Source: https://github.com/NikkelM/Game-Pass-API (README, `config.schema.json`, `package.json`; checked 2026-11-02).
