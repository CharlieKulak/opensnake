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
from .modes import (DEFAULT_BOARD, DEFAULT_SPEED, FRUIT_LABELS, LEGACY_SIZES, LEGACY_SPEEDS,
                    MAX_BOARD, MIN_BOARD_H, MIN_BOARD_W, MODE_DESCS, MODES, SNAKE_COLORS, SPEED_TICKS,
                    blend_modes, mode_label, speed_ms, toggle_mode)
from .assets import AssetPack, config_dir
from .mods import default_dirs as mod_dirs
from .mods import load_mods
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
}

# Number fields: key -> (label, min, max)
MAX_FRUIT = 500
NUMBERS = {"apple_count": ("Count", 1, MAX_FRUIT),
           "board_w": ("Width", MIN_BOARD_W, MAX_BOARD), "board_h": ("Height", MIN_BOARD_H, MAX_BOARD)}

# Smallest cell size before a big board starts scrolling instead of shrinking.
MIN_CELL = 20

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
        for key, (_label, lo, hi) in NUMBERS.items():
            try:
                s[key] = min(hi, max(lo, int(s[key])))
            except (TypeError, ValueError):
                s[key] = DEFAULTS[key]

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"settings": self.settings, "best": self.best}, indent=2))
        except OSError:
            pass  # read-only home etc.; settings just won't persist

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
        self.mod_results = load_mods(mod_dirs(mods_dir))
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
        self.pack = AssetPack.default(assets_dir)
        render.apply_pack_colors(self.pack)
        self.renderer = Renderer(self.pack)
        self.sfx = Sfx(self.pack)
        self.sfx.muted = self.store.settings["muted"]
        self.state = "menu"
        self.paused = False
        self.acc = 0.0
        self.over_at = None  # ms when the game ended, to delay the panel
        self.focus = 0
        self.widgets: list[dict] = []
        self.buttons: list[dict] = []
        self.editing: dict | None = None  # number field being typed into
        self.dragging = False              # speed slider held with the mouse
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
        self.game = Game(s["board_w"], s["board_h"], s["modes"], s["apple_count"], s["fruit"])
        self.paused = False
        self.acc = 0.0
        self.over_at = None
        self.recorded = False
        self.new_best = False

    def play(self):
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
        hx, hy = head_position(g, t)
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
            else:
                self.play_key(ev)
        elif ev.type == pygame.MOUSEMOTION:
            if self.dragging:
                self.slide_to(ev.pos[0])
                return
            hit = self.hit(ev.pos)
            if hit is not None and self.state == "menu" and not self.editing:
                self.focus = hit
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            self.click(ev.pos)
        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1 and self.dragging:
            self.dragging = False
            self.store.save()

    def play_key(self, ev):
        g = self.game
        if ev.key in KEYMAP:
            if not g.over and not self.paused:
                was_started = g.started
                before = [len(s.queue) for s in g.snakes]
                g.input(KEYMAP[ev.key])
                if not was_started:
                    self.sfx.play("start")
                elif [len(s.queue) for s in g.snakes] != before:
                    self.sfx.play("turn")
            return
        if ev.key == pygame.K_ESCAPE:
            if g.started and not g.over and not self.paused:
                self.paused = True
            else:
                self.open_menu()
        elif ev.key in (pygame.K_p, pygame.K_SPACE, pygame.K_RETURN):
            if g.over and self.over_panel_ready():
                self.new_game()
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
        grid_h = int(ph * 0.38)
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
                (("num", "board_w"), ("num", "board_h"))]
        for row in grid:
            for x, (kind, key) in zip((lx, rx), row):
                widgets.append({"kind": kind, "key": key, "rect": pygame.Rect(x, y, ow, row_h)})
            y += row_h + 6
        slider_h = int(row_h * 1.6)
        widgets.append({"kind": "slider", "key": "speed", "rect": pygame.Rect(lx, y, ow * 2 + 20, slider_h)})
        bh = max(36, int(ph * 0.065))
        hint_h = int(ph * 0.024) + 16  # shortcut hint along the panel's bottom edge
        by = min(y + slider_h + 10, panel.bottom - hint_h - bh)
        bw = min(round(200 * grow), pw // 3 - 20)
        buttons = [("blender", "Blender"), ("play", "Play")] + ([] if WEB else [("quit", "Quit")])
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
            elif w["kind"] == "slider":
                self.draw_slider(r)
            else:
                primary = w["id"] == "play"
                bg = ACCENT if primary else (242, 244, 239)
                pygame.draw.rect(scr, bg, r, border_radius=r.h // 2)
                text = {"blender": "Blender", "play": "Play", "quit": "Quit"}[w["id"]]
                t = R.font(int(r.h * 0.55)).render(text, True, WHITE if primary else INK)
                scr.blit(t, t.get_rect(center=r.center))
            if is_focus:
                pygame.draw.rect(scr, (255, 170, 0), r.inflate(6, 6), 3, border_radius=14)

        if focused["kind"] == "mode":
            desc = MODE_DESCS[focused["id"]]
        elif focused.get("id") == "blender":
            desc = "Mix 2-4 random modes together."
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
            "Arrows: move   Enter: select   B: blender   F11: fullscreen" + mods_txt, True, MUTED)
        scr.blit(hint, hint.get_rect(midbottom=(p.centerx, p.bottom - 10)))

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

    # ---- play --------------------------------------------------------------------

    def update(self, dt):
        g = self.game
        if self.state != "play" or self.paused or not g.started or g.over:
            self.drain()
            return
        ms = speed_ms(self.settings["speed"])
        self.acc += dt
        while self.acc >= ms:
            self.acc -= ms
            g.step()
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
            elif ev.type in ("die", "win"):
                R.shake = R.c * 0.4 if ev.type == "die" else 0
                self.over_at = pygame.time.get_ticks()
                self.record_score()
        g.events.clear()

    def over_panel_ready(self):
        return self.over_at is not None and pygame.time.get_ticks() - self.over_at > 700

    def draw_header(self):
        scr = self.screen
        R = self.renderer
        hh = self.header_h()
        scr.fill(render.HEADER, (0, 0, scr.get_width(), hh))
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
        if self.state != "play":
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

        if g.over and self.over_panel_ready():
            lines = [("You win!" if g.won else "Game over", 1.2, INK),
                     (f"Score {g.score}    Best {self.best()}", 0.8, MUTED)]
            if self.new_best and g.score:
                lines.append(("New best!", 0.8, (230, 120, 0)))
            card(lines, [("Play again", self.new_game, True), ("Menu", self.open_menu, False)])
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
        ms = speed_ms(self.settings["speed"])
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
        board = R.draw_board(g, t, now, palette, view, hide_snake=blink)
        ox = oy = 0
        if R.shake > 0:
            ox, oy = random.uniform(-R.shake, R.shake), random.uniform(-R.shake, R.shake)
            R.shake = R.shake * 0.85 if R.shake > 0.5 else 0
        pygame.draw.rect(scr, (68, 110, 40), rect.inflate(12, 12), border_radius=6)
        scr.blit(board, (rect.x + ox, rect.y + oy))
        self.draw_header()
        self.draw_overlay(rect)
        if self.state == "menu":
            self.draw_menu()

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
    args = parser.parse_args(argv)
    App(args.assets, args.mods).run()


if __name__ == "__main__":
    main()
