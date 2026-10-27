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
