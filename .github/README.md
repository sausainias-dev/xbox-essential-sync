# Xbox Game Pass catalog sync

Syncs the four GameScriptions Xbox Game Pass catalogs used by Subli.one.

Plans: Essential, PC, Premium, Ultimate.

The scraper reads the exact `Available Games (N)` count from each GameScriptions page, expands `Load Full Games List`, extracts only game links from the available-games table, and refuses to publish if any plan count differs.

Run manually from GitHub Actions with `Sync Xbox Game Pass catalog`.
