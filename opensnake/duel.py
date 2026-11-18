"""Boss duels: you and a boss each have your own board, side by side.

Eat fruit in quick succession to build a combo. When a combo ends it attacks: it first
cancels junk heading your way, and whatever's left drops walls ("junk") on the other
board a moment later. Every boss also has a signature attack it uses every few seconds.
The first snake to crash loses. After a few minutes, sudden death rains junk on both.

The server runs duels (a boss is a computer snake, see bots.py), so this only needs the
rules: no client has to reproduce them.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import bots
from .game import DIRS, Event, Game, Wall, game_to_state
from .story import Boss

YOU, BOSS = 0, 1
WARN_SECONDS = 2.0        # how long junk waits in the tray before it drops
FORCE_DROP_SECONDS = 4.0  # junk drops even mid-combo after this long
MAX_DROP = 8              # junk walls dropped in one go (the rest follow)
SUDDEN_DEATH_SECONDS = 150
SUDDEN_DEATH_EVERY = 3.0  # seconds between sudden-death junk
SIGNATURES = ["pebbles", "venom", "scramble", "icewall", "firestorm", "eclipse", "overclock"]
FOG_SECONDS, OVERCLOCK_SECONDS, VENOM_SECONDS, ARROW_SECONDS = 6.0, 8.0, 6.0, 8.0
ICE_SECONDS, FIRE_SECONDS = 7.0, 4.0
# How sloppy each boss is: the chance it doesn't bother steering this move (only when
# straight ahead is safe), so early bosses gather fruit slowly; and of wandering.
BOT_SLOPPY = {"easy": 0.35, "normal": 0.15, "hard": 0.0}  # online battles' computer players
SLOPPY = {"boss1": 0.45, "boss2": 0.38, "boss3": 0.32, "boss4": 0.26, "boss5": 0.2, "boss6": 0.14,
          "boss7": 0.08, "boss8": 0.0}


def chain_power(chain: int) -> int:
    """Junk sent by a combo of this many fruit: 1, 2, 4, 6, 9, 12, 16, then 4 more each."""
    table = [0, 1, 2, 4, 6, 9, 12, 16]
    return table[chain] if chain < len(table) else 16 + 4 * (chain - 7)


@dataclass
class Side:
    game: Game
    chain: int = 0           # fruit in the combo going now
    chain_left: int = 0      # moves left to keep it going
    incoming: list = field(default_factory=list)   # [amount, drop at tick, force at tick]
    temp: dict = field(default_factory=dict)       # (x, y) -> tick it melts (ice and embers)
    arrows: dict = field(default_factory=dict)     # (x, y) -> tick it goes
    venom: list = field(default_factory=list)      # [(x, y), tick it wears off]
    fog_until: int = 0
    overclock_until: int = 0
    best_chain: int = 0
    sent: int = 0

    @property
    def pending(self) -> int:
        return sum(a for a, _d, _f in self.incoming)


class Battle:
    """Two to four snakes, each on their own board. Combos send junk to an opponent: the one
    with the least junk already on its way (so it spreads round), and the last snake still
    going wins."""

    def __init__(self, n: int, w: int, h: int, modes=(), apples: int = 3, tick_ms: float = 120.0,
                 combo_window: int = 8, seed: int | None = None, names=None):
        seed = seed if seed is not None else random.randrange(2 ** 31)
        root = random.Random(seed)
        self.sides = []
        for i in range(n):
            g = Game(w, h, modes, apples, "apple", random.Random(root.getrandbits(32)))
            g.snakes[0].name = (names or [])[i] if i < len(names or []) else f"Player {i + 1}"
            self.sides.append(Side(g))
        self.rng = random.Random(root.getrandbits(32))       # junk and attacks
        self.bot_rng = random.Random(root.getrandbits(32))   # computer players' steering
        self.base_tick_ms = tick_ms
        self.combo_window = combo_window
        self.tick = 0
        self.per_second = 1000.0 / tick_ms
        self.next_sudden = self.secs(SUDDEN_DEATH_SECONDS)
        self.over = False
        self.winner: int | None = None
        self.out: list[int] = []      # sides in the order they crashed
        self.events: list[list] = []  # this move's events, for the animations

    def speed(self) -> float:
        """How long this move lasts, as a share of the normal speed."""
        return 1.0

    def secs(self, s: float) -> int:
        return max(1, round(s * self.per_second))

    def start(self) -> None:
        for s in self.sides:
            s.game.started = True

    def alive(self) -> list[int]:
        return [i for i, s in enumerate(self.sides) if not s.game.over]

    def steer_bot(self, i: int, level: str, sloppy: float = 0.0) -> None:
        """A computer player picks its next turn on board i."""
        g = self.sides[i].game
        if g.over:
            return
        s = g.snakes[0]
        d = bots.choose(g, 0, self.bot_rng, level)
        dx, dy = DIRS[s.planned or s.dir]
        safe_ahead = g.in_bounds(s.head.x + dx, s.head.y + dy) and not g.solid_at(s.head.x + dx, s.head.y + dy)
        if d and not (safe_ahead and self.bot_rng.random() < sloppy):
            g.input_for(0, d)

    # ---- a move -------------------------------------------------------------------------

    def steer(self) -> None:
        """Computer players' turns before a move (a boss, in a duel)."""

    def extra(self) -> None:
        """Anything else that happens on a move (a boss's signature attacks)."""

    def step(self) -> None:
        if self.over:
            return
        self.tick += 1
        self.events = []
        self.steer()
        for i in range(len(self.sides)):
            self._move(i)
        for i in range(len(self.sides)):
            self._combo(i)
            self._drop(i)
            self._expire(i)
        if not self._ended():
            self.extra()
        if self.tick >= self.next_sudden:
            self.next_sudden = self.tick + self.secs(SUDDEN_DEATH_EVERY)
            if self.tick == self.secs(SUDDEN_DEATH_SECONDS):
                self.events.append(["sudden", -1, 0])
            for i in range(len(self.sides)):
                self._place_junk(i, 2)
        self._check_end()

    def _move(self, i: int) -> None:
        side = self.sides[i]
        g = side.game
        if g.over:
            return
        score = g.score
        g.step()
        eaten = g.score - score
        if eaten:
            side.chain = side.chain + eaten if side.chain_left > 0 else eaten
            side.chain_left = self.combo_window
            side.best_chain = max(side.best_chain, side.chain)
            self.events.append(["chain", i, side.chain])

    def _combo(self, i: int) -> None:
        side = self.sides[i]
        if side.chain_left > 0:
            side.chain_left -= 1
            if side.chain_left == 0 and side.chain:
                self.attack(i, chain_power(side.chain))
                side.chain = 0

    def target(self, i: int) -> int | None:
        """Who side i's junk goes to: the opponent still going with the least on its way."""
        others = [j for j in self.alive() if j != i]
        if not others:
            return None
        return min(others, key=lambda j: (self.sides[j].pending, (j - i) % len(self.sides)))

    def attack(self, i: int, power: int) -> None:
        """Side i attacks: cancel its own incoming junk first, send the rest across."""
        side = self.sides[i]
        to = self.target(i)
        cancelled = 0
        while power > 0 and side.incoming:
            take = min(power, side.incoming[0][0])
            side.incoming[0][0] -= take
            power -= take
            cancelled += take
            if side.incoming[0][0] == 0:
                side.incoming.pop(0)
        if power > 0 and to is not None:
            self.sides[to].incoming.append([power, self.tick + self.secs(WARN_SECONDS),
                                            self.tick + self.secs(FORCE_DROP_SECONDS)])
            side.sent += power
        self.events.append(["attack", i, power if to is not None else 0, cancelled, to if to is not None else -1])

    def _drop(self, i: int) -> None:
        side = self.sides[i]
        if not side.incoming or side.game.over:
            return
        amount, drop_at, force_at = side.incoming[0]
        if self.tick >= force_at or (self.tick >= drop_at and side.chain_left == 0):
            n = min(amount, MAX_DROP)
            placed = self._place_junk(i, n)
            side.incoming[0][0] -= n
            if side.incoming[0][0] <= 0:
                side.incoming.pop(0)
            if placed:
                self.events.append(["junk", i, placed])

    def _ok_cell(self, g: Game):
        head = g.snakes[0].head
        dx, dy = DIRS[g.snakes[0].planned or g.snakes[0].dir]
        ahead = {(head.x + dx * k, head.y + dy * k) for k in range(1, 5)}
        return lambda x, y: abs(x - head.x) + abs(y - head.y) > 3 and (x, y) not in ahead

    def _free_cell(self, g: Game, ok):
        """A random cell that's free and passes ``ok`` (from the duel's own random numbers)."""
        cells = [(x, y) for y in range(g.h) for x in range(g.w) if g.is_free(x, y) and ok(x, y)]
        return self.rng.choice(cells) if cells else None

    def _place_junk(self, i: int, n: int, temp_seconds: float = 0) -> int:
        g = self.sides[i].game
        if g.over:
            return 0
        ok = self._ok_cell(g)
        placed = 0
        for _ in range(n):
            c = self._free_cell(g, ok)
            if not c:
                break
            g.walls[c] = Wall(c[0], c[1], "wall")
            if temp_seconds:
                self.sides[i].temp[c] = self.tick + self.secs(temp_seconds)
            placed += 1
        return placed

    def _expire(self, i: int) -> None:
        side, g = self.sides[i], self.sides[i].game
        for c, until in list(side.temp.items()):
            if self.tick >= until:
                g.walls.pop(c, None)
                del side.temp[c]
        for c, until in list(side.arrows.items()):
            if self.tick >= until:
                g.arrows.pop(c, None)
                del side.arrows[c]
        keep = []
        for c, until in side.venom:
            a = g.apple_at(*c)
            if self.tick >= until:
                if a:
                    a.poison = False
            elif a:
                keep.append((c, until))
        side.venom = keep

    # ---- the end ------------------------------------------------------------------------

    def _ended(self) -> bool:
        return len(self.alive()) <= 1

    def _check_end(self) -> None:
        for i, s in enumerate(self.sides):
            if s.game.over and i not in self.out:
                self.out.append(i)
                self.events.append(["out", i, len(self.sides) - len(self.out) + 1])
        alive = self.alive()
        won = [i for i, s in enumerate(self.sides) if s.game.won]
        if won:
            self.winner = won[0]  # (filled the board!)
        elif len(alive) == 1:
            self.winner = alive[0]
        elif not alive:
            self.winner = None  # (everyone left crashed on the same move: a draw)
        else:
            return
        self.over = True
        self.events.append(["over", -1 if self.winner is None else self.winner, 0])

    def place(self, i: int) -> int:
        """Where side i finished: 1 for the winner, then by how long they lasted."""
        if self.winner == i:
            return 1
        if i in self.out:
            return len(self.sides) - self.out.index(i)
        return 1

    def forfeit(self, i: int) -> None:
        """Side i gives up (left the match): its snake is out."""
        g = self.sides[i].game
        if not g.over:
            g.over = True
            g.snakes[0].dead = True
        self._check_end()

    # ---- what the clients see -----------------------------------------------------------

    def side_state(self, i: int) -> dict:
        s = self.sides[i]
        st = game_to_state(s.game)
        st.update({
            "arrows": [[x, y, d] for (x, y), d in s.game.arrows.items()],
            "temp": [[x, y, max(0, until - self.tick)] for (x, y), until in s.temp.items()],
            "chain": s.chain, "chain_left": s.chain_left,
            "incoming": [[a, max(0, d - self.tick)] for a, d, _f in s.incoming],
            "fog": max(0, s.fog_until - self.tick), "overclock": max(0, s.overclock_until - self.tick),
            "best_chain": s.best_chain, "sent": s.sent, "out": i in self.out,
        })
        return st

    def state(self) -> dict:
        return {"tick": self.tick, "over": self.over, "tick_ms": self.base_tick_ms * self.speed(), "winner": self.winner,
                "sides": [self.side_state(i) for i in range(len(self.sides))], "events": self.events,
                "combo_window": self.combo_window, "sudden": self.tick >= self.secs(SUDDEN_DEATH_SECONDS)}

    def clear_events(self) -> None:
        for s in self.sides:
            s.game.events.clear()


class Duel(Battle):
    """Story mode: you against a boss, which also has a signature attack."""

    def __init__(self, boss: Boss, seed: int | None = None):
        self.boss = boss
        super().__init__(2, boss.w, boss.h, boss.modes, boss.apples, boss.tick_ms, boss.combo_window, seed,
                         ["You", boss.name])
        self.next_signature = self.secs(boss.attack_every)
        self.signature_i = 0

    @property
    def you(self) -> Game:
        return self.sides[YOU].game

    def speed(self) -> float:
        """Overclock: everything runs a third faster for a while."""
        return 0.75 if self.sides[YOU].overclock_until > self.tick else 1.0

    def steer(self) -> None:
        self.steer_bot(BOSS, self.boss.bot, SLOPPY.get(self.boss.bot, 0.0))

    def extra(self) -> None:
        if self.tick >= self.next_signature:
            self._signature()
            self.next_signature = self.tick + self.secs(max(6, self.boss.attack_every))

    def _check_end(self) -> None:
        you, boss = self.sides[YOU].game, self.sides[BOSS].game
        if you.over and not you.won:
            self.winner = BOSS  # (crashing on the same move as the boss still loses)
        elif you.won or boss.over:
            self.winner = YOU if (you.won or not boss.won) else BOSS
        else:
            return
        self.over = True
        self.events.append(["over", self.winner, 0])

    def forfeit(self, i: int = YOU) -> None:
        if not self.over:
            self.over, self.winner = True, BOSS

    def state(self) -> dict:
        return super().state() | {"next_signature": max(0, self.next_signature - self.tick)}

    # ---- the boss's signature attacks ---------------------------------------------------

    def _signature(self) -> None:
        kind = self.boss.attack
        if kind == "chaos":
            kind = SIGNATURES[self.signature_i % len(SIGNATURES)]
            self.signature_i += 1
        self.events.append(["signature", BOSS, 0, kind])
        side, g = self.sides[YOU], self.sides[YOU].game
        if kind == "pebbles":
            side.incoming.append([3, self.tick + self.secs(1.0), self.tick + self.secs(1.0)])
        elif kind == "venom":
            for a in [a for a in g.apples if not a.poison][: max(1, len(g.apples) - 1)]:
                a.poison = True
                side.venom.append(((a.x, a.y), self.tick + self.secs(VENOM_SECONDS)))
        elif kind == "scramble":
            ok = self._ok_cell(g)
            for _ in range(4):
                c = self._free_cell(g, ok)
                if c:
                    g.arrows[c] = self.rng.choice(list(DIRS))
                    side.arrows[c] = self.tick + self.secs(ARROW_SECONDS)
        elif kind == "icewall":
            ok = self._ok_cell(g)
            if self.rng.random() < 0.5:
                y = self.rng.randrange(g.h)
                cells = [(x, y) for x in range(g.w)]
            else:
                x = self.rng.randrange(g.w)
                cells = [(x, y) for y in range(g.h)]
            gap = self.rng.randrange(len(cells) - 2)
            for k, c in enumerate(cells):
                if gap <= k < gap + 3 or not g.is_free(*c) or not ok(*c):
                    continue  # (always a gap to get through)
                g.walls[c] = Wall(c[0], c[1], "wall")
                side.temp[c] = self.tick + self.secs(ICE_SECONDS)
        elif kind == "firestorm":
            self._place_junk(YOU, 6, FIRE_SECONDS)
        elif kind == "eclipse":
            side.fog_until = self.tick + self.secs(FOG_SECONDS)
        elif kind == "overclock":
            side.overclock_until = self.tick + self.secs(OVERCLOCK_SECONDS)


def replay_duel(boss: Boss, seed: int, inputs, max_ticks: int = 40_000) -> tuple["Duel", float]:
    """Replay a boss duel played on a player's own computer from its seed and their turns
    ([move, direction], as they pressed them): (the duel, the least real ms it could have taken)."""
    d = Duel(boss, seed)
    d.start()
    turns = [(int(t), str(m)) for t, m in inputs]
    if any(m not in DIRS for _t, m in turns) or len(turns) > 100_000:
        raise ValueError("unknown moves")
    i = 0
    least = 0.0
    while not d.over and d.tick < max_ticks:
        while i < len(turns) and turns[i][0] <= d.tick:
            d.you.input_for(0, turns[i][1])
            i += 1
        least += d.boss.tick_ms * d.speed()
        d.step()
        d.clear_events()
    return d, least


def simulate(boss: Boss, seed: int, you_level: str = "hard", max_ticks: int = 20_000) -> Duel:
    """Play a duel with a bot in your seat (for tests and tuning)."""
    d = Duel(boss, seed)
    d.start()
    rng = random.Random(seed + 99)
    while not d.over and d.tick < max_ticks:
        g = d.you
        if not g.over:
            m = bots.choose(g, 0, rng, you_level)
            if m:
                g.input_for(0, m)
        d.step()
        d.clear_events()
    return d


__all__ = ["Battle", "Duel", "Side", "chain_power", "simulate", "YOU", "BOSS", "Event"]
