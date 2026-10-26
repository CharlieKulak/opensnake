"""Speedrun mode: fixed categories, an in-game timer, replays and records.

Times are in-game time (IGT): the sum of the tick lengths of every move made,
so a run's time doesn't depend on frame rate or how busy the computer is.
Each run is seeded and its inputs recorded, so a saved run can be replayed
exactly to verify its time (``opensnake --verify run.json``).

Records:
  PR  personal record, kept in the player's settings file.
  WR  world record, read from ``records.json``. The copy bundled with the
      game is refreshed from the project's GitHub repository when online, so
      updating that file there updates every player's WR.
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .game import Event, Game

RUN_FORMAT = 1
CUSTOM_PREFIX = "custom-"
CUSTOM_FILE_FORMAT = 1
RECORDS_URL = "https://raw.githubusercontent.com/CharlieKulak/opensnake/main/opensnake/records.json"
BUNDLED_RECORDS = Path(__file__).parent / "records.json"


@dataclass(frozen=True)
class Category:
    id: str
    name: str
    desc: str
    w: int
    h: int
    modes: tuple = ()
    goal: int | None = 10       # fruit to eat; None = play until the board is full
    fruit_count: int = 1
    tick_ms: float = 130        # time per move
    accel: float = 0            # ms faster per fruit eaten (Accelerate)
    min_tick_ms: float = 45
    fruit: str = "apple"        # "mixed" changes the random sequence, so it's part of the rules
    custom: bool = False

    def ms_for(self, score: int) -> float:
        return max(self.min_tick_ms, self.tick_ms - self.accel * score)

    @property
    def goal_text(self) -> str:
        return "Fill the board" if self.goal is None else f"Eat {self.goal}"


CATEGORIES = [
    Category("sprint10", "Sprint 10", "Eat 10 apples on a 10 x 9 board.", 10, 9, goal=10),
    Category("sprint25", "Sprint 25", "Eat 25 apples on a 10 x 9 board.", 10, 9, goal=25),
    Category("rush", "Apple Rush", "5 apples at a time on a big board. Eat 30.", 17, 15, goal=30, fruit_count=5),
    Category("accelerate", "Accelerate", "Starts slow, gets faster with every apple. Eat 30.",
             10, 9, goal=30, tick_ms=170, accel=4),
    Category("fullboard", "Full Board", "Fill every cell of an 8 x 5 board.", 8, 5, goal=None, tick_ms=110),
    Category("portal", "Portal Dash", "Portal mode: eat 15 and ride the portals.", 12, 11, ("portal",), goal=15),
    Category("walls", "Wall Gauntlet", "Wall mode: every apple adds a wall. Eat 20.", 10, 9, ("wall",), goal=20),
    Category("keys", "Key Hunt", "Key mode: grab each key, then its apple. Eat 10.", 12, 11, ("key",), goal=10),
    Category("twin", "Twin Turns", "Twin mode: you flip around after every apple. Eat 15.",
             10, 9, ("twin",), goal=15),
    Category("minefield", "Minefield", "Minesweeper mode: avoid the hidden mines. Eat 15.",
             12, 11, ("minesweeper",), goal=15),
]
CATEGORY_BY_ID = {c.id: c for c in CATEGORIES}


# ---- custom categories ----------------------------------------------------------
#
# A custom category is any combination of the normal game settings plus a goal.
# Its id is a hash of exactly those rules, so everyone who plays the same
# settings shares the same id: that is what lets personal and world records
# work for custom setups. The name is just a label and isn't part of the id.

def _rules(w, h, modes, goal, fruit_count, tick_ms, fruit) -> dict:
    return {"w": int(w), "h": int(h), "modes": sorted(str(m) for m in modes),
            "goal": None if not goal else int(goal), "fruit_count": int(fruit_count),
            "tick_ms": round(float(tick_ms), 1), "fruit": str(fruit)}


def custom_id(rules: dict) -> str:
    canon = json.dumps(rules, sort_keys=True, separators=(",", ":"))
    return CUSTOM_PREFIX + hashlib.sha1(canon.encode()).hexdigest()[:10]


def describe(rules: dict) -> str:
    from .modes import mode_label
    goal = "fill the board" if rules["goal"] is None else f"eat {rules['goal']}"
    parts = [mode_label(rules["modes"]), f"{rules['w']} x {rules['h']}", goal,
             f"{1000 / rules['tick_ms']:.1f} cells/s"]
    if rules["fruit_count"] != 1:
        parts.append(f"{rules['fruit_count']} fruit at once")
    return ", ".join(parts).capitalize() + "."


def make_custom(w, h, modes, goal, fruit_count, tick_ms, fruit="apple", name: str = "") -> Category:
    """Build a custom category from settings (goal 0 or None = fill the board)."""
    rules = _rules(w, h, modes, goal, fruit_count, tick_ms, fruit)
    return Category(custom_id(rules), name or "Custom", describe(rules), rules["w"], rules["h"],
                    tuple(rules["modes"]), rules["goal"], rules["fruit_count"], rules["tick_ms"],
                    fruit=rules["fruit"], custom=True)


def category_def(c: Category) -> dict:
    """The rules of a custom category, as saved in run files and the categories file."""
    return {"id": c.id, "name": c.name,
            **_rules(c.w, c.h, c.modes, c.goal, c.fruit_count, c.tick_ms, c.fruit)}


def category_from_def(d: dict) -> Category:
    """Rebuild a custom category; raises ValueError if its id doesn't match its rules."""
    c = make_custom(d["w"], d["h"], d.get("modes", ()), d.get("goal"), d.get("fruit_count", 1),
                    d["tick_ms"], d.get("fruit", "apple"), str(d.get("name", ""))[:40])
    if "id" in d and d["id"] != c.id:
        raise ValueError("category id doesn't match its rules")
    if not (5 <= c.w <= 1000 and 5 <= c.h <= 1000 and c.tick_ms > 0 and c.fruit_count >= 1):
        raise ValueError("category rules out of range")
    return c


def load_custom_categories(path: Path) -> list[Category]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    out, seen = [], set()
    for d in data.get("categories", []) if isinstance(data, dict) else []:
        try:
            c = category_from_def(d)
        except (KeyError, TypeError, ValueError):
            continue
        if c.id not in seen:
            seen.add(c.id)
            out.append(c)
    return out


def save_custom_categories(path: Path, categories: list[Category]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"format": CUSTOM_FILE_FORMAT,
                                    "categories": [category_def(c) for c in categories]}, indent=2))
        return True
    except OSError as e:
        print(f"opensnake: could not save custom categories: {e}", file=sys.stderr)
        return False


def find_category(category_id: str, data: dict | None = None) -> Category:
    """A built-in category by id, or a custom one from a run file's definition."""
    if category_id in CATEGORY_BY_ID:
        return CATEGORY_BY_ID[category_id]
    if category_id.startswith(CUSTOM_PREFIX) and data and isinstance(data.get("category_def"), dict):
        c = category_from_def(data["category_def"])
        if c.id != category_id:
            raise ValueError("category id doesn't match its rules")
        return c
    raise KeyError(f"unknown category {category_id!r}")


def format_time(ms: float | None) -> str:
    """12345 -> "0:12.345"; None -> "--"."""
    if ms is None:
        return "--"
    ms = int(round(ms))
    minutes, rest = divmod(ms, 60000)
    return f"{minutes}:{rest // 1000:02d}.{rest % 1000:03d}"


def format_delta(ms: float) -> str:
    """Signed difference, e.g. "-0.412" (ahead) or "+1.050" (behind)."""
    sign = "-" if ms < 0 else "+"
    ms = abs(int(round(ms)))
    if ms >= 60000:
        return f"{sign}{format_time(ms)}"
    return f"{sign}{ms // 1000}.{ms % 1000:03d}"


class Run:
    """One speedrun attempt: a seeded game plus timer, splits and input log."""

    def __init__(self, category: Category, seed: int | None = None):
        self.category = category
        self.seed = seed if seed is not None else random.randrange(2 ** 31)
        self.game = Game(category.w, category.h, category.modes, category.fruit_count, category.fruit,
                         rng=random.Random(self.seed))
        self.inputs: list[list] = []   # [tick, direction]
        self.elapsed = 0.0             # ms of in-game time
        self.splits: list[float] = []  # elapsed time at each fruit
        self.finished = False

    @property
    def tick_ms(self) -> float:
        return self.category.ms_for(self.game.score)

    @property
    def goal(self) -> int | None:
        return self.category.goal

    def input(self, d: str) -> None:
        if self.game.over:
            return
        self.inputs.append([self.game.tick, d])
        self.game.input(d)

    def step(self) -> None:
        g = self.game
        if g.over or not g.started:
            return
        ms = self.tick_ms
        tick, score = g.tick, g.score
        g.step()
        if g.tick == tick:
            return  # nothing moved
        self.elapsed += ms
        for _ in range(g.score - score):
            self.splits.append(self.elapsed)
        if (self.goal is not None and g.score >= self.goal) or (g.won and not any(s.dead for s in g.snakes)):
            self.finished = True
            if not g.over:
                g.over = g.won = True
                g.events.append(Event("win"))

    def to_json(self, player: str = "", game_version: str = "") -> dict:
        extra = {"category_def": category_def(self.category)} if self.category.custom else {}
        return {**extra,
            "format": RUN_FORMAT,
            "game": "opensnake",
            "game_version": game_version,
            "category": self.category.id,
            "seed": self.seed,
            "time_ms": round(self.elapsed),
            "time": format_time(self.elapsed),
            "splits_ms": [round(s) for s in self.splits],
            "inputs": self.inputs,
            "player": player,
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }


def replay(data: dict, max_ticks: int = 2_000_000) -> Run:
    """Re-run a saved run from its seed and inputs."""
    category = find_category(str(data["category"]), data)
    run = Run(category, int(data["seed"]))
    inputs = [(int(t), str(d)) for t, d in data["inputs"]]
    i = 0
    while not run.game.over and run.game.tick < max_ticks:
        while i < len(inputs) and inputs[i][0] <= run.game.tick:
            run.input(inputs[i][1])
            i += 1
        if not run.game.started:
            break  # no more inputs and never started
        run.step()
        run.game.events.clear()
    return run


def verify(data: dict) -> tuple[bool, str]:
    """Check a saved run: (valid, explanation)."""
    if data.get("game") != "opensnake" or data.get("format") != RUN_FORMAT:
        return False, "not an OpenSnake run file (or an unsupported format)"
    try:
        find_category(str(data.get("category")), data)
    except (KeyError, TypeError, ValueError) as e:
        return False, str(e).strip("'\"")
    try:
        run = replay(data)
    except (KeyError, TypeError, ValueError) as e:
        return False, f"malformed run file: {e}"
    claimed = data.get("time_ms")
    name = run.category.name
    if not run.finished:
        return False, f"{name}: the replay does not finish the category"
    if claimed is not None and abs(round(run.elapsed) - int(claimed)) > 0:
        return False, (f"{name}: claimed {format_time(claimed)} but the replay finishes in "
                       f"{format_time(run.elapsed)}")
    return True, f"{name}: valid, {format_time(run.elapsed)}"


# ---- world records ----------------------------------------------------------

class Records:
    """World records by category id: {"time_ms", "player", "date", ...}.

    Starts from the bundled records.json (or a cached newer copy) and, when
    allowed, refreshes from GitHub in a background thread.
    """

    def __init__(self, cache_path: Path | None = None):
        self.cache_path = cache_path
        self.records: dict[str, dict] = {}
        self.updated: str = ""
        self.source = "none"
        self._loaded = False  # whether any records file has been accepted yet
        self._load(BUNDLED_RECORDS, "bundled")
        if cache_path:
            self._load(cache_path, "cached")

    def _accept(self, data: dict, source: str) -> bool:
        if not isinstance(data, dict) or not isinstance(data.get("records"), dict):
            return False
        updated = str(data.get("updated", ""))
        if self._loaded and updated <= self.updated:
            return False  # not newer than what we have
        clean = {}
        for cid, rec in data["records"].items():
            known = cid in CATEGORY_BY_ID or (isinstance(cid, str) and cid.startswith(CUSTOM_PREFIX))
            if known and isinstance(rec, dict) and isinstance(rec.get("time_ms"), int):
                clean[cid] = rec
        self.records, self.updated, self.source = clean, updated, source
        self._loaded = True
        return True

    def _load(self, path: Path, source: str) -> None:
        try:
            self._accept(json.loads(path.read_text()), source)
        except (OSError, ValueError):
            pass

    def get(self, category_id: str) -> dict | None:
        return self.records.get(category_id)

    def refresh_in_background(self, url: str = RECORDS_URL, timeout: float = 4.0) -> None:
        def work():
            try:
                import urllib.request
                with urllib.request.urlopen(url, timeout=timeout) as resp:
                    raw = resp.read(256 * 1024)
                data = json.loads(raw)
                if self._accept(data, "online") and self.cache_path:
                    self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                    self.cache_path.write_text(json.dumps(data, indent=2))
            except Exception:
                pass  # offline or blocked: keep what we have
        threading.Thread(target=work, daemon=True).start()


def save_run(run: Run, folder: Path, player: str = "", game_version: str = "") -> Path | None:
    """Write a finished run as JSON; returns the path (None if it couldn't be written)."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = folder / f"{run.category.id}-{stamp}-{round(run.elapsed)}ms.json"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(run.to_json(player, game_version), indent=1))
        return path
    except OSError as e:
        print(f"opensnake: could not save run: {e}", file=sys.stderr)
        return None
