"""Play every story level with the bot and suggest challenge targets (story.CHALLENGES).

    python tools/calibrate_story.py            # prints a CHALLENGES table
"""
from __future__ import annotations

import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opensnake import bots, story  # noqa: E402
from opensnake.speedrun import Run  # noqa: E402


def bot_play(level, seed, max_ticks=6000):
    run = Run(level.category, seed)
    g = run.game
    rng = random.Random(seed * 7 + 1)
    run.input("up")
    while not g.over and g.tick < max_ticks:
        d = bots.choose(g, 0, rng, "hard")
        if d and d != (g.snakes[0].planned or g.snakes[0].dir):
            run.input(d)
        run.step()
        g.events.clear()
    data = run.to_json("bot")
    if not run.finished:
        return None
    _lv, r = story.replay_level(data)
    return r


def main():
    seeds = range(1, 25)
    out = {}
    for ch in story.CHAPTERS:
        for lv in ch.levels:
            results = [r for r in (bot_play(lv, s) for s in seeds) if r]
            rate = len(results) / len(seeds)
            if not results:
                print(f"# {lv.id} {lv.name}: the bot never finished", file=sys.stderr)
                out[lv.id] = None
                continue
            t = statistics.median(r.elapsed for r in results)
            turns = statistics.median(r.turns for r in results)
            half = max(1, lv.goal // 2)
            sp = statistics.median(r.splits[half - 1] for r in results)
            print(f"# {lv.id} {lv.name:22} ok {rate:4.0%}  time {t/1000:6.1f}s  turns {turns:5.1f}  "
                  f"split{half} {sp/1000:5.1f}s", file=sys.stderr)
            out[lv.id] = (t, turns, half, sp)
    return out




SLACK = {1: 1.8, 2: 1.65, 3: 1.55, 4: 1.45, 5: 1.4, 6: 1.35, 7: 1.25, 8: 1.15}


def suggest(stats):
    lines = ["CHALLENGES = {"]
    for ch in story.CHAPTERS:
        f = SLACK[ch.num]
        for lv in ch.levels:
            st = stats.get(lv.id)
            if st is None:  # (the bot can't push crates: generous, hand-set targets)
                t, turns, half, sp = lv.goal * 16_000 / f, lv.goal * 16 / f, max(1, lv.goal // 2), lv.goal * 7_000 / f
            else:
                t, turns, half, sp = st
            time_c = ("time", int(round(t * f / 500) * 500), 0)
            if "shield" in lv.modes and lv.num % 2 == 0:
                second = ("noshield", 0, 0)
            elif lv.num % 2:
                second = ("turns", int(turns * (f + 0.1) + 0.999), 0)
            else:
                second = ("split", half, int(round(sp * f / 500) * 500))
            lines.append(f"    {lv.id!r}: ({time_c!r}, {second!r}),  # {lv.name}")
    lines.append("}")
    return "\n".join(lines)


if __name__ == "__main__" and "--table" in sys.argv:
    print(suggest(main()))
