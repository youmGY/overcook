"""Pygame engine initialisation — display, fonts, image cache.

This module runs ``pygame.init()`` at import time to set up the display
and audio subsystem.  All rendering modules import shared objects from
here (``screen``, ``FONTS``, ``clock``, etc.).
"""
import os
from typing import Optional

import pygame

pygame.init()

SCREEN_WIDTH: int = 1024
SCREEN_HEIGHT: int = 600

screen: pygame.Surface = pygame.display.set_mode(
    (SCREEN_WIDTH, SCREEN_HEIGHT), pygame.RESIZABLE,
)
pygame.display.set_caption("Cooking Game")
clock: pygame.time.Clock = pygame.time.Clock()
FPS: int = 60

# Backward-compatible aliases
W, H = SCREEN_WIDTH, SCREEN_HEIGHT

_FONT_SIZES: tuple[int, ...] = (12, 14, 18, 24, 32, 40)

_FONT_SEARCH_PATHS: tuple[str, ...] = (
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "C:/Windows/Fonts/malgun.ttf",
)


def _load_fonts() -> dict[int, pygame.font.Font]:
    """Load Korean-capable fonts for all required sizes."""
    font_path = next((p for p in _FONT_SEARCH_PATHS if os.path.exists(p)), None)
    if font_path:
        return {sz: pygame.font.Font(font_path, sz) for sz in _FONT_SIZES}
    return {sz: pygame.font.SysFont("Arial", sz) for sz in _FONT_SIZES}


FONTS: dict[int, pygame.font.Font] = _load_fonts()

# Backward-compatible alias (used extensively across the codebase)
F = FONTS

IMG_CACHE: dict[tuple, Optional[pygame.Surface]] = {}


def get_img(ing_id: str, w: int, h: int) -> Optional[pygame.Surface]:
    """Return a cached, scaled ingredient image (or ``None`` if unavailable)."""
    key = (ing_id, w, h)
    if key in IMG_CACHE:
        return IMG_CACHE[key]

    base_path = f"assets/ingredients/{ing_id}.png"
    if not os.path.exists(base_path):
        IMG_CACHE[key] = None
        return None

    try:
        if not hasattr(pygame, "image"):
            return None
        img = pygame.image.load(base_path).convert_alpha()
        img = pygame.transform.smoothscale(img, (w, h))
        IMG_CACHE[key] = img
        return img
    except Exception:
        IMG_CACHE[key] = None
        return None