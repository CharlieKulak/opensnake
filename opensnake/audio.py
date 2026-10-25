"""Synthesized sound effects, so there are no audio assets."""

from __future__ import annotations

import math
import random
import sys
from array import array
from pathlib import Path

import pygame

from .registry import SOUNDS

RATE = 22050

# Recorded sounds that ship with the game (see CREDITS.md). Anything not here
# is synthesized from EFFECTS below.
BUNDLED = Path(__file__).parent / "sounds"

# Playback volume per sound (0.0-1.0); anything not listed plays at full volume.
# The bite recordings are loud, so eating is turned down.
VOLUMES = {"eat": 0.35}

# Each effect is a list of tones: (freq, seconds, wave, gain, slide_hz, delay)
EFFECTS = {
    # Two crunchy bites over a soft low thump: "chomp-chomp".
    "eat": [(2600, 0.055, "crunch", 0.75, -900, 0), (140, 0.06, "sine", 0.35, -50, 0),
            (2000, 0.075, "crunch", 0.65, -800, 0.085), (120, 0.07, "sine", 0.3, -40, 0.085)],
    "turn": [(330, 0.025, "sine", 0.12, 60, 0)],
    "die": [(220, 0.18, "square", 0.22, -120, 0), (150, 0.35, "triangle", 0.35, -90, 0.12)],
    "start": [(440, 0.06, "sine", 0.3, 0, 0), (660, 0.08, "sine", 0.3, 0, 0.07)],
    "portal": [(300, 0.25, "sine", 0.3, 900, 0)],
    "push": [(140, 0.07, "triangle", 0.25, 0, 0)],
    "unlock": [(660, 0.07, "square", 0.2, 0, 0), (990, 0.1, "square", 0.2, 0, 0.07)],
    "shieldup": [(440, 0.12, "sine", 0.3, 440, 0)],
    "shield": [(200, 0.2, "triangle", 0.35, -100, 0)],
    "poison": [(180, 0.3, "saw", 0.25, -120, 0)],
    "dimension": [(700, 0.18, "sine", 0.25, -400, 0)],
    "arrow": [(600, 0.05, "triangle", 0.2, 0, 0)],
    "bump": [(120, 0.05, "triangle", 0.15, 0, 0)],
    "poof": [(400, 0.12, "noise", 0.15, 0, 0)],
    "win": [(f, 0.15, "square", 0.2, 0, i * 0.12) for i, f in enumerate((523, 659, 784, 1046))],
}


def _wave(kind: str, phase: float) -> float:
    p = phase % 1.0
    if kind == "square":
        return 1.0 if p < 0.5 else -1.0
    if kind == "triangle":
        return 4 * p - 1 if p < 0.5 else 3 - 4 * p
    if kind == "saw":
        return 2 * p - 1
    if kind == "noise":
        return random.uniform(-1, 1)
    return math.sin(2 * math.pi * p)


def _crunch(n: int, rate: int, cutoff: float, slide: float, rng: random.Random):
    """Low-passed noise chopped into random-loudness grains, like a bite."""
    out = []
    lp = 0.0
    grain_len = max(1, int(rate * 0.004))
    level = 1.0
    for i in range(n):
        if i % grain_len == 0:
            level = rng.uniform(0.15, 1.0)
        f = cutoff + slide * i / n
        alpha = min(1.0, 2 * math.pi * f / rate)
        lp += alpha * (rng.uniform(-1, 1) - lp)
        out.append(lp * level * 2.2)
    return out


def synth(tones, rate: int = RATE, channels: int = 1) -> array:
    total = max(int((d + dur) * rate) for _, dur, _, _, _, d in tones) + 1
    buf = [0.0] * total
    rng = random.Random(7)  # fixed seed: the same crunch every time
    for freq, dur, kind, gain, slide, delay in tones:
        start, n = int(delay * rate), int(dur * rate)
        noise = _crunch(n, rate, freq, slide, rng) if kind == "crunch" else None
        phase = 0.0
        for i in range(n):
            t = i / n
            env = (1 - t) ** 2 * min(1.0, i / 40)
            if noise is not None:
                buf[start + i] += noise[i] * gain * env
                continue
            f = freq * ((freq + slide) / freq) ** t if slide else freq
            phase += f / rate
            buf[start + i] += _wave(kind, phase) * gain * env
    return array("h", (int(max(-1.0, min(1.0, v)) * 32767) for v in buf for _ in range(channels)))


def _bundled(name: str) -> list[Path]:
    """Bundled recordings for a sound: ``name.ogg``, or variants ``name_1.ogg``,
    ``name_2.ogg``... of which one is picked at random each time it plays."""
    for ext in (".ogg", ".wav"):
        p = BUNDLED / (name + ext)
        if p.is_file():
            return [p]
    return sorted(p for ext in (".ogg", ".wav") for p in BUNDLED.glob(f"{name}_*{ext}"))


class Sfx:
    def __init__(self, pack=None):
        self.muted = False
        self.sounds: dict[str, list[pygame.mixer.Sound]] = {}
        try:
            pygame.mixer.init(RATE, -16, 1, 512)
            rate, _fmt, channels = pygame.mixer.get_init()  # the device may not honour the request
        except pygame.error:
            return  # no audio device; play silently
        for name in list(EFFECTS) + [n for n in SOUNDS if n not in EFFECTS]:
            tones = EFFECTS.get(name)
            # Asset pack beats a mod's sound, which beats the bundled file, which beats synthesis.
            override = (pack.sound(name) if pack else None) or SOUNDS.get(name)
            variants = []
            for path in [override] if override else _bundled(name):
                try:
                    variants.append(pygame.mixer.Sound(str(path)))
                except pygame.error as e:
                    print(f"opensnake: could not load {path}: {e}", file=sys.stderr)
            if not variants and tones:
                variants = [pygame.mixer.Sound(buffer=synth(tones, rate, channels).tobytes())]
            for snd in variants:
                snd.set_volume(VOLUMES.get(name, 1.0))
            if variants:
                self.sounds[name] = variants

    def play(self, name: str) -> None:
        variants = self.sounds.get(name)
        if variants and not self.muted:
            random.choice(variants).play()
