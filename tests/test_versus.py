import json
import random
import unittest

from opensnake.game import Apple, Game, Seg, apply_state, game_to_state


def versus(teams, w=20, h=18, **kw):
    g = Game(w, h, kw.pop("modes", ()), kw.pop("apple_count", 1), rng=random.Random(1), teams=teams, **kw)
    g.started = True
    g.apples.clear()
    return g


class SpawnTests(unittest.TestCase):
    def test_all_team_sizes_spawn_cleanly(self):
        for a in range(1, 5):
            for b in range(1, 5):
                teams = [0] * a + [1] * b
                g = versus(teams)
                cells = [(p.x, p.y) for s in g.snakes for p in s.body]
                self.assertEqual(len(cells), len(set(cells)), f"{a}v{b} overlap")
                self.assertTrue(all(0 <= x < g.w and 0 <= y < g.h for x, y in cells), f"{a}v{b} off board")
                self.assertEqual([s.team for s in g.snakes], teams)
                self.assertEqual({s.dir for s in g.snakes if s.team == 0}, {"right"})
                self.assertEqual({s.dir for s in g.snakes if s.team == 1}, {"left"})

    def test_yinyang_is_ignored_in_versus(self):
        g = versus([0, 1], modes=["yinyang"])
        self.assertFalse(g.has("yinyang"))


class RulesTests(unittest.TestCase):
    def test_each_player_steers_their_own_snake(self):
        g = versus([0, 1])
        g.input_for(0, "up")
        g.step()
        self.assertEqual(g.snakes[0].dir, "up")
        self.assertEqual(g.snakes[1].dir, "left")

    def test_crash_only_knocks_out_that_snake(self):
        g = versus([0, 0, 1])
        g.snakes[0].body = [Seg(0, 1), Seg(1, 1), Seg(2, 1), Seg(3, 1)]
        g.snakes[0].dir = "left"
        g.step()
        self.assertTrue(g.snakes[0].dead)
        self.assertFalse(g.over)

    def test_last_team_standing_wins(self):
        g = versus([0, 1])
        g.snakes[1].body = [Seg(g.w - 1, 2), Seg(g.w - 2, 2), Seg(g.w - 3, 2), Seg(g.w - 4, 2)]
        g.snakes[1].dir = "right"
        g.step()
        self.assertTrue(g.over)
        self.assertEqual(g.winner, 0)

    def test_head_on_kills_both(self):
        g = versus([0, 1])
        g.snakes[0].body = [Seg(8, 5), Seg(7, 5), Seg(6, 5), Seg(5, 5)]
        g.snakes[0].dir = "right"
        g.snakes[1].body = [Seg(10, 5), Seg(11, 5), Seg(12, 5), Seg(13, 5)]
        g.snakes[1].dir = "left"
        g.step()
        self.assertTrue(g.snakes[0].dead and g.snakes[1].dead)
        self.assertTrue(g.over)
        self.assertIsNone(g.winner)  # draw

    def test_only_the_eater_grows_and_goal_wins(self):
        g = versus([0, 1], goal=2)
        h = g.snakes[0].head
        g.apples.append(Apple(h.x + 1, h.y, "apple", 50))
        n0, n1 = len(g.snakes[0].body), len(g.snakes[1].body)
        g.step(); g.step()
        self.assertEqual(g.snakes[0].score, 1)
        self.assertEqual(len(g.snakes[0].body), n0 + 1)
        self.assertEqual(len(g.snakes[1].body), n1)
        h = g.snakes[0].head
        g.apples.clear()
        g.apples.append(Apple(h.x + 1, h.y, "apple", 51))
        g.step()
        self.assertTrue(g.over)
        self.assertEqual(g.winner, 0)

    def test_dead_snakes_do_not_block(self):
        g = versus([0, 1])
        g.snakes[1].dead = True
        b = g.snakes[1].body[1]
        self.assertIsNone(g.solid_at(b.x, b.y))

    def test_random_matches_never_crash(self):
        rng = random.Random(5)
        for teams in ([0, 1], [0, 0, 1, 1], [0, 0, 0, 0, 1, 1, 1, 1], [0, 1, 1, 1]):
            for modes in ((), ("wall",), ("borderless", "cheese"), ("portal", "shield"), ("poison", "twin", "statue")):
                g = Game(20, 18, modes, 3, rng=random.Random(rng.random()), teams=teams)
                g.started = True
                for _ in range(400):
                    for i in range(len(teams)):
                        if rng.random() < 0.3:
                            g.input_for(i, rng.choice(["up", "down", "left", "right"]))
                    g.step()
                    g.events.clear()
                    if g.over:
                        break


class StateTests(unittest.TestCase):
    def test_state_round_trip(self):
        g = Game(16, 12, ("wall", "key"), 3, rng=random.Random(2), teams=[0, 0, 1])
        g.started = True
        g.snakes[0].name = "alice"
        for _ in range(5):
            g.step()
        st = json.loads(json.dumps(game_to_state(g)))  # must survive JSON
        client = Game(16, 12, (), 1, teams=[0, 1])
        apply_state(client, st)
        self.assertEqual(game_to_state(client)["snakes"], st["snakes"])
        self.assertEqual(sorted(map(tuple, game_to_state(client)["apples"])), sorted(map(tuple, st["apples"])))
        self.assertEqual(client.snakes[0].name, "alice")
        self.assertEqual(len(client.walls), len(g.walls))


if __name__ == "__main__":
    unittest.main()
