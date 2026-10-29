"""Window, game loop, menu and HUD."""

from __future__ import annotations

import asyncio
import json
import math
import os
import random
import sys
from pathlib import Path

import pygame

from . import render
from .audio import Sfx
from .game import Game
from . import __version__
from .modes import (DEFAULT_BOARD, DEFAULT_SPEED, FRUIT_LABELS, LEGACY_SIZES, LEGACY_SPEEDS,
                    MAX_BOARD, MIN_BOARD_H, MIN_BOARD_W, MODE_DESCS, MODES, SNAKE_COLORS, SPEED_SCALE_VERSION,
                    SPEED_TICKS, blend_modes, migrate_speed_v1, mode_label, speed_ms, toggle_mode)
from .speedrun import (CATEGORIES, Records, Run, format_delta, format_time, load_custom_categories, make_custom,
                       save_custom_categories, save_run)
from .addons import discover_packs, open_folder, restart_program, user_mods_dir, user_packs_dir
from .assets import AssetPack, config_dir, load_image
from .mods import LOADED as MOD_RESULTS
from .mods import default_dirs as mod_dirs
from .mods import describe_mod, iter_mods, load_mods
from .online import Online
from .render import FRUIT_COLORS, Renderer, View, head_position, mode_icon

KEYMAP = {
    pygame.K_UP: "up", pygame.K_DOWN: "down", pygame.K_LEFT: "left", pygame.K_RIGHT: "right",
    pygame.K_w: "up", pygame.K_s: "down", pygame.K_a: "left", pygame.K_d: "right",
}

RESOLUTIONS = [(800, 600), (1024, 768), (1280, 720), (1280, 800), (1366, 768), (1440, 900), (1600, 900),
               (1920, 1080), (1920, 1200), (2560, 1080), (2560, 1440), (3440, 1440), (3840, 2160)]
# "window" is a freely resizable window; the rest are fixed sizes, then fullscreen.
DISPLAY_VALUES = ["window"] + [f"{w}x{h}" for w, h in RESOLUTIONS] + ["fullscreen"]
DEFAULT_WINDOW = (1000, 840)

# Running in a web browser (pygbag / WebAssembly). The page scales the game's
# canvas to fit, so the Display option picks the canvas resolution (16:9 sizes)
# or fullscreen, and there is no Quit.
WEB = sys.platform == "emscripten"
WEB_RESOLUTIONS = [(1024, 576), (1280, 720), (1600, 900), (1920, 1080), (2560, 1440), (3840, 2160)]
WEB_DEFAULT_DISPLAY = "1280x720"


def browser_window():
    """The page's JavaScript ``window`` object in the browser build, else None."""
    if not WEB:
        return None
    try:
        import platform as pygbag_platform  # pygbag's module of this name exposes the page
        return getattr(pygbag_platform, "window", None)
    except Exception:
        return None


ASPECTS = [(16, 9), (16, 10), (4, 3), (5, 4), (21, 9)]


def aspect_label(w: int, h: int) -> str:
    """Nearest common aspect ratio, e.g. "16:9" (1366x768 counts as 16:9)."""
    ratio = w / h
    a, b = min(ASPECTS, key=lambda ab: abs(ab[0] / ab[1] - ratio))
    if (a, b) == (21, 9):
        return "21:9" if abs(ratio - 21 / 9) < 0.08 else f"{w}:{h}"
    return f"{a}:{b}" if abs(ratio - a / b) < 0.02 else f"{w}:{h}"


def display_label(value: str) -> str:
    if value in ("window", "fullscreen"):
        return {"window": "Window", "fullscreen": "Fullscreen"}[value]
    w, h = map(int, value.split("x"))
    return f"{w} x {h} ({aspect_label(w, h)})"


DEFAULTS = {
    "modes": [], "fruit": "apple", "apple_count": 1, "speed": DEFAULT_SPEED,
    "board_w": DEFAULT_BOARD[0], "board_h": DEFAULT_BOARD[1],
    "color": "blue", "muted": False, "display": "window",
    "speed_scale": SPEED_SCALE_VERSION,
    "speedrun_mode": False,  # menu checkbox: time a run of your own settings
    "packs": None,           # enabled resource packs, highest priority first (None = never set)
    "mods_disabled": [],     # mod names not to load
    "server_url": "",        # desktop: OpenSnake website to play online with
    "accounts": {},          # desktop: saved logins per server {url: {user, token}}
    "sr_goal": 10,           # its goal: fruit to eat (0 = fill the board)
    "player_name": "",       # put in saved speedrun files
    "online_records": True,  # fetch the latest world records from GitHub
}

GOOD = (40, 160, 70)   # ahead of PB
BAD = (210, 60, 50)    # behind PB

# Number fields: key -> (label, min, max)
MAX_FRUIT = 500
NUMBERS = {"apple_count": ("Count", 1, MAX_FRUIT), "sr_goal": ("Goal", 0, 9999),
           "board_w": ("Width", MIN_BOARD_W, MAX_BOARD), "board_h": ("Height", MIN_BOARD_H, MAX_BOARD)}

# Smallest cell size before a big board starts scrolling instead of shrinking.
MIN_CELL = 20

# When a turn is waiting, finish the current cell at least this fast, so
# turning stays snappy at slow speeds (it's the Fast speed's time per cell).
TURN_CELL_MS = 85

OPTIONS = [
    ("fruit", "Fruit", list(FRUIT_LABELS), lambda v: FRUIT_LABELS[v]),
    ("color", "Snake", list(SNAKE_COLORS), lambda v: SNAKE_COLORS[v][2]),
    ("display", "Display", DISPLAY_VALUES, display_label),
]

WHITE = (255, 255, 255)
PANEL = (255, 255, 255)
INK = (40, 52, 33)
MUTED = (96, 112, 86)
ACCENT = (61, 111, 232)


def config_path() -> Path:
    return config_dir() / "settings.json"


class Store:
    def __init__(self, path: Path):
        self.path = path
        data = {}
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            pass
        self._raw = data.get("settings", {})
        self.settings = {**DEFAULTS, **self._raw}
        self.best: dict[str, int] = data.get("best", {})
        sr = data.get("speedrun")
        self.speedrun: dict = sr if isinstance(sr, dict) else {}
        if not isinstance(self.speedrun.get("pb"), dict):
            self.speedrun["pb"] = {}
        self._sanitize()

    def _sanitize(self):
        s = self.settings
        # Older settings files used named speeds and sizes.
        if isinstance(s.get("speed"), str):
            s["speed"] = LEGACY_SPEEDS.get(s["speed"], DEFAULT_SPEED)
        legacy = s.pop("size", None)
        if legacy in LEGACY_SIZES and "board_w" not in self._raw:
            s["board_w"], s["board_h"] = LEGACY_SIZES[legacy]
        s["modes"] = [m for m in s.get("modes", []) if m in MODE_DESCS and m != "classic"]
        for key, _label, values, _show in OPTIONS:
            if s.get(key) not in values:
                s[key] = DEFAULTS[key]
        try:
            s["speed"] = min(1.0, max(0.0, float(s["speed"])))
        except (TypeError, ValueError):
            s["speed"] = DEFAULT_SPEED
        if "speed" in self._raw and self._raw.get("speed_scale") != SPEED_SCALE_VERSION:
            # Saved with the old 3-stop slider: keep the same actual speed.
            s["speed"] = migrate_speed_v1(s["speed"])
            self.best = {self._migrate_key(k): v for k, v in self.best.items()}
        s["speed_scale"] = SPEED_SCALE_VERSION
        s["player_name"] = str(s.get("player_name") or "")[:40]
        s["online_records"] = bool(s.get("online_records", True))
        s["speedrun_mode"] = bool(s.get("speedrun_mode", False))
        if not isinstance(s.get("packs"), list):
            # First run with packs: keep using the old single "assets" folder if there is one.
            s["packs"] = ["legacy:assets"] if (config_dir() / "assets").is_dir() else []
        s["packs"] = [str(x) for x in s["packs"]][:50]
        s["mods_disabled"] = [str(x) for x in s.get("mods_disabled") or []][:200]
        s["server_url"] = str(s.get("server_url") or "")[:200]
        if not isinstance(s.get("accounts"), dict):
            s["accounts"] = {}
        for key, (_label, lo, hi) in NUMBERS.items():
            try:
                s[key] = min(hi, max(lo, int(s[key])))
            except (TypeError, ValueError):
                s[key] = DEFAULTS[key]

    @staticmethod
    def _migrate_key(key: str) -> str:
        parts = key.split(":")
        try:
            parts[2] = f"{migrate_speed_v1(float(parts[2])):.2f}"
        except (IndexError, ValueError):
            return key
        return ":".join(parts)

    def pb(self, category_id: str) -> dict | None:
        return self.speedrun["pb"].get(category_id)

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"settings": self.settings, "best": self.best,
                                             "speedrun": self.speedrun}, indent=2))
        except OSError:
            pass  # read-only home etc.; settings just won't persist

    @staticmethod
    def peek(path: Path, key: str, default):
        """Read one raw setting before the store is set up."""
        try:
            value = json.loads(path.read_text()).get("settings", {}).get(key, default)
        except (OSError, ValueError, AttributeError):
            return default
        return value if isinstance(value, type(default)) else default

    def score_key(self) -> str:
        s = self.settings
        modes = "+".join(sorted(s["modes"])) or "classic"
        return f"{modes}:{s['board_w']}x{s['board_h']}:{s['speed']:.2f}:{s['apple_count']}"


def trophy(surf, x, y, size):
    gold, dark = (255, 202, 40), (214, 150, 0)
    w = size
    pygame.draw.polygon(surf, gold, [(x + w * 0.2, y + w * 0.1), (x + w * 0.8, y + w * 0.1),
                                     (x + w * 0.72, y + w * 0.5), (x + w * 0.28, y + w * 0.5)])
    pygame.draw.circle(surf, gold, (x + w * 0.5, y + w * 0.45), w * 0.22)
    for side in (0.15, 0.85):
        pygame.draw.circle(surf, dark, (x + w * side, y + w * 0.25), w * 0.12, max(2, int(w * 0.06)))
    pygame.draw.rect(surf, dark, (x + w * 0.44, y + w * 0.6, w * 0.12, w * 0.15))
    pygame.draw.rect(surf, gold, (x + w * 0.3, y + w * 0.75, w * 0.4, w * 0.12), border_radius=3)


class App:
    def __init__(self, assets_dir: str | None = None, mods_dir: str | None = None):
        # Window class / app id "opensnake" matches StartupWMClass in the
        # .desktop file, so the taskbar shows the right name and icon.
        for hint in ("SDL_VIDEO_X11_WMCLASS", "SDL_VIDEO_WAYLAND_WMCLASS", "SDL_APP_ID"):
            os.environ.setdefault(hint, "opensnake")
        pygame.init()
        # Mods first: they can add modes and fruits the settings refer to.
        # (Only the list of disabled mods is needed from the settings for this.)
        self.mod_dir_list = mod_dirs(mods_dir)
        self.mods_disabled_at_start = set(Store.peek(config_path(), "mods_disabled", []))
        self.mod_results = load_mods(self.mod_dir_list, self.mods_disabled_at_start)
        OPTIONS[0][2][:] = list(FRUIT_LABELS)
        pygame.display.set_caption("OpenSnake")
        logo = Path(__file__).parent / "images" / "opensnake.svg"
        try:
            pygame.display.set_icon(pygame.image.load_sized_svg(str(logo), (64, 64)))
        except (pygame.error, FileNotFoundError):
            pass  # no icon is fine
        if WEB:
            DISPLAY_VALUES[:] = [f"{w}x{h}" for w, h in WEB_RESOLUTIONS] + ["fullscreen"]
            DEFAULTS["display"] = WEB_DEFAULT_DISPLAY
            self.desktop = self.window_size = DEFAULT_WINDOW
        else:
            self.desktop = self._desktop_size()
            # Only offer fixed window sizes that fit on this monitor.
            DISPLAY_VALUES[:] = [v for v in DISPLAY_VALUES if v in ("window", "fullscreen")
                                 or all(a <= b for a, b in zip(map(int, v.split("x")), self.desktop))]
            dw, dh = self.desktop
            self.window_size = (min(DEFAULT_WINDOW[0], dw - 80), min(DEFAULT_WINDOW[1], dh - 100))
        self.clock = pygame.time.Clock()
        self.store = Store(config_path())
        windowed = WEB_DEFAULT_DISPLAY if WEB else "window"
        self.windowed_display = windowed if self.store.settings["display"] == "fullscreen" \
            else self.store.settings["display"]
        self.icon_cache: dict = {}
        self.apply_display()
        self.assets_dir = assets_dir
        self.ad_col = 0                    # Packs & Mods screen: 0 = packs, 1 = mods
        self.ad_row = [0, 0]
        self.ad_hits: list[tuple] = []     # (rect, action) for mouse clicks on that screen
        self.ad_packs = discover_packs()
        self.apply_packs()
        self.state = "menu"
        self.paused = False
        self.acc = 0.0
        self.over_at = None  # ms when the game ended, to delay the panel
        self.focus = 0
        self.widgets: list[dict] = []
        self.buttons: list[dict] = []
        self.editing: dict | None = None  # number field being typed into
        self.dragging = False              # speed slider held with the mouse
        self.attempt: Run | None = None    # active speedrun, if any (not `run`: that's the main loop)
        self.run_result: dict | None = None
        self.sr_focus = 0                  # selected row on the speedrun screen
        self.sr_rows: list[pygame.Rect] = []
        self.attempt_origin = "speedrun"   # where Esc / Back goes after a run: "menu" or "speedrun"
        self.custom_path = config_dir() / "custom-categories.json"
        self.custom_cats = load_custom_categories(self.custom_path)
        self.sr_scroll = 0                 # first visible row on the speedrun screen
        self.sr_delete: str | None = None  # custom category id awaiting a second Delete
        self.records = Records(config_dir() / "records-cache.json")
        if not WEB and self.store.settings["online_records"]:
            self.records.refresh_in_background()
        self.online = Online(self)  # site connection, accounts, versus
        self.running = True
        self.new_game()
        self.focus_play()

    # ---- display -----------------------------------------------------------------

    @staticmethod
    def _desktop_size():
        try:
            sizes = pygame.display.get_desktop_sizes()
            if sizes:
                return sizes[0]
        except (AttributeError, pygame.error):
            pass
        info = pygame.display.Info()
        return (info.current_w, info.current_h) if info.current_w > 0 else (1920, 1080)

    def apply_display(self):
        value = self.store.settings["display"]
        if WEB:
            self.apply_web_display(value)
            return
        if value == "fullscreen":
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        elif value == "window":
            self.screen = pygame.display.set_mode(self.window_size, pygame.RESIZABLE)
        else:
            w, h = map(int, value.split("x"))
            self.screen = pygame.display.set_mode((w, h))
        if value != "fullscreen":
            self.windowed_display = value
        self.icon_cache.clear()

    def apply_web_display(self, value):
        """Browser: set the canvas resolution; the page scales it to fit.

        Fullscreen uses the monitor's own resolution so it fills the screen
        with no bars. Browsers only allow entering fullscreen right after a
        key press or click, which is when this runs.
        """
        win = browser_window()
        doc = getattr(win, "document", None) if win else None
        if value == "fullscreen":
            size = WEB_RESOLUTIONS[3]
            try:
                size = (int(win.screen.width), int(win.screen.height))
                doc.documentElement.requestFullscreen()
            except Exception:
                pass  # no JS access or fullscreen refused: just use a big 16:9 canvas
        else:
            size = tuple(map(int, value.split("x")))
            self.windowed_display = value
            try:
                if doc.fullscreenElement:
                    doc.exitFullscreen()
            except Exception:
                pass
        self.screen = pygame.display.set_mode(size)
        self.icon_cache.clear()

    def toggle_fullscreen(self):
        s = self.store.settings
        s["display"] = self.windowed_display if s["display"] == "fullscreen" else "fullscreen"
        self.store.save()
        self.apply_display()

    # ---- game lifecycle --------------------------------------------------------

    @property
    def settings(self):
        return self.store.settings

    def new_game(self):
        s = self.settings
        self.attempt = None
        self.game = Game(s["board_w"], s["board_h"], s["modes"], s["apple_count"], s["fruit"])
        self._reset_play()

    def start_run(self, category, origin: str = "speedrun"):
        self.attempt_origin = origin
        self.attempt = Run(category)
        self.game = self.attempt.game
        self.state = "play"
        self._reset_play()

    def restart(self):
        if self.attempt:
            self.start_run(self.attempt.category, self.attempt_origin)
        else:
            self.new_game()

    def leave_run(self):
        """Back to wherever the run was started from."""
        if self.attempt_origin == "menu":
            self.open_menu()
        else:
            self.open_speedrun()

    def all_categories(self):
        return CATEGORIES + self.custom_cats

    def custom_category(self, name: str = ""):
        """The custom speedrun category made of the current menu settings."""
        s = self.settings
        cat = make_custom(s["board_w"], s["board_h"], s["modes"], s["sr_goal"], s["apple_count"],
                          speed_ms(s["speed"]), s["fruit"], name)
        saved = next((c for c in self.custom_cats if c.id == cat.id), None)
        return saved or cat

    def add_custom_category(self):
        """Save the current settings as a named category on the speedrun screen."""
        cat = self.custom_category()
        if not any(c.id == cat.id for c in self.custom_cats):
            s = self.settings
            label = mode_label(s["modes"]).replace("Blender: ", "")
            name = f"{label} {cat.w}x{cat.h} {cat.goal_text}"
            cat = make_custom(cat.w, cat.h, cat.modes, cat.goal, cat.fruit_count, cat.tick_ms, cat.fruit, name)
            self.custom_cats.append(cat)
            save_custom_categories(self.custom_path, self.custom_cats)
        self.sr_focus = next(i for i, c in enumerate(self.all_categories()) if c.id == cat.id)

    def delete_custom_category(self, category_id: str):
        self.custom_cats = [c for c in self.custom_cats if c.id != category_id]
        save_custom_categories(self.custom_path, self.custom_cats)
        self.sr_focus = min(self.sr_focus, len(self.all_categories()) - 1)
        self.sr_delete = None

    def open_speedrun(self):
        self.state = "speedrun"
        self.attempt = None
        self.new_game()

    def turn_boost(self) -> float:
        """How much faster to move while a turn is waiting (1.0 = normal).

        At slow speeds the snake can only turn at the next cell, which could
        take a quarter of a second. While a turn is queued it glides through
        the rest of its cell at the Fast speed instead, then carries on at the
        chosen speed. Speedrun times aren't affected: they count moves, not
        real time.
        """
        ms = self.tick_ms()
        if ms > TURN_CELL_MS and any(s.queue or s.planned for s in self.game.snakes):
            return ms / TURN_CELL_MS
        return 1.0

    def tick_ms(self) -> float:
        if self.state == "versus":
            return self.online.tick_ms
        return self.attempt.tick_ms if self.attempt else speed_ms(self.settings["speed"])

    def _reset_play(self):
        self.run_result = None
        self.paused = False
        self.acc = 0.0
        self.over_at = None
        self.recorded = False
        self.new_best = False

    def play(self):
        if self.settings["speedrun_mode"]:
            self.start_run(self.custom_category(), origin="menu")
            return
        self.state = "play"
        self.new_game()

    def open_menu(self):
        self.state = "menu"
        self.focus_play()

    def focus_play(self):
        self.layout_menu()
        self.focus = next(i for i, w in enumerate(self.widgets) if w.get("id") == "play")

    def best(self) -> int:
        return self.store.best.get(self.store.score_key(), 0)

    def finish_run(self):
        """Record a speedrun that just ended (finished or died)."""
        if self.recorded:
            return
        self.recorded = True
        run = self.attempt
        cat = run.category
        pb = self.store.pb(cat.id)
        result = {"finished": run.finished, "time": run.elapsed, "score": run.game.score,
                  "pb_before": pb["time_ms"] if pb else None, "new_pb": False, "file": None}
        if run.finished:
            path = save_run(run, config_dir() / "speedruns", self.settings["player_name"], __version__)
            result["file"] = str(path) if path else None
            if pb is None or round(run.elapsed) < pb["time_ms"]:
                result["new_pb"] = True
                self.store.speedrun["pb"][cat.id] = {
                    "time_ms": round(run.elapsed), "splits_ms": [round(x) for x in run.splits],
                    "date": run.to_json()["date"], "file": result["file"]}
                self.store.save()
        self.run_result = result
        if run.finished and self.online.logged_in:
            def report(text, color, res=result):
                res["online"] = (text, color)
            self.online.submit_run(run.to_json(self.online.user, __version__), report)

    def record_score(self):
        if self.recorded:
            return
        self.recorded = True
        key = self.store.score_key()
        self.new_best = self.game.score > self.store.best.get(key, 0)
        if self.new_best:
            self.store.best[key] = self.game.score
            self.store.save()

    # ---- layout ------------------------------------------------------------------

    def header_h(self) -> int:
        return max(48, self.screen.get_height() // 14)

    def board_rect(self) -> pygame.Rect:
        """Screen rectangle of the board viewport; also sets the cell size.

        Boards that fit are scaled to fill the window. Bigger ones keep a
        readable cell size and scroll with the snake instead.
        """
        sw, sh = self.screen.get_size()
        hh = self.header_h()
        margin = 18
        g = self.game
        aw, ah = max(1, sw - 2 * margin), max(1, sh - hh - 2 * margin)
        c = min(aw // g.w, ah // g.h, 200)
        if c < MIN_CELL:
            c = min(MIN_CELL, max(4, min(aw, ah) // 5))
        self.renderer.c = c
        vw, vh = min(g.w * c, aw), min(g.h * c, ah)
        return pygame.Rect((sw - vw) // 2, hh + (sh - hh - vh) // 2, vw, vh)

    def camera(self, rect, t):
        """Top-left board cell of the viewport, centred on the snake's head."""
        g, c = self.game, self.renderer.c
        hx, hy = head_position(g, t, self.online.you if self.state == "versus" else 0)
        span_x, span_y = rect.w / c, rect.h / c
        cam_x = 0.0 if g.w <= span_x else min(g.w - span_x, max(0.0, hx - span_x / 2))
        cam_y = 0.0 if g.h <= span_y else min(g.h - span_y, max(0.0, hy - span_y / 2))
        return cam_x, cam_y

    # ---- events ------------------------------------------------------------------

    def handle(self, ev):
        if ev.type == pygame.QUIT:
            self.running = False
        elif ev.type == pygame.VIDEORESIZE and self.store.settings["display"] == "window":
            self.window_size = ev.size
        elif ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_F11:
                self.toggle_fullscreen()
            elif ev.key == pygame.K_m and self.state == "play":
                self.toggle_mute()
            elif self.state == "menu":
                self.menu_key(ev)
            elif self.state == "speedrun":
                self.speedrun_key(ev)
            elif self.state == "addons":
                self.addons_key(ev)
            elif self.state in ("online", "lobby", "matches"):
                self.online.key(ev)
            elif self.state == "versus":
                self.online.versus_key(ev)
            else:
                self.play_key(ev)
        elif ev.type == pygame.MOUSEMOTION:
            if self.dragging:
                self.slide_to(ev.pos[0])
                return
            if self.state == "speedrun":
                row = self.sr_hit(ev.pos)
                if row is not None:
                    self.sr_focus = row
                return
            hit = self.hit(ev.pos)
            if hit is not None and self.state == "menu" and not self.editing:
                self.focus = hit
        elif ev.type == pygame.MOUSEWHEEL and self.state == "speedrun":
            self.sr_scroll = max(0, self.sr_scroll - ev.y)
        elif ev.type == pygame.MOUSEWHEEL and self.state == "matches":
            self.online.scroll(-ev.y)
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            self.click(ev.pos)
        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1 and self.dragging:
            self.dragging = False
            self.store.save()

    def play_key(self, ev):
        g = self.game
        if ev.key == pygame.K_r:
            self.restart()  # instant reset, any time
            return
        if ev.key in KEYMAP:
            if not g.over and not self.paused:
                was_started = g.started
                before = [len(s.queue) for s in g.snakes]
                (self.attempt or g).input(KEYMAP[ev.key])
                if not was_started:
                    self.sfx.play("start")
                elif [len(s.queue) for s in g.snakes] != before:
                    self.sfx.play("turn")
            return
        if ev.key == pygame.K_ESCAPE:
            if g.started and not g.over and not self.paused:
                self.paused = True
            elif self.attempt:
                self.leave_run()
            else:
                self.open_menu()
        elif ev.key in (pygame.K_p, pygame.K_SPACE, pygame.K_RETURN):
            if g.over and self.over_panel_ready():
                self.restart()
            elif g.started and not g.over:
                self.paused = not self.paused

    def toggle_mute(self):
        self.settings["muted"] = not self.settings["muted"]
        self.sfx.muted = self.settings["muted"]
        self.store.save()

    def hit(self, pos):
        for i, w in enumerate(self.widgets if self.state == "menu" else []):
            if w["rect"].collidepoint(pos):
                return i
        return None

    def click(self, pos):
        if self.state in ("online", "lobby", "matches"):
            self.online.click(pos)
            return
        if self.state == "addons":
            for rect, action in self.ad_hits:
                if rect.collidepoint(pos):
                    action()
                    return
            return
        if self.state == "speedrun":
            row = self.sr_hit(pos)
            if row is not None:
                self.sr_focus = row
                self.start_run(self.all_categories()[row])
            elif getattr(self, "sr_back", None) and self.sr_back.collidepoint(pos):
                self.open_menu()
            elif getattr(self, "sr_add", None) and self.sr_add.collidepoint(pos):
                self.add_custom_category()
            return
        if self.state == "menu":
            i = self.hit(pos)
            if self.editing and (i is None or self.widgets[i].get("key") != self.editing["key"]):
                self.commit_edit()
            if i is None:
                return
            w = self.widgets[i]
            self.focus = i
            r = w["rect"]
            if w["kind"] == "opt":
                self.cycle(w["key"], -1 if pos[0] < r.centerx - r.w // 6 else 1)
            elif w["kind"] == "check":
                self.toggle_check(w["key"])
            elif w["kind"] == "slider":
                self.dragging = True
                self.slide_to(pos[0])
            elif w["kind"] == "num":
                if pos[0] >= r.right - r.h:
                    self.nudge(w["key"], 1)
                elif r.x + r.w * 0.36 <= pos[0] < r.x + r.w * 0.36 + r.h:
                    self.nudge(w["key"], -1)
                else:
                    self.editing = {"key": w["key"], "buf": ""}
            else:
                self.activate(w)
        else:
            for b in self.buttons:
                if b["rect"].collidepoint(pos):
                    b["action"]()
                    return

    # ---- menu --------------------------------------------------------------------

    def menu_key(self, ev):
        w = self.widgets[self.focus]
        if self.editing:
            if ev.unicode and ev.unicode.isdigit():
                if len(self.editing["buf"]) < 4:
                    self.editing["buf"] += ev.unicode
                return
            if ev.key == pygame.K_BACKSPACE:
                self.editing["buf"] = self.editing["buf"][:-1]
                return
            if ev.key == pygame.K_ESCAPE:
                self.editing = None
                return
            self.commit_edit()
            if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return
            # anything else (arrows, Tab) falls through and moves on
        if w["kind"] == "num":
            if ev.unicode and ev.unicode.isdigit():
                self.editing = {"key": w["key"], "buf": ev.unicode}
                return
            if ev.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_a, pygame.K_d):
                step = 10 if ev.mod & pygame.KMOD_SHIFT else 1
                self.nudge(w["key"], step if ev.key in (pygame.K_RIGHT, pygame.K_d) else -step)
                return
        if w["kind"] == "slider" and ev.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_a, pygame.K_d):
            step = 0.05 if ev.key in (pygame.K_RIGHT, pygame.K_d) else -0.05
            self.set_speed(self.settings["speed"] + step)
            self.store.save()
            return
        if w["kind"] == "check" and ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE,
                                               pygame.K_LEFT, pygame.K_RIGHT):
            self.toggle_check(w["key"])
            return
        if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            if w["kind"] == "opt":
                self.cycle(w["key"], 1)
            elif w["kind"] == "num":
                self.editing = {"key": w["key"], "buf": ""}
            elif w["kind"] != "slider":
                self.activate(w)
        elif ev.key == pygame.K_ESCAPE:
            if self.game.started and not self.game.over:
                self.state = "play"
                self.paused = True
        elif ev.key in (pygame.K_LEFT, pygame.K_a) and w["kind"] == "opt":
            self.cycle(w["key"], -1)
        elif ev.key in (pygame.K_RIGHT, pygame.K_d) and w["kind"] == "opt":
            self.cycle(w["key"], 1)
        elif ev.key in KEYMAP:
            self.move_focus(KEYMAP[ev.key])
        elif ev.key == pygame.K_TAB:
            step = -1 if ev.mod & pygame.KMOD_SHIFT else 1
            self.focus = (self.focus + step) % len(self.widgets)
        elif ev.key == pygame.K_b:
            self.activate({"kind": "btn", "id": "blender"})
        elif ev.key == pygame.K_m:
            self.open_addons()
        elif ev.key == pygame.K_o:
            self.open_online()
        elif ev.key == pygame.K_t:  # (S is taken: WASD "down")
            self.open_speedrun()

    def move_focus(self, d):
        """Spatial navigation: nearest widget in the pressed direction."""
        cur = self.widgets[self.focus]["rect"]
        dx, dy = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}[d]
        best, best_score = None, None
        for i, w in enumerate(self.widgets):
            if i == self.focus:
                continue
            r = w["rect"]
            vx, vy = r.centerx - cur.centerx, r.centery - cur.centery
            along = vx * dx + vy * dy
            if along <= 0:
                continue
            across = abs(vx * dy) + abs(vy * dx)
            score = along + across * 2.5
            if best_score is None or score < best_score:
                best, best_score = i, score
        if best is not None:
            self.focus = best

    def cycle(self, key, step):
        for k, _label, values, _show in OPTIONS:
            if k == key:
                i = values.index(self.settings[key])
                self.settings[key] = values[(i + step) % len(values)]
        self.store.save()
        if key == "display":
            self.apply_display()
        else:
            self.new_game()

    def toggle_check(self, key):
        self.settings[key] = not self.settings[key]
        self.store.save()

    # number fields and the speed slider

    def set_number(self, key, value):
        _label, lo, hi = NUMBERS[key]
        value = min(hi, max(lo, value))
        if value != self.settings[key]:
            self.settings[key] = value
            self.store.save()
            self.new_game()

    def nudge(self, key, step):
        self.set_number(key, self.settings[key] + step)

    def commit_edit(self):
        ed, self.editing = self.editing, None
        if ed and ed["buf"]:
            self.set_number(ed["key"], int(ed["buf"]))

    def set_speed(self, value):
        value = min(1.0, max(0.0, value))
        for pos, _label, _ms in SPEED_TICKS:  # snap onto the labelled ticks
            if abs(value - pos) < 0.025:
                value = pos
        self.settings["speed"] = round(value, 3)

    def slider_track(self, r):
        """(x0, x1, y) of the slider's track inside widget rect r."""
        return r.x + r.w * 0.17, r.right - r.w * 0.17, r.y + r.h * 0.4

    def slide_to(self, x):
        w = next(w for w in self.widgets if w["kind"] == "slider")
        x0, x1, _ = self.slider_track(w["rect"])
        self.set_speed((x - x0) / (x1 - x0))

    def activate(self, w):
        if w["kind"] == "mode":
            self.settings["modes"] = sorted(toggle_mode(self.settings["modes"], w["id"]))
            self.store.save()
            self.new_game()
        elif w.get("id") == "blender":
            self.settings["modes"] = sorted(blend_modes())
            self.store.save()
            self.new_game()
        elif w.get("id") == "play":
            self.play()
        elif w.get("id") == "speedrun":
            self.open_speedrun()
        elif w.get("id") == "addons":
            self.open_addons()
        elif w.get("id") == "online":
            self.open_online()
        elif w.get("id") == "quit":
            self.running = False

    def layout_menu(self):
        sw, sh = self.screen.get_size()
        # Scale the menu up on big screens; small screens just use what's there.
        grow = max(1.0, min(sw / DEFAULT_WINDOW[0], sh / DEFAULT_WINDOW[1]))
        pw = min(sw - 40, round(940 * grow))
        ph = min(sh - 40, round(800 * grow))
        panel = pygame.Rect((sw - pw) // 2, (sh - ph) // 2, pw, ph)
        self.panel = panel
        widgets = []
        cols = 7 if pw > 700 else 5 if pw > 480 else 4
        rows = math.ceil(len(MODES) / cols)
        gap = 10
        title_h = int(ph * 0.12)
        grid_h = int(ph * 0.33)
        tile = min((pw - 40 - gap * (cols - 1)) // cols, (grid_h - gap * (rows - 1)) // rows)
        gx = panel.x + (pw - (cols * tile + (cols - 1) * gap)) // 2
        gy = panel.y + title_h
        for i, (mid, _name, _desc) in enumerate(MODES):
            r, c = divmod(i, cols)
            widgets.append({"kind": "mode", "id": mid,
                            "rect": pygame.Rect(gx + c * (tile + gap), gy + r * (tile + gap), tile, tile)})
        self.tile = tile
        y = gy + rows * (tile + gap) + int(ph * 0.05)
        self.desc_y = y - int(ph * 0.03)
        row_h = max(28, int(ph * 0.05))
        ow = min(round(360 * grow), pw // 2 - 30)
        lx, rx = panel.centerx - ow - 10, panel.centerx + 10
        grid = [(("opt", "fruit"), ("opt", "display")),
                (("opt", "color"), ("num", "apple_count")),
                (("num", "board_w"), ("num", "board_h")),
                (("check", "speedrun_mode"), ("num", "sr_goal"))]
        for row in grid:
            for x, (kind, key) in zip((lx, rx), row):
                widgets.append({"kind": kind, "key": key, "rect": pygame.Rect(x, y, ow, row_h)})
            y += row_h + 6
        slider_h = int(row_h * 1.6)
        widgets.append({"kind": "slider", "key": "speed", "rect": pygame.Rect(lx, y, ow * 2 + 20, slider_h)})
        bh = max(36, int(ph * 0.065))
        hint_h = int(ph * 0.024) + 16  # shortcut hint along the panel's bottom edge
        by = min(y + slider_h + 10, panel.bottom - hint_h - bh)
        buttons = [("blender", "Blender"), ("speedrun", "Speedrun"), ("online", "Online"),
                   ("addons", "Packs & Mods"), ("play", "Play")] + \
            ([] if WEB else [("quit", "Quit")])
        bw = min(round(190 * grow), (pw - 40) // len(buttons) - 16)
        for i, (bid, _label) in enumerate(buttons):
            x = panel.centerx + (i - (len(buttons) - 1) / 2) * (bw + 16) - bw // 2
            widgets.append({"kind": "btn", "id": bid, "rect": pygame.Rect(x, by, bw, bh)})
        self.widgets = widgets
        self.focus = min(self.focus, len(widgets) - 1)

    def draw_menu(self):
        scr = self.screen
        R = self.renderer
        self.layout_menu()
        shade = pygame.Surface(scr.get_size(), pygame.SRCALPHA)
        shade.fill((20, 35, 12, 150))
        scr.blit(shade, (0, 0))
        p = self.panel
        pygame.draw.rect(scr, PANEL, p, border_radius=18)
        ph = p.h

        title = R.font(int(ph * 0.08)).render("OpenSnake", True, (74, 117, 44))
        scr.blit(title, title.get_rect(midtop=(p.centerx, p.y + int(ph * 0.025))))
        active = set(self.settings["modes"])
        focused = self.widgets[self.focus]

        label = R.font(int(ph * 0.032), False).render(mode_label(active), True, MUTED)
        scr.blit(label, label.get_rect(midtop=(p.centerx, p.y + int(ph * 0.025) + title.get_height())))

        name_font = R.font(max(14, int(self.tile * 0.2)))
        for w in self.widgets:
            r = w["rect"]
            is_focus = w is focused
            if w["kind"] == "mode":
                on = (not active) if w["id"] == "classic" else w["id"] in active
                bg = (226, 238, 255) if on else (242, 244, 239)
                pygame.draw.rect(scr, bg, r, border_radius=12)
                isz = int(r.w * 0.62)
                key = (w["id"], isz)
                if key not in self.icon_cache:
                    self.icon_cache[key] = mode_icon(R.sprites, w["id"], isz)
                icon = self.icon_cache[key]
                scr.blit(icon, icon.get_rect(midtop=(r.centerx, r.y + int(r.h * 0.08))))
                txt = name_font.render(dict((m[0], m[1]) for m in MODES)[w["id"]], True, INK)
                if txt.get_width() > r.w - 6:
                    txt = pygame.transform.smoothscale(txt, (r.w - 6, int(txt.get_height() * (r.w - 6) / txt.get_width())))
                scr.blit(txt, txt.get_rect(midbottom=(r.centerx, r.bottom - int(r.h * 0.05))))
                if on:
                    pygame.draw.rect(scr, ACCENT, r, 3, border_radius=12)
            elif w["kind"] == "opt":
                key = w["key"]
                _k, lab, _values, show = next(o for o in OPTIONS if o[0] == key)
                pygame.draw.rect(scr, (242, 244, 239), r, border_radius=10)
                f = R.font(int(r.h * 0.6))
                scr.blit(f.render(lab, True, MUTED), f.render(lab, True, MUTED).get_rect(midleft=(r.x + 14, r.centery)))
                vx = r.x + r.w * 0.68
                val = f.render(show(self.settings[key]), True, INK)
                val_rect = val.get_rect(center=(vx, r.centery))
                scr.blit(val, val_rect)
                for sx, ch in ((r.x + r.w * 0.36 + r.h / 2, "<"), (r.right - r.h / 2, ">")):
                    a = f.render(ch, True, ACCENT)
                    scr.blit(a, a.get_rect(center=(sx, r.centery)))
                # small preview just left of the value
                if key == "fruit" and self.settings["fruit"] != "mixed":
                    spr = R.sprites.get("fruit", int(r.h * 0.85), self.settings["fruit"])
                    scr.blit(spr, spr.get_rect(midright=(val_rect.left - 6, r.centery)))
                if key == "color":
                    render.aa_disc(scr, SNAKE_COLORS[self.settings["color"]][0], val_rect.left - 6 - r.h * 0.25,
                                   r.centery, r.h * 0.25)
            elif w["kind"] == "num":
                self.draw_number(w, r)
            elif w["kind"] == "check":
                self.draw_check(w, r)
            elif w["kind"] == "slider":
                self.draw_slider(r)
            else:
                primary = w["id"] == "play"
                bg = ACCENT if primary else (242, 244, 239)
                pygame.draw.rect(scr, bg, r, border_radius=r.h // 2)
                text = {"blender": "Blender", "speedrun": "Speedrun", "addons": "Packs & Mods", "online": "Online",
                        "play": "Play", "quit": "Quit"}[w["id"]]
                t = R.font(int(r.h * 0.55)).render(text, True, WHITE if primary else INK)
                if t.get_width() > r.w - 16:  # long label on a narrow button
                    t = R.font(int(r.h * 0.55 * (r.w - 16) / t.get_width())).render(text, True,
                                                                                    WHITE if primary else INK)
                scr.blit(t, t.get_rect(center=r.center))
            if is_focus:
                pygame.draw.rect(scr, (255, 170, 0), r.inflate(6, 6), 3, border_radius=14)

        if focused["kind"] == "mode":
            desc = MODE_DESCS[focused["id"]]
        elif focused.get("id") == "blender":
            desc = "Mix 2-4 random modes together."
        elif focused.get("id") == "online":
            desc = "Accounts, this site's leaderboards and versus matches (1v1 up to 4v4) with a code."
        elif focused.get("id") == "addons":
            desc = "Turn resource packs and mods on and off, like Minecraft resource packs."
        elif focused.get("id") == "speedrun":
            desc = "Race fixed categories against the clock. Personal and world records."
        elif focused["kind"] == "check":
            cat = self.custom_category()
            pb = self.store.pb(cat.id)
            desc = ("Play times a speedrun of these settings, with PB and WR. "
                    f"PB here: {format_time(pb['time_ms']) if pb else '--'}")
        elif focused["kind"] == "num" and focused["key"] == "sr_goal":
            desc = "Speedrun goal: fruit to eat. 0 = fill the whole board."
        elif focused["kind"] == "num" and focused["key"] == "apple_count":
            desc = f"Fruit on the board at once, 1 to {MAX_FRUIT}. Type a number, or Left/Right (Shift: 10)."
        elif focused["kind"] == "num":
            desc = (f"Board size in cells, {MIN_BOARD_W}x{MIN_BOARD_H} up to {MAX_BOARD}x{MAX_BOARD}. "
                    "Type a number, or Left/Right (Shift: 10).")
        elif focused["kind"] == "slider":
            desc = "Drag, or Left/Right. Snaps to Slow, Default and Fast."
        else:
            desc = f"Best for this setup: {self.best()}"
        d = R.font(int(ph * 0.03), False).render(desc, True, INK)
        scr.blit(d, d.get_rect(center=(p.centerx, self.desc_y)))
        mods_ok = sum(1 for _n, err in self.mod_results if err is None)
        mods_bad = len(self.mod_results) - mods_ok
        mods_txt = f"   Mods: {mods_ok} loaded" if self.mod_results else ""
        if mods_bad:
            mods_txt += f", {mods_bad} failed (see terminal)"
        hint = R.font(int(ph * 0.024), False).render(
            "Arrows: move   Enter: select   B: blender   T: speedrun   O: online   M: packs & mods   F11: fullscreen" + mods_txt, True, MUTED)
        scr.blit(hint, hint.get_rect(midbottom=(p.centerx, p.bottom - 10)))

    def draw_check(self, w, r):
        scr, R = self.screen, self.renderer
        on = self.settings[w["key"]]
        pygame.draw.rect(scr, (226, 238, 255) if on else (242, 244, 239), r, border_radius=10)
        f = R.font(int(r.h * 0.6))
        lab = f.render("Speedrun", True, INK if on else MUTED)
        scr.blit(lab, lab.get_rect(midleft=(r.x + 14, r.centery)))
        box = pygame.Rect(0, 0, int(r.h * 0.62), int(r.h * 0.62))
        box.midleft = (r.x + r.w * 0.42, r.centery)
        pygame.draw.rect(scr, ACCENT if on else WHITE, box, border_radius=5)
        pygame.draw.rect(scr, ACCENT if on else (170, 178, 164), box, 2, border_radius=5)
        if on:  # check mark
            pts = [(box.x + box.w * 0.22, box.y + box.h * 0.52), (box.x + box.w * 0.43, box.y + box.h * 0.74),
                   (box.x + box.w * 0.8, box.y + box.h * 0.28)]
            pygame.draw.lines(scr, WHITE, False, pts, max(2, box.w // 7))
        small = R.font(int(r.h * 0.42), False)
        txt = small.render("timed run of my settings" if on else "off", True, INK if on else MUTED)
        scr.blit(txt, txt.get_rect(midleft=(box.right + 10, r.centery)))

    def draw_number(self, w, r):
        scr, R = self.screen, self.renderer
        key = w["key"]
        label, _lo, _hi = NUMBERS[key]
        pygame.draw.rect(scr, (242, 244, 239), r, border_radius=10)
        f = R.font(int(r.h * 0.6))
        lab = f.render(label, True, MUTED)
        scr.blit(lab, lab.get_rect(midleft=(r.x + 14, r.centery)))
        box = pygame.Rect(0, 0, int(r.w * 0.36), int(r.h * 0.78))
        box.center = (r.x + r.w * 0.68, r.centery)
        editing = self.editing and self.editing["key"] == key
        pygame.draw.rect(scr, WHITE, box, border_radius=6)
        pygame.draw.rect(scr, ACCENT if editing else (200, 206, 194), box, 2, border_radius=6)
        text = self.editing["buf"] if editing else str(self.settings[key])
        if editing and (pygame.time.get_ticks() // 500) % 2 == 0:
            text += "|"
        val = f.render(text, True, INK)
        scr.blit(val, val.get_rect(center=box.center))
        for sx, ch in ((r.x + r.w * 0.36 + r.h / 2, "<"), (r.right - r.h / 2, ">")):
            a = f.render(ch, True, ACCENT)
            scr.blit(a, a.get_rect(center=(sx, r.centery)))

    def draw_slider(self, r):
        scr, R = self.screen, self.renderer
        pygame.draw.rect(scr, (242, 244, 239), r, border_radius=10)
        x0, x1, ty = self.slider_track(r)
        f = R.font(int(r.h * 0.36))
        lab = f.render("Speed", True, MUTED)
        scr.blit(lab, lab.get_rect(midleft=(r.x + 14, ty)))
        v = self.settings["speed"]
        rate = f.render(f"{1000 / speed_ms(v):.1f} cells/s", True, INK)
        scr.blit(rate, rate.get_rect(midright=(r.right - 14, ty)))
        th = max(4, int(r.h * 0.09))
        pygame.draw.rect(scr, (205, 211, 199), (x0, ty - th / 2, x1 - x0, th), border_radius=th)
        kx = x0 + (x1 - x0) * v
        pygame.draw.rect(scr, ACCENT, (x0, ty - th / 2, kx - x0, th), border_radius=th)
        small = R.font(int(r.h * 0.3), False)
        for pos, name, _ms in SPEED_TICKS:  # little dashes with their labels
            x = x0 + (x1 - x0) * pos
            pygame.draw.line(scr, MUTED, (x, ty + th), (x, ty + th + r.h * 0.14), max(2, th // 2))
            t = small.render(name, True, INK if abs(v - pos) < 1e-6 else MUTED)
            scr.blit(t, t.get_rect(midtop=(x, ty + th + r.h * 0.17)))
        knob = r.h * 0.2
        render.aa_disc(scr, WHITE, kx, ty, knob + 2)
        render.aa_disc(scr, ACCENT, kx, ty, knob)

    # ---- packs & mods ---------------------------------------------------------------

    def pack_by_id(self):
        return {pk.id: pk for pk in self.ad_packs}

    def apply_packs(self):
        """Rebuild the active assets from the enabled packs (top of the list wins)."""
        known = self.pack_by_id()
        enabled = [known[i].path for i in self.settings["packs"] if i in known]
        self.pack = AssetPack([self.assets_dir, os.environ.get("OPENSNAKE_ASSETS")] + enabled)
        render.apply_pack_colors(self.pack)
        self.renderer = Renderer(self.pack)
        self.sfx = Sfx(self.pack)
        self.sfx.muted = self.settings["muted"]
        self.icon_cache.clear()

    def open_online(self):
        self.state = "online"
        self.online.focus = None
        if self.online.server_state in ("ok", "no-server", "error") and self.online.server:
            self.online.fetch_records()

    def open_addons(self):
        self.ad_packs = discover_packs()  # pick up packs dropped in since last time
        self.state = "addons"

    def pack_rows(self):
        """Enabled packs in priority order, then the rest."""
        known = self.pack_by_id()
        enabled = [known[i] for i in self.settings["packs"] if i in known]
        return enabled + [pk for pk in self.ad_packs if pk.id not in self.settings["packs"]]

    def mod_rows(self):
        """Every mod found, with its status: loaded, failed, off, or waiting for a restart."""
        results = dict(MOD_RESULTS)
        disabled = set(self.settings["mods_disabled"])
        rows = []
        for name, path, _folder, _pkg in iter_mods(self.mod_dir_list):
            on = name not in disabled
            was_on = name not in self.mods_disabled_at_start
            if on != was_on:
                status = "on after restart" if on else "off after restart"
            elif not on:
                status = "off"
            elif name in results and results[name]:
                status = "failed: " + results[name]
            elif name in results:
                status = "loaded"
            else:
                status = "on after restart"
            rows.append({"name": name, "desc": describe_mod(path), "on": on, "status": status})
        return rows

    def mods_changed(self) -> bool:
        return set(self.settings["mods_disabled"]) != self.mods_disabled_at_start

    def toggle_pack(self, pack_id):
        packs = self.settings["packs"]
        if pack_id in packs:
            packs.remove(pack_id)
        else:
            packs.insert(0, pack_id)  # newly enabled packs go on top, like Minecraft
        self.store.save()
        self.apply_packs()
        self.ad_row[0] = next(i for i, pk in enumerate(self.pack_rows()) if pk.id == pack_id)

    def move_pack(self, pack_id, step):
        packs = self.settings["packs"]
        if pack_id not in packs:
            return
        i = packs.index(pack_id)
        j = min(len(packs) - 1, max(0, i + step))
        packs[i], packs[j] = packs[j], packs[i]
        self.store.save()
        self.apply_packs()
        self.ad_row[0] = j

    def toggle_mod(self, name):
        disabled = self.settings["mods_disabled"]
        if name in disabled:
            disabled.remove(name)
        else:
            disabled.append(name)
        self.store.save()

    def addons_key(self, ev):
        rows = [self.pack_rows(), self.mod_rows()]
        col = self.ad_col
        n = len(rows[col])
        shift = ev.mod & pygame.KMOD_SHIFT
        if ev.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
            self.open_menu()
        elif ev.key in (pygame.K_LEFT, pygame.K_a, pygame.K_RIGHT, pygame.K_d, pygame.K_TAB):
            self.ad_col = 1 - col
        elif n == 0:
            return
        elif ev.key in (pygame.K_UP, pygame.K_w, pygame.K_DOWN, pygame.K_s):
            step = -1 if ev.key in (pygame.K_UP, pygame.K_w) else 1
            if shift and col == 0:
                self.move_pack(rows[0][self.ad_row[0]].id, step)
            else:
                self.ad_row[col] = (self.ad_row[col] + step) % n
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            if col == 0:
                self.toggle_pack(rows[0][self.ad_row[0]].id)
            else:
                self.toggle_mod(rows[1][self.ad_row[1]]["name"])
        elif ev.key == pygame.K_o and not WEB:
            open_folder(user_packs_dir() if col == 0 else user_mods_dir())

    def _switch(self, rect, on):
        """Draw an on/off toggle switch."""
        scr = self.screen
        pygame.draw.rect(scr, ACCENT if on else (190, 196, 184), rect, border_radius=rect.h // 2)
        r = rect.h // 2 - 3
        cx = rect.right - rect.h // 2 if on else rect.x + rect.h // 2
        render.aa_disc(scr, WHITE, cx, rect.centery, r)

    def _icon(self, path, size):
        key = ("addon-icon", str(path), size)
        if key not in self.icon_cache:
            self.icon_cache[key] = load_image(path, size) if path else None
        return self.icon_cache[key]

    def draw_addons(self):
        """Packs & Mods screen: two lists with on/off switches."""
        scr, R = self.screen, self.renderer
        shade = pygame.Surface(scr.get_size(), pygame.SRCALPHA)
        shade.fill((20, 35, 12, 150))
        scr.blit(shade, (0, 0))
        sw, sh = scr.get_size()
        grow = max(1.0, min(sw / DEFAULT_WINDOW[0], sh / DEFAULT_WINDOW[1]))
        pw, ph = min(sw - 40, round(940 * grow)), min(sh - 40, round(800 * grow))
        p = pygame.Rect((sw - pw) // 2, (sh - ph) // 2, pw, ph)
        pygame.draw.rect(scr, PANEL, p, border_radius=18)
        self.ad_hits = []

        title = R.font(int(ph * 0.07)).render("Packs & Mods", True, (74, 117, 44))
        scr.blit(title, title.get_rect(midtop=(p.centerx, p.y + int(ph * 0.025))))
        sub = R.font(int(ph * 0.026), False).render(
            "Resource packs change how the game looks and sounds. Mods add new modes.", True, MUTED)
        scr.blit(sub, sub.get_rect(midtop=(p.centerx, p.y + int(ph * 0.025) + title.get_height())))

        top = p.y + int(ph * 0.16)
        bottom = p.bottom - int(ph * 0.2)
        gap = 20
        col_w = (pw - 40 - gap) // 2
        row_h = max(44, int(ph * 0.085))
        head_f = R.font(int(ph * 0.03))
        name_f = R.font(int(row_h * 0.32))
        small_f = R.font(int(row_h * 0.24), False)

        def fit(img, width):
            if img.get_width() > width:
                return pygame.transform.smoothscale(img, (width, max(1, int(img.get_height() * width / img.get_width()))))
            return img

        packs, mods = self.pack_rows(), self.mod_rows()
        enabled = self.settings["packs"]
        for col, (label, items) in enumerate((("Resource packs", packs), ("Mods", mods))):
            x = p.x + 20 + col * (col_w + gap)
            hdr = head_f.render(label, True, INK)
            scr.blit(hdr, (x, top))
            note = "top of the list wins" if col == 0 else ("changes apply after a restart" if not WEB else "")
            if note:
                img = small_f.render(note, True, MUTED)
                scr.blit(img, img.get_rect(bottomright=(x + col_w, top + hdr.get_height())))
            y0 = top + hdr.get_height() + 8
            visible = max(1, (bottom - y0) // (row_h + 6))
            sel = min(self.ad_row[col], max(0, len(items) - 1))
            self.ad_row[col] = sel
            first = min(max(0, sel - visible + 1), max(0, len(items) - visible))
            if not items:
                msg = ("No packs found." if col == 0 else
                       "Mods aren't available in the browser version." if WEB else
                       "No mods installed. Put .py mods in the mods folder.")
                img = small_f.render(msg, True, MUTED)
                scr.blit(img, (x + 4, y0 + 8))
            for row, i in enumerate(range(first, min(len(items), first + visible))):
                item = items[i]
                r = pygame.Rect(x, y0 + row * (row_h + 6), col_w, row_h)
                focus = self.ad_col == col and i == sel
                on = (item.id in enabled) if col == 0 else item["on"]
                pygame.draw.rect(scr, (226, 238, 255) if focus else (244, 246, 241), r, border_radius=10)
                if focus:
                    pygame.draw.rect(scr, (255, 170, 0), r, 3, border_radius=10)
                ic = row_h - 12
                if col == 0:
                    icon = self._icon(item.icon or Path(__file__).parent / "images" / "opensnake.svg", ic)
                    if icon:
                        scr.blit(icon, (r.x + 6, r.y + 6))
                    name = item.name + ("  (built in)" if item.builtin else "")
                    desc = item.description or str(item.path)
                    status = f"#{enabled.index(item.id) + 1}" if on else ""
                else:
                    pygame.draw.rect(scr, (205, 214, 196), (r.x + 6, r.y + 6, ic, ic), border_radius=8)
                    img = R.font(int(ic * 0.5)).render("M", True, INK)
                    scr.blit(img, img.get_rect(center=(r.x + 6 + ic / 2, r.y + 6 + ic / 2)))
                    name, desc, status = item["name"], item["desc"] or "(no description)", item["status"]
                tx = r.x + ic + 16
                switch = pygame.Rect(0, 0, int(row_h * 0.8), int(row_h * 0.42))
                switch.midright = (r.right - 10, r.centery)
                room = switch.x - tx - 10
                arrows = col == 0 and on
                if arrows:
                    room -= int(row_h * 0.6)
                scr.blit(fit(name_f.render(name, True, INK), room), (tx, r.y + row_h * 0.12))
                status_col = BAD if status.startswith("failed") else MUTED
                line = desc if col == 0 else f"{status}  -  {desc}"
                scr.blit(fit(small_f.render(line, True, status_col if col == 1 else MUTED), room),
                         (tx, r.y + row_h * 0.56))
                self._switch(switch, on)
                if col == 0:
                    self.ad_hits.append((switch.inflate(8, 8), lambda pid=item.id: self.toggle_pack(pid)))
                    if status:
                        img = small_f.render(status, True, ACCENT)
                        scr.blit(img, img.get_rect(midright=(switch.x - 6, r.y + row_h * 0.3)))
                else:
                    self.ad_hits.append((switch.inflate(8, 8), lambda n=item["name"]: self.toggle_mod(n)))
                if arrows:  # priority buttons
                    aw = int(row_h * 0.42)
                    for k, (sym, step) in enumerate((("^", -1), ("v", 1))):
                        b = pygame.Rect(switch.x - 8 - aw * (2 - k) - 4 * (1 - k), r.centery + 2, aw, aw - 6)
                        pygame.draw.rect(scr, (232, 236, 228), b, border_radius=5)
                        img = small_f.render(sym, True, INK)
                        scr.blit(img, img.get_rect(center=b.center))
                        self.ad_hits.append((b, lambda pid=item.id, st=step: self.move_pack(pid, st)))
                self.ad_hits.append((r, lambda c=col, idx=i: self._select(c, idx)))
            if len(items) > visible:
                img = small_f.render(f"{first + 1}-{first + visible} of {len(items)}", True, MUTED)
                scr.blit(img, img.get_rect(topright=(x + col_w, y0 + visible * (row_h + 6))))

        # buttons
        bh = max(34, int(ph * 0.055))
        buttons = []
        if not WEB:
            buttons += [("Open packs folder", lambda: open_folder(user_packs_dir()), False),
                        ("Open mods folder", lambda: open_folder(user_mods_dir()), False)]
            if self.mods_changed():
                buttons.append(("Restart now", self.restart_game, True))
        buttons.append(("Done", self.open_menu, not self.mods_changed() or WEB))
        bw = min(int(220 * grow), (pw - 40) // len(buttons) - 14)
        bx = p.centerx - (len(buttons) * (bw + 14) - 14) // 2
        by = p.bottom - int(ph * 0.05) - bh
        for k, (text, action, primary) in enumerate(buttons):
            b = pygame.Rect(bx + k * (bw + 14), by, bw, bh)
            pygame.draw.rect(scr, ACCENT if primary else (232, 236, 228), b, border_radius=bh // 2)
            img = fit(R.font(int(bh * 0.45)).render(text, True, WHITE if primary else INK), bw - 16)
            scr.blit(img, img.get_rect(center=b.center))
            self.ad_hits.append((b, action))
        if self.mods_changed():
            msg = "Mod changes take effect after a restart." + ("" if WEB else " Press Restart now.")
            img = R.font(int(ph * 0.028)).render(msg, True, BAD)
            scr.blit(img, img.get_rect(midbottom=(p.centerx, by - 8)))
        hint = ("Up/Down: choose   Left/Right: switch list   Enter: on/off   Shift+Up/Down: pack priority"
                + ("" if WEB else "   O: open folder") + "   Esc: back")
        img = fit(R.font(int(ph * 0.022), False).render(hint, True, MUTED), pw - 20)
        scr.blit(img, img.get_rect(midbottom=(p.centerx, p.bottom - 8)))

    def _select(self, col, idx):
        self.ad_col = col
        self.ad_row[col] = idx

    def restart_game(self):
        self.store.save()
        pygame.quit()
        restart_program()

    # ---- speedrun ------------------------------------------------------------------

    def speedrun_key(self, ev):
        cats = self.all_categories()
        n = len(cats)
        if ev.key != pygame.K_DELETE:
            self.sr_delete = None
        if ev.key in (pygame.K_UP, pygame.K_w):
            self.sr_focus = (self.sr_focus - 1) % n
        elif ev.key in (pygame.K_DOWN, pygame.K_s):
            self.sr_focus = (self.sr_focus + 1) % n
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            self.start_run(cats[self.sr_focus])
        elif ev.key == pygame.K_a and ev.mod & pygame.KMOD_CTRL or ev.key == pygame.K_INSERT:
            self.add_custom_category()
        elif ev.key == pygame.K_DELETE and cats[self.sr_focus].custom:
            cid = cats[self.sr_focus].id
            if self.sr_delete == cid:
                self.delete_custom_category(cid)
            else:
                self.sr_delete = cid  # press Delete again to confirm
        elif ev.key == pygame.K_ESCAPE:
            self.open_menu()

    def sr_hit(self, pos):
        for i, r in self.sr_rows:
            if r.collidepoint(pos):
                return i
        return None

    def wr_text(self, category_id: str) -> tuple[str, str]:
        rec = self.records.get(category_id)
        if not rec:
            return "--", ""
        return format_time(rec["time_ms"]), str(rec.get("player", ""))[:24]

    def draw_speedrun(self):
        """Category picker: built-in and saved custom categories, with PB and WR."""
        scr, R = self.screen, self.renderer
        shade = pygame.Surface(scr.get_size(), pygame.SRCALPHA)
        shade.fill((20, 35, 12, 150))
        scr.blit(shade, (0, 0))
        sw, sh = scr.get_size()
        grow = max(1.0, min(sw / DEFAULT_WINDOW[0], sh / DEFAULT_WINDOW[1]))
        pw, ph = min(sw - 40, round(940 * grow)), min(sh - 40, round(800 * grow))
        p = pygame.Rect((sw - pw) // 2, (sh - ph) // 2, pw, ph)
        pygame.draw.rect(scr, PANEL, p, border_radius=18)

        title = R.font(int(ph * 0.07)).render("Speedrun", True, (74, 117, 44))
        scr.blit(title, title.get_rect(midtop=(p.centerx, p.y + int(ph * 0.025))))
        sub = R.font(int(ph * 0.028), False).render(
            "Pick a category. Times are in-game time, so frame rate doesn't matter.", True, MUTED)
        scr.blit(sub, sub.get_rect(midtop=(p.centerx, p.y + int(ph * 0.025) + title.get_height())))

        cols = [("Category", 0.04), ("Goal", 0.36), ("Board", 0.52), ("Your PB", 0.68), ("World record", 0.83)]
        top = p.y + int(ph * 0.17)
        head_f = R.font(int(ph * 0.026))
        for label, fx in cols:
            img = head_f.render(label, True, MUTED)
            scr.blit(img, (p.x + pw * fx, top))
        top += head_f.get_height() + 8
        bottom = p.bottom - int(ph * 0.17)
        cats = self.all_categories()
        row_h = min((bottom - top) // len(CATEGORIES), int(54 * grow))
        visible = max(1, (bottom - top) // row_h)
        # keep the selected row on screen
        self.sr_focus = min(self.sr_focus, len(cats) - 1)
        if self.sr_focus < self.sr_scroll:
            self.sr_scroll = self.sr_focus
        elif self.sr_focus >= self.sr_scroll + visible:
            self.sr_scroll = self.sr_focus - visible + 1
        self.sr_scroll = max(0, min(self.sr_scroll, len(cats) - visible))
        name_f = R.font(int(row_h * 0.46))
        text_f = R.font(int(row_h * 0.38), False)
        small_f = R.font(int(row_h * 0.3), False)
        self.sr_rows = []
        for row, i in enumerate(range(self.sr_scroll, min(len(cats), self.sr_scroll + visible))):
            cat = cats[i]
            r = pygame.Rect(p.x + 14, top + row * row_h, pw - 28, row_h - 4)
            self.sr_rows.append((i, r))
            focus = i == self.sr_focus
            base = (235, 243, 228) if cat.custom else (244, 246, 241)
            pygame.draw.rect(scr, (226, 238, 255) if focus else base, r, border_radius=10)
            if focus:
                pygame.draw.rect(scr, (255, 170, 0), r, 3, border_radius=10)
            cy = r.centery
            img = name_f.render(cat.name, True, INK)
            if img.get_width() > pw * 0.31:
                img = text_f.render(cat.name, True, INK)
            scr.blit(img, img.get_rect(midleft=(p.x + pw * 0.04, cy - (row_h * 0.1 if cat.custom else 0))))
            if cat.custom:
                tag = small_f.render(f"custom  {1000 / cat.tick_ms:.1f} cells/s", True, MUTED)
                scr.blit(tag, tag.get_rect(midleft=(p.x + pw * 0.04, cy + row_h * 0.24)))
            img = text_f.render(cat.goal_text, True, INK)
            scr.blit(img, img.get_rect(midleft=(p.x + pw * 0.36, cy)))
            modes = mode_label(cat.modes).replace("Blender: ", "") if cat.modes else ""
            board = f"{cat.w} x {cat.h}" + (f"  {modes}" if modes else "")
            img = text_f.render(board, True, INK)
            room = int(pw * 0.15)
            if img.get_width() > room:
                img = small_f.render(board, True, INK)
            if img.get_width() > room:  # still too long: squeeze to fit the column
                img = pygame.transform.smoothscale(img, (room, img.get_height()))
            scr.blit(img, img.get_rect(midleft=(p.x + pw * 0.52, cy)))
            pb = self.store.pb(cat.id)
            img = text_f.render(format_time(pb["time_ms"]) if pb else "--", True, INK)
            scr.blit(img, img.get_rect(midleft=(p.x + pw * 0.68, cy)))
            wr_time, wr_player = self.wr_text(cat.id)
            img = text_f.render(wr_time, True, INK)
            scr.blit(img, img.get_rect(midleft=(p.x + pw * 0.83, cy - (row_h * 0.12 if wr_player else 0))))
            if wr_player:
                img = small_f.render(wr_player, True, MUTED)
                scr.blit(img, img.get_rect(midleft=(p.x + pw * 0.83, cy + row_h * 0.22)))
        if len(cats) > visible:  # scroll position
            more = small_f.render(f"{self.sr_scroll + 1}-{self.sr_scroll + len(self.sr_rows)} of {len(cats)}"
                                  "   (scroll for more)", True, MUTED)
            scr.blit(more, more.get_rect(topright=(p.right - 18, top + visible * row_h)))

        cat = cats[self.sr_focus]
        if self.sr_delete == cat.id:
            line, color = f"Press Delete again to remove \"{cat.name}\" (its PB is kept).", BAD
        else:
            line, color = cat.desc, INK
        d = R.font(int(ph * 0.03), False).render(line, True, color)
        if d.get_width() > pw - 40:
            d = pygame.transform.smoothscale(d, (pw - 40, int(d.get_height() * (pw - 40) / d.get_width())))
        scr.blit(d, d.get_rect(center=(p.centerx, bottom + int(ph * 0.035))))

        bh = max(34, int(ph * 0.055))
        self.sr_back = pygame.Rect(0, 0, int(140 * grow), bh)
        self.sr_add = pygame.Rect(0, 0, int(250 * grow), bh)
        gap = 16
        total = self.sr_back.w + gap + self.sr_add.w
        self.sr_back.bottomleft = (p.centerx - total // 2, p.bottom - int(ph * 0.045))
        self.sr_add.bottomleft = (self.sr_back.right + gap, self.sr_back.bottom)
        for rect, text, primary in ((self.sr_back, "Back", False), (self.sr_add, "+ Add my settings", True)):
            pygame.draw.rect(scr, ACCENT if primary else (232, 236, 228), rect, border_radius=bh // 2)
            img = R.font(int(bh * 0.48)).render(text, True, WHITE if primary else INK)
            scr.blit(img, img.get_rect(center=rect.center))
        src = {"online": "updated online", "cached": "saved from online", "bundled": "built in"}.get(
            self.records.source, "none")
        hint = R.font(int(ph * 0.022), False).render(
            "Up/Down: choose   Enter: start   Insert: add my settings   Delete: remove custom   Esc: back"
            f"      World records: {src}" + (f" ({self.records.updated})" if self.records.updated else ""),
            True, MUTED)
        if hint.get_width() > pw - 20:
            hint = pygame.transform.smoothscale(hint, (pw - 20, int(hint.get_height() * (pw - 20) / hint.get_width())))
        scr.blit(hint, hint.get_rect(midbottom=(p.centerx, p.bottom - 8)))

    def draw_run_header(self, hh):
        """Speedrun HUD: live timer, progress, split vs PB, PB and WR."""
        scr, R, run = self.screen, self.renderer, self.attempt
        cat, g = run.category, run.game
        live = run.elapsed
        if g.started and not g.over and not self.paused:
            live += min(self.acc, run.tick_ms)
        big = R.font(int(hh * 0.62))
        img = big.render(format_time(live), True, WHITE)
        scr.blit(img, img.get_rect(midleft=(16, hh // 2)))
        x = 16 + big.size("0:00.000")[0] + 28
        ic = int(hh * 0.62)
        scr.blit(R.sprites.get("fruit", ic, "apple"), (x, (hh - ic) // 2))
        mid = R.font(int(hh * 0.46))
        progress = f"{g.score}/{cat.goal}" if cat.goal else f"{len(g.snakes[0].body)}/{g.w * g.h} cells"
        img = mid.render(progress, True, WHITE)
        scr.blit(img, img.get_rect(midleft=(x + ic + 8, hh // 2)))
        x += ic + 8 + img.get_width() + 24
        pb = self.store.pb(cat.id)
        k = len(run.splits)
        if pb and k and len(pb.get("splits_ms", [])) >= k:
            delta = run.splits[-1] - pb["splits_ms"][k - 1]
            img = mid.render(format_delta(delta), True, GOOD if delta < 0 else BAD)
            box = img.get_rect(midleft=(x, hh // 2)).inflate(12, 4)
            pygame.draw.rect(scr, (255, 255, 255), box, border_radius=box.h // 2)
            scr.blit(img, img.get_rect(center=box.center))
        small = R.font(int(hh * 0.34), False)
        wr_time, wr_player = self.wr_text(cat.id)
        right = (f"{cat.name}    PB {format_time(pb['time_ms']) if pb else '--'}    WR {wr_time}"
                 + (f" ({wr_player})" if wr_player else "") + "    R: restart")
        img = small.render(right, True, (220, 236, 200))
        scr.blit(img, img.get_rect(midright=(scr.get_width() - 16, hh // 2)))

    def back_label(self) -> str:
        return "Menu" if self.attempt_origin == "menu" else "Categories"

    def run_overlay(self, card):
        g, run, res = self.game, self.attempt, self.run_result
        cat = run.category
        pb = self.store.pb(cat.id)
        wr = self.records.get(cat.id)
        if g.over and self.over_panel_ready() and res:
            if res["finished"]:
                t = res["time"]
                lines = [("New PB!" if res["new_pb"] else "Finished", 1.0, (230, 120, 0) if res["new_pb"] else INK),
                         (format_time(t), 1.5, INK)]
                compare = []
                if res["pb_before"] is not None:
                    compare.append(f"PB {format_time(res['pb_before'])} ({format_delta(t - res['pb_before'])})")
                if wr:
                    compare.append(f"WR {format_time(wr['time_ms'])} ({format_delta(t - wr['time_ms'])})")
                lines.append(("   ".join(compare) or "First finish: that's your PB", 0.55, MUTED))
                if res.get("online"):
                    lines.append((res["online"][0], 0.5, res["online"][1]))
                if wr and round(t) < wr["time_ms"]:
                    lines.append(("Faster than the world record! Submit your run file.", 0.5, GOOD))
                elif not wr:
                    lines.append(("No world record yet. Submit your run file to set one.", 0.5, MUTED))
            else:
                goal = f"{res['score']}/{cat.goal}" if cat.goal else f"{len(g.snakes[0].body)} cells"
                lines = [("Run over", 1.0, INK), (f"{goal} at {format_time(res['time'])}", 0.7, MUTED)]
            card(lines, [("Retry (R)", self.restart, True), (self.back_label(), self.leave_run, False)])
        elif self.paused:
            card([("Paused", 1.2, INK), ("The timer only counts moves, so pausing costs nothing.", 0.5, MUTED)],
                 [("Resume", self.unpause, True), (self.back_label(), self.leave_run, False)])
        elif not g.started:
            wr_time, wr_player = self.wr_text(cat.id)
            card([(cat.name, 1.1, INK), (cat.desc, 0.5, MUTED),
                  (f"PB {format_time(pb['time_ms']) if pb else '--'}     WR {wr_time}"
                   + (f" ({wr_player})" if wr_player else ""), 0.6, INK),
                  ("Press an arrow key to start. R restarts any time.", 0.5, MUTED)])

    # ---- play --------------------------------------------------------------------

    def update(self, dt):
        self.online.poll()
        if self.state == "versus":  # the server runs the match; just animate towards its next state
            self.acc = min(self.acc + dt, self.tick_ms())
            self.drain()
            return
        g = self.game
        if g is None:
            self.new_game()
            g = self.game
        if self.state != "play" or self.paused or not g.started or g.over:
            self.drain()
            return
        self.acc += dt * self.turn_boost()
        while self.acc >= (ms := self.tick_ms()):
            self.acc -= ms
            (self.attempt or g).step()
            self.drain()
            if g.over:
                break
        if self.acc >= ms / 2:
            g.plan()  # head is entering its cell: lock the turn so it can curve

    def drain(self):
        g = self.game
        R = self.renderer
        for ev in g.events:
            self.sfx.play(ev.type)
            if ev.type == "eat":
                R.burst(ev.x, ev.y, FRUIT_COLORS.get(ev.fruit, (231, 71, 29)))
            elif ev.type == "portal":
                R.burst(ev.x, ev.y, (0, 162, 255), 18)
            elif ev.type == "poison":
                R.burst(ev.x, ev.y, (125, 47, 191), 18)
            elif ev.type == "shield":
                R.burst(ev.x, ev.y, (47, 128, 237), 20)
            elif self.state == "versus":
                if ev.type == "die":  # someone was knocked out
                    R.burst(ev.x, ev.y, (90, 90, 90), 22)
                    if ev.snake == self.online.you:
                        R.shake = R.c * 0.4
            elif ev.type in ("die", "win"):
                R.shake = R.c * 0.4 if ev.type == "die" else 0
                self.over_at = pygame.time.get_ticks()
                if self.attempt:
                    self.finish_run()
                else:
                    self.record_score()
        g.events.clear()

    def over_panel_ready(self):
        delay = 250 if self.attempt else 700  # speedrunners want to retry fast
        return self.over_at is not None and pygame.time.get_ticks() - self.over_at > delay

    def draw_header(self):
        scr = self.screen
        R = self.renderer
        hh = self.header_h()
        scr.fill(render.HEADER, (0, 0, scr.get_width(), hh))
        if self.state == "versus" and self.online.game:
            self.online.draw_header(hh)
            return
        if self.attempt:
            self.draw_run_header(hh)
            return
        ic = int(hh * 0.7)
        y = (hh - ic) // 2
        apple = R.sprites.get("fruit", ic, self.settings["fruit"] if self.settings["fruit"] != "mixed" else "apple")
        scr.blit(apple, (16, y))
        f = R.font(int(hh * 0.62))
        sc = f.render(str(self.game.score), True, WHITE)
        scr.blit(sc, sc.get_rect(midleft=(16 + ic + 8, hh // 2)))
        tx = 16 + ic + 8 + max(sc.get_width(), f.size("000")[0]) + 24
        cup = R.sprites.image("trophy", ic)
        if cup:
            scr.blit(cup, (tx, y))
        else:
            trophy(scr, tx, y, ic)
        best = f.render(str(max(self.best(), self.game.score if not self.recorded else 0)), True, WHITE)
        scr.blit(best, best.get_rect(midleft=(tx + ic + 8, hh // 2)))
        small = R.font(int(hh * 0.36), False)
        lab = small.render(mode_label(self.settings["modes"]), True, (220, 236, 200))
        hint = small.render("Esc: pause/menu   M: " + ("unmute" if self.settings["muted"] else "mute"), True,
                            (190, 214, 170))
        scr.blit(hint, hint.get_rect(midright=(scr.get_width() - 16, hh // 2)))
        room = scr.get_width() - 32 - hint.get_width() - (best.get_rect().w + tx + ic + 40)
        if room > 80:
            if lab.get_width() > room:
                lab = pygame.transform.smoothscale(lab, (room, int(lab.get_height() * room / lab.get_width())))
            scr.blit(lab, lab.get_rect(center=(tx + ic + 40 + best.get_width() + room // 2, hh // 2)))

    def draw_overlay(self, rect):
        g = self.game
        R = self.renderer
        scr = self.screen
        self.buttons = []
        if self.state not in ("play", "versus"):
            return

        def card(lines, buttons=()):
            w = min(rect.w - 20, max(320, int(rect.w * 0.55)))
            line_h = int(min(rect.h, rect.w) * 0.075)
            h = 30 + line_h * len(lines) + (line_h * 1.4 + 10 if buttons else 0) + 20
            box = pygame.Rect(0, 0, w, h)
            box.center = rect.center
            surf = pygame.Surface(box.size, pygame.SRCALPHA)
            pygame.draw.rect(surf, (255, 255, 255, 235), surf.get_rect(), border_radius=16)
            scr.blit(surf, box)
            y = box.y + 22
            for text, size, color in lines:
                img = R.font(int(line_h * size)).render(text, True, color)
                if img.get_width() > w - 30:
                    img = pygame.transform.smoothscale(
                        img, (w - 30, max(1, int(img.get_height() * (w - 30) / img.get_width()))))
                scr.blit(img, img.get_rect(midtop=(box.centerx, y)))
                y += line_h
            if buttons:
                bw = (w - 60) // len(buttons)
                for i, (text, action, primary) in enumerate(buttons):
                    r = pygame.Rect(box.x + 20 + i * (bw + 20), y + 10, bw, int(line_h * 1.3))
                    pygame.draw.rect(scr, ACCENT if primary else (232, 236, 228), r, border_radius=r.h // 2)
                    img = R.font(int(r.h * 0.55)).render(text, True, WHITE if primary else INK)
                    scr.blit(img, img.get_rect(center=r.center))
                    self.buttons.append({"rect": r, "action": action})

        if self.state == "versus":
            self.online.draw_overlay(rect, card)
            return
        if self.attempt:
            self.run_overlay(card)
            return
        if g.over and self.over_panel_ready():
            lines = [("You win!" if g.won else "Game over", 1.2, INK),
                     (f"Score {g.score}    Best {self.best()}", 0.8, MUTED)]
            if self.new_best and g.score:
                lines.append(("New best!", 0.8, (230, 120, 0)))
            card(lines, [("Play again", self.restart, True), ("Menu", self.open_menu, False)])
        elif self.paused:
            card([("Paused", 1.2, INK), ("P / Space to resume, Esc for menu", 0.6, MUTED)],
                 [("Resume", self.unpause, True), ("Menu", self.open_menu, False)])
        elif not g.started:
            card([("Press an arrow key or WASD to start", 0.7, INK)])

    def unpause(self):
        self.paused = False

    def draw(self):
        scr = self.screen
        R = self.renderer
        scr.fill(render.BORDER)
        rect = self.board_rect()
        g = self.game
        ms = self.tick_ms()
        t = min(1.0, self.acc / ms) if g.started and not g.over and not self.paused else 1.0
        if self.paused:
            t = min(1.0, self.acc / ms)
        now = pygame.time.get_ticks()
        palette = SNAKE_COLORS[self.settings["color"]]
        palette = (self.pack.color("snake_head", palette[0]), self.pack.color("snake_tail", palette[1]))
        since = now - self.over_at if self.over_at is not None else None
        blink = g.over and not g.won and since is not None and since < 900 and (since // 150) % 2 == 1
        cam_x, cam_y = self.camera(rect, t)
        view = View(R.c, cam_x, cam_y, rect.w, rect.h, g.w, g.h, now)
        board = R.draw_board(g, t, now, palette, view, hide_snake=blink and self.state != "versus")
        if self.state == "versus":
            self.online.draw_labels(board, view)
        ox = oy = 0
        if R.shake > 0:
            ox, oy = random.uniform(-R.shake, R.shake), random.uniform(-R.shake, R.shake)
            R.shake = R.shake * 0.85 if R.shake > 0.5 else 0
        frame = tuple(int(c * 0.78) for c in render.BORDER)  # a shade darker than the border, follows packs
        pygame.draw.rect(scr, frame, rect.inflate(12, 12), border_radius=6)
        scr.blit(board, (rect.x + ox, rect.y + oy))
        self.draw_header()
        self.draw_overlay(rect)
        if self.state == "menu":
            self.draw_menu()
        elif self.state == "speedrun":
            self.draw_speedrun()
        elif self.state == "addons":
            self.draw_addons()
        elif self.state == "online":
            self.online.draw_online()
        elif self.state == "lobby":
            self.online.draw_lobby()
        elif self.state == "matches":
            self.online.draw_matches()

    def frame(self):
        dt = self.clock.tick(60 if WEB else 120)
        for ev in pygame.event.get():
            self.handle(ev)
        self.update(dt)
        self.draw()
        pygame.display.flip()

    def run(self):
        while self.running:
            self.frame()
        pygame.quit()

    async def run_async(self):
        """Main loop for the browser: hand control back to the page every frame."""
        while self.running:
            self.frame()
            await asyncio.sleep(0)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(prog="opensnake", description="OpenSnake desktop snake game")
    parser.add_argument("--assets", metavar="DIR", help="folder with an asset pack (images, sounds, pack.json)")
    parser.add_argument("--mods", metavar="DIR", help="extra folder to load mods from")
    parser.add_argument("--verify", metavar="RUN.json", help="replay a saved speedrun and check its time, then exit")
    args = parser.parse_args(argv)
    if args.verify:
        raise SystemExit(verify_file(args.verify))
    App(args.assets, args.mods).run()


def verify_file(path: str) -> int:
    """Print whether a saved speedrun is valid. Returns a process exit code."""
    from .speedrun import verify
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        print(f"Could not read {path}: {e}")
        return 2
    ok, message = verify(data)
    player = data.get("player") or "unknown player" if isinstance(data, dict) else ""
    print(("VALID   " if ok else "INVALID ") + message + (f" ({player})" if ok else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    main()
