"""All graphics, drawn procedurally with pygame. There are no image assets.

Sprites are drawn at SS x their final size and smooth-scaled down, which
gives clean anti-aliased edges from plain pygame.draw calls.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

import pygame
import pygame.gfxdraw

from . import modes
from .assets import load_image
from .game import DIRS
from .registry import MODE_HOOKS

SS = 4

LIGHT = (170, 215, 81)
DARK = (162, 209, 73)
SAND = (229, 194, 159)
SAND_DARK = (215, 184, 153)
BORDER = (87, 138, 52)
HEADER = (74, 117, 44)

FRUIT_COLORS = {
    "apple": (231, 71, 29), "orange": (245, 154, 27), "cherry": (200, 16, 46), "grape": (123, 63, 181),
    "strawberry": (232, 36, 60), "lemon": (255, 213, 46), "banana": (255, 217, 59),
}
PORTAL_COLORS = [(255, 122, 0), (0, 162, 255), (225, 59, 214), (255, 212, 0), (32, 201, 151), (255, 71, 87)]
MINE_NUMBER_COLORS = [None, (25, 118, 210), (56, 142, 60), (211, 47, 47), (123, 31, 162),
                      (255, 143, 0), (0, 151, 167), (66, 66, 66), (158, 158, 158)]
LEAF = (76, 175, 55)
STEM = (107, 68, 35)


def apply_pack_colors(pack) -> None:
    """Let an asset pack's pack.json recolour the board."""
    global LIGHT, DARK, SAND, SAND_DARK, BORDER, HEADER
    LIGHT = pack.color("board_light", LIGHT)
    DARK = pack.color("board_dark", DARK)
    SAND = pack.color("board_sand", SAND)
    SAND_DARK = pack.color("board_sand_dark", SAND_DARK)
    BORDER = pack.color("border", BORDER)
    HEADER = pack.color("header", HEADER)


def mix(c1, c2, t):
    return tuple(round(a + (b - a) * t) for a, b in zip(c1, c2))


def lighten(c, t=0.55):
    return mix(c, (255, 255, 255), t)


# ---- geometry helpers ---------------------------------------------------------

def bezier(p0, p1, p2, p3, n=14):
    out = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        out.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                    u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
    return out


def ellipse_poly(cx, cy, rx, ry, ang=0.0, n=32):
    ca, sa = math.cos(ang), math.sin(ang)
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        x, y = rx * math.cos(a), ry * math.sin(a)
        pts.append((cx + x * ca - y * sa, cy + x * sa + y * ca))
    return pts


def arc_band(cx, cy, r_out, r_in, a0, a1, n=28):
    outer = [(cx + r_out * math.cos(a0 + (a1 - a0) * i / n), cy + r_out * math.sin(a0 + (a1 - a0) * i / n))
             for i in range(n + 1)]
    inner = [(cx + r_in * math.cos(a0 + (a1 - a0) * i / n), cy + r_in * math.sin(a0 + (a1 - a0) * i / n))
             for i in range(n, -1, -1)]
    return outer + inner


def thick_line(s, color, a, b, w):
    pygame.draw.line(s, color, a, b, max(1, int(w)))
    for p in (a, b):
        pygame.draw.circle(s, color, p, w / 2)


def dashed_ring(s, color, cx, cy, r, w, dashes=10, fill=0.6):
    for i in range(dashes):
        a0 = 2 * math.pi * i / dashes
        a1 = a0 + 2 * math.pi / dashes * fill
        pygame.draw.polygon(s, color, arc_band(cx, cy, r + w / 2, r - w / 2, a0, a1, 6))


# ---- fruit -------------------------------------------------------------------

def leaf(s, x, y, r, ang):
    cx, cy = x + math.cos(ang) * r * 0.35, y + math.sin(ang) * r * 0.35
    pygame.draw.polygon(s, LEAF, ellipse_poly(cx, cy, r * 0.38, r * 0.17, ang))


def stem(s, x, y, r):
    pts = [(x, y)] + bezier((x, y), (x + r * 0.05, y - r * 0.15), (x + r * 0.1, y - r * 0.3), (x + r * 0.2, y - r * 0.45), 6)
    pygame.draw.lines(s, STEM, False, pts, max(2, int(r * 0.14)))


def shine(s, x, y, r, base):
    pygame.draw.polygon(s, lighten(base), ellipse_poly(x, y, r * 0.22, r * 0.13, -0.7))


def fruit_apple(s, x, y, r, color=FRUIT_COLORS["apple"]):
    top = (x, y - r * 0.55)
    pts = [top]
    pts += bezier(top, (x + r * 0.5, y - r * 0.95), (x + r * 1.1, y - r * 0.4), (x + r * 0.85, y + r * 0.3))
    pts += bezier(pts[-1], (x + r * 0.7, y + r * 0.85), (x + r * 0.3, y + r * 0.95), (x, y + r * 0.8))
    pts += bezier(pts[-1], (x - r * 0.3, y + r * 0.95), (x - r * 0.7, y + r * 0.85), (x - r * 0.85, y + r * 0.3))
    pts += bezier(pts[-1], (x - r * 1.1, y - r * 0.4), (x - r * 0.5, y - r * 0.95), top)
    pygame.draw.polygon(s, color, pts)
    shine(s, x - r * 0.4, y - r * 0.2, r, color)
    stem(s, x, y - r * 0.5, r)
    leaf(s, x + r * 0.08, y - r * 0.68, r, -0.5)


def fruit_orange(s, x, y, r):
    col = FRUIT_COLORS["orange"]
    pygame.draw.circle(s, col, (x, y + r * 0.08), r * 0.82)
    for dx, dy in ((0.3, 0.2), (-0.25, 0.4), (0.1, -0.2), (-0.35, -0.05), (0.4, -0.25)):
        pygame.draw.circle(s, mix(col, (150, 70, 0), 0.35), (x + dx * r, y + dy * r), r * 0.05)
    shine(s, x - r * 0.35, y - r * 0.2, r, col)
    leaf(s, x, y - r * 0.7, r, -0.4)


def fruit_cherry(s, x, y, r):
    green = (79, 122, 40)
    top = (x + r * 0.15, y - r * 0.8)
    for start, ctrl in (((x - r * 0.4, y + r * 0.2), (x - r * 0.1, y - r * 0.4)),
                        ((x + r * 0.42, y + r * 0.3), (x + r * 0.35, y - r * 0.3))):
        pygame.draw.lines(s, green, False, [start] + bezier(start, ctrl, ctrl, top, 8), max(2, int(r * 0.1)))
    col = FRUIT_COLORS["cherry"]
    for dx, dy in ((-0.42, 0.42), (0.42, 0.5)):
        pygame.draw.circle(s, col, (x + dx * r, y + dy * r), r * 0.4)
        shine(s, x + (dx - 0.15) * r, y + (dy - 0.12) * r, r * 0.5, col)
    leaf(s, top[0], top[1], r * 0.8, 0.2)


def fruit_grape(s, x, y, r):
    col = FRUIT_COLORS["grape"]
    pts = ((-0.4, -0.35), (0, -0.4), (0.4, -0.35), (-0.2, 0.05), (0.2, 0.05), (0, 0.45), (-0.45, 0.3), (0.45, 0.3))
    for dx, dy in pts:
        pygame.draw.circle(s, col, (x + dx * r, y + dy * r), r * 0.3)
        pygame.draw.circle(s, mix(col, (40, 10, 70), 0.4), (x + dx * r, y + dy * r), r * 0.3, max(1, int(r * 0.04)))
    for dx, dy in pts:
        pygame.draw.circle(s, lighten(col, 0.4), (x + (dx - 0.1) * r, y + (dy - 0.1) * r), r * 0.08)
    stem(s, x, y - r * 0.6, r * 0.8)
    leaf(s, x + r * 0.05, y - r * 0.75, r * 0.9, -0.3)


def fruit_strawberry(s, x, y, r):
    col = FRUIT_COLORS["strawberry"]
    a = (x - r * 0.8, y - r * 0.35)
    pts = [a]
    pts += bezier(a, (x - r * 0.9, y + r * 0.3), (x - r * 0.2, y + r * 0.9), (x, y + r * 0.9))
    pts += bezier(pts[-1], (x + r * 0.2, y + r * 0.9), (x + r * 0.9, y + r * 0.3), (x + r * 0.8, y - r * 0.35))
    pts += bezier(pts[-1], (x + r * 0.3, y - r * 0.6), (x - r * 0.3, y - r * 0.6), a)
    pygame.draw.polygon(s, col, pts)
    for dx, dy in ((-0.4, -0.05), (0, -0.1), (0.4, -0.05), (-0.2, 0.3), (0.2, 0.3), (0, 0.6)):
        pygame.draw.polygon(s, (255, 226, 138), ellipse_poly(x + dx * r, y + dy * r, r * 0.05, r * 0.08, 0, 12))
    cy = y - r * 0.45
    star = []
    for i in range(10):
        a = math.pi + i / 9 * math.pi
        rad = r * (0.55 if i % 2 == 0 else 0.22)
        star.append((x + math.cos(a) * rad, cy + math.sin(a) * rad * 0.7))
    star.append((x, cy + r * 0.12))
    pygame.draw.polygon(s, (63, 156, 47), star)


def fruit_lemon(s, x, y, r):
    col = FRUIT_COLORS["lemon"]
    pygame.draw.polygon(s, col, ellipse_poly(x, y, r * 0.88, r * 0.66, -0.35))
    pygame.draw.circle(s, col, (x + r * 0.78, y - r * 0.3), r * 0.13)
    shine(s, x - r * 0.35, y - r * 0.2, r, col)
    leaf(s, x - r * 0.62, y - r * 0.32, r * 0.8, -2.4)


def fruit_banana(s, x, y, r):
    cx, cy = x - r * 0.15, y - r * 0.5
    pygame.draw.polygon(s, (217, 163, 0), arc_band(cx, cy, r * 1.27, r * 0.65, 0.35, 2.55))
    pygame.draw.polygon(s, FRUIT_COLORS["banana"], arc_band(cx, cy, r * 1.17, r * 0.73, 0.4, 2.5))
    pygame.draw.circle(s, STEM, (cx + math.cos(0.35) * r * 0.96, cy + math.sin(0.35) * r * 0.96), r * 0.12)


FRUIT_DRAW = {
    "apple": fruit_apple, "orange": fruit_orange, "cherry": fruit_cherry, "grape": fruit_grape,
    "strawberry": fruit_strawberry, "lemon": fruit_lemon, "banana": fruit_banana,
}


def fruit_poison(s, x, y, r):
    fruit_apple(s, x, y, r, (125, 47, 191))
    w = max(2, int(r * 0.1))
    for ex in (-0.3, 0.3):
        pygame.draw.line(s, (27, 11, 42), (x + (ex - 0.1) * r, y + 0.05 * r), (x + (ex + 0.1) * r, y + 0.25 * r), w)
        pygame.draw.line(s, (27, 11, 42), (x + (ex + 0.1) * r, y + 0.05 * r), (x + (ex - 0.1) * r, y + 0.25 * r), w)
    pygame.draw.polygon(s, (126, 224, 74), ellipse_poly(x + r * 0.15, y + r * 0.85, r * 0.08, r * 0.14, 0, 12))


# ---- board objects (drawn into a full cell of size S) ---------------------------

def obj_wall(s, S):
    pad = S * 0.04
    pygame.draw.rect(s, (122, 79, 44), (pad, pad, S - 2 * pad, S - 2 * pad), border_radius=int(S * 0.14))
    bh = (S - 2 * pad) / 3
    brick = (160, 106, 59)
    for row in range(3):
        off = S * 0.25 if row % 2 else 0
        for col in range(-1, 2):
            bx = pad + off + col * S * 0.5 + S * 0.04
            x0, x1 = max(pad + S * 0.06, bx), min(S - pad - S * 0.06, bx + S * 0.42)
            if x1 > x0:
                pygame.draw.rect(s, brick, (x0, pad + row * bh + S * 0.04, x1 - x0, bh - S * 0.08),
                                 border_radius=int(S * 0.03))


def obj_statue(s, S):
    pygame.draw.rect(s, (154, 160, 166), (S * 0.08, S * 0.08, S * 0.84, S * 0.84), border_radius=int(S * 0.3))
    pygame.draw.circle(s, (195, 200, 204), (S * 0.35, S * 0.35), S * 0.12)
    pygame.draw.lines(s, (125, 132, 138), False, [(S * 0.55, S * 0.3), (S * 0.65, S * 0.5), (S * 0.58, S * 0.7)],
                      max(2, int(S * 0.04)))


def obj_gate_open(s, S):
    col = (125, 95, 60, 150)
    w = max(2, int(S * 0.06))
    a, b = S * 0.12, S * 0.88
    n = 4
    for i in range(n):
        t0, t1 = i / n, (i + 0.55) / n
        for (x0, y0, x1, y1) in ((a, a, b, a), (b, a, b, b), (b, b, a, b), (a, b, a, a)):
            pygame.draw.line(s, col, (x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0),
                             (x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1), w)


def obj_gate_closed(s, S):
    pygame.draw.rect(s, (93, 97, 104), (S * 0.08, S * 0.08, S * 0.84, S * 0.12))
    pygame.draw.rect(s, (93, 97, 104), (S * 0.08, S * 0.8, S * 0.84, S * 0.12))
    for i in range(4):
        pygame.draw.rect(s, (141, 147, 155), (S * (0.14 + i * 0.2), S * 0.1, S * 0.1, S * 0.8))


def obj_key(s, S, color):
    tmp = pygame.Surface((S, S), pygame.SRCALPHA)
    x, y, r = S / 2, S / 2, S * 0.4
    pygame.draw.circle(tmp, color, (x - r * 0.4, y), r * 0.32 + r * 0.11, max(2, int(r * 0.22)))
    pygame.draw.rect(tmp, color, (x - r * 0.1, y - r * 0.11, r * 0.95, r * 0.22))
    pygame.draw.rect(tmp, color, (x + r * 0.55, y, r * 0.14, r * 0.35))
    pygame.draw.rect(tmp, color, (x + r * 0.25, y, r * 0.14, r * 0.28))
    rot = pygame.transform.rotate(tmp, 34)
    s.blit(rot, rot.get_rect(center=(S / 2, S / 2)))


def obj_lock(s, S, color):
    x, y, r = S / 2, S / 2, S * 0.46
    pygame.draw.rect(s, (40, 40, 50, 120), (x - r, y - r, 2 * r, 2 * r), border_radius=int(r * 0.3))
    pygame.draw.circle(s, color, (x, y - r * 0.05), r * 0.38, max(2, int(r * 0.16)),
                       draw_top_left=True, draw_top_right=True)
    pygame.draw.rect(s, color, (x - r * 0.45, y - r * 0.05, r * 0.9, r * 0.65), border_radius=int(r * 0.1))
    pygame.draw.circle(s, (51, 51, 51), (x, y + r * 0.22), r * 0.09)


def obj_shield(s, S):
    x, y, r = S / 2, S / 2, S * 0.42
    outer = [(x, y - r * 0.75), (x + r * 0.65, y - r * 0.5)]
    outer += bezier(outer[-1], (x + r * 0.6, y + r * 0.1), (x + r * 0.5, y + r * 0.55), (x, y + r * 0.8))
    outer += bezier(outer[-1], (x - r * 0.5, y + r * 0.55), (x - r * 0.6, y + r * 0.1), (x - r * 0.65, y - r * 0.5))
    pygame.draw.polygon(s, (47, 128, 237), outer)
    inner = [(x, y - r * 0.5), (x + r * 0.4, y - r * 0.33)]
    inner += bezier(inner[-1], (x + r * 0.38, y + r * 0.1), (x + r * 0.3, y + r * 0.4), (x, y + r * 0.55))
    pygame.draw.polygon(s, (156, 198, 255), inner)


def obj_arrow(s, S, d):
    pygame.draw.rect(s, (255, 255, 255, 95), (S * 0.08, S * 0.08, S * 0.84, S * 0.84), border_radius=int(S * 0.18))
    ang = {"right": 0, "down": math.pi / 2, "left": math.pi, "up": -math.pi / 2}[d]
    shape = [(0.32, 0), (-0.02, -0.28), (-0.02, -0.11), (-0.3, -0.11), (-0.3, 0.11), (-0.02, 0.11), (-0.02, 0.28)]
    ca, sa = math.cos(ang), math.sin(ang)
    pts = [(S / 2 + (px * ca - py * sa) * S, S / 2 + (px * sa + py * ca) * S) for px, py in shape]
    pygame.draw.polygon(s, (232, 112, 26), pts)


def obj_target(s, S):
    dashed_ring(s, (255, 255, 255, 220), S / 2, S / 2, S * 0.38, S * 0.07, 9)
    pygame.draw.circle(s, (255, 255, 255, 130), (S / 2, S / 2), S * 0.1)


def obj_mine(s, S):
    x = y = S / 2
    r = S * 0.42
    for i in range(4):
        a = i * math.pi / 4
        pygame.draw.line(s, (34, 34, 34), (x + math.cos(a) * r * 0.7, y + math.sin(a) * r * 0.7),
                         (x - math.cos(a) * r * 0.7, y - math.sin(a) * r * 0.7), max(2, int(r * 0.14)))
    pygame.draw.circle(s, (34, 34, 34), (x, y), r * 0.48)
    pygame.draw.circle(s, (255, 255, 255), (x - r * 0.15, y - r * 0.15), r * 0.12)


def obj_ring(s, S, color):
    dashed_ring(s, color, S / 2, S / 2, S * 0.46, S * 0.08, 8)


def obj_fruit(s, S, fruit):
    (fruit_poison if fruit == "poison" else FRUIT_DRAW.get(fruit, fruit_apple))(s, S / 2, S / 2, S * 0.4)


OBJECTS = {
    "wall": obj_wall, "statue": obj_statue, "gate_open": obj_gate_open, "gate_closed": obj_gate_closed,
    "key": obj_key, "lock": obj_lock, "shield": obj_shield, "arrow": obj_arrow, "target": obj_target,
    "mine": obj_mine, "ring": obj_ring, "fruit": obj_fruit,
}


ARROW_ANGLES = {"right": 0, "up": 90, "left": 180, "down": -90}

# Bundled artwork (see CREDITS.md). Each file is named like its asset-pack
# override, e.g. fruit_apple.svg.
IMAGES = Path(__file__).parent / "images"

# How much of a cell each bundled image fills, so they don't touch edges.
IMAGE_FILL = {"fruit": 0.86, "key": 0.74, "lock": 0.56, "shield": 0.8, "mine": 0.8, "statue": 0.96}


def pack_name(name: str, args) -> str:
    """File name (without extension) an asset pack uses for a sprite."""
    if name == "fruit":
        return "fruit_" + args[0]
    return name


class Sprites:
    """Sprite cache. For each sprite, in order of preference: an asset pack
    image, a bundled image, or the procedural drawing in OBJECTS."""

    def __init__(self, pack=None):
        self.cache: dict = {}
        self.pack = pack

    def get(self, name: str, c: int, *args) -> pygame.Surface:
        key = (name, c, args)
        surf = self.cache.get(key)
        if surf is None:
            surf = self._from_image(name, c, args) or self._draw(name, c, args)
            self.cache[key] = surf
        return surf

    def _draw(self, name, c, args):
        big = pygame.Surface((c * SS, c * SS), pygame.SRCALPHA)
        OBJECTS[name](big, c * SS, *args)
        return pygame.transform.smoothscale(big, (c, c))

    def _pack_path(self, key):
        return self.pack.image_path(key) if self.pack else None

    def _bundled_path(self, key):
        p = IMAGES / (key + ".svg")
        return p if p.is_file() else None

    def image(self, key: str, size: int) -> pygame.Surface | None:
        """A pack or bundled image by file name at size x size, or None."""
        ck = ("image", key, size)
        if ck not in self.cache:
            path = self._pack_path(key) or self._bundled_path(key)
            self.cache[ck] = load_image(path, max(1, size)) if path else None
        return self.cache[ck]

    def _from_image(self, name, c, args):
        key = pack_name(name, args)
        path = self._pack_path(key)
        if path:  # pack art fills the whole cell, as documented
            surf = load_image(path, c)
            if surf and name == "arrow":  # pack arrows point right
                surf = pygame.transform.rotate(surf, ARROW_ANGLES[args[0]])
            return surf
        if key == "fruit_poison":
            return self._poison(c)
        path = self._bundled_path(key)
        if not path:
            return None
        img = load_image(path, max(1, int(c * IMAGE_FILL.get(name, 0.9))))
        if img is None:
            return None
        surf = pygame.Surface((c, c), pygame.SRCALPHA)
        if name == "key":  # coloured backdrop shows which lock it opens
            aa_disc(surf, (*args[0], 150), c / 2, c / 2, c * 0.46)
        elif name == "lock":
            pygame.draw.rect(surf, (40, 40, 50, 130), (0, 0, c, c), border_radius=int(c * 0.14))
            pygame.draw.rect(surf, args[0], (0, 0, c, c), max(2, c // 14), border_radius=int(c * 0.14))
        surf.blit(img, img.get_rect(center=(c / 2, c / 2)))
        return surf

    def _poison(self, c):
        """Purple-tinted apple with a skull badge, made from the bundled art."""
        size = max(1, int(c * IMAGE_FILL["fruit"]))
        apple = self.image("fruit_apple", size)
        if apple is None:
            return None
        tinted = pygame.transform.grayscale(apple)
        tinted.fill((70, 70, 70), special_flags=pygame.BLEND_RGB_ADD)
        tinted.fill((175, 105, 255), special_flags=pygame.BLEND_RGB_MULT)
        surf = pygame.Surface((c, c), pygame.SRCALPHA)
        surf.blit(tinted, tinted.get_rect(center=(c / 2, c / 2)))
        skull = self.image("skull", max(1, int(c * 0.5)))
        if skull:
            surf.blit(skull, skull.get_rect(bottomright=(c, c)))
        return surf

    def snake_head(self, c: int, dead: bool) -> pygame.Surface | None:
        """Optional pack image for the head, facing right."""
        path = (self._pack_path("snake_head_dead") if dead else None) or self._pack_path("snake_head")
        if not path:
            return None
        key = ("snake_head", c, str(path))
        if key not in self.cache:
            self.cache[key] = load_image(path, c)
        return self.cache[key]

    def ghost(self, name: str, c: int, alpha: int, *args) -> pygame.Surface:
        key = ("ghost", name, c, alpha, args)
        surf = self.cache.get(key)
        if surf is None:
            surf = self.get(name, c, *args).copy()
            surf.fill((255, 255, 255, alpha), special_flags=pygame.BLEND_RGBA_MULT)
            self.cache[key] = surf
        return surf


# ---- snake drawing -----------------------------------------------------------

def aa_disc(surf, color, x, y, r):
    xi, yi, ri = round(x), round(y), max(1, round(r))
    pygame.gfxdraw.aacircle(surf, xi, yi, ri, color)
    pygame.gfxdraw.filled_circle(surf, xi, yi, ri, color)


def band(surf, color, a, b, w):
    """Axis-aligned straight band between two centre points (square ends)."""
    r = w / 2
    x0, x1 = sorted((a[0], b[0]))
    y0, y1 = sorted((a[1], b[1]))
    if x1 - x0 >= y1 - y0:
        rect = pygame.Rect(round(x0), round(y0 - r), max(1, round(x1) - round(x0)), round(w))
    else:
        rect = pygame.Rect(round(x0 - r), round(y0), round(w), max(1, round(y1) - round(y0)))
    pygame.draw.rect(surf, color, rect)


def capsule(surf, color, a, b, w):
    """Axis-aligned segment with round ends."""
    band(surf, color, a, b, w)
    aa_disc(surf, color, a[0], a[1], w / 2)
    aa_disc(surf, color, b[0], b[1], w / 2)


def _step(a, b, w, h, wrap):
    """Direction of travel from cell a to the adjacent cell b, plus whether the
    move wrapped around the board edge. None if the cells are not adjacent."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    wrapped = False
    if wrap:
        if w > 2 and abs(dx) == w - 1 and dy == 0:
            dx, wrapped = (-1 if dx > 0 else 1), True
        elif h > 2 and abs(dy) == h - 1 and dx == 0:
            dy, wrapped = (-1 if dy > 0 else 1), True
    if abs(dx) + abs(dy) != 1:
        return None, False
    return (dx, dy), wrapped


class SnakePath:
    """Smooth centre line of a snake, in cell units.

    Cell i (0 = head) covers the parameter range s in [i - 0.5, i + 0.5]: s = i + 0.5
    is the edge it was entered through and s = i - 0.5 the edge it leaves by.
    Straight cells are straight lines; turning cells are quarter circles around
    the corner shared by the two edges, so the body bends smoothly.
    """

    def __init__(self, cells, exit_dir, w, h, wrap):
        n = len(cells)
        self.cells = cells
        self.entry = [None] * n
        self.exit = [None] * n
        self.cut = set()    # i: no line between cell i and i + 1
        self.capped = set()  # cuts that need round caps (teleports, not wraps)
        for i in range(n - 1):
            d, wrapped = _step(cells[i + 1], cells[i], w, h, wrap)
            self.entry[i] = d
            self.exit[i + 1] = d
            if d is None or wrapped:
                self.cut.add(i)
                if d is None:
                    self.capped.add(i)
        self.exit[0] = exit_dir
        for i in range(n):
            self.entry[i] = self.entry[i] or self.exit[i] or (1, 0)
            self.exit[i] = self.exit[i] or self.entry[i]

    def cell_of(self, s):
        return min(len(self.cells) - 1, max(0, math.floor(s + 0.5)))

    def point(self, s, i=None):
        """(x, y, tx, ty): position in cell units and unit tangent (direction of travel).

        Pass ``i`` to evaluate a specific cell's piece (s is clamped into it).
        """
        if i is None:
            i = self.cell_of(s)
        u = min(1.0, max(0.0, i + 0.5 - s))
        cx, cy = self.cells[i][0] + 0.5, self.cells[i][1] + 0.5
        e, x = self.entry[i], self.exit[i]
        if e == x or (e[0] == -x[0] and e[1] == -x[1]):
            return cx + e[0] * (u - 0.5), cy + e[1] * (u - 0.5), e[0], e[1]
        kx, ky = cx - e[0] / 2 + x[0] / 2, cy - e[1] / 2 + x[1] / 2
        a0 = math.atan2(-x[1], -x[0])
        d = math.atan2(e[1], e[0]) - a0
        d = (d + math.pi) % (2 * math.pi) - math.pi
        a = a0 + d * u
        sign = 1 if d > 0 else -1
        return kx + 0.5 * math.cos(a), ky + 0.5 * math.sin(a), -math.sin(a) * sign, math.cos(a) * sign


def build_snake_path(game, s, prev, t):
    """Path plus the head/tail parameters for the current frame."""
    cells = [(p.x, p.y) for p in s.body]
    n = len(cells)
    s_head, s_tail = 0.0, float(n - 1)
    wrap = game.has("borderless")
    if prev and not s.no_interp and prev[0] != cells[0]:
        d, _ = _step(prev[0], cells[0], game.w, game.h, wrap)
        if d is not None and n > 1 and prev[0] == cells[1]:
            s_head = 1.0 - t
        if prev[-1] != cells[-1] and _step(prev[-1], cells[-1], game.w, game.h, wrap)[0] is not None:
            cells.append(prev[-1])  # the cell the tail is sliding out of
            s_tail = n - t
    exit_dir = DIRS[s.planned or s.dir]
    return SnakePath(cells, exit_dir, game.w, game.h, wrap), s_head, s_tail


def draw_snake(surf, s, path, s_head, s_tail, c, head_col, tail_col, cheese=False, outline=None, offset=(0, 0)):
    """Draw the body as anti-aliased strips, one per cell, head on top."""
    ox, oy = offset
    n_body = len(s.body)
    span = max(1.0, s_tail - s_head)

    def hidden(i):
        return cheese and 0 < i < n_body and s.body[i].hole

    def strip(i, s0, s1, half, col):
        k = max(2, math.ceil((s1 - s0) * 10))
        left, right = [], []
        for j in range(k + 1):
            x, y, tx, ty = path.point(s0 + (s1 - s0) * j / k, i)
            left.append(((x - ty * half) * c + ox, (y + tx * half) * c + oy))
            right.append(((x + ty * half) * c + ox, (y - tx * half) * c + oy))
        poly = left + right[::-1]
        pygame.gfxdraw.filled_polygon(surf, poly, col)
        pygame.gfxdraw.aapolygon(surf, poly, col)

    def cap(sv, half, col):
        x, y, _, _ = path.point(sv)
        aa_disc(surf, col, x * c + ox, y * c + oy, half * c)

    def paint(half, color_of):
        first = path.cell_of(s_tail)
        last = path.cell_of(s_head)
        for i in range(first, last - 1, -1):
            if hidden(i):
                continue
            s0 = max(s_head, i - 0.5)
            s1 = min(s_tail, i + 0.5)
            if s1 - s0 <= 1e-6:
                continue
            col = color_of(i)
            # overlap neighbouring strips slightly so no seam shows
            lo = s0 if (i - 1) in path.cut or i - 1 < 0 else max(s_head, s0 - 0.03)
            hi = s1 if i in path.cut else min(s_tail, s1 + 0.03)
            strip(i, lo, hi, half, col)
            if i in path.capped and s1 >= i + 0.5:
                cap(i + 0.5 - 1e-6, half, col)
            if (i - 1) in path.capped and s0 <= i - 0.5:
                cap(i - 0.5 + 1e-6, half, col)
            if hidden(i + 1) and s1 >= i + 0.5:
                cap(i + 0.5 - 1e-6, half, col)
            if i > 0 and hidden(i - 1) and s0 <= i - 0.5:
                cap(i - 0.5 + 1e-6, half, col)
        cap(s_tail, half, color_of(path.cell_of(s_tail)))

    def color(i):
        return mix(head_col, tail_col, min(1.0, i / span))

    half = 0.39
    if outline:
        paint(half + 1.5 / c, lambda i: outline)
        cap(s_head, half + 1.5 / c, outline)
    paint(half, color)
    cap(s_head, 0.43 if not outline else half, head_col)


def draw_eyes(surf, h, tangent, c, dead):
    dx, dy = tangent
    px, py = -dy, dx
    for side in (-1, 1):
        ex = h[0] + dx * c * 0.1 + px * side * c * 0.22
        ey = h[1] + dy * c * 0.1 + py * side * c * 0.22
        if dead:
            r = c * 0.09
            w = max(2, int(c * 0.06))
            pygame.draw.line(surf, (17, 17, 17), (ex - r, ey - r), (ex + r, ey + r), w)
            pygame.draw.line(surf, (17, 17, 17), (ex + r, ey - r), (ex - r, ey + r), w)
            continue
        aa_disc(surf, (255, 255, 255), ex, ey, c * 0.165)
        aa_disc(surf, (30, 30, 30), ex + dx * c * 0.06, ey + dy * c * 0.06, c * 0.09)
        aa_disc(surf, (255, 255, 255), ex + dx * c * 0.03 - c * 0.03, ey + dy * c * 0.03 - c * 0.03, c * 0.03)


# ---- renderer ------------------------------------------------------------------

class View:
    """The visible window onto the board.

    ``cam_x``/``cam_y`` is the board position (in cells, may be fractional) at
    the viewport's top-left corner; ``w``/``h`` is the viewport size in pixels.
    Mods get one of these in their ``draw`` hook.
    """

    def __init__(self, c: int, cam_x: float, cam_y: float, w: int, h: int, board_w: int, board_h: int, now=0):
        self.c, self.cam_x, self.cam_y, self.w, self.h, self.now = c, cam_x, cam_y, w, h, now
        self.ox, self.oy = -cam_x * c, -cam_y * c
        self.x0, self.y0 = max(0, math.floor(cam_x) - 1), max(0, math.floor(cam_y) - 1)
        self.x1 = min(board_w, math.ceil(cam_x + w / c) + 1)
        self.y1 = min(board_h, math.ceil(cam_y + h / c) + 1)

    def px(self, x, y):
        """Top-left pixel of cell (x, y) on the viewport surface."""
        return round(x * self.c + self.ox), round(y * self.c + self.oy)

    def center(self, x, y):
        return x * self.c + self.ox + self.c / 2, y * self.c + self.oy + self.c / 2

    def visible(self, x, y) -> bool:
        return self.x0 <= x < self.x1 and self.y0 <= y < self.y1


def head_position(game, t):
    """Interpolated centre of the first snake's head, in cells (for the camera)."""
    s = game.snakes[0]
    path, s_head, _ = build_snake_path(game, s, game.prev[0] if game.prev else None, t)
    x, y, _, _ = path.point(s_head)
    return x, y


class Renderer:
    def __init__(self, pack=None):
        self.sprites = Sprites(pack)
        self.particles: list[list] = []
        self.shake = 0.0
        self.c = 32
        self._bg = None
        self._dark = None
        self._holes: dict = {}
        self._fonts: dict = {}

    def font(self, size: int, bold: bool = True) -> pygame.font.Font:
        key = (size, bold)
        f = self._fonts.get(key)
        if f is None:
            f = pygame.font.Font(None, size)
            f.set_bold(bold)
            self._fonts[key] = f
        return f

    def burst(self, x, y, color, n=14):
        c = self.c
        for _ in range(n):
            a = random.uniform(0, 2 * math.pi)
            sp = random.uniform(0.04, 0.12) * c
            self.particles.append([(x + 0.5) * c, (y + 0.5) * c, math.cos(a) * sp, math.sin(a) * sp, 1.0,
                                   color, c * random.uniform(0.06, 0.14)])

    def checker(self, c, vw, vh):
        """Checkerboard tile big enough to cover the viewport from any scroll offset."""
        key = (c, vw, vh, LIGHT, DARK)
        if not self._bg or self._bg[0] != key:
            cols, rows = vw // c + 4, vh // c + 4
            bg = pygame.Surface((cols * c, rows * c))
            for y in range(rows):
                for x in range(cols):
                    bg.fill(LIGHT if (x + y) % 2 == 0 else DARK, (x * c, y * c, c, c))
            self._bg = (key, bg)
        return self._bg[1]

    def draw_board(self, game, t: float, now: float, palette, view: "View",
                   hide_snake: bool = False) -> pygame.Surface:
        """Render the part of the board inside ``view`` to a viewport-sized surface."""
        c = self.c
        sp = self.sprites
        v = view
        surf = pygame.Surface((v.w, v.h))
        # Even-aligned so the checker pattern lines up with the cells.
        bx, by = v.x0 - v.x0 % 2, v.y0 - v.y0 % 2
        surf.blit(self.checker(c, v.w, v.h), v.px(bx, by))

        if game.has("minesweeper"):
            f = self.font(int(c * 0.8))
            for (x, y) in game.revealed:
                if v.visible(x, y):
                    surf.fill(SAND if (x + y) % 2 == 0 else SAND_DARK, (*v.px(x, y), c, c))
            for (x, y) in game.revealed:
                if v.visible(x, y):
                    n = game.mine_count(x, y)
                    if n and not game.snake_at(x, y):
                        img = f.render(str(n), True, MINE_NUMBER_COLORS[n])
                        surf.blit(img, img.get_rect(center=v.center(x, y)))
            if game.over:
                for (x, y) in game.mines:
                    if v.visible(x, y):
                        surf.blit(sp.get("mine", c), v.px(x, y))

        if game.has("dimension") and game.dim == 1:
            tint = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
            tint.fill((90, 40, 160, 46))
            surf.blit(tint, (0, 0))

        for (x, y) in game.targets:
            if v.visible(x, y):
                surf.blit(sp.get("target", c), v.px(x, y))
        for (x, y), d in game.arrows.items():
            if v.visible(x, y):
                surf.blit(sp.get("arrow", c, d), v.px(x, y))
        for g in game.gates:
            if v.visible(g.x, g.y):
                surf.blit(sp.get("gate_open" if g.open else "gate_closed", c), v.px(g.x, g.y))
        for wall in game.walls.values():
            if not v.visible(wall.x, wall.y):
                continue
            if wall.kind == "statue":
                surf.blit(sp.get("statue", c), v.px(wall.x, wall.y))
            elif game.wall_active(wall):
                surf.blit(sp.get("wall", c), v.px(wall.x, wall.y))
            else:
                surf.blit(sp.ghost("wall", c, 70), v.px(wall.x, wall.y))

        for it in game.items:
            if not v.visible(it.x, it.y):
                continue
            bob = math.sin(now / 250 + it.x) * c * 0.04
            img = sp.get("key", c, self.group_color(it.group)) if it.type == "key" else sp.get("shield", c)
            px, py = v.px(it.x, it.y)
            surf.blit(img, (px, py + bob))

        for a in game.apples:
            if not v.visible(a.x, a.y):
                continue
            center = v.center(a.x, a.y)
            if game.has("portal") and not a.poison:
                ring = pygame.transform.rotate(sp.get("ring", c, self.group_color(a.group)), -now / 7 % 360)
                surf.blit(ring, ring.get_rect(center=center))
            pulse = 1 + math.sin(now / 180 + a.x * 3 + a.y) * 0.04
            img = sp.get("fruit", max(1, round(c * pulse)), "poison" if a.poison else a.fruit)
            surf.blit(img, img.get_rect(center=center))
            if a.locked:
                surf.blit(sp.get("lock", c, self.group_color(a.group)), v.px(a.x, a.y))

        heads = []
        for i, s in enumerate(game.snakes):
            path, s_head, s_tail = build_snake_path(game, s, game.prev[i] if i < len(game.prev) else None, t)
            hx, hy, tx, ty = path.point(s_head)
            h = (hx * c + v.ox, hy * c + v.oy)
            heads.append(h)
            if hide_snake:
                continue
            if i == 1:
                draw_snake(surf, s, path, s_head, s_tail, c, (242, 242, 242), (184, 184, 184),
                           game.has("cheese"), (85, 85, 85), (v.ox, v.oy))
            else:
                draw_snake(surf, s, path, s_head, s_tail, c, palette[0], palette[1], game.has("cheese"),
                           offset=(v.ox, v.oy))
            if s.shield > 0:
                pygame.gfxdraw.filled_circle(surf, round(h[0]), round(h[1]), round(c * 0.62), (120, 190, 255, 70))
                pygame.draw.circle(surf, (80, 160, 255), h, c * 0.62, max(2, int(c * 0.07)))
            head_img = sp.snake_head(c, s.dead)
            if head_img:
                rot = pygame.transform.rotate(head_img, -math.degrees(math.atan2(ty, tx)))
                surf.blit(rot, rot.get_rect(center=h))
            else:
                draw_eyes(surf, h, (tx, ty), c, s.dead)

        for hook in game.hooks:
            hook.call("draw", surf, game, v)

        alive = []
        for p in self.particles:
            p[0] += p[2]
            p[1] += p[3]
            p[2] *= 0.94
            p[3] *= 0.94
            p[4] -= 0.03
            if p[4] > 0:
                col = (*p[5], int(255 * p[4]))
                pygame.gfxdraw.filled_circle(surf, round(p[0] + v.ox), round(p[1] + v.oy),
                                             max(1, round(p[6])), col)
                alive.append(p)
        self.particles = alive

        if game.has("light"):
            self.draw_darkness(surf, game, heads, v)
        elif heads:
            self.draw_pointers(surf, game, v, heads[0])
        return surf

    def draw_pointers(self, surf, game, v, head, limit=3):
        """On scrolling boards, markers at the edge pointing to the nearest
        off-screen fruit, so it can be found."""
        c = self.c
        m = max(c, 34)  # marker size: readable even when cells are small
        margin = m * 1.25
        hx, hy = head
        off = []
        for a in game.apples:
            if a.poison or a.locked:
                continue
            ax, ay = v.center(a.x, a.y)
            if -c / 2 <= ax <= v.w + c / 2 and -c / 2 <= ay <= v.h + c / 2:
                continue  # already on screen
            off.append((math.hypot(ax - hx, ay - hy), ax, ay, a))
        for dist, ax, ay, a in sorted(off, key=lambda o: o[0])[:limit]:
            dx, dy = ax - hx, ay - hy
            # walk from the head toward the fruit until we hit the inset edge
            k = min((v.w - margin - hx) / dx if dx > 0 else (margin - hx) / dx if dx < 0 else math.inf,
                    (v.h - margin - hy) / dy if dy > 0 else (margin - hy) / dy if dy < 0 else math.inf)
            px, py = hx + dx * k, hy + dy * k
            ang = math.atan2(dy, dx)
            tip = (px + math.cos(ang) * m * 0.66, py + math.sin(ang) * m * 0.66)
            side = (math.cos(ang + math.pi / 2) * m * 0.22, math.sin(ang + math.pi / 2) * m * 0.22)
            base = (px + math.cos(ang) * m * 0.4, py + math.sin(ang) * m * 0.4)
            pygame.draw.polygon(surf, (255, 255, 255), [tip, (base[0] + side[0], base[1] + side[1]),
                                                       (base[0] - side[0], base[1] - side[1])])
            aa_disc(surf, (255, 255, 255), px, py, m * 0.48)
            icon = self.sprites.get("fruit", int(m * 0.75), a.fruit)
            surf.blit(icon, icon.get_rect(center=(px, py)))
            cells = round(dist / c)
            img = self.font(max(14, int(m * 0.45))).render(str(cells), True, (40, 52, 33))
            # label on the side facing the middle of the screen, so it never clips
            label = img.get_rect(center=(px, py + (m * 0.8 if py < v.h / 2 else -m * 0.8)))
            bg = label.inflate(6, 2)
            pygame.draw.rect(surf, (255, 255, 255), bg, border_radius=bg.h // 2)
            surf.blit(img, label)

    def group_color(self, g):
        return PORTAL_COLORS[g % len(PORTAL_COLORS)]

    def hole(self, radius: int, alpha: int) -> pygame.Surface:
        key = (radius, alpha)
        surf = self._holes.get(key)
        if surf is None:
            surf = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
            surf.fill((5, 10, 20, 255))
            for r in range(radius, 0, -1):
                k = r / radius
                a = alpha * (0.15 * k / 0.6 if k < 0.6 else 0.15 + 0.85 * (k - 0.6) / 0.4)
                pygame.draw.circle(surf, (5, 10, 20, int(a)), (radius, radius), r)
            self._holes[key] = surf
        return surf

    def draw_darkness(self, surf, game, heads, v):
        c = self.c
        alpha = 140 if game.over else 237
        if not self._dark or self._dark.get_size() != surf.get_size():
            self._dark = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        dark = self._dark
        dark.fill((5, 10, 20, alpha))
        big = self.hole(int(c * 3.4), alpha)
        for h in heads:
            dark.blit(big, big.get_rect(center=h), special_flags=pygame.BLEND_RGBA_MIN)
        small = self.hole(int(c * 0.8), alpha)
        for a in game.apples:
            if v.visible(a.x, a.y):
                dark.blit(small, small.get_rect(center=v.center(a.x, a.y)), special_flags=pygame.BLEND_RGBA_MIN)
        surf.blit(dark, (0, 0))


# ---- mode picker icons -----------------------------------------------------------

def mode_icon(sprites: Sprites, mode_id: str, size: int) -> pygame.Surface:
    c = size // 3
    s = pygame.Surface((c * 3, c * 3), pygame.SRCALPHA)
    for y in range(3):
        for x in range(3):
            s.fill(DARK if (x + y) % 2 else LIGHT, (x * c, y * c, c, c))

    blue = (61, 111, 232)

    def snake(cells, color=blue, holes=()):
        pts = [((x + 0.5) * c, (y + 0.5) * c) for x, y in cells]
        if len(pts) == 1:
            aa_disc(s, color, pts[0][0], pts[0][1], c * 0.36)
        for i in range(len(pts) - 1):
            if i not in holes:
                capsule(s, color, pts[i], pts[i + 1], c * 0.72)

    def put(name, x, y, *args):
        s.blit(sprites.get(name, c, *args), (x * c, y * c))

    def text(t, x, y, color, scale=0.9):
        img = pygame.font.Font(None, int(c * scale * 1.3)).render(t, True, color)
        s.blit(img, img.get_rect(center=((x + 0.5) * c, (y + 0.5) * c)))

    m = mode_id
    if m == "classic":
        snake([(0, 2), (1, 2), (1, 1)]); put("fruit", 2, 0, "apple")
    elif m == "wall":
        snake([(0, 2), (1, 2)]); put("wall", 1, 0); put("wall", 2, 1); put("fruit", 2, 0, "apple")
    elif m == "portal":
        for x, y in ((0, 0), (2, 2)):
            put("ring", x, y, PORTAL_COLORS[0]); put("fruit", x, y, "apple")
    elif m == "cheese":
        snake([(0, 0), (1, 0), (2, 0), (2, 1), (2, 2), (1, 2), (0, 2)], holes=(1, 4))
    elif m == "borderless":
        snake([(1, 1), (2, 1)]); snake([(0, 1)]); put("fruit", 1, 0, "apple")
    elif m == "twin":
        snake([(0, 1), (1, 1), (2, 1)]); text("<>", 1, 0, (255, 255, 255))
    elif m == "yinyang":
        snake([(0, 0), (1, 0)]); snake([(2, 2), (1, 2)], (242, 242, 242)); put("fruit", 1, 1, "apple")
    elif m == "key":
        put("key", 0, 2, PORTAL_COLORS[0]); put("fruit", 2, 0, "apple"); put("lock", 2, 0, PORTAL_COLORS[0])
    elif m == "sokoban":
        put("target", 2, 1); put("fruit", 1, 1, "apple"); snake([(0, 1)])
    elif m == "poison":
        put("fruit", 0, 0, "apple"); put("fruit", 2, 2, "poison"); put("fruit", 2, 0, "poison"); put("fruit", 0, 2, "apple")
    elif m == "dimension":
        put("wall", 0, 0); s.blit(sprites.ghost("wall", c, 70), (c, c)); put("wall", 2, 2)
        tint = pygame.Surface(s.get_size(), pygame.SRCALPHA); tint.fill((90, 40, 160, 46)); s.blit(tint, (0, 0))
    elif m == "minesweeper":
        for i in range(3):
            s.fill(SAND_DARK if i % 2 else SAND, (i * c, 2 * c, c, c))
        text("1", 0, 2, MINE_NUMBER_COLORS[1]); text("2", 1, 2, MINE_NUMBER_COLORS[2]); put("mine", 1, 0)
    elif m == "statue":
        for x in range(3):
            put("statue", x, 0)
        snake([(0, 2), (1, 2)]); put("fruit", 2, 2, "apple")
    elif m == "light":
        dark = pygame.Surface(s.get_size(), pygame.SRCALPHA)
        dark.fill((5, 10, 20, 230))
        for r in range(int(c * 1.3), 0, -1):
            pygame.draw.circle(dark, (5, 10, 20, int(230 * r / (c * 1.3))), (1.5 * c, 1.5 * c), r)
        s.blit(dark, (0, 0)); snake([(1, 1)])
    elif m == "shield":
        s.blit(sprites.get("shield", c * 3), (0, 0))
    elif m == "arrow":
        put("arrow", 1, 1, "up"); put("arrow", 0, 0, "right"); put("arrow", 2, 2, "down")
    elif m == "magnet":
        pygame.draw.polygon(s, (211, 47, 47), arc_band(1.5 * c, 1.3 * c, c * 0.95, c * 0.5, 0, math.pi))
        s.fill((221, 221, 221), (0.55 * c, 1.0 * c, c * 0.45, c * 0.3))
        s.fill((221, 221, 221), (2.0 * c, 1.0 * c, c * 0.45, c * 0.3))
        put("fruit", 1, 0, "apple")
    elif m == "gate":
        put("gate_closed", 1, 0); put("gate_open", 1, 2); snake([(0, 1), (1, 1), (2, 1)])
    elif m == "peaceful":
        snake([(0, 2), (1, 2), (1, 1)])
        heart = [(2.5 * c + 16 * math.sin(t) ** 3 * c / 50, 0.5 * c - (13 * math.cos(t) - 5 * math.cos(2 * t)
                  - 2 * math.cos(3 * t) - math.cos(4 * t)) * c / 50) for t in [i / 30 * 2 * math.pi for i in range(30)]]
        pygame.draw.polygon(s, (255, 107, 154), heart)
    elif m in MODE_HOOKS and MODE_HOOKS[m].icon:
        MODE_HOOKS[m].call("icon", s, s.get_width())
    else:
        # Mod mode without its own icon: its initial on the board.
        text(modes.MODE_NAMES.get(m, m)[:1].upper(), 1, 1, (255, 255, 255), 1.6)
    return s
