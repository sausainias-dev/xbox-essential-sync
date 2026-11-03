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


if __name__ == "__main__":
    unittest.main()
