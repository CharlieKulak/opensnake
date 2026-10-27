"""Core game simulation.

Pure logic with no pygame dependency: the renderer reads the state, the app
feeds input and drains ``events`` for sound and effects.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .registry import MODE_HOOKS

DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}
FRUITS = ["apple", "orange", "cherry", "grape", "strawberry", "lemon", "banana"]


def dir_between(a, b) -> str:
    dx, dy = b[0] - a[0], b[1] - a[1]
    if abs(dx) >= abs(dy):
        return "right" if dx > 0 else "left"
    return "down" if dy > 0 else "up"


@dataclass(slots=True)
class Seg:
    x: int
    y: int
    hole: bool = False


@dataclass(slots=True)
class Snake:
    body: list[Seg]
    dir: str
    queue: list[str] = field(default_factory=list)
    planned: str | None = None  # next direction, locked in half a cell early
    grow: int = 0
    shield: int = 0
    dead: bool = False
    hole_counter: int = 0
    no_interp: bool = False
    moved: bool = False
    team: int = 0            # versus: which team (0 or 1)
    score: int = 0           # versus: fruit this snake has eaten
    name: str = ""           # versus: player name shown above the head
    colors: tuple | None = None  # (head, tail) colour override

    @property
    def head(self) -> Seg:
        return self.body[0]


@dataclass(slots=True)
class Apple:
    x: int
    y: int
    fruit: str
    group: int
    poison: bool = False
    locked: bool = False


@dataclass(slots=True)
class Item:
    x: int
    y: int
    type: str  # "key" | "shield"
    group: int = 0


@dataclass(slots=True)
class Wall:
    x: int
    y: int
    kind: str = "wall"  # "wall" | "statue"
    dim: int | None = None  # dimension mode: which dimension it is solid in


@dataclass(slots=True)
class Gate:
    x: int
    y: int
    period: int
    phase: int
    open: bool = True


@dataclass(slots=True)
class Event:
    type: str
    x: int = 0
    y: int = 0
    fruit: str = ""
    snake: int = -1  # index of the snake it happened to, where that matters


class Game:
    def __init__(self, w: int, h: int, modes=(), apple_count: int = 1, fruit: str = "apple",
                 rng: random.Random | None = None, teams: list[int] | None = None, goal: int = 0):
        """``teams`` turns on versus: one snake per entry, the entry being its team (0 or 1).
        ``goal`` (versus only): first team to eat this many fruit wins; 0 = last team alive."""
        self.w, self.h = w, h
        self.teams = list(teams) if teams else None
        self.goal = goal
        self.modes = set(modes)
        if self.teams:
            self.modes.discard("yinyang")  # the second snake slot is a real player in versus
        self.apple_count = apple_count
        self.fruit = fruit
        self.rng = rng or random.Random()
        self.reset()

    def has(self, mode: str) -> bool:
        return mode in self.modes

    def reset(self) -> None:
        w, h = self.w, self.h
        mid_y = h // 2
        start_x = max(3, w // 4)
        yin = self.has("yinyang")

        self.hooks = [MODE_HOOKS[m] for m in sorted(self.modes) if m in MODE_HOOKS]
        self.mod_state: dict = {}  # free space for mods, keyed however they like
        self.tick = 0
        self.score = 0
        self.over = False
        self.won = False
        self.started = False
        self.events: list[Event] = []
        self.winner: int | None = None  # versus: winning team, None = draw / not over
        self.next_group = 1
        self.dim = 0

        self.walls: dict[tuple[int, int], Wall] = {}
        self.apples: list[Apple] = []
        self.items: list[Item] = []
        self.targets: list[tuple[int, int]] = []
        self.mines: set[tuple[int, int]] = set()
        self.revealed: set[tuple[int, int]] = set()
        self.arrows: dict[tuple[int, int], str] = {}
        self.gates: list[Gate] = []

        row = max(1, mid_y - 2) if yin else mid_y
        if self.teams:
            self.snakes = self._spawn_teams()
        else:
            self.snakes = [self._make_snake(start_x, row, "right")]
            if yin:
                self.snakes.append(self._make_snake(w - 1 - start_x, h - 1 - row, "left"))
        self.prev = self.snapshot()

        if not self.teams and not yin and not self.has("sokoban") and not self.has("portal"):
            # First fruit straight ahead, but not miles away on huge boards.
            self._maybe_lock(self._add_apple(min(w - 1 - start_x, start_x + 8), mid_y))
        self.fill_apples()
        if self.has("gate"):
            self.spawn_gate()
        if self.has("arrow"):
            self.spawn_arrow()
        if self.has("minesweeper"):
            for _ in range(3):
                self.spawn_mine()
        for s in self.snakes:
            for p in s.body:
                self.revealed.add((p.x, p.y))
        for h in self.hooks:
            h.call("on_reset", self)

    @property
    def versus(self) -> bool:
        return bool(self.teams)

    def _spawn_teams(self) -> list[Snake]:
        """Team 0 lines up on the left facing right, team 1 on the right facing left."""
        snakes = [None] * len(self.teams)
        x = min(max(3, self.w // 6), self.w // 2 - 2)
        for team, (col, d) in enumerate(((x, "right"), (self.w - 1 - x, "left"))):
            members = [i for i, t in enumerate(self.teams) if t == team]
            for j, i in enumerate(members):
                y = round((j + 1) * self.h / (len(members) + 1))
                y = min(self.h - 1, max(0, y if team == 0 else self.h - 1 - y))
                sn = self._make_snake(col, y, d)
                sn.team = team
                snakes[i] = sn
        return snakes

    def _make_snake(self, x: int, y: int, d: str) -> Snake:
        dx, dy = DIRS[d]
        return Snake(body=[Seg(x - dx * i, y - dy * i) for i in range(4)], dir=d)

    def snapshot(self) -> list[list[tuple[int, int]]]:
        return [[(p.x, p.y) for p in s.body] for s in self.snakes]

    # ---- input -------------------------------------------------------------

    def input_for(self, index: int, d: str) -> None:
        """Queue a turn for one snake (versus: each player steers their own)."""
        if self.over or not (0 <= index < len(self.snakes)) or d not in DIRS:
            return
        s = self.snakes[index]
        if s.dead:
            return
        last = s.queue[-1] if s.queue else (s.planned or s.dir)
        if d not in (last, OPPOSITE[last]) and len(s.queue) < 3:
            s.queue.append(d)

    def input(self, d: str) -> None:
        if self.over:
            return
        self.started = True
        for i, s in enumerate(self.snakes):
            want = OPPOSITE[d] if i == 1 else d  # the yin-yang twin is point-mirrored
            last = s.queue[-1] if s.queue else (s.planned or s.dir)
            if want in (last, OPPOSITE[last]) or len(s.queue) >= 3:
                continue
            s.queue.append(want)

    # ---- queries -----------------------------------------------------------

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def apple_at(self, x, y) -> Apple | None:
        return next((a for a in self.apples if a.x == x and a.y == y), None)

    def item_at(self, x, y) -> Item | None:
        return next((it for it in self.items if it.x == x and it.y == y), None)

    def gate_at(self, x, y) -> Gate | None:
        return next((g for g in self.gates if g.x == x and g.y == y), None)

    def snake_at(self, x, y) -> bool:
        return any(p.x == x and p.y == y for s in self.snakes for p in s.body)

    def wall_active(self, wall: Wall) -> bool:
        return wall.dim is None or wall.dim == self.dim

    def solid_at(self, x: int, y: int) -> str | None:
        """What would stop a head entering (x, y), or None if passable."""
        for h in self.hooks:
            reason = h.call("blocks", self, x, y)
            if reason:
                return reason
        wall = self.walls.get((x, y))
        if wall and self.wall_active(wall):
            return wall.kind
        gate = self.gate_at(x, y)
        if gate and not gate.open:
            return "gate"
        apple = self.apple_at(x, y)
        if apple and apple.locked:
            return "lock"
        if (x, y) in self.mines:
            return "mine"
        cheese = self.has("cheese")
        for s in self.snakes:
            if s.dead and self.versus:
                continue  # knocked-out snakes are off the board
            # A tail that will move away this tick does not block.
            end = len(s.body) - 1 if (not s.moved and s.grow == 0) else len(s.body)
            for i in range(end):
                p = s.body[i]
                if p.x == x and p.y == y and not (cheese and p.hole and i > 0):
                    return "snake"
        return None

    def is_free(self, x: int, y: int) -> bool:
        k = (x, y)
        return (self.in_bounds(x, y) and k not in self.walls and not self.gate_at(x, y)
                and not self.apple_at(x, y) and not self.item_at(x, y) and k not in self.targets
                and k not in self.mines and k not in self.arrows and not self.snake_at(x, y))

    def head_dist(self, x: int, y: int) -> int:
        return min(abs(s.head.x - x) + abs(s.head.y - y) for s in self.snakes)

    def random_free(self, ok=lambda x, y: True):
        """A uniformly random free cell passing ``ok``, or None if there is none.

        Tries random cells first, which is fast even on a 1000x1000 board, and
        only scans the whole board when it is so crowded that guessing fails.
        """
        taken = {(p.x, p.y) for s in self.snakes for p in s.body}
        taken.update((a.x, a.y) for a in self.apples)
        taken.update((it.x, it.y) for it in self.items)
        taken.update((g.x, g.y) for g in self.gates)
        taken.update(self.targets)

        def free(x, y):
            k = (x, y)
            return k not in taken and k not in self.walls and k not in self.mines and k not in self.arrows

        rand = self.rng.randrange
        for _ in range(200):
            x, y = rand(self.w), rand(self.h)
            if free(x, y) and ok(x, y):
                return x, y
        cells = [(x, y) for y in range(self.h) for x in range(self.w) if free(x, y) and ok(x, y)]
        return self.rng.choice(cells) if cells else None

    def in_path(self, x: int, y: int) -> bool:
        """Cells right in front of a head are kept clear of new hazards."""
        for s in self.snakes:
            dx, dy = DIRS[s.dir]
            for i in range(1, 4):
                if (s.head.x + dx * i, s.head.y + dy * i) == (x, y):
                    return True
        return False

    def hazard_cell(self, extra=lambda x, y: True):
        return (self.random_free(lambda x, y: self.head_dist(x, y) >= 3 and not self.in_path(x, y) and extra(x, y))
                or self.random_free(lambda x, y: self.head_dist(x, y) >= 2 and extra(x, y)))

    # ---- spawning ----------------------------------------------------------

    def _pick_fruit(self) -> str:
        return self.rng.choice(FRUITS) if self.fruit == "mixed" else self.fruit

    def _add_apple(self, x, y, **extra) -> Apple:
        group = extra.pop("group", None)
        if group is None:
            group = self.next_group
            self.next_group += 1
        apple = Apple(x, y, extra.pop("fruit", None) or self._pick_fruit(), group, **extra)
        self.apples.append(apple)
        return apple

    def _spawn_group(self) -> bool:
        def interior(x, y):
            return 0 < x < self.w - 1 and 0 < y < self.h - 1

        if self.has("sokoban"):
            a = self.random_free(lambda x, y: interior(x, y) and self.head_dist(x, y) >= 2)
            if not a:
                return False
            apple = self._add_apple(*a)
            t = self.random_free(lambda x, y: interior(x, y) and (x, y) != a)
            if t:
                self.targets.append(t)
            self._maybe_lock(apple)
            return True

        a = self.random_free(lambda x, y: self.head_dist(x, y) >= 2)
        if not a:
            return False
        apple = self._add_apple(*a)
        if self.has("portal"):
            b = self.random_free(lambda x, y: self.head_dist(x, y) >= 2 and abs(x - a[0]) + abs(y - a[1]) >= 4)
            if not b:
                self.apples.pop()
                return False
            self._add_apple(*b, group=apple.group, fruit=apple.fruit)
        self._maybe_lock(apple)
        return True

    def _maybe_lock(self, apple: Apple) -> None:
        if not self.has("key"):
            return
        k = self.random_free(lambda x, y: self.head_dist(x, y) >= 2)
        if not k:
            return
        for a in self.apples:
            if a.group == apple.group:
                a.locked = True
        self.items.append(Item(k[0], k[1], "key", apple.group))

    def fill_apples(self) -> None:
        def good_groups():
            return len({a.group for a in self.apples if not a.poison})

        guard, limit = 0, self.apple_count * 4 + 50  # stops when the board has no room left
        while good_groups() < self.apple_count and guard < limit:
            guard += 1
            if not self._spawn_group():
                break
        if self.has("poison"):
            limit += self.apple_count * 2
            while sum(a.poison for a in self.apples) < self.apple_count and guard < limit:
                guard += 1
                p = self.random_free(lambda x, y: self.head_dist(x, y) >= 2)
                if not p:
                    break
                self._add_apple(*p, poison=True)
        if not any(not a.poison for a in self.apples):
            self.win()

    def spawn_wall(self, dim=None) -> None:
        c = self.hazard_cell()
        if c:
            self.walls[c] = Wall(c[0], c[1], "wall", dim)

    def spawn_mine(self) -> None:
        c = self.hazard_cell(lambda x, y: (x, y) not in self.revealed)
        if c:
            self.mines.add(c)

    def spawn_gate(self) -> None:
        c = self.hazard_cell()
        if not c:
            return
        period = 16 + self.rng.randrange(3) * 4
        self.gates.append(Gate(c[0], c[1], period, self.rng.randrange(period)))
        self.update_gates()

    def spawn_arrow(self) -> None:
        c = self.hazard_cell()
        if not c:
            return
        # Never point an arrow straight into the edge right next to it.
        ok = [n for n, (dx, dy) in DIRS.items() if self.in_bounds(c[0] + dx * 2, c[1] + dy * 2)]
        self.arrows[c] = self.rng.choice(ok) if ok else "right"

    def spawn_shield(self) -> None:
        if any(it.type == "shield" for it in self.items):
            return
        c = self.random_free(lambda x, y: self.head_dist(x, y) >= 3)
        if c:
            self.items.append(Item(c[0], c[1], "shield"))

    def update_gates(self) -> None:
        for g in self.gates:
            should_open = ((self.tick + g.phase) % g.period) < g.period / 2
            # A gate never shuts on top of the snake.
            g.open = should_open or self.snake_at(g.x, g.y)

    # ---- simulation --------------------------------------------------------

    def plan(self) -> None:
        """Lock in each snake's next turn.

        Called halfway between steps, when the head is visually crossing into
        its cell, so the renderer can curve the head through the corner
        without the path changing under it.
        """
        for s in self.snakes:
            if s.planned is None and s.queue:
                s.planned = s.queue.pop(0)

    def step(self) -> None:
        if self.over or not self.started:
            return
        self.tick += 1
        self.prev = self.snapshot()
        for s in self.snakes:
            s.moved = False
            s.no_interp = False

        targets = {}
        if self.versus:
            # Everyone picks a direction first, so two snakes heading for the same
            # cell are treated alike, whichever of them happens to move first.
            for i, s in enumerate(self.snakes):
                if not s.dead:
                    self._turn(s)
                    targets[i] = self._next_cell(s)
        for s in self.snakes:
            if s.dead and self.versus:
                continue
            if not self.versus:
                self._turn(s)
            self._move_snake(s)
            s.moved = True
            if self.over:
                return
        if self.versus:
            self._head_on(targets)
            self._check_versus_end()
            if self.over:
                return

        if self.has("magnet") and self.tick % 2 == 0:
            self._magnetize()
        if self.has("sokoban"):
            self._check_targets()
        if self.has("gate"):
            self.update_gates()
        if self.has("shield") and self.tick % 60 == 0:
            self.spawn_shield()
        for h in self.hooks:
            h.call("on_step", self)

    def _turn(self, s: Snake) -> None:
        if s.planned:
            s.dir, s.planned = s.planned, None
        elif s.queue:
            s.dir = s.queue.pop(0)

    def _next_cell(self, s: Snake) -> tuple[int, int]:
        dx, dy = DIRS[s.dir]
        x, y = s.head.x + dx, s.head.y + dy
        return self._wrap(x, y) if self.has("borderless") else (x, y)

    def _wrap(self, x, y):
        return x % self.w, y % self.h

    def _move_snake(self, s: Snake) -> None:
        dx, dy = DIRS[s.dir]
        nx, ny = s.head.x + dx, s.head.y + dy
        if not self.in_bounds(nx, ny):
            if self.has("borderless"):
                nx, ny = self._wrap(nx, ny)
            else:
                return self._collide(s, "edge")

        if self.has("sokoban"):
            box = self.apple_at(nx, ny)
            if box and not box.locked and not box.poison:
                px, py = nx + dx, ny + dy
                if not self.in_bounds(px, py) and self.has("borderless"):
                    px, py = self._wrap(px, py)
                blocked = (not self.in_bounds(px, py) or self.solid_at(px, py) or self.apple_at(px, py)
                           or self.snake_at(px, py) or self.item_at(px, py))
                if blocked:
                    return self._collide(s, "push")
                box.x, box.y = px, py
                self.events.append(Event("push", px, py))

        hit = self.solid_at(nx, ny)
        if hit:
            if s.shield > 0 and hit != "lock":
                s.shield -= 1
                self.walls.pop((nx, ny), None)
                self.mines.discard((nx, ny))
                self.events.append(Event("shield", nx, ny))
            else:
                return self._collide(s, hit)

        hole = self.has("cheese") and (s.hole_counter % 5 >= 3)
        s.hole_counter += 1
        s.body.insert(0, Seg(nx, ny, hole))
        if s.grow > 0:
            s.grow -= 1
        else:
            s.body.pop()

        self.revealed.add((nx, ny))

        if (nx, ny) in self.arrows:
            s.dir = self.arrows[(nx, ny)]
            s.queue.clear()
            s.planned = None
            self.events.append(Event("arrow", nx, ny))

        item = self.item_at(nx, ny)
        if item:
            self.items.remove(item)
            if item.type == "key":
                for a in self.apples:
                    if a.group == item.group:
                        a.locked = False
                self.events.append(Event("unlock", nx, ny))
            else:
                s.shield += 1
                self.events.append(Event("shieldup", nx, ny))

        for h in self.hooks:
            h.call("on_move", self, s)

        apple = self.apple_at(nx, ny)
        if apple and (not self.has("sokoban") or apple.poison):
            self._eat(s, apple)

    def _collide(self, s: Snake, what: str) -> None:
        if self.has("peaceful"):
            # Peaceful: the snake just waits until it is pointed somewhere open.
            self.events.append(Event("bump"))
            return
        s.dead = True
        if self.versus:  # only this snake is out; the match goes on
            self.events.append(Event("die", s.head.x, s.head.y, what, self.snakes.index(s)))
            return
        self.over = True
        self.events.append(Event("die", fruit=what))

    # ---- versus --------------------------------------------------------------

    def _head_on(self, targets: dict[int, tuple[int, int]]) -> None:
        """Snakes that went for the same cell this tick are all out, together."""
        cells: dict[tuple[int, int], list[int]] = {}
        for i, cell in targets.items():
            cells.setdefault(cell, []).append(i)
        for group in cells.values():
            if len(group) > 1:
                for i in group:
                    sn = self.snakes[i]
                    if not sn.dead:
                        sn.dead = True
                        self.events.append(Event("die", sn.head.x, sn.head.y, "head-on", i))

    def team_score(self, team: int) -> int:
        return sum(sn.score for sn in self.snakes if sn.team == team)

    def _check_versus_end(self) -> None:
        alive = {sn.team for sn in self.snakes if not sn.dead}
        reached = [t for t in (0, 1) if self.goal and self.team_score(t) >= self.goal]
        if reached:
            self.winner = reached[0] if len(reached) == 1 else None
        elif len(alive) <= 1:
            self.winner = next(iter(alive)) if alive else None
        else:
            return
        self.over = True
        self.events.append(Event("win" if self.winner is not None else "draw"))

    def _eat(self, s: Snake, apple: Apple) -> None:
        self.apples.remove(apple)
        if apple.poison:
            self.events.append(Event("poison", apple.x, apple.y, apple.fruit))
            if self.has("peaceful"):
                del s.body[max(2, len(s.body) - 3):]
                s.no_interp = True
                self.fill_apples()
            else:
                self._collide(s, "poison")
            return

        self.events.append(Event("eat", apple.x, apple.y, apple.fruit))
        if self.has("portal"):
            partner = next((a for a in self.apples if a.group == apple.group), None)
            if partner:
                self.apples.remove(partner)
                s.body[0] = Seg(partner.x, partner.y)
                self.revealed.add((partner.x, partner.y))
                self.events.append(Event("portal", partner.x, partner.y))
        self._scored(s)

    def _scored(self, s: Snake) -> None:
        self.score += 1
        s.score += 1
        # Only the eater grows, except in Yin Yang where both snakes share everything.
        for t in (self.snakes if self.has("yinyang") else [s]):
            t.grow += 1

        if self.has("statue") and len(s.body) > 3:
            for p in s.body[3:]:
                self.walls[(p.x, p.y)] = Wall(p.x, p.y, "statue")
            del s.body[3:]
            s.no_interp = True
        if self.has("twin"):
            s.body.reverse()
            s.dir = dir_between((s.body[1].x, s.body[1].y), (s.body[0].x, s.body[0].y)) \
                if len(s.body) > 1 else OPPOSITE[s.dir]
            s.queue.clear()
            s.planned = None
            s.no_interp = True
        if self.has("wall"):
            self.spawn_wall()
        if self.has("dimension"):
            self.dim = 1 - self.dim
            self.spawn_wall(self.rng.randrange(2))
            self.events.append(Event("dimension"))
        if self.has("minesweeper"):
            self.spawn_mine()
        if self.has("gate") and self.score % 2 == 0:
            self.spawn_gate()
        if self.has("arrow"):
            self.spawn_arrow()
        if self.has("shield") and self.score % 4 == 0:
            self.spawn_shield()
        for h in self.hooks:
            h.call("on_score", self, s)

        self.fill_apples()
        if self.has("poison"):
            # n good + n poison always; eating one swaps which half is which.
            for a in self.apples:
                a.poison = not a.poison

    def _check_targets(self) -> None:
        for a in list(self.apples):
            if (a.x, a.y) in self.targets:
                self.targets.remove((a.x, a.y))
                self.apples.remove(a)
                self.events.append(Event("eat", a.x, a.y, a.fruit))
                self._scored(self.snakes[0])
        # An apple shoved into a corner can never be scored; replace it.
        if self.has("borderless"):
            return
        for a in list(self.apples):
            if a.x in (0, self.w - 1) and a.y in (0, self.h - 1):
                self.apples.remove(a)
                if self.targets:
                    self.targets.pop(0)
                self.events.append(Event("poof", a.x, a.y))
                self.fill_apples()

    def _magnetize(self) -> None:
        for a in list(self.apples):
            if a.locked or a.poison:
                continue
            best = None
            for s in self.snakes:
                dist = max(abs(s.head.x - a.x), abs(s.head.y - a.y))
                if 0 < dist <= 3 and (best is None or dist < best[1]):
                    best = (s, dist)
            if not best:
                continue
            s = best[0]
            sx = (s.head.x > a.x) - (s.head.x < a.x)
            sy = (s.head.y > a.y) - (s.head.y < a.y)
            steps = [(sx, 0), (0, sy)] if abs(s.head.x - a.x) >= abs(s.head.y - a.y) else [(0, sy), (sx, 0)]
            for mx, my in steps:
                if not mx and not my:
                    continue
                tx, ty = a.x + mx, a.y + my
                if (tx, ty) == (s.head.x, s.head.y):
                    if self.has("sokoban"):
                        continue
                    a.x, a.y = tx, ty
                    self._eat(s, a)
                    return  # apple list changed
                if self.is_free(tx, ty):
                    a.x, a.y = tx, ty
                    break

    def win(self) -> None:
        if self.over:
            return
        if self.versus:  # board full: the team with more fruit wins
            a, b = self.team_score(0), self.team_score(1)
            self.winner = None if a == b else (0 if a > b else 1)
            self.over = True
            self.events.append(Event("win" if self.winner is not None else "draw"))
            return
        self.won = True
        self.over = True
        self.events.append(Event("win"))

    def mine_count(self, x: int, y: int) -> int:
        """Mines in the 8 cells around (x, y), for minesweeper hints."""
        return sum((x + dx, y + dy) in self.mines
                   for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy)


# ---- network state --------------------------------------------------------------
# The multiplayer server runs the real game and sends this state every tick;
# clients load it into their own Game object, which the normal renderer draws.

def game_to_state(g: Game) -> dict:
    return {
        "w": g.w, "h": g.h, "tick": g.tick, "over": g.over, "winner": g.winner, "started": g.started,
        "goal": g.goal, "modes": sorted(g.modes), "dim": g.dim,
        "snakes": [{"b": [[p.x, p.y, int(p.hole)] for p in s.body], "d": s.dir, "dead": s.dead,
                    "team": s.team, "score": s.score, "shield": s.shield, "name": s.name,
                    "ni": s.no_interp} for s in g.snakes],
        "apples": [[a.x, a.y, a.fruit, a.group, int(a.poison), int(a.locked)] for a in g.apples],
        "walls": [[w.x, w.y, w.kind, w.dim] for w in g.walls.values()],
        "items": [[it.x, it.y, it.type, it.group] for it in g.items],
        "events": [[e.type, e.x, e.y, e.fruit, e.snake] for e in g.events],
    }


def apply_state(g: Game, st: dict) -> None:
    """Load a server state into a client-side Game (the previous state becomes prev)."""
    g.prev = g.snapshot()
    g.w, g.h = st["w"], st["h"]
    g.tick, g.over, g.winner, g.started = st["tick"], st["over"], st["winner"], st["started"]
    g.goal, g.dim = st.get("goal", 0), st.get("dim", 0)
    g.modes = set(st.get("modes", []))
    snakes = []
    for i, d in enumerate(st["snakes"]):
        old = g.snakes[i] if i < len(g.snakes) else None
        sn = Snake(body=[Seg(x, y, bool(h)) for x, y, h in d["b"]], dir=d["d"], dead=d["dead"],
                   team=d["team"], score=d["score"], shield=d["shield"], name=d.get("name", ""),
                   no_interp=d.get("ni", False), colors=old.colors if old else None)
        snakes.append(sn)
    if len(snakes) != len(g.snakes):
        g.prev = [[(p.x, p.y) for p in sn.body] for sn in snakes]
    g.snakes = snakes
    g.teams = [sn.team for sn in snakes]
    g.apples = [Apple(x, y, fruit, group, bool(poison), bool(locked)) for x, y, fruit, group, poison, locked in st["apples"]]
    g.walls = {(x, y): Wall(x, y, kind, dim) for x, y, kind, dim in st["walls"]}
    g.items = [Item(x, y, t, group) for x, y, t, group in st["items"]]
    g.events.extend(Event(t, x, y, fruit, sn) for t, x, y, fruit, sn in st.get("events", []))
