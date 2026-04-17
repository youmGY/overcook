"""Drawing utility functions — reusable primitives for the game UI."""
from typing import Sequence, Union

import pygame

from .engine import FONTS

# Type alias for color values
Color = Union[tuple[int, int, int], tuple[int, int, int, int]]


def draw_rounded_rect(
    surf: pygame.Surface,
    color: Color,
    rect: Sequence[int],
    r: int = 6,
) -> None:
    """Draw a filled rounded rectangle."""
    pygame.draw.rect(surf, color, rect, border_radius=r)


def draw_text(
    surf: pygame.Surface,
    s: str,
    size: int,
    color: Color,
    cx: int,
    cy: int,
    anchor: str = "center",
) -> None:
    """Render text at *(cx, cy)* aligned by *anchor* (e.g. ``'center'``, ``'topleft'``)."""
    rendered = FONTS[size].render(str(s), True, color)
    rc = rendered.get_rect()
    setattr(rc, anchor, (cx, cy))
    surf.blit(rendered, rc)


def draw_progress_bar(
    surf: pygame.Surface,
    x: int,
    y: int,
    w: int,
    h: int,
    pct: float,
    bg: Color,
    fg: Color,
    r: int = 3,
) -> None:
    """Draw a horizontal progress bar filled to *pct* (0.0–1.0)."""
    import overcook.utils as _self
    _self.rr(surf, bg, (x, y, w, h), r)
    if pct > 0:
        fill_w = max(r * 2, int(w * pct))
        _self.rr(surf, fg, (x, y, fill_w, h), r)


# Backward-compatible short aliases (used extensively across the codebase)
rr = draw_rounded_rect
txt = draw_text
bar = draw_progress_bar
