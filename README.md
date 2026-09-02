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
- Cover art
- Short real game description
- Genres
- Play modes
- Game style (source: GameScriptions Themes)
- Developer and publisher when available
- Platforms limited to Xbox and PC
- Plan membership
- Added and Leaving Soon status/date when available
- Per-service genre counts

The source URL is retained for synchronization and identification. Subli.one can choose not to display it.

## Safety checks

The sync reads the `Available Games (N)` count from each GameScriptions service page and extracts only the Available Games table. It retries the full-list control when needed and refuses to publish if any service's extracted/merged count does not exactly match the source count.
