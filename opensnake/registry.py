"""Shared registry that mods add to.

Kept free of pygame so ``game.py`` can use it without pulling in graphics.
"""

from __future__ import annotations

import sys
import traceback
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ModeHooks:
    """Callbacks a mod mode can provide. Every one is optional.

    on_reset(game)            new game set up
    on_step(game)             after every snake has moved this tick
    on_move(game, snake)      after one snake moved into a new cell
    on_score(game, snake)     a fruit was scored (before new fruit spawns)
    blocks(game, x, y)        return a reason string if (x, y) is solid, else None
    draw(surface, game, view) draw extra things on the board (see render.View)
    icon(surface, size)       draw the menu icon onto a size x size surface
    """
    mode_id: str
    mod: str
    on_reset: Callable | None = None
    on_step: Callable | None = None
    on_move: Callable | None = None
    on_score: Callable | None = None
    blocks: Callable | None = None
    draw: Callable | None = None
    icon: Callable | None = None
    broken: set = field(default_factory=set)

    def call(self, name: str, *args):
        """Run one hook; a hook that raises is reported once and switched off."""
        fn = getattr(self, name)
        if fn is None or name in self.broken:
            return None
        try:
            return fn(*args)
        except Exception:  # a broken mod must not crash the game
            self.broken.add(name)
            print(f"opensnake: mod '{self.mod}' hook {self.mode_id}.{name} failed and was disabled:",
                  file=sys.stderr)
            traceback.print_exc()
            return None


MODE_HOOKS: dict[str, ModeHooks] = {}
SOUNDS: dict[str, str] = {}  # sound name -> file path, added by mods
