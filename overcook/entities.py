import pygame
import math
import time
import os
import uuid

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from .engine import F, get_img
from .constants import (
    C,
    INGS,
    RECIPES,
    BURN_TIME,
    ORDER_TIME,
    CHOP_ACTIONS,
    STIR_ACTIONS,
    PLAYER_COLORS,
)
from .utils import rr, bar


COMPLETED_FOOD_DIR = os.path.join(_ROOT, "assets", "images", "completed_foods")
_COMPLETED_IMG_CACHE = {}

# Station icon images mapping
STATION_ICONS = {
    "ing":    os.path.join(_ROOT, "assets", "images", "stations", "pantry.png"),
    "chop":   os.path.join(_ROOT, "assets", "images", "stations", "chop.png"),
    "pot":    os.path.join(_ROOT, "assets", "images", "stations", "stove.png"),
    "submit": os.path.join(_ROOT, "assets", "images", "stations", "submit.png"),
    "trash":  os.path.join(_ROOT, "assets", "images", "stations", "trash.png"),
}
_STATION_ICON_CACHE = {}


def _load_station_icon(kind, max_size):
    """Load station icon from assets/stations folder, maintaining aspect ratio."""
    key = (kind, max_size)
    if key in _STATION_ICON_CACHE:
        return _STATION_ICON_CACHE[key]

    path = STATION_ICONS.get(kind)
    if not path or not os.path.exists(path):
        _STATION_ICON_CACHE[key] = None
        return None

    try:
        img = pygame.image.load(path).convert_alpha()
        # Get original aspect ratio and scale to fit within max_size
        orig_w, orig_h = img.get_size()
        ratio = min(max_size / orig_w, max_size / orig_h)
        new_w = max(1, int(orig_w * ratio))
        new_h = max(1, int(orig_h * ratio))
        img = pygame.transform.smoothscale(img, (new_w, new_h))
        _STATION_ICON_CACHE[key] = img
        return img
    except Exception:
        _STATION_ICON_CACHE[key] = None
        return None


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
        return _load_completed_food_img("unknown_dish.png", w, h)
    return _load_completed_food_img(f"{dish_name}.png", w, h)


class Station:
    SW = 180
    SH = 62

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


    def draw(self, surf, gy, show_label=True, show_box=True):
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

        # rr(surf, base, (self.x + 8, self.y + self.h, self.w - 16, gy - self.y - self.h), 2)
        box_x, box_y, box_w, box_h = self.x, self.y, self.w, self.h
        if show_box:
            # In amateur mode, lower and slim this box so it does not overlap station icons.
            box_y = self.y + 10
            box_h = max(36, self.h - 14)
            rr(surf, top, (box_x, box_y, box_w, box_h), 6)
            surf.fill((255, 255, 255, 15), (box_x + 5, box_y + 2, box_w - 10, 3))

        if show_label:
            s = F[14].render(self._station_label(), True, (220, 220, 220))
            label_cx = box_x + box_w // 2 if show_box else self.cx()
            label_cy = box_y + box_h // 2 if show_box else self.cy()
            surf.blit(s, (label_cx - s.get_width() // 2, label_cy - s.get_height() // 2))

        ix, iy = self.cx(), self.y - 8
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
        # Try to load icon image from assets
        # Scale icon size with station dimensions so larger stations remain readable.
        max_size = int(min(self.w * 0.6, self.h * 1.9))
        icon_img = _load_station_icon(self.kind, max_size)
        if icon_img:
            img_w, img_h = icon_img.get_size()
            x = ix - img_w // 2
            y = iy - img_h + 20
            surf.blit(icon_img, (int(x), int(y)))
            # Draw item overlays on top of the icon image
            if self.kind == "chop" and self.chop_item:
                self._draw_chop_item(surf, ix, iy - 8)
            elif self.kind == "pot":
                self._draw_pot_items(surf, ix, iy - 60)
            return

        # Fallback to original drawing code if image not found
        if self.kind == "ing":
            rr(surf, C["ing_top"], (ix - 14, iy - 10, 28, 20), 4)
            t = F[12].render("INGs", True, (255, 255, 255))
            surf.blit(t, (ix - t.get_width() // 2, iy - t.get_height() // 2))

        elif self.kind == "chop":
            if self.chop_item:
                self._draw_chop_item(surf, ix, iy)
            else:
                pygame.draw.line(surf, (180, 180, 180), (ix - 10, iy + 8), (ix + 10, iy - 8), 3)
                pygame.draw.line(surf, (130, 130, 130), (ix + 7, iy - 10), (ix + 12, iy - 5), 2)

        elif self.kind == "pot":
            pygame.draw.circle(surf, (80, 80, 80), (ix, iy), 13)
            pygame.draw.circle(surf, (110, 110, 110), (ix, iy), 13, 1)
            self._draw_pot_items(surf, ix, iy)

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

    def _draw_chop_item(self, surf, ix, iy):
        """Draw the item on the chop board plus progress bar.
        Shows the _c (chopped) image once chopping is complete."""
        item_id = self.chop_item["id"]
        chopped = self.chop_item.get("chopped", False)
        # Use _c image after chopping, base image while in progress
        display_id = item_id if chopped else item_id.replace("_c", "")
        img = get_img(display_id, 38, 38)
        if img:
            surf.blit(img, (ix - 19, iy - 19))
        else:
            base_id = item_id.replace("_c", "")
            col = INGS.get(base_id, {}).get("color", (150, 150, 150))
            pygame.draw.circle(surf, col, (ix, iy), 19)
        if chopped:
            pygame.draw.line(surf, C["lime"], (ix - 6, iy + 4), (ix + 10, iy - 6), 2)
        else:
            bar(surf, self.x + 14, self.y - 50, self.w - 28, 5,
                self.chop_prog, (50, 50, 50), C["orange"], 2)

    def _draw_pot_items(self, surf, ix, iy):
        """Draw ingredients in the pot plus cooking/burn progress bars."""
        if self.pot_items:
            n = min(len(self.pot_items), 3)
            for i, item in enumerate(self.pot_items[:3]):
                ox = ix + (i - (n - 1) / 2) * 16
                item_id = item.get("id", "")
                chopped = bool(item.get("chopped"))
                display_id = item_id if chopped else item_id.replace("_c", "")
                base_id = item_id.replace("_c", "")
                img = get_img(display_id, 30, 30)
                if img:
                    surf.blit(img, (int(ox) - 15, iy - 15))
                else:
                    col = INGS.get(base_id, {}).get("color", (150, 150, 150))
                    pygame.draw.circle(surf, col, (int(ox), iy), 13)
        if self.pot_cooking or self.pot_cooked:
            col_f = C["green"] if self.pot_cooked else C["orange"]
            bar(surf, self.x + 14, self.y - 90, self.w - 28, 5,
                self.pot_prog, (40, 40, 40), col_f, 2)
        if self.pot_cooked and self.pot_items:
            burn_pct = min(1.0, self.pot_burn / BURN_TIME)
            col_b = C["burn"] if burn_pct < 0.7 else C["red"]
            bar(surf, self.x + 14, self.y - 100, self.w - 28, 4,
                burn_pct, (30, 20, 20), col_b, 2)
        if self.pot_cooked and not (self.pot_burn >= BURN_TIME):
            pygame.draw.circle(surf, C["green"], (ix + 12, iy - 10), 5)

    def to_dict(self) -> dict:
        """Serialize station state for network transmission."""
        return {
            "kind": self.kind,
            "x": self.x,
            "y": self.y,
            "chop_item": self.chop_item,
            "chop_prog": self.chop_prog,
            "chop_hits": self.chop_hits,
            "chopping": self.chopping,
            "pot_items": self.pot_items,
            "pot_prog": self.pot_prog,
            "pot_cooking": self.pot_cooking,
            "pot_stirs": self.pot_stirs,
            "pot_cooked": self.pot_cooked,
            "pot_burn": self.pot_burn,
            "pot_on": self.pot_on,
            "pot_burned": self.pot_burned,
            "plate_item": self.plate_item,
        }

    def apply_dict(self, d: dict):
        """Apply server state to this station."""
        self.chop_item = d.get("chop_item")
        self.chop_prog = d.get("chop_prog", 0.0)
        self.chop_hits = d.get("chop_hits", 0)
        self.chopping = d.get("chopping", False)
        self.pot_items = d.get("pot_items", [])
        self.pot_prog = d.get("pot_prog", 0.0)
        self.pot_cooking = d.get("pot_cooking", False)
        self.pot_stirs = d.get("pot_stirs", 0)
        self.pot_cooked = d.get("pot_cooked", False)
        self.pot_burn = d.get("pot_burn", 0.0)
        self.pot_on = d.get("pot_on", False)
        self.pot_burned = d.get("pot_burned", False)
        self.plate_item = d.get("plate_item")


class Player:
    PW, PH = 38, 50

    def __init__(self, x, y, player_id: int = 0, name: str = "Player 1"):
        self.x = float(x); self.y = float(y)
        self.vx = 0.0; self.vy = 0.0
        self.facing = 1
        self.holding = None
        self.walk_t = 0.0
        self.player_id = player_id
        self.name = name
        self._color_idx = player_id % len(PLAYER_COLORS)

    def _pc(self, key: str):
        """Get player color component (body/dark/hat)."""
        return PLAYER_COLORS[self._color_idx].get(key, C["char_body"])

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

    def draw(self, surf, is_local=True):
        px, py = int(self.x), int(self.y)
        f = self.facing
        walk = abs(self.vx) > 10
        bob  = int(math.sin(self.walk_t) * 2) if walk else 0
        ls   = int(math.sin(self.walk_t) * 5) if walk else 0
        as_  = int(math.sin(self.walk_t) * 4) if walk else 0

        # Use player-specific colors
        pc_body = self._pc("body")
        pc_dark = self._pc("dark")
        pc_hat = self._pc("hat")

        pygame.draw.ellipse(surf, (0, 0, 0, 50), (px + 2, py + self.PH - 7, self.PW - 4, 9))
        rr(surf, pc_dark, (px + 6,  py + 31 + ls,  11, 17), 3)
        rr(surf, pc_hat,  (px + 21, py + 31 - ls,  11, 17), 3)
        rr(surf, pc_body, (px + 3,  py + 18 + bob, 32, 22), 6)
        rr(surf, C["apron"],     (px + 9,  py + 20 + bob, 20, 17), 3)
        rr(surf, (200, 195, 180),(px + 11, py + 22 + bob, 16, 12), 2)
        rr(surf, pc_body, (px + (32 if f > 0 else 0),  py + 21 + bob - as_, 8, 14), 3)
        rr(surf, pc_body, (px + (0  if f > 0 else 30), py + 21 + bob + as_, 8, 14), 3)
        pygame.draw.circle(surf, C["char_face"], (px + 19, py + 12 + bob), 13)
        rr(surf, C["white"],    (px + 9,  py + 1 + bob, 20, 10), 2)
        rr(surf, (230, 230, 230),(px + 5, py + 8 + bob, 28, 5), 1)

        ex = px + 19 + f * 5
        pygame.draw.circle(surf, pc_hat,       (ex,     py + 12 + bob), 2)
        pygame.draw.circle(surf, (255, 255, 255),  (ex + 1, py + 11 + bob), 1)
        pygame.draw.arc(surf, (80, 60, 30),
                (px + 15 + f, py + 14 + bob, 8, 5),
                        math.pi + 0.2, 2 * math.pi - 0.2, 2)

        # Name label above player
        name_lbl = F[12].render(self.name, True, C["white"])
        name_x = px + self.PW // 2 - name_lbl.get_width() // 2
        name_y = py - 18
        surf.blit(name_lbl, (name_x, name_y))
        if is_local:
            # Underline for local player
            pygame.draw.line(surf, pc_body, 
                           (name_x, name_y + name_lbl.get_height() + 1),
                           (name_x + name_lbl.get_width(), name_y + name_lbl.get_height() + 1), 2)

        if self.holding:
            hx = px + 19 + f * 28
            hy = py + 6 + bob
            item_id = self.holding.get("id", "")
            is_completed = bool(self.holding.get("cooked"))
            item_size = 50 if is_completed else 32
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
                rad = 20 if is_completed else 15
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

    def to_dict(self) -> dict:
        """Serialize player state for network transmission."""
        return {
            "x": self.x,
            "y": self.y,
            "vx": self.vx,
            "vy": self.vy,
            "facing": self.facing,
            "holding": self.holding,
            "player_id": self.player_id,
            "name": self.name,
        }

    def apply_dict(self, d: dict):
        """Apply server state to this player."""
        self.x = d.get("x", self.x)
        self.y = d.get("y", self.y)
        self.vx = d.get("vx", self.vx)
        self.vy = d.get("vy", self.vy)
        self.facing = d.get("facing", self.facing)
        self.holding = d.get("holding")
        # player_id and name don't change


class Order:
    def __init__(self, recipe):
        self.id = uuid.uuid4().hex[:8]  # unique per-session, survives game resets
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
        h = 74
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

        needs = self.recipe["needs"]
        n_needs = len(needs)
        img_sz = min(36, max(20, (w - 16) // max(n_needs, 1) - 4))
        gap_i = 5
        total_w = n_needs * img_sz + (n_needs - 1) * gap_i
        start_x = x + w // 2 - total_w // 2
        iy = y + 22
        for idx_i, need in enumerate(needs):
            ix = start_x + idx_i * (img_sz + gap_i)
            base = need.replace("_c", "")
            img = get_img(base, img_sz, img_sz)
            if img:
                surf.blit(img, (ix, iy))
            else:
                ing = INGS.get(base, {})
                col_i = ing.get("color", (150, 150, 150))
                pygame.draw.circle(surf, col_i, (ix + img_sz // 2, iy + img_sz // 2), img_sz // 2)

        pct = self.t / ORDER_TIME if self.status == "active" else 0
        col_f = C["green"] if pct > 0.4 else C["orange"] if pct > 0.15 else C["red"]
        bar(surf, x + 4, y + h - 13, w - 8, 7, pct, (25, 38, 48), col_f, 2)

    def to_dict(self) -> dict:
        """Serialize order state for network transmission."""
        return {
            "id": self.id,
            "recipe_name": self.recipe["name"],
            "t": self.t,
            "status": self.status,
        }

    def apply_dict(self, d: dict):
        """Apply server state to this order."""
        self.t = d.get("t", self.t)
        self.status = d.get("status", self.status)