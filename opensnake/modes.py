"""Mode catalogue and game options.

Any combination of modes can be enabled at once ("Blender"), except for the
pairs listed in ``CONFLICTS``.
"""

from __future__ import annotations

import random

MODES = [
    ("classic", "Classic", "Eat fruit, grow longer, avoid the walls and yourself."),
    ("wall", "Wall", "Every fruit you eat drops a new wall somewhere on the board."),
    ("portal", "Portal", "Fruit comes in pairs. Eat one and you pop out of the other."),
    ("cheese", "Cheese", "Your body is full of holes you can slither through."),
    ("borderless", "Borderless", "Leave one side of the board, come back on the other."),
    ("twin", "Twin", "Each fruit flips you around: your tail becomes your head."),
    ("yinyang", "Yin Yang", "Control two mirrored snakes at once. Don't let them touch."),
    ("key", "Key", "Fruit is locked. Grab its key first to open it."),
    ("sokoban", "Sokoban", "Push fruit onto the targets instead of eating it."),
    ("poison", "Poison", "Half the fruit is poison, and it swaps every time you eat."),
    ("dimension", "Dimension", "Walls live in two dimensions. Eating flips which one is solid."),
    ("minesweeper", "Minesweeper", "Hidden mines. Numbers on visited cells count nearby mines."),
    ("statue", "Statue", "Eating turns your body to stone. Keep going with what's left."),
    ("light", "Light", "The board is dark. Only your head lights the way."),
    ("shield", "Shield", "Pick up shields that let you survive one crash."),
    ("arrow", "Arrow", "Arrow tiles force you to turn the way they point."),
    ("magnet", "Magnet", "Fruit near your head gets pulled toward you."),
    ("gate", "Gate", "Gates open and close on a timer. Time your runs."),
    ("peaceful", "Peaceful", "No game over. Crashing just stops you until you turn."),
]
MODE_NAMES = {m[0]: m[1] for m in MODES}
MODE_DESCS = {m[0]: m[2] for m in MODES}

CONFLICTS = [("sokoban", "portal"), ("sokoban", "poison"), ("portal", "poison")]

# Board size limits (cells). Any rectangle in this range works.
MIN_BOARD_W, MIN_BOARD_H = 8, 5
MAX_BOARD = 1000
DEFAULT_BOARD = (10, 9)

# Speed is a slider from 0.0 (slowest) to 1.0 (fastest); these are the labelled
# ticks as (slider position, label, milliseconds per cell).
SPEED_TICKS = [(0.0, "Slowest", 260), (0.25, "Slow", 170), (0.5, "Default", 130),
               (0.75, "Fast", 85), (1.0, "Fastest", 45)]
DEFAULT_SPEED = 0.5
# Settings saved before the slider was widened used 0 = Slow, 1 = Fast.
SPEED_SCALE_VERSION = 2


def migrate_speed_v1(value: float) -> float:
    """Convert a speed from the old 3-stop slider to the same speed on this one."""
    return round(0.25 + 0.5 * min(1.0, max(0.0, value)), 3)

# Settings files from older versions used named sizes and speeds.
LEGACY_SIZES = {"small": (10, 9), "medium": (17, 15), "large": (24, 21)}
LEGACY_SPEEDS = {"slow": 0.0, "normal": 0.5, "fast": 1.0}


def speed_ms(value: float) -> float:
    """Milliseconds per cell for a slider position, interpolating between ticks."""
    value = min(1.0, max(0.0, value))
    for (p0, _l0, m0), (p1, _l1, m1) in zip(SPEED_TICKS, SPEED_TICKS[1:]):
        if value <= p1:
            return m0 + (m1 - m0) * (value - p0) / (p1 - p0)
    return SPEED_TICKS[-1][2]


SNAKE_COLORS = {
    "blue": ((61, 111, 232), (122, 162, 255), "Blue"),
    "purple": ((138, 63, 224), (193, 155, 255), "Purple"),
    "orange": ((232, 112, 26), (255, 179, 107), "Orange"),
    "pink": ((224, 69, 123), (255, 158, 192), "Pink"),
    "teal": ((19, 154, 143), (111, 224, 212), "Teal"),
    "black": ((38, 42, 51), (107, 114, 128), "Black"),
}

FRUIT_LABELS = {
    "apple": "Apple", "orange": "Orange", "cherry": "Cherry", "grape": "Grape",
    "strawberry": "Strawberry", "lemon": "Lemon", "banana": "Banana", "mixed": "Mixed",
}


def toggle_mode(active, mode_id: str) -> set[str]:
    """Turning a mode on turns off anything it conflicts with.

    "classic" is the empty set, so selecting it clears everything else.
    """
    nxt = set(active)
    if mode_id == "classic":
        return set()
    if mode_id in nxt:
        nxt.discard(mode_id)
        return nxt
    nxt.add(mode_id)
    for a, b in CONFLICTS:
        if a == mode_id:
            nxt.discard(b)
        if b == mode_id:
            nxt.discard(a)
    return nxt


def blend_modes(rng=random) -> set[str]:
    pool = [m[0] for m in MODES if m[0] not in ("classic", "peaceful")]
    n = rng.randint(2, 4)
    chosen: set[str] = set()
    for mode_id in rng.sample(pool, len(pool)):
        if len(chosen) >= n:
            break
        if not any((a == mode_id and b in chosen) or (b == mode_id and a in chosen) for a, b in CONFLICTS):
            chosen.add(mode_id)
    return chosen


def mode_label(modes) -> str:
    if not modes:
        return "Classic"
    names = [MODE_NAMES[m] for m in MODES_ORDER if m in modes]
    return "Blender: " + " + ".join(names) if len(names) > 1 else names[0]


MODES_ORDER = [m[0] for m in MODES]
