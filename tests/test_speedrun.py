import json
import random
import tempfile
import unittest
from pathlib import Path

from opensnake.speedrun import (CATEGORIES, CATEGORY_BY_ID, Records, Run, format_delta, format_time,
                                replay, verify)

DIRS = ["up", "down", "left", "right"]


def bot_run(category, seed, rng, max_ticks=4000):
    """Play a run with a simple bot: head for the nearest edible fruit, dodge danger."""
    run = Run(category, seed)
    g = run.game
    run.input("up")
    while not g.over and g.tick < max_ticks:
        head = g.snakes[0].head
        targets = [a for a in g.apples if not a.poison and not a.locked]
        targets += [it for it in g.items if it.type == "key"]
        if targets:
            t = min(targets, key=lambda a: abs(a.x - head.x) + abs(a.y - head.y))
            want = []
            if t.x > head.x: want.append("right")
            if t.x < head.x: want.append("left")
            if t.y > head.y: want.append("down")
            if t.y < head.y: want.append("up")
        else:
            want = []
        options = want + rng.sample(DIRS, 4)
        from opensnake.game import DIRS as V, OPPOSITE
        s = g.snakes[0]
        for d in options:
            if d == OPPOSITE[s.dir]:
                continue
            nx, ny = head.x + V[d][0], head.y + V[d][1]
            if g.in_bounds(nx, ny) and not g.solid_at(nx, ny):
                if d != s.dir:
                    run.input(d)
                break
        run.step()
        g.events.clear()
    return run


class FormatTests(unittest.TestCase):
    def test_format(self):
        self.assertEqual(format_time(12345), "0:12.345")
        self.assertEqual(format_time(61005), "1:01.005")
        self.assertEqual(format_time(None), "--")
        self.assertEqual(format_delta(-412), "-0.412")
        self.assertEqual(format_delta(1050), "+1.050")


class RunTests(unittest.TestCase):
    def test_categories_are_valid(self):
        self.assertEqual(len(CATEGORY_BY_ID), len(CATEGORIES))
        for c in CATEGORIES:
            run = Run(c, 1)
            self.assertFalse(run.game.over, c.id)
            self.assertGreater(c.ms_for(1000), 0)

    def test_timer_counts_game_time(self):
        run = Run(CATEGORY_BY_ID["sprint10"], 5)
        run.input("up")
        for _ in range(3):
            run.step()
        self.assertEqual(run.elapsed, 3 * 130)

    def test_accelerate_gets_faster(self):
        c = CATEGORY_BY_ID["accelerate"]
        self.assertLess(c.ms_for(10), c.ms_for(0))
        self.assertEqual(c.ms_for(1000), c.min_tick_ms)

    def test_replays_match_and_verify(self):
        rng = random.Random(9)
        finished = 0
        for c in CATEGORIES:
            for seed in (1, 2):
                run = bot_run(c, seed, rng)
                data = json.loads(json.dumps(run.to_json("tester", "test")))
                again = replay(data)
                self.assertEqual(round(again.elapsed), round(run.elapsed), c.id)
                self.assertEqual(again.game.score, run.game.score, c.id)
                self.assertEqual(again.finished, run.finished, c.id)
                if run.finished:
                    finished += 1
                    ok, msg = verify(data)
                    self.assertTrue(ok, msg)
                    self.assertEqual(len(run.splits), run.game.score)
        self.assertGreater(finished, 3)  # the bot completes several categories

    def test_tampered_time_is_rejected(self):
        rng = random.Random(3)
        run = bot_run(CATEGORY_BY_ID["sprint10"], 4, rng)
        self.assertTrue(run.finished)
        data = run.to_json()
        data["time_ms"] -= 500
        ok, msg = verify(data)
        self.assertFalse(ok)
        self.assertIn("claimed", msg)

    def test_unfinished_run_is_rejected(self):
        run = Run(CATEGORY_BY_ID["sprint10"], 4)
        run.input("up")
        for _ in range(3):
            run.step()
        ok, msg = verify(run.to_json())
        self.assertFalse(ok)


class RecordsTests(unittest.TestCase):
    def test_bundled_and_newer_cache(self):
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d) / "records.json"
            cache.write_text(json.dumps({"updated": "2999-01-01", "records": {
                "sprint10": {"time_ms": 9000, "player": "someone"},
                "not_a_category": {"time_ms": 1},
                "sprint25": {"time_ms": "fast"}}}))
            r = Records(cache)
            self.assertEqual(r.get("sprint10")["time_ms"], 9000)
            self.assertIsNone(r.get("not_a_category"))
            self.assertIsNone(r.get("sprint25"))

    def test_older_cache_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d) / "records.json"
            cache.write_text(json.dumps({"updated": "2000-01-01", "records": {"sprint10": {"time_ms": 1}}}))
            r = Records(cache)
            self.assertEqual(r.source, "bundled")


if __name__ == "__main__":
    unittest.main()


class CustomCategoryTests(unittest.TestCase):
    def test_same_settings_same_id(self):
        from opensnake.speedrun import make_custom
        a = make_custom(12, 9, ["wall", "portal"], 15, 1, 130, name="Mine")
        b = make_custom(12, 9, ["portal", "wall"], 15, 1, 130.04, name="Yours")
        c = make_custom(12, 9, ["portal", "wall"], 16, 1, 130)
        self.assertEqual(a.id, b.id)          # mode order and name don't matter
        self.assertNotEqual(a.id, c.id)       # the goal does
        self.assertTrue(a.id.startswith("custom-"))
        self.assertIsNone(make_custom(8, 5, [], 0, 1, 130).goal)  # 0 = fill the board

    def test_custom_run_replays_and_verifies(self):
        from opensnake.speedrun import make_custom
        cat = make_custom(10, 9, ["borderless"], 6, 2, 100, fruit="mixed", name="Wrap 6")
        run = bot_run(cat, 3, random.Random(1))
        self.assertTrue(run.finished)
        data = json.loads(json.dumps(run.to_json("tester")))
        self.assertIn("category_def", data)
        ok, msg = verify(data)
        self.assertTrue(ok, msg)
        self.assertIn("Wrap 6", msg)

    def test_edited_rules_are_rejected(self):
        from opensnake.speedrun import make_custom
        cat = make_custom(10, 9, [], 5, 1, 130)
        run = bot_run(cat, 2, random.Random(4))
        self.assertTrue(run.finished)
        data = run.to_json()
        data["category_def"]["goal"] = 1  # make it easier, keep the old id
        ok, msg = verify(data)
        self.assertFalse(ok)
        self.assertIn("doesn't match", msg)

    def test_save_and_load(self):
        from opensnake.speedrun import load_custom_categories, make_custom, save_custom_categories
        cats = [make_custom(10, 9, ["wall"], 10, 1, 85, name="Fast walls"),
                make_custom(20, 20, [], None, 5, 130, name="Big fill")]
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "custom-categories.json"
            self.assertTrue(save_custom_categories(path, cats + [cats[0]]))  # duplicate is dropped on load
            loaded = load_custom_categories(path)
        self.assertEqual([c.id for c in loaded], [c.id for c in cats])
        self.assertEqual(loaded[0].name, "Fast walls")

    def test_custom_world_records_are_accepted(self):
        from opensnake.speedrun import make_custom
        cid = make_custom(10, 9, [], 5, 1, 130).id
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d) / "records.json"
            cache.write_text(json.dumps({"updated": "2999-01-01",
                                         "records": {cid: {"time_ms": 4000, "player": "x"}}}))
            self.assertEqual(Records(cache).get(cid)["time_ms"], 4000)


class SiteRecordsTests(unittest.TestCase):
    def test_site_records_replace_and_restore(self):
        r = Records(None)
        offline = dict(r.records)
        r.set_server({"sprint10": {"time_ms": 5000, "player": "site-hero"}, "junk": "x"}, "snake.example.com")
        self.assertEqual(r.get("sprint10")["player"], "site-hero")
        self.assertIsNone(r.get("junk"))
        self.assertEqual(r.source, "site:snake.example.com")
        r.set_server({}, "other.example.com")  # switching sites keeps the original to restore
        self.assertIsNone(r.get("sprint10"))
        r.clear_server()
        self.assertEqual(r.records, offline)
        self.assertNotEqual(r.source.split(":")[0], "site")
