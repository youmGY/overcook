import pygame
from engine import F, screen
from constants import C, INGS, ING_KEYS, RECIPES
from utils import rr, txt, bar


class Popup:
    def __init__(self, x, y, message, color):
        self.x = x; self.y = float(y)
        self.msg = message; self.color = color
        self.life = 80

    def update(self): self.life -= 1; self.y -= 0.65

    @property
    def dead(self): return self.life <= 0

    def draw(self, surf):
        a = min(255, int(self.life / 18 * 255))
        s = F[14].render(self.msg, True, self.color)
        bg = pygame.Surface((s.get_width() + 14, s.get_height() + 8), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 140)); bg.set_alpha(a); s.set_alpha(a)
        bx = int(self.x) - bg.get_width() // 2
        by = int(self.y) - bg.get_height() // 2
        surf.blit(bg, (bx, by)); surf.blit(s, (bx + 7, by + 4))


class Btn:
    def __init__(self, x, y, w, h, label, base_col=(50, 50, 110), lbl_col=(255, 255, 255)):
        self.x = x; self.y = y; self.w = w; self.h = h
        self.label = label; self.base = base_col; self.lbl_col = lbl_col
        self.held = False; self.hover = False

    @property
    def rect(self): return pygame.Rect(self.x, self.y, self.w, self.h)

    def update(self, mpos, mpressed):
        self.hover = self.rect.collidepoint(mpos)
        was = self.held
        self.held = self.hover and mpressed
        return self.held and not was

    def draw(self, surf):
        col = tuple(max(0, c - 50) for c in self.base) if self.held \
              else tuple(min(255, c + 25) for c in self.base) if self.hover \
              else self.base
        rr(surf, col, self.rect, 10)
        pygame.draw.rect(surf, (255, 255, 255, 80) if self.hover else (255, 255, 255, 40),
                         self.rect, 2, border_radius=10)
        for sz in (18, 14, 12):
            if sz in F:
                s = F[sz].render(self.label, True, self.lbl_col)
                if s.get_width() <= self.w - 8:
                    break
        surf.blit(s, s.get_rect(center=self.rect.center))


class RecipeOverlay:
    def __init__(self):
        self.active = False

    def draw(self, surf):
        if not self.active: return
        gw, gh = screen.get_size()

        ov = pygame.Surface((gw, gh), pygame.SRCALPHA)
        ov.fill((5, 8, 25, 220))
        surf.blit(ov, (0, 0))

        PW, PH = min(700, gw - 40), min(430, gh - 80)
        px, py = (gw - PW) // 2, (gh - PH) // 2
        rr(surf, (18, 22, 52), (px, py, PW, PH), 14)
        pygame.draw.rect(surf, (70, 60, 150), (px, py, PW, PH), 2, border_radius=14)

        rr(surf, (28, 32, 72), (px, py, PW, 38), 14)
        txt(surf, "Recipe Book", 18, C["gold"], px + PW // 2, py + 19)

        CARD_W = PW // 2 - 22
        CARD_H = 66
        MARGIN = 12

        for i, rec in enumerate(RECIPES):
            col  = i % 2
            row  = i // 2
            cx_  = px + MARGIN + col * (CARD_W + MARGIN)
            cy_  = py + 50 + row * (CARD_H + 8)

            if cy_ + CARD_H > py + PH - 30:
                break

            rr(surf, (28, 36, 72), (cx_, cy_, CARD_W, CARD_H), 8)
            pygame.draw.rect(surf, (55, 50, 120), (cx_, cy_, CARD_W, CARD_H), 1, border_radius=8)

            name_s = F[14].render(rec["name"], True, C["white"])
            surf.blit(name_s, (cx_ + 8, cy_ + 6))
            pts_s = F[12].render(f"+{rec['pts']} pts", True, C["gold"])
            surf.blit(pts_s, (cx_ + CARD_W - pts_s.get_width() - 8, cy_ + 6))

            ing_x = cx_ + 8
            ing_y = cy_ + 24
            for need in rec["needs"]:
                base = need.replace("_c", "")
                ing  = INGS.get(base, {})
                dot_col = ing.get("color", (150, 150, 150))
                pygame.draw.circle(surf, dot_col, (ing_x + 6, ing_y), 6)
                ing_x += 18

            step_y = ing_y + 14
            for j, step in enumerate(rec.get("steps", [])):
                step_txt = f"{j + 1}. {step}"
                step_s = F[11].render(step_txt, True, (200, 200, 200)) if 11 in F \
                         else F[12].render(step_txt[:25], True, (200, 200, 200))
                if step_s.get_width() > CARD_W - 16:
                    step_txt = f"{j + 1}. {step[:20]}"
                    step_s = F[11].render(step_txt, True, (200, 200, 200)) if 11 in F \
                             else F[12].render(step_txt, True, (200, 200, 200))
                surf.blit(step_s, (cx_ + 8, step_y))
                step_y += 14

            badge_lbl = "cook" if rec["cook"] else "raw"
            badge_col = C["orange"] if rec["cook"] else C["lime"]
            bs = F[12].render(badge_lbl, True, badge_col)
            surf.blit(bs, (cx_ + CARD_W - bs.get_width() - 8, cy_ + CARD_H - bs.get_height() - 3))

        txt(surf, "colored dot = ingredient   * = needs chopping   Cook = use stove",
            12, (130, 130, 170), px + PW // 2, py + PH - 20)
        txt(surf, "Press R to close", 12, (100, 100, 150), px + PW // 2, py + PH - 6)


class IngredientOverlay:
    CARD_W, CARD_H = 120, 90
    COLS = 5

    def __init__(self):
        self.active = False
        self.cards  = []
        self._build_cards()

    def _build_cards(self):
        gw, gh = screen.get_size()
        total_w = self.COLS * (self.CARD_W + 16) - 16
        start_x = (gw - total_w) // 2
        y = gh // 2 - self.CARD_H // 2 - 20
        self.cards = []
        for i, key in enumerate(ING_KEYS):
            x = start_x + i * (self.CARD_W + 16)
            self.cards.append((pygame.Rect(x, y, self.CARD_W, self.CARD_H), key))

    def rebuild(self):
        self._build_cards()

    def draw(self, surf):
        if not self.active: return
        gw, gh = screen.get_size()

        ov = pygame.Surface((gw, gh), pygame.SRCALPHA)
        ov.fill((8, 12, 30, 215))
        surf.blit(ov, (0, 0))

        txt(surf, "Select Ingredient", 24, C["gold"], gw // 2, self.cards[0][0].y - 32)

        mpos = pygame.mouse.get_pos()
        for rect, key in self.cards:
            ing = INGS[key]
            hover = rect.collidepoint(mpos)
            bg = C["ov_sel"] if hover else C["ov_card"]
            rr(surf, bg, rect, 10)
            pygame.draw.rect(surf, C["ov_border"] if hover else (60, 60, 100),
                             rect, 2, border_radius=10)

            pygame.draw.circle(surf, ing["color"], (rect.centerx, rect.y + 32), 20)

            if ing["can_chop"]:
                badge = F[12].render("Choppable", True, (200, 200, 200))
            else:
                badge = F[12].render("No chop", True, (140, 140, 140))
            surf.blit(badge, (rect.centerx - badge.get_width() // 2, rect.y + 56))

            name_s = F[14].render(ing["label"], True, C["white"])
            surf.blit(name_s, (rect.centerx - name_s.get_width() // 2, rect.y + rect.h - 22))

        txt(surf, "Press ESC or click outside to cancel", 12,
            (140, 140, 170), gw // 2, self.cards[0][0].bottom + 20)

    def check_click(self, mpos):
        for rect, key in self.cards:
            if rect.collidepoint(mpos):
                return key
        return None
