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


class LagCompensationTests(unittest.TestCase):
    """A turn that reaches the server a move or two late still happens where it was pressed, when that's fair."""

    def path(self, g, i=0):
        return [(p.x, p.y) for p in g.snakes[i].body]

    def test_a_late_turn_is_applied_where_it_was_meant(self):
        on_time, late = versus([0, 1]), versus([0, 1])
        for g in (on_time, late):
            g.step()
            g.step()
        on_time.input_for(0, "up")  # arrives in time for move 3
        on_time.step()
        late.step()                  # move 3 happens first (straight on)...
        self.assertTrue(late.retro_turn(0, "up", 1))  # ...then the turn meant for it arrives
        self.assertEqual(self.path(late), self.path(on_time))
        self.assertEqual(late.snakes[0].dir, "up")

    def test_only_one_move_back(self):
        # players' games aim turns at a move they can reach in time; rewinding further
        # would make that snake jump on everyone else's screen
        g = versus([0, 1])
        for _ in range(3):
            g.step()
        self.assertFalse(g.retro_turn(0, "down", 2))

    def test_only_when_fair(self):
        g = versus([0, 1])
        g.step()
        self.assertFalse(g.retro_turn(0, "up", 2))     # only one move to undo
        self.assertFalse(g.retro_turn(0, "left", 1))   # a reverse is never allowed
        self.assertFalse(g.retro_turn(0, "right", 1))  # not a turn
        g.input_for(0, "up")
        g.step()
        self.assertFalse(g.retro_turn(0, "left", 1))   # it turned meanwhile
        g = versus([0, 1])
        g.step()
        x, y = g.snakes[0].head.x, g.snakes[0].head.y
        g.apples.append(Apple(x, y - 1, "apple", 0))  # the new path (up from here) would eat a fruit
        g.step()
        self.assertFalse(g.retro_turn(0, "up", 1))
        g = versus([0, 1])
        g.step()
        x, y = g.snakes[0].head.x, g.snakes[0].head.y
        g.apples.append(Apple(x + 1, y, "apple", 0))  # the late move ate: no take-backs
        g.step()
        self.assertFalse(g.retro_turn(0, "up", 1))
        g = versus([0, 1], h=6)
        while g.snakes[0].head.y > 0:  # against the top wall: the new path would leave the board
            g.input_for(0, "up")
            g.step()
        g.input_for(0, "right")
        g.step()
        g.step()
        self.assertFalse(g.retro_turn(0, "up", 1))
        self.assertFalse(g.over)

    def test_the_server_uses_the_turn_step(self):
        """End to end through the server's message handler, with a turn that arrives a move late."""
        import asyncio
        from opensnake.server import Player, Room, Server
        import tempfile
        from pathlib import Path
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        server = Server(Path(tmp.name), None)
        self.addCleanup(server.db.close)
        host = Player(None, 1, "a")
        room = Room(server, "ABCD", host)
        room.game = versus([0, 1])
        room.state = "playing"
        host.room, host.snake = room, 0
        room.game.step()
        room.game.step()  # the player saw tick 1 and meant the turn for move 2
        asyncio.run(server.on_message(host, {"t": "input", "d": "up", "step": 2}))
        self.assertEqual(room.game.snakes[0].dir, "up")
        self.assertEqual(room.game.snakes[0].queue, [])  # applied, not queued for later
        # a turn sent ahead for a later move waits for it
        asyncio.run(server.on_message(host, {"t": "input", "d": "right", "step": room.game.tick + 2}))
        room.apply_scheduled()
        room.game.step()
        self.assertEqual(room.game.snakes[0].dir, "up")     # not yet...
        room.apply_scheduled()
        room.game.step()
        self.assertEqual(room.game.snakes[0].dir, "right")  # ...now


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


