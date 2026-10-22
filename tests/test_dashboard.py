"""Dashboard interaction tests.

Skipped automatically when pygame is missing or the CSVs are not downloaded,
so `python -m unittest` still works on a bare machine.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Must be set before pygame initialises; harmless on desktops with a display.
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

try:
    import pygame
except ImportError:  # pragma: no cover - depends on the machine
    pygame = None


@unittest.skipIf(pygame is None, "pygame is not installed")
class DashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import dashboard
        cls.module = dashboard
        pygame.init()
        cls.screen = pygame.display.set_mode((dashboard.WIDTH, dashboard.HEIGHT))
        try:
            cities, meta = dashboard.load_cities()
        except FileNotFoundError as exc:
            pygame.quit()
            raise unittest.SkipTest(f"city data missing: {exc}")
        cls.board = dashboard.Dashboard(cities, meta)

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def setUp(self):
        self.board.rain = 1.0
        self.board.temp = 0.0
        self.board.drag = None
        self.board.active = "rain"
        self.board.selected = self.board.order()[0]

    def key(self, code: int) -> bool:
        return self.board.handle(pygame.event.Event(pygame.KEYDOWN, key=code, mod=0, unicode=""))

    def click(self, pos) -> None:
        self.board.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1))
        self.board.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1))

    def test_number_keys_select_the_visible_row(self):
        self.key(pygame.K_3)
        self.assertEqual(self.board.selected, self.board.order()[2])

    def test_arrows_respect_limits_and_tab_switches(self):
        self.key(pygame.K_TAB)
        self.assertEqual(self.board.active, "temp")
        for _ in range(20):
            self.key(pygame.K_RIGHT)
        self.assertEqual(self.board.temp, 5.0)
        for _ in range(30):
            self.key(pygame.K_LEFT)
        self.assertEqual(self.board.temp, -2.0)

    def test_dragging_slider_sets_value(self):
        track = self.board.rain_track
        self.board.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                            pos=(track.left, track.centery), button=1))
        self.assertEqual(self.board.rain, 0.0)
        self.assertEqual(self.board.drag, "rain")
        self.board.handle(pygame.event.Event(pygame.MOUSEMOTION,
                                            pos=(track.right, track.centery),
                                            rel=(0, 0), buttons=(1, 0, 0)))
        self.assertEqual(self.board.rain, 1.5)
        self.board.handle(pygame.event.Event(pygame.MOUSEBUTTONUP,
                                            pos=(track.right, track.centery), button=1))
        self.assertIsNone(self.board.drag)

    def test_clicking_a_row_selects_that_city(self):
        expected = self.board.order()[2]
        self.click(self.board.city_rows[2].center)
        self.assertEqual(self.board.selected, expected)

    def test_reset_returns_to_real_data(self):
        self.board.rain, self.board.temp = 0.3, 3.0
        self.key(pygame.K_r)
        self.assertEqual((self.board.rain, self.board.temp), (1.0, 0.0))
        self.assertFalse(self.board.score(self.board.selected)["is_scenario"])

    def test_escape_closes_the_window(self):
        self.assertFalse(self.key(pygame.K_ESCAPE))

    def test_frames_render_for_every_city(self):
        for city in self.board.cities:
            self.board.selected = city
            self.board.draw(self.screen)
        self.assertEqual(self.screen.get_size(), (self.module.WIDTH, self.module.HEIGHT))


if __name__ == "__main__":
    unittest.main()
