import pygame
import os

pygame.init()

W, H = 1024, 600
screen = pygame.display.set_mode((W, H), pygame.RESIZABLE)
pygame.display.set_caption("Cooking Game")
clock = pygame.time.Clock()
FPS = 60


def _load_fonts():
    candidates = [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "C:/Windows/Fonts/malgun.ttf",
    ]
    fp = next((p for p in candidates if os.path.exists(p)), None)
    if fp:
        return {sz: pygame.font.Font(fp, sz) for sz in (12, 14, 18, 24, 32, 40)}
    return {sz: pygame.font.SysFont("Arial", sz) for sz in (12, 14, 18, 24, 32, 40)}


F = _load_fonts()


IMG_CACHE = {}

def get_img(ing_id, w, h):
    """지정된 크기의 재료 이미지를 캐싱하여 반환합니다."""
    key = (ing_id, w, h)
    if key in IMG_CACHE:
        return IMG_CACHE[key]

    base_path = f"assets/ingredients/{ing_id}.png"
    if not os.path.exists(base_path):
        IMG_CACHE[key] = None
        return None

    try:
        # 테스트 환경(test_game.py) 등에서 pygame.image 모듈이 없을 때를 대비
        if not hasattr(pygame, "image"):
            return None
        img = pygame.image.load(base_path).convert_alpha()
        img = pygame.transform.smoothscale(img, (w, h))
        IMG_CACHE[key] = img
        return img
    except Exception:
        IMG_CACHE[key] = None
        return None