"""Snake points, skins, texture packs, loot boxes and ranks.

Shared by the game and the server: the server decides what you earn and what
a loot box gives you, and the game uses the same catalogue to draw skins and
the store. Everything here lives on an OpenSnake server account, so each
website has its own points, items and ranks (like its leaderboards).
"""

from __future__ import annotations

import colorsys
import math
import random
from dataclasses import dataclass

# ---- snake points --------------------------------------------------------------

ROUND_BASE = 25          # finishing a single-player round (dying or winning)
ROUND_PER_FRUIT = 10
ROUND_CAP = 2_000        # most one round can give
PR_REWARD = 1_000        # new personal record in a built-in speedrun category
WR_REWARD = 100_000      # new world record in a built-in category
WR_HOLD_REWARD = 10_000  # for every full 3 days you keep a world record
WR_HOLD_DAYS = 3
MATCH_PLAYED = 50        # online versus, per match
MATCH_PER_FRUIT = 10
MATCH_WIN = 200


def round_points(fruit: int) -> int:
    return min(ROUND_CAP, ROUND_BASE + ROUND_PER_FRUIT * max(0, int(fruit)))


def format_points(n: int) -> str:
    return f"{int(n):,}"


# ---- ranks -------------------------------------------------------------------------
#
# Rank points (RP) come from online versus matches against other people.
# Matches with bots don't change your rank.

RP_WIN, RP_LOSS, RP_DRAW = 30, -20, 5

RANKS = [  # (minimum RP, name, colour)
    (0, "Hatchling", (150, 160, 140)),
    (100, "Garter", (104, 170, 80)),
    (250, "Rattler", (196, 150, 80)),
    (500, "Cobra", (60, 150, 220)),
    (800, "Viper", (130, 90, 220)),
    (1200, "Python", (230, 120, 40)),
    (1700, "Anaconda", (220, 60, 70)),
    (2300, "Basilisk", (255, 196, 0)),
]


def rank_for(rp: int) -> tuple[int, str, tuple]:
    """(index, name, colour) of the rank for this many RP."""
    index = max(i for i, (lo, _n, _c) in enumerate(RANKS) if rp >= lo)
    return index, RANKS[index][1], RANKS[index][2]


def next_rank(rp: int) -> tuple[str, int] | None:
    """The next rank's name and the RP it needs, or None at the top."""
    index = rank_for(rp)[0]
    if index + 1 >= len(RANKS):
        return None
    lo, name, _c = RANKS[index + 1]
    return name, lo


# ---- rarities ----------------------------------------------------------------------

RARITIES = ["common", "uncommon", "rare", "epic", "legendary", "mythic"]
RARITY_NAMES = {"common": "Common", "uncommon": "Uncommon", "rare": "Rare", "epic": "Epic",
                "legendary": "Legendary", "mythic": "Mythic"}
RARITY_COLORS = {"common": (176, 186, 190), "uncommon": (76, 175, 80), "rare": (33, 150, 243),
                 "epic": (163, 64, 214), "legendary": (255, 176, 0), "mythic": (240, 60, 60)}
# Points back for a loot box item you already own.
DUPLICATE_REFUND = {"common": 200, "uncommon": 600, "rare": 2_500, "epic": 8_000,
                    "legendary": 25_000, "mythic": 60_000}


# ---- skins -------------------------------------------------------------------------

@dataclass(frozen=True)
class Skin:
    id: str
    name: str
    rarity: str
    pattern: str            # grad / stripes / rainbow / flow / pulse / shimmer
    colors: tuple           # the pattern's colours (head first)
    outline: tuple | None = None
    glow: bool = False      # the outline pulses
    price: int | None = None  # None: only from loot boxes

    @property
    def shop(self) -> bool:
        return self.price is not None


def _c(hexstr: str) -> tuple:
    h = hexstr.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _skin(id, name, rarity, pattern, colors, outline=None, glow=False, price=None):
    return Skin(id, name, rarity, pattern, tuple(_c(c) for c in colors),
                _c(outline) if outline else None, glow, price)


SKINS = [
    # Common: plain colours, in the shop
    _skin("mint", "Mint", "common", "grad", ["#2fb879", "#9be8c4"], price=500),
    _skin("sky", "Sky", "common", "grad", ["#3b9be0", "#a9d8ff"], price=500),
    _skin("coral", "Coral", "common", "grad", ["#f0645a", "#ffb3a6"], price=500),
    _skin("lavender", "Lavender", "common", "grad", ["#9a7be0", "#d5c6ff"], price=600),
    _skin("sand", "Sand", "common", "grad", ["#c9a25c", "#f1dcae"], price=600),
    _skin("slate", "Slate", "common", "grad", ["#55636e", "#a8b5bf"], price=600),
    _skin("forest", "Forest", "common", "grad", ["#2e7d32", "#81c784"], price=750),
    _skin("cherry", "Cherry", "common", "grad", ["#c2185b", "#f48fb1"], price=750),
    _skin("lemon", "Lemon", "common", "grad", ["#e0b800", "#fff59d"], price=750),
    _skin("ocean", "Ocean", "common", "grad", ["#0b5e8e", "#4fc3c7"], price=1_000),
    _skin("rust", "Rust", "common", "grad", ["#a0461f", "#e0955f"], price=1_000),
    _skin("bubblegum", "Bubblegum", "common", "grad", ["#ff5fa8", "#ffc4e1"], price=1_000),
    _skin("charcoal", "Charcoal", "common", "grad", ["#262a30", "#6b7480"], price=1_250),
    _skin("ice", "Ice", "common", "grad", ["#7fc8e8", "#effaff"], price=1_500),
    # Uncommon: stripes and two-tone, in the shop
    _skin("bumblebee", "Bumblebee", "uncommon", "stripes", ["#f6c400", "#2a2a2a"], price=2_500),
    _skin("candycane", "Candy Cane", "uncommon", "stripes", ["#e53935", "#fafafa"], price=2_500),
    _skin("coralsnake", "Coral Snake", "uncommon", "stripes", ["#d32f2f", "#fdd835", "#212121", "#fdd835"],
          price=3_000),
    _skin("tiger", "Tiger", "uncommon", "stripes", ["#f57c00", "#f57c00", "#1b1b1b"], price=3_000),
    _skin("zebra", "Zebra", "uncommon", "stripes", ["#f5f5f5", "#202020"], price=3_000),
    _skin("watermelon", "Watermelon", "uncommon", "stripes", ["#2e9e3e", "#86d47a"], "#e8435a", price=3_500),
    _skin("mintchoc", "Mint Choc", "uncommon", "stripes", ["#7ee0b5", "#5b3a29"], price=3_500),
    _skin("siren", "Siren", "uncommon", "stripes", ["#1e5bd8", "#e0262e"], price=4_000),
    _skin("pumpkin", "Pumpkin", "uncommon", "stripes", ["#ff8f1f", "#d96a00"], "#3d6b1f", price=4_000),
    _skin("grapesoda", "Grape Soda", "uncommon", "grad", ["#5b2a86", "#b07be8"], "#2c1145", price=4_500),
    _skin("sunset", "Sunset", "uncommon", "grad", ["#ff7a18", "#8e2de2"], price=5_000),
    _skin("seafoam", "Seafoam", "uncommon", "grad", ["#11998e", "#f0e6b6"], price=5_000),
    # Rare: outlines, metals and the first rainbow, in the shop
    _skin("gold", "Gold", "rare", "shimmer", ["#c8961e", "#ffe08a"], "#8a6410", price=10_000),
    _skin("chrome", "Chrome", "rare", "shimmer", ["#8e9aa6", "#f2f6fa"], "#4b5560", price=10_000),
    _skin("bronze", "Bronze", "rare", "shimmer", ["#8c5a2b", "#e3a868"], "#5a3518", price=10_000),
    _skin("toxic", "Toxic", "rare", "grad", ["#7cff3a", "#1f6b0f"], "#b6ff6e", glow=True, price=12_500),
    _skin("frostbite", "Frostbite", "rare", "grad", ["#bff0ff", "#3a8fd6"], "#e6fbff", glow=True, price=12_500),
    _skin("ember", "Ember", "rare", "grad", ["#ffd23f", "#d1261b"], "#ff8a00", glow=True, price=15_000),
    _skin("neon", "Neon", "rare", "grad", ["#ff2bd6", "#6a00ff"], "#ff9cf0", glow=True, price=15_000),
    _skin("midnight", "Midnight", "rare", "grad", ["#0d1b3e", "#1f3a7a"], "#36e0ff", price=17_500),
    _skin("rainbow", "Rainbow", "rare", "rainbow", ["#ff0000"], price=20_000),
    _skin("ghost", "Ghost", "rare", "grad", ["#f4f6ff", "#c9cfe6"], "#8a93b8", price=20_000),
    # Epic: animated, loot boxes only
    _skin("lavaflow", "Lava Flow", "epic", "flow", ["#ff3b00", "#ff9a00", "#ffe066", "#b31200"]),
    _skin("aurora", "Aurora", "epic", "flow", ["#00e0a1", "#00b3ff", "#8f5bff", "#00e0a1"]),
    _skin("galaxy", "Galaxy", "epic", "flow", ["#2a0a5e", "#5b2bd9", "#e64fd8", "#1a1150"], "#b38cff"),
    _skin("electric", "Electric", "epic", "pulse", ["#00e5ff", "#fff200"], "#00e5ff", glow=True),
    _skin("toxicwaste", "Toxic Waste", "epic", "pulse", ["#39ff14", "#0a3d00"], "#c6ff00", glow=True),
    _skin("bloodmoon", "Blood Moon", "epic", "pulse", ["#7a0010", "#ff2a3d"], "#3a0006", glow=True),
    _skin("cottoncandy", "Cotton Candy", "epic", "flow", ["#ff9ad5", "#9ad7ff", "#fff0a8", "#ff9ad5"]),
    # Legendary: animated with glowing outlines, loot boxes only
    _skin("prismatic", "Prismatic", "legendary", "rainbow", ["#ff0000"], "#ffffff", glow=True),
    _skin("inferno", "Inferno", "legendary", "flow", ["#ff2200", "#ff7b00", "#ffd000", "#ff7b00"], "#ffef80",
          glow=True),
    _skin("void", "Void", "legendary", "pulse", ["#050008", "#2a0050"], "#b026ff", glow=True),
    _skin("goldendragon", "Golden Dragon", "legendary", "shimmer", ["#b8001f", "#ffcc33"], "#ffe9a3", glow=True),
    _skin("northernlights", "Northern Lights", "legendary", "flow",
          ["#0b3d2e", "#1de9b6", "#7c4dff", "#00b0ff"], "#a7ffeb", glow=True),
    # Mythic: the rarest, loot boxes only
    _skin("celestial", "Celestial", "mythic", "rainbow", ["#ffffff"], "#ffd54f", glow=True),
    _skin("basilisk", "Basilisk", "mythic", "shimmer", ["#003d1f", "#00e676"], "#ffd700", glow=True),
]
SKIN_BY_ID = {s.id: s for s in SKINS}


def _lerp(a, b, t):
    return (round(a[0] + (b[0] - a[0]) * t), round(a[1] + (b[1] - a[1]) * t), round(a[2] + (b[2] - a[2]) * t))


def _cycle(colors, t):
    """A colour from a looping palette, t in [0, 1)."""
    n = len(colors)
    t = (t % 1.0) * n
    i = int(t)
    return _lerp(colors[i % n], colors[(i + 1) % n], t - i)


def skin_color(skin: Skin, i: int, n: int, now: float) -> tuple:
    """Colour of body cell ``i`` (0 = head) of an ``n``-cell snake at time ``now`` (ms)."""
    c = skin.colors
    k = i / max(1, n - 1)
    if skin.pattern == "grad":
        return _lerp(c[0], c[-1], k)
    if skin.pattern == "stripes":
        return c[i % len(c)]
    if skin.pattern == "rainbow":
        hue = (i * 0.07 - now / 2500) % 1.0
        r, g, b = colorsys.hsv_to_rgb(hue, 0.85 if c[0] != (255, 255, 255) else 0.45, 1.0)
        return (round(r * 255), round(g * 255), round(b * 255))
    if skin.pattern == "flow":
        return _cycle(c, i * 0.09 - now / 1800)
    if skin.pattern == "pulse":
        return _lerp(c[0], c[1], 0.5 + 0.5 * math.sin(now / 260 - i * 0.55))
    if skin.pattern == "shimmer":
        band = (now / 90) % (n + 8) - 4  # a bright band running down the body
        return _lerp(c[0], c[1], max(0.0, 1 - abs(i - band) / 2.5))
    return c[0]


def skin_outline(skin: Skin, now: float) -> tuple | None:
    if not skin.outline:
        return None
    if not skin.glow:
        return skin.outline
    k = 0.5 + 0.5 * math.sin(now / 220)
    return _lerp(skin.outline, (255, 255, 255), 0.35 * k)


def skin_preview_color(skin: Skin) -> tuple:
    return skin.colors[0]


# ---- loot-box texture packs -------------------------------------------------------
#
# Colour packs shipped with the game but only usable once you've won them
# (opensnake/packs/<id>/, marked "locked" in pack.json).

@dataclass(frozen=True)
class LootPack:
    id: str        # folder name in opensnake/packs
    name: str
    rarity: str
    swatch: tuple  # colours for the store's preview


PACKS = [
    LootPack("midnight", "Midnight", "epic", (_c("#1b2440"), _c("#2c3a63"), _c("#4fc3f7"))),
    LootPack("sakura", "Sakura", "epic", (_c("#ffd6e7"), _c("#f7b6cf"), _c("#d81b60"))),
    LootPack("desertnight", "Desert Night", "epic", (_c("#3e2f4f"), _c("#6b4f6e"), _c("#ffb74d"))),
    LootPack("synthwave", "Synthwave", "legendary", (_c("#2b0f54"), _c("#ff2a6d"), _c("#05d9e8"))),
    LootPack("arctic", "Arctic", "legendary", (_c("#e3f2fd"), _c("#b3e5fc"), _c("#0277bd"))),
    LootPack("obsidian", "Obsidian", "mythic", (_c("#0a0a0f"), _c("#1d1b2e"), _c("#ffd54f"))),
]
PACK_BY_ID = {p.id: p for p in PACKS}


# ---- the catalogue of everything you can own -----------------------------------------
#
# Item ids are "skin:<id>" and "pack:<id>".

def item_rarity(item: str) -> str | None:
    kind, _, key = item.partition(":")
    if kind == "skin" and key in SKIN_BY_ID:
        return SKIN_BY_ID[key].rarity
    if kind == "pack" and key in PACK_BY_ID:
        return PACK_BY_ID[key].rarity
    return None


def item_name(item: str) -> str:
    kind, _, key = item.partition(":")
    if kind == "skin" and key in SKIN_BY_ID:
        return SKIN_BY_ID[key].name
    if kind == "pack" and key in PACK_BY_ID:
        return PACK_BY_ID[key].name + " pack"
    return item


ALL_ITEMS = [f"skin:{s.id}" for s in SKINS] + [f"pack:{p.id}" for p in PACKS]


# ---- loot boxes ----------------------------------------------------------------------

@dataclass(frozen=True)
class Crate:
    id: str
    name: str
    price: int
    color: tuple
    odds: dict  # rarity -> percent


CRATES = [
    Crate("bronze", "Bronze Crate", 2_000, (196, 120, 60),
          {"common": 70, "uncommon": 22, "rare": 6, "epic": 1.6, "legendary": 0.35, "mythic": 0.05}),
    Crate("silver", "Silver Crate", 7_500, (170, 180, 192),
          {"common": 40, "uncommon": 35, "rare": 17, "epic": 6, "legendary": 1.7, "mythic": 0.3}),
    Crate("gold", "Gold Crate", 25_000, (230, 180, 30),
          {"common": 10, "uncommon": 30, "rare": 35, "epic": 18, "legendary": 6, "mythic": 1}),
    Crate("diamond", "Diamond Crate", 100_000, (80, 210, 240),
          {"uncommon": 10, "rare": 35, "epic": 35, "legendary": 16, "mythic": 4}),
]
CRATE_BY_ID = {c.id: c for c in CRATES}


def items_of(rarity: str) -> list[str]:
    return [it for it in ALL_ITEMS if item_rarity(it) == rarity]


def roll(crate: Crate, rng=random) -> str:
    """One item from a loot box: pick a rarity by the odds, then an item of it."""
    rarities = [r for r in RARITIES if crate.odds.get(r)]
    rarity = rng.choices(rarities, weights=[crate.odds[r] for r in rarities])[0]
    return rng.choice(items_of(rarity))


# ---- profile pictures ---------------------------------------------------------------

AVATAR_ICONS = ["opensnake", "fruit_apple", "fruit_orange", "fruit_cherry", "fruit_grape", "fruit_strawberry",
                "fruit_lemon", "fruit_banana", "key", "shield", "trophy", "skull", "statue", "lock", "mine"]
AVATAR_COLORS = [(61, 111, 232), (232, 112, 26), (40, 160, 70), (210, 60, 50), (138, 63, 224),
                 (19, 154, 143), (224, 69, 123), (38, 42, 51)]
DEFAULT_AVATAR = "opensnake:0"
CUSTOM_AVATAR = "custom"  # "custom:<version>": the player's own uploaded picture


def custom_picture(value) -> str | None:
    """The version of a player's own picture if their avatar is one, else None."""
    kind, _, version = str(value or "").partition(":")
    return version if kind == CUSTOM_AVATAR and version else None


def parse_avatar(value) -> tuple[str, int]:
    """("icon", colour index) from "icon:index", falling back to the default."""
    icon, _, color = str(value or "").partition(":")
    try:
        ci = int(color)
    except ValueError:
        ci = 0
    if icon not in AVATAR_ICONS or not 0 <= ci < len(AVATAR_COLORS):
        return "opensnake", 0
    return icon, ci
