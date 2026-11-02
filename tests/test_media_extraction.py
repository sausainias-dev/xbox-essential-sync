import unittest
from bs4 import BeautifulSoup

import sync


class MediaExtractionTests(unittest.TestCase):
    def test_gallery_screenshot_from_lazy_image_and_link(self):
        soup = BeautifulSoup(
            '''
            <div class="game-gallery">
              <a data-fancybox="gallery"
                 href="https://images.igdb.com/igdb/image/upload/t_screenshot_big/ab123.jpg">
                <img data-src="https://images.igdb.com/igdb/image/upload/t_screenshot_big/ab123.jpg"
                     alt="Screenshot 1">
              </a>
            </div>
            ''',
            "html.parser",
        )
        screenshots, trailer, gameplay = sync.extract_game_media(
            soup, "https://gamescriptions.com/game/1"
        )
        self.assertEqual(len(screenshots), 1)
        self.assertIn("t_screenshot_big", screenshots[0])
        self.assertIsNone(trailer)
        self.assertIsNone(gameplay)

    def test_trailer_and_gameplay_are_separated(self):
        soup = BeautifulSoup(
            '''
            <section class="trailer">
              <iframe src="https://www.youtube-nocookie.com/embed/Trailer12345"></iframe>
            </section>
            <section class="gameplay">
              <a href="https://youtu.be/Gameplay12345" title="Gameplay walkthrough">Watch</a>
            </section>
            ''',
            "html.parser",
        )
        _, trailer, gameplay = sync.extract_game_media(
            soup, "https://gamescriptions.com/game/2"
        )
        self.assertEqual(trailer, "https://www.youtube.com/watch?v=Trailer12345")
        self.assertEqual(gameplay, "https://www.youtube.com/watch?v=Gameplay12345")

    def test_compact_playtime_estimate(self):
        label, hours = sync.extract_playtime(
            "Released: October 12th, 2026 A Solid Adventure (10-19 Hours)"
        )
        self.assertEqual(label, "A Solid Adventure")
        self.assertEqual(hours, "10-19 Hours")

    def test_alternate_playtime_estimate(self):
        label, hours = sync.extract_playtime("Main Story: 12-15 Hours")
        self.assertEqual(label, "Main Story")
        self.assertEqual(hours, "12-15 Hours")

    def test_missing_playtime_is_not_invented(self):
        self.assertEqual(sync.extract_playtime("Released: May 9th, 2024"), (None, None))


if __name__ == "__main__":
    unittest.main()
