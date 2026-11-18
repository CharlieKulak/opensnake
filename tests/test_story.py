"""Story mode: the levels, their stars, the boss duels and what they pay."""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_server import ServerTestCase  # noqa: E402

from opensnake import bots, cosmetics as cos, duel, story  # noqa: E402
from opensnake.game import Wall  # noqa: E402
from opensnake.server import DuelRoom  # noqa: E402
from opensnake.speedrun import Run  # noqa: E402


def bot_level_run(level, seed=1, max_ticks=6000) -> dict:
    """A run file of the bot playing a story level."""
    run = Run(level.category, seed)
    g = run.game
    rng = random.Random(seed)
    run.input("up")
    while not g.over and g.tick < max_ticks:
        d = bots.choose(g, 0, rng, "hard")
        if d and d != (g.snakes[0].planned or g.snakes[0].dir):
            run.input(d)
        run.step()
        g.events.clear()
    data = run.to_json("bot")
    data["finished"] = run.finished
    return data


def finished_run(level_id) -> dict:
    for seed in range(1, 40):
        data = bot_level_run(story.LEVEL_BY_ID[level_id], seed)
        if data.pop("finished"):
            return data
    raise AssertionError(f"the bot couldn't finish {level_id}")


class ContentTests(unittest.TestCase):
    def test_eight_chapters_of_ten_and_a_boss_each(self):
        self.assertEqual(len(story.CHAPTERS), 8)
        ids = [lv.id for ch in story.CHAPTERS for lv in ch.levels]
        self.assertEqual((len(ids), len(set(ids))), (80, 80))
        self.assertEqual(len(story.stage_ids()), 88)
        for ch in story.CHAPTERS:
            self.assertEqual(ch.boss.num, ch.num)
            for lv in ch.levels:
                self.assertEqual(len(lv.challenges), 2, lv.id)
                self.assertTrue(all(story.challenge_text(c) for c in lv.challenges))
                self.assertTrue(lv.category.id.startswith("story-"))

    def test_it_gets_harder(self):
        avg_tick = [sum(lv.tick_ms for lv in ch.levels) / 10 for ch in story.CHAPTERS]
        self.assertEqual(avg_tick, sorted(avg_tick, reverse=True))
        self.assertLess(avg_tick[-1], avg_tick[0] * 0.75)
        points = [dict(b.rewards)["points"] for b in story.BOSSES]
        self.assertEqual(points, sorted(points))
        self.assertGreaterEqual(points[-1], 2_000_000)
        self.assertEqual([story.STAR_POINTS[i] for i in range(1, 9)], sorted(story.STAR_POINTS.values()))

    def test_boss_skins_only_come_from_story_mode(self):
        for b in story.BOSSES:
            self.assertIn(b.skin, cos.STORY_ONLY)
            self.assertNotIn(b.skin, cos.UNTRADEABLE)  # (they can be sold and traded)
            self.assertIn(("item", b.skin), b.rewards)
            self.assertFalse(any(b.skin in cos.items_of(r) for r in cos.RARITIES))
        self.assertEqual(cos.skin_color(cos.SKIN_BY_ID["st_ouroboros"], 3, 10, 1234.0).__len__(), 3)

    def test_unlocking_goes_in_order(self):
        self.assertTrue(story.unlocked("s1-01", {}))
        self.assertFalse(story.unlocked("s1-02", {}))
        self.assertTrue(story.unlocked("s1-02", {"s1-01": 1}))
        nine = {f"s1-{i:02d}": 3 for i in range(1, 10)}
        self.assertFalse(story.unlocked("boss-1", nine))
        ten = nine | {"s1-10": 1}
        self.assertTrue(story.unlocked("boss-1", ten))
        self.assertFalse(story.unlocked("s2-01", ten))
        self.assertTrue(story.unlocked("s2-01", ten | {"boss-1": 1}))
        self.assertFalse(story.unlocked("nope", ten))

    def test_every_level_the_bot_can_play_is_finishable(self):
        for ch in story.CHAPTERS:
            for lv in ch.levels:
                if "sokoban" in lv.modes:
                    continue  # (the bot can't push crates)
                self.assertTrue(any(bot_level_run(lv, s).get("finished") for s in range(1, 40)), lv.id)


class StarTests(unittest.TestCase):
    def test_stars_come_from_the_replay(self):
        data = finished_run("s1-01")
        level, r = story.replay_level(data)
        self.assertTrue(r.finished)
        self.assertEqual(round(r.elapsed), data["time_ms"])
        self.assertEqual(len(r.splits), level.goal)
        stars = story.stars_for(level, r)
        self.assertTrue(stars[0])
        (kind, ms, _), _second = level.challenges
        self.assertEqual(stars[1], r.elapsed <= ms)

    def test_cheats_dont_check_out(self):
        data = finished_run("s1-01")
        with self.assertRaises(ValueError):
            story.replay_level({**data, "time_ms": data["time_ms"] - 100})
        with self.assertRaises(ValueError):
            story.replay_level({**data, "category": "sprint10"})
        with self.assertRaises(ValueError):
            story.replay_level({**data, "inputs": [[0, "sideways"]]})
        short = {**data, "inputs": data["inputs"][:1]}  # (heads straight for the wall)
        _lv, r = story.replay_level(short)
        self.assertFalse(r.finished)
        self.assertEqual(story.stars_for(story.LEVEL_BY_ID["s1-01"], r), [False, False, False])

    def test_challenge_kinds(self):
        lv = story.Level("x", 1, 1, "x", 10, 10, (), 4, 1, 100.0,
                         challenges=(("turns", 5, 0), ("split", 2, 1000)))
        r = story.Result(True, 5000.0, 5, 0, [500.0, 900.0, 2000.0, 5000.0])
        self.assertEqual(story.stars_for(lv, r), [True, True, True])
        r = story.Result(True, 5000.0, 6, 1, [500.0, 1100.0, 2000.0, 5000.0])
        self.assertEqual(story.stars_for(lv, r), [True, False, False])
        lv2 = story.Level("x", 1, 1, "x", 10, 10, (), 4, 1, 100.0, challenges=(("noshield", 0, 0), ("time", 5000, 0)))
        self.assertEqual(story.stars_for(lv2, r), [True, False, True])


class DuelTests(unittest.TestCase):
    def test_combo_power(self):
        self.assertEqual([duel.chain_power(n) for n in range(1, 10)], [1, 2, 4, 6, 9, 12, 16, 20, 24])

    def test_attacks_cancel_incoming_first(self):
        d = duel.Duel(story.BOSSES[0], 5)
        d.sides[duel.YOU].incoming = [[3, 100, 200]]
        d.attack(duel.YOU, 2)
        self.assertEqual((d.sides[duel.YOU].pending, d.sides[duel.BOSS].pending), (1, 0))
        d.attack(duel.YOU, 6)
        self.assertEqual((d.sides[duel.YOU].pending, d.sides[duel.BOSS].pending), (0, 5))
        self.assertEqual(d.sides[duel.YOU].sent, 5)

    def test_junk_never_lands_next_to_your_head(self):
        d = duel.Duel(story.BOSSES[0], 3)
        d.start()
        g = d.you
        placed = d._place_junk(duel.YOU, 60)
        self.assertGreater(placed, 30)
        head = g.snakes[0].head
        for (x, y) in g.walls:
            self.assertGreater(abs(x - head.x) + abs(y - head.y), 3)

    def test_same_seed_same_duel(self):
        a, b = duel.simulate(story.BOSSES[2], 11), duel.simulate(story.BOSSES[2], 11)
        self.assertEqual((a.tick, a.winner, a.state()["sides"]), (b.tick, b.winner, b.state()["sides"]))

    def test_every_duel_ends_and_early_bosses_are_easier(self):
        rates = []
        for b in story.BOSSES:
            games = [duel.simulate(b, s) for s in range(12)]
            self.assertTrue(all(g.over for g in games), b.name)
            rates.append(sum(g.winner == duel.YOU for g in games))
        self.assertGreater(rates[0], rates[-1])
        self.assertGreater(rates[-1], 0)  # (the last boss can be beaten)

    def test_signature_attacks(self):
        def fired(attack):
            b = story.BOSSES[0].__class__(**{**story.BOSSES[0].__dict__, "attack": attack})
            d = duel.Duel(b, 2)
            d.start()
            d._signature()
            return d
        self.assertEqual(fired("pebbles").sides[duel.YOU].pending, 3)
        venom = fired("venom")
        self.assertTrue(any(a.poison for a in venom.you.apples))
        self.assertTrue(any(not a.poison for a in venom.you.apples))
        self.assertTrue(fired("scramble").you.arrows)
        ice = fired("icewall")
        self.assertTrue(ice.you.walls and ice.sides[duel.YOU].temp)
        self.assertGreater(fired("eclipse").state()["sides"][0]["fog"], 0)
        oc = fired("overclock")
        self.assertLess(oc.speed(), 1.0)
        self.assertLess(oc.state()["tick_ms"], story.BOSSES[0].tick_ms)
        # ice melts
        for _ in range(ice.secs(duel.ICE_SECONDS) + 1):
            ice.tick += 1
            ice._expire(duel.YOU)
        self.assertFalse(ice.sides[duel.YOU].temp)


class StoryServerTests(ServerTestCase):
    async def test_levels_pay_each_star_once(self):
        token = await self.account("alice")
        status, view = await self.get("/api/story")
        self.assertEqual((status, len(view["chapters"]), view["stars"]), (200, 8, 0))
        self.assertTrue(view["chapters"][0]["levels"][0]["unlocked"])
        self.assertFalse(view["chapters"][0]["levels"][1]["unlocked"])
        run2 = finished_run("s1-02")
        self.assertIn("isn't unlocked", (await self.post("/api/story/run", run2, token))[1]["error"])
        run = finished_run("s1-01")
        status, r = await self.post("/api/story/run", run, token)
        self.assertEqual((status, r["valid"]), (200, True), r)
        stars = sum(r["earned"])
        self.assertEqual(r["points_earned"], stars * story.STAR_POINTS[1])
        self.assertEqual((r["next"], r["next_unlocked"]), ("s1-02", True))
        status, again = await self.post("/api/story/run", run, token)
        self.assertEqual(again["points_earned"], 0)
        view = (await self.get("/api/story", token))[1]
        self.assertEqual(view["chapters"][0]["levels"][0]["stars"], stars)
        self.assertTrue(view["chapters"][0]["levels"][1]["unlocked"])
        bad = {**run, "time_ms": run["time_ms"] + 1}
        self.assertFalse((await self.post("/api/story/run", bad, token))[1]["valid"])
        self.assertEqual((await self.post("/api/story/run", run))[0], 401)

    async def test_boss_rewards_once(self):
        await self.account("alice")
        db = self.server.db
        before = db.points(1)
        boss = story.BOSSES[0]
        first = db.story_boss_won(1, boss)
        self.assertTrue(first["first"])
        self.assertEqual(first["points_earned"], 50_000)
        self.assertEqual(db.copies(1, boss.skin), 1)
        self.assertEqual(len(first["opened"]), 2)  # (the Gold Crate and the skin)
        again = db.story_boss_won(1, boss)
        self.assertFalse(again["first"])
        self.assertEqual(again["points_earned"], story.REMATCH_POINTS[1])
        self.assertEqual(db.copies(1, boss.skin), 1)
        self.assertGreaterEqual(db.points(1), before + 50_000 + story.REMATCH_POINTS[1])

    async def ws_until(self, ws, kind, limit=4000):
        for _ in range(limit):
            m = json.loads((await asyncio.wait_for(ws.receive(), 10)).data)
            if m["t"] == kind or m["t"] == "error":
                return m
        raise AssertionError(f"no {kind}")

    async def test_a_duel_over_the_websocket(self):
        DuelRoom.time_scale = 0.01
        self.addCleanup(setattr, DuelRoom, "time_scale", 1.0)
        token = await self.account("alice")
        db = self.server.db
        ws = await self.client.ws_connect(f"/ws?token={token}")
        await self.ws_until(ws, "welcome")
        await ws.send_json({"t": "duel", "boss": 1})
        self.assertIn("ten levels", (await self.ws_until(ws, "error"))["msg"])
        for i in range(1, 11):
            db.story_level_done(1, story.LEVEL_BY_ID[f"s1-{i:02d}"], [True, False, False], 9000)
        await ws.send_json({"t": "duel", "boss": 1})
        start = await self.ws_until(ws, "duel_start")
        self.assertEqual((start["boss"], len(start["state"]["sides"])), (1, 2))
        await self.ws_until(ws, "duel_state")
        # box the boss in: it crashes straight away, and you win
        room = next(iter(self.server.connected[1])).room
        g = room.duel.sides[duel.BOSS].game
        head = g.snakes[0].head
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if g.in_bounds(head.x + dx, head.y + dy) and not g.snake_at(head.x + dx, head.y + dy):
                g.walls[(head.x + dx, head.y + dy)] = Wall(head.x + dx, head.y + dy)
        over = await self.ws_until(ws, "duel_over")
        self.assertTrue(over["won"])
        self.assertTrue(over["first"])
        self.assertEqual(db.copies(1, story.BOSSES[0].skin), 1)
        self.assertTrue((await self.get("/api/story", token))[1]["chapters"][0]["boss"]["beaten"])
        # a lost duel pays nothing (just don't steer: into the wall you go)
        points = db.points(1)
        await ws.send_json({"t": "duel", "boss": 1})
        over = await self.ws_until(ws, "duel_over")
        self.assertFalse(over["won"])
        self.assertEqual(db.points(1), points)
        await ws.close()


if __name__ == "__main__":
    unittest.main()


class BattleTests(unittest.TestCase):
    def test_junk_spreads_round_and_the_last_snake_wins(self):
        b = duel.Battle(4, 14, 11, (), 3, 100.0, seed=4, names=["a", "b", "c", "d"])
        b.start()
        b.attack(0, 3)
        b.attack(0, 3)  # (the next lot goes to whoever has the least coming)
        self.assertEqual(sorted(s.pending for s in b.sides[1:]), [0, 3, 3])
        b.forfeit(2)
        self.assertNotIn(2, b.alive())
        self.assertFalse(b.over)
        b.forfeit(1)
        b.forfeit(3)
        self.assertTrue(b.over)
        self.assertEqual(b.winner, 0)
        self.assertEqual([b.place(i) for i in range(4)], [1, 3, 4, 2])  # (out: 2 first, then 1, then 3)

    def test_bots_battle_to_the_end(self):
        for n in (2, 3, 4):
            b = duel.Battle(n, 16, 12, ("wall",), 3, 100.0, seed=n)
            b.start()
            while not b.over and b.tick < 20_000:
                for i in range(n):
                    b.steer_bot(i, ["easy", "normal", "hard", "hard"][i], duel.BOT_SLOPPY[["easy", "normal", "hard", "hard"][i]])
                b.step()
                b.clear_events()
            self.assertTrue(b.over, n)
            self.assertEqual(len(b.state()["sides"]), n)


class OnlineBattleTests(StoryServerTests.__mro__[1]):
    async def test_a_four_way_battle_online(self):
        from opensnake.server import Room
        Room.time_scale = 0.01
        self.addCleanup(setattr, Room, "time_scale", 1.0)
        token = await self.account("alice")
        ws = await self.client.ws_connect(f"/ws?token={token}")
        await StoryServerTests.ws_until(self, ws, "welcome")
        await ws.send_json({"t": "host", "settings": {"format": "battle", "size": "small", "speed": 1.0},
                            "bots": [{"team": 1, "level": "easy"}, {"team": 0, "level": "normal"}, {"team": 1, "level": "hard"}]})
        room = await StoryServerTests.ws_until(self, ws, "room")
        self.assertEqual((room["settings"]["format"], len(room["players"])), ("battle", 4))
        await ws.send_json({"t": "add_bot", "team": 0, "level": "easy"})
        self.assertIn("full", (await StoryServerTests.ws_until(self, ws, "error"))["msg"])
        await ws.send_json({"t": "start"})
        start = await StoryServerTests.ws_until(self, ws, "duel_start")
        self.assertEqual((start["mode"], start["you"], len(start["players"]), len(start["state"]["sides"])), ("battle", 0, 4, 4))
        await StoryServerTests.ws_until(self, ws, "duel_state")
        await ws.send_json({"t": "input", "d": "up"})  # (steering your own board)
        over = await StoryServerTests.ws_until(self, ws, "duel_over", limit=40_000)
        self.assertIn(over["place"], (1, 2, 3, 4))
        self.assertEqual(over["won"], over["place"] == 1)
        self.assertGreater(over["points_earned"], 0)
        await ws.close()


def play_duel_offline(boss, seed):
    """Play a duel the way a game does on its own: (turns pressed, who won)."""
    d = duel.Duel(boss, seed)
    d.start()
    rng, inputs = random.Random(seed), []
    while not d.over and d.tick < 20_000:
        g = d.you
        if not g.over:
            m = bots.choose(g, 0, rng, "hard")
            if m:
                inputs.append([d.tick, m])
                g.input_for(0, m)
        d.step()
        d.clear_events()
    return inputs, d.winner


class OfflineDuelTests(StoryServerTests.__mro__[1]):
    async def test_a_duel_played_offline_is_checked_and_paid(self):
        token = await self.account("alice")
        db = self.server.db
        self.assertIn("ten levels", (await self.post("/api/story/duel/start", {"boss": 1}, token))[1]["error"])
        for i in range(1, 11):
            db.story_level_done(1, story.LEVEL_BY_ID[f"s1-{i:02d}"], [True, False, False], 9000)
        for _ in range(15):
            st = (await self.post("/api/story/duel/start", {"boss": 1}, token))[1]
            inputs, winner = play_duel_offline(story.BOSSES[0], st["seed"])
            if winner == duel.YOU:
                break
            res = (await self.post("/api/story/duel/finish", {"token": st["token"], "inputs": inputs}, token))[1]
            self.assertFalse(res["won"])
        else:
            self.fail("the bot never beat the first boss")
        # sent straight back: faster than it could have been played
        res = (await self.post("/api/story/duel/finish", {"token": st["token"], "inputs": inputs}, token))[1]
        self.assertIn("faster than it could be played", res["message"])
        st = (await self.post("/api/story/duel/start", {"boss": 1}, token))[1]
        inputs, winner = play_duel_offline(story.BOSSES[0], st["seed"])
        t = self.server.duel_starts[st["token"]]
        self.server.duel_starts[st["token"]] = (*t[:3], t[3] - 600)  # (as if it took ten minutes)
        res = (await self.post("/api/story/duel/finish", {"token": st["token"], "inputs": inputs}, token))[1]
        self.assertEqual(res["won"], winner == duel.YOU)
        if res["won"]:
            self.assertTrue(res["first"])
            self.assertEqual(db.copies(1, story.BOSSES[0].skin), 1)
        # a token is good once, and only for its player
        self.assertIn("wasn't started", (await self.post("/api/story/duel/finish", {"token": st["token"], "inputs": inputs}, token))[1]["error"])


class PresenceTests(StoryServerTests.__mro__[1]):
    def long_session(self, uid, hours=2.6):
        now = asyncio.get_running_loop().time()
        self.server.sessions[uid] = {"start": now - hours * 3600, "last": now - 60, "check": None}

    async def test_still_here_after_two_and_a_half_hours(self):
        from test_social import played_round
        token = await self.account("alice")
        self.long_session(1)
        res = (await self.post("/api/rounds", {"round": played_round(1, 5)[0]}, token))[1]
        self.assertEqual(res["earned"], 0)
        self.assertIn("Are you still here", res["message"])
        check = (await self.get("/api/presence", token))[1]["check"]
        self.assertEqual(len(check["choices"]), 4)
        self.assertIn(check["code"], check["choices"])
        self.assertGreater(check["seconds"], 15)
        wrong = next(c for c in check["choices"] if c != check["code"])
        self.assertFalse((await self.post("/api/presence", {"answer": wrong}, token))[1]["ok"])
        self.assertTrue((await self.post("/api/presence", {"answer": check["code"]}, token))[1]["ok"])
        self.assertIsNone((await self.get("/api/presence", token))[1]["check"])
        self.assertGreater((await self.post("/api/rounds", {"round": played_round(2, 5)[0]}, token))[1]["earned"], 0)

    async def test_no_answer_takes_back_six_hours(self):
        await self.account("alice")
        db = self.server.db
        db.add_points(1, 5_000, "round")
        db.add_points(1, 2_000, "market: sold skin:mint")  # (sales between players stay)
        old = (datetime.now(timezone.utc) - timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        db.db.execute("INSERT INTO ledger (user_id, amount, reason, created) VALUES (1, 0, 'round', ?)", (old,))
        db.db.execute("UPDATE users SET points = points + 3000 WHERE id = 1")  # (earned 7 hours ago: stays)
        db.db.commit()
        self.long_session(1)
        await self.server.note_play(1)
        now = asyncio.get_running_loop().time()
        self.server.sessions[1]["check"]["shown"] = now - 30  # (shown 30 s ago, never answered)
        await self.server.sweep_presence()
        self.assertEqual(db.points(1), 5_000)
        self.assertIsNone(self.server.sessions[1]["check"])

    async def test_playing_on_without_ever_showing_it(self):
        await self.account("alice")
        db = self.server.db
        db.add_points(1, 4_000, "versus win")
        self.long_session(1)
        await self.server.note_play(1)
        self.server.sessions[1]["check"]["created"] -= 200  # (asked 200 s ago; the game never showed it)
        msg = await self.server.note_play(1)
        self.assertIn("taken back", msg)
        self.assertEqual(db.points(1), 0)

    async def test_a_break_clears_it(self):
        await self.account("alice")
        self.long_session(1)
        await self.server.note_play(1)
        self.server.sessions[1]["last"] -= 20 * 60
        self.assertIsNone(await self.server.note_play(1))
        self.assertIsNone(self.server.sessions[1]["check"])
