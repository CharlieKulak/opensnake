"""OpenSnake server: the web game, accounts, world records and versus multiplayer.

Run it on the computer that hosts your OpenSnake website:

    python -m opensnake.server --port 8000

Everything it stores (accounts, records) lives in its own data folder, so two
websites running their own server have separate logins and leaderboards.

HTTP API (JSON):
    POST /api/register  {username, password}     -> {token, username}
    POST /api/login     {username, password}     -> {token, username}
    POST /api/logout    (Authorization: Bearer)  -> {}
    GET  /api/me        (Authorization: Bearer)  -> {username}
    GET  /api/info                               -> {server, version, site}
    GET  /api/records                            -> {records: {category: {time_ms, player, date}}}
    GET  /api/leaderboard/{category}             -> {entries: [{player, time_ms, date}]}
    POST /api/runs      (Authorization: Bearer)  run file -> {valid, message, time_ms, rank, wr, pb}
WebSocket /ws: versus rooms (see Room).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import random
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import WSMsgType, web

from . import __version__
from .game import DIRS, Game, game_to_state
from .modes import speed_ms
from .speedrun import CATEGORY_BY_ID, CUSTOM_PREFIX, verify

REPO = Path(__file__).resolve().parents[1]
DEFAULT_WEB = REPO / "web-support" / "build" / "opensnake" / "build" / "web"
DEFAULT_DATA = REPO / "web-support" / "data"

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,20}$")
MIN_PASSWORD = 4
CODE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # no I or O, which look like 1 and 0

# Modes that work in versus (the rest are single-player ideas or conflict with teams).
VERSUS_MODES = ["wall", "borderless", "cheese", "poison", "portal", "shield", "magnet", "twin",
                "statue", "key", "light"]
MAX_TEAM = 4
SIZES = {"small": (16, 12), "medium": (20, 16), "large": (28, 22)}
DEFAULT_SETTINGS = {"size": "medium", "speed": 0.5, "apples": 3, "goal": 0, "modes": []}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- storage ----------------------------------------------------------------------

class Database:
    """Accounts, login tokens and speedrun runs in one SQLite file."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                salt BLOB NOT NULL, pw BLOB NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, category TEXT NOT NULL,
                time_ms INTEGER NOT NULL, run TEXT NOT NULL, created TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS runs_cat ON runs(category, time_ms);
        """)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    @staticmethod
    def _hash(password: str, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)

    def register(self, name: str, password: str) -> str:
        if not NAME_RE.match(name or ""):
            raise ValueError("Username must be 3-20 letters, numbers, _ or -.")
        if len(password or "") < MIN_PASSWORD:
            raise ValueError(f"Password must be at least {MIN_PASSWORD} characters.")
        salt = secrets.token_bytes(16)
        try:
            cur = self.db.execute("INSERT INTO users (name, salt, pw, created) VALUES (?, ?, ?, ?)",
                                  (name, salt, self._hash(password, salt), now_iso()))
        except sqlite3.IntegrityError:
            raise ValueError("That username is taken.") from None
        self.db.commit()
        return self._new_session(cur.lastrowid)

    def login(self, name: str, password: str) -> tuple[str, str]:
        row = self.db.execute("SELECT id, name, salt, pw FROM users WHERE name = ?", (name or "",)).fetchone()
        if not row or not hmac.compare_digest(row["pw"], self._hash(password or "", row["salt"])):
            raise ValueError("Wrong username or password.")
        return self._new_session(row["id"]), row["name"]

    def _new_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        self.db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (token, user_id, now_iso()))
        self.db.commit()
        return token

    def user_for(self, token: str | None) -> sqlite3.Row | None:
        if not token:
            return None
        return self.db.execute("SELECT users.id, users.name FROM sessions JOIN users ON users.id = sessions.user_id "
                               "WHERE token = ?", (token,)).fetchone()

    def logout(self, token: str) -> None:
        self.db.execute("DELETE FROM sessions WHERE token = ?", (token,))
        self.db.commit()

    def add_run(self, user_id: int, category: str, time_ms: int, run: dict) -> None:
        self.db.execute("INSERT INTO runs (user_id, category, time_ms, run, created) VALUES (?, ?, ?, ?, ?)",
                        (user_id, category, time_ms, json.dumps(run), now_iso()))
        self.db.commit()

    def leaderboard(self, category: str, limit: int = 50) -> list[dict]:
        rows = self.db.execute("""
            SELECT users.name AS player, MIN(runs.time_ms) AS time_ms, runs.created AS date
            FROM runs JOIN users ON users.id = runs.user_id
            WHERE runs.category = ? GROUP BY runs.user_id ORDER BY time_ms, date LIMIT ?""",
                               (category, limit)).fetchall()
        return [dict(r) for r in rows]

    def records(self) -> dict[str, dict]:
        out = {}
        for cat in [r[0] for r in self.db.execute("SELECT DISTINCT category FROM runs")]:
            best = self.leaderboard(cat, 1)
            if best:
                out[cat] = best[0]
        return out

    def best_for(self, user_id: int, category: str) -> int | None:
        row = self.db.execute("SELECT MIN(time_ms) FROM runs WHERE user_id = ? AND category = ?",
                              (user_id, category)).fetchone()
        return row[0]


# ---- versus rooms ---------------------------------------------------------------------

class Player:
    def __init__(self, ws: web.WebSocketResponse, pid: int, name: str):
        self.ws, self.id, self.name = ws, pid, name
        self.team = 0
        self.room: Room | None = None
        self.snake = -1  # index in the running game


class Room:
    """A versus match: lobby -> countdown -> playing -> over (-> lobby on rematch)."""

    def __init__(self, server: "Server", code: str, host: Player):
        self.server, self.code = server, code
        self.players: list[Player] = []
        self.host = host
        self.settings = dict(DEFAULT_SETTINGS)
        self.state = "lobby"
        self.game: Game | None = None
        self.task: asyncio.Task | None = None

    def info(self) -> dict:
        return {"t": "room", "code": self.code, "host": self.host.id, "state": self.state,
                "settings": self.settings, "players": [{"id": p.id, "name": p.name, "team": p.team}
                                                       for p in self.players]}

    async def broadcast(self, msg: dict) -> None:
        text = json.dumps(msg, separators=(",", ":"))
        for p in list(self.players):
            if not p.ws.closed:
                try:
                    await p.ws.send_str(text)
                except (ConnectionError, RuntimeError):
                    pass

    def add(self, p: Player) -> None:
        sizes = [sum(1 for q in self.players if q.team == t) for t in (0, 1)]
        p.team = 0 if sizes[0] <= sizes[1] else 1
        p.room = self
        self.players.append(p)

    def remove(self, p: Player) -> None:
        if p in self.players:
            self.players.remove(p)
        p.room = None
        if self.game and 0 <= p.snake < len(self.game.snakes):
            self.game.snakes[p.snake].dead = True  # leaving mid-match knocks your snake out
        if self.host is p and self.players:
            self.host = self.players[0]

    def set_team(self, p: Player, team: int) -> str | None:
        if self.state != "lobby":
            return "You can only switch teams in the lobby."
        if team not in (0, 1):
            return "Unknown team."
        if sum(1 for q in self.players if q.team == team and q is not p) >= MAX_TEAM:
            return f"That team is full ({MAX_TEAM} players)."
        p.team = team
        return None

    def update_settings(self, new: dict) -> None:
        s = self.settings
        if new.get("size") in SIZES:
            s["size"] = new["size"]
        try:
            s["speed"] = min(1.0, max(0.0, float(new.get("speed", s["speed"]))))
            s["apples"] = min(10, max(1, int(new.get("apples", s["apples"]))))
            s["goal"] = min(200, max(0, int(new.get("goal", s["goal"]))))
        except (TypeError, ValueError):
            pass
        if isinstance(new.get("modes"), list):
            s["modes"] = [m for m in VERSUS_MODES if m in new["modes"]]

    def start(self) -> str | None:
        if self.state not in ("lobby", "over"):
            return "The match has already started."
        teams = [sum(1 for p in self.players if p.team == t) for t in (0, 1)]
        if not all(teams):
            return "Both teams need at least one player."
        order = sorted(self.players, key=lambda p: p.team)
        w, h = SIZES[self.settings["size"]]
        self.game = Game(w, h, self.settings["modes"], self.settings["apples"],
                         "apple", random.Random(), teams=[p.team for p in order], goal=self.settings["goal"])
        for i, p in enumerate(order):
            p.snake = i
            self.game.snakes[i].name = p.name
        self.task = asyncio.create_task(self.run())
        return None

    async def run(self) -> None:
        g = self.game
        tick = speed_ms(self.settings["speed"]) / 1000
        self.state = "countdown"
        await self.broadcast(self.info())
        for p in self.players:
            await self.send(p, {"t": "start", "you": p.snake, "tick_ms": tick * 1000,
                                "state": game_to_state(g)})
        for n in (3, 2, 1):
            await self.broadcast({"t": "countdown", "n": n})
            await asyncio.sleep(1)
        g.started = True
        self.state = "playing"
        await self.broadcast({"t": "countdown", "n": 0})
        loop = asyncio.get_running_loop()
        deadline = loop.time()
        while not g.over and self.players:
            g.step()
            state = game_to_state(g)
            g.events.clear()
            await self.broadcast({"t": "state", "s": state})
            deadline += tick
            await asyncio.sleep(max(0.0, deadline - loop.time()))
        self.state = "over"
        await self.broadcast({"t": "over", "winner": g.winner, "scores": [g.team_score(0), g.team_score(1)]})
        await self.broadcast(self.info())

    async def send(self, p: Player, msg: dict) -> None:
        if not p.ws.closed:
            await p.ws.send_str(json.dumps(msg, separators=(",", ":")))


# ---- the server ---------------------------------------------------------------------

class Server:
    def __init__(self, data_dir: Path, web_dir: Path | None):
        self.db = Database(data_dir / "opensnake.db")
        self.web_dir = web_dir if web_dir and (web_dir / "index.html").is_file() else None
        self.rooms: dict[str, Room] = {}
        self.next_pid = 1

    # -- helpers
    @staticmethod
    def token(request: web.Request) -> str | None:
        auth = request.headers.get("Authorization", "")
        return auth[7:].strip() if auth.startswith("Bearer ") else None

    @staticmethod
    async def body(request: web.Request) -> dict:
        try:
            data = await request.json()
        except (ValueError, UnicodeDecodeError):
            raise web.HTTPBadRequest(text=json.dumps({"error": "Expected JSON."}),
                                     content_type="application/json") from None
        if not isinstance(data, dict):
            raise web.HTTPBadRequest(text=json.dumps({"error": "Expected a JSON object."}),
                                     content_type="application/json")
        return data

    @staticmethod
    def error(message: str, status: int = 400) -> web.Response:
        return web.json_response({"error": message}, status=status)

    def app(self) -> web.Application:
        app = web.Application(client_max_size=4 * 1024 * 1024)
        app.on_cleanup.append(self.shutdown)
        r = app.router
        r.add_get("/api/info", self.info)
        r.add_post("/api/register", self.register)
        r.add_post("/api/login", self.login)
        r.add_post("/api/logout", self.logout)
        r.add_get("/api/me", self.me)
        r.add_get("/api/records", self.records)
        r.add_get("/api/leaderboard/{category}", self.leaderboard)
        r.add_post("/api/runs", self.submit_run)
        r.add_get("/ws", self.websocket)
        if self.web_dir:
            r.add_get("/", self.index)
            r.add_static("/", self.web_dir)
        return app

    async def shutdown(self, app: web.Application) -> None:
        """Stop running matches and close the database (Windows can't delete open files)."""
        for room in list(self.rooms.values()):
            if room.task:
                room.task.cancel()
        self.rooms.clear()
        self.db.close()

    # -- web game
    async def index(self, request: web.Request) -> web.StreamResponse:
        return web.FileResponse(self.web_dir / "index.html", headers={"Cache-Control": "no-store"})

    # -- accounts
    async def info(self, request: web.Request) -> web.Response:
        return web.json_response({"server": "OpenSnake", "version": __version__, "site": request.host})

    async def register(self, request: web.Request) -> web.Response:
        data = await self.body(request)
        try:
            token = self.db.register(str(data.get("username", "")), str(data.get("password", "")))
        except ValueError as e:
            return self.error(str(e))
        return web.json_response({"token": token, "username": data["username"]})

    async def login(self, request: web.Request) -> web.Response:
        data = await self.body(request)
        try:
            token, name = self.db.login(str(data.get("username", "")), str(data.get("password", "")))
        except ValueError as e:
            return self.error(str(e), 401)
        return web.json_response({"token": token, "username": name})

    async def logout(self, request: web.Request) -> web.Response:
        if self.token(request):
            self.db.logout(self.token(request))
        return web.json_response({})

    async def me(self, request: web.Request) -> web.Response:
        user = self.db.user_for(self.token(request))
        if not user:
            return self.error("Not logged in.", 401)
        return web.json_response({"username": user["name"]})

    # -- world records
    async def records(self, request: web.Request) -> web.Response:
        return web.json_response({"site": request.host, "updated": now_iso(), "records": self.db.records()})

    async def leaderboard(self, request: web.Request) -> web.Response:
        return web.json_response({"category": request.match_info["category"],
                                  "entries": self.db.leaderboard(request.match_info["category"])})

    async def submit_run(self, request: web.Request) -> web.Response:
        user = self.db.user_for(self.token(request))
        if not user:
            return self.error("Log in to submit runs.", 401)
        run = await self.body(request)
        category = str(run.get("category", ""))
        if category not in CATEGORY_BY_ID and not category.startswith(CUSTOM_PREFIX):
            return self.error("Unknown category.")
        # Replaying can take a moment for long runs; keep the server responsive meanwhile.
        ok, message = await asyncio.get_running_loop().run_in_executor(None, verify, run)
        if not ok:
            return web.json_response({"valid": False, "message": message})
        time_ms = int(run["time_ms"])
        before = self.db.best_for(user["id"], category)
        wr_before = self.db.records().get(category)
        self.db.add_run(user["id"], category, time_ms, run)
        board = self.db.leaderboard(category, 1000)
        rank = next((i + 1 for i, e in enumerate(board) if e["player"].lower() == user["name"].lower()), None)
        return web.json_response({
            "valid": True, "message": message, "time_ms": time_ms, "rank": rank,
            "pb": before is None or time_ms < before,
            "wr": wr_before is None or time_ms < wr_before["time_ms"]})

    # -- versus multiplayer
    def new_code(self) -> str:
        while True:
            code = "".join(random.choice(CODE_LETTERS) for _ in range(4))
            if code not in self.rooms:
                return code

    async def websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        user = self.db.user_for(request.query.get("token"))
        guest = re.sub(r"[^A-Za-z0-9_ -]", "", request.query.get("name", ""))[:16].strip()
        name = user["name"] if user else (guest or f"Guest{random.randint(100, 999)}")
        player = Player(ws, self.next_pid, name)
        self.next_pid += 1
        await ws.send_str(json.dumps({"t": "welcome", "id": player.id, "name": name, "account": bool(user)}))
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except ValueError:
                    continue
                if isinstance(data, dict):
                    await self.on_message(player, data)
        finally:
            await self.leave(player)
        return ws

    async def on_message(self, p: Player, m: dict) -> None:
        t = m.get("t")
        room = p.room
        err = None
        if t == "input" and room and room.game and room.state == "playing":
            if m.get("d") in DIRS and p.snake >= 0:
                room.game.input_for(p.snake, m["d"])
            return
        if t == "host":
            await self.leave(p)
            room = Room(self, self.new_code(), p)
            room.update_settings(m.get("settings") or {})
            self.rooms[room.code] = room
            room.add(p)
        elif t == "join":
            await self.leave(p)
            room = self.rooms.get(str(m.get("code", "")).strip().upper())
            if not room:
                err = "No match with that code."
            elif room.state != "lobby":
                err = "That match has already started."
            elif len(room.players) >= 2 * MAX_TEAM:
                err = "That match is full."
            else:
                room.add(p)
        elif t == "leave":
            await self.leave(p)
            room = None
        elif not room:
            err = "You're not in a match."
        elif t == "team":
            err = room.set_team(p, m.get("team"))
        elif t == "settings":
            if p is not room.host:
                err = "Only the host can change settings."
            elif room.state != "lobby":
                err = "Settings can only change in the lobby."
            else:
                room.update_settings(m.get("settings") or {})
        elif t == "start":
            err = "Only the host can start." if p is not room.host else room.start()
        elif t == "rematch":
            if p is room.host and room.state == "over":
                room.state = "lobby"
                room.game = None
        if err:
            await p.ws.send_str(json.dumps({"t": "error", "msg": err}))
        if room and room.code in self.rooms:
            await room.broadcast(room.info())

    async def leave(self, p: Player) -> None:
        room = p.room
        if not room:
            return
        room.remove(p)
        if not room.players:
            self.rooms.pop(room.code, None)
            if room.task:
                room.task.cancel()
        else:
            await room.broadcast(room.info())


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="opensnake.server", description="OpenSnake website + game server")
    parser.add_argument("--host", default="0.0.0.0", help="address to listen on (default: all)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--web", type=Path, default=DEFAULT_WEB, help="folder with the built web game")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="folder for accounts and records")
    args = parser.parse_args(argv)
    server = Server(args.data, args.web)
    print(f"OpenSnake server {__version__}")
    print(f"  data:     {args.data}")
    print(f"  web game: {server.web_dir or 'not built (run web-support/build.sh); API only'}")
    print(f"  http://localhost:{args.port}/   (Ctrl+C to stop)", flush=True)
    web.run_app(server.app(), host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
