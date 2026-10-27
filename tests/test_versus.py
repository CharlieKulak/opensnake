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


class PredictionTests(unittest.TestCase):
    """The joining player's own snake reacts to their keys at once (client-side prediction)."""

    def setUp(self):
        import os
        import tempfile
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["OPENSNAKE_CONFIG_DIR"] = self.tmp.name
        from opensnake.app import App
        self.app = App()
        self.on = self.app.online
        self.server = Game(20, 16, (), 1, rng=random.Random(1), teams=[0, 1])  # stands in for the server
        self.sent = []

        class FakeSocket:
            state = "open"
            inbox = []
            def send(_, m): self.sent.append(m)
            def poll(_):
                out, FakeSocket.inbox = FakeSocket.inbox, []
                return out
        self.sock = FakeSocket
        self.on.sock = FakeSocket()
        self.on.my_id = 1
        self.on.on_message({"t": "start", "you": 1, "tick_ms": 130, "state": game_to_state(self.server)})

    def tearDown(self):
        self.tmp.cleanup()

    def server_step(self):
        for m in self.sent:
            if m["t"] == "input":
                self.server.input_for(1, m["d"])
        self.sent.clear()
        self.server.started = True
        self.server.step()
        return {"t": "state", "s": game_to_state(self.server)}

    def test_turn_shows_immediately_then_server_confirms(self):
        me = lambda: self.on.game.snakes[1]
        self.assertEqual(me().dir, "left")
        self.on.turn("up")
        self.assertEqual(self.sent, [{"t": "input", "d": "up"}])  # still sent to the server
        self.assertEqual(me().planned, "up")                       # ...but shown right away
        self.on.on_message(self.server_step())                     # server applies it
        self.assertEqual(me().dir, "up")
        self.assertEqual(self.on.pending, [])

    def test_prediction_survives_states_until_applied(self):
        self.on.turn("down")
        self.sent.clear()  # pretend the input is still on its way: the server hasn't seen it
        self.server.started = True
        self.server.step()
        self.on.on_message({"t": "state", "s": game_to_state(self.server)})
        self.assertEqual(self.on.game.snakes[1].dir, "left")
        self.assertEqual(self.on.game.snakes[1].planned, "down")  # still predicted

    def test_unapplied_turn_is_dropped_eventually(self):
        import pygame
        self.on.turn("up")
        self.sent.clear()
        self.on.pending = [("up", pygame.time.get_ticks() - 10_000)]  # sent long ago, never applied
        self.server.started = True
        self.server.step()
        self.on.on_message({"t": "state", "s": game_to_state(self.server)})
        self.assertEqual(self.on.pending, [])
        self.assertIsNone(self.on.game.snakes[1].planned)

    def test_reverse_is_not_predicted(self):
        self.on.turn("right")  # straight back into yourself: the server ignores it, so do we
        self.assertEqual(self.sent, [])
        self.assertEqual(self.on.pending, [])

    def test_backlog_draws_only_the_newest_state(self):
        self.server.started = True
        h = self.server.snakes[1].head
        self.server.apples.append(Apple(h.x - 1, h.y, "apple", 99))
        msgs = [self.server_step() for _ in range(3)]  # first one has an "eat" event
        self.assertTrue(any(e[0] == "eat" for e in msgs[0]["s"]["events"]))
        applied = []
        real = self.on.on_message
        self.on.on_message = lambda m: (applied.append(m["t"]), real(m))
        self.sock.inbox = msgs
        played = []
        self.app.sfx.play = played.append
        self.on.poll()
        self.assertEqual(applied, ["state"])                      # one state drawn, not three
        self.assertEqual(self.on.game.tick, self.server.tick)     # the newest one
        self.assertIn("eat", played)                              # the skipped one's sound still plays
