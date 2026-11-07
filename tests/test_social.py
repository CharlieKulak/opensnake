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
    def test_seventy_skins_with_the_rarest_only_in_loot_boxes(self):
        self.assertEqual(len(cos.SKINS), 70)
        self.assertEqual(len({s.id for s in cos.SKINS}), 70)
        stands = [s for s in cos.SKINS if s.series == "Stand"]
        self.assertEqual(len(stands), 20)
        self.assertTrue(all(not s.shop for s in stands))
        for s in cos.SKINS:
            self.assertIn(s.rarity, cos.RARITIES)
            if s.rarity in ("epic", "legendary", "mythic"):
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
        self.assertEqual(res["earned"], cos.PR_REWARD + cos.WR_REWARD)  # first run: a PR and the WR
        res = (await self.post("/api/runs", slow.to_json(), b))[1]   # same time: a PR, not a WR
        self.assertEqual(res["earned"], cos.PR_REWARD)
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
        # a duplicate gives points back
        before = db.points(1)
        dup = db.open_crate(1, "bronze", FixedRoll(res["item"]))
        self.assertFalse(dup["new"])
        self.assertEqual(dup["points"], before - 2000 + cos.DUPLICATE_REFUND[cos.item_rarity(res["item"])])
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


class ClientRobustnessTests(ServerTestCase):
    """The game side: a bad reply can't freeze the game, and downloaded pictures decode."""

    def setUp(self):
        import os
        import tempfile
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        self.cfg = tempfile.TemporaryDirectory()
        os.environ["OPENSNAKE_CONFIG_DIR"] = self.cfg.name
        from opensnake.app import App
        self.app = App()

    def tearDown(self):
        self.cfg.cleanup()

    def test_a_failing_reply_handler_does_not_stop_the_game(self):
        class Done:
            done = ok = True
            def poll(self):
                return True
        later = []
        on = self.app.online
        on.requests = [(Done(), lambda r: 1 / 0), (Done(), lambda r: later.append("ran"))]
        on.poll()  # used to raise, which stopped the main loop in the browser
        self.assertEqual(later, ["ran"])
        self.assertIn("went wrong", on.message)

    def test_pictures_decode(self):
        import base64
        from opensnake.net import decode_png, load_picture
        img = decode_png(base64.b64decode(load_picture("packaging/linux/opensnake-256.png")))
        self.assertEqual(img.get_size(), (128, 128))
