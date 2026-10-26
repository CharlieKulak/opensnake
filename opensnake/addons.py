"""Finding resource packs and mods for the Packs & Mods screen.

Resource packs work like Minecraft's: each pack is a folder (images, sounds
and a pack.json) and any number can be enabled at once, in priority order.
Packs come from two places:

  built-in   opensnake/packs/<name>/       shipped with the game
  yours      <config dir>/resourcepacks/<name>/

The old single ``<config dir>/assets`` folder still works and shows up as a
pack called "assets".
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .assets import config_dir

BUILTIN_PACKS = Path(__file__).parent / "packs"


def user_packs_dir() -> Path:
    return config_dir() / "resourcepacks"


def user_mods_dir() -> Path:
    return config_dir() / "mods"


@dataclass
class PackInfo:
    id: str            # "builtin:<folder>", "user:<folder>" or "legacy:assets"
    name: str
    description: str
    path: Path
    builtin: bool
    icon: Path | None  # pack.svg / pack.png, like Minecraft's pack.png


def _read_pack(pack_id: str, path: Path, builtin: bool) -> PackInfo:
    meta = {}
    try:
        meta = json.loads((path / "pack.json").read_text())
    except (OSError, ValueError):
        pass
    if not isinstance(meta, dict):
        meta = {}
    icon = next((path / f for f in ("pack.svg", "pack.png") if (path / f).is_file()), None)
    name = str(meta.get("name") or path.name)[:40]
    desc = str(meta.get("description") or "")[:140]
    return PackInfo(pack_id, name, desc, path, builtin, icon)


def discover_packs() -> list[PackInfo]:
    """Every pack the game can find, built-in ones first."""
    packs = []
    for root, prefix, builtin in ((BUILTIN_PACKS, "builtin", True), (user_packs_dir(), "user", False)):
        if root.is_dir():
            for d in sorted(root.iterdir()):
                if d.is_dir() and not d.name.startswith((".", "_")):
                    packs.append(_read_pack(f"{prefix}:{d.name}", d, builtin))
    legacy = config_dir() / "assets"
    if legacy.is_dir():
        packs.append(_read_pack("legacy:assets", legacy, False))
    return packs


def open_folder(path: Path) -> bool:
    """Show a folder in the system file manager (creating it first)."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(path))  # noqa: S606 - opening a folder the user asked for
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (OSError, AttributeError):
        return False


def restart_program() -> None:
    """Start the game again in place (used after changing mods)."""
    if getattr(sys, "frozen", False):   # standalone build: the executable is the game
        os.execv(sys.executable, [sys.executable] + sys.argv[1:])
    if sys.argv and sys.argv[0].endswith("__main__.py"):  # started as "python -m opensnake"
        os.execv(sys.executable, [sys.executable, "-m", "opensnake"] + sys.argv[1:])
    os.execv(sys.executable, [sys.executable] + sys.argv)
