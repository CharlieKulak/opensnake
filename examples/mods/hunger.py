"""Example OpenSnake mod: a "Hunger" mode and a kiwi fruit.

Copy this file into your mods folder (see README.md), start OpenSnake, and
"Hunger" appears in the mode menu and "Kiwi" in the fruit options.

Hunger: every HUNGER_TICKS moves without eating, the snake loses its last
segment. A hunger bar along the top of the board shows how long you have.
"""

import math

import pygame

HUNGER_TICKS = 40


def setup(api):
    def on_reset(game):
        game.mod_state["hunger"] = 0

    def on_score(game, snake):
        game.mod_state["hunger"] = 0

    def on_step(game):
        game.mod_state["hunger"] = game.mod_state.get("hunger", 0) + 1
        if game.mod_state["hunger"] < HUNGER_TICKS:
            return
        game.mod_state["hunger"] = 0
        for s in game.snakes:
            if len(s.body) > 2:
                s.body.pop()
            elif not game.has("peaceful"):
                s.dead = True
                game.over = True
                game.events.append(api.game.Event("die", fruit="hunger"))
                return
        game.events.append(api.game.Event("hungry"))

    def draw(surface, game, view):
        # Bar across the top of the viewport that drains as you get hungry.
        left = 1 - game.mod_state.get("hunger", 0) / HUNGER_TICKS
        h = max(4, view.c // 6)
        pygame.draw.rect(surface, (60, 40, 20), (0, 0, view.w, h))
        color = (90, 200, 70) if left > 0.3 else (230, 80, 50)
        pygame.draw.rect(surface, color, (0, 0, int(view.w * left), h))

    def icon(surface, size):
        r = size * 0.32
        cx = cy = size / 2
        pygame.draw.circle(surface, (240, 240, 240), (cx, cy), r)
        pygame.draw.circle(surface, (120, 120, 120), (cx, cy), r, max(2, size // 30))
        # fork and knife
        pygame.draw.line(surface, (120, 120, 120), (cx - r * 1.35, cy - r), (cx - r * 1.35, cy + r), max(2, size // 25))
        pygame.draw.line(surface, (120, 120, 120), (cx + r * 1.35, cy - r), (cx + r * 1.35, cy + r), max(2, size // 25))

    api.add_mode("hunger", "Hunger", "Go too long without eating and your tail starts to shrink.",
                 on_reset=on_reset, on_step=on_step, on_score=on_score, draw=draw, icon=icon)

    def draw_kiwi(surface, x, y, r):
        pygame.draw.circle(surface, (120, 85, 40), (x, y), r * 0.85)        # skin
        pygame.draw.circle(surface, (130, 190, 50), (x, y), r * 0.72)       # flesh
        pygame.draw.circle(surface, (235, 240, 200), (x, y), r * 0.22)      # core
        for i in range(10):                                                  # seeds
            a = i / 10 * 2 * math.pi
            pygame.draw.circle(surface, (30, 30, 20), (x + math.cos(a) * r * 0.4, y + math.sin(a) * r * 0.4), r * 0.05)

    api.add_fruit("kiwi", "Kiwi", draw_kiwi, color=(130, 190, 50))
