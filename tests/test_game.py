import itertools
import random
import unittest

from opensnake.game import Apple, Game, Wall
from opensnake.modes import CONFLICTS, MODES, blend_modes, toggle_mode


def make(modes=(), w=17, h=15, **kw):
    g = Game(w, h, modes, rng=random.Random(1), **kw)
    g.started = True
    return g


def clear_apples(g):
    g.apples.clear()
    g.items.clear()
    g.targets.clear()


class ClassicTests(unittest.TestCase):
    def test_moves_right(self):
        g = make()
        x = g.snakes[0].head.x
        g.step()
        self.assertEqual(g.snakes[0].head.x, x + 1)

    def test_eat_grows_and_scores(self):
        g = make()
        clear_apples(g)
        h = g.snakes[0].head
        g.apples.append(Apple(h.x + 1, h.y, "apple", 99))
        n = len(g.snakes[0].body)
        g.step()
        g.step()
        self.assertEqual(g.score, 1)
        self.assertEqual(len(g.snakes[0].body), n + 1)
        self.assertEqual(len(g.apples), 1)  # respawned

    def test_edge_kills(self):
        g = make()
        for _ in range(g.w):
            g.step()
        self.assertTrue(g.over)
        self.assertFalse(g.won)

    def test_reverse_is_ignored(self):
        g = make()
        g.input("left")
        self.assertEqual(g.snakes[0].queue, [])

    def test_self_collision(self):
        g = make()
        clear_apples(g)
        g.snakes[0].grow = 5
        for d in ("down", "left", "up"):
            g.input(d)
            g.step()
        self.assertTrue(g.over)

    def test_can_follow_own_tail(self):
        g = make()
        clear_apples(g)
        s = g.snakes[0]
        # A 2x2 loop: the head always enters the cell the tail is leaving.
        from opensnake.game import Seg
        s.body = [Seg(5, 5), Seg(5, 6), Seg(6, 6), Seg(6, 5)]
        s.dir = "right"
        g.step()
        self.assertFalse(g.over)


class ModeTests(unittest.TestCase):
    def test_borderless_wraps(self):
        g = make(["borderless"])
        clear_apples(g)
        for _ in range(g.w):
            g.step()
        self.assertFalse(g.over)

    def test_wall_spawns_on_eat(self):
        g = make(["wall"])
        clear_apples(g)
        h = g.snakes[0].head
        g.apples.append(Apple(h.x + 1, h.y, "apple", 99))
        g.step()
        self.assertEqual(len(g.walls), 1)

    def test_portal_teleports(self):
        g = make(["portal"])
        clear_apples(g)
        h = g.snakes[0].head
        g.apples += [Apple(h.x + 1, h.y, "apple", 7), Apple(2, 1, "apple", 7)]
        g.step()
        self.assertEqual((g.snakes[0].head.x, g.snakes[0].head.y), (2, 1))

    def test_twin_reverses(self):
        g = make(["twin"])
        clear_apples(g)
        s = g.snakes[0]
        h = s.head
        g.apples.append(Apple(h.x + 1, h.y, "apple", 99))
        g.step()
        self.assertEqual(s.dir, "left")

    def test_cheese_holes_are_passable(self):
        g = make(["cheese"])
        s = g.snakes[0]
        s.body[2].hole = True
        b = s.body[2]
        self.assertIsNone(g.solid_at(b.x, b.y))
        self.assertEqual(g.solid_at(s.body[1].x, s.body[1].y), "snake")

    def test_peaceful_never_dies(self):
        g = make(["peaceful"])
        for _ in range(g.w * 2):
            g.step()
        self.assertFalse(g.over)

    def test_key_locks_until_collected(self):
        g = make(["key"])
        a = next(a for a in g.apples)
        self.assertTrue(a.locked)
        self.assertEqual(g.solid_at(a.x, a.y), "lock")

    def test_sokoban_push(self):
        g = make(["sokoban"])
        clear_apples(g)
        h = g.snakes[0].head
        g.apples.append(Apple(h.x + 1, h.y, "apple", 5))
        g.targets.append((h.x + 2, h.y))
        g.step()
        self.assertEqual(g.score, 1)

    def test_poison_kills_and_swaps(self):
        g = make(["poison"], apple_count=3)
        self.assertEqual(sum(a.poison for a in g.apples), 3)
        self.assertEqual(sum(not a.poison for a in g.apples), 3)
        good = [a for a in g.apples if not a.poison]
        clear_apples(g)
        h = g.snakes[0].head
        g.apples.append(Apple(h.x + 1, h.y, "apple", 99, poison=True))
        g.step()
        self.assertTrue(g.over)
        self.assertTrue(good)

    def test_dimension_walls(self):
        g = make(["dimension"])
        g.walls[(1, 1)] = Wall(1, 1, "wall", 1)
        self.assertIsNone(g.solid_at(1, 1))
        g.dim = 1
        self.assertEqual(g.solid_at(1, 1), "wall")

    def test_statue_leaves_stone(self):
        g = make(["statue"])
        clear_apples(g)
        h = g.snakes[0].head
        g.apples.append(Apple(h.x + 1, h.y, "apple", 99))
        g.step()
        self.assertEqual(len(g.snakes[0].body), 3)
        self.assertTrue(any(w.kind == "statue" for w in g.walls.values()))

    def test_shield_absorbs_crash(self):
        g = make()
        g.snakes[0].shield = 1
        h = g.snakes[0].head
        g.walls[(h.x + 1, h.y)] = Wall(h.x + 1, h.y)
        g.step()
        self.assertFalse(g.over)
        self.assertEqual(g.snakes[0].shield, 0)

    def test_yinyang_mirrors(self):
        g = make(["yinyang"])
        g.input("up")
        self.assertEqual(g.snakes[1].queue, ["down"])


class ModeMenuTests(unittest.TestCase):
    def test_conflicts_resolve(self):
        s = toggle_mode({"portal"}, "sokoban")
        self.assertEqual(s, {"sokoban"})

    def test_blend_has_no_conflicts(self):
        rng = random.Random(3)
        for _ in range(200):
            s = blend_modes(rng)
            self.assertGreaterEqual(len(s), 2)
            for a, b in CONFLICTS:
                self.assertFalse(a in s and b in s)


class FuzzTests(unittest.TestCase):
    """Random play across every pair of modes must never raise."""

    def test_all_pairs(self):
        ids = [m[0] for m in MODES if m[0] != "classic"]
        dirs = ["up", "down", "left", "right"]
        rng = random.Random(42)
        combos = [()] + [(m,) for m in ids] + list(itertools.combinations(ids, 2))
        for combo in combos:
            if any(a in combo and b in combo for a, b in CONFLICTS):
                continue
            for size in ((10, 9), (24, 21)):
                g = Game(*size, combo + ("peaceful",), apple_count=rng.choice([1, 3, 12]),
                         fruit="mixed", rng=random.Random(rng.random()))
                for _ in range(300):
                    if rng.random() < 0.3:
                        g.input(rng.choice(dirs))
                    g.started = True
                    g.step()
                    g.events.clear()
                    if g.over:
                        break


class PlanTests(unittest.TestCase):
    def test_plan_locks_next_turn(self):
        g = make()
        g.input("down")
        g.plan()
        self.assertEqual(g.snakes[0].planned, "down")
        self.assertEqual(g.snakes[0].queue, [])
        g.step()
        self.assertEqual(g.snakes[0].dir, "down")
        self.assertIsNone(g.snakes[0].planned)

    def test_reverse_of_planned_is_ignored(self):
        g = make()
        g.input("down")
        g.plan()
        g.input("up")
        self.assertEqual(g.snakes[0].queue, [])


class PathTests(unittest.TestCase):
    def test_head_moves_without_jumps_through_turns(self):
        import math
        import os
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        from opensnake.render import build_snake_path
        g = make()
        clear_apples(g)
        g.step()  # get moving first: before the first step there is nothing to interpolate
        heads = []
        g.input("down")
        g.input("left")
        for _ in range(4):
            for t in (0.0, 0.25, 0.5, 0.75):
                if t >= 0.5:
                    g.plan()
                path, s_head, _ = build_snake_path(g, g.snakes[0], g.prev[0], t)
                heads.append(path.point(s_head)[:2])
            g.step()
        steps = [math.dist(a, b) for a, b in zip(heads, heads[1:])]
        self.assertLess(max(steps), 0.26)
        self.assertGreater(min(steps), 0.18)


if __name__ == "__main__":
    unittest.main()
