"""The few pygame.gfxdraw calls OpenSnake uses, with a fallback.

pygame.gfxdraw isn't available in every pygame build (the browser build made
by pygbag lacks it). Where it's missing, the same shapes are drawn with
pygame.draw, and translucent colours are blended through a temporary surface
the way gfxdraw would blend them.
"""

from __future__ import annotations

import importlib

import pygame

_UNSET = object()
_gfx_module = _UNSET


def _gfxdraw():
    """pygame.gfxdraw, or None if this build lacks it.

    Looked up on first use rather than imported at the top: the browser
    packager scans import statements and would try to download
    "pygame.gfxdraw" as a separate package.
    """
    global _gfx_module
    if _gfx_module is _UNSET:
        try:
            _gfx_module = importlib.import_module("pygame.gfxdraw")
        except ImportError:
            _gfx_module = None
    return _gfx_module


def _blend(surf, color, rect: pygame.Rect, paint):
    """Run paint(target, rgb, ox, oy), blending if ``color`` has alpha < 255."""
    if len(color) < 4 or color[3] >= 255:
        paint(surf, tuple(color[:3]), 0, 0)
        return
    rect = rect.clip(surf.get_rect())
    if rect.w <= 0 or rect.h <= 0:
        return
    tmp = pygame.Surface(rect.size, pygame.SRCALPHA)
    paint(tmp, tuple(color[:3]), rect.x, rect.y)
    tmp.set_alpha(color[3])
    surf.blit(tmp, rect.topleft)


def filled_circle(surf, x, y, r, color):
    _gfx = _gfxdraw()
    if _gfx:
        _gfx.filled_circle(surf, x, y, r, color)
        return
    _blend(surf, color, pygame.Rect(x - r - 1, y - r - 1, 2 * r + 3, 2 * r + 3),
           lambda s, c, ox, oy: pygame.draw.circle(s, c, (x - ox, y - oy), r))


def aacircle(surf, x, y, r, color):
    _gfx = _gfxdraw()
    if _gfx:
        _gfx.aacircle(surf, x, y, r, color)
        return

    def paint(s, c, ox, oy):
        aa = getattr(pygame.draw, "aacircle", None)
        if aa:
            aa(s, c, (x - ox, y - oy), r, 1)
        else:
            pygame.draw.circle(s, c, (x - ox, y - oy), r, 1)
    _blend(surf, color, pygame.Rect(x - r - 2, y - r - 2, 2 * r + 5, 2 * r + 5), paint)


def _bounds(points) -> pygame.Rect:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, y0 = int(min(xs)) - 2, int(min(ys)) - 2
    return pygame.Rect(x0, y0, int(max(xs)) - x0 + 4, int(max(ys)) - y0 + 4)


def filled_polygon(surf, points, color):
    _gfx = _gfxdraw()
    if _gfx:
        _gfx.filled_polygon(surf, points, color)
        return
    _blend(surf, color, _bounds(points),
           lambda s, c, ox, oy: pygame.draw.polygon(s, c, [(px - ox, py - oy) for px, py in points]))


def aapolygon(surf, points, color):
    _gfx = _gfxdraw()
    if _gfx:
        _gfx.aapolygon(surf, points, color)
        return
    _blend(surf, color, _bounds(points),
           lambda s, c, ox, oy: pygame.draw.aalines(s, c, True, [(px - ox, py - oy) for px, py in points]))
