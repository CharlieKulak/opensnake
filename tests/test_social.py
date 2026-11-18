"""Snake points, the store, profiles, friends, bots, ranks and community categories (server side)."""

import random
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_server import ServerTestCase, VersusTests  # noqa: E402
from test_speedrun import bot_run  # noqa: E402

from opensnake import cosmetics as cos  # noqa: E402
from opensnake.speedrun import CATEGORY_BY_ID, make_custom  # noqa: E402


class CatalogueTests(ServerTestCase):
    def test_skins_with_the_rarest_only_in_loot_boxes(self):
        self.assertEqual(len(cos.SKINS), 147)
        self.assertEqual(len({s.id for s in cos.SKINS}), 147)
        stands = [s for s in cos.SKINS if s.series == "Stand"]
        self.assertEqual(len(stands), 34)
        self.assertTrue(all(not s.shop for s in stands))
        for s in cos.SKINS:
            self.assertIn(s.rarity, cos.RARITIES)
            if s.rarity in ("epic", "legendary", "mythic") or s.series in ("Pass", "Ranked", "Holiday", "Gift", "Story"):
                self.assertFalse(s.shop, s.id)
            else:
                self.assertTrue(s.shop, s.id)
        self.assertEqual(len(cos.RANKS), 8)

    def test_loot_box_odds(self):
        for crate in cos.CRATES:
            self.assertAlmostEqual(sum(crate.odds.values()), 100, places=6)
        rng = random.Random(1)
        got = Counter(cos.item_rarity(cos.roll(cos.CRATE_BY_ID["bronze"], rng)) for _ in range(20000))
        self.assertAlmostEqual(got["common"] / 20000, 0.70, delta=0.02)
        self.assertNotIn("common", {cos.item_rarity(cos.roll(cos.CRATE_BY_ID["diamond"], rng)) for _ in range(2000)})
        royal = Counter(cos.item_rarity(cos.roll(cos.CRATE_BY_ID["royal"], rng)) for _ in range(5000))
        self.assertEqual(set(royal), {"legendary", "mythic"})  # legendary and above only
        self.assertAlmostEqual(royal["mythic"] / 5000, 0.15, delta=0.02)
        self.assertEqual(cos.CRATE_BY_ID["royal"].price, 500_000)

    def test_packs(self):
        sold = [p for p in cos.PACKS if p.price]
        self.assertEqual(len(sold), 4)
        self.assertTrue(all(p.rarity not in ("epic", "legendary", "mythic") for p in sold))


    def test_skin_colours_are_valid(self):
        for s in cos.SKINS:
            for i in range(12):
                c = cos.skin_color(s, i, 12, 1234.0 * i)
                self.assertEqual(len(c), 3)
                self.assertTrue(all(0 <= v <= 255 for v in c), (s.id, c))


class PointsTests(ServerTestCase):
    async def test_rounds_pay_points_but_not_too_fast(self):
        token = await self.account()
        status, res = await self.post("/api/rounds", {"fruit": 7}, token)
        self.assertEqual((status, res["earned"]), (200, cos.round_points(7)))
        self.assertEqual((await self.post("/api/rounds", {"fruit": 7}, token))[1]["earned"], 0)  # too soon
        self.assertEqual((await self.get("/api/me", token))[1]["points"], cos.round_points(7))
        self.assertEqual((await self.post("/api/rounds", {"fruit": 1}))[0], 401)

    async def test_speedrun_pr_and_wr_rewards(self):
        a, b = await self.account("alice"), await self.account("bob")
        cat = CATEGORY_BY_ID["sprint10"]
        slow = bot_run(cat, 4, random.Random(3))
        res = (await self.post("/api/runs", slow.to_json(), a))[1]
        self.assertEqual(res["earned"], cos.PR_REWARD + cos.WR_REWARD)  # first run: a PB and 1st place
        res = (await self.post("/api/runs", slow.to_json(), b))[1]   # same time: a PB, and 2nd place
        self.assertEqual(res["earned"], cos.PR_REWARD + cos.WR_REWARD // 2)
        res = (await self.post("/api/runs", slow.to_json(), b))[1]   # no improvement
        self.assertEqual(res["earned"], 0)

    async def test_community_categories_pay_nothing_but_keep_records(self):
        token = await self.account()
        cat = make_custom(10, 9, ["wall"], 3, 1, 130, name="Wally")
        res = (await self.post("/api/runs", bot_run(cat, 4, random.Random(3)).to_json(), token))[1]
        self.assertTrue(res["valid"])
        self.assertEqual(res["earned"], 0)
        listed = (await self.get("/api/categories"))[1]["categories"]
        self.assertEqual([(c["name"], c["creator"], c["wr"]["player"]) for c in listed], [("Wally", "alice", "alice")])
        self.assertEqual((await self.get("/api/categories?q=nothing"))[1]["categories"], [])

    async def test_world_record_holders_get_paid_every_three_days(self):
        token = await self.account()
        await self.post("/api/runs", bot_run(CATEGORY_BY_ID["sprint10"], 4, random.Random(3)).to_json(), token)
        db = self.server.db
        start = db.points(1)
        now = datetime.now(timezone.utc)
        self.assertEqual(db.settle_wr_holds(now + timedelta(days=2)), [])
        db.settle_wr_holds(now + timedelta(days=7))  # two full 3-day periods
        self.assertEqual(db.points(1), start + 2 * cos.WR_HOLD_REWARD)
        db.settle_wr_holds(now + timedelta(days=8))  # nothing new yet
        self.assertEqual(db.points(1), start + 2 * cos.WR_HOLD_REWARD)


class StoreTests(ServerTestCase):
    async def test_buying_and_equipping(self):
        token = await self.account()
        self.assertIn("Not enough", (await self.post("/api/store/buy", {"item": "skin:mint"}, token))[1]["error"])
        self.server.db.add_points(1, 5000, "test")
        self.assertEqual((await self.post("/api/store/buy", {"item": "skin:mint"}, token))[1]["points"], 4500)
        self.assertIn("already", (await self.post("/api/store/buy", {"item": "skin:mint"}, token))[1]["error"])
        self.assertIn("isn't sold", (await self.post("/api/store/buy", {"item": "skin:celestial"}, token))[1]["error"])
        self.assertIn("isn't sold", (await self.post("/api/store/buy", {"item": "pack:goldenhour"}, token))[1]["error"])
        self.assertIn("Not enough", (await self.post("/api/store/buy", {"item": "pack:meadow"}, token))[1]["error"])
        self.server.db.add_points(1, 6_000, "test")
        status, res = await self.post("/api/store/buy", {"item": "pack:meadow"}, token)  # packs are sold too
        self.assertEqual((status, res["points"]), (200, 4500))
        self.assertIn("pack:meadow", (await self.get("/api/me", token))[1]["inventory"])
        status, me = await self.post("/api/profile", {"skin": "mint"}, token)
        self.assertEqual((status, me["skin"]), (200, "mint"))
        self.assertIn("don't own", (await self.post("/api/profile", {"skin": "sky"}, token))[1]["error"])

    async def test_loot_boxes_and_duplicates(self):
        token = await self.account()
        db = self.server.db
        db.add_points(1, 10_000, "test")
        status, res = await self.post("/api/store/open", {"crate": "bronze"}, token)
        self.assertEqual(status, 200)
        self.assertIn(res["item"], cos.ALL_ITEMS)
        self.assertTrue(res["new"])
        self.assertIn(res["item"], (await self.get("/api/me", token))[1]["inventory"])
        # a duplicate is another copy
        before = db.points(1)
        dup = db.open_crate(1, "bronze", FixedRoll(res["item"]))
        self.assertFalse(dup["new"])
        self.assertEqual((dup["points"], dup["copies"]), (before - 2000, 2))
        me = (await self.get("/api/me", token))[1]
        self.assertEqual(me["inventory"].count(res["item"]), 1)  # (older games see it once)
        self.assertEqual(me["counts"][res["item"]], 2)
        self.assertIn("Unknown", (await self.post("/api/store/open", {"crate": "nope"}, token))[1]["error"])


class FixedRoll(random.Random):
    """Makes a loot box give a particular item."""

    def __init__(self, item):
        super().__init__(0)
        self.item = item

    def choices(self, population, weights=None, k=1):
        return [cos.item_rarity(self.item)]

    def choice(self, seq):
        return self.item


class ProfileTests(ServerTestCase):
    async def test_profile_search_and_friends(self):
        a, b = await self.account("alice"), await self.account("bobby")
        await self.account("alicia")
        status, me = await self.post("/api/profile", {"bio": " Hi\n  there\x00 ", "avatar": "trophy:3"}, a)
        self.assertEqual((me["bio"], me["avatar"]), ("Hi there", "trophy:3"))
        me = (await self.post("/api/profile", {"avatar": "bogus:99"}, a))[1]
        self.assertEqual(me["avatar"], "opensnake:0")
        self.assertEqual([u["name"] for u in (await self.get("/api/users?q=ali"))[1]["users"]], ["alice", "alicia"])
        self.assertEqual((await self.get("/api/users?q=_"))[1]["users"], [])  # "_" isn't a wildcard
        prof = (await self.get("/api/users/ALICE", b))[1]
        self.assertEqual((prof["name"], prof["rank"], prof["friend"]), ("alice", "Hatchling", "none"))

        self.assertEqual((await self.post("/api/friends/add", {"name": "alice"}, b))[1]["friend"], "outgoing")
        self.assertEqual([f["name"] for f in (await self.get("/api/friends", a))[1]["incoming"]], ["bobby"])
        self.assertEqual((await self.post("/api/friends/add", {"name": "bobby"}, a))[1]["friend"], "friends")
        self.assertEqual([f["name"] for f in (await self.get("/api/friends", b))[1]["friends"]], ["alice"])
        self.assertIn("you", (await self.post("/api/friends/add", {"name": "alice"}, a))[1]["error"])
        await self.post("/api/friends/remove", {"name": "alice"}, b)
        self.assertEqual((await self.get("/api/friends", a))[1]["friends"], [])


class BotAndInviteTests(ServerTestCase):
    recv = VersusTests.recv

    async def connect(self, token=None, name="Guest"):
        ws = await self.client.ws_connect(f"/ws?token={token}" if token else f"/ws?name={name}")
        await self.recv(ws, "welcome")
        return ws

    async def test_bot_match_pays_points_but_not_rank(self):
        token = await self.account()
        ws = await self.connect(token)
        await ws.send_json({"t": "host", "settings": {"size": "small", "speed": 1.0},
                            "bots": [{"team": 1, "level": "hard"}]})
        room = await self.recv(ws, "room")
        bots = [p for p in room["players"] if p["bot"]]
        self.assertEqual((len(bots), bots[0]["team"], bots[0]["rank"]), (1, 1, "Hard bot"))
        await ws.send_json({"t": "add_bot", "team": 0, "level": "easy"})
        room = await self.recv(ws, "room")
        self.assertEqual(len(room["players"]), 3)
        await ws.send_json({"t": "remove_bot", "id": bots[0]["id"]})
        await ws.send_json({"t": "add_bot", "team": 1, "level": "normal"})
        await ws.send_json({"t": "start"})
        reward = await self.recv(ws, "reward", timeout=60)  # I don't steer, so I crash; the bots play on
        self.assertFalse(reward["ranked"])
        self.assertEqual(reward["rp_change"], 0)
        self.assertGreaterEqual(reward["points"], cos.MATCH_PLAYED)
        self.assertEqual((await self.get("/api/me", token))[1]["points"], reward["balance"])
        await ws.close()

    async def test_matches_between_people_are_ranked(self):
        a, b = await self.account("alice"), await self.account("bobby")
        wa, wb = await self.connect(a), await self.connect(b)
        await wa.send_json({"t": "host", "settings": {"size": "small", "speed": 1.0}})
        code = (await self.recv(wa, "room"))["code"]
        await wb.send_json({"t": "join", "code": code})
        await self.recv(wb, "room")
        await wa.send_json({"t": "start"})
        ra, rb = await self.recv(wa, "reward", timeout=30), await self.recv(wb, "reward", timeout=30)
        self.assertTrue(ra["ranked"] and rb["ranked"])
        changes = sorted([ra["rp_change"], rb["rp_change"]])
        self.assertIn(changes, ([cos.RP_LOSS, cos.RP_WIN], [cos.RP_DRAW, cos.RP_DRAW]))
        for ws in (wa, wb):
            await ws.close()

    async def test_invites_reach_online_friends_only(self):
        a, b = await self.account("alice"), await self.account("bobby")
        wa = await self.connect(a)
        await wa.send_json({"t": "host"})
        room = await self.recv(wa, "room")
        await wa.send_json({"t": "invite", "name": "bobby"})
        self.assertIn("friends", (await self.recv(wa, "error"))["msg"])
        await self.post("/api/friends/add", {"name": "bobby"}, a)
        await self.post("/api/friends/add", {"name": "alice"}, b)
        await wa.send_json({"t": "invite", "name": "bobby"})
        self.assertIn("isn't online", (await self.recv(wa, "error"))["msg"])
        wb = await self.connect(b)
        await wb.send_json({"t": "hello"})
        self.assertTrue((await self.get("/api/friends", a))[1]["friends"][0]["online"])
        await wa.send_json({"t": "invite", "name": "bobby"})
        await self.recv(wa, "invited")
        invite = await self.recv(wb, "invite")
        self.assertEqual((invite["from"], invite["code"]), ("alice", room["code"]))
        for ws in (wa, wb):
            await ws.close()


class PictureTests(ServerTestCase):
    @staticmethod
    def png(w, h, extra=b""):
        return (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + w.to_bytes(4, "big") + h.to_bytes(4, "big")
                + b"\x08\x06\x00\x00\x00" + extra)

    async def test_own_pictures(self):
        import base64
        token = await self.account()
        pic = self.png(128, 128, b"pixels")
        status, me = await self.post("/api/profile/picture", {"png": base64.b64encode(pic).decode()}, token)
        self.assertEqual(status, 200, me)
        version = cos.custom_picture(me["avatar"])
        self.assertTrue(version)
        status, got = await self.get("/api/pictures/ALICE")
        self.assertEqual((status, got["version"], base64.b64decode(got["png"])), (200, version, pic))
        self.assertEqual((await self.get("/api/users?q=alice"))[1]["users"][0]["avatar"], me["avatar"])
        # back to an icon; the picture stays stored for next time
        self.assertEqual((await self.post("/api/profile", {"avatar": "skull:2"}, token))[1]["avatar"], "skull:2")
        self.assertEqual((await self.get("/api/pictures/alice"))[0], 200)

    async def test_bad_pictures(self):
        import base64
        token = await self.account()
        for data, why in ((base64.b64encode(b"GIF89a....").decode(), "PNG"),
                          ("not base64!", "PNG"),
                          (base64.b64encode(self.png(2000, 10)).decode(), "512"),
                          (base64.b64encode(self.png(64, 64, b"x" * 300_000)).decode(), "too big")):
            status, res = await self.post("/api/profile/picture", {"png": data}, token)
            self.assertEqual(status, 400)
            self.assertIn(why, res["error"])
        self.assertEqual((await self.post("/api/profile/picture", {"png": ""})) [0], 401)
        self.assertEqual((await self.get("/api/pictures/alice"))[0], 404)


class RenameCategoryTests(ServerTestCase):
    async def test_only_the_creator_can_rename(self):
        alice, bob = await self.account("alice"), await self.account("bobby")
        cat = make_custom(10, 9, ["wall"], 3, 1, 130, name="Wally")
        await self.post("/api/runs", bot_run(cat, 4, random.Random(3)).to_json(), alice)
        status, res = await self.post("/api/categories/rename", {"id": cat.id, "name": "  Wall   Sprint\n"}, alice)
        self.assertEqual((status, res["name"]), (200, "Wall Sprint"))
        listed = (await self.get("/api/categories"))[1]["categories"][0]
        self.assertEqual((listed["name"], listed["def"]["name"], listed["wr"]["player"]),
                         ("Wall Sprint", "Wall Sprint", "alice"))  # the record stays
        self.assertEqual((await self.get("/api/categories?q=sprint"))[1]["categories"][0]["id"], cat.id)
        self.assertEqual((await self.post("/api/categories/rename", {"id": cat.id, "name": "Mine"}, bob))[0], 403)
        self.assertEqual((await self.post("/api/categories/rename", {"id": "custom-nope", "name": "x"}, alice))[0], 404)
        self.assertEqual((await self.post("/api/categories/rename", {"id": cat.id, "name": "   "}, alice))[0], 400)
        self.assertEqual((await self.post("/api/categories/rename", {"id": cat.id, "name": "x"}))[0], 401)
        long = (await self.post("/api/categories/rename", {"id": cat.id, "name": "y" * 99}, alice))[1]["name"]
        self.assertEqual(len(long), 40)
        # someone else running it later doesn't change its name back
        await self.post("/api/runs", bot_run(cat, 5, random.Random(4)).to_json(), bob)
        self.assertEqual((await self.get("/api/categories"))[1]["categories"][0]["name"], long)


class MessageTests(ServerTestCase):
    recv = VersusTests.recv

    async def friends(self):
        a, b = await self.account("alice"), await self.account("bobby")
        await self.post("/api/friends/add", {"name": "bobby"}, a)
        await self.post("/api/friends/add", {"name": "alice"}, b)
        return a, b

    async def test_friends_only_and_limits(self):
        a = await self.account("alice")
        await self.account("bobby")
        status, res = await self.post("/api/messages", {"to": "bobby", "body": "hi"}, a)
        self.assertEqual(status, 403)
        self.assertIn("friends", res["error"])
        self.assertEqual((await self.post("/api/messages", {"to": "nobody", "body": "hi"}, a))[0], 404)
        self.assertEqual((await self.post("/api/messages", {"to": "bobby", "body": "hi"}))[0], 401)
        b = await self.account("carol")
        await self.post("/api/friends/add", {"name": "carol"}, a)
        await self.post("/api/friends/add", {"name": "alice"}, b)
        self.assertEqual((await self.post("/api/messages", {"to": "carol", "body": " \n\x00 "}, a))[0], 400)
        sent = (await self.post("/api/messages", {"to": "carol", "body": "x" * 900}, a))[1]
        self.assertEqual(len(sent["body"]), 500)
        self.assertEqual((await self.post("/api/messages", {"to": "carol", "body": "again"}, a))[0], 429)  # too fast

    async def test_chat_unread_live_and_history(self):
        a, b = await self.friends()
        wb = await self.client.ws_connect(f"/ws?token={b}")
        await self.recv(wb, "welcome")
        await wb.send_json({"t": "hello"})
        self.server.last_message.clear()
        sent = (await self.post("/api/messages", {"to": "bobby", "body": "hey bob"}, a))[1]
        live = await self.recv(wb, "dm")
        self.assertEqual((live["from"], live["to"], live["body"], live["id"]), ("alice", "bobby", "hey bob", sent["id"]))
        chats = (await self.get("/api/messages", b))[1]
        self.assertEqual((chats["unread"], chats["chats"][0]["name"], chats["chats"][0]["last"]["body"]),
                         (1, "alice", "hey bob"))
        msgs = (await self.get("/api/messages/alice", b))[1]["messages"]
        self.assertEqual([m["body"] for m in msgs], ["hey bob"])
        self.assertEqual((await self.get("/api/messages", b))[1]["unread"], 0)  # reading clears it
        for i in range(60):  # a long chat: pages of 50, oldest first
            self.server.last_message.clear()
            await self.post("/api/messages", {"to": "alice", "body": f"msg {i}"}, b)
        page = (await self.get("/api/messages/bobby", a))[1]["messages"]
        self.assertEqual((len(page), page[-1]["body"]), (50, "msg 59"))
        older = (await self.get(f"/api/messages/bobby?before={page[0]['id']}", a))[1]["messages"]
        self.assertEqual([m["body"] for m in older][:2], ["hey bob", "msg 0"])
        self.assertEqual(len(older), 11)
        await wb.close()




class RankingTests(ServerTestCase):
    async def test_scores_out_of_100_and_ranked(self):
        self.assertEqual(cos.player_score(cos.FULL_WRS, 21, 21, cos.FULL_EARNED)["score"], 100.0)
        self.assertEqual(cos.player_score(0, 0, 21, 0)["score"], 0.0)
        self.assertNotIn("skins", [k for k, _l, _m in cos.SCORE_PARTS])
        a, b = await self.account("alice"), await self.account("bobby")
        await self.account("carol")  # no score: not listed
        db = self.server.db
        await self.post("/api/runs", bot_run(CATEGORY_BY_ID["sprint10"], 4, random.Random(3)).to_json(), a)  # PR + WR
        db.add_points(2, 50_000, "test")
        db.buy(2, "skin:mint")  # spending doesn't lower the score
        db.grant(2, "skin:galaxy")
        cat = make_custom(10, 9, ["wall"], 3, 1, 130)  # community records don't count
        await self.post("/api/runs", bot_run(cat, 4, random.Random(3)).to_json(), b)
        status, data = await self.get("/api/rankings", b)
        self.assertEqual(status, 200)
        by = {p["name"]: p for p in data["players"]}
        self.assertEqual(set(by), {"alice", "bobby"})
        alice, bobby = by["alice"], by["bobby"]
        self.assertEqual((alice["wrs"], alice["prs"], alice["earned"]),
                         (1, 1, cos.PR_REWARD + cos.WR_REWARD))  # (a PB and 1st place)
        self.assertEqual((bobby["wrs"], bobby["prs"], bobby["earned"]), (0, 0, 50_000))
        self.assertNotIn("skins", bobby["parts"])
        self.assertEqual([p["name"] for p in data["players"]],
                         sorted(by, key=lambda n: -by[n]["score"]))
        self.assertEqual([p["place"] for p in data["players"]], [1, 2])
        self.assertEqual(data["me"]["name"], "bobby")
        self.assertAlmostEqual(alice["score"], sum(alice["parts"].values()), places=1)
        self.assertEqual(sum(pt["most"] for pt in data["parts"]), 100)



def finished_runs(category, count, seeds=range(1, 80)):
    """Bot runs of a category with different finishing times, slowest first."""
    by_time = {}
    for seed in seeds:
        run = bot_run(category, seed, random.Random(seed))
        if run.finished:
            by_time.setdefault(round(run.elapsed), run)
        if len(by_time) >= count:
            break
    return [by_time[t] for t in sorted(by_time, reverse=True)]


class PlacementTests(ServerTestCase):
    async def test_moving_up_pays_by_place_and_pbs_need_5_percent(self):
        self.assertEqual([cos.placement_points(i) for i in range(1, 8)],
                         [100_000, 50_000, 25_000, 12_500, 6_250, 3_125, 1_563])  # halving, whole points
        runs = finished_runs(CATEGORY_BY_ID["sprint10"], 4)
        self.assertEqual(len(runs), 4)
        slow, mid, fast, fastest = runs
        tokens = {n: await self.account(n) for n in ("alice", "bobby", "carol")}

        async def submit(name, run):
            return (await self.post("/api/runs", run.to_json(), tokens[name]))[1]
        r = await submit("alice", mid)
        self.assertEqual((r["rank"], r["earned"]), (1, 100_000 + cos.PR_REWARD))
        r = await submit("bobby", fast)   # takes 1st: alice drops to 2nd
        self.assertEqual((r["rank"], r["earned"]), (1, 100_000 + cos.PR_REWARD))
        r = await submit("carol", slow)   # 3rd
        self.assertEqual((r["rank"], r["earned"]), (3, 25_000 + cos.PR_REWARD))
        r = await submit("carol", slow)   # nothing new
        self.assertEqual(r["earned"], 0)
        r = await submit("alice", fastest)  # back to 1st, and a PB if it's 5% better
        pb = cos.PR_REWARD if fastest.elapsed <= mid.elapsed * 0.95 else 0
        self.assertEqual((r["rank"], r["earned"]), (1, 100_000 + pb))
        self.assertTrue(r["wr"])

    async def test_small_improvements_dont_pay_a_pb(self):
        cat = CATEGORY_BY_ID["sprint10"]
        runs = finished_runs(cat, 30)
        pairs = [(a, b) for a, b in zip(runs, runs[1:]) if b.elapsed > a.elapsed * 0.95]  # under 5% faster
        self.assertTrue(pairs)
        slower, faster = pairs[0]
        token = await self.account()
        await self.post("/api/runs", slower.to_json(), token)
        r = (await self.post("/api/runs", faster.to_json(), token))[1]
        self.assertTrue(r["pb"])          # it is a personal best...
        self.assertEqual(r["earned"], 0)  # ...but too small a step to pay (and still 1st: no place change)


class WeeklyTests(ServerTestCase):
    WEEK = "2026-W46"  # its Classic weeklies are easy for the test bot

    async def asyncSetUp(self):
        await super().asyncSetUp()
        import opensnake.server as server_module
        self.real_week = server_module.week_id
        server_module.week_id = lambda when=None: self.WEEK

    async def asyncTearDown(self):
        import opensnake.server as server_module
        server_module.week_id = self.real_week
        await super().asyncTearDown()

    def test_weekly_categories_are_the_same_everywhere_and_verify(self):
        from opensnake.speedrun import find_category, verify, weekly_categories
        cats = weekly_categories(self.WEEK)
        self.assertEqual(len(cats), 10)
        self.assertEqual(len({c.id for c in cats}), 10)
        self.assertEqual([c.id for c in weekly_categories(self.WEEK)], [c.id for c in cats])  # deterministic
        self.assertNotEqual([c.name for c in weekly_categories("2026-W47")], [c.name for c in cats])
        classic = next(c for c in cats if not c.modes)
        self.assertEqual(find_category(classic.id), classic)
        run = finished_runs(classic, 1)[0]
        self.assertTrue(verify(run.to_json())[0])

    async def test_this_weeks_runs_pay_and_old_ones_dont(self):
        from opensnake.speedrun import weekly_categories
        token = await self.account()
        status, data = await self.get("/api/weekly")
        self.assertEqual((status, data["week"], len(data["categories"])), (200, self.WEEK, 10))
        classic = next(c for c in weekly_categories(self.WEEK) if not c.modes)
        r = (await self.post("/api/runs", finished_runs(classic, 1)[0].to_json(), token))[1]
        self.assertTrue(r["valid"])
        self.assertEqual(r["earned"], 100_000 + cos.PR_REWARD)
        self.assertEqual((await self.get("/api/weekly"))[1]["categories"][[c.id for c in weekly_categories(self.WEEK)]
                                                                         .index(classic.id)]["wr"]["player"], "alice")
        old = next(c for c in weekly_categories("2026-W40") if not c.modes)
        r = (await self.post("/api/runs", finished_runs(old, 1)[0].to_json(), token))[1]
        self.assertTrue(r["valid"])       # a past week's run still counts on its leaderboard...
        self.assertEqual(r["earned"], 0)  # ...but its week is over: no rewards
        self.assertEqual((await self.post("/api/runs", {"category": "weekly-nope"}, token))[0], 400)


class BattlePassTests(ServerTestCase):
    async def test_buy_level_and_claim(self):
        token = await self.account()
        db = self.server.db
        info = (await self.get("/api/battlepass", token))[1]
        self.assertEqual((info["owned"], info["level"], info["price"], len(info["tiers"])), (False, 0, 10_000, 21))
        self.assertEqual(info["tiers"][-1]["level"], 100)
        self.assertEqual(info["tiers"][-1]["crate"], "royal")
        self.assertIn("Buy", (await self.post("/api/battlepass/claim", {"level": 5}, token))[1]["error"])
        self.assertIn("Not enough", (await self.post("/api/battlepass/buy", {}, token))[1]["error"])
        db.add_points(1, 15_000, "test")
        status, info = await self.post("/api/battlepass/buy", {}, token)
        self.assertEqual((status, info["owned"], info["points"]), (200, True, 5_000))
        self.assertIn("already", (await self.post("/api/battlepass/buy", {}, token))[1]["error"])
        self.assertIn("Reach level 5", (await self.post("/api/battlepass/claim", {"level": 5}, token))[1]["error"])
        db.add_xp(1, 12 * cos.LEVEL_XP + 10)
        info = (await self.get("/api/battlepass", token))[1]
        self.assertEqual((info["level"], info["into_level"]), (12, 10))
        r = (await self.post("/api/battlepass/claim", {"level": 5}, token))[1]
        self.assertEqual((r["tier"]["kind"], r["points"]), ("points", 5_000 + 5_000))
        r = (await self.post("/api/battlepass/claim", {"level": 10}, token))[1]  # a free Gold Crate
        self.assertIn(r["item"], cos.ALL_ITEMS)
        self.assertIn("already", (await self.post("/api/battlepass/claim", {"level": 5}, token))[1]["error"])
        self.assertIn("Reach", (await self.post("/api/battlepass/claim", {"level": 15}, token))[1]["error"])
        self.assertIn("no reward", (await self.post("/api/battlepass/claim", {"level": 7}, token))[1]["error"])
        claimed = [t["level"] for t in (await self.get("/api/battlepass", token))[1]["tiers"] if t["claimed"]]
        self.assertEqual(claimed, [5, 10])

    async def test_no_daily_cap_but_levels_take_more_xp(self):
        token = await self.account()
        db = self.server.db
        self.assertEqual(cos.LEVEL_XP * cos.PASS_LEVELS, 120_000)
        self.assertEqual(db.add_xp(1, 130_000), 130_000)  # all of it, in one day
        info = (await self.get("/api/battlepass", token))[1]
        self.assertEqual(info["level"], 130_000 // cos.LEVEL_XP)
        self.assertNotIn("day_limit", info)

    async def test_xp_from_playing_and_levels_past_100_carry_over(self):
        token = await self.account()
        db = self.server.db
        await self.post("/api/rounds", {"fruit": 10}, token)
        self.assertEqual((await self.get("/api/battlepass", token))[1]["xp"], cos.round_points(10))
        db.pass_row(1, "2025-W10")  # (past weeks, so they can't clash with the real current week)
        db.db.execute("UPDATE battlepass SET xp = ? WHERE week = '2025-W10'", (120 * cos.LEVEL_XP + 50,))
        db.db.commit()
        row = db.pass_row(1, "2025-W11")  # the next week
        self.assertEqual(cos.pass_level(row["xp"]), 20)  # level 120 -> 20
        self.assertEqual(row["xp"], 20 * cos.LEVEL_XP + 50)
        self.assertEqual(db.pass_row(1, "2025-W13")["xp"], 0)  # (skipped a week: nothing to carry)
        from opensnake.weeks import previous_week
        self.assertEqual(previous_week("2026-W01"), "2025-W52")  # (across a new year)

    def test_each_week_has_its_own_rewards(self):
        a, b = cos.battle_pass("2026-W46"), cos.battle_pass("2026-W47")
        self.assertEqual([t["level"] for t in a], list(range(5, 100, 5)) + [99, 100])
        self.assertEqual([t.get("crate") for t in a if t["level"] in (50, 85, 100)], ["royal"] * 3)
        legendary, mythic = cos.pass_skins("2026-W46")
        self.assertEqual([t.get("item") for t in a if t["level"] in (75, 99)], [legendary, mythic])
        self.assertNotEqual(cos.pass_skins("2026-W47"), (legendary, mythic))  # new ones each week
        rng = random.Random(2)
        for crate in cos.CRATES:  # never from loot boxes
            self.assertFalse({cos.roll(crate, rng) for _ in range(300)} & cos.PASS_ONLY)
        self.assertNotEqual([t.get("item") for t in a], [t.get("item") for t in b])
        for t in a:
            if t["kind"] == "item":
                self.assertIn(t["item"], cos.ALL_ITEMS)


class RestartWeekTests(ServerTestCase):
    async def test_restarting_the_week(self):
        from opensnake.speedrun import weekly_categories
        from opensnake.weeks import week_id
        buyer, other = await self.account("alice"), await self.account("bobby")
        db = self.server.db
        db.add_points(1, 10_000, "test")
        await self.post("/api/battlepass/buy", {}, buyer)
        db.add_xp(1, 12 * cos.LEVEL_XP)
        db.add_xp(2, 5 * cos.LEVEL_XP)
        await self.post("/api/battlepass/claim", {"level": 5}, buyer)
        old = (await self.get("/api/weekly"))[1]
        self.assertEqual(old["week"], week_id())

        new_week = db.restart_week()
        self.assertEqual(new_week, f"{week_id()}r1")
        a = (await self.get("/api/battlepass", buyer))[1]
        b = (await self.get("/api/battlepass", other))[1]
        self.assertEqual((a["week"], a["level"], a["owned"]), (new_week, 0, True))   # bought it: keeps it
        self.assertEqual((b["level"], b["owned"]), (0, False))
        self.assertFalse(any(t["claimed"] for t in a["tiers"]))
        self.assertEqual([t["name"] for t in a["tiers"]], [t["name"] for t in cos.battle_pass(new_week)])
        new = (await self.get("/api/weekly"))[1]
        self.assertEqual(new["week"], new_week)
        self.assertNotEqual([c["name"] for c in new["categories"]], [c["name"] for c in old["categories"]])
        self.assertEqual([c["id"] for c in new["categories"]], [c.id for c in weekly_categories(new_week)])
        # the old week's speedruns stop paying
        classic = next((c for c in weekly_categories(week_id()) if not c.modes), None)
        if classic:
            run = finished_runs(classic, 1)
            if run:
                r = (await self.post("/api/runs", run[0].to_json(), buyer))[1]
                self.assertTrue(r["valid"])
                self.assertEqual(r["earned"], 0)
        self.assertEqual(db.restart_week(), f"{week_id()}r2")  # it can happen again


class MarketTests(ServerTestCase):
    async def test_list_buy_cancel_and_fees(self):
        seller, buyer = await self.account("alice"), await self.account("bobby")
        db = self.server.db
        db.grant(1, "skin:galaxy")
        db.grant(1, "skin:galaxy")  # two copies
        db.set_profile(1, {"skin": "galaxy"})
        db.add_points(2, 100_000, "test")
        status, r = await self.post("/api/market/list", {"item": "skin:galaxy", "price": 40_000}, seller)
        self.assertEqual((status, r["copies"]), (200, 1))
        self.assertEqual(db.user_by_id(1)["skin"], "galaxy")  # still has a copy on
        listing = (await self.get("/api/market?q=gal"))[1]["listings"]
        self.assertEqual([(x["name"], x["price"], x["seller"]) for x in listing], [("Galaxy", 40_000, "alice")])
        self.assertIn("own listing", (await self.post("/api/market/buy", {"id": r["id"]}, seller))[1]["error"])
        status, bought = await self.post("/api/market/buy", {"id": r["id"]}, buyer)
        self.assertEqual((status, bought["points"], bought["copies"]), (200, 60_000, 1))
        self.assertEqual(db.points(1), 40_000 - cos.market_fee(40_000))
        self.assertIn("already sold", (await self.post("/api/market/buy", {"id": r["id"]}, buyer))[1]["error"])
        # selling isn't "earning" on the leaderboard
        self.assertFalse(any(p["name"] == "alice" for p in db.rankings()))
        # listing your last copy takes it off; cancelling gives it back
        r = (await self.post("/api/market/list", {"item": "skin:galaxy", "price": 500}, seller))[1]
        self.assertEqual((r["copies"], db.user_by_id(1)["skin"]), (0, ""))
        self.assertIn("your listings", (await self.post("/api/market/cancel", {"id": r["id"]}, buyer))[1]["error"])
        self.assertEqual((await self.post("/api/market/cancel", {"id": r["id"]}, seller))[1]["copies"], 1)
        self.assertEqual((await self.get("/api/market", seller))[1]["mine"], [])

    async def test_what_cant_be_sold(self):
        token = await self.account()
        db = self.server.db
        db.grant(1, "skin:rk_cobra")
        cases = [({"item": "skin:rk_cobra", "price": 500}, "can't be sold"),
                 ({"item": "skin:mint", "price": 500}, "don't own"),
                 ({"item": "skin:nope", "price": 500}, "Unknown"),
                 ({"item": "skin:rk_cobra", "price": 5}, "can't be sold")]
        for body, error in cases:
            self.assertIn(error, (await self.post("/api/market/list", body, token))[1]["error"])
        db.grant(1, "skin:mint")
        self.assertIn("Prices", (await self.post("/api/market/list", {"item": "skin:mint", "price": 5}, token))[1]
                      ["error"])
        self.assertIn("Prices", (await self.post("/api/market/list", {"item": "skin:mint", "price": "x"}, token))[1]
                      ["error"].replace("Enter a price.", "Prices"))
        self.assertEqual(db.copies(1, "skin:mint"), 1)  # nothing was taken by the failed attempts


class RankRewardTests(ServerTestCase):
    async def test_each_rank_pays_once(self):
        await self.account()
        db = self.server.db
        db.db.execute("UPDATE users SET rp = 260 WHERE id = 1")  # Rattler, two ranks up at once
        got = db.record_match(1, "draw", True, 50)["rank_ups"]
        self.assertEqual([g["rank"] for g in got], ["Garter", "Rattler"])
        self.assertTrue({"skin:rk_garter", "skin:rk_rattler"} <= set(db.inventory(1)))
        points = db.points(1)
        db.db.execute("UPDATE users SET rp = 90 WHERE id = 1")  # drop back to Hatchling...
        self.assertEqual(db.record_match(1, "win", True, 0)["rank_ups"], [])  # ...and climb back: nothing
        self.assertEqual(db.points(1), points)
        db.db.execute("UPDATE users SET rp = 500 WHERE id = 1")  # a new rank pays
        self.assertEqual([g["rank"] for g in db.record_match(1, "draw", True, 0)["rank_ups"]], ["Cobra"])
        self.assertFalse(set(cos.RANKED_ONLY) & {cos.roll(c, random.Random(1)) for c in cos.CRATES for _ in range(50)})

    def test_existing_players_get_rewards_for_ranks_they_have(self):
        import sqlite3
        import tempfile
        from pathlib import Path
        from opensnake.server import Database
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "old.db"
            db = Database(path)
            db.register("oldie", "password1")
            db.db.execute("UPDATE users SET rp = 120")
            db.db.commit()
            db.close()
            raw = sqlite3.connect(path)  # make it look like a database from before 2.6
            raw.execute("ALTER TABLE users DROP COLUMN best_rank")
            raw.commit()
            raw.close()
            db = Database(path)
            self.assertIn("skin:rk_garter", db.inventory(1))
            self.assertEqual(db.user_by_id(1)["best_rank"], 1)
            db.close()


class UnrankedTests(ServerTestCase):
    recv = VersusTests.recv

    async def connect(self, token):
        ws = await self.client.ws_connect("/ws")
        self.assertFalse((await self.recv(ws, "welcome"))["account"])
        await ws.send_json({"t": "auth", "token": token})  # (logging in without the token in the URL)
        self.assertTrue((await self.recv(ws, "welcome"))["account"])
        return ws

    async def test_unranked_matches_keep_rank_points(self):
        a, b = await self.account("alice"), await self.account("bobby")
        wa, wb = await self.connect(a), await self.connect(b)
        await wa.send_json({"t": "host", "settings": {"size": "small", "speed": 1.0}, "ranked": False})
        room = await self.recv(wa, "room")
        self.assertFalse(room["ranked"])
        await wb.send_json({"t": "join", "code": room["code"]})
        await self.recv(wb, "room")
        await wa.send_json({"t": "start"})
        ra, rb = await self.recv(wa, "reward", timeout=30), await self.recv(wb, "reward", timeout=30)
        self.assertEqual((ra["ranked"], ra["rp_change"], rb["rp_change"]), (False, 0, 0))
        self.assertGreaterEqual(ra["points"], cos.MATCH_PLAYED)  # still pays snake points
        progress = self.server.db.daily_info(1)
        if any(c["kind"] == "matches" for c in progress["challenges"]):
            self.assertEqual(next(c for c in progress["challenges"] if c["kind"] == "matches")["progress"], 1)
        for ws in (wa, wb):
            await ws.close()


class DailyTests(ServerTestCase):
    async def test_challenges_progress_and_claims(self):
        token = await self.account()
        db = self.server.db
        day = "2026-11-13"
        chs = cos.daily_challenges(day)
        self.assertEqual([c["difficulty"] for c in chs], ["easy", "medium", "hard"])
        self.assertEqual(chs, cos.daily_challenges(day))  # the same for everyone
        with self.assertRaisesRegex(ValueError, "Finish the challenge"):
            db.claim_daily(1, 0, day)
        for c in chs:
            db.progress(1, c["kind"], c["goal"], day)
        before = db.points(1)
        db.claim_daily(1, 0, day)
        with self.assertRaisesRegex(ValueError, "already"):
            db.claim_daily(1, 0, day)
        with self.assertRaisesRegex(ValueError, "Unknown"):
            db.claim_daily(1, True, day)
        db.claim_daily(1, 1, day)
        db.claim_daily(1, 2, day)
        db.claim_daily(1, "bonus", day)
        self.assertEqual(db.points(1) - before, sum(c["reward"] for c in chs) + cos.DAILY_BONUS)
        info = (await self.get("/api/daily", token))[1]
        self.assertEqual(info["day"], db.today())
        self.assertEqual(len(info["challenges"]), 3)

    async def test_rounds_count(self):
        token = await self.account()
        await self.post("/api/rounds", {"fruit": 12}, token)
        info = self.server.db.daily_info(1)
        for c in info["challenges"]:
            if c["kind"] == "fruit":
                self.assertEqual(c["progress"], 12)
            if c["kind"] == "rounds":
                self.assertEqual(c["progress"], 1)


class RunCheckTests(ServerTestCase):
    async def test_future_weeks_cant_be_played_early(self):
        from opensnake.speedrun import weekly_categories
        from opensnake.weeks import week_id
        from datetime import datetime, timedelta, timezone
        token = await self.account()
        later = week_id(datetime.now(timezone.utc) + timedelta(days=14))
        cat = weekly_categories(later)[0]
        run = {"format": 1, "game": "opensnake", "category": cat.id, "seed": 1, "time_ms": 1000, "inputs": []}
        self.assertIn("hasn't started", (await self.post("/api/runs", run, token))[1]["error"])

    def test_replays_stop_at_the_claimed_time(self):
        import time
        from opensnake.speedrun import RUN_FORMAT, verify
        wrap = CATEGORY_BY_ID["wrap"]
        # a run that just goes round and round (borderless), claiming a short time
        run = {"format": RUN_FORMAT, "game": "opensnake", "category": wrap.id, "seed": 1, "time_ms": 5_000,
               "inputs": [[0, "right"]]}
        start = time.perf_counter()
        ok, _msg = verify(run)
        self.assertFalse(ok)
        self.assertLess(time.perf_counter() - start, 1.0)
        self.assertFalse(verify({**run, "time_ms": 10 ** 12})[0])
        self.assertFalse(verify({**run, "time_ms": "5000"})[0])




class CommunityVoteTests(ServerTestCase):
    async def test_upvotes_search_and_sorting(self):
        a, b, c = await self.account("alice"), await self.account("bobby"), await self.account("carol")
        portal = make_custom(10, 9, ["portal"], 3, 1, 130, name="Portal Party")
        walls = make_custom(10, 9, ["wall"], 3, 1, 130, name="Brick Run")
        await self.post("/api/runs", bot_run(portal, 4, random.Random(3)).to_json(), a)   # alice made it
        await self.post("/api/runs", bot_run(walls, 4, random.Random(3)).to_json(), b)    # bobby made this one
        await self.post("/api/runs", bot_run(walls, 5, random.Random(5)).to_json(), c)
        # you can't upvote your own, but others can (once each)
        self.assertIn("own", (await self.post("/api/categories/vote", {"id": portal.id}, a))[1]["error"])
        r = (await self.post("/api/categories/vote", {"id": portal.id}, b))[1]
        self.assertEqual((r["votes"], r["voted"]), (1, True))
        await self.post("/api/categories/vote", {"id": portal.id}, b)
        r = (await self.post("/api/categories/vote", {"id": portal.id}, c))[1]
        self.assertEqual(r["votes"], 2)
        self.assertEqual((await self.post("/api/categories/vote", {"id": "custom-nope"}, c))[0], 404)
        # top: most upvoted first; popular: most players first
        top = (await self.get("/api/categories", c))[1]["categories"]
        self.assertEqual([x["name"] for x in top], ["Portal Party", "Brick Run"])
        self.assertEqual((top[0]["votes"], top[0]["voted"], top[0]["mine"]), (2, True, False))
        popular = (await self.get("/api/categories?sort=popular"))[1]["categories"]
        self.assertEqual([x["name"] for x in popular], ["Brick Run", "Portal Party"])
        # search by name, creator or mode
        for q, want in (("brick", ["Brick Run"]), ("alice", ["Portal Party"]), ("wall", ["Brick Run"]), ("zzz", [])):
            got = (await self.get(f"/api/categories?q={q}"))[1]["categories"]
            self.assertEqual([x["name"] for x in got], want, q)
        # taking an upvote back
        r = (await self.post("/api/categories/vote", {"id": portal.id, "up": False}, c))[1]
        self.assertEqual((r["votes"], r["voted"]), (1, False))


class CommunityUploadTests(ServerTestCase):
    async def test_making_a_community_category_without_playing_it_first(self):
        token = await self.account()
        rules = {"name": "  Speedy   walls ", "w": 14, "h": 12, "modes": ["wall", "gate"], "goal": 12,
                 "fruit_count": 2, "tick_ms": 130, "fruit": "apple", "accel": 4}
        status, r = await self.post("/api/categories", {"def": rules}, token)
        self.assertEqual((status, r["new"], r["name"], r["creator"]), (200, True, "Speedy walls", "alice"))
        listed = (await self.get("/api/categories?q=speedy"))[1]["categories"]
        self.assertEqual([c["id"] for c in listed], [r["id"]])
        self.assertEqual((listed[0]["def"]["accel"], listed[0]["def"]["modes"]), (4.0, ["gate", "wall"]))
        # the same rules again are the same category
        again = (await self.post("/api/categories", {"def": {**rules, "name": "Copycat"}}, token))[1]
        self.assertEqual((again["id"], again["new"], again["name"]), (r["id"], False, "Speedy walls"))
        bad = (await self.post("/api/categories", {"def": {**rules, "w": 2}}, token))[1]
        self.assertIn("out of range", bad["error"])
        self.assertEqual((await self.post("/api/categories", {"def": rules}))[0], 401)


class HolidayCrateTests(ServerTestCase):
    async def test_the_holiday_crate_gives_holiday_skins_only(self):
        holiday = {f"skin:{s.id}" for s in cos.SKINS if s.series == "Holiday"}
        self.assertEqual(len(holiday), 14)
        self.assertEqual(holiday, cos.THEMED_ONLY)
        rng = random.Random(4)
        crate = cos.CRATE_BY_ID["holiday"]
        self.assertEqual({cos.roll(crate, rng) for _ in range(3000)}, holiday)  # every one can come out
        for other in cos.CRATES:
            if not other.series:
                self.assertFalse({cos.roll(other, rng) for _ in range(500)} & holiday, other.id)
        for week in ("2026-W46", "2026-W47", "2026-W48"):  # not battle pass rewards either
            self.assertFalse({t.get("item") for t in cos.battle_pass(week)} & holiday)
        token = await self.account()
        self.server.db.add_points(1, 100_000, "test")
        status, r = await self.post("/api/store/open", {"crate": "holiday"}, token)
        self.assertEqual(status, 200)
        self.assertIn(r["item"], holiday)
        c = cos.skin_color(cos.SKIN_BY_ID["christmaslights"], 2, 9, 1234.0)
        self.assertTrue(all(0 <= v <= 255 for v in c))


class LoginRewardTests(ServerTestCase):
    async def test_thirty_days_with_big_milestones(self):
        token = await self.account()
        db = self.server.db
        info = (await self.get("/api/login-reward", token))[1]
        self.assertEqual((info["ready"], info["streak"], len(info["rewards"])), (True, 1, 30))
        self.assertEqual([m["day"] for m in info["milestones"]], [7, 14, 15, 21, 30])
        self.assertEqual(info["rewards"][14], "250,000 snake points")
        self.assertEqual(info["rewards"][29], "2 Royal Crates + 500,000 snake points")
        from datetime import date, timedelta
        day = lambda n: (date(2026, 11, 1) + timedelta(days=n)).isoformat()
        r = db.claim_login_reward(1, random.Random(1), day(0))
        self.assertEqual((r["kind"], r["points"], r["ready"], r["opened"]), ("points", 5_000, False, []))
        with self.assertRaisesRegex(ValueError, "tomorrow"):
            db.claim_login_reward(1, random.Random(1), day(0))
        for n in range(1, 15):
            before = db.points(1)
            r = db.claim_login_reward(1, random.Random(n), day(n))
        self.assertEqual(r["streak"], 15)
        self.assertEqual(db.points(1) - before, 250_000)  # day 15
        for n in range(15, 30):
            before = db.points(1)
            r = db.claim_login_reward(1, random.Random(n), day(n))
        self.assertEqual(r["streak"], 30)
        self.assertEqual(len(r["opened"]), 2)  # day 30: two Royal Crates, opened...
        self.assertTrue(all(o["crate"] == "royal" for o in r["opened"]))
        self.assertEqual(db.points(1) - before, 500_000)  # ...and 500,000 points
        r = db.claim_login_reward(1, random.Random(1), day(30))  # round again
        self.assertEqual((r["streak"], r["step"]), (31, 0))
        r = db.claim_login_reward(1, random.Random(1), day(32))  # skipped a day: back to day 1
        self.assertEqual((r["streak"], r["step"]), (1, 0))


class TradeTests(ServerTestCase):
    async def test_offer_accept_and_what_moves(self):
        a, b = await self.account("alice"), await self.account("bobby")
        db = self.server.db
        db.grant(1, "skin:galaxy")
        db.grant(1, "skin:galaxy")
        db.grant(2, "skin:snowflake")
        db.add_points(2, 50_000, "test")
        db.set_profile(2, {"skin": "snowflake"})
        items = (await self.get("/api/users/bobby/items"))[1]["items"]
        self.assertEqual(items, {"skin:snowflake": 1})
        offer = {"to": "bobby", "give": ["skin:galaxy"], "give_points": 0, "want": ["skin:snowflake"], "want_points": 5_000}
        status, t = await self.post("/api/trades", offer, a)
        self.assertEqual((status, t["from"], t["to"], t["status"]), (200, "alice", "bobby", "open"))
        listing = (await self.get("/api/trades", b))[1]
        self.assertEqual([x["id"] for x in listing["incoming"]], [t["id"]])
        self.assertIn("wasn't offered to you", (await self.post("/api/trades/answer", {"id": t["id"], "action": "accept"}, a))[1]["error"])
        status, done = await self.post("/api/trades/answer", {"id": t["id"], "action": "accept"}, b)
        self.assertEqual((status, done["status"]), (200, "accepted"))
        self.assertEqual((db.copies(1, "skin:galaxy"), db.copies(1, "skin:snowflake")), (1, 1))
        self.assertEqual((db.copies(2, "skin:galaxy"), db.copies(2, "skin:snowflake")), (1, 0))
        self.assertEqual((db.points(1), db.points(2)), (5_000, 45_000))
        self.assertEqual(db.user_by_id(2)["skin"], "")  # bobby's last snowflake went: it came off
        self.assertIn("isn't open", (await self.post("/api/trades/answer", {"id": t["id"], "action": "accept"}, b))[1]["error"])
        self.assertFalse(any(p["name"] == "alice" for p in db.rankings()))  # trades aren't earnings

    async def test_what_cant_be_traded(self):
        a, b = await self.account("alice"), await self.account("bobby")
        db = self.server.db
        db.grant(1, "skin:rk_cobra")
        db.grant(1, "skin:mint")
        db.grant(2, "skin:sky")
        cases = [({"to": "alice"}, "That's you"), ({"to": "nobody"}, "No player"),
                 ({"give": ["skin:rk_cobra"], "want": ["skin:sky"]}, "can't be traded"),
                 ({"give": ["skin:sky"], "want": ["skin:sky"]}, "don't have everything"),
                 ({"give": ["skin:mint"], "want": ["skin:mint"]}, "doesn't have everything"),
                 ({"give": ["skin:mint"], "want": []}, "both sides"),
                 ({"give": ["skin:mint"], "want_points": -5}, "Points")]
        for extra, error in cases:
            offer = {"to": "bobby", "give": [], "want": ["skin:sky"], **extra}
            self.assertIn(error, (await self.post("/api/trades", offer, a))[1]["error"], extra)
        # an offer that can't happen any more (the item went) is refused when accepted
        t = (await self.post("/api/trades", {"to": "bobby", "give": ["skin:mint"], "want": ["skin:sky"]}, a))[1]
        db.take(1, "skin:mint")
        self.assertIn("any more", (await self.post("/api/trades/answer", {"id": t["id"], "action": "accept"}, b))[1]["error"])
        self.assertEqual(db.copies(2, "skin:sky"), 1)  # nothing moved
        t2 = (await self.post("/api/trades", {"to": "bobby", "give_points": 0, "give": [], "want": ["skin:sky"]}, a))[1]
        self.assertIn("error", t2)
        db.add_points(1, 100, "test")
        t3 = (await self.post("/api/trades", {"to": "bobby", "give_points": 100, "want": ["skin:sky"]}, a))[1]
        self.assertEqual((await self.post("/api/trades/answer", {"id": t3["id"], "action": "cancel"}, a))[1]["status"], "cancelled")


class ReplayTests(ServerTestCase):
    async def test_watching_world_records(self):
        token = await self.account()
        cat = CATEGORY_BY_ID["sprint10"]
        run = bot_run(cat, 4, random.Random(3))
        await self.post("/api/runs", run.to_json(), token)
        status, r = await self.get("/api/replay/sprint10")
        self.assertEqual((status, r["player"], r["time_ms"]), (200, "alice", round(run.elapsed)))
        self.assertEqual((r["run"]["seed"], r["run"]["inputs"]), (run.seed, run.inputs))
        self.assertEqual((await self.get("/api/replay/sprint25"))[0], 404)  # no record yet
        custom = make_custom(10, 9, [], 5, 1, 130)
        self.assertIn("can't be watched", (await self.get(f"/api/replay/{custom.id}"))[1]["error"])
        self.assertEqual((await self.get("/api/replay/nonsense"))[0], 404)


class JackpotTests(ServerTestCase):
    async def test_pot_countdown_and_weighted_draw(self):
        a, b = await self.account("alice"), await self.account("bobby")
        db = self.server.db
        db.grant(1, "skin:galaxy")
        db.grant(2, "skin:snowflake")
        db.grant(2, "skin:mint")
        status, pot = await self.post("/api/jackpot/enter", {"items": ["skin:galaxy"]}, a)
        self.assertEqual((status, len(pot["players"]), pot["seconds_left"]), (200, 1, None))
        self.assertEqual(db.copies(1, "skin:galaxy"), 0)  # held in the pot
        self.assertIsNone(db.jackpot_tick())  # nobody else yet: no draw
        status, pot = await self.post("/api/jackpot/enter", {"items": ["skin:snowflake", "skin:mint"]}, b)
        self.assertEqual(status, 200)
        self.assertEqual(pot["seconds_left"], cos.JACKPOT_COUNTDOWN)
        values = {p["name"]: p["value"] for p in pot["players"]}
        self.assertEqual(values["alice"], cos.item_value("skin:galaxy"))
        self.assertEqual(values["bobby"], cos.item_value("skin:snowflake") + cos.item_value("skin:mint"))
        self.assertEqual(pot["total"], sum(values.values()))
        self.assertAlmostEqual(sum(p["chance"] for p in pot["players"]), 100, delta=0.2)
        self.assertIsNone(db.jackpot_tick())  # still counting down

        class Rigged:  # the ticket lands in bobby's slice (after alice's)
            def random(self):
                return 0.999
        later = datetime.now(timezone.utc) + timedelta(seconds=cos.JACKPOT_COUNTDOWN + 1)
        result = db.jackpot_tick(later, Rigged())
        self.assertEqual((result["winner_name"], result["total"]), ("bobby", pot["total"]))
        for it in ("skin:galaxy", "skin:snowflake", "skin:mint"):
            self.assertEqual(db.copies(2, it), 1)
        self.assertEqual(db.copies(1, "skin:galaxy"), 0)
        state = (await self.get("/api/jackpot", a))[1]
        self.assertEqual((state["last"]["winner"], state["players"], state["history"][0]["players"]), ("bobby", [], 2))

    async def test_what_cant_go_in(self):
        a = await self.account("alice")
        db = self.server.db
        db.grant(1, "skin:rk_cobra")
        for items, msg in ((["skin:galaxy"], "don't have"), (["skin:rk_cobra"], "Ranked"), ([], "1 to"),
                           (["skin:nope"], "Unknown")):
            status, r = await self.post("/api/jackpot/enter", {"items": items}, a)
            self.assertEqual(status, 400)
            self.assertIn(msg, r["error"])
        self.assertEqual((await self.post("/api/jackpot/enter", {"items": ["skin:galaxy"]}))[0], 401)

    async def test_a_lone_player_gets_their_items_back(self):
        await self.account("alice")
        db = self.server.db
        db.grant(1, "skin:galaxy")
        db.jackpot_enter(1, ["skin:galaxy"])
        self.assertIsNone(db.jackpot_tick())
        result = db.jackpot_tick(datetime.now(timezone.utc) + timedelta(hours=cos.JACKPOT_LONE_HOURS, minutes=1))
        self.assertEqual(result["refunded"], 1)
        self.assertEqual(db.copies(1, "skin:galaxy"), 1)
        self.assertEqual(db.jackpot_state()["players"], [])

    def test_values(self):
        self.assertEqual(cos.item_value("skin:galaxy"), cos.shop_price("skin:galaxy") or cos.RARITY_VALUE[cos.item_rarity("skin:galaxy")])
        self.assertEqual(cos.item_value("skin:snowflake"), cos.RARITY_VALUE[cos.item_rarity("skin:snowflake")])


class GiftSkinTests(ServerTestCase):
    async def test_a_gift_skin_stays_put(self):
        a, b = await self.account("alice"), await self.account("bobby")
        db = self.server.db
        db.grant(1, "skin:gambledtoomuch")
        self.assertIn("skin:gambledtoomuch", cos.UNTRADEABLE)
        self.assertFalse(any("skin:gambledtoomuch" in cos.items_of(r) for r in cos.RARITIES))
        self.assertIsNone(cos.shop_price("skin:gambledtoomuch"))
        status, r = await self.post("/api/market/list", {"item": "skin:gambledtoomuch", "price": 500}, a)
        self.assertIn("can't be sold", r["error"])
        status, r = await self.post("/api/trades", {"to": "bobby", "give": ["skin:gambledtoomuch"], "want": [],
                                                    "want_points": 100}, a)
        self.assertIn("can't be traded", r["error"])
        status, r = await self.post("/api/jackpot/enter", {"items": ["skin:gambledtoomuch"]}, a)
        self.assertIn("can't go in the jackpot", r["error"])
        self.assertEqual(db.copies(1, "skin:gambledtoomuch"), 1)
        self.assertEqual((await self.post("/api/profile", {"skin": "gambledtoomuch"}, a))[0], 200)
