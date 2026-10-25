import json
import os
import random
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from opensnake.game import Game  # noqa: E402
from opensnake.modes import speed_ms  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "mods"


class SpeedTests(unittest.TestCase):
    def test_ticks_and_interpolation(self):
        self.assertEqual(speed_ms(0.0), 170)
        self.assertEqual(speed_ms(0.5), 130)
        self.assertEqual(speed_ms(1.0), 85)
        self.assertTrue(130 > speed_ms(0.75) > 85)
        self.assertEqual(speed_ms(-1), 170)
        self.assertEqual(speed_ms(5), 85)


class BigBoardTests(unittest.TestCase):
    def test_huge_rectangular_board_plays(self):
        g = Game(1000, 7, ["wall", "minesweeper", "gate"], apple_count=12, rng=random.Random(1))
        g.started = True
        for _ in range(200):
            g.step()
        self.assertEqual(sum(not a.poison for a in g.apples), 12)

    def test_full_board_wins(self):
        g = Game(8, 5, [], rng=random.Random(1))
        # Fill every cell except the snake with walls, then remove the fruit.
        from opensnake.game import Wall
        snake = {(p.x, p.y) for p in g.snakes[0].body}
        g.apples.clear()
        for y in range(5):
            for x in range(8):
                if (x, y) not in snake:
                    g.walls[(x, y)] = Wall(x, y)
        g.fill_apples()
        self.assertTrue(g.won)


class SettingsMigrationTests(unittest.TestCase):
    def test_old_named_size_and_speed(self):
        import pygame
        pygame.init()
        from opensnake.app import Store
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            path.write_text(json.dumps({"settings": {"size": "large", "speed": "fast"}}))
            s = Store(path).settings
            self.assertEqual((s["board_w"], s["board_h"]), (24, 21))
            self.assertEqual(s["speed"], 1.0)
            self.assertNotIn("size", s)

    def test_numbers_are_clamped(self):
        from opensnake.app import Store
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            path.write_text(json.dumps({"settings": {"board_w": 5000, "board_h": 1, "speed": "x"}}))
            s = Store(path).settings
            self.assertEqual((s["board_w"], s["board_h"]), (1000, 5))
            self.assertEqual(s["speed"], 0.5)


class ModTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from opensnake import mods
        if not any(name == "hunger" for name, _ in mods.LOADED):
            mods.load_mods([EXAMPLES])

    def test_example_mod_registers(self):
        from opensnake import mods
        from opensnake.game import FRUITS
        from opensnake.modes import FRUIT_LABELS, MODE_NAMES
        self.assertIn(("hunger", None), mods.LOADED)
        self.assertEqual(MODE_NAMES["hunger"], "Hunger")
        self.assertIn("kiwi", FRUITS)
        self.assertEqual(list(FRUIT_LABELS)[-1], "mixed")

    def test_hunger_shrinks_snake(self):
        g = Game(30, 30, ["hunger", "borderless"], rng=random.Random(1))
        g.apples.clear()
        g.started = True
        g.input("down")
        n = len(g.snakes[0].body)
        for _ in range(40):
            g.step()
        self.assertEqual(len(g.snakes[0].body), n - 1)

    def test_broken_mod_is_reported_not_fatal(self):
        from opensnake import mods
        with tempfile.TemporaryDirectory() as d:
            Path(d, "broken_mod.py").write_text("def setup(api):\n    raise RuntimeError('boom')\n")
            Path(d, "no_setup.py").write_text("x = 1\n")
            mods.load_mods([Path(d)])
        errors = dict(mods.LOADED)
        self.assertIn("boom", errors["broken_mod"])
        self.assertIn("setup", errors["no_setup"])

    def test_failing_hook_is_disabled(self):
        from opensnake import mods
        with tempfile.TemporaryDirectory() as d:
            Path(d, "crashy.py").write_text(
                "def setup(api):\n"
                "    def on_step(game):\n"
                "        raise ValueError('bad hook')\n"
                "    api.add_mode('crashy', 'Crashy', 'Crashes.', on_step=on_step)\n")
            mods.load_mods([Path(d)])
        g = Game(17, 15, ["crashy"], rng=random.Random(1))
        g.started = True
        for _ in range(5):
            g.step()  # must not raise
        self.assertIn("on_step", g.hooks[0].broken)


if __name__ == "__main__":
    unittest.main()
