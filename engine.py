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
