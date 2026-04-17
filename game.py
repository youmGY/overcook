#!/usr/bin/env python3
"""
오버쿡 스타일 요리 게임 (pygame)
실행: python game.py
설치: pip install pygame

조작: 화면 버튼 (← →  이동 | Action 버튼)
      키보드:  ← → 이동 | Z / Space = 행동
"""

import dataclasses
import argparse
import pygame
import sys
import random
import logging
from typing import Optional

try:
    import cv2
except Exception:
    cv2 = None

from engine import screen, clock, FPS, F, get_img
from constants import C, INGS, RECIPES, BURN_TIME, ORDER_TIME, GAME_TIME, CHOP_ACTIONS, STIR_ACTIONS
from utils import rr, txt, bar
from ui import Popup, Btn, RecipeOverlay, IngredientOverlay
from entities import Station, Player, Order

# ── logger ────────────────────────────────────────────────────────────────
logging.basicConfig(
    filename="game.log",
    filemode="a",
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("overcook")

# ── gesture / unified input ───────────────────────────────────────────────
GESTURE_STATION_SLOTS: dict[int, str] = {
    1: "trash",
    2: "ing",
    3: "chop",
    4: "pot",
    5: "submit",
}


@dataclasses.dataclass
class GameInput:
    move_to_slot: Optional[int] = None
    station_click: Optional[tuple] = None
    chop:         bool = False
    stir:         bool = False
    put_down:     bool = False
    confirm:      bool = False
    move_dir:      int  = 0
    action:        bool = False
    overlay_click: Optional[tuple] = None


class Game:
    def __init__(self, ui_mode: str = "active"):
        self.ui_mode = ui_mode
        self.use_camera_ui = ui_mode != "test"
        self._camera = None
        self._camera_error = None
        self._act_btn_info = self._build_act_btn_info()

        if self.use_camera_ui:
            self._init_camera()

        self.state = "title"
        self.overlay = IngredientOverlay()
        self.recipe_overlay = RecipeOverlay()
        self._make_btns()
        self.reset()

    def _build_act_btn_info(self):
        return [
            ("confirm", "OK", (60, 120, 60)),
            ("chop", "Chop Chop", (120, 80, 30)),
            ("stir", "Stir Stir", (30, 80, 120)),
            ("pause", "Pause", (80, 60, 80)),
        ]

    def _init_camera(self):
        if cv2 is None:
            self._camera_error = "OpenCV(cv2) not installed"
            return
        cam = cv2.VideoCapture(0)
        if not cam or not cam.isOpened():
            self._camera_error = "Camera open failed"
            return
        self._camera = cam

    def shutdown(self):
        if self._camera:
            self._camera.release()
            self._camera = None

    def reset(self):
        log.info("--- GAME RESET ---")
        self.score = 0
        self.timer = GAME_TIME
        self.orders = []; self.popups = []
        self.elapsed = 0.0; self.next_order = 15.0
        self._build_level()
        gw, gh = screen.get_size()
        gy = self._gy()
        self.player = Player(gw // 2 - 15, gy - 50)
        self.overlay.active = False
        self.overlay.rebuild()
        self.recipe_overlay.active = False

    def _gy(self):
        _, gh = screen.get_size()
        return gh - gh // 4

    def _build_level(self):
        gw, gh = screen.get_size()
        gy = self._gy()
        self.gw, self.gh = gw, gh

        N   = 5
        pad = 20
        gap = (gw - 2 * pad - N * Station.SW) // (N - 1)
        sy  = gy - Station.SH - 36

        kinds = ["trash", "ing", "chop", "pot", "submit"]
        self.stations = []
        for i, k in enumerate(kinds):
            sx = pad + i * (Station.SW + gap)
            self.stations.append(Station(k, sx, sy))

    def _recipe_panel_rect(self):
        gw, gh = screen.get_size()
        HUD_H = 44
        gy = self._gy()
        station_top = gy - Station.SH - 36 - 40
        pad = 8
        full_h = max(70, station_top - HUD_H - pad * 2)
        reduced_h = int(full_h * 0.82)
        return (pad, HUD_H + pad, gw - pad * 2, reduced_h)

    def _camera_rect_from_controls(self):
        return getattr(self, "_cam_slot_rect", None)

    def _draw_camera_panel(self):
        if not self.use_camera_ui:
            return
        rect = self._camera_rect_from_controls()
        if rect is None:
            return

        rr(screen, (18, 20, 28), rect, 8)
        pygame.draw.rect(screen, (55, 65, 85), rect, 1, border_radius=8)

        frame_surf = self._capture_camera_surface(rect.w - 8, rect.h - 8)
        inner = pygame.Rect(rect.x + 4, rect.y + 4, rect.w - 8, rect.h - 8)
        if frame_surf:
            screen.blit(frame_surf, inner.topleft)
        else:
            pygame.draw.rect(screen, (30, 34, 48), inner, border_radius=6)
            msg = self._camera_error or "Camera not ready"
            s = F[12].render(msg, True, (190, 190, 210))
            screen.blit(s, (inner.centerx - s.get_width() // 2, inner.centery - s.get_height() // 2))

    def _capture_camera_surface(self, w: int, h: int):
        if not self._camera:
            return None
        ok, frame = self._camera.read()
        if not ok or frame is None:
            self._camera_error = "Camera frame read failed"
            return None

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frame = cv2.flip(frame, 1)

        # Keep original camera aspect ratio and pad with black bars.
        src_h, src_w = frame.shape[:2]
        scale = min(w / float(src_w), h / float(src_h))
        new_w = max(1, int(src_w * scale))
        new_h = max(1, int(src_h * scale))
        resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)

        pad_x = w - new_w
        pad_y = h - new_h
        left = pad_x // 2
        right = pad_x - left
        top = pad_y // 2
        bottom = pad_y - top
        frame = cv2.copyMakeBorder(
            resized,
            top,
            bottom,
            left,
            right,
            cv2.BORDER_CONSTANT,
            value=(0, 0, 0),
        )

        frame = frame.swapaxes(0, 1)
        return pygame.surfarray.make_surface(frame)

    def _make_btns(self):
        gw, gh = screen.get_size()
        gy = self._gy()
        y   = gy + 8
        pad = 8
        gap = 4
        self.btn_acts = []
        self.btn_acts_map = {}

        if self.use_camera_ui:
            # Left side: 2×2 grid  (OK / Chop Chop on top, Stir Stir / Pause on bottom)
            # Right side: camera panel
            avail_h = gh - y - pad
            btn_h   = max(28, (avail_h - gap) // 2)
            left_w  = (gw - pad * 2) * 2 // 3         # left 2/3 for buttons (2 cols)
            btn_w   = (left_w - gap) // 2

            grid = [
                (0, 0, "chop",    "Chop Chop", (120, 80,  30)),
                (1, 0, "stir",    "Stir Stir", ( 30, 80, 120)),
                (0, 1, "confirm", "OK",        ( 60, 120,  60)),
                (1, 1, "pause",   "Pause",     ( 80, 60,  80)),
            ]
            for col, row, key, lbl, col_c in grid:
                bx = pad + col * (btn_w + gap)
                by = y  + row * (btn_h + gap)
                btn = Btn(bx, by, btn_w, btn_h, lbl, col_c)
                self.btn_acts.append(btn)
                self.btn_acts_map[key] = btn

            # Camera slot: right 1/3
            cam_x = pad + left_w + gap
            cam_w = gw - cam_x - pad
            self._cam_slot_rect = pygame.Rect(cam_x, y, cam_w, avail_h)
        else:
            # test: classic 4-button horizontal row
            bh    = max(28, (gh - gy - 24) // 2 - 4)
            n_act = 4
            right_w = gw - pad * 2
            aw = (right_w - gap * (n_act - 1)) // n_act
            for i, (key, lbl, col_c) in enumerate([
                ("confirm", "OK",        (60, 120, 60)),
                ("chop",    "Chop Chop", (120, 80, 30)),
                ("stir",    "Stir Stir", (30,  80, 120)),
                ("pause",   "Pause",     (80,  60, 80)),
            ]):
                bx = pad + i * (aw + gap)
                btn = Btn(bx, y, aw, bh, lbl, col_c)
                self.btn_acts.append(btn)
                self.btn_acts_map[key] = btn
            self._cam_slot_rect = None

        self.btn_action = self.btn_acts_map["confirm"]
        self.btn_start  = Btn(gw // 2 - 55, gh // 2 + 70, 110, 52, "Start", (50, 50, 130))
        self.btn_pause_continue = Btn(gw // 2 - 115, gh // 2 + 20, 110, 52, "▶ Continue", (40, 120, 60))
        self.btn_pause_restart  = Btn(gw // 2 + 5,   gh // 2 + 20, 110, 52, "↺ Restart",  (120, 50, 50))

    def _near(self):
        px, py = self.player.center()
        best, bd = None, 9999
        for s in self.stations:
            d = s.dist(px, py)
            if d < 110 and d < bd:
                best, bd = s, d
        return best

    def _station_for_slot(self, slot: int):
        kind = GESTURE_STATION_SLOTS.get(slot)
        if not kind: return None
        group = [s for s in self.stations if s.kind == kind]
        if not group: return None
        if kind == "chop":
            idle = [s for s in group if not s.chop_item and not s.chopping]
            return idle[0] if idle else group[0]
        if kind == "pot":
            idle = [s for s in group if not s.pot_cooking and not s.pot_cooked]
            return idle[0] if idle else group[0]
        return group[0]

    def _station_at_point(self, pos):
        if not pos:
            return None
        x, y = pos
        for st in self.stations:
            if pygame.Rect(st.x, st.y, st.w, st.h).collidepoint(x, y):
                return st
        return None

    def _find_submit_dish(self):
        h = self.player.holding
        if h and h.get("cooked"): return h, True
        return None, False

    def _clear_submit_source(self, from_holding: bool):
        if from_holding: self.player.holding = None

    def _dish_name_from_contents(self, contents):
        h_ids = sorted(c.get("id") for c in contents if isinstance(c, dict) and c.get("id"))
        if len(h_ids) != len(contents):
            return None
        for rec in RECIPES:
            if not rec.get("cook", True):
                continue
            if sorted(rec.get("needs", [])) == h_ids:
                return rec.get("name")
        return None

    def _act_ing(self, _st):
        if not self.player.holding:
            self.overlay.active = True
        else:
            self._pop(self.player.x, self.player.y - 20, "Drop item first!", C["red"])

    def _act_chop(self, st, chop_action=False):
        h = self.player.holding
        if h:
            base = h.get("id", "").replace("_c", "")
            if h.get("chopped"):
                self._pop(self.player.x, self.player.y - 20, "Already chopped", C["white"])
                return
            if not base or not INGS.get(base, {}).get("can_chop"):
                self._pop(self.player.x, self.player.y - 20, "Can't chop this!", C["red"])
                return
            if st.chop_item:
                self._pop(self.player.x, self.player.y - 20, "Board occupied", C["orange"])
                return

            st.chop_item = dict(h)
            self.player.holding = None
            st.chop_prog = 0.0
            if chop_action:
                st.chop_hits = 1
                st.chopping = True
                self._pop(st.cx(), st.y - 14, f"Chop {CHOP_ACTIONS}x ({st.chop_hits}/{CHOP_ACTIONS})", C["orange"])
            else:
                st.chop_hits = 0
                st.chopping = False
                self._pop(st.cx(), st.y - 14, "Placed on board", C["lime"])
            return

        if st.chop_item and st.chop_item.get("chopped"):
            self.player.holding = dict(st.chop_item)
            st.chop_item = None
            st.chop_prog = 0.0
            st.chop_hits = 0
            st.chopping = False
            self._pop(self.player.x, self.player.y - 20, "Picked up", C["lime"])
            return

        if chop_action and st.chop_item and not st.chop_item.get("chopped"):
            st.chopping = True
            st.chop_hits = min(CHOP_ACTIONS, st.chop_hits + 1)
            st.chop_prog = st.chop_hits / float(CHOP_ACTIONS)
            self._pop(st.cx(), st.y - 14, f"Chop {CHOP_ACTIONS}x ({st.chop_hits}/{CHOP_ACTIONS})", C["orange"])

    def _act_pot(self, st, stir_only=False):
        h = self.player.holding
        burned = st.pot_burned

        if stir_only:
            if h:
                self._pop(self.player.x, self.player.y - 20, "Drop item first!", C["red"])
                return
            if not st.pot_items:
                self._pop(st.cx(), st.y - 14, "Add ingredients first", C["white"])
                return
            if st.pot_burned:
                self._pop(st.cx(), st.y - 14, "Already burned! Clear it.", C["burn"])
                return
            if not st.pot_cooking and not st.pot_cooked:
                st.pot_on = True
                st.pot_cooking = True
                st.pot_stirs = 0
                st.pot_prog = 0.0
            st.pot_stirs += 1
            if st.pot_stirs >= STIR_ACTIONS + 3:
                st.pot_cooking = False
                st.pot_cooked = True
                st.pot_burned = True
                st.pot_burn = BURN_TIME
                self._pop(st.cx(), st.y - 14, "🔥 Over-stirred! BURNED!", C["burn"])
                log.warning("POT_BURNED: over-stirred")
                return
            st.pot_prog = min(1.0, st.pot_stirs / float(STIR_ACTIONS))
            self._pop(st.cx(), st.y - 14, f"Stir {STIR_ACTIONS}x ({st.pot_stirs}/{STIR_ACTIONS})", C["orange"])
            return

        if h and h.get("cooked"):
            self._pop(self.player.x, self.player.y - 20, "Can't add cooked dish!", C["red"])
        elif h and not st.pot_cooked:
            base = h.get("id", "").replace("_c", "")
            if INGS.get(base, {}).get("can_chop") and not h.get("chopped"):
                self._pop(self.player.x, self.player.y - 20, "Chop it first!", C["red"])
            else:
                st.pot_items.append(dict(h))
                self.player.holding = None
                self._pop(st.cx(), st.y - 14, "Added ✓", C["gold"])
        elif not h and st.pot_cooked and not burned:
            dish_name = self._dish_name_from_contents(st.pot_items)
            self.player.holding = {
                "id": "cooked",
                "label": "Cooked Dish",
                "contents": list(st.pot_items),
                "dish_name": dish_name,
                "cooked": True,
            }
            st.pot_items = []
            st.pot_cooked = False
            st.pot_cooking = False
            st.pot_stirs = 0
            st.pot_prog = 0.0
            st.pot_on = False
            st.pot_burn = 0.0
            st.pot_burned = False
            self._pop(self.player.x, self.player.y - 20, "Picked!", C["green"])
        elif not h and burned:
            dish_name = self._dish_name_from_contents(st.pot_items)
            self.player.holding = {
                "id": "cooked",
                "label": "Burned Dish",
                "contents": list(st.pot_items),
                "dish_name": dish_name,
                "cooked": True,
                "burned": True,
            }
            st.pot_items = []
            st.pot_cooked = False
            st.pot_cooking = False
            st.pot_stirs = 0
            st.pot_prog = 0.0
            st.pot_on = False
            st.pot_burn = 0.0
            st.pot_burned = False
            self._pop(self.player.x, self.player.y - 20, "Picked burned dish!", C["burn"])
        elif not h and st.pot_cooking:
            self._pop(st.cx(), st.y - 14, f"Stir {STIR_ACTIONS}x ({st.pot_stirs}/{STIR_ACTIONS})", C["white"])

    def _act_submit(self, st):
        dish, from_holding = self._find_submit_dish()
        if not dish:
            self._pop(st.cx(), st.y - 14, "Nothing to submit!", C["red"])
            return

        contents = dish.get("contents", [])
        h_ids = sorted(c.get("id") for c in contents if isinstance(c, dict) and c.get("id"))
        if len(h_ids) != len(contents):
            self._pop(st.cx(), st.y - 14, "Invalid dish: missing ingredient id", C["red"])
            self._clear_submit_source(from_holding)
            return

        matched = None
        for o in self.orders:
            if o.status != "active": continue
            if sorted(o.recipe["needs"]) == h_ids and o.recipe.get("cook", True) == dish.get("cooked", False):
                matched = o
                break

        if matched:
            if dish.get("burned"):
                penalty = matched.recipe["pts"] // 2
                self.score = max(0, self.score - penalty)
                matched.status = "done"
                self._clear_submit_source(from_holding)
                self._pop(st.cx(), st.y - 30, f"-{penalty} pts! BURNED!", C["burn"])
            else:
                bonus = int(matched.t / ORDER_TIME * 50)
                pts = matched.recipe["pts"] + bonus
                self.score += pts
                matched.status = "done"
                self._clear_submit_source(from_holding)
                self._pop(st.cx(), st.y - 30, f"+{pts} pts! 🎉", C["green"])
        else:
            penalty = 30
            self.score = max(0, self.score - penalty)
            self._pop(st.cx(), st.y - 14, f"No order! -{penalty} pts", C["red"])
            self._clear_submit_source(from_holding)

    def _act_trash(self, st):
        h = self.player.holding
        if h:
            self.player.holding = None
            self._pop(st.cx(), st.y - 14, "Trashed!", C["pink"])
            return

        chops = [s for s in self.stations if s.kind == "chop" and s.chop_item]
        if chops:
            for chop in chops:
                chop.chop_item = None
                chop.chop_prog = 0.0
                chop.chop_hits = 0
                chop.chopping = False
            self._pop(st.cx(), st.y - 14, "Chop boards cleared", C["pink"])
        else:
            self._pop(st.cx(), st.y - 14, "Nothing to trash", C["white"])

    def do_action(self):
        if self.overlay.active:
            self.overlay.active = False
            return
        st = self._near()
        if not st: return
        handlers = {
            "ing": self._act_ing,
            "chop": self._act_chop,
            "pot": self._act_pot,
            "submit": self._act_submit,
            "trash": self._act_trash,
        }
        handler = handlers.get(st.kind)
        if handler: handler(st)

    def _pick_ingredient(self, ing_key):
        ing = INGS[ing_key]
        self.player.holding = {"id": ing_key, "label": ing["label"], "chopped": False}
        self._pop(self.player.x, self.player.y - 20, f"Picked {ing['label']}", C["lime"])
        self.overlay.active = False

    def _pop(self, x, y, msg, col):
        self.popups.append(Popup(x, y, msg, col))

    def _spawn_order(self):
        active = sum(1 for o in self.orders if o.status == "active")
        if active >= 3: return
        self.orders.append(Order(random.choice(RECIPES)))

    def _hint(self):
        if self.overlay.active: return "Click an ingredient card  |  ESC to cancel"
        st = self._near()
        if not st: return ""
        h = self.player.holding
        k = st.kind
        if k == "ing":
            return "Action: Open pantry" if not h else "Action: Drop item first"
        if k == "chop":
            if h and not h.get("chopped") and INGS.get(h.get("id", "").replace("_c", ""), {}).get("can_chop"):
                return "Action: Place on board  |  Chop!: Start chopping"
            if not h and st.chop_item and st.chop_item.get("chopped"):
                return "Action: Pick chopped item"
            if not h and st.chop_item:
                return f"Chop button: {st.chop_hits}/{CHOP_ACTIONS}"
        if k == "pot":
            burned = st.pot_burned
            if burned: return "Action: Pick up burned dish (trash to discard)"
            if h and not st.pot_cooked:
                base = h.get("id", "").replace("_c", "")
                if INGS.get(base, {}).get("can_chop") and not h.get("chopped"):
                    return "Chop it first before adding to pot!"
                return "Action: Add to pot"
            if not h and st.pot_items and not st.pot_cooking and not st.pot_cooked:
                return f"Stir to start cooking! (max {STIR_ACTIONS + 2} stirs)"
            if not h and st.pot_cooked: return "Action: Pick cooked dish"
            if not h and st.pot_cooking: return f"Stir button: {st.pot_stirs}/{STIR_ACTIONS} (burn at {STIR_ACTIONS + 3})"
        if k == "submit":
            if h and h.get("cooked"):
                if h.get("burned"): return "Action: Submit burned dish (penalty!)"
                return "Action: Submit dish!"
            dish, _ = self._find_submit_dish()
            return "Action: Submit dish!" if dish else "Action: Nothing to submit"
        if k == "trash":
            if h: return "Action: Trash item"
            return "Action: Clear chop boards"
        return ""

    def update(self, dt, gi: "GameInput", mpos, mpressed):
        gw, gh = screen.get_size()
        if gw != self.gw or gh != self.gh:
            self.gw, self.gh = gw, gh
            self._build_level(); self._make_btns()
            self.overlay.rebuild()

        if self.state in ("title", "over"):
            if self.btn_start.update(mpos, mpressed):
                self.reset(); self.state = "play"
                self._spawn_order(); self._spawn_order()
            return

        if self.state == "paused":
            if self.btn_pause_continue.update(mpos, mpressed): self.state = "play"
            if self.btn_pause_restart.update(mpos, mpressed):
                self.reset(); self.state = "play"
                self._spawn_order(); self._spawn_order()
            return

        if self.overlay.active:
            if gi.overlay_click:
                key = self.overlay.check_click(gi.overlay_click)
                if key: self._pick_ingredient(key)
                else: self.overlay.active = False
            return

        if self.recipe_overlay.active: return

        move_to_slot = gi.move_to_slot
        clicked_station = self._station_at_point(gi.station_click)
        if clicked_station:
            self.player.x = float(clicked_station.cx() - Player.PW // 2)
            self.player.y = float(self._gy() - Player.PH)
            self.player.vy = 0.0

        act_flags = {
            "confirm":  gi.confirm  or gi.action,
            "chop":     gi.chop,
            "stir":     gi.stir,
            "pause":    False,
        }

        for btn in self.btn_acts:
            key = next(k for k, v in self.btn_acts_map.items() if v is btn)
            if btn.update(mpos, mpressed):
                act_flags[key] = True

        if act_flags["pause"]:
            self.state = "paused"
            return

        move_dir = gi.move_dir
        if move_to_slot is not None:
            target = self._station_for_slot(move_to_slot)
            if target:
                self.player.x = float(target.cx() - Player.PW // 2)
                self.player.y = float(self._gy() - Player.PH)
                self.player.vy = 0.0

        self.player.update(move_dir, dt, gw, self._gy())

        handled = False
        if act_flags["chop"]:
            st = self._near()
            if st and st.kind == "chop":
                self._act_chop(st, chop_action=True)
                handled = True
        if act_flags["stir"] and not handled:
            st = self._near()
            if st and st.kind == "pot":
                self._act_pot(st, stir_only=True)
                handled = True
        if act_flags["confirm"] and not handled:
            self.do_action()

        for s in self.stations:
            events = s.update(dt)
            for ev in events:
                if ev == "chop_done": self._pop(s.cx(), s.y - 14, "✓ Chopped!", C["lime"])
                elif ev == "cook_done": self._pop(s.cx(), s.y - 14, "✓ Cooked! Pick it up!", C["green"])
                elif ev == "burned": self._pop(s.cx(), s.y - 14, "🔥 BURNED!", C["burn"])

        for o in self.orders:
            ev = o.update(dt)
            if ev == "failed":
                self.score = max(0, self.score - 30)
                self._pop(gw // 2, gh // 2 - 80, "Order failed! -30", C["red"])

        self.elapsed += dt
        if self.elapsed >= self.next_order:
            self._spawn_order()
            self.next_order = self.elapsed + 15.0

        self.timer = max(0.0, self.timer - dt)
        if self.timer <= 0:
            self.state = "over"

        for p in self.popups: p.update()
        self.popups = [p for p in self.popups if not p.dead]

    def draw(self):
        gw, gh = screen.get_size()
        gy = self._gy()

        screen.fill(C["bg"])
        for y in range(0, gh, 32):
            pygame.draw.line(screen, (*C["grid"], 20), (0, y), (gw, y), 1)
        for x in range(0, gw, 36):
            c = C["tile_a"] if (x // 36) % 2 == 0 else C["tile_b"]
            screen.fill(c, (x, 0, 35, gy))

        screen.fill(C["ground"], (0, gy, gw, gh - gy))
        for x in range(0, gw, 30):
            c = C["tile_a"] if (x // 30) % 2 == 0 else C["tile_b"]
            screen.fill(c, (x, gy, 29, 7))
        pygame.draw.line(screen, (*C["ground_line"], 100), (0, gy), (gw, gy), 2)
        screen.fill((8, 8, 26), (0, gy + 7, gw, gh - gy - 7))

        for s in self.stations: s.draw(screen, gy)

        ns = self._near()
        if ns and not self.overlay.active:
            pygame.draw.rect(screen, (*C["yellow"], 200),
                             (ns.x - 2, ns.y - 2, ns.w + 4, ns.h + 4), 2, border_radius=8)

        self.player.draw(screen)
        for p in self.popups: p.draw(screen)

        self.overlay.draw(screen)
        self.recipe_overlay.draw(screen)

        self._draw_hud(gw, gh)
        if not self.overlay.active:
            self._draw_recipes_panel()

        if self.state == "play":
            for btn in self.btn_acts:
                btn.draw(screen)
            self._draw_camera_panel()

    def _draw_recipes_panel(self):
        rx, ry, rw, rh = self._recipe_panel_rect()
        if rh < 60: return

        rr(screen, (16, 20, 48), (rx, ry, rw, rh), 10)
        pygame.draw.rect(screen, (45, 40, 100), (rx, ry, rw, rh), 1, border_radius=10)

        title_s = F[14].render("Current Orders", True, C["gold"])
        screen.blit(title_s, (rx + 10, ry + 6))

        active_orders = [o for o in self.orders if o.status == "active"]
        if not active_orders:
            no_order_s = F[12].render("No active orders", True, (150, 150, 150))
            screen.blit(no_order_s, (rx + 10, ry + 35))
            return

        n = len(active_orders)
        TITLE_H = 24
        area_y = ry + TITLE_H
        area_h = rh - TITLE_H - 4
        area_w = rw - 12

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

            if cy_ + card_h > ry + rh - 2: break

            rr(screen, (24, 30, 62), (cx_, cy_, card_w, card_h), 6)
            pygame.draw.rect(screen, (55, 48, 115), (cx_, cy_, card_w, card_h), 1, border_radius=6)

            inner_y = cy_ + 4
            name_s = F[14].render(rec["name"], True, C["white"])
            if name_s.get_width() > card_w - 6:
                name_s = F[12].render(rec["name"], True, C["white"])
            screen.blit(name_s, (cx_ + 4, inner_y))

            pts_s = F[12].render(f"+{rec['pts']}", True, C["gold"])
            screen.blit(pts_s, (cx_ + card_w - pts_s.get_width() - 4, inner_y))
            inner_y += name_s.get_height() + 2

            dot_x = cx_ + 4
            for j, need in enumerate(rec["needs"]):
                r_dot = 5
                dy = inner_y + r_dot
                if dot_x + r_dot * 2 + 2 > cx_ + card_w - 4:
                    break
                
                img = get_img(need, 10, 10)
                if img:
                    screen.blit(img, (dot_x, dy - 5))
                else:
                    base = need.replace("_c", "")
                    ing  = INGS.get(base, {})
                    col_dot = ing.get("color", (150, 150, 150))
                    pygame.draw.circle(screen, col_dot, (dot_x + r_dot, dy), r_dot)
                
                dot_x += r_dot * 2 + 6
            inner_y += 14

            for idx, step in enumerate(rec.get("steps", [])):
                step_txt = f"{idx + 1}. {step}"
                step_s = F[11].render(step_txt, True, (200, 200, 100)) if 11 in F \
                         else F[12].render(step_txt[:22], True, (200, 200, 100))
                if step_s.get_width() > card_w - 8:
                    step_txt = f"{idx + 1}. {step[:18]}"
                    step_s = F[11].render(step_txt, True, (200, 200, 100)) if 11 in F \
                             else F[12].render(step_txt, True, (200, 200, 100))
                screen.blit(step_s, (cx_ + 4, inner_y))
                inner_y += step_s.get_height() + 1

            badge_lbl = "cook" if rec["cook"] else "raw"
            badge_col = C["orange"] if rec["cook"] else C["lime"]
            bs = F[12].render(badge_lbl, True, badge_col)
            screen.blit(bs, (cx_ + card_w - bs.get_width() - 4, cy_ + card_h - bs.get_height() - 3))

    def _draw_hud(self, gw, gh):
        HH = 44
        rr(screen, C["hud_bg"], (0, 0, gw, HH), 0)
        pygame.draw.line(screen, C["hud_brd"], (0, HH), (gw, HH), 1)

        sc = F[18].render(f"Score  {self.score}", True, C["gold"])
        screen.blit(sc, (12, HH // 2 - sc.get_height() // 2))

        m = int(self.timer) // 60; s = int(self.timer) % 60
        tc = C["red"] if self.timer < 20 else C["white"]
        tm = F[24].render(f"{m}:{s:02d}", True, tc)
        screen.blit(tm, (gw // 2 - tm.get_width() // 2, HH // 2 - tm.get_height() // 2))

        ox = gw - 8
        for o in reversed([o for o in self.orders if o.status != "done"]):
            ox -= 84
            o.draw(screen, ox, 2, w=82)

        hint = self._hint()
        if hint:
            hs = F[12].render(hint, True, (200, 200, 200))
            hw = hs.get_width() + 16; hh2 = hs.get_height() + 8
            bg = pygame.Surface((hw, hh2), pygame.SRCALPHA)
            bg.fill((0, 0, 0, 160))
            hy = self._gy() - hh2 - 4
            screen.blit(bg, (gw // 2 - hw // 2, hy))
            screen.blit(hs, (gw // 2 - hs.get_width() // 2, hy + 4))

    def draw_title(self):
        gw, gh = screen.get_size()
        screen.fill(C["bg"])
        txt(screen, "🍳 Cooking Game", 40, C["gold"], gw // 2, gh // 2 - 110)
        lines = [
            "Tap/click a station to move there  |  Action = interact",
            "Keyboard: arrow keys + Z/Space also work",
            "",
            "Pantry → pick ingredient   |   Chop board → OK to place, Chop! to chop",
            "Stove → add ingredients → Stir to cook (burn if over-stirred!)",
            "Stove done → pick up dish → go to Submit → submit for points",
            "Trash → drop unwanted items or clear chop board",
            "",
            "⚠  Leave pot too long after cooking → BURNED!",
            "Press R or Recipe button to view recipes anytime",
        ]
        for i, line in enumerate(lines):
            txt(screen, line, 14, (170, 170, 210), gw // 2, gh // 2 - 50 + i * 22)
        self.btn_start.draw(screen)

    def draw_over(self):
        self.draw()
        gw, gh = screen.get_size()
        ov = pygame.Surface((gw, gh), pygame.SRCALPHA)
        ov.fill((5, 5, 20, 210)); screen.blit(ov, (0, 0))
        txt(screen, "Game Over!", 40, C["gold"], gw // 2, gh // 2 - 80)
        txt(screen, f"{self.score} pts", 40, C["white"], gw // 2, gh // 2 - 20)
        txt(screen, "Click Start to play again", 18, (150, 150, 200), gw // 2, gh // 2 + 40)
        self.btn_start.draw(screen)

    def draw_paused(self):
        self.draw()
        gw, gh = screen.get_size()
        ov = pygame.Surface((gw, gh), pygame.SRCALPHA)
        ov.fill((5, 5, 20, 180)); screen.blit(ov, (0, 0))
        txt(screen, "⏸ Paused", 40, C["gold"], gw // 2, gh // 2 - 60)
        self.btn_pause_continue.draw(screen)
        self.btn_pause_restart.draw(screen)


def main():
    parser = argparse.ArgumentParser(description="Overcook-style pygame game")
    parser.add_argument("-test", action="store_true", help="Use test button labels")
    parser.add_argument("-active", action="store_true", help="Show camera feed instead of action buttons")
    args = parser.parse_args()

    ui_mode = "normal"
    if args.test:
        ui_mode = "test"
    if args.active:
        ui_mode = "active"

    game = Game(ui_mode=ui_mode)
    held      = {"left": False, "right": False}
    _gi_frame: dict = {}
    mpressed     = False
    station_click = None
    overlay_click = None

    _SLOT_KEYS = {
        pygame.K_1: 1, pygame.K_2: 2, pygame.K_3: 3,
        pygame.K_4: 4, pygame.K_5: 5,
    }

    while True:
        dt = min(clock.tick(FPS) / 1000.0, 0.05)
        _gi_frame = {}
        station_click = None
        overlay_click = None

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                game.shutdown()
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_LEFT, pygame.K_a): held["left"] = True
                if event.key in (pygame.K_RIGHT, pygame.K_d): held["right"] = True
                if event.key in _SLOT_KEYS and game.state == "play":
                    _gi_frame["move_to_slot"] = _SLOT_KEYS[event.key]
                if event.key in (pygame.K_z, pygame.K_SPACE):
                    if game.state == "play": _gi_frame["confirm"] = True
                    elif game.state in ("title", "over"):
                        game.reset(); game.state = "play"
                        game._spawn_order(); game._spawn_order()
                if event.key == pygame.K_c and game.state == "play": _gi_frame["chop"] = True
                if event.key == pygame.K_v and game.state == "play": _gi_frame["stir"] = True
                if event.key == pygame.K_g and game.state == "play": _gi_frame["put_down"] = True
                if event.key == pygame.K_r:
                    if game.state == "play":
                        game.recipe_overlay.active = not game.recipe_overlay.active
                        game.overlay.active = False
                if event.key == pygame.K_RETURN:
                    if game.state in ("title", "over"):
                        game.reset(); game.state = "play"
                        game._spawn_order(); game._spawn_order()
                if event.key == pygame.K_ESCAPE:
                    if game.recipe_overlay.active: game.recipe_overlay.active = False
                    elif game.overlay.active: game.overlay.active = False
                    elif game.state == "play": game.state = "paused"
                    elif game.state == "paused": game.state = "play"
                    else:
                        game.shutdown()
                        pygame.quit(); sys.exit()
            if event.type == pygame.KEYUP:
                if event.key in (pygame.K_LEFT, pygame.K_a): held["left"]  = False
                if event.key in (pygame.K_RIGHT, pygame.K_d): held["right"] = False
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mpressed = True
                click_pos = pygame.mouse.get_pos()
                if game.overlay.active: overlay_click = click_pos
                else: station_click = click_pos
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                mpressed = False

        move_dir = 0
        if held["left"]:    move_dir = -1
        elif held["right"]: move_dir = 1

        mpos = pygame.mouse.get_pos()
        gi = GameInput(
            move_dir     = move_dir,
            move_to_slot = _gi_frame.get("move_to_slot"),
            station_click= station_click,
            confirm      = _gi_frame.get("confirm",  False),
            chop         = _gi_frame.get("chop",     False),
            stir         = _gi_frame.get("stir",     False),
            put_down     = _gi_frame.get("put_down", False),
            overlay_click= overlay_click,
        )
        game.update(dt, gi, mpos, mpressed)

        if game.state == "title": game.draw_title()
        elif game.state == "over": game.draw_over()
        elif game.state == "paused": game.draw_paused()
        else: game.draw()

        pygame.display.flip()

if __name__ == "__main__":
    main()