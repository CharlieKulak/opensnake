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
        self.assertEqual(speed_ms(0.0), 260)   # Slowest
        self.assertEqual(speed_ms(0.25), 170)  # Slow
        self.assertEqual(speed_ms(0.5), 130)   # Default
        self.assertEqual(speed_ms(0.75), 85)   # Fast
        self.assertEqual(speed_ms(1.0), 45)    # Fastest
        self.assertTrue(130 > speed_ms(0.6) > 85)
        self.assertEqual(speed_ms(-1), 260)
        self.assertEqual(speed_ms(5), 45)


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
            self.assertEqual(speed_ms(s["speed"]), 85)  # "fast" keeps the same actual speed
            self.assertNotIn("size", s)

    def test_old_slider_scale_keeps_speeds_and_bests(self):
        from opensnake.app import Store
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            # Saved by the 3-stop slider (0 = Slow, 0.5 = Default, 1 = Fast).
            path.write_text(json.dumps({"settings": {"speed": 1.0},
                                        "best": {"classic:17x15:1.00:1": 42, "classic:10x9:0.50:1": 7}}))
            store = Store(path)
            self.assertEqual(speed_ms(store.settings["speed"]), 85)
            self.assertEqual(store.best, {"classic:17x15:0.75:1": 42, "classic:10x9:0.50:1": 7})
            store.save()
            again = Store(path)  # already converted: must not convert twice
            self.assertEqual(again.settings["speed"], 0.75)
            self.assertEqual(again.best["classic:17x15:0.75:1"], 42)

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


class MainLoopTests(unittest.TestCase):
    """Start the real main loop, as the desktop launcher does (not just draw()/update())."""

    def run_app_once(self, setup=None):
        import pygame
        from opensnake.app import App
        with tempfile.TemporaryDirectory() as d:
            os.environ["OPENSNAKE_CONFIG_DIR"] = str(Path(d) / "opensnake")
            app = App()
            if setup:
                setup(app)
            self.assertTrue(callable(app.run), "App.run must stay the main-loop method")
            pygame.event.post(pygame.event.Event(pygame.QUIT))
            app.run()  # must return after the QUIT event, not crash
            self.assertFalse(app.running)

    def test_main_loop_from_menu(self):
        self.run_app_once()

    def test_main_loop_during_speedrun(self):
        from opensnake.speedrun import CATEGORIES
        self.run_app_once(lambda app: app.start_run(CATEGORIES[0]))


class CustomSpeedrunAppTests(unittest.TestCase):
    def test_checkbox_play_and_saved_category(self):
        import pygame
        from opensnake.app import App
        from opensnake.speedrun import load_custom_categories
        with tempfile.TemporaryDirectory() as d:
            os.environ["OPENSNAKE_CONFIG_DIR"] = str(Path(d) / "opensnake")
            app = App()
            s = app.settings
            s.update(speedrun_mode=True, sr_goal=7, modes=["wall"], board_w=12, board_h=10)
            app.play()
            self.assertIsNotNone(app.attempt)
            cat = app.attempt.category
            self.assertTrue(cat.custom)
            self.assertEqual((cat.w, cat.h, cat.goal, cat.modes), (12, 10, 7, ("wall",)))
            self.assertEqual(app.attempt_origin, "menu")
            # Esc before starting goes back to the menu it came from
            app.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0, unicode=""))
            self.assertEqual(app.state, "menu")

            app.open_speedrun()
            app.add_custom_category()
            app.add_custom_category()  # adding the same settings twice keeps one
            self.assertEqual(len(app.custom_cats), 1)
            saved = load_custom_categories(Path(d) / "opensnake" / "custom-categories.json")
            self.assertEqual([c.id for c in saved], [cat.id])
            self.assertEqual(app.all_categories()[app.sr_focus].id, cat.id)
            # Delete needs a second press
            key = lambda k: app.handle(pygame.event.Event(pygame.KEYDOWN, key=k, mod=0, unicode=""))
            key(pygame.K_DELETE)
            self.assertEqual(len(app.custom_cats), 1)
            key(pygame.K_DELETE)
            self.assertEqual(len(app.custom_cats), 0)


class PacksAndModsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["OPENSNAKE_CONFIG_DIR"] = str(Path(self.tmp.name) / "opensnake")

    def tearDown(self):
        self.tmp.cleanup()

    def test_builtin_pack_is_found(self):
        from opensnake.addons import discover_packs
        packs = {p.id: p for p in discover_packs()}
        self.assertIn("builtin:shadow_venom", packs)
        self.assertEqual(packs["builtin:grave_viper"].name, "Grave Viper")
        self.assertEqual(packs["builtin:everforest"].name, "Everforest")
        venom = packs["builtin:shadow_venom"]
        self.assertEqual(venom.name, "Shadow Venom")
        self.assertTrue(venom.builtin and venom.icon is not None)

    def test_enable_disable_and_priority(self):
        from opensnake import render
        from opensnake.app import App
        app = App()
        default_light = render.LIGHT
        app.open_addons()
        app.toggle_pack("builtin:shadow_venom")
        self.assertEqual(app.settings["packs"], ["builtin:shadow_venom"])
        self.assertEqual(render.LIGHT, (0x1c, 0x1a, 0x22))      # pack.json colours applied
        self.assertIsNotNone(app.pack.image_path("snake_head"))  # pack art used
        self.assertIsNotNone(app.pack.sound("eat"))
        # a second (user) pack on top overrides the same colour
        user = Path(self.tmp.name) / "opensnake" / "resourcepacks" / "mine"
        user.mkdir(parents=True)
        (user / "pack.json").write_text(json.dumps({"name": "Mine", "board_light": "#010203"}))
        app.open_addons()
        app.toggle_pack("user:mine")
        self.assertEqual(app.settings["packs"], ["user:mine", "builtin:shadow_venom"])
        self.assertEqual(render.LIGHT, (1, 2, 3))
        app.move_pack("user:mine", 1)  # lower its priority
        self.assertEqual(render.LIGHT, (0x1c, 0x1a, 0x22))
        # turning everything off restores the built-in look
        app.toggle_pack("user:mine")
        app.toggle_pack("builtin:shadow_venom")
        self.assertEqual(render.LIGHT, default_light)
        self.assertIsNone(app.pack.image_path("snake_head"))
        # and the setting is saved
        from opensnake.app import Store, config_path
        self.assertEqual(Store(config_path()).settings["packs"], [])

    def test_disabled_mod_is_not_loaded(self):
        from opensnake import mods
        d = Path(self.tmp.name) / "m"
        d.mkdir()
        (d / "sleepy_mod.py").write_text('"""A test mod."""\ndef setup(api):\n    raise SystemError("should not run")\n')
        before = len(mods.LOADED)
        mods.load_mods([d], disabled={"sleepy_mod"})
        self.assertEqual(len(mods.LOADED), before)
        self.assertEqual([n for n, *_ in mods.iter_mods([d])], ["sleepy_mod"])
        self.assertEqual(mods.describe_mod(d / "sleepy_mod.py"), "A test mod.")

    def test_addons_screen_draws_and_main_loop_runs(self):
        import pygame
        from opensnake.app import App
        app = App()
        app.open_addons()
        app.draw()
        first = app.pack_rows()[0].id
        app.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0, unicode=""))
        self.assertEqual(app.settings["packs"], [first])  # Enter toggles the selected (first) pack
        pygame.event.post(pygame.event.Event(pygame.QUIT))
        app.run()


class BuiltinPackContentTests(unittest.TestCase):
    """Every built-in pack's files load, and each pack covers the same sprites."""

    def test_all_builtin_pack_files_load(self):
        import pygame
        from opensnake.addons import BUILTIN_PACKS
        from opensnake.assets import AssetPack, load_image
        pygame.init()
        expected = {"snake_head", "fruit_apple", "fruit_poison", "wall", "statue", "mine", "key", "lock",
                    "shield", "trophy", "ring", "target", "arrow", "gate_open", "gate_closed", "pack"}
        for folder in sorted(BUILTIN_PACKS.iterdir()):
            names = {f.stem for f in folder.glob("*.svg")}
            self.assertTrue(expected <= names, f"{folder.name} is missing {expected - names}")
            for svg in folder.glob("*.svg"):
                img = load_image(svg, 48)
                self.assertIsNotNone(img, svg)
                self.assertGreater(pygame.transform.average_color(img)[3], 0, f"{svg} renders blank")
            pack = AssetPack([folder])
            self.assertIsNotNone(pack.sound("eat"), folder.name)
            self.assertIn("board_light", pack.colors, folder.name)
