"""Drawing mixin for the Game class — all rendering methods."""
from __future__ import annotations

import pygame

try:
    import cv2
except Exception:
    cv2 = None

from .engine import screen, F, get_img
from .constants import C, INGS
from .utils import rr, txt
from .entities import _load_completed_food_img


class GameDrawMixin:
    """Mixin that provides all draw/render methods for Game."""

    def _draw_camera_panel(self, pipeline_frame=None):
        if not self.use_camera_ui:
            return
        rect = self._camera_rect_from_controls()
        if rect is None:
            return

        rr(screen, (18, 20, 28), rect, 8)
        pygame.draw.rect(screen, (55, 65, 85), rect, 1, border_radius=8)

        frame_surf = self._capture_camera_surface(rect.w - 8, rect.h - 8, pipeline_frame)
        inner = pygame.Rect(rect.x + 4, rect.y + 4, rect.w - 8, rect.h - 8)
        if frame_surf:
            screen.blit(frame_surf, inner.topleft)
        else:
            pygame.draw.rect(screen, (30, 34, 48), inner, border_radius=6)
            msg = self._camera_error or "Camera not ready"
            s = F[12].render(msg, True, (190, 190, 210))
            screen.blit(s, (inner.centerx - s.get_width() // 2, inner.centery - s.get_height() // 2))

    def _capture_camera_surface(self, w: int, h: int, pipeline_frame=None):
        # Use pipeline frame if available (gesture mode shares camera)
        if pipeline_frame is not None and cv2 is not None:
            frame = cv2.cvtColor(pipeline_frame, cv2.COLOR_BGR2RGB)
        elif self._camera:
            ok, frame = self._camera.read()
            if not ok or frame is None:
                self._camera_error = "Camera frame read failed"
                return None
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame = cv2.flip(frame, 1)
        else:
            return None

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

    def draw(self, pipeline_frame=None):
        gw, gh = screen.get_size()
        gy = self._gy()

        screen.fill(C["bg"])
        if self._game_bg_img:
            bg_scaled = pygame.transform.smoothscale(self._game_bg_img, (gw, gh))
            screen.blit(bg_scaled, (0, 0))
        else:
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

        show_station_labels = self.settings_overlay.amateur_mode
        show_station_boxes = self.settings_overlay.amateur_mode
        for s in self.stations:
            s.draw(screen, gy, show_label=show_station_labels, show_box=show_station_boxes)

        # 로컬 플레이어의 overlay 상태 확인
        local_overlay_active = self._player_overlays.get(self.local_player_id, False)

        # Draw all players (multiplayer support)
        for pid, p in self.players.items():
            is_local = (pid == self.local_player_id)
            p.draw(screen, is_local=is_local)
        
        for p in self.popups: p.draw(screen)

        # 로컬 플레이어의 overlay만 표시 (멀티플레이어에서 독립적)
        if local_overlay_active:
            # Sync highlighted from per-player store so server-side swapping doesn't blank it
            self.overlay.highlighted = self._player_highlights.get(self.local_player_id)
            self.overlay.draw(screen)
        self.recipe_overlay.draw(screen)

        self._draw_hud(gw, gh)
        if not local_overlay_active and self.settings_overlay.amateur_mode:
            self._draw_recipes_panel()

        if self.state == "play":
            for btn in self.btn_acts:
                btn.draw(screen)
            self._draw_camera_panel(pipeline_frame)

        if self.state == "play":
            self._record_frame()

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

            # Completed dish thumbnail next to recipe name
            name_s = F[14].render(rec["name"], True, C["white"])
            if name_s.get_width() > card_w - 40:
                name_s = F[12].render(rec["name"], True, C["white"])
            text_h = name_s.get_height()

            dish_thumb = _load_completed_food_img(f"{rec['name']}.png", 32, 32)
            thumb_offset = 0
            if dish_thumb:
                # Crop transparent padding from the thumbnail for tighter fit
                mask = pygame.mask.from_surface(dish_thumb)
                brect = mask.get_bounding_rects()
                if brect:
                    cr = brect[0]
                    for r2 in brect[1:]:
                        cr.union_ip(r2)
                    dish_thumb = dish_thumb.subsurface(cr)
                th = dish_thumb.get_height()
                tw = dish_thumb.get_width()
                # Vertically center thumb with text
                thumb_y = inner_y + text_h // 2 - th // 2
                screen.blit(dish_thumb, (cx_ + 4, thumb_y))
                thumb_offset = tw + 4

            screen.blit(name_s, (cx_ + 4 + thumb_offset, inner_y))

            pts_s = F[12].render(f"+{rec['pts']}", True, C["gold"])
            screen.blit(pts_s, (cx_ + card_w - pts_s.get_width() - 4, inner_y))
            inner_y += max(name_s.get_height(), 20) + 2

            dot_x = cx_ + 4
            ing_size = 24
            for j, need in enumerate(rec["needs"]):
                if dot_x + ing_size + 2 > cx_ + card_w - 4:
                    break
                base = need.replace("_c", "")
                img = get_img(base, ing_size, ing_size)
                if img:
                    screen.blit(img, (dot_x, inner_y))
                else:
                    ing  = INGS.get(base, {})
                    col_dot = ing.get("color", (150, 150, 150))
                    pygame.draw.circle(screen, col_dot, (dot_x + ing_size // 2, inner_y + ing_size // 2), ing_size // 2)
                dot_x += ing_size + 6
            inner_y += ing_size + 4

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
        HH = 84
        rr(screen, C["hud_bg"], (0, 0, gw, HH), 0)
        pygame.draw.line(screen, C["hud_brd"], (0, HH), (gw, HH), 1)

        sc = F[18].render(f"Score  {self.score}", True, C["gold"])
        screen.blit(sc, (12, HH // 2 - sc.get_height() // 2))

        m = int(self.timer) // 60; s = int(self.timer) % 60
        tc = C["red"] if self.timer < 20 else C["white"]
        tm = F[24].render(f"{m}:{s:02d}", True, tc)
        screen.blit(tm, (gw // 2 - tm.get_width() // 2, HH // 2 - tm.get_height() // 2))

        ox = gw - 8
        for o in reversed([o for o in self.orders if o.status == "active"]):
            ox -= 142
            o.draw(screen, ox, 2, w=140)

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

        if self._start_btn_img:
            btn_rect = self.btn_start.rect
            btn_scaled = pygame.transform.smoothscale(self._start_btn_img, (btn_rect.width, btn_rect.height))
            screen.blit(btn_scaled, btn_rect.topleft)
        else:
            self.btn_start.draw(screen)

        if self._settings_btn_img:
            btn_rect = self.btn_settings.rect
            btn_scaled = pygame.transform.smoothscale(self._settings_btn_img, (btn_rect.width, btn_rect.height))
            screen.blit(btn_scaled, btn_rect.topleft)
        else:
            self.btn_settings.draw(screen)
        self.settings_overlay.draw(screen)

    def draw_over(self):
        self.draw()
        gw, gh = screen.get_size()
        ov = pygame.Surface((gw, gh), pygame.SRCALPHA)
        ov.fill((5, 5, 20, 210)); screen.blit(ov, (0, 0))
        txt(screen, "Game Over!", 40, C["gold"], gw // 2, gh // 2 - 80)
        txt(screen, f"{self.score} pts", 40, C["white"], gw // 2, gh // 2 - 20)
        txt(screen, "Choose next action", 18, (150, 150, 200), gw // 2, gh // 2 + 20)
        # Only show restart button to host (server)
        if self.is_server:
            self.btn_over_restart.draw(screen)
        self.btn_over_home.draw(screen)
        self._record_frame()
        if self._record_stop_after_over_draws >= 0:
            self._record_stop_after_over_draws -= 1
            if self._record_stop_after_over_draws <= 0:
                self._stop_recording("game_over_postscreen")

    def draw_paused(self):
        self.draw()
        gw, gh = screen.get_size()
        ov = pygame.Surface((gw, gh), pygame.SRCALPHA)
        ov.fill((5, 5, 20, 180)); screen.blit(ov, (0, 0))
        txt(screen, "Paused", 40, C["gold"], gw // 2, gh // 2 - 60)
        self.btn_pause_continue.draw(screen)
        self.btn_pause_restart.draw(screen)
        self.btn_pause_home.draw(screen)
        self.btn_pause_settings.draw(screen)
        rec_label, rec_col = self._record_btn_style()
        self.btn_pause_record.label = rec_label
        self.btn_pause_record.base = rec_col
        self.btn_pause_record.draw(screen)
        self.settings_overlay.draw(screen)
        self._record_frame()
