"""
assets.py — 재료 아이콘 로더
game.py 와 같은 디렉터리에 두세요.
assets/ingredients/ 폴더에 PNG들이 있어야 합니다.
"""

import os
import pygame

_cache: dict[str, pygame.Surface] = {}
ASSET_DIR = os.path.join(os.path.dirname(__file__), "assets", "ingredients")

def load_ing_icon(key: str, size: int = 48) -> pygame.Surface | None:
    """재료 key에 해당하는 아이콘 Surface 반환. 없으면 None."""
    cache_key = f"{key}:{size}"
    if cache_key in _cache:
        return _cache[cache_key]

    # chopped suffix 처리: "tomato_c" → assets/tomato_c.png
    path = os.path.join(ASSET_DIR, f"{key}.png")
    if not os.path.exists(path):
        # fallback: base ingredient (chopped 없을 때)
        base = key.replace("_c", "")
        path = os.path.join(ASSET_DIR, f"{base}.png")
    if not os.path.exists(path):
        return None

    try:
        surf = pygame.image.load(path).convert_alpha()
        surf = pygame.transform.smoothscale(surf, (size, size))
        _cache[cache_key] = surf
        return surf
    except Exception:
        return None


def draw_ing_icon(screen: pygame.Surface, key: str, cx: int, cy: int, size: int = 40):
    """중심 좌표 (cx, cy) 기준으로 아이콘 그리기. 없으면 색 원으로 폴백."""
    surf = load_ing_icon(key, size)
    if surf:
        screen.blit(surf, (cx - size // 2, cy - size // 2))
        return True
    return False
