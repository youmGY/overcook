#!/usr/bin/env python3
"""
오버쿡 스타일 요리 게임 (pygame)
실행: python game.py
조작: 화면 버튼 (← → 이동 | 행동 버튼)
설치: pip install pygame
"""

import pygame
import sys
import math
import random
import time

# ── 초기화 ───────────────────────────────────────────
pygame.init()
pygame.display.set_caption("🍳 요리 게임")

W, H = 800, 480
screen = pygame.display.set_mode((W, H), pygame.RESIZABLE)
clock = pygame.time.Clock()
FPS = 60

# ── 색상 ─────────────────────────────────────────────
C = {
    "bg":         (11,  11,  28),
    "ground":     (24,  24,  58),
    "ground_top": (46,  46,  90),
    "tile_a":     (32,  32,  66),
    "tile_b":     (26,  26,  52),
    "wall":       (18,  18,  40),
    "grid":       (40,  35, 100),

    "counter_base": (42, 24,  8),
    "counter_top":  (107,76, 42),
    "chop_base":    (10, 32, 10),
    "chop_top":     (42,160, 90),
    "pot_base":     (26, 8,   8),
    "pot_off":      (51, 51, 51),
    "pot_on":       (160,35,  0),
    "plate_base":   (10, 10, 42),
    "plate_top":    (46, 46,106),
    "submit_base":  (8,  24,  8),
    "submit_top":   (29,158,117),
    "trash_base":   (32,  8,  8),
    "trash_top":    (122,32, 64),

    "char_body":  ( 83, 65,183),
    "char_dark":  ( 57, 40,137),
    "char_face":  (245,214,184),
    "char_hat":   ( 38, 33,105),
    "apron":      (224,220,208),

    "white":  (255,255,255),
    "black":  (  0,  0,  0),
    "yellow": (255,215, 80),
    "orange": (239,159, 39),
    "red":    (226, 75, 74),
    "green":  (29, 158,117),
    "lime":   (151,196, 89),
    "gold":   (250,199,117),
    "blue":   (133,183,235),
    "purple": (127,119,221),
    "pink":   (212, 83,126),

    "hud_bg":     (22, 22, 46),
    "hud_border": (60, 48,137),
    "order_bg":   (15, 42, 63),
    "order_brd":  (55,138,221),
    "order_urg":  (239,159, 39),
    "popup_bg":   ( 0,  0,  0, 160),
}

# ── Ingredients Definition ─────────────────────────────────────────
INGS = {
    "tomato":   {"label": "Tomato", "color": (226, 75, 74),  "can_chop": True},
    "carrot":   {"label": "Carrot", "color": (239,159, 39),  "can_chop": True},
    "onion":    {"label": "Onion",  "color": (175,169,236),  "can_chop": True},
    "mushroom": {"label": "Mushroom", "color": (180,178,169),  "can_chop": True},
    "rice":     {"label": "Rice",   "color": (232,224,208),  "can_chop": False},
}

# ── Recipe Definition ───────────────────────────────────────
RECIPES = [
    {"name": "Tomato Soup", "pts": 100, "needs": ["tomato_c", "onion_c"],          "cook": True},
    {"name": "Fried Rice",  "pts": 110, "needs": ["rice",     "tomato_c"],          "cook": True},
    {"name": "Mushroom Stir Fry", "pts":  90, "needs": ["mushroom_c","onion_c"],          "cook": True},
    {"name": "Vegetable Curry", "pts": 150, "needs": ["carrot_c", "onion_c", "rice"],   "cook": True},
    {"name": "Carrot Soup", "pts":  80, "needs": ["carrot_c"],                      "cook": True},
    {"name": "Vegetable Salad", "pts":  70, "needs": ["tomato_c", "mushroom_c"],        "cook": False},
]

# ── 폰트 ─────────────────────────────────────────────
try:
    # 한글 지원 폰트 자동 탐색
    import os
    candidates = [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "C:/Windows/Fonts/malgun.ttf",
    ]
    font_path = next((p for p in candidates if os.path.exists(p)), None)
    if font_path:
        FONT_SM  = pygame.font.Font(font_path, 13)
        FONT_MD  = pygame.font.Font(font_path, 16)
        FONT_LG  = pygame.font.Font(font_path, 22)
        FONT_XL  = pygame.font.Font(font_path, 36)
        FONT_HUD = pygame.font.Font(font_path, 20)
    else:
        raise FileNotFoundError
except Exception:
    FONT_SM  = pygame.font.SysFont("Arial", 13)
    FONT_MD  = pygame.font.SysFont("Arial", 16)
    FONT_LG  = pygame.font.SysFont("Arial", 22)
    FONT_XL  = pygame.font.SysFont("Arial", 36)
    FONT_HUD = pygame.font.SysFont("Arial", 20)


# ── 유틸 ─────────────────────────────────────────────
def rr(surf, color, rect, radius=6):
    """둥근 사각형 그리기"""
    pygame.draw.rect(surf, color, rect, border_radius=radius)

def text(surf, txt, font, color, cx, cy, anchor="center"):
    s = font.render(str(txt), True, color)
    r = s.get_rect()
    if anchor == "center": r.center = (cx, cy)
    elif anchor == "midleft": r.midleft = (cx, cy)
    elif anchor == "midright": r.midright = (cx, cy)
    surf.blit(s, r)

def draw_bar(surf, x, y, w, h, pct, col_bg, col_fill, radius=3):
    rr(surf, col_bg,   (x, y, w, h), radius)
    if pct > 0:
        rr(surf, col_fill, (x, y, int(w * pct), h), radius)

# ── 버튼 클래스 ───────────────────────────────────────
class Button:
    def __init__(self, x, y, w, h, text, color=(60,60,120), text_color=(255,255,255)):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.text = text
        self.color = color
        self.text_color = text_color
        self.pressed = False
        self.hover = False
        
    @property
    def rect(self):
        return pygame.Rect(self.x, self.y, self.w, self.h)
        
    def handle_mouse(self, mouse_pos, mouse_pressed):
        old_hover = self.hover
        old_pressed = self.pressed
        
        self.hover = self.rect.collidepoint(mouse_pos)
        self.pressed = self.hover and mouse_pressed
        
        # Return True if button was just pressed (not held)
        return self.pressed and not old_pressed
        
    def draw(self, surf):
        # Button background
        color = self.color
        if self.pressed:
            color = tuple(max(0, c - 40) for c in color)
        elif self.hover:
            color = tuple(min(255, c + 20) for c in color)
            
        rr(surf, color, self.rect, 8)
        
        # Button border
        border_color = (255,255,255,100) if self.hover else (255,255,255,60)
        pygame.draw.rect(surf, border_color, self.rect, 2, border_radius=8)
        
        # Button text
        text_surf = FONT_MD.render(self.text, True, self.text_color)
        text_rect = text_surf.get_rect(center=self.rect.center)
        surf.blit(text_surf, text_rect)


# ── 팝업 메시지 ───────────────────────────────────────
class Popup:
    def __init__(self, x, y, text, color):
        self.x, self.y0 = x, y
        self.y = float(y)
        self.text = text
        self.color = color
        self.life = 90  # frames

    def update(self):
        self.life -= 1
        self.y -= 0.7

    def draw(self, surf):
        alpha = min(255, int(self.life / 20 * 255))
        s = FONT_MD.render(self.text, True, self.color)
        bg = pygame.Surface((s.get_width() + 14, s.get_height() + 8), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 140))
        pygame.draw.rect(bg, (0,0,0,0), bg.get_rect(), border_radius=5)
        bg.set_alpha(alpha)
        s.set_alpha(alpha)
        bx = int(self.x) - bg.get_width() // 2
        by = int(self.y) - bg.get_height() // 2
        surf.blit(bg, (bx, by))
        surf.blit(s, (int(self.x) - s.get_width()//2, by + 4))

    @property
    def dead(self): return self.life <= 0


# ── 스테이션 ─────────────────────────────────────────
class Station:
    W = 78
    H = 24
    LEG_COLOR = None  # set per type

    def __init__(self, stype, x, y, **kwargs):
        self.type = stype
        self.x, self.y = x, y
        self.w, self.h = self.W, self.H
        self.label = kwargs.get("label", "")
        # per-type state
        self.ing_id   = kwargs.get("ing_id", None)       # ingredient dispenser
        self.contents = kwargs.get("contents", None)      # chop / plate / cooked item
        self.prog     = 0.0
        self.chopping = False
        self.pot_contents = []                             # pot
        self.cooked   = False
        self.cooking  = False
        self.on       = False

    @property
    def rect(self):
        return pygame.Rect(self.x, self.y, self.w, self.h)

    def center(self):
        return (self.x + self.w // 2, self.y + self.h // 2)

    def dist(self, px, py):
        cx, cy = self.center()
        return math.hypot(px - cx, py - cy)

    def update(self, dt):
        if self.type == "chop" and self.chopping and self.contents and not self.contents.get("chopped"):
            self.prog = min(1.0, self.prog + dt * 0.013)
            if self.prog >= 1.0:
                self.contents["chopped"] = True
                self.contents["id"] = self.contents["id"] + "_c"
                self.contents["label"] = "Chopped " + self.contents["label"]
                self.chopping = False
                return "chop_done"
        if self.type == "pot" and self.cooking and not self.cooked:
            self.prog = min(1.0, self.prog + dt * 0.009)
            if self.prog >= 1.0:
                self.cooked = True
                self.cooking = False
                return "cook_done"
        return None

    def draw(self, surf, gy):
        # colors
        if   self.type == "ing":    base, top = C["counter_base"], C["counter_top"]
        elif self.type == "chop":   base, top = C["chop_base"],    C["chop_top"]
        elif self.type == "pot":    base, top = C["pot_base"],     C["pot_on"] if self.on else C["pot_off"]
        elif self.type == "plate":  base, top = C["plate_base"],   C["plate_top"]
        elif self.type == "submit": base, top = C["submit_base"],  C["submit_top"]
        elif self.type == "trash":  base, top = C["trash_base"],   C["trash_top"]
        else:                       base, top = (30,30,30), (60,60,60)

        # leg pillar
        leg_rect = (self.x + 6, self.y + self.h, self.w - 12, gy - self.y - self.h)
        rr(surf, base, leg_rect, 2)

        # surface top
        rr(surf, top, (self.x, self.y, self.w, self.h), 5)
        # sheen
        surf.fill((255,255,255,20), (self.x+4, self.y+2, self.w-8, 2))

        # label
        lbl = FONT_SM.render(self.label, True, (255,255,255,200))
        surf.blit(lbl, (self.x + self.w//2 - lbl.get_width()//2, self.y + self.h//2 - lbl.get_height()//2))

        # icon area above surface
        ix, iy = self.x + self.w // 2, self.y - 14

        if self.type == "ing":
            ing = INGS.get(self.ing_id, {})
            color = ing.get("color", (150,150,150))
            pygame.draw.circle(surf, color, (ix, iy), 10)
            pygame.draw.circle(surf, (255,255,255,80), (ix, iy), 10, 1)
            lbl2 = FONT_SM.render(ing.get("label","")[:2], True, (0,0,0))
            surf.blit(lbl2, (ix - lbl2.get_width()//2, iy - lbl2.get_height()//2))

        elif self.type == "chop":
            if self.contents:
                bid = self.contents["id"].replace("_c","")
                color = INGS.get(bid,{}).get("color",(150,150,150))
                done = self.contents.get("chopped", False)
                pygame.draw.circle(surf, color, (ix-6, iy), 8)
                if done:
                    # checkmark
                    pygame.draw.line(surf, C["lime"], (ix-2, iy+2), (ix+6, iy-4), 2)
                # progress bar
                if not done:
                    draw_bar(surf, self.x+2, self.y-7, self.w-4, 4,
                             self.prog, (60,60,60), C["orange"], 2)
            else:
                # knife icon
                pygame.draw.line(surf, (200,200,200), (ix-8, iy+6), (ix+8, iy-6), 3)
                pygame.draw.line(surf, (150,150,150), (ix+5, iy-8), (ix+10, iy-3), 2)

        elif self.type == "pot":
            # pot circle
            pygame.draw.circle(surf, (80,80,80), (ix, iy), 11)
            pygame.draw.circle(surf, (110,110,110), (ix, iy), 11, 1)
            if self.pot_contents:
                n = min(len(self.pot_contents), 3)
                for i, item in enumerate(self.pot_contents[:3]):
                    bid = item["id"].replace("_c","")
                    col = INGS.get(bid,{}).get("color",(150,150,150))
                    ox = ix + (i - (n-1)/2) * 7
                    pygame.draw.circle(surf, col, (int(ox), iy), 5)
            # cook bar
            if self.cooking or self.cooked:
                col_fill = C["green"] if self.cooked else C["red"]
                draw_bar(surf, self.x+2, self.y-8, self.w-4, 4,
                         self.prog, (40,40,40), col_fill, 2)
            # cooked indicator
            if self.cooked:
                pygame.draw.circle(surf, C["green"], (ix+10, iy-8), 5)
            # flame
            if self.on and not self.cooked:
                t = time.time()
                for fx, off in [(self.x+8, math.sin(t*8)*1.5),
                                (self.x+self.w-16, math.sin(t*8+1)*1.5)]:
                    fy = self.y + self.h + 5 + off
                    pygame.draw.polygon(surf, (255,100,0), [
                        (fx, fy+8), (fx-4, fy+2), (fx, fy-4), (fx+4, fy+2)])
                    pygame.draw.polygon(surf, (255,200,0), [
                        (fx, fy+6), (fx-2, fy+2), (fx, fy-1), (fx+2, fy+2)])

        elif self.type == "plate":
            pygame.draw.circle(surf, (200,195,180), (ix, iy), 11)
            pygame.draw.circle(surf, (180,175,160), (ix, iy), 11, 1)
            if self.contents:
                pygame.draw.circle(surf, C["green"], (ix+8, iy-8), 5)
                lbl3 = FONT_SM.render("Plated", True, C["lime"])
                surf.blit(lbl3, (ix - lbl3.get_width()//2, iy + 4))

        elif self.type == "submit":
            # box icon
            rr(surf, C["submit_top"], (ix-9, iy-8, 18, 14), 3)
            pygame.draw.line(surf, (255,255,255,120), (ix-9,iy-2), (ix+9,iy-2), 1)

        elif self.type == "trash":
            # bin icon
            rr(surf, C["trash_top"], (ix-8, iy-7, 16, 14), 2)
            pygame.draw.line(surf, (200,100,100), (ix-5, iy-4), (ix-5, iy+4), 2)
            pygame.draw.line(surf, (200,100,100), (ix,   iy-4), (ix,   iy+4), 2)
            pygame.draw.line(surf, (200,100,100), (ix+5, iy-4), (ix+5, iy+4), 2)


# ── 플레이어 ─────────────────────────────────────────
class Player:
    W, H = 30, 38

    def __init__(self, x, y):
        self.x, self.y = float(x), float(y)
        self.vx, self.vy = 0.0, 0.0
        self.facing = 1
        self.holding = None  # dict or None
        self.walk_t = 0.0

    def rect(self):
        return pygame.Rect(int(self.x), int(self.y), self.W, self.H)

    def center(self):
        return (int(self.x + self.W // 2), int(self.y + self.H // 2))

    def update(self, keys_held, dt, gw, gy):
        WALK = 120  # px/sec (reduced from 220)
        GRAV = 900

        if keys_held["left"]:
            self.vx = -WALK
            self.facing = -1
        elif keys_held["right"]:
            self.vx = WALK
            self.facing = 1
        else:
            self.vx *= (0.55 ** dt)
            if abs(self.vx) < 2: self.vx = 0

        self.vy += GRAV * dt
        self.x += self.vx * dt
        self.y += self.vy * dt

        # ground
        if self.y + self.H >= gy:
            self.y = gy - self.H
            self.vy = 0

        # walls
        self.x = max(4, min(gw - self.W - 4, self.x))

        if abs(self.vx) > 10:
            self.walk_t += dt * 8

    def draw(self, surf):
        px, py = int(self.x), int(self.y)
        f = self.facing
        walk = abs(self.vx) > 10
        bob = int(math.sin(self.walk_t) * 2) if walk else 0

        # shadow
        pygame.draw.ellipse(surf, (0,0,0,60),
                            (px + 2, py + self.H - 5, self.W - 4, 7))

        # legs
        leg_swing = int(math.sin(self.walk_t) * 5) if walk else 0
        rr(surf, C["char_dark"],  (px+5,  py+24+leg_swing,  10, 14), 3)
        rr(surf, C["char_hat"],   (px+17, py+24-leg_swing,  10, 14), 3)

        # body
        rr(surf, C["char_body"], (px+2, py+14+bob, 28, 18), 5)

        # apron
        rr(surf, C["apron"], (px+7, py+16+bob, 18, 14), 3)
        rr(surf, (200,195,180), (px+9, py+18+bob, 14, 10), 2)

        # arms
        arm_swing = int(math.sin(self.walk_t) * 4) if walk else 0
        rr(surf, C["char_body"], (px+(26 if f>0 else 0), py+16+bob-arm_swing, 7, 11), 3)
        rr(surf, C["char_body"], (px+(1  if f>0 else 25), py+16+bob+arm_swing, 7, 11), 3)

        # head
        pygame.draw.circle(surf, C["char_face"], (px+16, py+10+bob), 11)

        # chef hat
        rr(surf, C["white"],    (px+7,  py+1+bob,  18, 8), 2)
        rr(surf, (230,230,230), (px+4,  py+7+bob,  24, 4), 1)

        # eyes
        ex = px + 16 + f * 4
        pygame.draw.circle(surf, C["char_hat"], (ex, py+10+bob), 2)
        pygame.draw.circle(surf, (255,255,255),  (ex+1, py+9+bob), 1)

        # smile
        pygame.draw.arc(surf, (80,60,30),
                        (px+12+f, py+12+bob, 8, 5), math.pi+0.2, 2*math.pi-0.2, 2)

        # held item
        if self.holding:
            hx = px + 16 + f * 22
            hy = py + 4 + bob
            bid = self.holding["id"].replace("_c","")
            ing = INGS.get(bid, {})
            color = C["green"] if self.holding.get("cooked") \
                   else C["lime"] if self.holding.get("chopped") \
                   else ing.get("color", (150,150,150))
            pygame.draw.circle(surf, color, (hx, hy), 12)
            pygame.draw.circle(surf, (255,255,255,60), (hx, hy), 12, 1)

            if self.holding.get("cooked"):
                lbl = FONT_SM.render("Done", True, (255,255,255))
            elif self.holding.get("chopped"):
                lbl = FONT_SM.render("Cut", True, (0,0,0))
            else:
                lbl = FONT_SM.render(ing.get("label","")[:1], True, (0,0,0))
            surf.blit(lbl, (hx - lbl.get_width()//2, hy - lbl.get_height()//2))


# ── 주문 카드 ─────────────────────────────────────────
class Order:
    ORDER_TIME = 38.0
    _id_ctr = 0

    def __init__(self, recipe):
        Order._id_ctr += 1
        self.id = Order._id_ctr
        self.recipe = recipe
        self.t = self.ORDER_TIME
        self.status = "active"   # active / done / failed

    def update(self, dt):
        if self.status != "active": return
        self.t -= dt
        if self.t <= 0:
            self.t = 0
            self.status = "failed"
            return "failed"
        return None

    def draw(self, surf, x, y, w=70):
        h = 52
        urgent = self.t < 12 and self.status == "active"
        failed = self.status == "failed"
        border = C["red"] if failed else C["order_urg"] if urgent else C["order_brd"]
        alpha = 100 if failed else 255

        bg = pygame.Surface((w, h), pygame.SRCALPHA)
        bg.fill((*C["order_bg"], alpha))
        surf.blit(bg, (x, y))
        pygame.draw.rect(surf, border, (x, y, w, h), 1, border_radius=7)

        # recipe name
        nm = FONT_SM.render(self.recipe["name"], True, C["blue"] if not failed else (150,150,150))
        surf.blit(nm, (x + w//2 - nm.get_width()//2, y + 6))

        # ingredients list small
        needs_str = " ".join(
            n.replace("_c","↗").replace("tomato","Tom").replace("carrot","Car")
             .replace("onion","Oni").replace("mushroom","Msh").replace("rice","Ric")
            for n in self.recipe["needs"]
        )
        ni = FONT_SM.render(needs_str, True, (160,160,160))
        surf.blit(ni, (x + w//2 - ni.get_width()//2, y + 20))

        # timer bar
        pct = self.t / self.ORDER_TIME if self.status == "active" else 0
        col_fill = C["green"] if pct > 0.4 else C["orange"] if pct > 0.15 else C["red"]
        draw_bar(surf, x+4, y+h-10, w-8, 5, pct, (30,40,50), col_fill, 2)


# ── 메인 게임 ─────────────────────────────────────────
class Game:
    GAME_TIME = 120

    def __init__(self):
        self.state = "title"   # title / play / over
        self.buttons = {}
        self.mouse_pos = (0, 0)
        self.mouse_pressed = False
        self.reset()

    def reset(self):
        self.score = 0
        self.timer = self.GAME_TIME
        self.orders = []
        self.popups = []
        self.next_order_t = 0.0
        self.elapsed = 0.0
        self._build_level()
        self.player = Player(160, 100)
        self._setup_buttons()

    def _build_level(self):
        gw, gh = screen.get_size()
        self.gw, self.gh = gw, gh
        gy = gh - 60
        self.gy = gy
        T, SW = 52, 78

        def st(tp, nx, **kw):
            return Station(tp, int(T * nx), int(gy - T * 1.3), **kw)

        self.stations = [
            st("ing", 0.05, ing_id="tomato",   label="Tomato"),
            st("ing", 1.75, ing_id="carrot",   label="Carrot"),
            st("ing", 3.45, ing_id="onion",    label="Onion"),
            st("ing", 5.15, ing_id="mushroom", label="Mushroom"),
            st("ing", 6.85, ing_id="rice",     label="Rice"),
            Station("trash",  int(T*8.55),        int(gy - T*1.3), label="Trash"),  # keep same spacing with ingredients
            Station("chop",   int(gw - T*6.5),    int(gy - T*1.3), label="Chop"),  # keep spacing from stove side
            Station("pot",    int(gw - T*5.0),    int(gy - T*1.3), label="Pot ①"),
            Station("pot",    int(gw - T*3.2),    int(gy - T*1.3), label="Pot ②"),
            Station("plate",  int(gw - T*1.4),    int(gy - T*1.3), label="Plate"),
            Station("submit", int(gw - T*1.4 + SW + 6), int(gy - T*1.3), label="Submit"),
        ]
        
    def _setup_buttons(self):
        gw, gh = screen.get_size()
        btn_h = 50
        btn_w = 80
        margin = 15
        
        # Control buttons at bottom
        bottom_y = gh - btn_h - margin
        
        self.buttons = {
            "left": Button(margin, bottom_y, btn_w, btn_h, "← Left", (45,85,45)),
            "right": Button(margin + btn_w + 10, bottom_y, btn_w, btn_h, "Right →", (45,85,45)),
            "action": Button(gw - btn_w - margin, bottom_y, btn_w, btn_h, "Action", (85,45,45)),
            "start": Button(gw//2 - btn_w//2, gh//2 + 60, btn_w, btn_h, "Start", (45,45,85)),
        }

    def near_station(self):
        px, py = self.player.center()
        best, bd = None, 999
        for s in self.stations:
            d = s.dist(px, py)
            if d < 90 and d < bd:
                best, bd = s, d
        return best

    def do_action(self):
        st = self.near_station()
        if not st: return
        h = self.player.holding

        # ── ingredient dispenser
        if st.type == "ing":
            if not h:
                ing = INGS[st.ing_id]
                self.player.holding = {"id": st.ing_id, "label": ing["label"], "chopped": False}
                self._pop(self.player.x+15, self.player.y-10, "Picked " + ing["label"], C["lime"])
            return

        # ── chop board
        if st.type == "chop":
            if h:
                base = h["id"].replace("_c","")
                if h.get("chopped"):
                    self._pop(self.player.x+15, self.player.y-10, "Already chopped", (150,150,150))
                    return
                if not INGS.get(base,{}).get("can_chop"):
                    self._pop(self.player.x+15, self.player.y-10, "Cannot chop", (150,150,150))
                    return
                if st.contents and st.contents["id"].replace("_c","") != base:
                    self._pop(st.x+st.w//2, st.y-10, "Clear first!", C["red"])
                    return
                if not st.contents:
                    st.contents = dict(h)
                    self.player.holding = None
                    st.prog = 0
                if not st.chopping:
                    st.chopping = True
                    self._pop(st.x+st.w//2, st.y-10, "Chopping...", C["orange"])
            else:
                if st.contents and st.contents.get("chopped"):
                    self.player.holding = dict(st.contents)
                    st.contents = None; st.prog = 0; st.chopping = False
                    self._pop(self.player.x+15, self.player.y-10, "✓ Picked up", C["lime"])
                elif st.contents and not st.chopping:
                    st.chopping = True
                    self._pop(st.x+st.w//2, st.y-10, "Chopping...", C["orange"])
            return

        # ── pot
        if st.type == "pot":
            if h and not st.cooked:
                st.pot_contents.append(dict(h))
                self.player.holding = None
                self._pop(st.x+st.w//2, st.y-10, "Added ✓", C["gold"])
            elif not h and st.pot_contents and not st.cooking and not st.cooked:
                st.on = True; st.cooking = True
                self._pop(st.x+st.w//2, st.y-10, "Fire on!", C["orange"])
            elif not h and st.cooked:
                self.player.holding = {
                    "id": "cooked", "label": "Cooked Dish",
                    "contents": list(st.pot_contents), "cooked": True
                }
                st.pot_contents=[]; st.cooked=False; st.cooking=False; st.prog=0; st.on=False
                self._pop(self.player.x+15, self.player.y-10, "Picked cooked!", C["green"])
            elif not h and st.cooking:
                self._pop(st.x+st.w//2, st.y-10, "Cooking...", (150,150,150))
            return

        # ── plate
        if st.type == "plate":
            if h and h.get("cooked"):
                st.contents = dict(h)
                self.player.holding = None
                self._pop(st.x+st.w//2, st.y-10, "Plated", C["lime"])
            elif not h and st.contents:
                self.player.holding = dict(st.contents)
                st.contents = None
                self._pop(self.player.x+15, self.player.y-10, "Picked plate", C["lime"])
            elif h and not h.get("cooked"):
                self._pop(self.player.x+15, self.player.y-10, "Cooked food only!", C["red"])
            return

        # ── submit
        if st.type == "submit":
            if not h: return
            if not h.get("cooked"):
                self._pop(st.x+st.w//2, st.y-10, "No cooked food", C["red"])
                return
            h_ids = sorted(
                (c["id"]+"_c" if c.get("chopped") else c["id"])
                for c in h["contents"]
            )
            matched = None
            for o in self.orders:
                if o.status != "active": continue
                if sorted(o.recipe["needs"]) == h_ids:
                    matched = o; break
            if matched:
                bonus = int(matched.t / matched.ORDER_TIME * 40)
                pts = matched.recipe["pts"] + bonus
                self.score += pts
                matched.status = "done"
                self.player.holding = None
                self._pop(st.x+st.w//2, st.y-25, f"+{pts} pts!", C["green"])
            else:
                self._pop(st.x+st.w//2, st.y-10, "No matching order!", C["red"])
                self.player.holding = None
            return

        # ── trash
        if st.type == "trash":
            if h:
                self.player.holding = None
                self._pop(st.x+st.w//2, st.y-10, "Trashed", C["pink"])
            else:
                chop = next((s for s in self.stations if s.type=="chop"), None)
                if chop and chop.contents:
                    chop.contents=None; chop.prog=0; chop.chopping=False
                    self._pop(st.x+st.w//2, st.y-10, "Cleared chop board", C["pink"])
            return

    def _pop(self, x, y, msg, color):
        self.popups.append(Popup(x, y, msg, color))

    def _spawn_order(self):
        active = sum(1 for o in self.orders if o.status=="active")
        if active >= 3: return
        recipe = random.choice(RECIPES)
        self.orders.append(Order(recipe))

    def _hint_text(self, st):
        if not st: return ""
        h = self.player.holding
        if st.type == "ing" and not h:
            return f"Action: Pick {st.label}"
        if st.type == "chop":
            if h and not h.get("chopped") and INGS.get(h["id"].replace("_c",""),{}).get("can_chop"):
                return "Action: Chop"
            if not h and st.contents and st.contents.get("chopped"):
                return "Action: Pick chopped item"
            if not h and st.contents and not st.chopping:
                return "Action: Start chopping"
        if st.type == "pot":
            if h and not st.cooked: return "Action: Add to pot"
            if not h and st.pot_contents and not st.cooking and not st.cooked: return "Action: Turn on fire 🔥"
            if not h and st.cooked: return "Action: Pick cooked dish"
        if st.type == "plate":
            if h and h.get("cooked"): return "Action: Put on plate"
            if not h and st.contents: return "Action: Pick up plate"
        if st.type == "submit" and h: return "Action: Submit!"
        if st.type == "trash": return "Action: Trash / Clear chop board"
        return ""

    def update(self, dt, mouse_pos, mouse_pressed):
        gw, gh = screen.get_size()
        if gw != self.gw or gh != self.gh:
            self.gw, self.gh = gw, gh
            self._build_level()
            self._setup_buttons()

        self.mouse_pos = mouse_pos
        self.mouse_pressed = mouse_pressed
        
        # Handle button inputs
        keys_held = {"left": False, "right": False}
        action_pressed = False
        
        if self.state == "play":
            self.buttons["left"].handle_mouse(mouse_pos, mouse_pressed)
            self.buttons["right"].handle_mouse(mouse_pos, mouse_pressed)
            keys_held["left"] = self.buttons["left"].pressed
            keys_held["right"] = self.buttons["right"].pressed
            action_pressed = self.buttons["action"].handle_mouse(mouse_pos, mouse_pressed)
        elif self.state in ("title", "over"):
            if self.buttons["start"].handle_mouse(mouse_pos, mouse_pressed):
                self.reset()
                self.state = "play"
                self._spawn_order()
                self._spawn_order()
            return

        # player
        self.player.update(keys_held, dt, gw, self.gy)
        if action_pressed:
            self.do_action()

        # stations
        for s in self.stations:
            result = s.update(dt)
            if result == "chop_done":
                self._pop(s.x+s.w//2, s.y-10, "✓ Chopping done!", C["lime"])
            if result == "cook_done":
                self._pop(s.x+s.w//2, s.y-10, "🍳 Cooked!", C["green"])

        # orders
        for o in self.orders:
            result = o.update(dt)
            if result == "failed":
                self.score = max(0, self.score - 30)
                self._pop(gw//2, gh//2-60, "Order failed! -30", C["red"])

        # spawn orders
        self.elapsed += dt
        if self.elapsed >= self.next_order_t:
            self._spawn_order()
            self.next_order_t = self.elapsed + 14.0

        # game timer
        self.timer -= dt
        if self.timer <= 0:
            self.timer = 0
            self.state = "over"

        # popups
        for p in self.popups: p.update()
        self.popups = [p for p in self.popups if not p.dead]

    def draw(self):
        gw, gh = screen.get_size()
        gy = self.gy

        # ── background
        screen.fill(C["bg"])
        for y in range(0, gh, 32):
            pygame.draw.line(screen, (*C["grid"], 18), (0, y), (gw, y), 1)
        for x in range(0, gw, 36):
            c = C["tile_a"] if (x//36)%2==0 else C["tile_b"]
            screen.fill(c, (x, 0, 35, gy))

        # ── ground
        screen.fill(C["ground"], (0, gy, gw, gh - gy))
        for x in range(0, gw, 30):
            c = C["tile_a"] if (x//30)%2==0 else C["tile_b"]
            screen.fill(c, (x, gy, 29, 8))
        pygame.draw.line(screen, (*C["purple"], 80), (0, gy), (gw, gy), 2)
        screen.fill((10,10,30), (0, gy+8, gw, gh-gy-8))

        # ── stations
        for s in self.stations:
            s.draw(screen, gy)

        # ── near highlight
        ns = self.near_station()
        if ns:
            pygame.draw.rect(screen, (*C["yellow"], 200),
                             (ns.x-2, ns.y-2, ns.w+4, ns.h+4), 2, border_radius=6)

        # ── player
        self.player.draw(screen)

        # ── popups
        for p in self.popups:
            p.draw(screen)

        # ── buttons
        if self.state == "play":
            for btn_name in ["left", "right", "action"]:
                self.buttons[btn_name].draw(screen)

        # ── HUD
        self._draw_hud(gw, gh)

    def _draw_hud(self, gw, gh):
        HH = 44
        rr(screen, C["hud_bg"], (0, 0, gw, HH), 0)
        pygame.draw.line(screen, C["hud_border"], (0, HH), (gw, HH), 1)

        # score
        sc = FONT_HUD.render(f"Score  {self.score}", True, C["gold"])
        screen.blit(sc, (12, HH//2 - sc.get_height()//2))

        # timer
        m = int(self.timer) // 60
        s = int(self.timer) % 60
        tc = C["red"] if self.timer < 20 else C["white"]
        tm = FONT_HUD.render(f"{m}:{s:02d}", True, tc)
        screen.blit(tm, (gw//2 - tm.get_width()//2, HH//2 - tm.get_height()//2))

        # orders
        ox = gw - 10
        for o in reversed([o for o in self.orders if o.status != "done"]):
            ox -= 76
            o.draw(screen, ox, 2, w=74)

        # hint bar
        ns = self.near_station()
        hint = self._hint_text(ns)
        if hint:
            hs = FONT_SM.render(hint, True, (200,200,200))
            hw, hh2 = hs.get_width()+16, hs.get_height()+8
            bg = pygame.Surface((hw, hh2), pygame.SRCALPHA)
            bg.fill((0,0,0,160))
            screen.blit(bg, (gw//2-hw//2, gh-30))
            screen.blit(hs, (gw//2 - hs.get_width()//2, gh-26))

    def draw_title(self):
        gw, gh = screen.get_size()
        screen.fill(C["bg"])
        t1 = FONT_XL.render("🍳 Cooking Game", True, C["gold"])
        screen.blit(t1, (gw//2 - t1.get_width()//2, gh//2 - 100))
        lines = [
            "🖱️ Control with screen buttons",
            "← → : Move | Action : Pick·Drop·Cook·Submit",
            "",
            "Pick Ingredients  →  Chop Board  →  Pot(Cook)  →  Plate  →  Submit",
            "",
            "Click Start button below",
        ]
        for i, line in enumerate(lines):
            s = FONT_MD.render(line, True, (180,180,210))
            screen.blit(s, (gw//2 - s.get_width()//2, gh//2 - 30 + i*26))
            
        # Draw start button
        self.buttons["start"].draw(screen)

    def draw_over(self):
        gw, gh = screen.get_size()
        self.draw()  # show final state behind overlay
        ov = pygame.Surface((gw, gh), pygame.SRCALPHA)
        ov.fill((5, 5, 20, 200))
        screen.blit(ov, (0,0))
        t1 = FONT_XL.render("Game Over!", True, C["gold"])
        screen.blit(t1, (gw//2-t1.get_width()//2, gh//2-80))
        t2 = FONT_XL.render(f"{self.score} Points", True, C["white"])
        screen.blit(t2, (gw//2-t2.get_width()//2, gh//2-20))
        t3 = FONT_MD.render("Click Start button to restart", True, (160,160,200))
        screen.blit(t3, (gw//2-t3.get_width()//2, gh//2+30))
        
        # Draw restart button
        self.buttons["start"].draw(screen)


# ── 메인 루프 ─────────────────────────────────────────
def main():
    game = Game()
    mouse_pressed = False

    while True:
        dt = clock.tick(FPS) / 1000.0
        dt = min(dt, 0.05)  # cap

        # Handle events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.VIDEORESIZE:
                pass  # handled via get_size()
            if event.type == pygame.MOUSEBUTTONDOWN:
                mouse_pressed = True
            if event.type == pygame.MOUSEBUTTONUP:
                mouse_pressed = False
            # Keep keyboard support for ESC
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    pygame.quit(); sys.exit()

        mouse_pos = pygame.mouse.get_pos()
        game.update(dt, mouse_pos, mouse_pressed)

        if game.state == "title":
            game.draw_title()
        elif game.state == "over":
            game.draw_over()
        else:
            game.draw()

        pygame.display.flip()


if __name__ == "__main__":
    main()
