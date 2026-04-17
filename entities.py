import pygame
import math
import time
import random
import os

from engine import F, get_img
from constants import (
    C,
    INGS,
    RECIPES,
    BURN_TIME,
    ORDER_TIME,
    CHOP_ACTIONS,
    STIR_ACTIONS,
)
from utils import rr, bar


COMPLETED_FOOD_DIR = "assets/ccompleted_foods"
_COMPLETED_IMG_CACHE = {}


def _load_completed_food_img(filename, w, h):
    key = (filename, w, h)
    if key in _COMPLETED_IMG_CACHE:
        return _COMPLETED_IMG_CACHE[key]

    path = os.path.join(COMPLETED_FOOD_DIR, filename)
    if not os.path.exists(path):
        _COMPLETED_IMG_CACHE[key] = None
        return None

    try:
        if not hasattr(pygame, "image"):
            return None
        img = pygame.image.load(path).convert_alpha()
        img = pygame.transform.smoothscale(img, (w, h))
        _COMPLETED_IMG_CACHE[key] = img
        return img
    except Exception:
        _COMPLETED_IMG_CACHE[key] = None
        return None


def _dish_name_from_contents(contents):
    h_ids = sorted(c.get("id") for c in contents if isinstance(c, dict) and c.get("id"))
    if len(h_ids) != len(contents):
        return None
    for rec in RECIPES:
        if not rec.get("cook", True):
            continue
        if sorted(rec.get("needs", [])) == h_ids:
            return rec.get("name")
    return None


def _get_completed_food_img(holding, w, h):
    if holding.get("burned"):
        return _load_completed_food_img("burned_dish.png", w, h)
    if not holding.get("cooked"):
        return None

    dish_name = holding.get("dish_name") or _dish_name_from_contents(holding.get("contents", []))
    if not dish_name:
        return None
    return _load_completed_food_img(f"{dish_name}.png", w, h)


class Station:
    SW = 110
    SH = 28

    def __init__(self, kind, sx, sy):
        self.kind = kind
        self.x = sx; self.y = sy
        self.w = self.SW; self.h = self.SH

        self.chop_item   = None
        self.chop_prog   = 0.0
        self.chopping    = False
        self.chop_hits   = 0

        self.pot_items   = []
        self.pot_prog    = 0.0
        self.pot_cooking = False
        self.pot_stirs   = 0
        self.pot_cooked  = False
        self.pot_burn    = 0.0
        self.pot_on      = False
        self.pot_burned  = False

        self.plate_item  = None

    @property
    def rect(self): return pygame.Rect(self.x, self.y, self.w, self.h)
    def cx(self): return self.x + self.w // 2
    def cy(self): return self.y + self.h // 2

    def dist(self, px, py):
        return math.hypot(px - self.cx(), py - self.cy())

    def update(self, dt):
        events = []
        if self.kind == "chop" and self.chopping and self.chop_item \
                and not self.chop_item.get("chopped"):
            self.chop_prog = min(1.0, self.chop_hits / float(CHOP_ACTIONS))
            if self.chop_hits >= CHOP_ACTIONS:
                self.chop_item["chopped"] = True
                self.chop_item["id"] += "_c"
                self.chop_item["label"] = "Chopped " + self.chop_item["label"]
                self.chopping = False
                events.append("chop_done")

        if self.kind == "pot":
            if self.pot_cooking and not self.pot_cooked:
                self.pot_prog = min(1.0, self.pot_stirs / float(STIR_ACTIONS))
                if self.pot_stirs >= STIR_ACTIONS:
                    self.pot_cooked  = True
                    self.pot_cooking = False
                    self.pot_burn    = 0.0
                    events.append("cook_done")
            elif self.pot_cooked and self.pot_items and not self.pot_burned:
                self.pot_burn += dt
                if self.pot_burn >= BURN_TIME:
                    self.pot_burned = True
                    events.append("burned")

        return events

    def draw(self, surf, gy):
        if self.kind == "ing":
            base, top = C["ing_base"], C["ing_top"]
        elif self.kind == "chop":
            base, top = C["chop_base"], C["chop_top"]
        elif self.kind == "pot":
            base, top = C["pot_base"], C["pot_on"] if self.pot_on else C["pot_off"]
        elif self.kind == "trash":
            base, top = C["trash_base"], C["trash_top"]
        elif self.kind == "submit":
            base, top = C["submit_base"], C["submit_top"]
        else:  # plate
            base, top = C["plate_base"], C["plate_top"]

        rr(surf, base, (self.x + 8, self.y + self.h, self.w - 16, gy - self.y - self.h), 2)
        rr(surf, top, (self.x, self.y, self.w, self.h), 6)
        surf.fill((255, 255, 255, 15), (self.x + 5, self.y + 2, self.w - 10, 3))

        s = F[12].render(self._station_label(), True, (220, 220, 220))
        surf.blit(s, (self.cx() - s.get_width() // 2, self.cy() - s.get_height() // 2))

        ix, iy = self.cx(), self.y - 18
        self._draw_icon(surf, ix, iy)

    def _station_label(self):
        if self.kind == "ing":    return "Pantry"
        if self.kind == "chop":   return "Chop"
        if self.kind == "pot":    return "Stove"
        if self.kind == "trash":  return "Trash"
        if self.kind == "plate":  return "Plate"
        if self.kind == "submit": return "Submit"
        return ""

    def _draw_icon(self, surf, ix, iy):
        if self.kind == "ing":
            rr(surf, C["ing_top"], (ix - 14, iy - 10, 28, 20), 4)
            t = F[12].render("INGs", True, (255, 255, 255))
            surf.blit(t, (ix - t.get_width() // 2, iy - t.get_height() // 2))

        elif self.kind == "chop":
            if self.chop_item:
                item_id = self.chop_item["id"]
                img = get_img(item_id, 18, 18)
                if img:
                    surf.blit(img, (ix - 9, iy - 9))
                    if not self.chop_item.get("chopped"):
                        bar(surf, self.x + 2, self.y - 8, self.w - 4, 5,
                            self.chop_prog, (50, 50, 50), C["orange"], 2)
                else:
                    bid = item_id.replace("_c", "")
                    col = INGS.get(bid, {}).get("color", (150, 150, 150))
                    pygame.draw.circle(surf, col, (ix - 8, iy), 9)
                    if self.chop_item.get("chopped"):
                        pygame.draw.line(surf, C["lime"], (ix - 4, iy + 3), (ix + 8, iy - 5), 2)
                    else:
                        bar(surf, self.x + 2, self.y - 8, self.w - 4, 5,
                            self.chop_prog, (50, 50, 50), C["orange"], 2)
            else:
                pygame.draw.line(surf, (180, 180, 180), (ix - 10, iy + 8), (ix + 10, iy - 8), 3)
                pygame.draw.line(surf, (130, 130, 130), (ix + 7, iy - 10), (ix + 12, iy - 5), 2)

        elif self.kind == "pot":
            pygame.draw.circle(surf, (80, 80, 80), (ix, iy), 13)
            pygame.draw.circle(surf, (110, 110, 110), (ix, iy), 13, 1)

            if self.pot_items:
                n = min(len(self.pot_items), 3)
                for i, item in enumerate(self.pot_items[:3]):
                    ox = ix + (i - (n - 1) / 2) * 8
                    img = get_img(item["id"], 10, 10)
                    if img:
                        surf.blit(img, (int(ox) - 5, iy - 5))
                    else:
                        bid = item["id"].replace("_c", "")
                        col = INGS.get(bid, {}).get("color", (150, 150, 150))
                        pygame.draw.circle(surf, col, (int(ox), iy), 5)

            if self.pot_cooking or self.pot_cooked:
                col_f = C["green"] if self.pot_cooked else C["orange"]
                bar(surf, self.x + 2, self.y - 9, self.w - 4, 5, self.pot_prog, (40, 40, 40), col_f, 2)

            if self.pot_cooked and self.pot_items:
                burn_pct = min(1.0, self.pot_burn / BURN_TIME)
                col_b = C["burn"] if burn_pct < 0.7 else C["red"]
                bar(surf, self.x + 2, self.y - 16, self.w - 4, 4, burn_pct, (30, 20, 20), col_b, 2)

            if self.pot_cooked and not (self.pot_burn >= BURN_TIME):
                pygame.draw.circle(surf, C["green"], (ix + 12, iy - 10), 5)

            if self.pot_on and not self.pot_cooked:
                t = time.time()
                for fx, phase in [(self.x + 10, 0), (self.x + self.w - 18, 1)]:
                    fy = self.y + self.h + 4 + math.sin(t * 9 + phase) * 1.5
                    pygame.draw.polygon(surf, (255, 90, 0),
                        [(fx, fy + 9), (fx - 5, fy + 2), (fx, fy - 5), (fx + 5, fy + 2)])
                    pygame.draw.polygon(surf, (255, 210, 0),
                        [(fx, fy + 7), (fx - 3, fy + 2), (fx, fy - 2), (fx + 3, fy + 2)])

        elif self.kind in ("plate", "submit"):
            # plate circle
            pygame.draw.circle(surf, (200, 195, 180), (ix, iy), 11)
            pygame.draw.circle(surf, (160, 155, 140), (ix, iy), 11, 1)
            if self.kind == "plate":
                if self.plate_item:
                    pygame.draw.circle(surf, C["green"], (ix + 8, iy - 9), 5)
                    s = F[12].render("Plated", True, C["lime"])
                    surf.blit(s, (ix - s.get_width() // 2, iy + 6))
            else:  # submit
                rr(surf, C["submit_top"], (ix - 10, iy - 9, 22, 16), 3)
                pygame.draw.line(surf, (255, 255, 255, 100), (ix - 10, iy - 3), (ix + 12, iy - 3), 1)

        if self.kind == "trash":
            rr(surf, C["trash_top"], (ix - 10, iy - 8, 20, 17), 3)
            rr(surf, (160, 50, 90), (ix - 12, iy - 13, 24, 5), 2)
            for lx in (ix - 5, ix, ix + 5):
                pygame.draw.line(surf, (200, 100, 130), (lx, iy - 6), (lx, iy + 6), 1)


class Player:
    PW, PH = 30, 40

    def __init__(self, x, y):
        self.x = float(x); self.y = float(y)
        self.vx = 0.0; self.vy = 0.0
        self.facing = 1
        self.holding = None
        self.walk_t = 0.0

    def center(self):
        return (int(self.x + self.PW // 2), int(self.y + self.PH // 2))

    def update(self, move_dir, dt, gw, gy):
        SPEED = 160
        GRAV  = 950
        if move_dir != 0:
            self.vx = move_dir * SPEED
            self.facing = move_dir
        else:
            self.vx = 0

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
        px, py = int(self.x), int(self.y)
        f = self.facing
        walk = abs(self.vx) > 10
        bob  = int(math.sin(self.walk_t) * 2) if walk else 0
        ls   = int(math.sin(self.walk_t) * 5) if walk else 0
        as_  = int(math.sin(self.walk_t) * 4) if walk else 0

        pygame.draw.ellipse(surf, (0, 0, 0, 50), (px + 2, py + self.PH - 6, self.PW - 4, 7))
        rr(surf, C["char_dark"], (px + 5,  py + 26 + ls,  10, 14), 3)
        rr(surf, C["char_hat"],  (px + 17, py + 26 - ls,  10, 14), 3)
        rr(surf, C["char_body"], (px + 2,  py + 14 + bob, 28, 18), 5)
        rr(surf, C["apron"],     (px + 7,  py + 16 + bob, 18, 14), 3)
        rr(surf, (200, 195, 180),(px + 9,  py + 18 + bob, 14, 10), 2)
        rr(surf, C["char_body"], (px + (26 if f > 0 else 0),  py + 16 + bob - as_, 7, 11), 3)
        rr(surf, C["char_body"], (px + (1  if f > 0 else 25), py + 16 + bob + as_, 7, 11), 3)
        pygame.draw.circle(surf, C["char_face"], (px + 16, py + 10 + bob), 11)
        rr(surf, C["white"],    (px + 7,  py + 1 + bob, 18, 8), 2)
        rr(surf, (230, 230, 230),(px + 4, py + 7 + bob, 24, 4), 1)

        ex = px + 16 + f * 4
        pygame.draw.circle(surf, C["char_hat"],    (ex,     py + 10 + bob), 2)
        pygame.draw.circle(surf, (255, 255, 255),  (ex + 1, py + 9  + bob), 1)
        pygame.draw.arc(surf, (80, 60, 30),
                        (px + 12 + f, py + 12 + bob, 8, 5),
                        math.pi + 0.2, 2 * math.pi - 0.2, 2)

        if self.holding:
            hx = px + 16 + f * 24
            hy = py + 4 + bob
            item_id = self.holding.get("id", "")
            is_completed = bool(self.holding.get("cooked"))
            item_size = 42 if is_completed else 26
            half = item_size // 2

            completed_img = _get_completed_food_img(self.holding, item_size, item_size)
            dish_name = self.holding.get("dish_name") or _dish_name_from_contents(self.holding.get("contents", []))
            is_known_cooked = bool(dish_name)

            img = completed_img or get_img(item_id, item_size, item_size)
            if img:
                surf.blit(img, (hx - half, hy - half))
                if self.holding.get("burned") and not completed_img:
                    lbl = F[12].render("BURN", True, (255, 200, 100))
                    surf.blit(lbl, (hx - lbl.get_width() // 2, hy - lbl.get_height() // 2))
                elif self.holding.get("cooked") and not completed_img:
                    cooked_txt = "Done" if is_known_cooked else "Unknown"
                    lbl = F[12].render(cooked_txt, True, (255, 255, 255))
                    surf.blit(lbl, (hx - lbl.get_width() // 2, hy - lbl.get_height() // 2))
            else:
                bid = item_id.replace("_c", "")
                ing = INGS.get(bid, {})
                col = C["burn"]  if self.holding.get("burned") \
                     else C["green"] if self.holding.get("cooked") \
                     else C["lime"]  if self.holding.get("chopped") \
                     else ing.get("color", (150, 150, 150))
                rad = 17 if is_completed else 13
                pygame.draw.circle(surf, col, (hx, hy), rad)
                pygame.draw.circle(surf, (255, 255, 255, 50), (hx, hy), rad, 1)
                if self.holding.get("burned"):
                    lbl = F[12].render("BURN", True, (255, 200, 100))
                elif self.holding.get("cooked"):
                    cooked_txt = "Done" if is_known_cooked else "Unknown"
                    lbl = F[12].render(cooked_txt, True, (255, 255, 255))
                elif self.holding.get("chopped"):
                    lbl = F[12].render("Cut", True, (0, 0, 0))
                else:
                    lbl = F[12].render(ing.get("label", "")[:3], True, (0, 0, 0))
                surf.blit(lbl, (hx - lbl.get_width() // 2, hy - lbl.get_height() // 2))


class Order:
    _ctr = 0

    def __init__(self, recipe):
        Order._ctr += 1
        self.id = Order._ctr
        self.recipe = recipe
        self.t = ORDER_TIME
        self.status = "active"

    def update(self, dt):
        if self.status != "active": return None
        self.t = max(0.0, self.t - dt)
        if self.t <= 0:
            self.status = "failed"
            return "failed"
        return None

    def draw(self, surf, x, y, w=80):
        h = 56
        urg  = self.t < 15 and self.status == "active"
        fail = self.status == "failed"
        brd  = C["red"] if fail else C["ord_urg"] if urg else C["ord_brd"]
        a    = 90 if fail else 255

        bg = pygame.Surface((w, h), pygame.SRCALPHA)
        bg.fill((*C["ord_bg"], a)); surf.blit(bg, (x, y))
        pygame.draw.rect(surf, brd, (x, y, w, h), 1, border_radius=7)

        nm = F[12].render(self.recipe["name"], True,
                          C["blue"] if not fail else (130, 130, 130))
        surf.blit(nm, (x + w // 2 - nm.get_width() // 2, y + 5))

        abbr = " ".join(
            n.replace("_c", "*").replace("tomato", "Tom").replace("carrot", "Car")
             .replace("onion", "Oni").replace("mushroom", "Msh").replace("rice", "Ric")
            for n in self.recipe["needs"])
        ni = F[12].render(abbr, True, (150, 150, 150))
        surf.blit(ni, (x + w // 2 - ni.get_width() // 2, y + 20))

        pct = self.t / ORDER_TIME if self.status == "active" else 0
        col_f = C["green"] if pct > 0.4 else C["orange"] if pct > 0.15 else C["red"]
        bar(surf, x + 4, y + h - 11, w - 8, 6, pct, (25, 38, 48), col_f, 2)