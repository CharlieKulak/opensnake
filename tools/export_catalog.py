"""Export the game's catalogue (and test data) for OpenSnake in Rust.

The Rust game embeds what this writes, so Python stays the single source of
truth for skins, packs, loot boxes, ranks, modes and speedrun categories:

    python tools/export_catalog.py ../opensnake-rs/assets

Writes:
  catalog.json        everything the game shows or plays by
  golden.json         Python's random numbers and recorded runs, which the Rust
                      game must reproduce exactly (the server re-checks every
                      run by replaying it in Python)
  packs/<id>/         each built-in pack's pack.json, with its SVG images as PNGs
"""

from __future__ import annotations

import json
import os
import random
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from opensnake import __version__, cosmetics as cos  # noqa: E402
from opensnake.game import game_to_state  # noqa: E402
from opensnake.modes import (CONFLICTS, MODES, SNAKE_COLORS, SPEED_TICKS, VERSUS_MODES,  # noqa: E402
                             VERSUS_SIZES)
from opensnake.speedrun import CATEGORIES, Run, category_def, make_custom, weekly_categories  # noqa: E402

PACK_DIR = ROOT / "opensnake" / "packs"
IMAGE_SIZE = 128


def hexcol(c) -> str | None:
    return None if c is None else "#%02x%02x%02x" % tuple(c)


def catalog() -> dict:
    return {
        "version": __version__,
        "skins": [{"id": s.id, "name": s.name, "rarity": s.rarity, "pattern": s.pattern,
                   "colors": [hexcol(c) for c in s.colors], "outline": hexcol(s.outline), "glow": s.glow,
                   "price": s.price, "series": s.series} for s in cos.SKINS],
        "packs": [{"id": p.id, "name": p.name, "rarity": p.rarity, "swatch": [hexcol(c) for c in p.swatch],
                   "price": p.price} for p in cos.PACKS],
        "crates": [{"id": c.id, "name": c.name, "price": c.price, "color": hexcol(c.color), "odds": c.odds}
                   for c in cos.CRATES],
        "rarities": [{"id": r, "name": cos.RARITY_NAMES[r], "color": hexcol(cos.RARITY_COLORS[r])}
                     for r in cos.RARITIES],
        "ranks": [{"rp": lo, "name": name, "color": hexcol(col),
                   "rewards": cos.rank_reward_names(i)} for i, (lo, name, col) in enumerate(cos.RANKS)],
        "untradeable": sorted(cos.UNTRADEABLE),
        "pass_only": sorted(cos.PASS_ONLY),
        "avatar_icons": cos.AVATAR_ICONS,
        "avatar_colors": [hexcol(c) for c in cos.AVATAR_COLORS],
        "modes": [{"id": i, "name": n, "desc": d} for i, n, d in MODES],
        "conflicts": CONFLICTS,
        "versus_modes": VERSUS_MODES,
        "versus_sizes": VERSUS_SIZES,
        "speed_ticks": SPEED_TICKS,
        "snake_colors": {k: [hexcol(a), hexcol(b), name] for k, (a, b, name) in SNAKE_COLORS.items()},
        "categories": [{**category_def(c), "desc": c.desc, "accel": c.accel, "min_tick_ms": c.min_tick_ms}
                       for c in CATEGORIES],
        "economy": {"round_base": cos.ROUND_BASE, "round_per_fruit": cos.ROUND_PER_FRUIT,
                    "round_cap": cos.ROUND_CAP, "pr_reward": cos.PR_REWARD, "wr_reward": cos.WR_REWARD,
                    "wr_hold_reward": cos.WR_HOLD_REWARD, "pass_price": cos.PASS_PRICE,
                    "level_xp": cos.LEVEL_XP, "pass_levels": cos.PASS_LEVELS,
                    "market_fee": cos.MARKET_FEE, "market_min": cos.MARKET_MIN_PRICE,
                    "market_max": cos.MARKET_MAX_PRICE, "daily_bonus": cos.DAILY_BONUS},
    }


def golden() -> dict:
    """Random numbers and runs the Rust game has to reproduce."""
    rng_cases = []
    for seed in (0, 1, 42, 2 ** 31 - 1, 123456789, 2 ** 40 + 7):
        r = random.Random(seed)
        rng_cases.append({"seed": seed,
                          "u32": [r.getrandbits(32) for _ in range(8)],
                          "randrange": [r.randrange(n) for n in (1, 2, 3, 7, 10, 17, 100, 1000, 12345, 2 ** 31)],
                          "random": [r.random() for _ in range(3)],
                          "choice": [r.choice(["a", "b", "c", "d", "e"]) for _ in range(6)]})
    sys.path.insert(0, str(ROOT / "tests"))
    from test_speedrun import bot_run  # noqa: E402

    cats = list(CATEGORIES) + weekly_categories("2026-W46")[:4] + [
        make_custom(14, 12, ["portal", "key"], 12, 2, 120, "mixed"),
        make_custom(10, 9, ["sokoban"], 4, 1, 130),
        make_custom(12, 11, ["wall", "gate", "dimension", "minesweeper", "magnet"], 10, 2, 110),
        make_custom(10, 9, ["poison", "borderless", "twin", "statue"], 8, 2, 130),
        make_custom(9, 8, ["cheese", "arrow", "shield", "light"], 10, 1, 130),
    ]
    runs = []
    for c in cats:
        for seed in (1, 7):
            run = bot_run(c, seed, random.Random(seed))
            state = game_to_state(run.game)
            state.pop("events")
            runs.append({"category": category_def(c) | {"accel": c.accel, "min_tick_ms": c.min_tick_ms},
                         "id": c.id, "seed": seed, "inputs": run.inputs, "elapsed": run.elapsed,
                         "time_ms": round(run.elapsed), "finished": run.finished, "splits": run.splits,
                         "state": state})
    return {"rng": rng_cases, "runs": runs}


def export_packs(out: Path) -> None:
    import pygame
    pygame.init()
    for folder in sorted(PACK_DIR.iterdir()):
        if not (folder / "pack.json").is_file():
            continue
        dest = out / "packs" / folder.name
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        shutil.copy(folder / "pack.json", dest / "pack.json")
        for f in sorted(folder.iterdir()):
            if f.suffix == ".svg":
                img = pygame.image.load_sized_svg(str(f), (IMAGE_SIZE, IMAGE_SIZE))
                pygame.image.save(img, str(dest / (f.stem + ".png")))
            elif f.suffix in (".ogg", ".wav"):
                shutil.copy(f, dest / f.name)


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT.parent / "opensnake-rs" / "assets")
    out.mkdir(parents=True, exist_ok=True)
    (out / "catalog.json").write_text(json.dumps(catalog(), indent=1))
    (out / "golden.json").write_text(json.dumps(golden()))
    export_packs(out)
    print(f"Wrote the catalogue, golden data and {len(list((out / 'packs').iterdir()))} packs to {out}")


if __name__ == "__main__":
    main()
