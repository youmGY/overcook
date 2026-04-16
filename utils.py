import pygame
from engine import F


def rr(surf, color, rect, r=6):
    pygame.draw.rect(surf, color, rect, border_radius=r)


def txt(surf, s, size, color, cx, cy, anchor="center"):
    rendered = F[size].render(str(s), True, color)
    rc = rendered.get_rect()
    setattr(rc, anchor, (cx, cy))
    surf.blit(rendered, rc)


def bar(surf, x, y, w, h, pct, bg, fg, r=3):
    rr(surf, bg, (x, y, w, h), r)
    if pct > 0:
        rr(surf, fg, (x, y, max(r * 2, int(w * pct)), h), r)
