#!/usr/bin/env python3
"""
오버쿡 스타일 요리 게임 (pygame)
실행: python cooking_game.py
설치: pip install pygame

조작: 화면 버튼 (← →  이동 | Action 버튼)
      키보드:  ← → 이동 | Z / Space = 행동
"""

import pygame, sys, math, random, time

pygame.init()
pygame.display.set_caption("Cooking Game")

W, H = 900, 600
screen = pygame.display.set_mode((W, H), pygame.RESIZABLE)
clock  = pygame.time.Clock()
FPS    = 60

# ─────────────────────────────────────────────
#  색상
# ─────────────────────────────────────────────
C = {
    "bg":           (11,  11,  28),
    "tile_a":       (30,  30,  62),
    "tile_b":       (24,  24,  50),
    "ground":       (20,  20,  48),
    "ground_line":  (90,  80, 180),
    "grid":         (38,  34,  90),

    "ing_base":     (42,  24,   8), "ing_top":    (107, 76, 42),
    "chop_base":    (10,  32,  10), "chop_top":   ( 42,160, 90),
    "pot_base":     (26,   8,   8), "pot_off":    ( 51, 51, 51),
    "pot_on":       (160,  35,   0),
    "plate_base":   (10,  10,  42), "plate_top":  ( 46, 46,106),
    "submit_base":  ( 8,  24,   8), "submit_top": ( 29,158,117),
    "trash_base":   (32,   8,   8), "trash_top":  (122, 32, 64),

    "char_body": ( 83, 65,183), "char_dark": (57, 40,137),
    "char_face": (245,214,184), "char_hat":  (38, 33,105),
    "apron":     (224,220,208),

    "white":  (255,255,255), "black":   (  0,  0,  0),
    "yellow": (255,215, 80), "orange":  (239,159, 39),
    "red":    (226, 75, 74), "green":   ( 29,158,117),
    "lime":   (151,196, 89), "gold":    (250,199,117),
    "blue":   (133,183,235), "purple":  (127,119,221),
    "pink":   (212, 83,126), "burn":    (180, 60,  0),

    "hud_bg":    (22, 22, 46), "hud_brd":   (60, 48,137),
    "ord_bg":    (15, 42, 63), "ord_brd":   (55,138,221),
    "ord_urg":   (239,159, 39),

    # overlay
    "ov_bg":     ( 8, 12, 30),
    "ov_card":   (28, 34, 68),
    "ov_sel":    (60, 50,140),
    "ov_border": (80, 70,180),
}

# ─────────────────────────────────────────────
#  재료 / 레시피
# ─────────────────────────────────────────────
INGS = {
    "tomato":   {"label": "Tomato",   "color": (226, 75, 74),  "can_chop": True},
    "carrot":   {"label": "Carrot",   "color": (239,159, 39),  "can_chop": True},
    "onion":    {"label": "Onion",    "color": (175,169,236),  "can_chop": True},
    "mushroom": {"label": "Mushroom", "color": (180,178,169),  "can_chop": True},
    "rice":     {"label": "Rice",     "color": (232,224,208),  "can_chop": False},
}
ING_KEYS = list(INGS.keys())

RECIPES = [
    {"name": "Tomato Soup", "pts": 100, "needs": ["tomato_c","onion_c"], "cook": True,
     "steps": ["CHOP Tomato & Onion", "Add to Stove & Cook"]},
    {"name": "Fried Rice", "pts": 110, "needs": ["rice","tomato_c"], "cook": True,
     "steps": ["Get Rice, CHOP Tomato", "Add both to Stove & Cook"]},
    {"name": "Mushroom Stir-fry", "pts": 90, "needs": ["mushroom_c","onion_c"], "cook": True,
     "steps": ["CHOP Mushroom & Onion", "Add to Stove & Quick Cook"]},
    {"name": "Veg Curry", "pts": 150, "needs": ["carrot_c","onion_c","rice"], "cook": True,
     "steps": ["CHOP Carrot & Onion, Get Rice", "Add all to Stove & Simmer"]},
    {"name": "Carrot Soup", "pts": 80, "needs": ["carrot_c"], "cook": True,
     "steps": ["CHOP Carrot", "Add to Stove & Cook"]},
    {"name": "Rice Bowl", "pts": 95, "needs": ["rice","mushroom_c"], "cook": True,
     "steps": ["Get Rice, CHOP Mushroom", "Add both to Stove & Cook"]},
    {"name": "Veg Salad", "pts": 70, "needs": ["tomato_c","mushroom_c"], "cook": False,
     "steps": ["CHOP Tomato & Mushroom", "Mix & Plate (NO COOK)"]},
]

# ─────────────────────────────────────────────
#  폰트
# ─────────────────────────────────────────────
def _load_fonts():
    import os
    candidates = [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "C:/Windows/Fonts/malgun.ttf",
    ]
    fp = next((p for p in candidates if os.path.exists(p)), None)
    if fp:
        return {sz: pygame.font.Font(fp, sz) for sz in (12,14,18,24,32,40)}
    return {sz: pygame.font.SysFont("Arial", sz) for sz in (12,14,18,24,32,40)}

F = _load_fonts()

# ─────────────────────────────────────────────
#  유틸
# ─────────────────────────────────────────────
def rr(surf, color, rect, r=6):
    pygame.draw.rect(surf, color, rect, border_radius=r)

def txt(surf, s, size, color, cx, cy, anchor="center"):
    rendered = F[size].render(str(s), True, color)
    rc = rendered.get_rect()
    setattr(rc, anchor, (cx, cy))
    surf.blit(rendered, rc)

def bar(surf, x, y, w, h, pct, bg, fg, r=3):
    rr(surf, bg, (x,y,w,h), r)
    if pct > 0:
        rr(surf, fg, (x, y, max(r*2, int(w*pct)), h), r)

# ─────────────────────────────────────────────
#  팝업
# ─────────────────────────────────────────────
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
        bg = pygame.Surface((s.get_width()+14, s.get_height()+8), pygame.SRCALPHA)
        bg.fill((0,0,0,140)); bg.set_alpha(a); s.set_alpha(a)
        bx = int(self.x) - bg.get_width()//2
        by = int(self.y) - bg.get_height()//2
        surf.blit(bg,(bx,by)); surf.blit(s,(bx+7, by+4))

# ─────────────────────────────────────────────
#  버튼
# ─────────────────────────────────────────────
class Btn:
    def __init__(self, x, y, w, h, label, base_col=(50,50,110), lbl_col=(255,255,255)):
        self.x=x; self.y=y; self.w=w; self.h=h
        self.label=label; self.base=base_col; self.lbl_col=lbl_col
        self.held=False; self.hover=False

    @property
    def rect(self): return pygame.Rect(self.x,self.y,self.w,self.h)

    def update(self, mpos, mpressed):
        self.hover = self.rect.collidepoint(mpos)
        was = self.held
        self.held = self.hover and mpressed
        return self.held and not was   # True on press-down edge

    def draw(self, surf):
        col = tuple(max(0,c-50) for c in self.base) if self.held \
              else tuple(min(255,c+25) for c in self.base) if self.hover \
              else self.base
        rr(surf, col, self.rect, 10)
        pygame.draw.rect(surf, (255,255,255,80) if self.hover else (255,255,255,40),
                         self.rect, 2, border_radius=10)
        s = F[16 if len(self.label)<=6 else 13].render(self.label, True, self.lbl_col) \
            if 16 in F else F[14].render(self.label, True, self.lbl_col)
        # use closest available size
        for sz in (18,14,12):
            if sz in F:
                s = F[sz].render(self.label, True, self.lbl_col)
                if s.get_width() <= self.w - 8:
                    break
        surf.blit(s, s.get_rect(center=self.rect.center))

# ─────────────────────────────────────────────
#  스테이션  (5 칸)
#  0 = 재료창고  1 = 썰기대  2 = 냄비①  3 = 냄비②  4 = 접시+제출
# ─────────────────────────────────────────────
BURN_TIME   = 8.0    # 조리 완료 후 이 시간 내 안 건지면 탐
COOK_TIME   = 5.0    # 조리 완료까지 걸리는 시간
CHOP_TIME   = 3.0    # 썰기 완료까지 걸리는 시간

class Station:
    SW = 110   # station width
    SH = 28    # station surface height

    def __init__(self, kind, sx, sy):
        self.kind = kind          # "ing" | "chop" | "pot" | "plate_submit"
        self.x = sx; self.y = sy
        self.w = self.SW; self.h = self.SH

        # chop state
        self.chop_item   = None    # ingredient dict on board
        self.chop_prog   = 0.0
        self.chopping    = False

        # pot state
        self.pot_items   = []      # list of ingredient dicts
        self.pot_prog    = 0.0     # 0→1 cooking progress
        self.pot_cooking = False
        self.pot_cooked  = False
        self.pot_burn    = 0.0     # counts up after cooked; > BURN_TIME → burned
        self.pot_on      = False

        # plate state
        self.plate_item  = None    # cooked dish placed here

    @property
    def rect(self): return pygame.Rect(self.x, self.y, self.w, self.h)
    def cx(self): return self.x + self.w//2
    def cy(self): return self.y + self.h//2

    def dist(self, px, py):
        return math.hypot(px - self.cx(), py - self.cy())

    def update(self, dt):
        events = []
        if self.kind == "chop" and self.chopping and self.chop_item \
                and not self.chop_item.get("chopped"):
            self.chop_prog = min(1.0, self.chop_prog + dt / CHOP_TIME)
            if self.chop_prog >= 1.0:
                self.chop_item["chopped"] = True
                self.chop_item["id"] += "_c"
                self.chop_item["label"] = "Chopped " + self.chop_item["label"]
                self.chopping = False
                events.append("chop_done")

        if self.kind == "pot":
            if self.pot_cooking and not self.pot_cooked:
                self.pot_prog = min(1.0, self.pot_prog + dt / COOK_TIME)
                if self.pot_prog >= 1.0:
                    self.pot_cooked  = True
                    self.pot_cooking = False
                    self.pot_burn    = 0.0
                    events.append("cook_done")
            elif self.pot_cooked and self.pot_items:
                self.pot_burn += dt
                if self.pot_burn >= BURN_TIME:
                    events.append("burned")

        return events

    # ── drawing ──────────────────────────────
    def draw(self, surf, gy):
        # choose colors
        if self.kind == "ing":
            base, top = C["ing_base"], C["ing_top"]
        elif self.kind == "chop":
            base, top = C["chop_base"], C["chop_top"]
        elif self.kind == "pot":
            base, top = C["pot_base"], C["pot_on"] if self.pot_on else C["pot_off"]
        elif self.kind == "trash":
            base, top = C["trash_base"], C["trash_top"]
        else:  # plate_submit
            base, top = C["plate_base"], C["plate_top"]

        # pillar
        rr(surf, base, (self.x+8, self.y+self.h, self.w-16, gy-self.y-self.h), 2)
        # surface
        rr(surf, top, (self.x, self.y, self.w, self.h), 6)
        surf.fill((255,255,255,15), (self.x+5, self.y+2, self.w-10, 3))

        # label
        s = F[12].render(self._station_label(), True, (220,220,220))
        surf.blit(s, (self.cx()-s.get_width()//2, self.cy()-s.get_height()//2))

        # icon above surface
        ix, iy = self.cx(), self.y - 18
        self._draw_icon(surf, ix, iy)

    def _station_label(self):
        if self.kind == "ing":      return "Pantry"
        if self.kind == "chop":     return "Chop"
        if self.kind == "pot":      return "Stove"
        if self.kind == "trash":    return "Trash"
        return "Plate / Submit"

    def _draw_icon(self, surf, ix, iy):
        if self.kind == "ing":
            # show a generic box icon
            rr(surf, C["ing_top"], (ix-14,iy-10,28,20), 4)
            t = F[12].render("INGs", True, (255,255,255))
            surf.blit(t, (ix-t.get_width()//2, iy-t.get_height()//2))

        elif self.kind == "chop":
            if self.chop_item:
                bid = self.chop_item["id"].replace("_c","")
                col = INGS.get(bid,{}).get("color",(150,150,150))
                pygame.draw.circle(surf, col, (ix-8,iy), 9)
                if self.chop_item.get("chopped"):
                    pygame.draw.line(surf, C["lime"],(ix-4,iy+3),(ix+8,iy-5),2)
                else:
                    bar(surf, self.x+2, self.y-8, self.w-4, 5,
                        self.chop_prog, (50,50,50), C["orange"], 2)
            else:
                # knife
                pygame.draw.line(surf,(180,180,180),(ix-10,iy+8),(ix+10,iy-8),3)
                pygame.draw.line(surf,(130,130,130),(ix+7,iy-10),(ix+12,iy-5),2)

        elif self.kind == "pot":
            # pot body
            pygame.draw.circle(surf,(80,80,80),(ix,iy),13)
            pygame.draw.circle(surf,(110,110,110),(ix,iy),13,1)

            if self.pot_items:
                n = min(len(self.pot_items),3)
                for i,item in enumerate(self.pot_items[:3]):
                    bid=item["id"].replace("_c","")
                    col=INGS.get(bid,{}).get("color",(150,150,150))
                    ox=ix+(i-(n-1)/2)*8
                    pygame.draw.circle(surf,col,(int(ox),iy),5)

            # cook progress bar
            if self.pot_cooking or self.pot_cooked:
                col_f = C["green"] if self.pot_cooked else C["orange"]
                bar(surf,self.x+2,self.y-9,self.w-4,5,self.pot_prog,(40,40,40),col_f,2)

            # burn warning bar (red, counts up)
            if self.pot_cooked and self.pot_items:
                burn_pct = self.pot_burn / BURN_TIME
                col_b = C["burn"] if burn_pct < 0.7 else C["red"]
                bar(surf,self.x+2,self.y-16,self.w-4,4,burn_pct,(30,20,20),col_b,2)

            # cooked indicator
            if self.pot_cooked and not (self.pot_burn >= BURN_TIME):
                pygame.draw.circle(surf,C["green"],(ix+12,iy-10),5)

            # flame animation
            if self.pot_on and not self.pot_cooked:
                t=time.time()
                for fx,phase in [(self.x+10,0),(self.x+self.w-18,1)]:
                    fy=self.y+self.h+4+math.sin(t*9+phase)*1.5
                    pygame.draw.polygon(surf,(255,90,0),
                        [(fx,fy+9),(fx-5,fy+2),(fx,fy-5),(fx+5,fy+2)])
                    pygame.draw.polygon(surf,(255,210,0),
                        [(fx,fy+7),(fx-3,fy+2),(fx,fy-2),(fx+3,fy+2)])

        else:  # plate_submit
            # plate
            pygame.draw.circle(surf,(200,195,180),(ix-18,iy),11)
            pygame.draw.circle(surf,(160,155,140),(ix-18,iy),11,1)
            if self.plate_item:
                pygame.draw.circle(surf,C["green"],(ix-10,iy-9),5)
                s=F[12].render("Plated",True,C["lime"])
                surf.blit(s,(ix-18-s.get_width()//2,iy+6))

            # submit box
            rr(surf,C["submit_top"],(ix+4,iy-9,22,16),3)
            pygame.draw.line(surf,(255,255,255,100),(ix+4,iy-3),(ix+26,iy-3),1)

        if self.kind == "trash":
            # bin body
            rr(surf, C["trash_top"], (ix-10, iy-8, 20, 17), 3)
            # lid
            rr(surf, (160, 50, 90), (ix-12, iy-13, 24, 5), 2)
            # stripes
            for lx in (ix-5, ix, ix+5):
                pygame.draw.line(surf, (200,100,130), (lx, iy-6), (lx, iy+6), 1)


# ─────────────────────────────────────────────
#  레시피 북 오버레이
# ─────────────────────────────────────────────
class RecipeOverlay:
    def __init__(self):
        self.active = False

    def draw(self, surf):
        if not self.active: return
        gw, gh = screen.get_size()

        ov = pygame.Surface((gw, gh), pygame.SRCALPHA)
        ov.fill((5, 8, 25, 220))
        surf.blit(ov, (0,0))

        PW, PH = min(700, gw-40), min(430, gh-80)
        px, py = (gw-PW)//2, (gh-PH)//2
        rr(surf, (18, 22, 52), (px, py, PW, PH), 14)
        pygame.draw.rect(surf, (70, 60, 150), (px, py, PW, PH), 2, border_radius=14)

        # title bar
        rr(surf, (28, 32, 72), (px, py, PW, 38), 14)
        txt(surf, "Recipe Book", 18, C["gold"], px+PW//2, py+19)

        CARD_W = PW//2 - 22
        CARD_H = 66
        MARGIN = 12

        for i, rec in enumerate(RECIPES):
            col  = i % 2
            row  = i // 2
            cx_  = px + MARGIN + col*(CARD_W + MARGIN)
            cy_  = py + 50 + row*(CARD_H + 8)

            if cy_ + CARD_H > py + PH - 30:
                break

            rr(surf, (28, 36, 72), (cx_, cy_, CARD_W, CARD_H), 8)
            pygame.draw.rect(surf, (55, 50, 120), (cx_, cy_, CARD_W, CARD_H), 1, border_radius=8)

            # name
            name_s = F[14].render(rec["name"], True, C["white"])
            surf.blit(name_s, (cx_+8, cy_+6))
            # pts
            pts_s = F[12].render(f"+{rec['pts']} pts", True, C["gold"])
            surf.blit(pts_s, (cx_+CARD_W-pts_s.get_width()-8, cy_+6))

            # ingredient dots
            ing_x = cx_ + 8
            ing_y = cy_ + 24
            for need in rec["needs"]:
                base = need.replace("_c","")
                ing  = INGS.get(base, {})
                dot_col = ing.get("color", (150,150,150))
                pygame.draw.circle(surf, dot_col, (ing_x+6, ing_y), 6)
                ing_x += 18

            # steps
            step_y = ing_y + 14
            for i, step in enumerate(rec.get("steps", [])):
                step_txt = f"{i+1}. {step}"
                step_s = F[11].render(step_txt, True, (200,200,200)) if 11 in F \
                         else F[12].render(step_txt[:25], True, (200,200,200))
                if step_s.get_width() > CARD_W - 16:
                    step_txt = f"{i+1}. {step[:20]}"
                    step_s = F[11].render(step_txt, True, (200,200,200)) if 11 in F \
                             else F[12].render(step_txt, True, (200,200,200))
                surf.blit(step_s, (cx_+8, step_y))
                step_y += 14

            # cook badge
            badge_lbl = "cook" if rec["cook"] else "raw"
            badge_col = C["orange"] if rec["cook"] else C["lime"]
            bs = F[12].render(badge_lbl, True, badge_col)
            surf.blit(bs, (cx_+CARD_W-bs.get_width()-8, cy_+CARD_H-bs.get_height()-3))

        # legend
        txt(surf, "colored dot = ingredient   * = needs chopping   Cook = use stove",
            12, (130,130,170), px+PW//2, py+PH-20)

        txt(surf, "Press R to close", 12, (100,100,150), px+PW//2, py+PH-6)


# ─────────────────────────────────────────────
#  재료 선택 오버레이
# ─────────────────────────────────────────────
class IngredientOverlay:
    CARD_W, CARD_H = 120, 90
    COLS = 5

    def __init__(self):
        self.active = False
        self.cards  = []   # list of (rect, ing_key)
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

        # dim overlay
        ov = pygame.Surface((gw, gh), pygame.SRCALPHA)
        ov.fill((8,12,30,215))
        surf.blit(ov,(0,0))

        # title
        txt(surf,"Select Ingredient",24,C["gold"],gw//2,self.cards[0][0].y-32)

        mpos = pygame.mouse.get_pos()
        for rect, key in self.cards:
            ing = INGS[key]
            hover = rect.collidepoint(mpos)
            bg = C["ov_sel"] if hover else C["ov_card"]
            rr(surf, bg, rect, 10)
            pygame.draw.rect(surf, C["ov_border"] if hover else (60,60,100),
                             rect, 2, border_radius=10)

            # color circle
            pygame.draw.circle(surf, ing["color"],
                               (rect.centerx, rect.y+32), 20)
            # chop badge
            if ing["can_chop"]:
                badge = F[12].render("Choppable",True,(200,200,200))
                surf.blit(badge,(rect.centerx-badge.get_width()//2, rect.y+56))
            else:
                badge = F[12].render("No chop",True,(140,140,140))
                surf.blit(badge,(rect.centerx-badge.get_width()//2, rect.y+56))

            # name
            name_s = F[14].render(ing["label"],True,C["white"])
            surf.blit(name_s,(rect.centerx-name_s.get_width()//2, rect.y+rect.h-22))

        # cancel hint
        txt(surf,"Press ESC or click outside to cancel",12,
            (140,140,170),gw//2,self.cards[0][0].bottom+20)

    def check_click(self, mpos):
        """Return ingredient key if a card was clicked, else None."""
        for rect, key in self.cards:
            if rect.collidepoint(mpos):
                return key
        return None


# ─────────────────────────────────────────────
#  플레이어
# ─────────────────────────────────────────────
class Player:
    PW, PH = 30, 40

    def __init__(self, x, y):
        self.x=float(x); self.y=float(y)
        self.vx=0.0; self.vy=0.0
        self.facing=1
        self.holding=None
        self.walk_t=0.0

    def center(self):
        return (int(self.x+self.PW//2), int(self.y+self.PH//2))

    def update(self, move_dir, dt, gw, gy):
        """move_dir: -1 left, 0 none, 1 right"""
        SPEED = 160
        GRAV  = 950
        if move_dir != 0:
            self.vx = move_dir * SPEED
            self.facing = move_dir
        else:
            self.vx *= 0.55 ** dt
            if abs(self.vx) < 2: self.vx = 0

        self.vy += GRAV * dt
        self.x  += self.vx * dt
        self.y  += self.vy * dt

        if self.y + self.PH >= gy:
            self.y  = gy - self.PH
            self.vy = 0
        self.x = max(4, min(gw - self.PW - 4, self.x))

        if abs(self.vx) > 10:
            self.walk_t += dt * 9

    def draw(self, surf):
        px,py = int(self.x), int(self.y)
        f = self.facing
        walk = abs(self.vx) > 10
        bob  = int(math.sin(self.walk_t)*2) if walk else 0
        ls   = int(math.sin(self.walk_t)*5) if walk else 0
        as_  = int(math.sin(self.walk_t)*4) if walk else 0

        # shadow
        pygame.draw.ellipse(surf,(0,0,0,50),(px+2,py+self.PH-6,self.PW-4,7))
        # legs
        rr(surf,C["char_dark"],(px+5, py+26+ls, 10,14),3)
        rr(surf,C["char_hat"], (px+17,py+26-ls, 10,14),3)
        # body
        rr(surf,C["char_body"],(px+2, py+14+bob,28,18),5)
        # apron
        rr(surf,C["apron"],    (px+7, py+16+bob,18,14),3)
        rr(surf,(200,195,180), (px+9, py+18+bob,14,10),2)
        # arms
        rr(surf,C["char_body"],(px+(26 if f>0 else 0),py+16+bob-as_,7,11),3)
        rr(surf,C["char_body"],(px+(1  if f>0 else 25),py+16+bob+as_,7,11),3)
        # head
        pygame.draw.circle(surf,C["char_face"],(px+16,py+10+bob),11)
        # hat
        rr(surf,C["white"],   (px+7, py+1+bob,18,8),2)
        rr(surf,(230,230,230),(px+4, py+7+bob,24,4),1)
        # eyes
        ex = px+16+f*4
        pygame.draw.circle(surf,C["char_hat"],(ex,py+10+bob),2)
        pygame.draw.circle(surf,(255,255,255),(ex+1,py+9+bob),1)
        # smile
        pygame.draw.arc(surf,(80,60,30),(px+12+f,py+12+bob,8,5),
                        math.pi+0.2,2*math.pi-0.2,2)

        # held item bubble
        if self.holding:
            hx = px+16+f*24
            hy = py+4+bob
            bid = self.holding["id"].replace("_c","")
            ing = INGS.get(bid,{})
            col = C["burn"]   if self.holding.get("burned") \
                 else C["green"]  if self.holding.get("cooked") \
                 else C["lime"]   if self.holding.get("chopped") \
                 else ing.get("color",(150,150,150))
            pygame.draw.circle(surf,col,(hx,hy),13)
            pygame.draw.circle(surf,(255,255,255,50),(hx,hy),13,1)
            if self.holding.get("burned"):
                lbl=F[12].render("BURN",True,(255,200,100))
            elif self.holding.get("cooked"):
                lbl=F[12].render("Done",True,(255,255,255))
            elif self.holding.get("chopped"):
                lbl=F[12].render("Cut",True,(0,0,0))
            else:
                lbl=F[12].render(ing.get("label","")[:3],True,(0,0,0))
            surf.blit(lbl,(hx-lbl.get_width()//2,hy-lbl.get_height()//2))


# ─────────────────────────────────────────────
#  주문 카드
# ─────────────────────────────────────────────
ORDER_TIME = 55.0   # 주문당 제한 시간 (초)

class Order:
    _ctr = 0
    def __init__(self, recipe):
        Order._ctr += 1
        self.id=Order._ctr
        self.recipe=recipe
        self.t=ORDER_TIME
        self.status="active"

    def update(self,dt):
        if self.status!="active": return None
        self.t=max(0.0,self.t-dt)
        if self.t<=0:
            self.status="failed"
            return "failed"
        return None

    def draw(self,surf,x,y,w=80):
        h=56
        urg   = self.t<15 and self.status=="active"
        fail  = self.status=="failed"
        brd   = C["red"] if fail else C["ord_urg"] if urg else C["ord_brd"]
        a     = 90 if fail else 255

        bg=pygame.Surface((w,h),pygame.SRCALPHA)
        bg.fill((*C["ord_bg"],a)); surf.blit(bg,(x,y))
        pygame.draw.rect(surf,brd,(x,y,w,h),1,border_radius=7)

        nm=F[12].render(self.recipe["name"],True,
                        C["blue"] if not fail else (130,130,130))
        surf.blit(nm,(x+w//2-nm.get_width()//2,y+5))

        abbr=" ".join(
            n.replace("_c","*").replace("tomato","Tom").replace("carrot","Car")
             .replace("onion","Oni").replace("mushroom","Msh").replace("rice","Ric")
            for n in self.recipe["needs"])
        ni=F[12].render(abbr,True,(150,150,150))
        surf.blit(ni,(x+w//2-ni.get_width()//2,y+20))

        pct = self.t/ORDER_TIME if self.status=="active" else 0
        col_f=C["green"] if pct>0.4 else C["orange"] if pct>0.15 else C["red"]
        bar(surf,x+4,y+h-11,w-8,6,pct,(25,38,48),col_f,2)


# ─────────────────────────────────────────────
#  게임
# ─────────────────────────────────────────────
GAME_TIME = 120.0

class Game:
    def __init__(self):
        self.state="title"
        self.overlay = IngredientOverlay()
        self.recipe_overlay = RecipeOverlay()
        self._make_btns()
        self.reset()

    # ── setup ────────────────────────────────
    def reset(self):
        self.score=0
        self.timer=GAME_TIME
        self.orders=[]; self.popups=[]
        self.elapsed=0.0; self.next_order=0.0
        self._build_level()
        gw,gh=screen.get_size()
        gy=self._gy()
        self.player=Player(gw//2-15,gy-50)
        self.overlay.active=False
        self.overlay.rebuild()
        self.recipe_overlay.active=False

    def _gy(self):
        _,gh=screen.get_size()
        return gh - 80  # room for bottom buttons

    def _build_level(self):
        gw,gh=screen.get_size()
        gy=self._gy()
        self.gw,self.gh=gw,gh

        # 6 stations — pushed down close to ground so recipe panel has space above
        N   = 6
        pad = 20
        gap = (gw - 2*pad - N*Station.SW) // (N-1)
        sy  = gy - Station.SH - 36   # station surface y (closer to ground)

        kinds = ["trash","ing","chop","pot","pot","plate_submit"]
        self.stations=[]
        for i,k in enumerate(kinds):
            sx = pad + i*(Station.SW+gap)
            self.stations.append(Station(k,sx,sy))

    def _recipe_panel_rect(self):
        """Returns (x, y, w, h) of the always-visible recipe panel area."""
        gw, gh = screen.get_size()
        HUD_H = 44
        gy = self._gy()
        # station tops sit at gy - SH - 36 - icon_space (~36px above surface)
        station_top = gy - Station.SH - 36 - 40
        pad = 8
        return (pad, HUD_H + pad, gw - pad*2, station_top - HUD_H - pad*2)

    def _make_btns(self):
        gw,gh=screen.get_size()
        bh,bw=52,90
        y=gh-bh-10
        self.btn_left   = Btn(10,        y, bw,   bh, "◀ Left",  (40,80,40))
        self.btn_right  = Btn(10+bw+8,   y, bw,   bh, "Right ▶", (40,80,40))
        self.btn_action = Btn(gw-bw-10,  y, bw,   bh, "Action",  (80,40,40))
        self.btn_recipe = Btn(gw-bw*2-18,y, bw,   bh, "Recipe R",(50,50,100))
        self.btn_start  = Btn(gw//2-55,  gh//2+70,110,bh,"Start",(50,50,130))

    # ── station interaction ───────────────────
    def _near(self):
        px,py=self.player.center()
        best,bd=None,9999
        for s in self.stations:
            d=s.dist(px,py)
            if d<110 and d<bd:
                best,bd=s,d
        return best

    def do_action(self):
        # overlay open: action = confirm first hovered card
        if self.overlay.active:
            self.overlay.active=False
            return

        st=self._near()
        if not st: return
        h=self.player.holding

        # ── pantry: open ingredient overlay
        if st.kind=="ing":
            if not h:
                self.overlay.active=True
            else:
                self._pop(self.player.x,self.player.y-20,
                          "Drop item first!",C["red"])
            return

        # ── chop board
        if st.kind=="chop":
            if h:
                base=h["id"].replace("_c","")
                if h.get("chopped"):
                    self._pop(self.player.x,self.player.y-20,"Already chopped",C["white"])
                    return
                if not INGS.get(base,{}).get("can_chop"):
                    self._pop(self.player.x,self.player.y-20,"Can't chop this!",C["red"])
                    return
                
                # board에 chopped된 재료가 있으면: 먼저 그걸 손에 들기
                if st.chop_item and st.chop_item.get("chopped"):
                    self.player.holding=dict(st.chop_item)
                    st.chop_item=None; st.chop_prog=0.0; st.chopping=False
                    self._pop(self.player.x,self.player.y-20,"Picked up",C["lime"])
                    return  # chopped된 재료를 손에 들고 끝냄
                
                # board에 재료가 있으면 (chopping 중이든 아니든): 기존 재료 지우기
                if st.chop_item:
                    if st.chopping:
                        self._pop(st.cx(),st.y-14,"Wait for chopping to finish",C["orange"])
                        return
                    st.chop_item=None; st.chop_prog=0.0; st.chopping=False
                
                # board가 비어있으면 (또는 위에서 지웠으면): 새 재료 놓기
                if not st.chop_item:
                    st.chop_item=dict(h); self.player.holding=None; st.chop_prog=0.0
                    st.chopping=True
                    self._pop(st.cx(),st.y-14,"Chopping...",C["orange"])
            else:
                if st.chop_item and st.chop_item.get("chopped"):
                    self.player.holding=dict(st.chop_item)
                    st.chop_item=None; st.chop_prog=0.0; st.chopping=False
                    self._pop(self.player.x,self.player.y-20,"Picked up",C["lime"])
                elif st.chop_item and not st.chopping:
                    st.chopping=True
                    self._pop(st.cx(),st.y-14,"Chopping...",C["orange"])
            return

        # ── pot / stove
        if st.kind=="pot":
            burned = st.pot_cooked and st.pot_burn>=BURN_TIME
            if h and not st.pot_cooked:
                st.pot_items.append(dict(h)); self.player.holding=None
                self._pop(st.cx(),st.y-14,"Added ✓",C["gold"])
            elif not h and st.pot_items and not st.pot_cooking and not st.pot_cooked:
                st.pot_on=True; st.pot_cooking=True
                self._pop(st.cx(),st.y-14,"Fire on! 🔥",C["orange"])
            elif not h and st.pot_cooked and not burned:
                self.player.holding={
                    "id":"cooked","label":"Cooked Dish",
                    "contents":list(st.pot_items),"cooked":True}
                st.pot_items=[]; st.pot_cooked=False
                st.pot_cooking=False; st.pot_prog=0.0
                st.pot_on=False; st.pot_burn=0.0
                self._pop(self.player.x,self.player.y-20,"Picked!",C["green"])
            elif not h and burned:
                # discard burned food
                st.pot_items=[]; st.pot_cooked=False
                st.pot_cooking=False; st.pot_prog=0.0
                st.pot_on=False; st.pot_burn=0.0
                self._pop(st.cx(),st.y-14,"Burned! Cleared.",C["burn"])
            elif not h and st.pot_cooking:
                self._pop(st.cx(),st.y-14,"Cooking...",C["white"])
            return

        # ── plate + submit
        if st.kind=="plate_submit":
            if h and h.get("cooked") and not h.get("burned"):
                if not st.plate_item:
                    st.plate_item=dict(h); self.player.holding=None
                    self._pop(st.cx(),st.y-14,"Plated!",C["lime"])
                else:
                    self._pop(st.cx(),st.y-14,"Plate occupied!",C["red"])
            elif not h and st.plate_item:
                # try to submit
                dish=st.plate_item
                # get ingredient ids (already have _c suffix if chopped)
                h_ids=sorted(c["id"] for c in dish["contents"])
                matched=None
                for o in self.orders:
                    if o.status!="active": continue
                    if sorted(o.recipe["needs"])==h_ids:
                        matched=o; break
                if matched:
                    bonus=int(matched.t/ORDER_TIME*50)
                    pts=matched.recipe["pts"]+bonus
                    self.score+=pts
                    matched.status="done"
                    st.plate_item=None
                    self._pop(st.cx(),st.y-30,f"+{pts} pts! 🎉",C["green"])
                else:
                    self._pop(st.cx(),st.y-14,"No matching order!",C["red"])
                    st.plate_item=None
            elif h and h.get("burned"):
                self.player.holding=None
                self._pop(self.player.x,self.player.y-20,"Burned food discarded",C["burn"])
            return

        # ── trash
        if st.kind=="trash":
            if h:
                self.player.holding=None
                self._pop(st.cx(),st.y-14,"Trashed!",C["pink"])
            else:
                # also clear chop board if empty-handed
                chop=next((s for s in self.stations if s.kind=="chop"),None)
                if chop and chop.chop_item:
                    chop.chop_item=None; chop.chop_prog=0.0; chop.chopping=False
                    self._pop(st.cx(),st.y-14,"Chop board cleared",C["pink"])
                else:
                    self._pop(st.cx(),st.y-14,"Nothing to trash",C["white"])
            return

    def _pick_ingredient(self, ing_key):
        """Called when player selects an ingredient from overlay."""
        ing=INGS[ing_key]
        self.player.holding={"id":ing_key,"label":ing["label"],"chopped":False}
        self._pop(self.player.x,self.player.y-20,f"Picked {ing['label']}",C["lime"])
        self.overlay.active=False

    def _pop(self,x,y,msg,col):
        self.popups.append(Popup(x,y,msg,col))

    def _spawn_order(self):
        active=sum(1 for o in self.orders if o.status=="active")
        if active>=3: return
        self.orders.append(Order(random.choice(RECIPES)))

    # ── hint ─────────────────────────────────
    def _hint(self):
        if self.overlay.active:
            return "Click an ingredient card  |  ESC to cancel"
        st=self._near()
        if not st: return ""
        h=self.player.holding
        k=st.kind
        if k=="ing":
            return "Action: Open pantry" if not h else "Action: Drop item first"
        if k=="chop":
            if h and not h.get("chopped") and INGS.get(h["id"].replace("_c",""),{}).get("can_chop"):
                return "Action: Place & chop"
            if not h and st.chop_item and st.chop_item.get("chopped"):
                return "Action: Pick chopped item"
            if not h and st.chop_item:
                return "Action: Start chopping"
        if k=="pot":
            burned=st.pot_cooked and st.pot_burn>=BURN_TIME
            if burned: return "Action: Clear burned food"
            if h and not st.pot_cooked: return "Action: Add to pot"
            if not h and st.pot_items and not st.pot_cooking and not st.pot_cooked:
                return "Action: Turn on fire 🔥"
            if not h and st.pot_cooked: return "Action: Pick cooked dish"
        if k=="plate_submit":
            if h and h.get("cooked") and not h.get("burned"):
                return "Action: Place on plate"
            if not h and st.plate_item:
                return "Action: Submit dish!"
        if k=="trash":
            if h: return "Action: Trash item"
            return "Action: Clear chop board"
        return ""

    # ── update ───────────────────────────────
    def update(self, dt, move_dir, action_now, mpos, mpressed, overlay_click):
        gw,gh=screen.get_size()
        if gw!=self.gw or gh!=self.gh:
            self.gw,self.gh=gw,gh
            self._build_level(); self._make_btns()
            self.overlay.rebuild()

        # title / over: only start button
        if self.state in("title","over"):
            if self.btn_start.update(mpos,mpressed):
                self.reset(); self.state="play"
                self._spawn_order(); self._spawn_order()
            return

        # overlay click
        if self.overlay.active:
            if overlay_click:
                key=self.overlay.check_click(overlay_click)
                if key:
                    self._pick_ingredient(key)
                else:
                    self.overlay.active=False   # clicked outside
            return

        # recipe overlay blocks gameplay too
        if self.recipe_overlay.active:
            return

        # button updates
        left_held  = self.btn_left.held
        right_held = self.btn_right.held
        self.btn_left.update(mpos,mpressed)
        self.btn_right.update(mpos,mpressed)
        left_held  = self.btn_left.held
        right_held = self.btn_right.held
        if self.btn_action.update(mpos,mpressed):
            action_now=True
        if self.btn_recipe.update(mpos,mpressed):
            self.recipe_overlay.active = not self.recipe_overlay.active

        # combine button + keyboard
        if left_held:   move_dir=-1
        elif right_held: move_dir=1

        self.player.update(move_dir, dt, gw, self._gy())
        if action_now:
            self.do_action()

        # stations
        for s in self.stations:
            events=s.update(dt)
            for ev in events:
                if ev=="chop_done":
                    self._pop(s.cx(),s.y-14,"✓ Chopped!",C["lime"])
                elif ev=="cook_done":
                    self._pop(s.cx(),s.y-14,"✓ Cooked! Pick it up!",C["green"])
                elif ev=="burned":
                    self._pop(s.cx(),s.y-14,"🔥 BURNED!",C["burn"])

        # orders
        for o in self.orders:
            ev=o.update(dt)
            if ev=="failed":
                self.score=max(0,self.score-30)
                self._pop(gw//2,gh//2-80,"Order failed! -30",C["red"])

        # spawn
        self.elapsed+=dt
        if self.elapsed>=self.next_order:
            self._spawn_order()
            self.next_order=self.elapsed+15.0

        # timer
        self.timer=max(0.0,self.timer-dt)
        if self.timer<=0:
            self.state="over"

        # popups
        for p in self.popups: p.update()
        self.popups=[p for p in self.popups if not p.dead]

    # ── draw ─────────────────────────────────
    def draw(self):
        gw,gh=screen.get_size()
        gy=self._gy()

        screen.fill(C["bg"])
        # grid
        for y in range(0,gh,32):
            pygame.draw.line(screen,(*C["grid"],20),(0,y),(gw,y),1)
        # tiles
        for x in range(0,gw,36):
            c=C["tile_a"] if (x//36)%2==0 else C["tile_b"]
            screen.fill(c,(x,0,35,gy))

        # ground
        screen.fill(C["ground"],(0,gy,gw,gh-gy))
        for x in range(0,gw,30):
            c=C["tile_a"] if (x//30)%2==0 else C["tile_b"]
            screen.fill(c,(x,gy,29,7))
        pygame.draw.line(screen,(*C["ground_line"],100),(0,gy),(gw,gy),2)
        screen.fill((8,8,26),(0,gy+7,gw,gh-gy-7))

        for s in self.stations:
            s.draw(screen,gy)

        # near highlight
        ns=self._near()
        if ns and not self.overlay.active:
            pygame.draw.rect(screen,(*C["yellow"],200),
                             (ns.x-2,ns.y-2,ns.w+4,ns.h+4),2,border_radius=8)

        self.player.draw(screen)

        for p in self.popups: p.draw(screen)

        # overlay on top
        self.overlay.draw(screen)
        self.recipe_overlay.draw(screen)

        self._draw_hud(gw,gh)
        if not self.overlay.active:  # only show recipe panel when pantry is closed
            self._draw_recipes_panel()

        # buttons
        if self.state=="play":
            self.btn_left.draw(screen)
            self.btn_right.draw(screen)
            self.btn_action.draw(screen)

    def _draw_recipes_panel(self):
        rx, ry, rw, rh = self._recipe_panel_rect()
        if rh < 60: return  # not enough room

        # panel background
        rr(screen, (16, 20, 48), (rx, ry, rw, rh), 10)
        pygame.draw.rect(screen, (45, 40, 100), (rx, ry, rw, rh), 1, border_radius=10)

        # title
        title_s = F[14].render("Current Orders", True, C["gold"])
        screen.blit(title_s, (rx+10, ry+6))

        # get active orders only
        active_orders = [o for o in self.orders if o.status == "active"]
        if not active_orders:
            no_order_s = F[12].render("No active orders", True, (150,150,150))
            screen.blit(no_order_s, (rx+10, ry+35))
            return

        n = len(active_orders)
        if n == 0: return

        # figure out card layout
        TITLE_H = 24
        area_y = ry + TITLE_H
        area_h = rh - TITLE_H - 4
        area_w = rw - 12

        # try to fit all active orders in one row; if card height too small, do 2 rows
        card_w = area_w // n - 6
        card_h = area_h - 4

        cols = n
        rows = 1
        if card_h < 55:
            cols = (n + 1) // 2
            rows = 2
            card_w = area_w // cols - 6
            card_h = area_h // 2 - 6

        card_w = max(card_w, 80)

        for i, order in enumerate(active_orders):
            rec = order.recipe
            col = i % cols
            row = i // cols
            cx_ = rx + 6 + col * (card_w + 6)
            cy_ = area_y + 2 + row * (card_h + 4)

            if cy_ + card_h > ry + rh - 2:
                break

            # card bg
            rr(screen, (24, 30, 62), (cx_, cy_, card_w, card_h), 6)
            pygame.draw.rect(screen, (55, 48, 115), (cx_, cy_, card_w, card_h), 1, border_radius=6)

            inner_y = cy_ + 4

            # recipe name
            name_s = F[14].render(rec["name"], True, C["white"])
            if name_s.get_width() > card_w - 6:
                name_s = F[12].render(rec["name"], True, C["white"])
            screen.blit(name_s, (cx_+4, inner_y))

            # pts badge top-right
            pts_s = F[12].render(f"+{rec['pts']}", True, C["gold"])
            screen.blit(pts_s, (cx_+card_w-pts_s.get_width()-4, inner_y))

            inner_y += name_s.get_height() + 2

            # ingredient dots row (small)
            dot_x = cx_ + 4
            for j, need in enumerate(rec["needs"]):
                base = need.replace("_c","")
                ing  = INGS.get(base, {})
                col_dot = ing.get("color", (150,150,150))
                r_dot = 5
                dy = inner_y + r_dot

                if dot_x + r_dot*2 + 2 > cx_ + card_w - 4:
                    break

                pygame.draw.circle(screen, col_dot, (dot_x + r_dot, dy), r_dot)
                dot_x += r_dot*2 + 6

            inner_y += 14

            # steps
            for idx, step in enumerate(rec.get("steps", [])):
                step_txt = f"{idx+1}. {step}"
                step_s = F[11].render(step_txt, True, (200,200,100)) if 11 in F \
                         else F[12].render(step_txt[:22], True, (200,200,100))
                if step_s.get_width() > card_w - 8:
                    step_txt = f"{idx+1}. {step[:18]}"
                    step_s = F[11].render(step_txt, True, (200,200,100)) if 11 in F \
                             else F[12].render(step_txt, True, (200,200,100))
                screen.blit(step_s, (cx_+4, inner_y))
                inner_y += step_s.get_height() + 1

            # cook/raw badge bottom
            badge_lbl = "cook" if rec["cook"] else "raw"
            badge_col = C["orange"] if rec["cook"] else C["lime"]
            bs = F[12].render(badge_lbl, True, badge_col)
            screen.blit(bs, (cx_+card_w-bs.get_width()-4, cy_+card_h-bs.get_height()-3))

    def _draw_hud(self,gw,gh):
        HH=44
        rr(screen,C["hud_bg"],(0,0,gw,HH),0)
        pygame.draw.line(screen,C["hud_brd"],(0,HH),(gw,HH),1)

        # score
        sc=F[18].render(f"Score  {self.score}",True,C["gold"])
        screen.blit(sc,(12,HH//2-sc.get_height()//2))

        # timer
        m=int(self.timer)//60; s=int(self.timer)%60
        tc=C["red"] if self.timer<20 else C["white"]
        tm=F[24].render(f"{m}:{s:02d}",True,tc)
        screen.blit(tm,(gw//2-tm.get_width()//2,HH//2-tm.get_height()//2))

        # orders
        ox=gw-8
        for o in reversed([o for o in self.orders if o.status!="done"]):
            ox-=84
            o.draw(screen,ox,2,w=82)

        # hint
        hint=self._hint()
        if hint:
            hs=F[12].render(hint,True,(200,200,200))
            hw=hs.get_width()+16; hh2=hs.get_height()+8
            bg=pygame.Surface((hw,hh2),pygame.SRCALPHA)
            bg.fill((0,0,0,160))
            hy=self._gy()-hh2-4
            screen.blit(bg,(gw//2-hw//2,hy))
            screen.blit(hs,(gw//2-hs.get_width()//2,hy+4))

    def draw_title(self):
        gw,gh=screen.get_size()
        screen.fill(C["bg"])
        txt(screen,"🍳 Cooking Game",40,C["gold"],gw//2,gh//2-110)
        lines=[
            "Use screen buttons  (◀ ▶ move  |  Action = interact)",
            "Keyboard: arrow keys + Z/Space also work",
            "",
            "Pantry → pick ingredient   |   Chop board → chop",
            "Stove → add ingredients → fire on → pick when done",
            "Plate/Submit → plate dish → submit for points",
            "Trash → drop unwanted items or clear chop board",
            "",
            "⚠  Leave pot too long after cooking → BURNED!",
            "Press R or Recipe button to view recipes anytime",
        ]
        for i,line in enumerate(lines):
            txt(screen,line,14,(170,170,210),gw//2,gh//2-50+i*22)
        self.btn_start.draw(screen)

    def draw_over(self):
        self.draw()
        gw,gh=screen.get_size()
        ov=pygame.Surface((gw,gh),pygame.SRCALPHA)
        ov.fill((5,5,20,210)); screen.blit(ov,(0,0))
        txt(screen,"Game Over!",40,C["gold"],gw//2,gh//2-80)
        txt(screen,f"{self.score} pts",40,C["white"],gw//2,gh//2-20)
        txt(screen,"Click Start to play again",18,(150,150,200),gw//2,gh//2+40)
        self.btn_start.draw(screen)


# ─────────────────────────────────────────────
#  메인 루프
# ─────────────────────────────────────────────
def main():
    game=Game()

    # keyboard hold state
    held={"left":False,"right":False}
    # smooth repeat
    rep={"left":{"t":0,"active":False},"right":{"t":0,"active":False}}
    RD,RI=0.25,0.09

    mpressed=False
    overlay_click=None

    while True:
        dt=min(clock.tick(FPS)/1000.0, 0.05)

        action_now=False
        overlay_click=None

        for event in pygame.event.get():
            if event.type==pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type==pygame.KEYDOWN:
                if event.key in(pygame.K_LEFT,pygame.K_a):
                    held["left"]=True; rep["left"]={"t":0,"active":False}
                if event.key in(pygame.K_RIGHT,pygame.K_d):
                    held["right"]=True; rep["right"]={"t":0,"active":False}
                if event.key in(pygame.K_z,pygame.K_SPACE):
                    if game.state=="play": action_now=True
                    elif game.state in("title","over"):
                        game.reset(); game.state="play"
                        game._spawn_order(); game._spawn_order()
                if event.key==pygame.K_r:
                    if game.state=="play":
                        game.recipe_overlay.active = not game.recipe_overlay.active
                        game.overlay.active = False
                if event.key==pygame.K_RETURN:
                    if game.state in("title","over"):
                        game.reset(); game.state="play"
                        game._spawn_order(); game._spawn_order()
                if event.key==pygame.K_ESCAPE:
                    if game.recipe_overlay.active:
                        game.recipe_overlay.active=False
                    elif game.overlay.active:
                        game.overlay.active=False
                    else:
                        pygame.quit(); sys.exit()
            if event.type==pygame.KEYUP:
                if event.key in(pygame.K_LEFT,pygame.K_a):  held["left"]=False
                if event.key in(pygame.K_RIGHT,pygame.K_d): held["right"]=False
            if event.type==pygame.MOUSEBUTTONDOWN and event.button==1:
                mpressed=True
                if game.overlay.active:
                    overlay_click=pygame.mouse.get_pos()
            if event.type==pygame.MOUSEBUTTONUP and event.button==1:
                mpressed=False

        # keyboard repeat logic
        move_dir=0
        for k,d in (("left",-1),("right",1)):
            if held[k]:
                rep[k]["t"]+=dt
                delay=RD if not rep[k]["active"] else RI
                if rep[k]["t"]>=delay:
                    move_dir=d
                    rep[k]["t"]=0; rep[k]["active"]=True

        mpos=pygame.mouse.get_pos()
        game.update(dt, move_dir, action_now, mpos, mpressed, overlay_click)

        if game.state=="title":
            game.draw_title()
        elif game.state=="over":
            game.draw_over()
        else:
            game.draw()

        pygame.display.flip()


if __name__=="__main__":
    main()
