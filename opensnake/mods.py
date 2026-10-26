"""Mod loading and the API mods use.

A mod is a Python file (``my_mod.py``) or a folder with an ``__init__.py``
placed in a mods folder. It must define ``setup(api)``, which receives a
``ModAPI`` and uses it to register new modes, fruits and sounds.

Mods are ordinary Python code with full access to your computer, so only
install mods you trust. See README.md for the full guide.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
import traceback
from pathlib import Path

from . import game as game_module
from . import modes as modes_module
from . import render as render_module
from .assets import config_dir
from .registry import MODE_HOOKS, SOUNDS, ModeHooks

API_VERSION = 1
_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

# (mod name, error message or None) for every mod that was found.
LOADED: list[tuple[str, str | None]] = []


class ModAPI:
    """Handed to a mod's ``setup(api)``."""

    api_version = API_VERSION
    game = game_module      # Game, Seg, Wall, Item, Apple, Event, DIRS, ...
    render = render_module  # drawing helpers: aa_disc, bezier, ellipse_poly, mix, ...

    def __init__(self, name: str, folder: Path):
        self.name = name
        self.folder = folder

    def add_mode(self, mode_id: str, name: str, description: str, *, on_reset=None, on_step=None,
                 on_move=None, on_score=None, blocks=None, draw=None, icon=None, conflicts=()):
        """Register a game mode. It shows up in the menu and mixes with the others."""
        if not _ID.match(mode_id):
            raise ValueError(f"mode id {mode_id!r} must be lowercase letters, digits or _ (max 32)")
        if mode_id in modes_module.MODE_NAMES:
            raise ValueError(f"mode id {mode_id!r} is already taken")
        modes_module.MODES.append((mode_id, name, description))
        modes_module.MODE_NAMES[mode_id] = name
        modes_module.MODE_DESCS[mode_id] = description
        modes_module.MODES_ORDER.append(mode_id)
        for other in conflicts:
            modes_module.CONFLICTS.append((mode_id, other))
        MODE_HOOKS[mode_id] = ModeHooks(mode_id, self.name, on_reset, on_step, on_move, on_score,
                                        blocks, draw, icon)

    def add_fruit(self, name: str, label: str, draw, color=(220, 60, 60)):
        """Register a fruit. ``draw(surface, x, y, r)`` paints it centred at (x, y)
        with radius r; it is called once per size and cached."""
        if not _ID.match(name):
            raise ValueError(f"fruit name {name!r} must be lowercase letters, digits or _")
        if name in game_module.FRUITS or name in ("mixed", "poison"):
            raise ValueError(f"fruit {name!r} already exists")
        game_module.FRUITS.append(name)
        labels = modes_module.FRUIT_LABELS
        mixed = labels.pop("mixed")
        labels[name] = label
        labels["mixed"] = mixed  # keep "Mixed" last in the menu
        render_module.FRUIT_DRAW[name] = draw
        render_module.FRUIT_COLORS[name] = tuple(color)

    def add_sound(self, name: str, filename: str):
        """Register a sound file (relative to the mod's folder). Play it by
        appending ``api.game.Event(name)`` to ``game.events``. Using a built-in
        name such as "eat" replaces that sound."""
        path = (self.folder / filename).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        SOUNDS[name] = str(path)

    def asset(self, filename: str) -> Path:
        """Path to a file shipped inside the mod's folder."""
        return self.folder / filename

    def log(self, *parts) -> None:
        print(f"[mod {self.name}]", *parts, file=sys.stderr)


def default_dirs(cli_dir: str | None = None) -> list[Path]:
    dirs = [cli_dir, os.environ.get("OPENSNAKE_MODS"), config_dir() / "mods"]
    return [Path(d).expanduser() for d in dirs if d]


def iter_mods(dirs):
    """(name, entry point file, folder, package search path) for every mod found,
    without running any of them. Earlier folders win on name clashes."""
    seen = set()
    for d in dirs:
        if not d.is_dir():
            continue
        for entry in sorted(d.iterdir()):
            if entry.name.startswith(("_", ".")):
                continue
            if entry.is_file() and entry.suffix == ".py":
                found = (entry.stem, entry, d, None)
            elif entry.is_dir() and (entry / "__init__.py").is_file():
                found = (entry.name, entry / "__init__.py", entry, [str(entry)])
            else:
                continue
            if found[0] not in seen:
                seen.add(found[0])
                yield found


def describe_mod(path: Path) -> str:
    """First line of a mod's docstring, read without running the mod."""
    import ast
    try:
        doc = ast.get_docstring(ast.parse(path.read_text()))
    except (OSError, SyntaxError, ValueError):
        return ""
    return (doc or "").strip().split("\n")[0][:120]


def load_mods(dirs, disabled=()) -> list[tuple[str, str | None]]:
    """Import every mod in ``dirs`` except the ``disabled`` names."""
    seen = {name for name, _ in LOADED}
    disabled = set(disabled)
    for name, path, folder, pkg in iter_mods(dirs):
        if name in seen or name in disabled:
            continue
        seen.add(name)
        try:
            spec = importlib.util.spec_from_file_location(f"opensnake_mods.{name}", path,
                                                          submodule_search_locations=pkg)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            setup = getattr(module, "setup", None)
            if not callable(setup):
                raise RuntimeError("the mod has no setup(api) function")
            setup(ModAPI(name, folder))
            LOADED.append((name, None))
        except Exception as e:  # report and carry on without this mod
            print(f"opensnake: mod '{name}' failed to load:", file=sys.stderr)
            traceback.print_exc()
            LOADED.append((name, f"{type(e).__name__}: {e}"))
    return LOADED
