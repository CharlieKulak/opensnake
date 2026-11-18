"""Story mode: eight chapters of ten levels, each chapter ending in a boss duel.

A level is a speedrun-style challenge (a seeded game, replayed by the server to check it):
finishing it is the first star, and two challenges (a time to beat, few turns, a fast start,
no shield used) are the other two. A boss is a split-board duel against a computer snake
(see duel.py), played on the server.

Everything here is data both the server and the clients read (tools/export_catalog.py
exports it), so they agree on every level's rules and what each star needs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .game import DIRS
from .speedrun import MAX_RUN_MS, MIN_TICK_MS, Category, Run

STORY_PREFIX = "story-"


@dataclass(frozen=True)
class Level:
    id: str            # "s3-07": chapter 3, level 7
    chapter: int       # 1..8
    num: int           # 1..10
    name: str
    w: int
    h: int
    modes: tuple
    goal: int
    fruit_count: int
    tick_ms: float
    accel: float = 0.0
    challenges: tuple = ()   # two (kind, a, b): see challenge_text

    @property
    def category(self) -> Category:
        return Category(STORY_PREFIX + self.id, f"{self.chapter}-{self.num} {self.name}",
                        f"Chapter {self.chapter}, level {self.num}", self.w, self.h, tuple(sorted(self.modes)),
                        self.goal, self.fruit_count, self.tick_ms, self.accel, MIN_TICK_MS)


@dataclass(frozen=True)
class Boss:
    num: int
    id: str
    name: str
    title: str
    taunt: str
    colors: tuple           # body, belly, accent (hex)
    attack: str             # signature attack id (duel.py)
    attack_name: str
    attack_desc: str
    attack_every: int       # seconds between signature attacks
    bot: str                # bots.py tuning level
    w: int
    h: int
    apples: int
    tick_ms: float
    modes: tuple = ()
    combo_window: int = 12  # moves between fruit that keep a combo going
    rewards: tuple = ()
    skin: str = ""


@dataclass(frozen=True)
class Chapter:
    num: int
    name: str
    blurb: str
    color: str
    levels: tuple = field(default_factory=tuple)
    boss: Boss | None = None


# ---- the levels ------------------------------------------------------------------------
#
# (name, w, h, modes, goal, fruit on the board, ms a move, accelerate)

SPECS = {
    1: ("Meadow", "Sunny fields and an easy start. Learn to turn tight and think ahead.", "#4caf50", [
        ("First Bite", 10, 9, (), 5, 1, 150, 0),
        ("Clover Patch", 11, 9, (), 8, 1, 145, 0),
        ("Buttercup Lane", 12, 10, (), 10, 2, 140, 0),
        ("Dandelion Dash", 12, 10, (), 12, 2, 135, 0),
        ("Picnic Blanket", 9, 8, (), 12, 1, 140, 0),
        ("Bumblebee Loop", 14, 11, (), 15, 3, 130, 0),
        ("Sunflower Field", 14, 12, ("magnet",), 15, 2, 130, 0),
        ("Rabbit Run", 13, 11, (), 18, 2, 125, 0),
        ("Long Grass", 16, 12, (), 20, 3, 125, 0),
        ("Meadow's Edge", 12, 10, (), 22, 1, 120, 0),
    ]),
    2: ("Orchard", "Locked fruit, keys hidden in the trees, and shields to save your skin.", "#e8772e", [
        ("Locked Pantry", 12, 10, ("key",), 6, 1, 135, 0),
        ("Apple Cart", 13, 11, ("key",), 8, 2, 132, 0),
        ("Guardian Bark", 12, 10, ("shield",), 10, 1, 130, 0),
        ("Key Keeper", 14, 11, ("key", "magnet"), 10, 2, 128, 0),
        ("Bramble Shield", 13, 11, ("key", "shield"), 10, 2, 125, 0),
        ("Windfall", 15, 12, ("magnet",), 18, 3, 120, 0),
        ("Cellar Door", 12, 10, ("key",), 14, 1, 120, 0),
        ("Grafting", 14, 12, ("key", "shield"), 14, 2, 118, 0),
        ("Harvest Rush", 16, 12, ("magnet", "shield"), 22, 3, 115, 0),
        ("Orchard Gate", 14, 12, ("key", "magnet", "shield"), 18, 2, 110, 0),
    ]),
    3: ("Ruins", "Old stone that keeps on growing. Every bite builds another wall.", "#a1887f", [
        ("Crumbling Wall", 12, 10, ("wall",), 8, 1, 128, 0),
        ("Stone Garden", 12, 10, ("statue",), 6, 1, 128, 0),
        ("Swiss Steps", 13, 11, ("cheese",), 12, 1, 125, 0),
        ("Fallen Columns", 14, 11, ("wall",), 12, 2, 122, 0),
        ("Petrified", 13, 11, ("statue",), 9, 1, 120, 0),
        ("Holey Halls", 14, 12, ("cheese", "wall"), 12, 2, 118, 0),
        ("Rubble Run", 15, 12, ("shield", "wall"), 15, 2, 115, 0),
        ("Statuary", 14, 12, ("cheese", "statue"), 10, 2, 112, 0),
        ("Collapse", 16, 12, ("wall",), 18, 2, 108, 0),
        ("Heart of the Ruins", 15, 12, ("statue", "wall"), 12, 2, 104, 0),
    ]),
    4: ("Clockwork", "Portals, arrows and gates that tick open and shut. Mind the timing.", "#d4a14a", [
        ("Wormhole", 12, 10, ("portal",), 8, 1, 122, 0),
        ("Signposts", 12, 10, ("arrow",), 8, 1, 122, 0),
        ("Tick Tock Gates", 13, 11, ("gate",), 10, 1, 120, 0),
        ("Flip Side", 12, 10, ("twin",), 10, 1, 120, 0),
        ("Rush Hour", 14, 11, ("arrow", "gate"), 10, 2, 116, 0),
        ("Hall of Mirrors", 14, 12, ("portal", "twin"), 10, 1, 114, 0),
        ("Escapement", 14, 12, ("gate", "wall"), 12, 2, 110, 0),
        ("Compass Rose", 15, 12, ("arrow", "portal"), 12, 1, 106, 0),
        ("Mainspring", 16, 12, ("arrow", "gate", "twin"), 12, 2, 102, 0),
        ("The Great Clock", 16, 13, ("arrow", "gate", "portal"), 14, 2, 98, 0),
    ]),
    5: ("Swamp", "Poison fruit and pitch-dark water. Look before you bite.", "#5e8c31", [
        ("Toxic Tidbits", 12, 10, ("poison",), 8, 2, 118, 0),
        ("Lantern Light", 13, 11, ("light",), 8, 1, 118, 0),
        ("Bog Berries", 14, 11, ("poison",), 12, 3, 115, 0),
        ("Firefly Path", 14, 12, ("light", "magnet"), 10, 2, 112, 0),
        ("Will-o'-Wisp", 14, 12, ("light", "shield"), 12, 2, 110, 0),
        ("Murky Waters", 15, 12, ("light", "poison"), 10, 2, 106, 0),
        ("Leech Pool", 14, 12, ("poison", "wall"), 12, 2, 104, 0),
        ("Night Bloom", 15, 12, ("key", "light"), 10, 2, 100, 0),
        ("Miasma", 16, 12, ("cheese", "poison"), 15, 3, 98, 0),
        ("Heart of the Swamp", 16, 13, ("light", "poison", "wall"), 12, 3, 95, 0),
    ]),
    6: ("Minefield", "Hidden mines, crates to shove and walls that flicker between worlds.", "#8d6e63", [
        ("Tread Lightly", 12, 10, ("minesweeper",), 6, 1, 115, 0),
        ("Box Pusher", 9, 8, ("sokoban",), 2, 1, 112, 0),
        ("Phase Shift", 13, 11, ("dimension",), 10, 1, 112, 0),
        ("Sweeper", 14, 11, ("minesweeper", "shield"), 8, 1, 110, 0),
        ("Warehouse", 11, 9, ("sokoban",), 3, 2, 108, 0),
        ("Twin Realms", 14, 12, ("dimension", "wall"), 10, 1, 106, 0),
        ("Danger Close", 15, 12, ("magnet", "minesweeper"), 10, 2, 104, 0),
        ("Crate Expectations", 12, 10, ("sokoban",), 4, 2, 110, 0),
        ("Shifting Sands", 16, 12, ("dimension", "minesweeper"), 10, 2, 100, 0),
        ("No Man's Land", 16, 13, ("dimension", "minesweeper", "shield"), 12, 2, 96, 0),
    ]),
    7: ("Storm", "It only gets faster from here. Every bite speeds you up.", "#3f7fd6", [
        ("Tailwind", 14, 11, (), 15, 2, 120, 3),
        ("Wraparound", 14, 12, ("borderless",), 15, 2, 105, 0),
        ("Gale", 14, 12, ("wall",), 15, 2, 115, 3),
        ("Lightning Fork", 15, 12, ("borderless", "twin"), 12, 2, 100, 0),
        ("Downpour", 15, 12, ("magnet",), 20, 3, 110, 3),
        ("Eye of the Storm", 16, 12, ("borderless", "wall"), 15, 2, 98, 0),
        ("Thunderhead", 16, 13, ("borderless", "dimension"), 14, 2, 95, 0),
        ("Hailstones", 16, 13, ("shield", "wall"), 18, 2, 105, 3),
        ("Cyclone", 16, 13, ("borderless", "portal"), 16, 2, 92, 0),
        ("Tempest", 18, 14, ("borderless", "wall"), 22, 3, 105, 2),
    ]),
    8: ("Ouroboros Peak", "Everything you've learned, all at once, at full speed. The end is the beginning.",
        "#9c4dff", [
        ("The Climb", 16, 13, ("key", "wall"), 15, 2, 92, 0),
        ("Thin Air", 16, 13, ("light", "poison"), 12, 3, 90, 0),
        ("Frozen Steps", 16, 13, ("gate", "statue"), 12, 2, 88, 0),
        ("Snowblind", 17, 13, ("arrow", "light"), 12, 2, 86, 0),
        ("Avalanche", 18, 14, ("magnet", "wall"), 22, 3, 95, 2),
        ("Rope Bridge", 17, 13, ("cheese", "gate", "portal"), 14, 2, 84, 0),
        ("Summit Mines", 17, 13, ("minesweeper", "wall"), 12, 2, 82, 0),
        ("Mirrored Peaks", 16, 13, ("dimension", "twin", "wall"), 14, 2, 80, 0),
        ("Last Light", 18, 14, ("light", "poison", "wall"), 15, 3, 78, 0),
        ("Ouroboros' Door", 18, 14, ("arrow", "gate", "key", "wall"), 18, 2, 85, 1.5),
    ]),
}

# The two challenges of each level (the second and third stars), tuned against a bot that
# plays every level (tools/calibrate_story.py): the targets get tighter chapter by chapter.
CHALLENGES = {
    's1-01': (('time', 8000, 0), ('turns', 23, 0)),  # First Bite
    's1-02': (('time', 14000, 0), ('split', 4, 7000)),  # Clover Patch
    's1-03': (('time', 15500, 0), ('turns', 38, 0)),  # Buttercup Lane
    's1-04': (('time', 17500, 0), ('split', 6, 8000)),  # Dandelion Dash
    's1-05': (('time', 21000, 0), ('turns', 52, 0)),  # Picnic Blanket
    's1-06': (('time', 21500, 0), ('split', 7, 10000)),  # Bumblebee Loop
    's1-07': (('time', 20500, 0), ('turns', 46, 0)),  # Sunflower Field
    's1-08': (('time', 28000, 0), ('split', 9, 13000)),  # Rabbit Run
    's1-09': (('time', 28500, 0), ('turns', 65, 0)),  # Long Grass
    's1-10': (('time', 40000, 0), ('split', 11, 18500)),  # Meadow's Edge
    's2-01': (('time', 20500, 0), ('turns', 42, 0)),  # Locked Pantry
    's2-02': (('time', 22000, 0), ('split', 4, 12000)),  # Apple Cart
    's2-03': (('time', 19000, 0), ('turns', 47, 0)),  # Guardian Bark
    's2-04': (('time', 27000, 0), ('split', 5, 12500)),  # Key Keeper
    's2-05': (('time', 28000, 0), ('turns', 73, 0)),  # Bramble Shield
    's2-06': (('time', 17500, 0), ('split', 9, 8500)),  # Windfall
    's2-07': (('time', 45500, 0), ('turns', 108, 0)),  # Cellar Door
    's2-08': (('time', 41000, 0), ('noshield', 0, 0)),  # Grafting
    's2-09': (('time', 22000, 0), ('turns', 56, 0)),  # Harvest Rush
    's2-10': (('time', 44000, 0), ('noshield', 0, 0)),  # Orchard Gate
    's3-01': (('time', 12500, 0), ('turns', 33, 0)),  # Crumbling Wall
    's3-02': (('time', 8500, 0), ('split', 3, 4000)),  # Stone Garden
    's3-03': (('time', 20000, 0), ('turns', 43, 0)),  # Swiss Steps
    's3-04': (('time', 16500, 0), ('split', 6, 7500)),  # Fallen Columns
    's3-05': (('time', 14000, 0), ('turns', 37, 0)),  # Petrified
    's3-06': (('time', 15500, 0), ('split', 6, 7500)),  # Holey Halls
    's3-07': (('time', 23500, 0), ('turns', 62, 0)),  # Rubble Run
    's3-08': (('time', 12500, 0), ('split', 5, 6000)),  # Statuary
    's3-09': (('time', 22000, 0), ('turns', 65, 0)),  # Collapse
    's3-10': (('time', 14500, 0), ('split', 6, 7500)),  # Heart of the Ruins
    's4-01': (('time', 8500, 0), ('turns', 22, 0)),  # Wormhole
    's4-02': (('time', 11000, 0), ('split', 4, 5000)),  # Signposts
    's4-03': (('time', 15000, 0), ('turns', 36, 0)),  # Tick Tock Gates
    's4-04': (('time', 12000, 0), ('split', 5, 5500)),  # Flip Side
    's4-05': (('time', 11000, 0), ('turns', 31, 0)),  # Rush Hour
    's4-06': (('time', 10000, 0), ('split', 5, 5000)),  # Hall of Mirrors
    's4-07': (('time', 13500, 0), ('turns', 41, 0)),  # Escapement
    's4-08': (('time', 13500, 0), ('split', 6, 5500)),  # Compass Rose
    's4-09': (('time', 13500, 0), ('turns', 40, 0)),  # Mainspring
    's4-10': (('time', 10000, 0), ('split', 7, 5500)),  # The Great Clock
    's5-01': (('time', 7500, 0), ('turns', 21, 0)),  # Toxic Tidbits
    's5-02': (('time', 11000, 0), ('split', 4, 5500)),  # Lantern Light
    's5-03': (('time', 11500, 0), ('turns', 34, 0)),  # Bog Berries
    's5-04': (('time', 9500, 0), ('split', 5, 4500)),  # Firefly Path
    's5-05': (('time', 14500, 0), ('turns', 39, 0)),  # Will-o'-Wisp
    's5-06': (('time', 10000, 0), ('split', 5, 5000)),  # Murky Waters
    's5-07': (('time', 12000, 0), ('turns', 36, 0)),  # Leech Pool
    's5-08': (('time', 20500, 0), ('split', 5, 10500)),  # Night Bloom
    's5-09': (('time', 13000, 0), ('turns', 40, 0)),  # Miasma
    's5-10': (('time', 9500, 0), ('split', 6, 5000)),  # Heart of the Swamp
    's6-01': (('time', 6000, 0), ('turns', 21, 0)),  # Tread Lightly
    's6-02': (('time', 32000, 0), ('split', 1, 14000)),  # Box Pusher
    's6-03': (('time', 13500, 0), ('turns', 35, 0)),  # Phase Shift
    's6-04': (('time', 13000, 0), ('noshield', 0, 0)),  # Sweeper
    's6-05': (('time', 48000, 0), ('turns', 52, 0)),  # Warehouse
    's6-06': (('time', 13500, 0), ('split', 5, 6500)),  # Twin Realms
    's6-07': (('time', 7500, 0), ('turns', 24, 0)),  # Danger Close
    's6-08': (('time', 64000, 0), ('split', 2, 28000)),  # Crate Expectations
    's6-09': (('time', 9000, 0), ('turns', 31, 0)),  # Shifting Sands
    's6-10': (('time', 10500, 0), ('noshield', 0, 0)),  # No Man's Land
    's7-01': (('time', 13500, 0), ('turns', 40, 0)),  # Tailwind
    's7-02': (('time', 10500, 0), ('split', 7, 5000)),  # Wraparound
    's7-03': (('time', 12500, 0), ('turns', 45, 0)),  # Gale
    's7-04': (('time', 9500, 0), ('split', 6, 5000)),  # Lightning Fork
    's7-05': (('time', 10000, 0), ('turns', 36, 0)),  # Downpour
    's7-06': (('time', 10500, 0), ('split', 7, 5000)),  # Eye of the Storm
    's7-07': (('time', 10500, 0), ('turns', 36, 0)),  # Thunderhead
    's7-08': (('time', 15500, 0), ('noshield', 0, 0)),  # Hailstones
    's7-09': (('time', 8000, 0), ('turns', 32, 0)),  # Cyclone
    's7-10': (('time', 13000, 0), ('split', 11, 7500)),  # Tempest
    's8-01': (('time', 25000, 0), ('turns', 85, 0)),  # The Climb
    's8-02': (('time', 8000, 0), ('split', 6, 4000)),  # Thin Air
    's8-03': (('time', 9500, 0), ('turns', 34, 0)),  # Frozen Steps
    's8-04': (('time', 9000, 0), ('split', 6, 4500)),  # Snowblind
    's8-05': (('time', 11000, 0), ('turns', 47, 0)),  # Avalanche
    's8-06': (('time', 7500, 0), ('split', 7, 3500)),  # Rope Bridge
    's8-07': (('time', 8000, 0), ('turns', 35, 0)),  # Summit Mines
    's8-08': (('time', 10500, 0), ('split', 7, 5000)),  # Mirrored Peaks
    's8-09': (('time', 10000, 0), ('turns', 43, 0)),  # Last Light
    's8-10': (('time', 26500, 0), ('split', 9, 13500)),  # Ouroboros' Door
}

# ---- bosses ----------------------------------------------------------------------------

BOSSES = [
    Boss(1, "wiggleton", "Sir Wiggleton", "the Worm Knight",
         "Halt! None shall pass the meadow without besting my noble wriggle!",
         ("#8a94a6", "#d6dbe3", "#c0392b"), "pebbles", "Pebble Toss",
         "Throws a handful of pebbles onto your board: 3 walls.", 16, "boss1",
         14, 11, 3, 140, combo_window=9,
         rewards=(("points", 50_000), ("crate", "gold"), ("item", "skin:st_knight")), skin="skin:st_knight"),
    Boss(2, "mamba", "Mamba Mae", "Queen of the Swamp",
         "Oh, honey. Everything in my orchard is a little bit poisonous.",
         ("#1f7a3a", "#a5d65a", "#f5c518"), "venom", "Venom",
         "Turns fruit on your board into poison for a while.", 15, "boss2",
         14, 11, 3, 132, combo_window=8,
         rewards=(("points", 100_000), ("crate", "diamond"), ("item", "skin:st_mamba")), skin="skin:st_mamba"),
    Boss(3, "coil", "Professor Coil", "the Clockwork Genius",
         "Fascinating. Let us see how you handle a little... rearrangement.",
         ("#8a5a24", "#e8c27a", "#4fc3f7"), "scramble", "Scramble",
         "Bolts arrow tiles to your board that force you to turn.", 14, "boss3",
         15, 12, 3, 125, combo_window=8,
         rewards=(("points", 150_000), ("crate", "diamond"), ("crate", "diamond"), ("item", "skin:st_coil")),
         skin="skin:st_coil"),
    Boss(4, "frostfang", "Frostfang", "the Glacier Wyrm",
         "Cold is patient. Cold always wins.",
         ("#5fb4e8", "#e6f6ff", "#ffffff"), "icewall", "Ice Wall",
         "Freezes a wall of ice across your board. It melts after a while.", 14, "boss4",
         15, 12, 3, 118, combo_window=7,
         rewards=(("points", 250_000), ("crate", "royal"), ("item", "skin:st_frost")), skin="skin:st_frost"),
    Boss(5, "pyra", "Pyra", "the Ember Serpent",
         "Dance for me, little snake. The floor is lava.",
         ("#b3261e", "#ff8a3d", "#ffd54f"), "firestorm", "Firestorm",
         "Rains burning embers on your board. They burn out a few seconds later.", 13, "boss5",
         16, 12, 3, 110, combo_window=7,
         rewards=(("points", 400_000), ("crate", "royal"), ("item", "skin:st_pyra")), skin="skin:st_pyra"),
    Boss(6, "umbra", "Umbra", "the Shadow Coil",
         "You'll never see me coming. You won't see anything at all.",
         ("#2a1b3d", "#5b3f8a", "#b388ff"), "eclipse", "Eclipse",
         "Plunges your board into darkness for 6 seconds.", 12, "boss6",
         16, 12, 3, 104, combo_window=6,
         rewards=(("points", 600_000), ("crate", "royal"), ("crate", "royal"), ("item", "skin:st_umbra")),
         skin="skin:st_umbra"),
    Boss(7, "gearjaw", "Gearjaw", "the Iron Constrictor",
         "PROCESSING... TARGET IS SLOW. INCREASING TARGET SPEED.",
         ("#5a6270", "#aab3bf", "#ff5252"), "overclock", "Overclock",
         "Overclocks the arena: everything runs a third faster for 8 seconds.", 12, "boss7",
         17, 13, 3, 98, combo_window=6,
         rewards=(("points", 1_000_000), ("crate", "royal"), ("crate", "royal"), ("item", "skin:st_gear")),
         skin="skin:st_gear"),
    Boss(8, "ouroboros", "The Ouroboros", "the Endless One",
         "Every story ends where it began. Yours ends here.",
         ("#0f3d2e", "#2fbf71", "#ffd54f"), "chaos", "Endless Cycle",
         "Every trick the other bosses taught you, one after another.", 10, "boss8",
         18, 14, 4, 92, combo_window=5,
         rewards=(("points", 2_500_000), ("crate", "royal"), ("crate", "royal"), ("crate", "royal"),
                  ("item", "skin:st_ouroboros")), skin="skin:st_ouroboros"),
]
BOSS_BY_NUM = {b.num: b for b in BOSSES}

# beating a boss again pays a little (the big rewards are for the first win)
REMATCH_POINTS = {1: 2_000, 2: 3_000, 3: 4_000, 4: 6_000, 5: 8_000, 6: 10_000, 7: 15_000, 8: 25_000}

# snake points for each star (paid once), by chapter
STAR_POINTS = {1: 3_000, 2: 5_000, 3: 8_000, 4: 12_000, 5: 18_000, 6: 25_000, 7: 32_000, 8: 40_000}


def _build() -> tuple:
    chapters = []
    for num, (name, blurb, color, specs) in SPECS.items():
        levels = []
        for i, (lname, w, h, modes, goal, fruit, tick, accel) in enumerate(specs, start=1):
            lid = f"s{num}-{i:02d}"
            levels.append(Level(lid, num, i, lname, w, h, tuple(sorted(modes)), goal, fruit, float(tick),
                                float(accel), tuple(CHALLENGES.get(lid, ()))))
        chapters.append(Chapter(num, name, blurb, color, tuple(levels), BOSS_BY_NUM[num]))
    return tuple(chapters)


# ---- star rules --------------------------------------------------------------------------

def challenge_text(c) -> str:
    kind, a, b = c
    if kind == "time":
        return f"Finish in {a / 1000:.1f} s or less"
    if kind == "turns":
        return f"Finish with {a} turns or fewer"
    if kind == "split":
        return f"Eat {a} fruit in {b / 1000:.1f} s or less"
    if kind == "noshield":
        return "Finish without losing a shield"
    return kind


def stage_ids() -> list[str]:
    """Every stage in order: s1-01 .. s1-10, boss-1, s2-01, ..."""
    out = []
    for ch in CHAPTERS:
        out += [lv.id for lv in ch.levels] + [f"boss-{ch.num}"]
    return out


def unlocked(stage: str, stars: dict[str, int]) -> bool:
    """Can a player with these stars (stage -> stars, bosses 1 when beaten) play this stage?
    Levels unlock one after another; a boss needs its chapter's ten levels; the next
    chapter needs the boss beaten."""
    order = stage_ids()
    if stage not in order:
        return False
    i = order.index(stage)
    return i == 0 or stars.get(order[i - 1], 0) >= 1 and (not stage.startswith("boss-") or all(
        stars.get(lv.id, 0) >= 1 for lv in CHAPTERS[int(stage[5:]) - 1].levels))


@dataclass
class Result:
    finished: bool
    elapsed: float
    turns: int
    shields_lost: int
    splits: list


def replay_level(data: dict) -> tuple[Level, Result]:
    """Replay a story level's run file, counting what the challenges look at. Raises
    ValueError for anything that isn't a story run."""
    if data.get("game") != "opensnake" or data.get("format") != 1:
        raise ValueError("not an OpenSnake run file")
    cid = str(data.get("category", ""))
    level = LEVEL_BY_ID.get(cid[len(STORY_PREFIX):]) if cid.startswith(STORY_PREFIX) else None
    if not level:
        raise ValueError("not a story level")
    claimed = data.get("time_ms")
    if not isinstance(claimed, int) or isinstance(claimed, bool) or not 0 < claimed <= MAX_RUN_MS:
        raise ValueError("the claimed time is missing or too long")
    max_ticks = int(claimed / MIN_TICK_MS) + 2
    run = Run(level.category, int(data["seed"]))
    inputs = [(int(t), str(d)) for t, d in data["inputs"]]
    if any(d not in DIRS for _t, d in inputs) or len(inputs) > 100_000:
        raise ValueError("malformed inputs")
    g = run.game
    i = turns = shields = 0
    while not g.over and g.tick < max_ticks:
        while i < len(inputs) and inputs[i][0] <= g.tick:
            run.input(inputs[i][1])
            i += 1
        if not g.started:
            break
        before = g.snakes[0].dir
        run.step()
        kinds = {e.type for e in g.events}
        if g.snakes[0].dir != before and not kinds & {"arrow", "eat", "portal"}:
            turns += 1  # (a turn the player made: not an arrow tile or a twin flip)
        shields += sum(1 for e in g.events if e.type == "shield")
        g.events.clear()
    if run.finished and round(run.elapsed) != claimed:
        raise ValueError("the claimed time doesn't match the replay")
    return level, Result(run.finished, run.elapsed, turns, shields, run.splits)


def stars_for(level: Level, r: Result) -> list[bool]:
    """Which of the three stars a replayed run earns."""
    if not r.finished:
        return [False, False, False]
    out = [True]
    for kind, a, b in level.challenges:
        if kind == "time":
            out.append(r.elapsed <= a)
        elif kind == "turns":
            out.append(r.turns <= a)
        elif kind == "split":
            out.append(len(r.splits) >= a and r.splits[a - 1] <= b)
        elif kind == "noshield":
            out.append(r.shields_lost == 0)
        else:
            out.append(False)
    return out


def reward_names(rewards) -> list[str]:
    from . import cosmetics as cos
    out = []
    for kind, value in rewards:
        if kind == "points":
            out.append(f"{value:,} snake points")
        elif kind == "crate":
            out.append(cos.CRATE_BY_ID[value].name)
        else:
            out.append(cos.item_name(value))
    return out


def story_def() -> dict:
    """Everything a client needs to show and play story mode."""
    return {"star_points": STAR_POINTS, "chapters": [
        {"num": ch.num, "name": ch.name, "blurb": ch.blurb, "color": ch.color,
         "levels": [{"id": lv.id, "num": lv.num, "name": lv.name, "w": lv.w, "h": lv.h, "modes": list(lv.modes),
                     "goal": lv.goal, "fruit_count": lv.fruit_count, "tick_ms": lv.tick_ms, "accel": lv.accel,
                     "challenges": [list(c) for c in lv.challenges],
                     "challenge_text": [challenge_text(c) for c in lv.challenges]} for lv in ch.levels],
         "boss": {k: getattr(ch.boss, k) for k in ("num", "id", "name", "title", "taunt", "attack", "attack_name",
                                                   "attack_desc", "attack_every", "w", "h", "apples", "tick_ms",
                                                   "combo_window", "skin")}
         | {"colors": list(ch.boss.colors), "modes": list(ch.boss.modes),
            "rewards": [list(r) for r in ch.boss.rewards], "reward_names": reward_names(ch.boss.rewards)}}
        for ch in CHAPTERS]}


CHAPTERS: tuple = ()
LEVEL_BY_ID: dict = {}


def _install() -> None:
    global CHAPTERS, LEVEL_BY_ID
    CHAPTERS = _build()
    LEVEL_BY_ID = {lv.id: lv for ch in CHAPTERS for lv in ch.levels}


_install()
