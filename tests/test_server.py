import asyncio
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).parent))
from test_speedrun import bot_run  # noqa: E402

from opensnake.server import Server  # noqa: E402
from opensnake.speedrun import CATEGORY_BY_ID  # noqa: E402


class ServerTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.client = await self.make_client(Path(self.tmp.name) / "a")

    async def make_client(self, data_dir):
        client = TestClient(TestServer(Server(data_dir, None).app()))
        await client.start_server()
        return client

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def post(self, path, data, token=None, client=None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        resp = await (client or self.client).post(path, json=data, headers=headers)
        return resp.status, await resp.json()

    async def get(self, path, token=None, client=None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        resp = await (client or self.client).get(path, headers=headers)
        return resp.status, await resp.json()

    async def account(self, name="alice", client=None):
        status, data = await self.post("/api/register", {"username": name, "password": "hunter2"}, client=client)
        self.assertEqual(status, 200, data)
        return data["token"]


class ShutdownTests(ServerTestCase):
    async def test_database_is_closed_on_shutdown(self):
        await self.account()
        await self.client.close()  # runs the server's clean-up
        db = Path(self.tmp.name) / "a" / "opensnake.db"
        db.rename(db.with_suffix(".moved"))  # Windows refuses this while the file is still open
        self.client = await self.make_client(Path(self.tmp.name) / "a")  # asyncTearDown closes this one


class CacheTests(ServerTestCase):
    async def test_browsers_revalidate_the_web_game(self):
        web_dir = Path(self.tmp.name) / "web"
        web_dir.mkdir()
        (web_dir / "index.html").write_text("<html></html>")
        (web_dir / "opensnake.apk").write_bytes(b"new build")
        client = TestClient(TestServer(Server(Path(self.tmp.name) / "w", web_dir).app()))
        await client.start_server()
        try:
            resp = await client.get("/opensnake.apk")
            self.assertEqual(resp.headers["Cache-Control"], "no-cache")
            resp = await client.get("/opensnake.apk", headers={"If-None-Match": resp.headers["ETag"]})
            self.assertEqual(resp.status, 304)  # unchanged builds aren't downloaded again
            self.assertEqual((await client.get("/"))
                             .headers["Cache-Control"], "no-store")
        finally:
            await client.close()

    def test_stale_build_is_noticed(self):
        import os
        from opensnake.server import stale_build
        web_dir = Path(self.tmp.name) / "web"
        web_dir.mkdir()
        apk = web_dir / "opensnake-0123456789ab.tar.gz"
        apk.write_bytes(b"build")
        os.utime(apk, (0, 0))  # built long before the code
        self.assertTrue(stale_build(web_dir))
        now = 4_000_000_000
        os.utime(apk, (now, now))  # built after it
        self.assertFalse(stale_build(web_dir))
        self.assertFalse(stale_build(None))


class AccountTests(ServerTestCase):
    async def test_register_login_me_logout(self):
        token = await self.account()
        self.assertEqual((await self.get("/api/me", token))[1]["username"], "alice")
        status, data = await self.post("/api/login", {"username": "ALICE", "password": "hunter2"})
        self.assertEqual(status, 200)
        self.assertEqual(data["username"], "alice")  # names are case-insensitive, shown as registered
        await self.post("/api/logout", {}, token)
        self.assertEqual((await self.get("/api/me", token))[0], 401)
        self.assertEqual((await self.get("/api/me", data["token"]))[0], 200)  # other sessions stay

    async def test_bad_input(self):
        await self.account()
        self.assertIn("taken", (await self.post("/api/register", {"username": "Alice", "password": "pass1"}))[1]["error"])
        self.assertEqual((await self.post("/api/login", {"username": "alice", "password": "nope"}))[0], 401)
        self.assertEqual((await self.post("/api/register", {"username": "a!", "password": "pass1"}))[0], 400)
        self.assertEqual((await self.post("/api/register", {"username": "bob", "password": "12"}))[0], 400)
        resp = await self.client.post("/api/login", data="not json")
        self.assertEqual(resp.status, 400)

    async def test_sites_are_separate(self):
        await self.account("alice")
        other = await self.make_client(Path(self.tmp.name) / "b")
        try:
            status, _ = await self.post("/api/login", {"username": "alice", "password": "hunter2"}, client=other)
            self.assertEqual(status, 401)  # an account on one site doesn't exist on another
        finally:
            await other.close()


class RecordTests(ServerTestCase):
    async def test_submit_verified_runs(self):
        token = await self.account()
        cat = CATEGORY_BY_ID["sprint10"]
        fast = bot_run(cat, 4, random.Random(3))
        self.assertTrue(fast.finished)
        status, res = await self.post("/api/runs", fast.to_json("alice"), token)
        self.assertEqual(status, 200)
        self.assertTrue(res["valid"] and res["wr"] and res["pb"], res)
        self.assertEqual(res["rank"], 1)
        records = (await self.get("/api/records"))[1]["records"]
        self.assertEqual(records["sprint10"]["player"], "alice")
        self.assertEqual(records["sprint10"]["time_ms"], round(fast.elapsed))

        # someone slower doesn't take the record, and gets rank 2
        bob = await self.account("bob")
        slow = None
        for seed in range(5, 40):
            r = bot_run(cat, seed, random.Random(seed))
            if r.finished and r.elapsed > fast.elapsed:
                slow = r
                break
        self.assertIsNotNone(slow)
        res = (await self.post("/api/runs", slow.to_json("bob"), bob))[1]
        self.assertTrue(res["valid"] and res["pb"] and not res["wr"])
        self.assertEqual(res["rank"], 2)
        board = (await self.get("/api/leaderboard/sprint10"))[1]["entries"]
        self.assertEqual([e["player"] for e in board], ["alice", "bob"])

    async def test_rejected_runs(self):
        token = await self.account()
        run = bot_run(CATEGORY_BY_ID["sprint10"], 4, random.Random(3)).to_json()
        self.assertEqual((await self.post("/api/runs", run))[0], 401)  # must be logged in
        tampered = dict(run, time_ms=run["time_ms"] - 1000)
        res = (await self.post("/api/runs", tampered, token))[1]
        self.assertFalse(res["valid"])
        self.assertEqual((await self.post("/api/runs", dict(run, category="nope"), token))[0], 400)
        self.assertEqual((await self.get("/api/records"))[1]["records"], {})


class VersusTests(ServerTestCase):
    async def recv(self, ws, kind, timeout=8):
        """Next message of a given type (skipping others)."""
        async def wait():
            while True:
                msg = json.loads((await ws.receive()).data)
                if msg["t"] == kind:
                    return msg
        return await asyncio.wait_for(wait(), timeout)

    async def test_host_join_play_to_the_end(self):
        token = await self.account("hosty")
        host = await self.client.ws_connect(f"/ws?token={token}")
        guest = await self.client.ws_connect("/ws?name=Bob")
        self.assertEqual((await self.recv(host, "welcome"))["name"], "hosty")
        self.assertEqual((await self.recv(guest, "welcome"))["name"], "Bob")

        await host.send_json({"t": "host", "settings": {"size": "small", "speed": 1.0, "modes": ["wall", "bogus"]}})
        room = await self.recv(host, "room")
        code = room["code"]
        self.assertEqual(len(code), 4)
        self.assertEqual(room["settings"]["modes"], ["wall"])  # unknown modes are dropped

        await guest.send_json({"t": "join", "code": code.lower()})  # codes aren't case-sensitive
        room = await self.recv(guest, "room")
        self.assertEqual(sorted((p["name"], p["team"]) for p in room["players"]), [("Bob", 1), ("hosty", 0)])

        await guest.send_json({"t": "start"})
        self.assertIn("host", (await self.recv(guest, "error"))["msg"])

        await host.send_json({"t": "start"})
        start = await self.recv(guest, "start")
        self.assertEqual(start["state"]["snakes"][start["you"]]["name"], "Bob")
        self.assertEqual((await self.recv(guest, "countdown"))["n"], 3)
        state = (await self.recv(guest, "state"))["s"]
        self.assertEqual(len(state["snakes"]), 2)
        await guest.send_json({"t": "input", "d": "up"})
        over = await self.recv(guest, "over", timeout=20)  # nobody steers, so both crash soon
        self.assertIn(over["winner"], (0, 1, None))
        await host.close()
        await guest.close()

    async def test_join_errors_and_team_limits(self):
        a = await self.client.ws_connect("/ws?name=A")
        await self.recv(a, "welcome")
        await a.send_json({"t": "join", "code": "ZZZZ"})
        self.assertIn("No match", (await self.recv(a, "error"))["msg"])
        await a.send_json({"t": "host"})
        code = (await self.recv(a, "room"))["code"]
        others = []
        for i in range(7):  # fill to 4v4
            ws = await self.client.ws_connect(f"/ws?name=P{i}")
            await self.recv(ws, "welcome")
            await ws.send_json({"t": "join", "code": code})
            await self.recv(ws, "room")
            others.append(ws)
        extra = await self.client.ws_connect("/ws?name=Late")
        await self.recv(extra, "welcome")
        await extra.send_json({"t": "join", "code": code})
        self.assertIn("full", (await self.recv(extra, "error"))["msg"])
        # P0 was balanced onto team 1; team 0 already has 4, so switching there must fail
        await others[0].send_json({"t": "team", "team": 0})
        msg = await self.recv(others[0], "error")
        self.assertIn("full", msg["msg"])
        for ws in others + [a, extra]:
            await ws.close()

    async def test_one_team_cannot_start(self):
        a = await self.client.ws_connect("/ws?name=Solo")
        await self.recv(a, "welcome")
        await a.send_json({"t": "host"})
        await self.recv(a, "room")
        await a.send_json({"t": "start"})
        self.assertIn("Both teams", (await self.recv(a, "error"))["msg"])
        await a.close()


if __name__ == "__main__":
    unittest.main()


class ModsOfflineOnlyTests(ServerTestCase):
    async def test_runs_with_mod_modes_are_rejected(self):
        from opensnake.speedrun import make_custom
        token = await self.account()
        cat = make_custom(10, 9, ["somemod"], 3, 1, 130)  # "somemod" isn't a built-in mode
        run = bot_run(cat, 4, random.Random(3))
        self.assertTrue(run.finished)
        status, res = await self.post("/api/runs", run.to_json(), token)
        self.assertEqual(status, 400)
        self.assertIn("mods", res["error"])
        ok = make_custom(10, 9, ["wall"], 3, 1, 130)  # built-in modes are fine
        res = (await self.post("/api/runs", bot_run(ok, 4, random.Random(3)).to_json(), token))[1]
        self.assertTrue(res.get("valid"), res)


class PublicMatchTests(ServerTestCase):
    recv = VersusTests.recv

    async def host(self, player, **details):
        ws = await self.client.ws_connect(f"/ws?name={player}")
        await self.recv(ws, "welcome")
        await ws.send_json({"t": "host", **details})
        return ws, await self.recv(ws, "room")

    async def search(self, q=""):
        status, data = await self.get(f"/api/matches?q={q}")
        self.assertEqual(status, 200)
        return [m["name"] for m in data["matches"]]

    async def test_names_and_privacy(self):
        a, room = await self.host("Ann")
        self.assertEqual((room["name"], room["public"]), ("Ann's match", False))  # private by default
        self.assertEqual(await self.search(), [])
        await a.send_json({"t": "details", "name": "  Snake   party\n ", "public": True})
        room = await self.recv(a, "room")
        self.assertEqual((room["name"], room["public"]), ("Snake party", True))
        self.assertEqual(await self.search(), ["Snake party"])
        await a.send_json({"t": "details", "name": "x" * 99})
        self.assertEqual(len((await self.recv(a, "room"))["name"]), 32)
        await a.send_json({"t": "details", "name": ""})  # blank goes back to the default
        self.assertEqual((await self.recv(a, "room"))["name"], "Ann's match")

        guest = await self.client.ws_connect("/ws?name=Gus")
        await self.recv(guest, "welcome")
        await guest.send_json({"t": "join", "code": room["code"]})
        await self.recv(guest, "room")
        await guest.send_json({"t": "details", "public": False})
        self.assertIn("host", (await self.recv(guest, "error"))["msg"])
        await a.send_json({"t": "start"})  # started matches can't be joined, so they're not listed
        await self.recv(a, "start")
        self.assertEqual(await self.search(), [])
        for ws in (a, guest):
            await ws.close()

    async def test_search(self):
        socks = []
        for name, title in [("Ann", "Friday fun"), ("Bob", "Pros only"), ("Cat", "fun for everyone")]:
            ws, room = await self.host(name, name=title, public=True)
            socks.append(ws)
        hidden, _ = await self.host("Dan", name="Secret fun")  # private
        socks.append(hidden)
        self.assertEqual(sorted(await self.search()), ["Friday fun", "Pros only", "fun for everyone"])
        self.assertEqual(sorted(await self.search("FUN")), ["Friday fun", "fun for everyone"])
        self.assertEqual(await self.search("fun%20cat"), ["fun for everyone"])  # host names count too
        self.assertEqual(await self.search(room["code"]), ["fun for everyone"])  # and codes
        self.assertEqual(await self.search("nothing"), [])
        status, data = await self.get("/api/matches")
        listing = next(m for m in data["matches"] if m["name"] == "Pros only")
        self.assertEqual((listing["host"], listing["players"], listing["max"]), ("Bob", 1, 8))
        for ws in socks:
            await ws.close()
