"""Computer players for versus matches.

Each tick a bot looks for the shortest path to the nearest fruit it can eat
(or the key that opens it), then checks that the move doesn't box it into a
space smaller than its own body. Easy bots sometimes wander; Normal and Hard
bots are more careful near cells another snake's head could move into.
"""

from __future__ import annotations

from collections import deque

from .game import DIRS, OPPOSITE

LEVELS = ["easy", "normal", "hard"]
LEVEL_NAMES = {"easy": "Easy", "normal": "Normal", "hard": "Hard"}
WANDER = {"easy": 0.2, "normal": 0.05, "hard": 0.0}   # chance of an aimless (but safe) move
DANGER = {"easy": 12, "normal": 25, "hard": 60}         # how hard it avoids possible head-ons
BOT_NAMES = ["Ada", "Basil", "Cleo", "Dex", "Echo", "Fern", "Gus", "Hiss", "Ivy", "Jinx", "Kai", "Luna",
             "Milo", "Nyx", "Ozzy", "Pip", "Quill", "Rex", "Sly", "Tess", "Vex", "Wren", "Zed"]


def _blocked(game) -> set:
    """Cells a head can't move into this tick."""
    out = {k for k, w in game.walls.items() if game.wall_active(w)}
    out.update((g.x, g.y) for g in game.gates if not g.open)
    out.update((a.x, a.y) for a in game.apples if a.locked)
    cheese = game.has("cheese")
    for s in game.snakes:
        if s.dead:
            continue
        end = len(s.body) - 1 if (not s.moved and s.grow == 0) else len(s.body)  # tails move away
        for i in range(end):
            p = s.body[i]
            if not (cheese and p.hole and i > 0):
                out.add((p.x, p.y))
    return out


def choose(game, index: int, rng, level: str = "normal") -> str | None:
    """The direction bot ``index`` wants to go next, or None to keep going."""
    s = game.snakes[index]
    if s.dead or game.over:
        return None
    w, h = game.w, game.h
    wrap = game.has("borderless")
    current = s.planned or s.dir
    blocked = _blocked(game)

    def step(cell, d):
        dx, dy = DIRS[d]
        x, y = cell[0] + dx, cell[1] + dy
        if wrap:
            return x % w, y % h
        return (x, y) if 0 <= x < w and 0 <= y < h else None

    head = (s.head.x, s.head.y)
    moves = []
    for d in DIRS:
        if d == OPPOSITE[current]:
            continue
        c = step(head, d)
        if c is not None and c not in blocked:
            moves.append((d, c))
    if not moves:
        return None

    # Cells another snake's head might move into next: a head-on there knocks both out.
    danger = set()
    for j, o in enumerate(game.snakes):
        if j != index and not o.dead:  # teammates too: they knock each other out the same way
            for d in DIRS:
                c = step((o.head.x, o.head.y), d)
                if c is not None:
                    danger.add(c)

    # What's worth going for.
    locked = {a.group for a in game.apples if a.locked}
    targets = {(a.x, a.y) for a in game.apples if not a.poison and not a.locked}
    targets.update((it.x, it.y) for it in game.items
                   if (it.type == "key" and it.group in locked) or it.type == "shield")

    # Shortest path to the nearest target, remembering the first move.
    first = {}
    queue = deque()
    for d, c in moves:
        if c not in first:
            first[c] = d
            queue.append(c)
    goal_dir = None
    while queue:
        c = queue.popleft()
        if c in targets:
            goal_dir = first[c]
            break
        for d in DIRS:
            n = step(c, d)
            if n is not None and n not in blocked and n not in first:
                first[n] = first[c]
                queue.append(n)

    need = len(s.body) + 2

    def room(start):
        """Free cells reachable from ``start`` (stopping once there's clearly enough)."""
        seen = {start}
        todo = [start]
        while todo and len(seen) < need + 8:
            c = todo.pop()
            for d in DIRS:
                n = step(c, d)
                if n is not None and n not in blocked and n not in seen:
                    seen.add(n)
                    todo.append(n)
        return len(seen)

    scored = []
    for d, c in moves:
        space = room(c)
        score = min(space, need) * 10
        if d == goal_dir:
            score += 5
        if c in danger:
            score -= DANGER.get(level, 25)
        if d == current:
            score += 1  # don't wiggle for nothing
        scored.append((score, d))
    if rng.random() < WANDER.get(level, 0.05):
        safe = [d for sc, d in scored if sc >= need * 10 - 5]
        if safe:
            return rng.choice(safe)
    best = max(sc for sc, _d in scored)
    return rng.choice([d for sc, d in scored if sc == best])
