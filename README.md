# Xbox Game Pass catalog sync for Subli.one

Builds the combined Xbox catalog used by Subli.one from GameScriptions.

## Services

- Game Pass Essential
- Game Pass for PC
- Game Pass Premium
- Game Pass Ultimate
- EA Play (Xbox)
- Ubisoft+ Classics (Xbox)

## Data collected

- Exact Available Games count per service
- Game title and GameScriptions source URL
- Release year and release date when available
- Cover art and gallery screenshots
- Short real game description
- Estimated playtime category and hour range (for example, "A Solid Adventure", "10-19 Hours")
- Genres, play modes and themes
- Developer and publisher when available
- Xbox and PC platform compatibility
- Trailer and gameplay video links when available
- Campaign chapter count when available
- Aggregate community rating and rating count, plus public play-status totals when available
- Related games when exposed on the detail page
- Plan membership
- Added and Leaving Soon status/date when available
- Per-service genre counts
- Standalone Xbox Game Pass Ultimate service-page data: description, genre distribution, full available-game list, new releases, leaving-soon titles, and coming-soon schedule

The `service_pages.ultimate` object is intended for a dedicated Subli.one service page. It deliberately excludes game-level community ratings.

The source URL is retained for synchronization and identification. Subli.one can choose not to display it.

## Safety checks

The sync reads the `Available Games (N)` count from each GameScriptions service page and extracts only the Available Games table. It retries the full-list control when needed and refuses to publish if any service's extracted/merged count does not exactly match the source count.

## Workflow ownership

- `sync.yml` owns `xbox-essential.json` and the optional metadata cache.
- `upcoming-games.yml` is the only workflow that writes `upcoming-game-pass-games.json` and `upcoming-game-pass-games.html`.
- The main catalog sync still includes the Ultimate service page's compact `coming_soon` section, but no longer enriches those titles a second time or rewrites the dedicated Upcoming feed.
- Both publishers share one concurrency group and push back to the branch that triggered the workflow.

The Upcoming scraper accepts semantic headings and the source's alternate section-title layouts. It refuses to publish when the section or its game cards cannot be identified, and it compares the extracted count with the previous published feed to catch unusually large drops. Generated files are written through temporary files before replacement.
