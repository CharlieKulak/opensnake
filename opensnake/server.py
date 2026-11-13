"""OpenSnake server: the web game, accounts, world records and versus multiplayer.

Run it on the computer that hosts your OpenSnake website:

    python -m opensnake.server --port 8000

Everything it stores (accounts, records) lives in its own data folder, so two
websites running their own server have separate logins and leaderboards.

HTTP API (JSON):
    POST /api/register  {username, password}     -> {token, username}
    POST /api/login     {username, password}     -> {token, username}
    POST /api/logout    (Authorization: Bearer)  -> {}
    GET  /api/me        (Authorization: Bearer)  -> your profile, points, rank and items
    POST /api/profile   {bio?, avatar?, skin?}   -> your profile
    POST /api/profile/picture  {png} (base64)    -> your profile, with your own picture as the avatar
    GET  /api/pictures/{name}                    -> {png, version}: a player's own picture
    GET  /api/users?q=                           -> {users: [...]}            (search by name)
    GET  /api/users/{name}                       -> a player's profile
    GET  /api/friends                            -> {friends, incoming, outgoing}
    POST /api/friends/add     {name}             -> send (or accept) a friend request
    POST /api/friends/remove  {name}             -> unfriend, decline or cancel
    POST /api/store/buy       {item}             -> buy a shop skin with snake points
    POST /api/store/open      {crate}            -> open a loot box: {item, new, refund, points}
    POST /api/rounds          {fruit}            -> snake points for a finished round
    GET  /api/categories?q=                      -> community custom speedrun categories
    POST /api/categories      {def}              -> share a custom category
    POST /api/categories/rename  {id, name}      -> rename a category you made
    GET  /api/rankings                           -> the community leaderboard: scores out of 100
    GET  /api/weekly                             -> this week's 10 speedrun categories, with their WRs
    GET  /api/battlepass                         -> this week's pass: your level, XP and the reward track
    POST /api/battlepass/buy                     -> buy this week's pass
    POST /api/battlepass/claim  {level}          -> claim the reward at a level you've reached
    GET  /api/messages                           -> {chats: [{name, last, unread}], unread}
    GET  /api/messages/{name}?before=id          -> {messages: [...]} with a friend (marks them read)
    POST /api/messages        {to, body}         -> send a friend a message (also pushed live as "dm")
    GET  /api/info                               -> {server, version, site}
    GET  /api/records                            -> {records: {category: {time_ms, player, date}}}
    GET  /api/leaderboard/{category}             -> {entries: [{player, time_ms, date}]}
    POST /api/runs      (Authorization: Bearer)  run file -> {valid, message, time_ms, rank, wr, pb}
WebSocket /ws: versus rooms (see Room).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
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
from . import cosmetics as cos
from .bots import BOT_NAMES, LEVEL_NAMES, LEVELS
from .bots import choose as bot_choose
from .game import DIRS, MAX_LATE_MOVES, Game, game_to_state
from .modes import BUILTIN_MODE_IDS, VERSUS_MODES, VERSUS_SIZES, speed_ms
from .speedrun import (CATEGORY_BY_ID, CUSTOM_PREFIX, WEEKLY_PREFIX, category_from_def, find_category, verify,
                       weekly_categories)
from .weeks import previous_week, time_left, week_end, week_id

REPO = Path(__file__).resolve().parents[1]
DEFAULT_WEB = REPO / "web-support" / "build" / "opensnake" / "build" / "web"
DEFAULT_DATA = REPO / "web-support" / "data"

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,20}$")
MIN_PASSWORD = 4
CODE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # no I or O, which look like 1 and 0

MAX_TEAM = 4
DEFAULT_SETTINGS = {"size": "medium", "speed": 0.5, "apples": 3, "goal": 0, "modes": []}
MAX_MATCH_NAME = 32
MAX_LISTED = 50  # public matches returned per search
MAX_BIO = 160
MAX_CATEGORY_NAME = 40
MAX_MESSAGE = 500
MESSAGE_GAP = 0.3   # seconds between messages from one account (no flooding)
ROUND_GAP = 2.0  # seconds between paid single-player rounds (one account can't farm faster)
MAX_PICTURE_BYTES = 256 * 1024
MAX_PICTURE_SIDE = 512
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def clean_text(value, limit: int, single_spaced: bool = True) -> str:
    """Text players typed, as shown to others: printable characters only, trimmed to ``limit``.

    ``single_spaced`` also turns runs of spaces into one (names, bios); messages keep theirs."""
    text = "".join(ch for ch in str(value or "") if ch.isprintable())
    if single_spaced:
        text = " ".join(text.split())
    return text.strip()[:limit].strip()


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
            BEGIN;
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                salt BLOB NOT NULL, pw BLOB NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, category TEXT NOT NULL,
                time_ms INTEGER NOT NULL, run TEXT NOT NULL, created TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS runs_cat ON runs(category, time_ms);
            CREATE TABLE IF NOT EXISTS inventory (
                user_id INTEGER NOT NULL, item TEXT NOT NULL, created TEXT NOT NULL,
                PRIMARY KEY (user_id, item));
            CREATE TABLE IF NOT EXISTS friends (
                a INTEGER NOT NULL, b INTEGER NOT NULL, accepted INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL,
                PRIMARY KEY (a, b));  -- a asked b
            CREATE TABLE IF NOT EXISTS categories (
                id TEXT PRIMARY KEY, def TEXT NOT NULL, name TEXT NOT NULL, creator INTEGER NOT NULL,
                created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS wr_hold (
                category TEXT PRIMARY KEY, user_id INTEGER NOT NULL, since TEXT NOT NULL, paid INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY, sender INTEGER NOT NULL, recipient INTEGER NOT NULL, body TEXT NOT NULL,
                created TEXT NOT NULL, read INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS messages_pair ON messages(sender, recipient, id);
            CREATE TABLE IF NOT EXISTS battlepass (
                user_id INTEGER NOT NULL, week TEXT NOT NULL, xp INTEGER NOT NULL DEFAULT 0,
                owned INTEGER NOT NULL DEFAULT 0, claimed TEXT NOT NULL DEFAULT '[]', PRIMARY KEY (user_id, week));
            CREATE TABLE IF NOT EXISTS pictures (
                user_id INTEGER PRIMARY KEY, png BLOB NOT NULL, version TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS ledger (
                id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, amount INTEGER NOT NULL, reason TEXT NOT NULL,
                created TEXT NOT NULL);
        """)
        # Profile, points and rank columns (added in 2.0): add them to the users table if it's older.
        have = {r[1] for r in self.db.execute("PRAGMA table_info(users)")}
        for column, decl in (("points", "INTEGER NOT NULL DEFAULT 0"), ("bio", "TEXT NOT NULL DEFAULT ''"),
                             ("avatar", "TEXT NOT NULL DEFAULT ''"), ("skin", "TEXT NOT NULL DEFAULT ''"),
                             ("rp", "INTEGER NOT NULL DEFAULT 0"), ("wins", "INTEGER NOT NULL DEFAULT 0"),
                             ("losses", "INTEGER NOT NULL DEFAULT 0"), ("draws", "INTEGER NOT NULL DEFAULT 0")):
            if column not in have:
                self.db.execute(f"ALTER TABLE users ADD COLUMN {column} {decl}")
        self.db.commit()  # one write for all of it

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

    # -- snake points

    def add_points(self, user_id: int, amount: int, reason: str) -> int:
        """Change a balance (logged in the ledger) and return the new balance."""
        self.db.execute("UPDATE users SET points = MAX(0, points + ?) WHERE id = ?", (amount, user_id))
        self.db.execute("INSERT INTO ledger (user_id, amount, reason, created) VALUES (?, ?, ?, ?)",
                        (user_id, amount, reason, now_iso()))
        self.db.commit()
        return self.points(user_id)

    def points(self, user_id: int) -> int:
        row = self.db.execute("SELECT points FROM users WHERE id = ?", (user_id,)).fetchone()
        return row[0] if row else 0

    def settle_wr_holds(self, now: datetime | None = None) -> list[tuple[str, int, int]]:
        """Pay world record holders for every full 3 days they've kept a built-in category's WR.

        Returns what was paid: [(category, user id, points)]."""
        now = now or datetime.now(timezone.utc)
        paid = []
        for cat in CATEGORY_BY_ID:
            best = self.db.execute("SELECT user_id, created FROM runs WHERE category = ? "
                                   "ORDER BY time_ms, created LIMIT 1", (cat,)).fetchone()
            if not best:
                continue
            hold = self.db.execute("SELECT * FROM wr_hold WHERE category = ?", (cat,)).fetchone()
            if not hold or hold["user_id"] != best["user_id"]:  # a new holder: count from when they set it
                self.db.execute("INSERT OR REPLACE INTO wr_hold VALUES (?, ?, ?, 0)",
                                (cat, best["user_id"], best["created"]))
                hold = {"user_id": best["user_id"], "since": best["created"], "paid": 0}
            since = datetime.strptime(hold["since"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            periods = int((now - since).total_seconds() // (cos.WR_HOLD_DAYS * 86400))
            if periods > hold["paid"]:
                amount = (periods - hold["paid"]) * cos.WR_HOLD_REWARD
                self.db.execute("UPDATE wr_hold SET paid = ? WHERE category = ?", (periods, cat))
                self.add_points(hold["user_id"], amount, f"held the {cat} world record")
                paid.append((cat, hold["user_id"], amount))
        self.db.commit()
        return paid

    # -- profiles

    def user_row(self, name: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM users WHERE name = ?", (name or "",)).fetchone()

    def user_by_id(self, user_id: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    def wrs_held(self, user_id: int) -> int:
        name = self.user_by_id(user_id)["name"].lower()
        return sum(1 for cat, rec in self.records().items() if cat in CATEGORY_BY_ID and rec["player"].lower() == name)

    def profile(self, row: sqlite3.Row, private: bool = False) -> dict:
        """What everyone can see about a player (plus points and items for the player themself)."""
        _i, rank, _c = cos.rank_for(row["rp"])
        out = {"name": row["name"], "bio": row["bio"], "avatar": row["avatar"] or cos.DEFAULT_AVATAR,
               "skin": row["skin"], "rp": row["rp"], "rank": rank, "wins": row["wins"], "losses": row["losses"],
               "draws": row["draws"], "joined": row["created"][:10], "wrs": self.wrs_held(row["id"])}
        if private:
            out["points"] = row["points"]
            out["inventory"] = self.inventory(row["id"])
        return out

    def set_profile(self, user_id: int, data: dict) -> None:
        if "bio" in data:
            bio = clean_text(data["bio"], MAX_BIO)
            self.db.execute("UPDATE users SET bio = ? WHERE id = ?", (bio, user_id))
        if "avatar" in data:
            icon, color = cos.parse_avatar(data["avatar"])
            self.db.execute("UPDATE users SET avatar = ? WHERE id = ?", (f"{icon}:{color}", user_id))
        if "skin" in data:
            skin = str(data["skin"] or "")
            if skin and f"skin:{skin}" not in self.inventory(user_id):
                raise ValueError("You don't own that skin.")
            self.db.execute("UPDATE users SET skin = ? WHERE id = ?", (skin, user_id))
        self.db.commit()

    def set_picture(self, user_id: int, png: bytes) -> str:
        """Store a player's own profile picture (a small PNG) and make it their avatar."""
        if not png.startswith(PNG_SIGNATURE) or png[12:16] != b"IHDR":
            raise ValueError("The picture must be a PNG image.")
        if len(png) > MAX_PICTURE_BYTES:
            raise ValueError("That picture is too big (256 KB at most).")
        w, h = int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")
        if not (1 <= w <= MAX_PICTURE_SIDE and 1 <= h <= MAX_PICTURE_SIDE):
            raise ValueError(f"The picture can be at most {MAX_PICTURE_SIDE} x {MAX_PICTURE_SIDE} pixels.")
        version = hashlib.sha1(png).hexdigest()[:10]
        self.db.execute("INSERT OR REPLACE INTO pictures VALUES (?, ?, ?)", (user_id, png, version))
        self.db.execute("UPDATE users SET avatar = ? WHERE id = ?", (f"{cos.CUSTOM_AVATAR}:{version}", user_id))
        self.db.commit()
        return version

    def picture(self, user_id: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT png, version FROM pictures WHERE user_id = ?", (user_id,)).fetchone()

    def search_users(self, query: str, limit: int = 20) -> list[sqlite3.Row]:
        q = "%" + query.replace("\\", "").replace("%", "").replace("_", "\\_") + "%"
        return self.db.execute("SELECT * FROM users WHERE name LIKE ? ESCAPE '\\' "
                               "ORDER BY LENGTH(name), name LIMIT ?", (q, limit)).fetchall()

    # -- items

    def inventory(self, user_id: int) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT item FROM inventory WHERE user_id = ? ORDER BY created",
                                              (user_id,))]

    def grant(self, user_id: int, item: str) -> bool:
        """Give an item; False if they already had it."""
        cur = self.db.execute("INSERT OR IGNORE INTO inventory VALUES (?, ?, ?)", (user_id, item, now_iso()))
        self.db.commit()
        return cur.rowcount == 1

    def buy(self, user_id: int, item: str) -> int:
        """Buy a shop skin or texture pack; returns the new balance."""
        price = cos.shop_price(item)
        if price is None:
            raise ValueError("That isn't sold in the shop.")
        if item in self.inventory(user_id):
            raise ValueError("You already own that.")
        if self.points(user_id) < price:
            raise ValueError("Not enough snake points.")
        self.grant(user_id, item)
        return self.add_points(user_id, -price, f"bought {item}")

    def open_crate(self, user_id: int, crate_id: str, rng=random, free: bool = False) -> dict:
        """Open a loot box (``free``: a battle pass reward, not bought)."""
        crate = cos.CRATE_BY_ID.get(crate_id)
        if not crate:
            raise ValueError("Unknown loot box.")
        if not free:
            if self.points(user_id) < crate.price:
                raise ValueError("Not enough snake points.")
            self.add_points(user_id, -crate.price, f"opened {crate_id}")
        return self.give_item(user_id, cos.roll(crate, rng))

    def give_item(self, user_id: int, item: str) -> dict:
        """Grant an item, or points back if they already have it."""
        new = self.grant(user_id, item)
        refund = 0 if new else cos.DUPLICATE_REFUND[cos.item_rarity(item)]
        balance = self.add_points(user_id, refund, f"duplicate {item}") if refund else self.points(user_id)
        return {"item": item, "new": new, "refund": refund, "points": balance}

    # -- the battle pass

    def pass_row(self, user_id: int, week: str | None = None) -> sqlite3.Row:
        """A player's pass for a week, started (with any levels past 100 from last week) if new."""
        week = week or week_id()
        row = self.db.execute("SELECT * FROM battlepass WHERE user_id = ? AND week = ?", (user_id, week)).fetchone()
        if row:
            return row
        last = self.db.execute("SELECT xp FROM battlepass WHERE user_id = ? AND week = ?",
                               (user_id, previous_week(week))).fetchone()
        carry = max(0, last["xp"] - cos.PASS_LEVELS * cos.LEVEL_XP) if last else 0
        self.db.execute("INSERT OR IGNORE INTO battlepass (user_id, week, xp) VALUES (?, ?, ?)", (user_id, week, carry))
        self.db.commit()
        return self.pass_row(user_id, week)

    def add_xp(self, user_id: int, xp: int) -> None:
        if xp > 0:
            week = self.pass_row(user_id)["week"]
            self.db.execute("UPDATE battlepass SET xp = xp + ? WHERE user_id = ? AND week = ?", (xp, user_id, week))
            self.db.commit()

    def buy_pass(self, user_id: int) -> int:
        row = self.pass_row(user_id)
        if row["owned"]:
            raise ValueError("You already have this week's pass.")
        if self.points(user_id) < cos.PASS_PRICE:
            raise ValueError("Not enough snake points.")
        self.db.execute("UPDATE battlepass SET owned = 1 WHERE user_id = ? AND week = ?", (user_id, row["week"]))
        return self.add_points(user_id, -cos.PASS_PRICE, f"battle pass {row['week']}")

    def claim_pass(self, user_id: int, level: int, rng=random) -> dict:
        row = self.pass_row(user_id)
        week = row["week"]
        tier = next((t for t in cos.battle_pass(week) if t["level"] == level), None)
        claimed = json.loads(row["claimed"])
        if not tier:
            raise ValueError("There's no reward at that level.")
        if not row["owned"]:
            raise ValueError("Buy this week's pass to claim its rewards.")
        if cos.pass_level(row["xp"]) < level:
            raise ValueError(f"Reach level {level} first.")
        if level in claimed:
            raise ValueError("You've already claimed that.")
        claimed.append(level)
        self.db.execute("UPDATE battlepass SET claimed = ? WHERE user_id = ? AND week = ?",
                        (json.dumps(claimed), user_id, week))
        self.db.commit()
        if tier["kind"] == "points":
            return {"tier": tier, "points": self.add_points(user_id, tier["amount"], f"battle pass level {level}")}
        if tier["kind"] == "crate":
            return {"tier": tier, **self.open_crate(user_id, tier["crate"], rng, free=True)}
        return {"tier": tier, **self.give_item(user_id, tier["item"])}

    def pass_info(self, user_id: int) -> dict:
        row = self.pass_row(user_id)
        week, xp = row["week"], row["xp"]
        level = cos.pass_level(xp)
        claimed = set(json.loads(row["claimed"]))
        return {"week": week, "ends": week_end(week).strftime("%Y-%m-%dT%H:%M:%SZ"), "left": time_left(week),
                "owned": bool(row["owned"]), "price": cos.PASS_PRICE, "xp": xp, "level": level,
                "level_xp": cos.LEVEL_XP, "into_level": xp - level * cos.LEVEL_XP, "max": cos.PASS_LEVELS,
                "tiers": [{**t, "claimed": t["level"] in claimed, "reached": level >= t["level"]}
                          for t in cos.battle_pass(week)]}

    # -- friends

    def friendship(self, me: int, other: int) -> str:
        """none / friends / outgoing (I asked) / incoming (they asked)."""
        row = self.db.execute("SELECT a, accepted FROM friends WHERE (a = ? AND b = ?) OR (a = ? AND b = ?)",
                              (me, other, other, me)).fetchone()
        if not row:
            return "none"
        if row["accepted"]:
            return "friends"
        return "outgoing" if row["a"] == me else "incoming"

    def add_friend(self, me: int, other: int) -> str:
        if me == other:
            raise ValueError("That's you!")
        state = self.friendship(me, other)
        if state == "incoming":  # they already asked: accept
            self.db.execute("UPDATE friends SET accepted = 1 WHERE a = ? AND b = ?", (other, me))
            state = "friends"
        elif state == "none":
            self.db.execute("INSERT INTO friends VALUES (?, ?, 0, ?)", (me, other, now_iso()))
            state = "outgoing"
        self.db.commit()
        return state

    def remove_friend(self, me: int, other: int) -> None:
        self.db.execute("DELETE FROM friends WHERE (a = ? AND b = ?) OR (a = ? AND b = ?)", (me, other, other, me))
        self.db.commit()

    def friends(self, me: int) -> dict:
        out = {"friends": [], "incoming": [], "outgoing": []}
        rows = self.db.execute("SELECT * FROM friends WHERE a = ? OR b = ?", (me, me)).fetchall()
        for r in rows:
            other = r["b"] if r["a"] == me else r["a"]
            key = "friends" if r["accepted"] else ("outgoing" if r["a"] == me else "incoming")
            out[key].append(other)
        return out

    # -- messages

    def send_message(self, sender: int, recipient: int, body) -> dict:
        if self.friendship(sender, recipient) != "friends":
            raise PermissionError("You can only message your friends.")
        text = clean_text(body, MAX_MESSAGE, single_spaced=False)
        if not text:
            raise ValueError("Type a message.")
        cur = self.db.execute("INSERT INTO messages (sender, recipient, body, created) VALUES (?, ?, ?, ?)",
                              (sender, recipient, text, now_iso()))
        self.db.commit()
        return self.message(cur.lastrowid)

    def message(self, message_id: int) -> dict:
        r = self.db.execute("""SELECT messages.*, s.name AS sender_name, t.name AS recipient_name FROM messages
                               JOIN users s ON s.id = messages.sender JOIN users t ON t.id = messages.recipient
                               WHERE messages.id = ?""", (message_id,)).fetchone()
        return {"id": r["id"], "from": r["sender_name"], "to": r["recipient_name"], "body": r["body"],
                "created": r["created"], "read": bool(r["read"])}

    def conversation(self, me: int, other: int, before: int | None = None, limit: int = 50) -> list[dict]:
        """The latest messages between two players (oldest first), and mark theirs to me as read."""
        rows = self.db.execute("""SELECT id FROM messages WHERE ((sender = ? AND recipient = ?) OR (sender = ? AND
                                  recipient = ?)) AND id < ? ORDER BY id DESC LIMIT ?""",
                               (me, other, other, me, before or 1 << 62, limit)).fetchall()
        self.db.execute("UPDATE messages SET read = 1 WHERE sender = ? AND recipient = ? AND read = 0", (other, me))
        self.db.commit()
        return [self.message(r["id"]) for r in reversed(rows)]

    def chats(self, me: int) -> list[dict]:
        """Everyone you've messaged with: the last message and how many of theirs you haven't read."""
        rows = self.db.execute("""
            SELECT CASE WHEN sender = ? THEN recipient ELSE sender END AS other, MAX(id) AS last,
                   SUM(CASE WHEN recipient = ? AND read = 0 THEN 1 ELSE 0 END) AS unread
            FROM messages WHERE sender = ? OR recipient = ? GROUP BY other ORDER BY last DESC""",
                               (me, me, me, me)).fetchall()
        return [{"user": r["other"], "last": self.message(r["last"]), "unread": r["unread"]} for r in rows]

    # -- versus results

    def record_match(self, user_id: int, result: str, ranked: bool, points: int) -> dict:
        """Points (and, against other people, rank points) for a finished versus match."""
        delta = {"win": cos.RP_WIN, "loss": cos.RP_LOSS, "draw": cos.RP_DRAW}[result] if ranked else 0
        column = {"win": "wins", "loss": "losses", "draw": "draws"}[result]
        if ranked:
            self.db.execute(f"UPDATE users SET rp = MAX(0, rp + ?), {column} = {column} + 1 WHERE id = ?",
                            (delta, user_id))
        balance = self.add_points(user_id, points, f"versus {result}")
        rp = self.user_by_id(user_id)["rp"]
        return {"points": points, "balance": balance, "rp": rp, "rp_change": delta, "rank": cos.rank_for(rp)[1]}

    # -- the community leaderboard

    def rankings(self) -> list[dict]:
        """Every player with a score above 0, ranked by their score out of 100 (see cosmetics.player_score)."""
        builtin = list(CATEGORY_BY_ID)
        marks = ",".join("?" * len(builtin))
        wrs: dict[str, int] = {}
        for cat, rec in self.records().items():
            if cat in CATEGORY_BY_ID:
                wrs[rec["player"].lower()] = wrs.get(rec["player"].lower(), 0) + 1
        prs = dict(self.db.execute(f"SELECT user_id, COUNT(DISTINCT category) FROM runs WHERE category IN ({marks}) "
                                   "GROUP BY user_id", builtin).fetchall())
        earned = dict(self.db.execute("SELECT user_id, SUM(amount) FROM ledger WHERE amount > 0 "
                                      "AND reason NOT LIKE 'duplicate%' GROUP BY user_id").fetchall())
        skins = dict(self.db.execute("SELECT user_id, COUNT(*) FROM inventory WHERE item LIKE 'skin:%' "
                                     "GROUP BY user_id").fetchall())
        out = []
        for row in self.db.execute("SELECT id, name, avatar, rp FROM users").fetchall():
            stats = {"wrs": wrs.get(row["name"].lower(), 0), "prs": prs.get(row["id"], 0),
                     "earned": earned.get(row["id"], 0) or 0, "skins": skins.get(row["id"], 0)}
            result = cos.player_score(stats["wrs"], stats["prs"], len(builtin), stats["earned"], stats["skins"])
            if result["score"] <= 0:
                continue
            out.append({"name": row["name"], "avatar": row["avatar"] or cos.DEFAULT_AVATAR,
                        "rank": cos.rank_for(row["rp"])[1], **stats, **result})
        out.sort(key=lambda p: (-p["score"], p["name"].lower()))
        for place, p in enumerate(out, 1):
            p["place"] = place
        return out

    # -- community categories

    def share_category(self, definition: dict, user_id: int) -> str:
        """Add a custom category to the community list (the first to share it is its creator)."""
        cat = category_from_def(definition)
        if any(m not in BUILTIN_MODE_IDS for m in cat.modes):
            raise ValueError("Categories using mods can't be shared.")
        clean = {k: definition.get(k) for k in ("w", "h", "modes", "goal", "fruit_count", "tick_ms", "fruit")}
        clean.update(id=cat.id, name=cat.name)
        self.db.execute("INSERT OR IGNORE INTO categories VALUES (?, ?, ?, ?, ?)",
                        (cat.id, json.dumps(clean), cat.name, user_id, now_iso()))
        self.db.commit()
        return cat.id

    def rename_category(self, category_id: str, user_id: int, name) -> str:
        """Rename a community category; only the player who made it can."""
        row = self.db.execute("SELECT creator, def FROM categories WHERE id = ?", (category_id,)).fetchone()
        if not row:
            raise LookupError("No such category.")
        if row["creator"] != user_id:
            raise PermissionError("Only the player who made this category can rename it.")
        clean = clean_text(name, MAX_CATEGORY_NAME)
        if not clean:
            raise ValueError("Type a name.")
        definition = {**json.loads(row["def"]), "name": clean}  # (the name isn't part of the id: records stay)
        self.db.execute("UPDATE categories SET name = ?, def = ? WHERE id = ?",
                        (clean, json.dumps(definition), category_id))
        self.db.commit()
        return clean

    def community(self, query: str = "", limit: int = 100) -> list[dict]:
        rows = self.db.execute("""
            SELECT categories.*, users.name AS creator_name,
                   (SELECT COUNT(DISTINCT user_id) FROM runs WHERE runs.category = categories.id) AS players
            FROM categories JOIN users ON users.id = categories.creator""").fetchall()
        words = query.lower().split()
        out = []
        for r in rows:
            text = f"{r['name']} {r['creator_name']}".lower()
            if not all(w in text for w in words):
                continue
            best = self.leaderboard(r["id"], 1)
            out.append({"id": r["id"], "name": r["name"], "def": json.loads(r["def"]), "creator": r["creator_name"],
                        "created": r["created"][:10], "players": r["players"], "wr": best[0] if best else None})
        out.sort(key=lambda c: (-c["players"], c["name"].lower()))
        return out[:limit]


# ---- versus rooms ---------------------------------------------------------------------

class Player:
    def __init__(self, ws: web.WebSocketResponse | None, pid: int, name: str, user_id: int | None = None,
                 bot: str | None = None):
        self.ws, self.id, self.name = ws, pid, name
        self.user_id = user_id   # None for guests and bots
        self.bot = bot           # difficulty, for computer players
        self.team = 0
        self.room: Room | None = None
        self.snake = -1  # index in the running game
        self.rank = "Bot" if bot else ""
        self.avatar = ""

    @property
    def human(self) -> bool:
        return self.bot is None


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
        self.scheduled: list[tuple[int, int, str]] = []  # (move, snake, direction): turns for a later move
        self.name = f"{host.name}'s match"
        self.public = False  # public matches show up in everyone's match search

    def info(self) -> dict:
        return {"t": "room", "code": self.code, "host": self.host.id, "state": self.state,
                "name": self.name, "public": self.public, "settings": self.settings,
                "players": [{"id": p.id, "name": p.name, "team": p.team, "bot": p.bot, "rank": p.rank,
                             "avatar": p.avatar} for p in self.players]}

    @property
    def humans(self) -> list[Player]:
        return [p for p in self.players if p.human]

    def add_bot(self, team, level) -> str | None:
        if self.state != "lobby":
            return "Bots can only join in the lobby."
        if team not in (0, 1) or level not in LEVELS:
            return "Unknown team or bot level."
        if sum(1 for q in self.players if q.team == team) >= MAX_TEAM:
            return f"That team is full ({MAX_TEAM} players)."
        taken = {q.name for q in self.players}
        name = next((f"{n} (bot)" for n in random.sample(BOT_NAMES, len(BOT_NAMES)) if f"{n} (bot)" not in taken),
                    "Bot")
        bot = Player(None, self.server.new_pid(), name, bot=level)
        bot.rank = f"{LEVEL_NAMES[level]} bot"
        bot.team, bot.room = team, self
        self.players.append(bot)
        return None

    def remove_bot(self, pid) -> str | None:
        if self.state != "lobby":
            return "Bots can only leave in the lobby."
        bot = next((q for q in self.players if q.id == pid and q.bot), None)
        if not bot:
            return "No such bot."
        self.players.remove(bot)
        return None

    def set_details(self, m: dict) -> None:
        """The host's choice of match name and whether it's public."""
        if "name" in m:
            self.name = clean_text(m["name"], MAX_MATCH_NAME) or f"{self.host.name}'s match"
        if isinstance(m.get("public"), bool):
            self.public = m["public"]

    @property
    def open(self) -> bool:
        return self.state == "lobby" and len(self.players) < 2 * MAX_TEAM

    def listing(self) -> dict:
        """What the public match search shows about this match."""
        s = self.settings
        return {"code": self.code, "name": self.name, "host": self.host.name, "players": len(self.players),
                "max": 2 * MAX_TEAM, "size": s["size"], "speed": s["speed"], "goal": s["goal"],
                "modes": s["modes"]}

    async def broadcast(self, msg: dict) -> None:
        text = json.dumps(msg, separators=(",", ":"))
        for p in list(self.players):
            if p.ws is not None and not p.ws.closed:
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
        if self.host is p and self.humans:
            self.host = self.humans[0]

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
        if new.get("size") in VERSUS_SIZES:
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
        self.scheduled = []
        order = sorted(self.players, key=lambda p: p.team)
        w, h = VERSUS_SIZES[self.settings["size"]]
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
        bot_rng = random.Random()
        while not g.over and self.humans:
            self.apply_scheduled()
            for p in self.players:
                if p.bot and p.snake >= 0:
                    d = bot_choose(g, p.snake, bot_rng, p.bot)
                    if d:
                        g.input_for(p.snake, d)
            g.step()
            state = game_to_state(g)
            g.events.clear()
            await self.broadcast({"t": "state", "s": state})
            deadline += tick
            await asyncio.sleep(max(0.0, deadline - loop.time()))
        self.state = "over"
        await self.broadcast({"t": "over", "winner": g.winner, "scores": [g.team_score(0), g.team_score(1)]})
        await self.reward(g)
        await self.broadcast(self.info())

    def apply_scheduled(self) -> None:
        """Hand the game the players' turns that were sent ahead for the move it's about to make."""
        g = self.game
        due = sorted(x for x in self.scheduled if x[0] <= g.tick + 1)
        self.scheduled = [x for x in self.scheduled if x[0] > g.tick + 1]
        for _step, snake, d in due:
            g.input_for(snake, d)

    async def reward(self, g: Game) -> None:
        """Snake points for everyone with an account, and rank points if they played other people."""
        ranked = len(self.humans) >= 2
        for p in self.players:
            if p.user_id is None or not (0 <= p.snake < len(g.snakes)):
                continue
            result = "draw" if g.winner is None else ("win" if g.winner == p.team else "loss")
            points = cos.MATCH_PLAYED + cos.MATCH_PER_FRUIT * g.snakes[p.snake].score + \
                (cos.MATCH_WIN if result == "win" else 0)
            info = self.server.db.record_match(p.user_id, result, ranked, points)
            self.server.db.add_xp(p.user_id, points)
            p.rank = info["rank"]
            await self.send(p, {"t": "reward", "result": result, "ranked": ranked, **info})

    async def send(self, p: Player, msg: dict) -> None:
        if p.ws is not None and not p.ws.closed:
            await p.ws.send_str(json.dumps(msg, separators=(",", ":")))


# ---- the server ---------------------------------------------------------------------

class Server:
    def __init__(self, data_dir: Path, web_dir: Path | None):
        self.db = Database(data_dir / "opensnake.db")
        self.web_dir = web_dir if web_dir and (web_dir / "index.html").is_file() else None
        self.rooms: dict[str, Room] = {}
        self.next_pid = 1
        self.connected: dict[int, set[Player]] = {}  # account id -> its open connections (who's online)
        self.last_round: dict[int, float] = {}       # account id -> when its last round was paid
        self.last_message: dict[int, float] = {}     # account id -> when it last sent a message
        self.settle_task: asyncio.Task | None = None

    def new_pid(self) -> int:
        self.next_pid += 1
        return self.next_pid - 1

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

    def account(self, request: web.Request, message: str) -> sqlite3.Row:
        """The logged-in player making a request; if there isn't one, answers 401 with ``message``."""
        user = self.db.user_for(self.token(request))
        if not user:
            raise web.HTTPUnauthorized(text=json.dumps({"error": message}), content_type="application/json")
        return user

    def app(self) -> web.Application:
        app = web.Application(client_max_size=4 * 1024 * 1024)
        app.on_startup.append(self.startup)
        app.on_cleanup.append(self.shutdown)
        app.on_response_prepare.append(self.revalidate)
        r = app.router
        r.add_get("/api/info", self.info)
        r.add_post("/api/register", self.register)
        r.add_post("/api/login", self.login)
        r.add_post("/api/logout", self.logout)
        r.add_get("/api/me", self.me)
        r.add_get("/api/records", self.records)
        r.add_get("/api/leaderboard/{category}", self.leaderboard)
        r.add_post("/api/runs", self.submit_run)
        r.add_get("/api/matches", self.matches)
        r.add_post("/api/profile", self.set_profile)
        r.add_post("/api/profile/picture", self.set_picture)
        r.add_get("/api/pictures/{name}", self.get_picture)
        r.add_get("/api/users", self.search_users)
        r.add_get("/api/users/{name}", self.user_profile)
        r.add_get("/api/friends", self.friends)
        r.add_post("/api/friends/add", self.add_friend)
        r.add_post("/api/friends/remove", self.remove_friend)
        r.add_post("/api/store/buy", self.buy)
        r.add_post("/api/store/open", self.open_crate)
        r.add_post("/api/rounds", self.finish_round)
        r.add_get("/api/categories", self.categories)
        r.add_post("/api/categories", self.share_category)
        r.add_post("/api/categories/rename", self.rename_category)
        r.add_get("/api/rankings", self.rankings)
        r.add_get("/api/weekly", self.weekly)
        r.add_get("/api/battlepass", self.battlepass)
        r.add_post("/api/battlepass/buy", self.buy_pass)
        r.add_post("/api/battlepass/claim", self.claim_pass)
        r.add_get("/api/messages", self.chats)
        r.add_get("/api/messages/{name}", self.conversation)
        r.add_post("/api/messages", self.send_message)
        r.add_get("/ws", self.websocket)
        if self.web_dir:
            r.add_get("/", self.index)
            r.add_static("/", self.web_dir)
        return app

    @staticmethod
    async def revalidate(request: web.Request, response: web.StreamResponse) -> None:
        """Make browsers check for a newer build every time (a cheap 304 if nothing changed).

        The game files also get a new name with every build (see web-support/build.sh)."""
        response.headers.setdefault("Cache-Control", "no-cache")

    async def startup(self, app: web.Application) -> None:
        async def settle_hourly():
            while True:
                self.db.settle_wr_holds()
                await asyncio.sleep(3600)
        self.settle_task = asyncio.create_task(settle_hourly())

    async def shutdown(self, app: web.Application) -> None:
        """Stop running matches and close the database (Windows can't delete open files)."""
        if self.settle_task:
            self.settle_task.cancel()
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
        user = self.account(request, "Not logged in.")
        self.db.settle_wr_holds()
        return web.json_response({"username": user["name"], **self.db.profile(self.db.user_by_id(user["id"]), True)})

    def summary(self, row: sqlite3.Row) -> dict:
        """A player as listed in searches and friend lists."""
        _i, rank, _c = cos.rank_for(row["rp"])
        conns = self.connected.get(row["id"], ())
        playing = next((p.room for p in conns if p.room), None)
        return {"name": row["name"], "avatar": row["avatar"] or cos.DEFAULT_AVATAR, "rank": rank, "rp": row["rp"],
                "online": bool(conns), "in_match": bool(playing)}

    async def set_profile(self, request: web.Request) -> web.Response:
        user = self.account(request, "Log in to edit your profile.")
        try:
            self.db.set_profile(user["id"], await self.body(request))
        except ValueError as e:
            return self.error(str(e))
        return web.json_response(self.db.profile(self.db.user_by_id(user["id"]), True))

    async def set_picture(self, request: web.Request) -> web.Response:
        user = self.account(request, "Log in to change your picture.")
        try:
            png = base64.b64decode(str((await self.body(request)).get("png", "")), validate=True)
        except binascii.Error:
            return self.error("The picture must be a PNG image.")
        try:
            self.db.set_picture(user["id"], png)
        except ValueError as e:
            return self.error(str(e))
        return web.json_response(self.db.profile(self.db.user_by_id(user["id"]), True))

    async def get_picture(self, request: web.Request) -> web.Response:
        row = self.db.user_row(request.match_info["name"])
        pic = self.db.picture(row["id"]) if row else None
        if not pic:
            return self.error("No picture.", 404)
        return web.json_response({"png": base64.b64encode(pic["png"]).decode(), "version": pic["version"]},
                                 headers={"Cache-Control": "max-age=3600"})

    async def search_users(self, request: web.Request) -> web.Response:
        query = request.query.get("q", "").strip()[:20]
        rows = self.db.search_users(query) if query else []
        return web.json_response({"users": [self.summary(r) for r in rows]})

    async def user_profile(self, request: web.Request) -> web.Response:
        row = self.db.user_row(request.match_info["name"])
        if not row:
            return self.error("No player with that name.", 404)
        me = self.db.user_for(self.token(request))
        return web.json_response({**self.db.profile(row), **self.summary(row),
                                  "friend": self.db.friendship(me["id"], row["id"]) if me else "none"})

    async def friends(self, request: web.Request) -> web.Response:
        user = self.account(request, "Log in to see your friends.")
        lists = self.db.friends(user["id"])
        out = {key: [self.summary(self.db.user_by_id(uid)) for uid in ids] for key, ids in lists.items()}
        out["friends"].sort(key=lambda f: (not f["online"], f["name"].lower()))
        return web.json_response(out)

    async def friend_target(self, request: web.Request):
        user = self.account(request, "Log in to add friends.")
        other = self.db.user_row(str((await self.body(request)).get("name", "")))
        if not other:
            return None, None, self.error("No player with that name.", 404)
        return user, other, None

    async def add_friend(self, request: web.Request) -> web.Response:
        user, other, err = await self.friend_target(request)
        if err:
            return err
        try:
            state = self.db.add_friend(user["id"], other["id"])
        except ValueError as e:
            return self.error(str(e))
        await self.notify(other["id"], {"t": "friends"})  # refresh their list if it's open
        return web.json_response({"friend": state})

    async def remove_friend(self, request: web.Request) -> web.Response:
        user, other, err = await self.friend_target(request)
        if err:
            return err
        self.db.remove_friend(user["id"], other["id"])
        await self.notify(other["id"], {"t": "friends"})
        return web.json_response({"friend": "none"})

    async def notify(self, user_id: int, msg: dict) -> int:
        """Send a message to every open connection of an account; returns how many got it."""
        sent = 0
        for p in list(self.connected.get(user_id, ())):
            if not p.ws.closed:
                try:
                    await p.ws.send_str(json.dumps(msg))
                    sent += 1
                except (ConnectionError, RuntimeError):
                    pass
        return sent

    # -- store
    async def buy(self, request: web.Request) -> web.Response:
        user = self.account(request, "Log in to use the store.")
        item = str((await self.body(request)).get("item", ""))
        try:
            balance = self.db.buy(user["id"], item)
        except ValueError as e:
            return self.error(str(e))
        return web.json_response({"item": item, "points": balance})

    async def open_crate(self, request: web.Request) -> web.Response:
        user = self.account(request, "Log in to open loot boxes.")
        try:
            result = self.db.open_crate(user["id"], str((await self.body(request)).get("crate", "")))
        except ValueError as e:
            return self.error(str(e))
        return web.json_response(result)

    async def finish_round(self, request: web.Request) -> web.Response:
        """Snake points for a finished single-player round (sent by the game when you die or win)."""
        user = self.account(request, "Log in to earn snake points.")
        try:
            fruit = max(0, int((await self.body(request)).get("fruit", 0)))
        except (TypeError, ValueError):
            return self.error("Expected a fruit count.")
        now = asyncio.get_running_loop().time()
        if now - self.last_round.get(user["id"], -1e9) < ROUND_GAP:
            return web.json_response({"earned": 0, "points": self.db.points(user["id"])})
        self.last_round[user["id"]] = now
        earned = cos.round_points(fruit)
        self.db.add_xp(user["id"], earned)
        return web.json_response({"earned": earned, "points": self.db.add_points(user["id"], earned, "round")})

    # -- community categories
    async def categories(self, request: web.Request) -> web.Response:
        return web.json_response({"categories": self.db.community(request.query.get("q", "").strip()[:40])})

    # -- the community leaderboard
    async def rankings(self, request: web.Request) -> web.Response:
        """The top 100, plus your own place if you're logged in and further down."""
        ranked = self.db.rankings()
        me = self.db.user_for(self.token(request))
        mine = next((p for p in ranked if me and p["name"].lower() == me["name"].lower()), None)
        return web.json_response({"players": ranked[:100], "me": mine, "total": len(ranked),
                                  "parts": [{"key": k, "label": label, "most": most}
                                            for k, label, most in cos.SCORE_PARTS]})

    # -- messages
    async def chats(self, request: web.Request) -> web.Response:
        user = self.account(request, "Log in to see your messages.")
        chats = []
        for c in self.db.chats(user["id"]):
            row = self.db.user_by_id(c["user"])
            chats.append({**self.summary(row), "last": c["last"], "unread": c["unread"]})
        return web.json_response({"chats": chats, "unread": sum(c["unread"] for c in chats)})

    async def conversation(self, request: web.Request) -> web.Response:
        user = self.account(request, "Log in to see your messages.")
        other = self.db.user_row(request.match_info["name"])
        if not other:
            return self.error("No player with that name.", 404)
        try:
            before = int(request.query["before"]) if "before" in request.query else None
        except ValueError:
            before = None
        return web.json_response({"messages": self.db.conversation(user["id"], other["id"], before)})

    async def send_message(self, request: web.Request) -> web.Response:
        user = self.account(request, "Log in to send messages.")
        data = await self.body(request)
        other = self.db.user_row(str(data.get("to", "")))
        if not other:
            return self.error("No player with that name.", 404)
        now = asyncio.get_running_loop().time()
        if now - self.last_message.get(user["id"], -1e9) < MESSAGE_GAP:
            return self.error("Slow down a little.", 429)
        try:
            msg = self.db.send_message(user["id"], other["id"], data.get("body"))
        except PermissionError as e:
            return self.error(str(e), 403)
        except ValueError as e:
            return self.error(str(e))
        self.last_message[user["id"]] = now
        live = {"t": "dm", **msg}
        await self.notify(other["id"], live)
        await self.notify(user["id"], live)  # your other windows see it too
        return web.json_response(msg)

    async def rename_category(self, request: web.Request) -> web.Response:
        user = self.account(request, "Log in to rename categories.")
        data = await self.body(request)
        try:
            name = self.db.rename_category(str(data.get("id", "")), user["id"], data.get("name"))
        except LookupError as e:
            return self.error(str(e), 404)
        except PermissionError as e:
            return self.error(str(e), 403)
        except ValueError as e:
            return self.error(str(e))
        return web.json_response({"id": data.get("id"), "name": name})

    async def share_category(self, request: web.Request) -> web.Response:
        user = self.account(request, "Log in to share categories.")
        definition = (await self.body(request)).get("def")
        try:
            cid = self.db.share_category(definition if isinstance(definition, dict) else {}, user["id"])
        except (KeyError, TypeError, ValueError) as e:
            return self.error(f"Can't share that category: {e}")
        return web.json_response({"id": cid})

    # -- world records
    async def records(self, request: web.Request) -> web.Response:
        return web.json_response({"site": request.host, "updated": now_iso(), "records": self.db.records()})

    async def leaderboard(self, request: web.Request) -> web.Response:
        return web.json_response({"category": request.match_info["category"],
                                  "entries": self.db.leaderboard(request.match_info["category"])})

    async def submit_run(self, request: web.Request) -> web.Response:
        user = self.account(request, "Log in to submit runs.")
        run = await self.body(request)
        category = str(run.get("category", ""))
        if not category.startswith((CUSTOM_PREFIX, WEEKLY_PREFIX)) and category not in CATEGORY_BY_ID:
            return self.error("Unknown category.")
        try:
            weekly = find_category(category, run).weekly if category.startswith(WEEKLY_PREFIX) else ""
        except (KeyError, ValueError):
            return self.error("Unknown category.")
        # Only built-in modes count online: mod modes (or anything else) can't set records.
        definition = run.get("category_def") if isinstance(run.get("category_def"), dict) else {}
        modes = definition.get("modes", [])
        if not isinstance(modes, list) or any(m not in BUILTIN_MODE_IDS for m in modes):
            return self.error("Runs using mods or unknown modes can't be submitted.")
        # Replaying can take a moment for long runs; keep the server responsive meanwhile.
        ok, message = await asyncio.get_running_loop().run_in_executor(None, verify, run)
        if not ok:
            return web.json_response({"valid": False, "message": message})
        time_ms = int(run["time_ms"])
        name = user["name"].lower()

        def place() -> int | None:
            board = self.db.leaderboard(category, 1000)
            return next((i + 1 for i, e in enumerate(board) if e["player"].lower() == name), None)
        before, rank_before = self.db.best_for(user["id"], category), place()
        self.db.add_run(user["id"], category, time_ms, run)
        rank = place()
        pb = before is None or time_ms < before
        wr = rank == 1 and rank_before != 1
        earned = 0
        # Built-in categories, and this week's weekly ones, pay: moving up the leaderboard
        # (100,000 for 1st, half that for 2nd...) and a real personal best. Community
        # categories keep their records but pay nothing (anyone could make one to farm).
        if category in CATEGORY_BY_ID or (weekly and weekly == week_id()):
            if rank and (rank_before is None or rank < rank_before):
                earned += cos.placement_points(rank)
            if before is None or time_ms <= before * (1 - cos.PR_MIN_GAIN):
                earned += cos.PR_REWARD
            if earned:
                self.db.add_points(user["id"], earned, f"place {rank} in {category}")
            self.db.add_xp(user["id"], (cos.XP_WEEKLY if weekly else cos.XP_SPEEDRUN) + (cos.XP_PB if pb else 0))
            if category in CATEGORY_BY_ID:
                self.db.settle_wr_holds()
        elif definition and not weekly:
            try:  # the first person to submit a run in a custom category is its creator
                self.db.share_category(definition, user["id"])
            except (KeyError, TypeError, ValueError):
                pass
        return web.json_response({
            "valid": True, "message": message, "time_ms": time_ms, "rank": rank, "rank_before": rank_before,
            "pb": pb, "wr": wr, "earned": earned, "points": self.db.points(user["id"])})

    # -- weekly speedruns and the battle pass
    async def weekly(self, request: web.Request) -> web.Response:
        week = week_id()
        records = self.db.records()
        cats = []
        for c in weekly_categories(week):
            players = self.db.db.execute("SELECT COUNT(DISTINCT user_id) FROM runs WHERE category = ?",
                                         (c.id,)).fetchone()[0]
            cats.append({"id": c.id, "name": c.name, "desc": c.desc, "players": players, "wr": records.get(c.id)})
        return web.json_response({"week": week, "left": time_left(week), "categories": cats})

    async def battlepass(self, request: web.Request) -> web.Response:
        user = self.account(request, "Log in to see the battle pass.")
        return web.json_response(self.db.pass_info(user["id"]))

    async def buy_pass(self, request: web.Request) -> web.Response:
        user = self.account(request, "Log in to buy the battle pass.")
        try:
            balance = self.db.buy_pass(user["id"])
        except ValueError as e:
            return self.error(str(e))
        return web.json_response({**self.db.pass_info(user["id"]), "points": balance})

    async def claim_pass(self, request: web.Request) -> web.Response:
        user = self.account(request, "Log in to claim rewards.")
        try:
            level = int((await self.body(request)).get("level", 0))
        except (TypeError, ValueError):
            return self.error("Expected a level.")
        try:
            result = self.db.claim_pass(user["id"], level)
        except ValueError as e:
            return self.error(str(e))
        return web.json_response({**result, "pass": self.db.pass_info(user["id"]),
                                  "points": self.db.points(user["id"])})

    # -- versus multiplayer
    async def matches(self, request: web.Request) -> web.Response:
        """Public matches that can be joined, optionally searched by name, host or code.

        Every word of ?q= has to appear in one of those (ignoring case)."""
        words = request.query.get("q", "").lower().split()[:8]
        found = []
        for room in self.rooms.values():
            if not (room.public and room.open):
                continue
            text = f"{room.name} {room.host.name} {room.code}".lower()
            if all(w in text for w in words):
                found.append(room)
        found.sort(key=lambda r: (-len(r.players), r.name.lower()))  # busiest first
        return web.json_response({"total": len(found), "matches": [r.listing() for r in found[:MAX_LISTED]]})

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
        player = Player(ws, self.new_pid(), name, user["id"] if user else None)
        if user:
            row = self.db.user_by_id(user["id"])
            player.rank, player.avatar = cos.rank_for(row["rp"])[1], row["avatar"] or cos.DEFAULT_AVATAR
            self.connected.setdefault(user["id"], set()).add(player)
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
            if player.user_id is not None:
                conns = self.connected.get(player.user_id, set())
                conns.discard(player)
                if not conns:
                    self.connected.pop(player.user_id, None)
        return ws

    async def on_message(self, p: Player, m: dict) -> None:
        t = m.get("t")
        room = p.room
        err = None
        if t == "ping":  # lets players see their round-trip time
            await p.ws.send_str(json.dumps({"t": "pong", "at": m.get("at")}))
            return
        if t == "input" and room and room.game and room.state == "playing":
            g, d = room.game, m.get("d")
            if d in DIRS and p.snake >= 0:
                # "step": the move the player's game aimed this turn at (allowing for their
                # ping). Hold it until then; if it's late anyway, apply it there when fair.
                step = m.get("step")
                if not isinstance(step, int) or step == g.tick + 1:
                    g.input_for(p.snake, d)
                elif step > g.tick + 1:
                    if step <= g.tick + 4 and len(room.scheduled) < 40:  # (no far-future or flood)
                        room.scheduled.append((step, p.snake, d))
                elif not (g.tick - step + 1 <= MAX_LATE_MOVES and g.retro_turn(p.snake, d, g.tick - step + 1)):
                    g.input_for(p.snake, d)
            return
        if t == "host":
            await self.leave(p)
            room = Room(self, self.new_code(), p)
            room.update_settings(m.get("settings") or {})
            room.set_details(m)
            self.rooms[room.code] = room
            room.add(p)
            for b in (m.get("bots") or [])[:2 * MAX_TEAM - 1] if isinstance(m.get("bots"), list) else []:
                if isinstance(b, dict):
                    room.add_bot(b.get("team"), b.get("level", "normal"))
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
        elif t == "hello":  # just connecting (shows you as online to friends)
            return
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
        elif t == "invite":
            err = await self.invite(p, room, str(m.get("name", "")))
            if not err:
                await p.ws.send_str(json.dumps({"t": "invited", "name": m.get("name")}))
                return
        elif t in ("add_bot", "remove_bot"):
            if p is not room.host:
                err = "Only the host can add or remove bots."
            elif t == "add_bot":
                err = room.add_bot(m.get("team"), m.get("level", "normal"))
            else:
                err = room.remove_bot(m.get("id"))
        elif t == "details":
            if p is not room.host:
                err = "Only the host can rename the match or make it public."
            else:
                room.set_details(m)
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

    async def invite(self, p: Player, room: Room, name: str) -> str | None:
        """Invite a friend to your match: it pops up wherever they are in the game."""
        if p.user_id is None:
            return "Log in to invite friends."
        friend = self.db.user_row(name)
        if not friend or self.db.friendship(p.user_id, friend["id"]) != "friends":
            return "You can only invite your friends."
        if room.state != "lobby":
            return "Invites can only be sent from the lobby."
        sent = await self.notify(friend["id"], {"t": "invite", "from": p.name, "code": room.code, "match": room.name})
        return None if sent else f"{friend['name']} isn't online."

    async def leave(self, p: Player) -> None:
        room = p.room
        if not room:
            return
        room.remove(p)
        if not room.humans:  # bots don't keep a match going on their own
            self.rooms.pop(room.code, None)
            if room.task:
                room.task.cancel()
        else:
            await room.broadcast(room.info())


def stale_build(web_dir: Path | None) -> bool:
    """True if the game has changed since the web game was built (e.g. pulled but not rebuilt).

    Looks at everything that goes into the build: the game package (code, images,
    sounds, packs) except the server, and the browser entry point."""
    builds = list(web_dir.glob("opensnake*.tar.gz")) if web_dir else []
    if not builds:
        return False
    code = Path(__file__).parent
    files = [f for f in code.rglob("*") if f.is_file() and f.name != "server.py" and "__pycache__" not in f.parts]
    files.append(REPO / "web-support" / "main.py")
    newest = max(f.stat().st_mtime for f in files if f.exists())
    return newest > max(f.stat().st_mtime for f in builds)


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
    if stale_build(server.web_dir):
        print("  WARNING: the game code is newer than the web game build, so the website still runs the "
              "old version. Rebuild it: web-support/build.sh (or web-support/update.sh)")
    print(f"  http://localhost:{args.port}/   (Ctrl+C to stop)", flush=True)
    web.run_app(server.app(), host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
