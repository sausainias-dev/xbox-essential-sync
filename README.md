# Xbox Essential sync for Subli.one

This project periodically reads the public GameScriptions Game Pass Essential page,
collects the available game links plus new/leaving markers, and enriches each game
with cover art from the linked GameScriptions game page.

## Setup

1. Create a GitHub repository and upload these files.
2. Run the workflow once manually under **Actions**.
3. Enable **GitHub Pages** for the repository if you want a browser-readable JSON URL.
4. Put the resulting `xbox-essential.json` URL into the **JSON API Endpoint** field
   of the SellAuth `Xbox Essential Catalog` component.

The JSON has this shape:

```json
{
  "source": "https://gamescriptions.com/subscription/service/xbox_essential",
  "updated_at": "...",
  "games": [
    {
      "name": "Among Us",
      "year": 2018,
      "url": "https://gamescriptions.com/game/111469",
      "cover_url": "https://images.igdb.com/...",
      "added": null,
      "leaves": null
    }
  ]
}
```

The workflow runs every 6 hours. Review GameScriptions' terms and robots policy
before putting the scraper into production.
