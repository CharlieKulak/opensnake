"""OpenSnake server: accounts, snake points, world records, versus and the site's web clients.

Run it on the computer that hosts your OpenSnake website:

    opensnake-server --port 8000        (or: python -m opensnake)

Any game that speaks the API below is a client: Crustacean and PySnake are two.
The site serves the web builds in web-support/clients/ (see web-support/README.md).

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
    POST /api/store/open      {crate}            -> open a loot box: {item, new, copies, points}
    GET  /api/market?q=&rarity=&sort=            -> {listings, mine}: skins and packs players are selling
    POST /api/market/list     {item, price}      -> put one copy of an item up for sale
    POST /api/market/cancel   {id}               -> take your listing down (you get the item back)
    POST /api/market/buy      {id}               -> buy a listing
    GET  /api/daily                              -> today's three challenges and your progress
    GET  /api/login-reward                       -> {ready, streak, step, rewards}: today's login reward
    POST /api/login-reward/claim                 -> claim it (points, or a loot box: {item, new, ...})
    GET  /api/trades                             -> {incoming, outgoing, history}
    POST /api/trades  {to, give, give_points, want, want_points} -> offer a trade (items: "skin:id"...)
    POST /api/trades/answer  {id, action}        -> accept, decline (offered to you) or cancel (yours)
    GET  /api/users/{name}/items                 -> {name, items: {item: copies}}: what they could trade
    GET  /api/replay/{category}                  -> {player, time_ms, date, run}: the WR run, to watch
    GET  /api/jackpot                            -> the pot: players (items, value, chance), total, seconds_left, last draw
    POST /api/jackpot/enter   {items}            -> put items in the pot (drawn 45 s after a second player joins)
    POST /api/daily/claim     {id} (0-2 or "bonus") -> claim a finished challenge's snake points
    POST /api/rounds          {fruit}            -> snake points for a finished round
    GET  /api/categories?q=&sort=top|popular|new -> community custom speedrun categories (search, sort)
    POST /api/categories/vote    {id, up}        -> upvote a community category (up: false takes it back)
    POST /api/categories      {def}              -> share a custom category: {id, new, name, creator}
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
    GET  /api/clients                            -> {default, clients: [{name, path}]}: the site's web clients
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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aiohttp import WSMsgType, web

from . import __version__
from . import cosmetics as cos
from .bots import BOT_NAMES, LEVEL_NAMES, LEVELS
from .bots import choose as bot_choose
from .game import DIRS, MAX_LATE_MOVES, Game, game_to_state
from .modes import BUILTIN_MODE_IDS, VERSUS_MODES, VERSUS_SIZES, speed_ms
from .speedrun import (CATEGORY_BY_ID, CUSTOM_PREFIX, WEEKLY_PREFIX, category_def, category_from_def,
                       find_category, verify, weekly_categories)
from .weeks import previous_week, time_left, week_end, week_id, week_start

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DATA = REPO / "web-support" / "data"
# Web clients the site serves: one folder each (with an index.html), served at /<folder>/
DEFAULT_CLIENTS = REPO / "web-support" / "clients"
CLIENT_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
PREFERRED_CLIENTS = ["crustacean", "py"]  # the default client (at /), if there and no other is chosen

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,20}$")
MIN_PASSWORD = 4
CODE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # no I or O, which look like 1 and 0

MAX_TEAM = 4
DEFAULT_SETTINGS = {"size": "medium", "speed": 0.5, "apples": 3, "goal": 0, "modes": []}
MAX_MATCH_NAME = 32
MAX_LISTED = 50  # public matches returned per search
MAX_BIO = 160
MAX_CATEGORY_NAME = 40
MAX_CATEGORIES_EACH = 50  # community categories one player can make
MAX_MESSAGE = 500
MESSAGE_GAP = 0.3   # seconds between messages from one account (no flooding)
MAX_ROUND_FRUIT = 300  # most fruit one round counts towards daily challenges
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


def _parse_iso(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


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
            CREATE TABLE IF NOT EXISTS category_votes (
                category TEXT NOT NULL, user_id INTEGER NOT NULL, created TEXT NOT NULL,
                PRIMARY KEY (category, user_id));
            CREATE TABLE IF NOT EXISTS wr_hold (
                category TEXT PRIMARY KEY, user_id INTEGER NOT NULL, since TEXT NOT NULL, paid INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY, sender INTEGER NOT NULL, recipient INTEGER NOT NULL, body TEXT NOT NULL,
                created TEXT NOT NULL, read INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS messages_pair ON messages(sender, recipient, id);
            CREATE TABLE IF NOT EXISTS week_resets (week TEXT PRIMARY KEY, n INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS battlepass (
                user_id INTEGER NOT NULL, week TEXT NOT NULL, xp INTEGER NOT NULL DEFAULT 0,
                owned INTEGER NOT NULL DEFAULT 0, claimed TEXT NOT NULL DEFAULT '[]', PRIMARY KEY (user_id, week));
            CREATE TABLE IF NOT EXISTS pictures (
                user_id INTEGER PRIMARY KEY, png BLOB NOT NULL, version TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS ledger (
                id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, amount INTEGER NOT NULL, reason TEXT NOT NULL,
                created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS listings (
                id INTEGER PRIMARY KEY, seller INTEGER NOT NULL, item TEXT NOT NULL, price INTEGER NOT NULL,
                created TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS listings_item ON listings(item, price);
            CREATE TABLE IF NOT EXISTS jackpot_rounds (
                id INTEGER PRIMARY KEY, status TEXT NOT NULL DEFAULT 'open', created TEXT NOT NULL,
                ends TEXT NOT NULL DEFAULT '', winner INTEGER, total INTEGER NOT NULL DEFAULT 0,
                done TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS jackpot_entries (
                id INTEGER PRIMARY KEY, round INTEGER NOT NULL, user_id INTEGER NOT NULL, item TEXT NOT NULL,
                value INTEGER NOT NULL, created TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS jackpot_entries_round ON jackpot_entries(round);
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY, sender INTEGER NOT NULL, recipient INTEGER NOT NULL,
                give TEXT NOT NULL, give_points INTEGER NOT NULL, want TEXT NOT NULL, want_points INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'open', created TEXT NOT NULL, done TEXT NOT NULL DEFAULT '');
            CREATE INDEX IF NOT EXISTS trades_open ON trades(status, recipient, sender);
            CREATE TABLE IF NOT EXISTS daily (
                user_id INTEGER NOT NULL, day TEXT NOT NULL, progress TEXT NOT NULL DEFAULT '{}',
                claimed TEXT NOT NULL DEFAULT '[]', PRIMARY KEY (user_id, day));
        """)
        # Profile, points and rank columns (added in 2.0): add them to the users table if it's older.
        have = {r[1] for r in self.db.execute("PRAGMA table_info(users)")}
        for column, decl in (("points", "INTEGER NOT NULL DEFAULT 0"), ("bio", "TEXT NOT NULL DEFAULT ''"),
                             ("avatar", "TEXT NOT NULL DEFAULT ''"), ("skin", "TEXT NOT NULL DEFAULT ''"),
                             ("rp", "INTEGER NOT NULL DEFAULT 0"), ("wins", "INTEGER NOT NULL DEFAULT 0"),
                             ("losses", "INTEGER NOT NULL DEFAULT 0"), ("draws", "INTEGER NOT NULL DEFAULT 0"),
                             # daily login rewards (3.2): the last day claimed and the streak of days in a row
                             ("login_day", "TEXT NOT NULL DEFAULT ''"), ("login_streak", "INTEGER NOT NULL DEFAULT 0")):
            if column not in have:
                self.db.execute(f"ALTER TABLE users ADD COLUMN {column} {decl}")
        # The highest rank each player has reached, so rank-up rewards pay once (added in 2.6).
        new_best_rank = "best_rank" not in have
        if new_best_rank:
            self.db.execute("ALTER TABLE users ADD COLUMN best_rank INTEGER NOT NULL DEFAULT 0")
        # The battle pass's old daily XP cap (2.6 development; no longer used).
        have = {r[1] for r in self.db.execute("PRAGMA table_info(battlepass)")}
        for column, decl in (("day", "TEXT NOT NULL DEFAULT ''"), ("day_xp", "INTEGER NOT NULL DEFAULT 0")):
            if column not in have:
                self.db.execute(f"ALTER TABLE battlepass ADD COLUMN {column} {decl}")
        # Copies of items: you can own an item more than once (added in 2.6).
        if "qty" not in {r[1] for r in self.db.execute("PRAGMA table_info(inventory)")}:
            self.db.execute("ALTER TABLE inventory ADD COLUMN qty INTEGER NOT NULL DEFAULT 1")
        self.db.commit()  # one write for all of it
        if new_best_rank:  # pay the rewards for ranks players had already reached
            for row in self.db.execute("SELECT id FROM users WHERE rp > 0").fetchall():
                self.rank_up(row["id"])

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
            out["counts"] = self.counts(row["id"])
            out["best_rank"] = cos.RANKS[row["best_rank"]][1]
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
        """Every item a player owns (once each, however many copies)."""
        return [r[0] for r in self.db.execute("SELECT item FROM inventory WHERE user_id = ? ORDER BY created",
                                              (user_id,))]

    def counts(self, user_id: int) -> dict[str, int]:
        """How many copies of each item a player owns."""
        return dict(self.db.execute("SELECT item, qty FROM inventory WHERE user_id = ?", (user_id,)).fetchall())

    def copies(self, user_id: int, item: str) -> int:
        row = self.db.execute("SELECT qty FROM inventory WHERE user_id = ? AND item = ?", (user_id, item)).fetchone()
        return row[0] if row else 0

    def grant(self, user_id: int, item: str, commit: bool = True) -> bool:
        """Give a copy of an item; False if they already had one."""
        new = self.copies(user_id, item) == 0
        self.db.execute("INSERT INTO inventory (user_id, item, created, qty) VALUES (?, ?, ?, 1) "
                        "ON CONFLICT(user_id, item) DO UPDATE SET qty = qty + 1", (user_id, item, now_iso()))
        if commit:
            self.db.commit()
        return new

    def take(self, user_id: int, item: str) -> None:
        """Take one copy of an item away (into a market listing); unequips a skin when the last copy goes."""
        have = self.copies(user_id, item)
        if have <= 0:
            raise ValueError("You don't own that.")
        if have == 1:
            self.db.execute("DELETE FROM inventory WHERE user_id = ? AND item = ?", (user_id, item))
            kind, _, key = item.partition(":")
            if kind == "skin":
                self.db.execute("UPDATE users SET skin = '' WHERE id = ? AND skin = ?", (user_id, key))
        else:
            self.db.execute("UPDATE inventory SET qty = qty - 1 WHERE user_id = ? AND item = ?", (user_id, item))

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
        """Grant a copy of an item (a duplicate is another copy, to keep or sell on the market)."""
        new = self.grant(user_id, item)
        # ("refund" stays for older games, which show it for duplicates)
        return {"item": item, "new": new, "refund": 0, "copies": self.copies(user_id, item),
                "points": self.points(user_id)}

    # -- the player market

    def market(self, query: str = "", rarity: str = "", sort: str = "cheap", limit: int = 60) -> list[dict]:
        """Listings for sale, searched by item name and filtered by rarity."""
        order = {"cheap": "price, listings.id", "pricey": "price DESC, listings.id",
                 "new": "listings.id DESC"}.get(sort, "price, listings.id")
        rows = self.db.execute(f"SELECT listings.*, users.name AS seller_name FROM listings "
                               f"JOIN users ON users.id = listings.seller ORDER BY {order}").fetchall()
        words = query.lower().split()
        out = []
        for r in rows:
            name = cos.item_name(r["item"])
            if rarity and cos.item_rarity(r["item"]) != rarity:
                continue
            if not all(w in f"{name} {r['seller_name']}".lower() for w in words):
                continue
            out.append(self.listing(r, name))
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def listing(r: sqlite3.Row, name: str | None = None) -> dict:
        return {"id": r["id"], "item": r["item"], "name": name or cos.item_name(r["item"]),
                "rarity": cos.item_rarity(r["item"]), "price": r["price"], "seller": r["seller_name"],
                "created": r["created"]}

    def my_listings(self, user_id: int) -> list[dict]:
        rows = self.db.execute("SELECT listings.*, users.name AS seller_name FROM listings "
                               "JOIN users ON users.id = listings.seller WHERE seller = ? ORDER BY listings.id DESC",
                               (user_id,)).fetchall()
        return [self.listing(r) for r in rows]

    def list_item(self, user_id: int, item: str, price) -> dict:
        """Put one copy of an item up for sale (it's held by the market until it sells or you cancel)."""
        if cos.item_rarity(item) is None:
            raise ValueError("Unknown item.")
        if item in cos.UNTRADEABLE:
            raise ValueError("Ranked skins can't be sold.")
        try:
            price = int(price)
        except (TypeError, ValueError):
            raise ValueError("Enter a price.") from None
        if not cos.MARKET_MIN_PRICE <= price <= cos.MARKET_MAX_PRICE:
            raise ValueError(f"Prices go from {cos.MARKET_MIN_PRICE:,} to {cos.MARKET_MAX_PRICE:,} snake points.")
        if self.db.execute("SELECT COUNT(*) FROM listings WHERE seller = ?", (user_id,)).fetchone()[0] \
                >= cos.MARKET_MAX_LISTINGS:
            raise ValueError(f"You can have {cos.MARKET_MAX_LISTINGS} things for sale at once.")
        with self.db:
            self.take(user_id, item)
            cur = self.db.execute("INSERT INTO listings (seller, item, price, created) VALUES (?, ?, ?, ?)",
                                  (user_id, item, price, now_iso()))
        return {"id": cur.lastrowid, "copies": self.copies(user_id, item)}

    def cancel_listing(self, user_id: int, listing_id) -> str:
        row = self.db.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
        if not row or row["seller"] != user_id:
            raise ValueError("That isn't one of your listings.")
        with self.db:
            self.db.execute("DELETE FROM listings WHERE id = ?", (listing_id,))
            self.grant(user_id, row["item"], commit=False)
        return row["item"]

    def buy_listing(self, user_id: int, listing_id) -> dict:
        """Buy a listing: the price goes to the seller (less the market fee) and the item to you."""
        row = self.db.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
        if not row:
            raise ValueError("That's already sold (or was taken off the market).")
        if row["seller"] == user_id:
            raise ValueError("That's your own listing: cancel it to get it back.")
        price, item = row["price"], row["item"]
        if self.points(user_id) < price:
            raise ValueError("Not enough snake points.")
        name = cos.item_name(item)
        fee = cos.market_fee(price)
        with self.db:
            self.db.execute("DELETE FROM listings WHERE id = ?", (listing_id,))
            self.db.execute("UPDATE users SET points = points - ? WHERE id = ?", (price, user_id))
            self.db.execute("UPDATE users SET points = points + ? WHERE id = ?", (price - fee, row["seller"]))
            self.db.execute("INSERT INTO ledger (user_id, amount, reason, created) VALUES (?, ?, ?, ?), "
                            "(?, ?, ?, ?)", (user_id, -price, f"market: bought {item}", now_iso(),
                                             row["seller"], price - fee, f"market: sold {item}", now_iso()))
            self.grant(user_id, item, commit=False)
        return {"item": item, "name": name, "price": price, "seller_id": row["seller"], "fee": fee,
                "points": self.points(user_id), "copies": self.copies(user_id, item)}

    # -- the battle pass

    def current_week(self) -> str:
        """This week's name, with the restart suffix if the site restarted it ("2026-W46r1")."""
        week = week_id()
        row = self.db.execute("SELECT n FROM week_resets WHERE week = ?", (week,)).fetchone()
        return f"{week}r{row['n']}" if row else week

    def restart_week(self) -> str:
        """Start this week over: new weekly speedruns and a fresh battle pass until Monday.

        Everyone's pass levels start again from 0; anyone who'd bought the pass keeps it."""
        old = self.current_week()
        week = week_id()
        self.db.execute("INSERT INTO week_resets VALUES (?, 1) ON CONFLICT(week) DO UPDATE SET n = n + 1", (week,))
        new = self.current_week()
        self.db.execute("INSERT INTO battlepass (user_id, week, xp, owned) SELECT user_id, ?, 0, owned "
                        "FROM battlepass WHERE week = ? AND owned = 1", (new, old))
        self.db.commit()
        return new

    def pass_row(self, user_id: int, week: str | None = None) -> sqlite3.Row:
        """A player's pass for a week, started (with any levels past 100 from last week) if new."""
        week = week or self.current_week()
        row = self.db.execute("SELECT * FROM battlepass WHERE user_id = ? AND week = ?", (user_id, week)).fetchone()
        if row:
            return row
        # A new calendar week carries over levels past 100; a restarted week starts from 0.
        last = None if "r" in week else self.db.execute(
            "SELECT xp FROM battlepass WHERE user_id = ? AND week = ?", (user_id, previous_week(week))).fetchone()
        carry = max(0, last["xp"] - cos.PASS_LEVELS * cos.LEVEL_XP) if last else 0
        self.db.execute("INSERT OR IGNORE INTO battlepass (user_id, week, xp) VALUES (?, ?, ?)", (user_id, week, carry))
        self.db.commit()
        return self.pass_row(user_id, week)

    def add_xp(self, user_id: int, xp: int) -> int:
        """Add battle pass XP; returns what was added."""
        if xp <= 0:
            return 0
        row = self.pass_row(user_id)
        self.db.execute("UPDATE battlepass SET xp = xp + ? WHERE user_id = ? AND week = ?", (xp, user_id, row["week"]))
        self.db.commit()
        return xp

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
        """Points (and, in ranked matches against other people, rank points) for a finished versus match."""
        delta = {"win": cos.RP_WIN, "loss": cos.RP_LOSS, "draw": cos.RP_DRAW}[result] if ranked else 0
        column = {"win": "wins", "loss": "losses", "draw": "draws"}[result]
        if ranked:
            self.db.execute(f"UPDATE users SET rp = MAX(0, rp + ?), {column} = {column} + 1 WHERE id = ?",
                            (delta, user_id))
        self.add_points(user_id, points, f"versus {result}")
        rank_ups = self.rank_up(user_id)
        rp = self.user_by_id(user_id)["rp"]
        return {"points": points, "balance": self.points(user_id), "rp": rp, "rp_change": delta,
                "rank": cos.rank_for(rp)[1], "rank_ups": rank_ups}

    def rank_up(self, user_id: int, rng=random) -> list[dict]:
        """Rewards for every rank reached for the first time: [{"rank", "rewards": [names]}].

        Each rank pays once: dropping down and climbing back up again pays nothing."""
        row = self.user_by_id(user_id)
        index = cos.rank_for(row["rp"])[0]
        best = row["best_rank"]
        if index <= best:
            return []
        self.db.execute("UPDATE users SET best_rank = ? WHERE id = ?", (index, user_id))
        self.db.commit()
        out = []
        for reached in range(best + 1, index + 1):
            name = cos.RANKS[reached][1]
            got = []
            for kind, value in cos.RANK_REWARDS.get(reached, []):
                if kind == "points":
                    self.add_points(user_id, value, f"reached {name}")
                    got.append(f"{value:,} snake points")
                elif kind == "crate":
                    res = self.open_crate(user_id, value, rng, free=True)
                    got.append(f"{cos.CRATE_BY_ID[value].name}: {cos.item_name(res['item'])}")
                else:
                    self.grant(user_id, value)
                    got.append(cos.item_name(value))
            out.append({"rank": name, "rewards": got})
        return out

    # -- daily login rewards

    def login_reward_info(self, user_id: int, day: str | None = None) -> dict:
        """Today's login reward: the day of the streak it would be, what each day gives, and
        whether it's been claimed. Missing a day starts the streak again."""
        day = day or self.today()
        row = self.user_by_id(user_id)
        yesterday = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        claimed = row["login_day"] == day
        if claimed:
            streak = row["login_streak"]
        else:
            streak = row["login_streak"] + 1 if row["login_day"] == yesterday else 1
        step = (streak - 1) % len(cos.LOGIN_REWARDS)
        return {"ready": not claimed, "streak": streak, "step": step,
                "rewards": [cos.login_reward_name(r) for r in cos.LOGIN_REWARDS],
                "milestones": [{"day": d, "reward": cos.login_reward_name(cos.LOGIN_REWARDS[d - 1])}
                               for d in cos.LOGIN_MILESTONES]}

    def claim_login_reward(self, user_id: int, rng=random, day: str | None = None) -> dict:
        day = day or self.today()
        info = self.login_reward_info(user_id, day)
        if not info["ready"]:
            raise ValueError("You've had today's reward: come back tomorrow.")
        self.db.execute("UPDATE users SET login_day = ?, login_streak = ? WHERE id = ?", (day, info["streak"], user_id))
        self.db.commit()
        rewards = cos.LOGIN_REWARDS[info["step"]]
        opened = []
        for kind, value in rewards:
            if kind == "points":
                self.add_points(user_id, value, f"login reward, day {info['streak']}")
            else:
                opened.append({**self.open_crate(user_id, value, rng, free=True), "crate": value})
        out = {"reward": cos.login_reward_name(rewards), "kind": "crate" if opened else "points",
               "opened": opened, **self.login_reward_info(user_id, day), "points": self.points(user_id)}
        if opened:  # (the first loot box's item at the top level too, as before)
            out.update({k: opened[0][k] for k in ("item", "new", "copies", "crate")})
        return out

    # -- the jackpot

    def jackpot_round(self, now: datetime | None = None) -> sqlite3.Row:
        """The pot taking entries now (a new one once the last is drawn)."""
        row = self.db.execute("SELECT * FROM jackpot_rounds WHERE status = 'open' ORDER BY id LIMIT 1").fetchone()
        if row:
            return row
        now = now or datetime.now(timezone.utc)
        self.db.execute("INSERT INTO jackpot_rounds (created) VALUES (?)", (now.strftime("%Y-%m-%dT%H:%M:%SZ"),))
        self.db.commit()
        return self.jackpot_round()

    def _jackpot_players(self, round_id: int) -> list[dict]:
        """Who's in a pot, in the order they joined: name, avatar, items, value."""
        players: dict[int, dict] = {}
        for e in self.db.execute("SELECT jackpot_entries.*, users.name, users.avatar FROM jackpot_entries JOIN users "
                                 "ON users.id = jackpot_entries.user_id WHERE round = ? ORDER BY jackpot_entries.id",
                                 (round_id,)).fetchall():
            p = players.setdefault(e["user_id"], {"user_id": e["user_id"], "name": e["name"],
                                                  "avatar": e["avatar"] or cos.DEFAULT_AVATAR, "items": [], "value": 0})
            p["items"].append(e["item"])
            p["value"] += e["value"]
        return list(players.values())

    def jackpot_enter(self, user_id: int, items, now: datetime | None = None) -> None:
        """Put items into the pot (they're held until the draw)."""
        now = now or datetime.now(timezone.utc)
        if not isinstance(items, list) or not 1 <= len(items) <= cos.JACKPOT_MAX_ITEMS:
            raise ValueError(f"Put in 1 to {cos.JACKPOT_MAX_ITEMS} skins or packs.")
        items = [str(i) for i in items]
        for it in items:
            if cos.item_rarity(it) is None:
                raise ValueError("Unknown item.")
            if it in cos.UNTRADEABLE:
                raise ValueError("Ranked skins can't go in the jackpot.")
        rnd = self.jackpot_round(now)
        if rnd["ends"] and _parse_iso(rnd["ends"]) <= now:
            raise ValueError("The draw's happening: get in the next one.")
        players = self._jackpot_players(rnd["id"])
        mine = next((p for p in players if p["user_id"] == user_id), None)
        if not mine and len(players) >= cos.JACKPOT_MAX_PLAYERS:
            raise ValueError(f"This pot is full ({cos.JACKPOT_MAX_PLAYERS} players): get in the next one.")
        if mine and len(mine["items"]) + len(items) > cos.JACKPOT_MAX_ITEMS:
            raise ValueError(f"You can put {cos.JACKPOT_MAX_ITEMS} items in one pot.")
        if not self._has(user_id, items, 0):
            raise ValueError("You don't have everything you picked.")
        stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.db:
            for it in items:
                self.take(user_id, it)
                self.db.execute("INSERT INTO jackpot_entries (round, user_id, item, value, created) VALUES (?, ?, ?, ?, ?)",
                                (rnd["id"], user_id, it, cos.item_value(it), stamp))
            joined = len({p["user_id"] for p in players} | {user_id})
            if joined >= 2 and not rnd["ends"]:  # a second player: the countdown starts
                ends = (now + timedelta(seconds=cos.JACKPOT_COUNTDOWN)).strftime("%Y-%m-%dT%H:%M:%SZ")
                self.db.execute("UPDATE jackpot_rounds SET ends = ? WHERE id = ?", (ends, rnd["id"]))

    def jackpot_tick(self, now: datetime | None = None, rng=None) -> dict | None:
        """Draw the pot once its countdown is over (or give a lone player's items back after a day).
        Returns what happened, or None."""
        now = now or datetime.now(timezone.utc)
        rnd = self.db.execute("SELECT * FROM jackpot_rounds WHERE status = 'open' ORDER BY id LIMIT 1").fetchone()
        if not rnd:
            return None
        players = self._jackpot_players(rnd["id"])
        stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        if not rnd["ends"]:
            if len(players) == 1 and now - _parse_iso(rnd["created"]) > timedelta(hours=cos.JACKPOT_LONE_HOURS):
                with self.db:
                    for it in players[0]["items"]:
                        self.grant(players[0]["user_id"], it, commit=False)
                    self.db.execute("UPDATE jackpot_rounds SET status = 'refunded', done = ? WHERE id = ?", (stamp, rnd["id"]))
                return {"round": rnd["id"], "refunded": players[0]["user_id"]}
            return None
        if _parse_iso(rnd["ends"]) > now:
            return None
        total = sum(p["value"] for p in players)
        rng = rng or secrets.SystemRandom()
        ticket = rng.random() * total  # (a bigger share of the pot, a bigger slice of the tickets)
        winner, upto = players[-1], 0
        for p in players:
            upto += p["value"]
            if ticket < upto:
                winner = p
                break
        with self.db:
            for p in players:
                for it in p["items"]:
                    self.grant(winner["user_id"], it, commit=False)
            self.db.execute("UPDATE jackpot_rounds SET status = 'done', winner = ?, total = ?, done = ? WHERE id = ?",
                            (winner["user_id"], total, stamp, rnd["id"]))
        return {"round": rnd["id"], "winner": winner["user_id"], "winner_name": winner["name"], "total": total,
                "players": [p["user_id"] for p in players]}

    def _jackpot_view(self, round_id: int) -> dict:
        players = self._jackpot_players(round_id)
        total = sum(p["value"] for p in players)
        return {"total": total, "players": [
            {"name": p["name"], "avatar": p["avatar"], "items": p["items"], "value": p["value"],
             "chance": round(100 * p["value"] / total, 1) if total else 0} for p in players]}

    def jackpot_state(self, now: datetime | None = None) -> dict:
        """The pot now (who's in, with what, their chances and the countdown), the last draw and
        recent winners."""
        now = now or datetime.now(timezone.utc)
        rnd = self.jackpot_round(now)
        left = max(0, int((_parse_iso(rnd["ends"]) - now).total_seconds() + 0.999)) if rnd["ends"] else None
        out = {"round": rnd["id"], "seconds_left": left, "countdown": cos.JACKPOT_COUNTDOWN,
               **self._jackpot_view(rnd["id"]), "last": None, "history": []}
        done = self.db.execute("SELECT jackpot_rounds.*, users.name AS winner_name FROM jackpot_rounds JOIN users "
                               "ON users.id = jackpot_rounds.winner WHERE status = 'done' ORDER BY id DESC LIMIT 6").fetchall()
        if done:
            out["last"] = {"round": done[0]["id"], "winner": done[0]["winner_name"], **self._jackpot_view(done[0]["id"])}
            out["history"] = [{"round": d["id"], "winner": d["winner_name"], "total": d["total"],
                               "players": len(self._jackpot_players(d["id"]))} for d in done]
        return out

    # -- trading items with other players

    def tradeable_counts(self, user_id: int) -> dict[str, int]:
        """What a player has that they could trade: copies not on the market, ranked skins aside."""
        return {it: n for it, n in self.counts(user_id).items() if n > 0 and it not in cos.UNTRADEABLE}

    @staticmethod
    def _item_list(items) -> list[str]:
        if not isinstance(items, list) or len(items) > cos.TRADE_MAX_ITEMS:
            raise ValueError(f"A trade can have up to {cos.TRADE_MAX_ITEMS} items on each side.")
        items = [str(i) for i in items]
        for it in items:
            if cos.item_rarity(it) is None:
                raise ValueError("Unknown item.")
            if it in cos.UNTRADEABLE:
                raise ValueError("Ranked skins can't be traded.")
        return items

    @staticmethod
    def _points(n) -> int:
        try:
            n = int(n or 0)
        except (TypeError, ValueError):
            raise ValueError("Points must be a number.") from None
        if not 0 <= n <= cos.MARKET_MAX_PRICE:
            raise ValueError(f"Points in a trade go from 0 to {cos.MARKET_MAX_PRICE:,}.")
        return n

    def _has(self, user_id: int, items: list[str], points: int) -> bool:
        have = self.counts(user_id)
        need: dict[str, int] = {}
        for it in items:
            need[it] = need.get(it, 0) + 1
        return all(have.get(it, 0) >= n for it, n in need.items()) and self.points(user_id) >= points

    def offer_trade(self, sender: int, recipient_name: str, give, give_points, want, want_points) -> int:
        """Offer a trade: these of mine (and points) for those of theirs (and points)."""
        other = self.user_row(recipient_name)
        if not other:
            raise LookupError("No player with that name.")
        if other["id"] == sender:
            raise ValueError("That's you!")
        give, want = self._item_list(give), self._item_list(want)
        give_points, want_points = self._points(give_points), self._points(want_points)
        if not (give or give_points) or not (want or want_points):
            raise ValueError("Put something on both sides of the trade.")
        if not self._has(sender, give, give_points):
            raise ValueError("You don't have everything you're offering.")
        if not self._has(other["id"], want, want_points):
            raise ValueError(f"{other['name']} doesn't have everything you're asking for.")
        if self.db.execute("SELECT COUNT(*) FROM trades WHERE sender = ? AND status = 'open'",
                           (sender,)).fetchone()[0] >= cos.TRADE_MAX_OPEN:
            raise ValueError(f"You can have {cos.TRADE_MAX_OPEN} trade offers out at once.")
        cur = self.db.execute("INSERT INTO trades (sender, recipient, give, give_points, want, want_points, created) "
                              "VALUES (?, ?, ?, ?, ?, ?, ?)", (sender, other["id"], json.dumps(give), give_points,
                                                               json.dumps(want), want_points, now_iso()))
        self.db.commit()
        return cur.lastrowid

    def trade(self, trade_id) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()

    def answer_trade(self, user_id: int, trade_id, action: str) -> sqlite3.Row:
        """Accept or decline a trade offered to you, or cancel one you offered."""
        t = self.trade(trade_id)
        if not t or t["status"] != "open":
            raise LookupError("That trade isn't open any more.")
        if action == "cancel":
            if t["sender"] != user_id:
                raise PermissionError("Only the player who offered it can cancel it.")
        elif t["recipient"] != user_id:
            raise PermissionError("That trade wasn't offered to you.")
        if action == "accept":
            give, want = json.loads(t["give"]), json.loads(t["want"])
            if not self._has(t["sender"], give, t["give_points"]):
                raise ValueError("They don't have everything they offered any more.")
            if not self._has(t["recipient"], want, t["want_points"]):
                raise ValueError("You don't have everything they asked for any more.")
            stamp = now_iso()
            with self.db:  # all or nothing
                for it in give:
                    self.take(t["sender"], it)
                    self.grant(t["recipient"], it, commit=False)
                for it in want:
                    self.take(t["recipient"], it)
                    self.grant(t["sender"], it, commit=False)
                for frm, to, n in ((t["sender"], t["recipient"], t["give_points"]),
                                   (t["recipient"], t["sender"], t["want_points"])):
                    if n:
                        self.db.execute("UPDATE users SET points = points - ? WHERE id = ?", (n, frm))
                        self.db.execute("UPDATE users SET points = points + ? WHERE id = ?", (n, to))
                        self.db.execute("INSERT INTO ledger (user_id, amount, reason, created) VALUES (?, ?, ?, ?), "
                                        "(?, ?, ?, ?)", (frm, -n, f"trade: #{t['id']}", stamp, to, n, f"trade: #{t['id']}", stamp))
                self.db.execute("UPDATE trades SET status = 'accepted', done = ? WHERE id = ?", (stamp, t["id"]))
        else:
            self.db.execute("UPDATE trades SET status = ?, done = ? WHERE id = ?",
                            ("declined" if action == "decline" else "cancelled", now_iso(), t["id"]))
            self.db.commit()
        return self.trade(t["id"])

    def trade_view(self, t: sqlite3.Row) -> dict:
        names = {r["id"]: r["name"] for r in self.db.execute("SELECT id, name FROM users WHERE id IN (?, ?)",
                                                              (t["sender"], t["recipient"]))}
        return {"id": t["id"], "from": names.get(t["sender"]), "to": names.get(t["recipient"]),
                "give": json.loads(t["give"]), "give_points": t["give_points"],
                "want": json.loads(t["want"]), "want_points": t["want_points"],
                "status": t["status"], "created": t["created"], "done": t["done"]}

    def trades_for(self, user_id: int) -> dict:
        rows = self.db.execute("SELECT * FROM trades WHERE (sender = ? OR recipient = ?) AND status = 'open' "
                               "ORDER BY id DESC", (user_id, user_id)).fetchall()
        done = self.db.execute("SELECT * FROM trades WHERE (sender = ? OR recipient = ?) AND status != 'open' "
                               "ORDER BY id DESC LIMIT 10", (user_id, user_id)).fetchall()
        return {"incoming": [self.trade_view(t) for t in rows if t["recipient"] == user_id],
                "outgoing": [self.trade_view(t) for t in rows if t["sender"] == user_id],
                "history": [self.trade_view(t) for t in done]}

    def best_run(self, category: str) -> sqlite3.Row | None:
        """The world record run of a category (its whole run file), with who set it."""
        return self.db.execute("SELECT runs.run, runs.time_ms, runs.created, users.name FROM runs JOIN users "
                               "ON users.id = runs.user_id WHERE runs.category = ? ORDER BY runs.time_ms, "
                               "runs.created LIMIT 1", (category,)).fetchone()

    # -- daily challenges

    @staticmethod
    def today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def daily_row(self, user_id: int, day: str) -> sqlite3.Row:
        self.db.execute("INSERT OR IGNORE INTO daily (user_id, day) VALUES (?, ?)", (user_id, day))
        return self.db.execute("SELECT * FROM daily WHERE user_id = ? AND day = ?", (user_id, day)).fetchone()

    def progress(self, user_id: int, kind: str, amount: int = 1, day: str | None = None) -> None:
        """Count something towards today's challenges (fruit eaten, matches won, ...)."""
        day = day or self.today()
        if amount <= 0 or not any(c["kind"] == kind for c in cos.daily_challenges(day)):
            return
        row = self.daily_row(user_id, day)
        progress = json.loads(row["progress"])
        progress[kind] = progress.get(kind, 0) + amount
        self.db.execute("UPDATE daily SET progress = ? WHERE user_id = ? AND day = ?",
                        (json.dumps(progress), user_id, day))
        self.db.commit()

    def daily_info(self, user_id: int, day: str | None = None) -> dict:
        day = day or self.today()
        row = self.daily_row(user_id, day)
        self.db.commit()
        progress, claimed = json.loads(row["progress"]), set(json.loads(row["claimed"]))
        challenges = [{**c, "progress": min(c["goal"], progress.get(c["kind"], 0)),
                       "done": progress.get(c["kind"], 0) >= c["goal"], "claimed": c["id"] in claimed}
                      for c in cos.daily_challenges(day)]
        tomorrow = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
        left = max(0, int((tomorrow - datetime.now(timezone.utc)).total_seconds()))
        return {"day": day, "challenges": challenges, "bonus": cos.DAILY_BONUS,
                "bonus_ready": all(c["done"] for c in challenges), "bonus_claimed": "bonus" in claimed,
                "left": f"{left // 3600}h {left % 3600 // 60}m"}

    def claim_daily(self, user_id: int, which, day: str | None = None) -> int:
        """Claim a finished challenge's reward (0, 1, 2) or the bonus for all three ("bonus")."""
        day = day or self.today()
        if which != "bonus" and (isinstance(which, bool) or not isinstance(which, int)):
            raise ValueError("Unknown challenge.")
        info = self.daily_info(user_id, day)
        if which == "bonus":
            if not info["bonus_ready"]:
                raise ValueError("Finish all three challenges first.")
            amount, reason = cos.DAILY_BONUS, "daily challenges: all three"
        else:
            ch = next((c for c in info["challenges"] if c["id"] == which), None)
            if not ch:
                raise ValueError("Unknown challenge.")
            if not ch["done"]:
                raise ValueError("Finish the challenge first.")
            amount, reason = ch["reward"], f"daily challenge: {ch['text']}"
        row = self.daily_row(user_id, day)
        claimed = json.loads(row["claimed"])
        if which in claimed:
            raise ValueError("You've already claimed that.")
        claimed.append(which)
        self.db.execute("UPDATE daily SET claimed = ? WHERE user_id = ? AND day = ?", (json.dumps(claimed), user_id, day))
        return self.add_points(user_id, amount, reason)

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
        # (selling on the market only moves points between players, so it isn't earning)
        earned = dict(self.db.execute("SELECT user_id, SUM(amount) FROM ledger WHERE amount > 0 "
                                      "AND reason NOT LIKE 'duplicate%' AND reason NOT LIKE 'market:%' AND reason NOT LIKE 'trade:%' "
                                      "GROUP BY user_id").fetchall())
        # (skins don't count towards the score; the count is still sent for games from before 2.6)
        skins = dict(self.db.execute("SELECT user_id, COUNT(*) FROM inventory WHERE item LIKE 'skin:%' "
                                     "GROUP BY user_id").fetchall())
        out = []
        for row in self.db.execute("SELECT id, name, avatar, rp FROM users").fetchall():
            stats = {"wrs": wrs.get(row["name"].lower(), 0), "prs": prs.get(row["id"], 0),
                     "earned": earned.get(row["id"], 0) or 0}
            result = cos.player_score(stats["wrs"], stats["prs"], len(builtin), stats["earned"])
            if result["score"] <= 0:
                continue
            out.append({"name": row["name"], "avatar": row["avatar"] or cos.DEFAULT_AVATAR,
                        "rank": cos.rank_for(row["rp"])[1], **stats, "skins": skins.get(row["id"], 0), **result})
        out.sort(key=lambda p: (-p["score"], p["name"].lower()))
        for place, p in enumerate(out, 1):
            p["place"] = place
        return out

    # -- community categories

    def share_category(self, definition: dict, user_id: int) -> tuple[str, bool]:
        """Add a custom category to the community list (the first to share it is its creator).

        Returns (its id, whether it's new: the same rules shared before are the same category)."""
        cat = category_from_def(definition)
        if any(m not in BUILTIN_MODE_IDS for m in cat.modes):
            raise ValueError("Categories using mods can't be shared.")
        if self.db.execute("SELECT 1 FROM categories WHERE id = ?", (cat.id,)).fetchone():
            return cat.id, False
        if self.db.execute("SELECT COUNT(*) FROM categories WHERE creator = ?", (user_id,)).fetchone()[0] \
                >= MAX_CATEGORIES_EACH:
            raise ValueError(f"You've made {MAX_CATEGORIES_EACH} community categories, the most anyone can.")
        clean = category_def(cat)  # (the rules as the category has them)
        clean["name"] = clean_text(clean["name"], MAX_CATEGORY_NAME) or "Custom"
        self.db.execute("INSERT INTO categories VALUES (?, ?, ?, ?, ?)",
                        (cat.id, json.dumps(clean), clean["name"], user_id, now_iso()))
        self.db.commit()
        return cat.id, True

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

    def community(self, query: str = "", limit: int = 100, sort: str = "top", me: int | None = None) -> list[dict]:
        """Community categories, searched by name, creator or mode, sorted by upvotes
        ("top"), players ("popular") or newest first ("new")."""
        rows = self.db.execute("""
            SELECT categories.*, users.name AS creator_name,
                   (SELECT COUNT(DISTINCT user_id) FROM runs WHERE runs.category = categories.id) AS players,
                   (SELECT COUNT(*) FROM category_votes v WHERE v.category = categories.id) AS votes,
                   EXISTS (SELECT 1 FROM category_votes v WHERE v.category = categories.id AND v.user_id = ?) AS voted
            FROM categories JOIN users ON users.id = categories.creator""", (me or -1,)).fetchall()
        words = query.lower().split()
        out = []
        for r in rows:
            definition = json.loads(r["def"])
            modes = " ".join(str(m) for m in definition.get("modes", []))
            text = f"{r['name']} {r['creator_name']} {modes}".lower()
            if not all(w in text for w in words):
                continue
            out.append({"id": r["id"], "name": r["name"], "def": definition, "creator": r["creator_name"],
                        "created": r["created"][:10], "players": r["players"], "votes": r["votes"],
                        "voted": bool(r["voted"]), "mine": r["creator"] == me, "_created": r["created"]})
        keys = {"popular": lambda c: (-c["players"], -c["votes"], c["name"].lower()),
                "new": lambda c: (c["_created"],)}
        if sort == "new":
            out.sort(key=keys["new"], reverse=True)
        else:
            out.sort(key=keys.get(sort, lambda c: (-c["votes"], -c["players"], c["name"].lower())))
        out = out[:limit]
        for c in out:
            del c["_created"]
            best = self.leaderboard(c["id"], 1)
            c["wr"] = best[0] if best else None
        return out

    def vote_category(self, category_id: str, user_id: int, up: bool) -> dict:
        """Upvote a community category (or take the upvote back): one vote per player."""
        row = self.db.execute("SELECT creator FROM categories WHERE id = ?", (category_id,)).fetchone()
        if not row:
            raise LookupError("No community category with that id.")
        if row["creator"] == user_id:
            raise ValueError("You can't upvote your own category.")
        if up:
            self.db.execute("INSERT OR IGNORE INTO category_votes VALUES (?, ?, ?)", (category_id, user_id, now_iso()))
        else:
            self.db.execute("DELETE FROM category_votes WHERE category = ? AND user_id = ?", (category_id, user_id))
        self.db.commit()
        votes = self.db.execute("SELECT COUNT(*) FROM category_votes WHERE category = ?", (category_id,)).fetchone()[0]
        return {"id": category_id, "votes": votes, "voted": up}


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
        self.ranked = True   # ranked matches against other people change rank points

    def info(self) -> dict:
        return {"t": "room", "code": self.code, "host": self.host.id, "state": self.state,
                "name": self.name, "public": self.public, "ranked": self.ranked, "settings": self.settings,
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
        if isinstance(m.get("ranked"), bool) and self.state == "lobby":
            self.ranked = m["ranked"]

    @property
    def open(self) -> bool:
        return self.state == "lobby" and len(self.players) < 2 * MAX_TEAM

    def listing(self) -> dict:
        """What the public match search shows about this match."""
        s = self.settings
        return {"code": self.code, "name": self.name, "host": self.host.name, "players": len(self.players),
                "max": 2 * MAX_TEAM, "size": s["size"], "speed": s["speed"], "goal": s["goal"],
                "modes": s["modes"], "ranked": self.ranked}

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
        """Snake points for everyone with an account, and rank points in ranked matches against other people."""
        ranked = self.ranked and len(self.humans) >= 2
        for p in self.players:
            if p.user_id is None or not (0 <= p.snake < len(g.snakes)):
                continue
            result = "draw" if g.winner is None else ("win" if g.winner == p.team else "loss")
            points = cos.MATCH_PLAYED + cos.MATCH_PER_FRUIT * g.snakes[p.snake].score + \
                (cos.MATCH_WIN if result == "win" else 0)
            db = self.server.db
            info = db.record_match(p.user_id, result, ranked, points)
            db.add_xp(p.user_id, points)
            db.progress(p.user_id, "matches")
            # (wins count against people, or bots that aren't on easy)
            if result == "win" and (len(self.humans) >= 2 or any(q.bot and q.bot != "easy" for q in self.players
                                                                   if q.team != p.team)):
                db.progress(p.user_id, "wins")
            p.rank = info["rank"]
            await self.send(p, {"t": "reward", "result": result, "ranked": ranked, **info})

    async def send(self, p: Player, msg: dict) -> None:
        if p.ws is not None and not p.ws.closed:
            await p.ws.send_str(json.dumps(msg, separators=(",", ":")))


# ---- the server ---------------------------------------------------------------------

class Server:
    def __init__(self, data_dir: Path, clients_dir: Path | None = None, default_client: str | None = None):
        self.db = Database(data_dir / "opensnake.db")
        # The web clients this site serves (name -> folder): any game that speaks the
        # OpenSnake API can be one. The default one is served at /, every one at /<name>/.
        self.clients: dict[str, Path] = {}
        if clients_dir and clients_dir.is_dir():
            for d in sorted(clients_dir.iterdir()):
                if d.is_dir() and CLIENT_NAME.match(d.name) and (d / "index.html").is_file() \
                        and d.name not in ("api", "ws"):
                    self.clients[d.name] = d
        if default_client and default_client not in self.clients:
            raise ValueError(f"No web client called {default_client!r} in {clients_dir}")
        self.default_client = default_client or next(
            (c for c in PREFERRED_CLIENTS if c in self.clients), next(iter(self.clients), None))
        self.rooms: dict[str, Room] = {}
        self.next_pid = 1
        self.connected: dict[int, set[Player]] = {}  # account id -> its open connections (who's online)
        self.last_round: dict[int, float] = {}       # account id -> when its last round was paid
        self.last_message: dict[int, float] = {}     # account id -> when it last sent a message
        self.settle_task: asyncio.Task | None = None
        self.jackpot_task: asyncio.Task | None = None

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
        r.add_post("/api/categories/vote", self.vote_category)
        r.add_get("/api/rankings", self.rankings)
        r.add_get("/api/weekly", self.weekly)
        r.add_get("/api/battlepass", self.battlepass)
        r.add_post("/api/battlepass/buy", self.buy_pass)
        r.add_post("/api/battlepass/claim", self.claim_pass)
        r.add_get("/api/market", self.market)
        r.add_post("/api/market/list", self.market_list)
        r.add_post("/api/market/cancel", self.market_cancel)
        r.add_post("/api/market/buy", self.market_buy)
        r.add_get("/api/daily", self.daily)
        r.add_get("/api/login-reward", self.login_reward)
        r.add_post("/api/login-reward/claim", self.claim_login_reward)
        r.add_get("/api/trades", self.trades)
        r.add_post("/api/trades", self.offer_trade)
        r.add_post("/api/trades/answer", self.answer_trade)
        r.add_get("/api/users/{name}/items", self.user_items)
        r.add_get("/api/replay/{category}", self.replay_run)
        r.add_get("/api/jackpot", self.jackpot)
        r.add_post("/api/jackpot/enter", self.jackpot_enter)
        r.add_post("/api/daily/claim", self.claim_daily)
        r.add_get("/api/messages", self.chats)
        r.add_get("/api/messages/{name}", self.conversation)
        r.add_post("/api/messages", self.send_message)
        r.add_get("/ws", self.websocket)
        # With the Rust version built, it's the main game at / and the Python (pygame)
        # game moves to /py/; without it, the Python game stays at /. (Folders go
        # before "/", which would catch them too.)
        r.add_get("/api/clients", self.list_clients)
        # Every client at /<name>/ (folders go before "/", which would catch them too)...
        for name, folder in self.clients.items():
            r.add_get(f"/{name}", self.to_client_folder)
            r.add_get(f"/{name}/", self.client_index)
            r.add_static(f"/{name}/", folder)
        if "rs" not in self.clients:  # (where the Rust game used to be)
            r.add_get("/rs", self.to_root)
            r.add_get("/rs/", self.to_root)
        # ...and the default one at /.
        if self.default_client:
            r.add_get("/", self.client_index)
            r.add_static("/", self.clients[self.default_client])
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

        async def draw_jackpots():
            while True:
                await asyncio.sleep(1)
                try:
                    result = self.db.jackpot_tick()
                except Exception as e:  # (never let one bad draw stop the loop)
                    print(f"opensnake: jackpot draw failed: {e}", flush=True)
                    continue
                if result and "winner" in result:
                    for uid in result["players"]:
                        await self.notify(uid, {"t": "jackpot", "round": result["round"], "winner": result["winner_name"],
                                                "total": result["total"], "you_won": uid == result["winner"]})
        self.jackpot_task = asyncio.create_task(draw_jackpots())

    async def shutdown(self, app: web.Application) -> None:
        """Stop running matches and close the database (Windows can't delete open files)."""
        if self.settle_task:
            self.settle_task.cancel()
        if self.jackpot_task:
            self.jackpot_task.cancel()
        for room in list(self.rooms.values()):
            if room.task:
                room.task.cancel()
        self.rooms.clear()
        self.db.close()

    # -- web clients
    async def client_index(self, request: web.Request) -> web.StreamResponse:
        name = request.path.strip("/") or self.default_client
        return web.FileResponse(self.clients[name] / "index.html", headers={"Cache-Control": "no-store"})

    @staticmethod
    async def to_root(request: web.Request) -> web.StreamResponse:
        raise web.HTTPFound("/")

    @staticmethod
    async def to_client_folder(request: web.Request) -> web.StreamResponse:
        raise web.HTTPFound(request.path + "/")  # (a client's files are relative to its folder)

    async def list_clients(self, request: web.Request) -> web.Response:
        """The web clients this site serves, so players (and other clients) can find them."""
        return web.json_response({"default": self.default_client, "clients": [
            {"name": name, "path": "/" if name == self.default_client else f"/{name}/", "folder": f"/{name}/"}
            for name in self.clients]})

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

    # -- the player market
    async def market(self, request: web.Request) -> web.Response:
        q = request.query
        user = self.db.user_for(self.token(request))
        rarity = q.get("rarity", "") if q.get("rarity", "") in cos.RARITIES else ""
        return web.json_response({
            "listings": self.db.market(q.get("q", "").strip()[:40], rarity, q.get("sort", "cheap")),
            "mine": self.db.my_listings(user["id"]) if user else [], "fee": cos.MARKET_FEE,
            "min": cos.MARKET_MIN_PRICE, "max": cos.MARKET_MAX_PRICE})

    async def market_list(self, request: web.Request) -> web.Response:
        user = self.account(request, "Log in to sell things.")
        data = await self.body(request)
        try:
            result = self.db.list_item(user["id"], str(data.get("item", "")), data.get("price"))
        except ValueError as e:
            return self.error(str(e))
        return web.json_response({**result, "points": self.db.points(user["id"])})

    async def market_cancel(self, request: web.Request) -> web.Response:
        user = self.account(request, "Log in to use the market.")
        try:
            item = self.db.cancel_listing(user["id"], (await self.body(request)).get("id"))
        except ValueError as e:
            return self.error(str(e))
        return web.json_response({"item": item, "copies": self.db.copies(user["id"], item)})

    async def market_buy(self, request: web.Request) -> web.Response:
        user = self.account(request, "Log in to buy things.")
        try:
            result = self.db.buy_listing(user["id"], (await self.body(request)).get("id"))
        except ValueError as e:
            return self.error(str(e))
        seller = result.pop("seller_id")
        await self.notify(seller, {"t": "sold", "item": result["item"], "name": result["name"],
                                   "price": result["price"], "earned": result["price"] - result["fee"],
                                   "buyer": user["name"]})
        return web.json_response(result)

    # -- daily login rewards
    async def login_reward(self, request: web.Request) -> web.Response:
        user = self.account(request, "Log in for daily rewards.")
        return web.json_response(self.db.login_reward_info(user["id"]))

    async def claim_login_reward(self, request: web.Request) -> web.Response:
        user = self.account(request, "Log in for daily rewards.")
        try:
            return web.json_response(self.db.claim_login_reward(user["id"]))
        except ValueError as e:
            return self.error(str(e))

    # -- trading
    async def trades(self, request: web.Request) -> web.Response:
        user = self.account(request, "Log in to trade.")
        return web.json_response(self.db.trades_for(user["id"]))

    async def user_items(self, request: web.Request) -> web.Response:
        """What a player has to trade (their items, with how many copies)."""
        row = self.db.user_row(request.match_info["name"])
        if not row:
            return self.error("No player with that name.", 404)
        return web.json_response({"name": row["name"], "items": self.db.tradeable_counts(row["id"])})

    async def offer_trade(self, request: web.Request) -> web.Response:
        user = self.account(request, "Log in to trade.")
        d = await self.body(request)
        try:
            tid = self.db.offer_trade(user["id"], str(d.get("to", "")), d.get("give", []), d.get("give_points", 0),
                                      d.get("want", []), d.get("want_points", 0))
        except LookupError as e:
            return self.error(str(e), 404)
        except ValueError as e:
            return self.error(str(e))
        t = self.db.trade(tid)
        await self.notify(t["recipient"], {"t": "trade", "from": user["name"], "id": tid})
        return web.json_response(self.db.trade_view(t))

    async def answer_trade(self, request: web.Request) -> web.Response:
        user = self.account(request, "Log in to trade.")
        d = await self.body(request)
        action = d.get("action")
        if action not in ("accept", "decline", "cancel"):
            return self.error("Accept, decline or cancel?")
        try:
            t = self.db.answer_trade(user["id"], d.get("id"), action)
        except LookupError as e:
            return self.error(str(e), 404)
        except PermissionError as e:
            return self.error(str(e), 403)
        except ValueError as e:
            return self.error(str(e))
        other = t["sender"] if t["recipient"] == user["id"] else t["recipient"]
        await self.notify(other, {"t": "trade", "from": user["name"], "id": t["id"], "status": t["status"]})
        return web.json_response({**self.db.trade_view(t), "points": self.db.points(user["id"])})

    # -- the jackpot
    async def jackpot(self, request: web.Request) -> web.Response:
        return web.json_response(self.db.jackpot_state())

    async def jackpot_enter(self, request: web.Request) -> web.Response:
        user = self.account(request, "Log in to play the jackpot.")
        try:
            self.db.jackpot_enter(user["id"], (await self.body(request)).get("items"))
        except ValueError as e:
            return self.error(str(e))
        return web.json_response(self.db.jackpot_state())

    # -- watching world records
    async def replay_run(self, request: web.Request) -> web.Response:
        """A category's world record run, to watch. Built-in and weekly categories only."""
        category = request.match_info["category"]
        if category.startswith(CUSTOM_PREFIX):
            return self.error("Community runs can't be watched.", 404)
        if category not in CATEGORY_BY_ID and not category.startswith(WEEKLY_PREFIX):
            return self.error("Unknown category.", 404)
        best = self.db.best_run(category)
        if not best:
            return self.error("No world record yet.", 404)
        run = json.loads(best["run"])
        return web.json_response({"player": best["name"], "time_ms": best["time_ms"], "date": best["created"][:10],
                                  "run": {k: run.get(k) for k in ("format", "game", "category", "seed", "time_ms",
                                                                  "inputs", "splits_ms")}})

    # -- daily challenges
    async def daily(self, request: web.Request) -> web.Response:
        user = self.account(request, "Log in for daily challenges.")
        return web.json_response(self.db.daily_info(user["id"]))

    async def claim_daily(self, request: web.Request) -> web.Response:
        user = self.account(request, "Log in for daily challenges.")
        which = (await self.body(request)).get("id")
        try:
            points = self.db.claim_daily(user["id"], which)
        except ValueError as e:
            return self.error(str(e))
        return web.json_response({"points": points, **self.db.daily_info(user["id"])})

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
        self.db.progress(user["id"], "rounds")
        self.db.progress(user["id"], "fruit", min(fruit, MAX_ROUND_FRUIT))
        return web.json_response({"earned": earned, "points": self.db.add_points(user["id"], earned, "round")})

    # -- community categories
    async def categories(self, request: web.Request) -> web.Response:
        me = self.db.user_for(self.token(request))
        q = request.query
        return web.json_response({"categories": self.db.community(q.get("q", "").strip()[:40], sort=q.get("sort", "top"),
                                                                   me=me["id"] if me else None)})

    async def vote_category(self, request: web.Request) -> web.Response:
        user = self.account(request, "Log in to upvote categories.")
        data = await self.body(request)
        try:
            result = self.db.vote_category(str(data.get("id", "")), user["id"], data.get("up", True) is not False)
        except LookupError as e:
            return self.error(str(e), 404)
        except ValueError as e:
            return self.error(str(e))
        return web.json_response(result)

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
            cid, new = self.db.share_category(definition if isinstance(definition, dict) else {}, user["id"])
        except (KeyError, TypeError, ValueError) as e:
            return self.error(f"Can't share that category: {str(e).strip(chr(39))}")
        row = self.db.db.execute("SELECT categories.name, users.name AS creator FROM categories "
                                 "JOIN users ON users.id = categories.creator WHERE categories.id = ?", (cid,)).fetchone()
        return web.json_response({"id": cid, "new": new, "name": row["name"], "creator": row["creator"]})

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
            # (weekly speedruns are made from the week's name: no getting a head start on later weeks)
            if weekly and week_start(weekly) > week_start(self.db.current_week()):
                return self.error("That week hasn't started yet.")
        except (KeyError, ValueError):
            return self.error("Unknown category.")
        # Only built-in modes count online: mod modes (or anything else) can't set records.
        definition = run.get("category_def") if isinstance(run.get("category_def"), dict) else {}
        modes = definition.get("modes", [])
        if not isinstance(modes, list) or any(m not in BUILTIN_MODE_IDS for m in modes):
            return self.error("Runs using mods or unknown modes can't be submitted.")
        if not isinstance(run.get("time_ms"), int) or isinstance(run.get("time_ms"), bool):
            return self.error("The run has no time.")  # (verify() only limits the replay by the claimed time)
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
        if category in CATEGORY_BY_ID or (weekly and weekly == self.db.current_week()):
            if rank and (rank_before is None or rank < rank_before):
                earned += cos.placement_points(rank)
            if before is None or time_ms <= before * (1 - cos.PR_MIN_GAIN):
                earned += cos.PR_REWARD
            if earned:
                self.db.add_points(user["id"], earned, f"place {rank} in {category}")
            self.db.add_xp(user["id"], (cos.XP_WEEKLY if weekly else cos.XP_SPEEDRUN) + (cos.XP_PB if pb else 0))
            self.db.progress(user["id"], "speedruns")
            if weekly:
                self.db.progress(user["id"], "weekly")
            if pb and before is not None:  # (a first finish isn't a new best)
                self.db.progress(user["id"], "pbs")
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
        week = self.db.current_week()
        records = self.db.records()
        cats = []
        for c in weekly_categories(week):
            players = self.db.db.execute("SELECT COUNT(DISTINCT user_id) FROM runs WHERE category = ?",
                                         (c.id,)).fetchone()[0]
            cats.append({"id": c.id, "name": c.name, "desc": c.desc, "players": players, "wr": records.get(c.id),
                         "def": category_def(c)})  # (the rules, for games that don't make them themselves)
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
        # (newer games log in with an "auth" message instead of ?token=, which ends up in web server logs)
        user = self.db.user_for(request.query.get("token"))
        guest = re.sub(r"[^A-Za-z0-9_ -]", "", request.query.get("name", ""))[:16].strip()
        name = user["name"] if user else (guest or f"Guest{random.randint(100, 999)}")
        player = Player(ws, self.new_pid(), name, None)
        if user:
            self.sign_in(player, user)
        await ws.send_str(json.dumps({"t": "welcome", "id": player.id, "name": player.name, "account": bool(user)}))
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

    def sign_in(self, player: Player, user: sqlite3.Row) -> None:
        row = self.db.user_by_id(user["id"])
        player.user_id, player.name = user["id"], user["name"]
        player.rank, player.avatar = cos.rank_for(row["rp"])[1], row["avatar"] or cos.DEFAULT_AVATAR
        self.connected.setdefault(user["id"], set()).add(player)

    async def on_message(self, p: Player, m: dict) -> None:
        t = m.get("t")
        room = p.room
        err = None
        if t == "auth":  # log this connection in (only before joining a match)
            user = self.db.user_for(str(m.get("token", "")))
            if user and p.user_id is None and not room:
                self.sign_in(p, user)
            await p.ws.send_str(json.dumps({"t": "welcome", "id": p.id, "name": p.name,
                                            "account": p.user_id is not None}))
            return
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


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="opensnake-server", description="OpenSnake server: accounts, records, "
                                     "versus and the website's web clients")
    parser.add_argument("--host", default="0.0.0.0", help="address to listen on (default: all)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="folder for accounts and records")
    parser.add_argument("--clients", type=Path, default=DEFAULT_CLIENTS,
                        help="folder of web clients, one folder each, served at /<folder>/ (default: "
                             "web-support/clients)")
    parser.add_argument("--default-client", help="the client served at / (default: crustacean, if there)")
    parser.add_argument("--restart-week", action="store_true",
                        help="start this week over (new weekly speedruns, a fresh battle pass), then exit")
    args = parser.parse_args(argv)
    if args.restart_week:
        db = Database(args.data / "opensnake.db")
        print(f"This week is now {db.restart_week()}: new weekly speedruns and a fresh battle pass until Monday.")
        db.close()
        return
    try:
        server = Server(args.data, args.clients, args.default_client)
    except ValueError as e:
        parser.error(str(e))
    print(f"OpenSnake server {__version__}")
    print(f"  data:     {args.data}")
    if server.clients:
        for name in server.clients:
            print(f"  client:   {name} at {'/' if name == server.default_client else f'/{name}/'}")
    else:
        print(f"  clients:  none in {args.clients} (API only; see web-support/README.md)")
    print(f"  http://localhost:{args.port}/   (Ctrl+C to stop)", flush=True)
    web.run_app(server.app(), host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
