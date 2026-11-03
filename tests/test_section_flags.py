import unittest

import sync


class ServiceSectionIndexTests(unittest.TestCase):
    def test_index_preserves_source_order_and_deduplicates_urls(self):
        entries = [
            {"url": "https://gamescriptions.com/game/newest", "date_label": "Added: Nov 3, 2026"},
            {"url": "https://gamescriptions.com/game/next", "date_label": "Added: Nov 2, 2026"},
            {"url": "https://gamescriptions.com/game/newest", "date_label": "duplicate"},
            {"url": "", "date_label": "ignored"},
        ]

        indexed = sync.index_service_section(entries)

        self.assertEqual(list(indexed), [
            "https://gamescriptions.com/game/newest",
            "https://gamescriptions.com/game/next",
        ])
        self.assertEqual(indexed["https://gamescriptions.com/game/newest"]["order"], 0)
        self.assertEqual(indexed["https://gamescriptions.com/game/next"]["order"], 1)
        self.assertEqual(indexed["https://gamescriptions.com/game/newest"]["date_label"], "Added: Nov 3, 2026")

    def test_normalise_keeps_order_only_for_flagged_plans(self):
        game = {
            "name": "Example",
            "url": "https://gamescriptions.com/game/example",
            "plans": ["ultimate", "pc"],
            "new_plans": ["ultimate"],
            "leaving_plans": ["pc"],
            "new_plan_order": {"ultimate": 0, "pc": 4},
            "leaving_plan_order": {"pc": 2, "ultimate": 1},
        }

        normalized = sync.normalise(game)

        self.assertEqual(normalized["new_plan_order"], {"ultimate": 0})
        self.assertEqual(normalized["leaving_plan_order"], {"pc": 2})
        self.assertTrue(normalized["new"])
        self.assertTrue(normalized["leaving"])

    def test_normalise_does_not_create_leaving_flags(self):
        game = {
            "name": "Not Leaving",
            "url": "https://gamescriptions.com/game/not-leaving",
            "plans": ["ultimate"],
            "new_plans": [],
            "leaving_plans": [],
            "new_plan_order": {"ultimate": 3},
            "leaving_plan_order": {"ultimate": 1},
        }

        normalized = sync.normalise(game)

        self.assertFalse(normalized["leaving"])
        self.assertEqual(normalized["leaving_plan_order"], {})
        self.assertEqual(normalized["new_plan_order"], {})



class HistoricalAddedDateTests(unittest.TestCase):
    def test_parse_history_table_day_and_month_precision(self):
        html = """
        <table>
          <thead><tr><th>Game</th><th>Platform</th><th>Tier</th><th>Added</th><th>Left</th></tr></thead>
          <tbody>
            <tr><td>Example Game</td><td>PC</td><td>PC</td><td>21 Oct 2026</td><td></td></tr>
            <tr><td>Month Only</td><td>Xbox Series X</td><td>Console</td><td>October 2026</td><td></td></tr>
            <tr><td>Unknown Date</td><td>PC</td><td>PC</td><td></td><td></td></tr>
          </tbody>
        </table>
        """
        records = sync.parse_game_pass_history(html)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["added"], "Oct 21, 2026")
        self.assertEqual(records[0]["precision"], "day")
        self.assertEqual(records[1]["added"], "October 2026")
        self.assertEqual(records[1]["precision"], "month")

    def test_enriches_dates_by_matching_title_and_platform(self):
        records = [
            {"name":"Cross Platform", "title_key":sync.normalize_history_title("Cross Platform"),
             "platform":"PC", "platform_key":"pc", "tier":"PC",
             "added":"Oct 21, 2026", "precision":"day", "left":""},
            {"name":"Cross Platform", "title_key":sync.normalize_history_title("Cross Platform"),
             "platform":"Xbox Series X", "platform_key":"console", "tier":"Console",
             "added":"Oct 23, 2026", "precision":"day", "left":""},
        ]
        games = [{
            "name":"Cross Platform", "url":"https://example.test/game",
            "plans":["pc","ultimate"], "platforms":["PC (Microsoft Windows)","Xbox Series X|S"],
            "plan_added_dates":{}
        }]
        stats = sync.enrich_plan_added_dates(games, records)
        self.assertEqual(games[0]["plan_added_dates"]["pc"], "Oct 21, 2026")
        self.assertEqual(games[0]["plan_added_dates"]["ultimate"], "Oct 21, 2026")
        self.assertEqual(games[0]["plan_added_date_platforms"]["ultimate"],
                         {"pc":"Oct 21, 2026","console":"Oct 23, 2026"})
        self.assertEqual(stats["filled_plan_dates"], 2)

    def test_preserves_existing_fully_dated_source_value(self):
        record = {"name":"Preserve Me", "title_key":sync.normalize_history_title("Preserve Me"),
                  "platform":"PC", "platform_key":"pc", "tier":"PC",
                  "added":"Oct 23, 2026", "precision":"day", "left":""}
        game = {"name":"Preserve Me","url":"https://example.test/game","plans":["pc"],
                "platforms":["PC (Microsoft Windows)"],
                "plan_added_dates":{"pc":"Sep 1, 2025"}}
        sync.enrich_plan_added_dates([game],[record])
        self.assertEqual(game["plan_added_dates"]["pc"], "Sep 1, 2025")


if __name__ == "__main__":
    unittest.main()
