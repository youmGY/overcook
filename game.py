#!/usr/bin/env python3
"""
오버쿡 스타일 요리 게임 (pygame)
실행: python game.py
설치: pip install pygame

조작: 화면 버튼 (← →  이동 | Action 버튼)
      키보드:  ← → 이동 | Z / Space = 행동
"""

import pygame
import sys
import random

from engine import screen, clock, FPS, F
from constants import C, INGS, RECIPES, BURN_TIME, COOK_TIME, ORDER_TIME, GAME_TIME
from utils import rr, txt, bar
from ui import Popup, Btn, RecipeOverlay, IngredientOverlay
from entities import Station, Player, Order


class Game:
    def __init__(self):
        self.state = "title"
        self.overlay = IngredientOverlay()
        self.recipe_overlay = RecipeOverlay()
        self._make_btns()
        self.reset()

    # ── setup ────────────────────────────────
    def reset(self):
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

        N   = 8
        pad = 20
        gap = (gw - 2 * pad - N * Station.SW) // (N - 1)
        sy  = gy - Station.SH - 36

        kinds = ["trash", "ing", "chop", "chop", "pot", "pot", "plate", "submit"]
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
        return (pad, HUD_H + pad, gw - pad * 2, station_top - HUD_H - pad * 2)

    def _make_btns(self):
        gw, gh = screen.get_size()
        gy = self._gy()
        bh = gh - gy - 20
        bw = 90
        y = gy + 10
        self.btn_left   = Btn(10,          y, bw, bh, "◀ Left",   (40, 80, 40))
        self.btn_right  = Btn(10 + bw + 8, y, bw, bh, "Right ▶",  (40, 80, 40))
        self.btn_action = Btn(gw - bw - 10,     y, bw, bh, "Action",   (80, 40, 40))
        self.btn_recipe = Btn(gw - bw * 2 - 18, y, bw, bh, "Recipe R", (50, 50, 100))
        self.btn_start  = Btn(gw // 2 - 55, gh // 2 + 70, 110, 52, "Start", (50, 50, 130))

    # ── station interaction ───────────────────
    def _near(self):
        px, py = self.player.center()
        best, bd = None, 9999
        for s in self.stations:
            d = s.dist(px, py)
            if d < 110 and d < bd:
                best, bd = s, d
        return best

    def do_action(self):
        if self.overlay.active:
            self.overlay.active = False
            return

        st = self._near()
        if not st: return
        h = self.player.holding

        if st.kind == "ing":
            if not h:
                self.overlay.active = True
            else:
                self._pop(self.player.x, self.player.y - 20, "Drop item first!", C["red"])
            return

        if st.kind == "chop":
            if h:
                base = h["id"].replace("_c", "")
                if h.get("chopped"):
                    self._pop(self.player.x, self.player.y - 20, "Already chopped", C["white"])
                    return
                if not INGS.get(base, {}).get("can_chop"):
                    self._pop(self.player.x, self.player.y - 20, "Can't chop this!", C["red"])
                    return

                if st.chop_item and st.chop_item.get("chopped"):
                    self.player.holding = dict(st.chop_item)
                    st.chop_item = None; st.chop_prog = 0.0; st.chopping = False
                    self._pop(self.player.x, self.player.y - 20, "Picked up", C["lime"])
                    return

                if st.chop_item:
                    if st.chopping:
                        self._pop(st.cx(), st.y - 14, "Wait for chopping to finish", C["orange"])
                        return
                    st.chop_item = None; st.chop_prog = 0.0; st.chopping = False

                if not st.chop_item:
                    st.chop_item = dict(h); self.player.holding = None; st.chop_prog = 0.0
                    st.chopping = True
                    self._pop(st.cx(), st.y - 14, "Chopping...", C["orange"])
            else:
                if st.chop_item and st.chop_item.get("chopped"):
                    self.player.holding = dict(st.chop_item)
                    st.chop_item = None; st.chop_prog = 0.0; st.chopping = False
                    self._pop(self.player.x, self.player.y - 20, "Picked up", C["lime"])
                elif st.chop_item and not st.chopping:
                    st.chopping = True
                    self._pop(st.cx(), st.y - 14, "Chopping...", C["orange"])
            return

        if st.kind == "pot":
            burned = st.pot_cooked and st.pot_burn >= BURN_TIME
            if h and not st.pot_cooked:
                st.pot_items.append(dict(h)); self.player.holding = None
                self._pop(st.cx(), st.y - 14, "Added ✓", C["gold"])
            elif not h and st.pot_items and not st.pot_cooking and not st.pot_cooked:
                st.pot_on = True; st.pot_cooking = True
                self._pop(st.cx(), st.y - 14, "Fire on! 🔥", C["orange"])
            elif not h and st.pot_cooked and not burned:
                self.player.holding = {
                    "id": "cooked", "label": "Cooked Dish",
                    "contents": list(st.pot_items), "cooked": True}
                st.pot_items = []; st.pot_cooked = False
                st.pot_cooking = False; st.pot_prog = 0.0
                st.pot_on = False; st.pot_burn = 0.0; st.pot_burned = False
                self._pop(self.player.x, self.player.y - 20, "Picked!", C["green"])
            elif not h and burned:
                st.pot_items = []; st.pot_cooked = False
                st.pot_cooking = False; st.pot_prog = 0.0
                st.pot_on = False; st.pot_burn = 0.0; st.pot_burned = False
                self._pop(st.cx(), st.y - 14, "Burned! Cleared.", C["burn"])
            elif not h and st.pot_cooking:
                self._pop(st.cx(), st.y - 14, "Cooking...", C["white"])
            return

        if st.kind == "plate":
            if h and h.get("cooked") and not h.get("burned"):
                if not st.plate_item:
                    st.plate_item = dict(h); self.player.holding = None
                    self._pop(st.cx(), st.y - 14, "Plated!", C["lime"])
                else:
                    self._pop(st.cx(), st.y - 14, "Plate occupied!", C["red"])
            elif h and h.get("burned"):
                self.player.holding = None
                self._pop(self.player.x, self.player.y - 20, "Burned food discarded", C["burn"])
            elif not h and st.plate_item:
                self._pop(st.cx(), st.y - 14, "Submit at Submit station!", C["white"])
            return

        if st.kind == "submit":
            plate_st = next((s for s in self.stations if s.kind == "plate" and s.plate_item), None)
            if not plate_st:
                self._pop(st.cx(), st.y - 14, "Nothing plated!", C["red"])
                return
            dish = plate_st.plate_item
            h_ids = sorted(c["id"] for c in dish["contents"])
            matched = None
            for o in self.orders:
                if o.status != "active": continue
                if sorted(o.recipe["needs"]) == h_ids:
                    matched = o; break
            if matched:
                bonus = int(matched.t / ORDER_TIME * 50)
                pts = matched.recipe["pts"] + bonus
                self.score += pts
                matched.status = "done"
                plate_st.plate_item = None
                self._pop(st.cx(), st.y - 30, f"+{pts} pts! 🎉", C["green"])
            else:
                self._pop(st.cx(), st.y - 14, "No matching order!", C["red"])
                plate_st.plate_item = None
            return

        if st.kind == "trash":
            if h:
                self.player.holding = None
                self._pop(st.cx(), st.y - 14, "Trashed!", C["pink"])
            else:
                chops = [s for s in self.stations if s.kind == "chop" and s.chop_item]
                if chops:
                    for chop in chops:
                        chop.chop_item = None; chop.chop_prog = 0.0; chop.chopping = False
                    self._pop(st.cx(), st.y - 14, "Chop boards cleared", C["pink"])
                else:
                    self._pop(st.cx(), st.y - 14, "Nothing to trash", C["white"])
            return

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

    # ── hint ─────────────────────────────────
    def _hint(self):
        if self.overlay.active:
            return "Click an ingredient card  |  ESC to cancel"
        st = self._near()
        if not st: return ""
        h = self.player.holding
        k = st.kind
        if k == "ing":
            return "Action: Open pantry" if not h else "Action: Drop item first"
        if k == "chop":
            if h and not h.get("chopped") and INGS.get(h["id"].replace("_c", ""), {}).get("can_chop"):
                return "Action: Place & chop"
            if not h and st.chop_item and st.chop_item.get("chopped"):
                return "Action: Pick chopped item"
            if not h and st.chop_item:
                return "Action: Start chopping"
        if k == "pot":
            burned = st.pot_cooked and st.pot_burn >= BURN_TIME
            if burned: return "Action: Clear burned food"
            if h and not st.pot_cooked: return "Action: Add to pot"
            if not h and st.pot_items and not st.pot_cooking and not st.pot_cooked:
                return "Action: Turn on fire 🔥"
            if not h and st.pot_cooked: return "Action: Pick cooked dish"
        if k == "plate":
            if h and h.get("cooked") and not h.get("burned"):
                return "Action: Place on plate" if not st.plate_item else "Action: Plate occupied!"
            if not h and st.plate_item:
                return "Go to Submit station to submit"
        if k == "submit":
            plate_st = next((s for s in self.stations if s.kind == "plate" and s.plate_item), None)
            return "Action: Submit dish!" if plate_st else "Action: No plated dish"
        if k == "trash":
            if h: return "Action: Trash item"
            return "Action: Clear chop boards"
        return ""

    # ── update ───────────────────────────────
    def update(self, dt, move_dir, action_now, mpos, mpressed, overlay_click):
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

        if self.overlay.active:
            if overlay_click:
                key = self.overlay.check_click(overlay_click)
                if key:
                    self._pick_ingredient(key)
                else:
                    self.overlay.active = False
            return

        if self.recipe_overlay.active:
            return

        self.btn_left.update(mpos, mpressed)
        self.btn_right.update(mpos, mpressed)
        left_held  = self.btn_left.held
        right_held = self.btn_right.held
        if self.btn_action.update(mpos, mpressed):
            action_now = True
        if self.btn_recipe.update(mpos, mpressed):
            self.recipe_overlay.active = not self.recipe_overlay.active

        if left_held:   move_dir = -1
        elif right_held: move_dir = 1

        self.player.update(move_dir, dt, gw, self._gy())
        if action_now:
            self.do_action()

        for s in self.stations:
            events = s.update(dt)
            for ev in events:
                if ev == "chop_done":
                    self._pop(s.cx(), s.y - 14, "✓ Chopped!", C["lime"])
                elif ev == "cook_done":
                    self._pop(s.cx(), s.y - 14, "✓ Cooked! Pick it up!", C["green"])
                elif ev == "burned":
                    self._pop(s.cx(), s.y - 14, "🔥 BURNED!", C["burn"])

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

    # ── draw ─────────────────────────────────
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

        for s in self.stations:
            s.draw(screen, gy)

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
            self.btn_left.draw(screen)
            self.btn_right.draw(screen)
            self.btn_action.draw(screen)

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

            if cy_ + card_h > ry + rh - 2:
                break

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
                base = need.replace("_c", "")
                ing  = INGS.get(base, {})
                col_dot = ing.get("color", (150, 150, 150))
                r_dot = 5
                dy = inner_y + r_dot
                if dot_x + r_dot * 2 + 2 > cx_ + card_w - 4:
                    break
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


# ─────────────────────────────────────────────
#  메인 루프
# ─────────────────────────────────────────────
def main():
    game = Game()

    held = {"left": False, "right": False}

    mpressed = False
    overlay_click = None

    while True:
        dt = min(clock.tick(FPS) / 1000.0, 0.05)

        action_now = False
        overlay_click = None

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_LEFT, pygame.K_a):
                    held["left"] = True
                if event.key in (pygame.K_RIGHT, pygame.K_d):
                    held["right"] = True
                if event.key in (pygame.K_z, pygame.K_SPACE):
                    if game.state == "play": action_now = True
                    elif game.state in ("title", "over"):
                        game.reset(); game.state = "play"
                        game._spawn_order(); game._spawn_order()
                if event.key == pygame.K_r:
                    if game.state == "play":
                        game.recipe_overlay.active = not game.recipe_overlay.active
                        game.overlay.active = False
                if event.key == pygame.K_RETURN:
                    if game.state in ("title", "over"):
                        game.reset(); game.state = "play"
                        game._spawn_order(); game._spawn_order()
                if event.key == pygame.K_ESCAPE:
                    if game.recipe_overlay.active:
                        game.recipe_overlay.active = False
                    elif game.overlay.active:
                        game.overlay.active = False
                    else:
                        pygame.quit(); sys.exit()
            if event.type == pygame.KEYUP:
                if event.key in (pygame.K_LEFT, pygame.K_a):   held["left"] = False
                if event.key in (pygame.K_RIGHT, pygame.K_d):  held["right"] = False
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mpressed = True
                if game.overlay.active:
                    overlay_click = pygame.mouse.get_pos()
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                mpressed = False

        move_dir = 0
        if held["left"]:   move_dir = -1
        elif held["right"]: move_dir = 1

        mpos = pygame.mouse.get_pos()
        game.update(dt, move_dir, action_now, mpos, mpressed, overlay_click)

        if game.state == "title":
            game.draw_title()
        elif game.state == "over":
            game.draw_over()
        else:
            game.draw()

        pygame.display.flip()


if __name__ == "__main__":
    main()
