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
import os
import pygame
import sys
import random
import logging
from typing import Optional

try:
    import cv2
except Exception:
    cv2 = None

from .engine import screen, clock, FPS, F, get_img
from .constants import (
    C, INGS, ING_KEYS, RECIPES,
    BURN_TIME, ORDER_TIME, GAME_TIME, CHOP_ACTIONS, STIR_ACTIONS,
    OVER_STIR_THRESHOLD, WRONG_SUBMIT_PENALTY, INTERACTION_RANGE,
)
from .utils import rr, txt, bar
from .ui import Popup, Btn, RecipeOverlay, IngredientOverlay, SettingsOverlay
from .entities import Station, Player, Order, _load_completed_food_img
from .audio import AudioManager

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── logger ────────────────────────────────────────────────────────────────
logging.basicConfig(
    filename=os.path.join(_ROOT, "game.log"),
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
    # gesture-sourced overlay commands
    overlay_select:  Optional[int] = None  # 1-based ingredient index from finger gesture
    overlay_confirm: bool = False          # thumbs_up in overlay
    overlay_cancel:  bool = False          # ESC / cancel overlay

    def to_dict(self) -> dict:
        """Serialize for network transmission (skip local-only fields)."""
        return {
            "move_to_slot":   self.move_to_slot,
            "chop":           self.chop,
            "stir":           self.stir,
            "put_down":       self.put_down,
            "confirm":        self.confirm,
            "move_dir":       self.move_dir,
            "action":         self.action,
            "overlay_select":  self.overlay_select,
            "overlay_confirm": self.overlay_confirm,
            "overlay_cancel":  self.overlay_cancel,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GameInput":
        """Deserialize from network."""
        return cls(
            move_to_slot=d.get("move_to_slot"),
            chop=d.get("chop", False),
            stir=d.get("stir", False),
            put_down=d.get("put_down", False),
            confirm=d.get("confirm", False),
            move_dir=d.get("move_dir", 0),
            action=d.get("action", False),
            overlay_select=d.get("overlay_select"),
            overlay_confirm=d.get("overlay_confirm", False),
            overlay_cancel=d.get("overlay_cancel", False),
        )


def hand_inputs_to_game_input(
    hands,
    overlay_active: bool = False,
    thumbs_cooldown: bool = False,
) -> GameInput:
    """Convert List[HandInput] → GameInput following the gesture-action table.

    When the ingredient overlay is active, finger_N highlights an ingredient
    and thumbs_up confirms the selection.  Otherwise finger_N maps to
    move_to_slot and thumbs_up maps to confirm (station-specific action).

    thumbs_up confirm is fired as soon as the gesture is first detected
    (h.gesture == "thumbs_up"), gated by thumbs_cooldown to prevent
    re-firing while the user holds the pose.
    """
    gi = GameInput()
    for h in hands:
        if h.stale:
            continue

        # --- motion-based actions (only on actual completed strokes) ---
        if h.motion == "chop_motion" and h.motion_count > 0:
            gi.chop = True
        elif h.motion == "stir_motion" and h.motion_count > 0:
            gi.stir = True

        # --- thumbs_up: fire on first detection, not after N-frame debounce ---
        if h.gesture == "thumbs_up" and not thumbs_cooldown:
            if overlay_active:
                gi.overlay_confirm = True
            else:
                gi.confirm = True

        # --- debounced finger_N slot selection ---
        if not h.gesture_confirmed:
            continue

        if h.target_slot is not None:          # finger_1 ~ finger_5
            if overlay_active:
                gi.overlay_select = h.target_slot   # 1-based
            else:
                gi.move_to_slot = h.target_slot

    return gi


def merge_inputs(keyboard_gi: GameInput, gesture_gi: GameInput) -> GameInput:
    """OR-merge two GameInput instances (keyboard takes priority for move_to_slot)."""
    return GameInput(
        move_to_slot=keyboard_gi.move_to_slot or gesture_gi.move_to_slot,
        station_click=keyboard_gi.station_click,
        chop=keyboard_gi.chop or gesture_gi.chop,
        stir=keyboard_gi.stir or gesture_gi.stir,
        put_down=keyboard_gi.put_down or gesture_gi.put_down,
        confirm=keyboard_gi.confirm or gesture_gi.confirm,
        move_dir=keyboard_gi.move_dir or gesture_gi.move_dir,
        action=keyboard_gi.action or gesture_gi.action,
        overlay_click=keyboard_gi.overlay_click,
        overlay_select=gesture_gi.overlay_select,
        overlay_confirm=gesture_gi.overlay_confirm,
        overlay_cancel=keyboard_gi.overlay_cancel or gesture_gi.overlay_cancel,
    )


class Game:
    def __init__(
        self,
        ui_mode: str = "active",
        use_gesture: bool = False,
        flip: bool = True,
        fast_motion: bool = False,
        clahe: bool = True,
        clahe_clip: float = 2.0,
        clahe_grid: int = 8,
        device: int = 0,
        multiplayer: bool = False,
        is_server: bool = False,
        local_player_id: int = 0,
        player_name: str = "Player 1",
    ):
        self.ui_mode = ui_mode
        self.use_camera_ui = ui_mode != "test"
        self.use_gesture = use_gesture
        self._pipeline = None
        self._camera = None
        self._camera_error = None
        self._act_btn_info = self._build_act_btn_info()
        self._start_btn_img = None
        self._settings_btn_img = None
        self._load_start_btn()
        self._load_settings_btn()

        # Multiplayer fields
        self.multiplayer = multiplayer
        self.is_server = is_server
        self.local_player_id = local_player_id
        self.players: dict = {}  # pid → Player
        self._mp_player_names: dict = {}  # pid → name (from lobby)
        self._lock_modes: dict = {}  # pid → (mode, station) for multiplayer
        self._player_overlays: dict = {}  # pid → overlay active state (독립적 팬트리)
        self._station_locks: dict = {}  # station_idx → player_id (조리대 사용권)

        # Thumbs-up cooldown: True while the gesture is held to prevent re-firing
        # each frame. Resets to False when thumbs_up is no longer detected.
        self._thumbs_up_held: bool = False
        # Move-to-slot block: True for one frame after lock mode exits to prevent
        # accidental slot jumps caused by hand transitioning out of chop/stir pose.
        self._move_blocked: bool = False
        self._game_bg_img = None
        self._load_game_bg()

        if self.use_gesture:
            self._init_pipeline(
                flip,
                fast_motion=fast_motion,
                clahe=clahe,
                clahe_clip=clahe_clip,
                clahe_grid=clahe_grid,
                device=device,
            )
        elif self.use_camera_ui:
            self._init_camera()

        self.audio = AudioManager()
        self.state = "title"
        self._hurry_bgm_active = False
        self.overlay = IngredientOverlay()
        self.recipe_overlay = RecipeOverlay()
        self.settings_overlay = SettingsOverlay(self.audio)
        self._make_btns()
        # Horizontal inset from both screen edges for the station row.
        # Increase to pull left/right stations closer to the center.
        self.station_side_inset = 30
        # Additional right shift for stations except the first one (trash).
        self.station_right_shift_after_first = 19
        # Positive value moves station row downward; negative moves it upward.
        self.station_row_offset = 15
        self.reset()

    def _load_start_btn(self):
        """Load and cache the start button image."""
        try:
            _btn_path = os.path.join(_ROOT, "assets", "images", "ui", "start_btn.png")
            if not os.path.exists(_btn_path):
                return
            self._start_btn_img = pygame.image.load(_btn_path)
        except Exception as e:
            log.error("Failed to load start button: %s", e)
            self._start_btn_img = None

    def _load_settings_btn(self):
        """Load and cache the settings button image."""
        try:
            if not os.path.exists("assets/settings_btn.png"):
                return
            self._settings_btn_img = pygame.image.load("assets/settings_btn.png")
        except Exception as e:
            log.error("Failed to load settings button: %s", e)
            self._settings_btn_img = None

    def _load_game_bg(self):
        """Load and cache the in-game background image."""
        try:
            _bg_path = os.path.join(_ROOT, "assets", "game_bg.png")
            if not os.path.exists(_bg_path):
                return
            self._game_bg_img = pygame.image.load(_bg_path)
            log.info("Game background image loaded: %s", _bg_path)
        except Exception as e:
            log.error("Failed to load game background: %s", e)
            self._game_bg_img = None

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

    def _init_pipeline(
        self,
        flip: bool,
        fast_motion: bool = False,
        clahe: bool = True,
        clahe_clip: float = 2.0,
        clahe_grid: int = 8,
        device: int = 0,
    ):
        """Initialise the gesture recognition pipeline (lazy import)."""
        try:
            from .recognition.camera import CameraConfig
            from .recognition.hand_tracker import HandTrackerConfig
            from .recognition.interface import RecognitionPipeline

            fps = 60 if fast_motion else 30
            max_hands = 1 if fast_motion else 2
            min_conf = 0.15 if fast_motion else 0.2
            self._pipeline = RecognitionPipeline(
                camera_cfg=CameraConfig(device_index=device, width=640, height=480, fps=fps),
                hand_cfg=HandTrackerConfig(
                    max_num_hands=max_hands,
                    min_detection_confidence=min_conf,
                    min_tracking_confidence=min_conf,
                    detect_every_n_frames=1,
                    input_scale=1.0,
                ),
                flip=flip,
                clahe=clahe,
                clahe_clip=clahe_clip,
                clahe_grid=clahe_grid,
            )
            log.info("Gesture pipeline init: fast=%s clahe=%s device=%s", fast_motion, clahe, device)
        except Exception as e:
            log.error("Failed to init gesture pipeline: %s", e)
            self._camera_error = f"Pipeline init failed: {e}"
            self._pipeline = None

    def gesture_step(self):
        """Run one recognition step and return (List[HandInput], frame_or_None)."""
        if self._pipeline is None:
            return [], None
        hands = self._pipeline.step(draw_overlay=True)
        frame = self._pipeline.last_frame
        return hands, frame

    def shutdown(self):
        if self._pipeline:
            self._pipeline.close()
            self._pipeline = None
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
        
        # Multiplayer: create players based on _mp_player_names
        if self.multiplayer and self._mp_player_names:
            self.players = {}
            num_players = len(self._mp_player_names)
            spacing = gw // (num_players + 1)
            for i, (pid, name) in enumerate(sorted(self._mp_player_names.items())):
                px = spacing * (i + 1) - Player.PW // 2
                self.players[pid] = Player(px, gy - Player.PH, player_id=pid, name=name)
            self.player = self.players[self.local_player_id]
            self._lock_modes = {pid: None for pid in self.players}  # None = no lock, (mode, station) = locked
            self._player_overlays = {pid: False for pid in self.players}
            self._player_highlights: dict = {pid: None for pid in self.players}  # pid → overlay highlighted index
        else:
            # Solo: single player
            self.players = {0: Player(gw // 2 - Player.PW // 2, gy - Player.PH, player_id=0, name="Player 1")}
            self.player = self.players[0]
            self._player_overlays = {0: False}
            self._player_highlights = {0: None}
        
        self.overlay.active = False
        self.overlay.rebuild()
        self.recipe_overlay.active = False
        self._lock_mode = None
        self._locked_station = None
        # State-gated motion counting: per-player to avoid cross-player interference.
        self._motion_gate_ready = {"chop": False, "stir": False}
        self._motion_gates_per_player: dict = {}  # pid → {"chop": bool, "stir": bool}
        for pid in self.players:
            self._motion_gates_per_player[pid] = {"chop": False, "stir": False}
        # Station locks (멀티플레이어 조리대 선착순 사용)
        self._station_locks = {}  # station_idx → player_id
        self._server_tick_accum = 0.0

    def _gy(self):
        _, gh = screen.get_size()
        return gh - gh // 4

    def _build_level(self):
        gw, gh = screen.get_size()
        gy = self._gy()
        self.gw, self.gh = gw, gh

        N   = 5
        side_inset = int(self.station_side_inset)
        available_w = gw - 2 * side_inset
        total_station_w = N * Station.SW

        # Keep all inter-station gaps identical while preserving symmetric side margins.
        if available_w <= total_station_w:
            side_inset = max(0, (gw - total_station_w) // 2)
            gap = 0
            start_x = side_inset
        else:
            gap = (available_w - total_station_w) // (N - 1)
            used_w = total_station_w + gap * (N - 1)
            start_x = side_inset + (available_w - used_w) // 2

        # Keep station 1 fixed and move stations 2~5 to the right.
        # Clamp so the last station stays within the screen.
        max_extra_shift = max(0, gw - (start_x + (N - 1) * (Station.SW + gap) + Station.SW))
        extra_shift = max(0, min(int(self.station_right_shift_after_first), max_extra_shift))

        sy  = gy - Station.SH - int(self.station_row_offset)

        kinds = ["trash", "ing", "chop", "pot", "submit"]
        self.stations = []
        for i, k in enumerate(kinds):
            sx = start_x + i * (Station.SW + gap)
            if i > 0:
                sx += extra_shift
            self.stations.append(Station(k, sx, sy))

    def _get_station_idx(self, station) -> int:
        """Get station index from station object."""
        try:
            return self.stations.index(station)
        except ValueError:
            return -1

    def _can_use_station(self, station, player_id: int) -> bool:
        """Check if player can use this station (멀티플레이어 조리대 락 체크)."""
        if not self.multiplayer:
            return True  # Solo mode: always available
        
        st_idx = self._get_station_idx(station)
        if st_idx == -1:
            return True
        
        # Station not locked or locked by this player
        locked_by = self._station_locks.get(st_idx)
        return locked_by is None or locked_by == player_id

    def _lock_station(self, station, player_id: int):
        """Lock station for exclusive use by player."""
        if not self.multiplayer:
            return
        st_idx = self._get_station_idx(station)
        if st_idx >= 0:
            self._station_locks[st_idx] = player_id

    def _unlock_station(self, station):
        """Unlock station."""
        if not self.multiplayer:
            return
        st_idx = self._get_station_idx(station)
        if st_idx >= 0 and st_idx in self._station_locks:
            del self._station_locks[st_idx]

    def _recipe_panel_rect(self):
        gw, gh = screen.get_size()
        HUD_H = 44
        gy = self._gy()
        station_top = gy - Station.SH - int(self.station_row_offset) - 40
        pad = 8
        full_h = max(70, station_top - HUD_H - pad * 2)
        reduced_h = int(full_h * 0.82)
        return (pad, HUD_H + pad, gw - pad * 2, reduced_h)

    def _camera_rect_from_controls(self):
        return getattr(self, "_cam_slot_rect", None)

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
            btn_h   = max(50, (avail_h - gap) // 2)
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
            bh    = max(50, (gh - gy - 24) // 2 - 4)
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
        self.btn_start    = Btn(gw // 2 - 250, gh // 2 + 110, 240, 80, "Start",    (184, 101, 30))
        self.btn_settings = Btn(gw // 2 + 10,  gh // 2 + 110, 240, 80, "Settings", (55, 55, 110))
        _bw, _bh, _gap = 120, 52, 12
        _total = 4 * _bw + 3 * _gap
        _bx = gw // 2 - _total // 2
        _by = gh // 2 + 20
        self.btn_pause_continue  = Btn(_bx,                        _by, _bw, _bh, "Continue", (40, 120, 60))
        self.btn_pause_restart   = Btn(_bx + (_bw + _gap),         _by, _bw, _bh, "Restart",  (120, 50, 50))
        self.btn_pause_home      = Btn(_bx + (_bw + _gap) * 2,     _by, _bw, _bh, "Home",     (80, 60, 120))
        self.btn_pause_settings  = Btn(_bx + (_bw + _gap) * 3,     _by, _bw, _bh, "Settings", (55, 55, 110))

    def _near(self):
        px, py = self.player.center()
        best, bd = None, 9999
        for s in self.stations:
            d = s.dist(px, py)
            if d < INTERACTION_RANGE and d < bd:
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

    def _station_shortcuts_enabled(self) -> bool:
        """Enable station quick-move controls.

        Gesture mode depends on slot shortcuts (finger_1~5) for core navigation,
        so keep shortcuts enabled whenever gesture input is active.
        """
        return self.settings_overlay.amateur_mode or self.use_gesture

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
            pid = self.player.player_id
            self._player_overlays[pid] = True
            self._player_highlights[pid] = None  # reset highlight for this player
            self.overlay.highlighted = None
            # Keep overlay.active in sync for solo path and tests
            if pid == self.local_player_id:
                self.overlay.active = True
        else:
            self._pop(self.player.x, self.player.y - 20, "Drop item first!", C["red"])

    def _act_chop(self, st, chop_action=False):
        h = self.player.holding
        pid = self.player.player_id
        
        # Holding an item: place it on the chop board.
        if h:
            # Multiplayer: reject if another player is using this station.
            if not self._can_use_station(st, pid):
                locked_by = self._station_locks.get(self._get_station_idx(st))
                if locked_by is not None and locked_by in self.players:
                    other_name = self.players[locked_by].name
                    self._pop(self.player.x, self.player.y - 20, f"{other_name} is using this!", C["red"])
                else:
                    self._pop(self.player.x, self.player.y - 20, "Someone is using this!", C["red"])
                return
            
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
            # Lock station for this player
            self._lock_station(st, pid)
            
            if chop_action:
                st.chop_hits = 1
                st.chopping = True
                self._pop(st.cx(), st.y + st.h + 14, f"Chop {CHOP_ACTIONS}x ({st.chop_hits}/{CHOP_ACTIONS})", C["orange"])
                self.audio.play("chop_loop")
            else:
                st.chop_hits = 0
                st.chopping = False
                self._pop(st.cx(), st.y + st.h + 14, "Placed on board", C["lime"])
                self.audio.play("place")
            self._lock_mode = "chop"
            self._locked_station = st
            self._motion_gate_ready["chop"] = False
            return

        # Not holding anything and a chopped item is ready: pick it up.
        if (not chop_action) and st.chop_item and st.chop_item.get("chopped"):
            # Multiplayer: skip lock check — anyone can pick up a finished item.
            self.player.holding = dict(st.chop_item)
            st.chop_item = None
            st.chop_prog = 0.0
            st.chop_hits = 0
            st.chopping = False
            # Unlock station
            self._unlock_station(st)
            self._pop(self.player.x, self.player.y - 20, "Picked up", C["lime"])
            self.audio.play("pickup_done")
            return

        # chop_action: 자르기
        if chop_action and st.chop_item and not st.chop_item.get("chopped"):
            # Multiplayer: reject if another player is using this station.
            if not self._can_use_station(st, pid):
                locked_by = self._station_locks.get(self._get_station_idx(st))
                if locked_by is not None and locked_by in self.players:
                    other_name = self.players[locked_by].name
                    self._pop(self.player.x, self.player.y - 20, f"{other_name} is chopping!", C["red"])
                return
            
            st.chopping = True
            st.chop_hits = min(CHOP_ACTIONS, st.chop_hits + 1)
            st.chop_prog = st.chop_hits / float(CHOP_ACTIONS)
            self._pop(st.cx(), st.y + st.h + 14, f"Chop {CHOP_ACTIONS}x ({st.chop_hits}/{CHOP_ACTIONS})", C["orange"])
            self.audio.play("chop_loop")

    def _act_pot(self, st, stir_only=False):
        h = self.player.holding
        burned = st.pot_burned
        pid = self.player.player_id

        if stir_only:
            # Stove lock applies only while actively stirring (cooking in progress).
            # A different player can start stirring if no one is currently locked in.
            if st.pot_cooking and not self._can_use_station(st, pid):
                locked_by = self._station_locks.get(self._get_station_idx(st))
                if locked_by is not None and locked_by in self.players:
                    other_name = self.players[locked_by].name
                    self._pop(self.player.x, self.player.y - 20, f"{other_name} is stirring!", C["red"])
                return

            if h:
                self._pop(self.player.x, self.player.y - 20, "Drop item first!", C["red"])
                return
            if not st.pot_items:
                self._pop(st.cx(), st.y + st.h + 14, "Add ingredients first", C["white"])
                return
            if st.pot_burned:
                self._pop(st.cx(), st.y + st.h + 14, "Already burned! Clear it.", C["burn"])
                return
            if not st.pot_cooking and not st.pot_cooked:
                # First stir: lock station for this player's stir session
                self._lock_station(st, pid)
                st.pot_on = True
                st.pot_cooking = True
                st.pot_stirs = 0
                st.pot_prog = 0.0
                self._lock_mode = "stir"
                self._locked_station = st
                self._motion_gate_ready["stir"] = False
                self.audio.play("ignite_whoosh")
            st.pot_stirs += 1
            if st.pot_stirs >= OVER_STIR_THRESHOLD:
                st.pot_cooking = False
                st.pot_cooked = True
                st.pot_burned = True
                st.pot_burn = BURN_TIME
                self._pop(st.cx(), st.y + st.h + 14, "🔥 Over-stirred! BURNED!", C["burn"])
                log.warning("POT_BURNED: over-stirred")
                self.audio.play("sizzle_burn")
                return
            st.pot_prog = min(1.0, st.pot_stirs / float(STIR_ACTIONS))
            self._pop(st.cx(), st.y + st.h + 14, f"Stir {STIR_ACTIONS}x ({st.pot_stirs}/{STIR_ACTIONS})", C["orange"])
            self.audio.play("sizzle_loop")
            return

        if h and h.get("cooked"):
            self._pop(self.player.x, self.player.y - 20, "Can't add cooked dish!", C["red"])
        elif h and not st.pot_cooked:
            # Anyone can add ingredients as long as cooking hasn't started yet.
            if st.pot_cooking:
                self._pop(self.player.x, self.player.y - 20, "Already cooking! Wait.", C["orange"])
                return

            base = h.get("id", "").replace("_c", "")
            if INGS.get(base, {}).get("can_chop") and not h.get("chopped"):
                self._pop(self.player.x, self.player.y - 20, "Chop it first!", C["red"])
            else:
                st.pot_items.append(dict(h))
                self.player.holding = None
                self._pop(st.cx(), st.y + st.h + 14, "Added", C["gold"])
                self.audio.play("splash")
        elif not h and st.pot_cooked and not burned:
            # 완성품 픽업: unlock station
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
            self._unlock_station(st)
            self._pop(self.player.x, self.player.y - 20, "Picked!", C["green"])
            self.audio.play("plate_ding")
        elif not h and burned:
            # 탄 음식 픽업: unlock station
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
            self._unlock_station(st)
            self._pop(self.player.x, self.player.y - 20, "Picked burned dish!", C["burn"])
            self.audio.play("burn_puff")
        elif not h and st.pot_cooking:
            self._pop(st.cx(), st.y + st.h + 14, f"Stir {STIR_ACTIONS}x ({st.pot_stirs}/{STIR_ACTIONS})", C["white"])

    def _act_submit(self, st):
        dish, from_holding = self._find_submit_dish()
        if not dish:
            self._pop(st.cx(), st.y + st.h + 14, "Nothing to submit!", C["red"])
            return

        contents = dish.get("contents", [])
        h_ids = sorted(c.get("id") for c in contents if isinstance(c, dict) and c.get("id"))
        if len(h_ids) != len(contents):
            self._pop(st.cx(), st.y + st.h + 14, "Invalid dish: missing ingredient id", C["red"])
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
                self.audio.play("fail_buzz")
            else:
                bonus = int(matched.t / ORDER_TIME * 50)
                pts = matched.recipe["pts"] + bonus
                self.score += pts
                matched.status = "done"
                self._clear_submit_source(from_holding)
                self._pop(st.cx(), st.y - 30, f"+{pts} pts! 🎉", C["green"])
                self.audio.play("serve_chaching")
        else:
            penalty = WRONG_SUBMIT_PENALTY
            self.score = max(0, self.score - penalty)
            self._pop(st.cx(), st.y + st.h + 14, f"No order! -{penalty} pts", C["red"])
            self._clear_submit_source(from_holding)
            self.audio.play("wrong_buzz")

    def _act_trash(self, st):
        h = self.player.holding
        if h:
            self.player.holding = None
            self._pop(st.cx(), st.y + st.h + 14, "Trashed!", C["pink"])
            self.audio.play("trash_thud")
            return

        # No item held — clear the nearest occupied chop board only.
        px, py = self.player.center()
        chops = [s for s in self.stations if s.kind == "chop" and s.chop_item]
        if chops:
            nearest = min(chops, key=lambda s: s.dist(px, py))
            nearest.chop_item = None
            nearest.chop_prog = 0.0
            nearest.chop_hits = 0
            nearest.chopping = False
            self._unlock_station(nearest)
            self._pop(st.cx(), st.y + st.h + 14, "Chop board cleared", C["pink"])
        else:
            self._pop(st.cx(), st.y + st.h + 14, "Nothing to trash", C["white"])

    def do_action(self):
        # Close active overlay for this player before doing a station action.
        pid = self.player.player_id
        if self._player_overlays.get(pid, False):
            self._player_overlays[pid] = False
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
        # 플레이어별 독립적인 overlay 상태 사용 (self.overlay.active는 사용하지 않음)
        pid = self.player.player_id
        self._player_overlays[pid] = False
        self.audio.play("pickup")

    def _pop(self, x, y, msg, col):
        self.popups.append(Popup(x, y, msg, col))

    def _start_game_session(self):
        """Reset state, spawn initial orders, and start the game BGM."""
        self.reset()
        self.state = "play"
        self._spawn_order()
        self._spawn_order()
        self.audio.play("start_whistle")
        self.audio.play_bgm("play_loop")
        self._hurry_bgm_active = False

    def _spawn_order(self):
        active = sum(1 for o in self.orders if o.status == "active")
        if active >= 3: return
        self.orders.append(Order(random.choice(RECIPES)))
        self.audio.play("order_bell")

    def _hint(self):
        if self._lock_mode == "chop" and self._locked_station:
            st = self._locked_station
            return f"Chopping! Press Chop ({st.chop_hits}/{CHOP_ACTIONS})"
        if self._lock_mode == "stir" and self._locked_station:
            st = self._locked_station
            return f"Stirring! Press Stir ({st.pot_stirs}/{STIR_ACTIONS})"
        # 로컬 플레이어의 overlay 상태 확인
        local_overlay_active = self._player_overlays.get(self.local_player_id, False)
        if local_overlay_active: 
            return "Click an ingredient card  |  ESC to cancel"
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
                return f"Stir to start cooking! (max {OVER_STIR_THRESHOLD - 1} stirs)"
            if not h and st.pot_cooked: return "Action: Pick cooked dish"
            if not h and st.pot_cooking: return f"Stir button: {st.pot_stirs}/{STIR_ACTIONS} (burn at {OVER_STIR_THRESHOLD})"
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

    def update_ui_buttons(self, mpos, mpressed) -> dict:
        """Poll all action buttons and return a dict of triggered actions.

        This is called by both the solo loop (inside update()) and the
        multiplayer loop so that ChopChop / StirStir / Pause / OK buttons
        work regardless of whether game.update() or server_tick() drives
        the game state.

        Returns a dict with bool values keyed by action name:
        ``{"confirm": bool, "chop": bool, "stir": bool, "pause": bool}``
        """
        triggered: dict = {k: False for k in self.btn_acts_map}
        for key, btn in self.btn_acts_map.items():
            if btn.update(mpos, mpressed):
                triggered[key] = True
        return triggered

    def update(self, dt, gi: "GameInput", mpos, mpressed):
        gw, gh = screen.get_size()
        if gw != self.gw or gh != self.gh:
            self.gw, self.gh = gw, gh
            self._build_level(); self._make_btns()
            self.overlay.rebuild()

        # 로컬 플레이어의 overlay 상태를 self.overlay.active에 동기화 (기존 코드와 호환)
        local_overlay_active = self._player_overlays.get(self.local_player_id, False)
        self.overlay.active = local_overlay_active

        if self.state in ("title", "over"):
            if self.settings_overlay.active:
                return
            if self.state == "title" and self.btn_settings.update(mpos, mpressed):
                self.settings_overlay.active = True
                self.audio.play("ui_click")
                return
            if self.btn_start.update(mpos, mpressed):
                self._start_game_session()
                self.audio.play("ui_click")
            return

        if self.state == "paused":
            if self.settings_overlay.active:
                return
            if self.btn_pause_continue.update(mpos, mpressed):
                self.state = "play"
                self.audio.play("ui_resume")
                self.audio.unpause_bgm()
            if self.btn_pause_restart.update(mpos, mpressed):
                self._start_game_session()
                self.audio.play("ui_click")
            if self.btn_pause_home.update(mpos, mpressed):
                self.audio.stop_bgm()
                self.audio.play_bgm("intro_bgm")
                self.state = "title"
                self.audio.play("ui_click")
            if self.btn_pause_settings.update(mpos, mpressed):
                self.settings_overlay.active = True
                self.audio.play("ui_click")
            return

        # Solo: handle local overlay (pantry ingredient selection)
        # In multiplayer, this path is not taken — use _process_single_input via server_tick instead.
        local_overlay_active = self._player_overlays.get(self.local_player_id, False)
        if local_overlay_active:
            if gi.overlay_cancel:
                self._player_overlays[self.local_player_id] = False
                self.overlay.highlighted = None
                self._player_highlights[self.local_player_id] = None
                return
            if gi.overlay_click:
                key = self.overlay.check_click(gi.overlay_click)
                if key:
                    self._pick_ingredient(key)
                else:
                    self._player_overlays[self.local_player_id] = False
                    self.overlay.highlighted = None
                    self._player_highlights[self.local_player_id] = None
            if gi.overlay_select is not None:
                self.overlay.highlight_by_index(gi.overlay_select - 1)  # 1-based → 0-based
                self._player_highlights[self.local_player_id] = self.overlay.highlighted
            if gi.overlay_confirm:
                key = self.overlay.confirm_highlighted()
                if key:
                    self._pick_ingredient(key)
                else:
                    self._player_overlays[self.local_player_id] = False
                    self.overlay.highlighted = None
                    self._player_highlights[self.local_player_id] = None
            return

        if self.recipe_overlay.active: return

        # Tick stations first so completion state (chopped/cooked) is up-to-date
        # before we evaluate lock-mode exit and process this frame's input.
        station_events = []
        for s in self.stations:
            station_events.extend((s, ev) for ev in s.update(dt))

        if self._lock_mode:
            # While action mode is locked, still allow movement controls.
            btn_triggered = self.update_ui_buttons(mpos, mpressed)
            act_flags = {
                "confirm": gi.confirm or gi.action or btn_triggered.get("confirm", False),
                "chop": gi.chop or btn_triggered.get("chop", False),
                "stir": gi.stir or btn_triggered.get("stir", False),
                "pause": btn_triggered.get("pause", False),
            }
            if act_flags["pause"]:
                self.state = "paused"
                self.audio.play("ui_pause")
                self.audio.pause_bgm()
                return

            # Prevent all movement during chopping/stirring
            if self._lock_mode in ("chop", "stir"):
                move_dir = 0
            else:
                move_to_slot = gi.move_to_slot if self._station_shortcuts_enabled() else None
                clicked_station = self._station_at_point(gi.station_click) if self._station_shortcuts_enabled() else None
                if clicked_station:
                    self.player.x = float(clicked_station.cx() - Player.PW // 2)
                    self.player.y = float(self._gy() - Player.PH)
                    self.player.vy = 0.0

                move_dir = gi.move_dir
                if move_to_slot is not None:
                    target = self._station_for_slot(move_to_slot)
                    if target:
                        self.player.x = float(target.cx() - Player.PW // 2)
                        self.player.y = float(self._gy() - Player.PH)
                        self.player.vy = 0.0

            self.player.update(move_dir, dt, gw, self._gy())

            st = self._locked_station
            px, py = self.player.center()
            in_lock_range = bool(st and st.dist(px, py) < INTERACTION_RANGE)

            # Allow thumbs_up/confirm interactions even while lock mode is active.
            if act_flags["confirm"] and st:
                if self._lock_mode == "chop":
                    self._act_chop(st, chop_action=False)
                elif self._lock_mode == "stir":
                    self._act_pot(st, stir_only=False)

            # Arm counting only after first neutral frame post lock-entry.
            if self._lock_mode == "chop" and not gi.chop:
                self._motion_gate_ready["chop"] = True
            elif self._lock_mode == "stir" and not gi.stir:
                self._motion_gate_ready["stir"] = True

            if (
                self._lock_mode == "chop"
                and act_flags["chop"]
                and st
                and in_lock_range
                and not act_flags["confirm"]
            ):
                # Ignore stale gesture pulse that existed before lock started.
                if gi.chop and not self._motion_gate_ready["chop"]:
                    pass
                elif self._near() is st:
                    self._act_chop(st, chop_action=True)
            elif (
                self._lock_mode == "stir"
                and act_flags["stir"]
                and st
                and in_lock_range
                and not act_flags["confirm"]
            ):
                if gi.stir and not self._motion_gate_ready["stir"]:
                    pass
                elif self._near() is st:
                    self._act_pot(st, stir_only=True)
            # Unlock when done
            if self._lock_mode == "chop" and (not st or not st.chop_item or st.chop_item.get("chopped")):
                self._lock_mode = None
                self._locked_station = None
                self._motion_gate_ready["chop"] = False
                # Block thumbs_up and move_to_slot for the next frame so a
                # post-chop hand transition doesn't fire unintended actions.
                self._thumbs_up_held = True
                self._move_blocked = True
            elif self._lock_mode == "stir" and st and (
                st.pot_cooked
                or st.pot_burned
                or (not st.pot_cooking and not st.pot_items)
            ):
                self._lock_mode = None
                self._locked_station = None
                self._motion_gate_ready["stir"] = False
                # Same post-stir guard.
                self._thumbs_up_held = True
                self._move_blocked = True
        else:
            move_to_slot = gi.move_to_slot if self._station_shortcuts_enabled() else None
            clicked_station = self._station_at_point(gi.station_click) if self._station_shortcuts_enabled() else None
            if clicked_station:
                self.player.x = float(clicked_station.cx() - Player.PW // 2)
                self.player.y = float(self._gy() - Player.PH)
                self.player.vy = 0.0

            btn_triggered = self.update_ui_buttons(mpos, mpressed)
            act_flags = {
                "confirm":  gi.confirm  or gi.action or btn_triggered.get("confirm", False),
                "chop":     gi.chop     or btn_triggered.get("chop", False),
                "stir":     gi.stir     or btn_triggered.get("stir", False),
                "pause":    btn_triggered.get("pause", False),
            }

            if act_flags["pause"]:
                self.state = "paused"
                self.audio.play("ui_pause")
                self.audio.pause_bgm()
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

        # Emit audio/popup for station events collected at the top of this frame
        for s, ev in station_events:
            if ev == "chop_done":
                self._pop(s.cx(), s.y - 14, "Chopped!", C["lime"])
                self.audio.play("chop_done")
            elif ev == "cook_done":
                self._pop(s.cx(), s.y - 14, "Cooked! Pick it up!", C["green"])
                self.audio.play("cook_done")
            elif ev == "burned":
                self._pop(s.cx(), s.y - 14, "BURNED!", C["burn"])
                self.audio.play("burn_alarm")

        for o in self.orders:
            ev = o.update(dt)
            if ev == "failed":
                self.score = max(0, self.score - WRONG_SUBMIT_PENALTY)
                self._pop(gw // 2, gh // 2 - 80, f"Order failed! -{WRONG_SUBMIT_PENALTY}", C["red"])
                self.audio.play("fail_wah")

        self.elapsed += dt
        if self.elapsed >= self.next_order:
            self._spawn_order()
            order_interval = 10.0 if self.multiplayer else 15.0
            self.next_order = self.elapsed + order_interval

        self.timer = max(0.0, self.timer - dt)
        if self.timer <= 0:
            self.state = "over"
            if self.score > 0:
                self.audio.play("fanfare_win")
                self.audio.play_bgm("result_win", loops=0)
            else:
                self.audio.play("fail_wah")
                self.audio.play_bgm("result_lose", loops=0)
        elif self.timer < 20 and not self._hurry_bgm_active:
            self._hurry_bgm_active = True
            self.audio.play("tick_tock")
            self.audio.play_bgm("play_hurry_loop")

        for p in self.popups: p.update()
        self.popups = [p for p in self.popups if not p.dead]

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
        txt(screen, "Click Start to play again", 18, (150, 150, 200), gw // 2, gh // 2 + 40)
        self.btn_start.draw(screen)

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
        self.settings_overlay.draw(screen)

    # ── Multiplayer Methods ───────────────────────────────────────────

    def set_mp_player_names(self, player_names: dict):
        """Set player names from lobby (pid → name)."""
        self._mp_player_names = player_names

    def process_input_for_player(self, pid: int, gi: GameInput, dt: float):
        """Server: process input for a specific player (swaps self.player temporarily)."""
        if pid not in self.players:
            return

        saved_player = self.player
        saved_lock_mode = self._lock_mode
        saved_locked_station = self._locked_station
        saved_motion_gate = self._motion_gate_ready.copy()
        saved_overlay_highlighted = self.overlay.highlighted

        try:
            self.player = self.players[pid]

            # Restore per-player lock state
            lock_entry = self._lock_modes.get(pid)
            if lock_entry:
                self._lock_mode, self._locked_station = lock_entry
            else:
                self._lock_mode = None
                self._locked_station = None

            # Restore per-player motion gate
            self._motion_gate_ready = self._motion_gates_per_player.get(
                pid, {"chop": False, "stir": False}
            ).copy()

            # Restore per-player overlay highlight so players don't bleed into each other
            self.overlay.highlighted = self._player_highlights.get(pid)

            self._process_single_input(gi, dt)

            # Persist per-player state after processing
            self._lock_modes[pid] = (self._lock_mode, self._locked_station)
            self._motion_gates_per_player[pid] = self._motion_gate_ready.copy()
            self._player_highlights[pid] = self.overlay.highlighted
        finally:
            # Always restore global overlay/player context
            self.player = saved_player
            self._lock_mode = saved_lock_mode
            self._locked_station = saved_locked_station
            self._motion_gate_ready = saved_motion_gate
            self.overlay.highlighted = saved_overlay_highlighted

    def _process_single_input(self, gi: GameInput, dt: float):
        """Process input for current self.player (extracted for multiplayer reuse)."""
        gw, gh = screen.get_size()
        
        # Process per-player overlay (pantry ingredient selection)
        pid = self.player.player_id
        player_overlay_active = self._player_overlays.get(pid, False)

        if player_overlay_active:
            if gi.overlay_cancel:
                self._player_overlays[pid] = False
                self.overlay.highlighted = None
                return
            if gi.overlay_click:
                key = self.overlay.check_click(gi.overlay_click)
                if key:
                    self._pick_ingredient(key)
                else:
                    self._player_overlays[pid] = False
                    self.overlay.highlighted = None
            if gi.overlay_select is not None:
                self.overlay.highlight_by_index(gi.overlay_select - 1)
            if gi.overlay_confirm:
                key = self.overlay.confirm_highlighted()
                if key:
                    self._pick_ingredient(key)
                else:
                    self._player_overlays[pid] = False
                    self.overlay.highlighted = None
            return

        if self._lock_mode:
            st = self._locked_station
            # Fix M3: mirror update() — gate per current lock mode only
            if self._lock_mode == "chop" and not gi.chop:
                self._motion_gate_ready["chop"] = True
            elif self._lock_mode == "stir" and not gi.stir:
                self._motion_gate_ready["stir"] = True

            if self._lock_mode == "chop" and gi.chop and st:
                if not self._motion_gate_ready["chop"]:
                    pass
                else:
                    self._act_chop(st, chop_action=True)
            elif self._lock_mode == "stir" and gi.stir and st:
                if not self._motion_gate_ready["stir"]:
                    pass
                else:
                    self._act_pot(st, stir_only=True)

            # Fix H5: confirm while locked picks up the finished item
            if (gi.confirm or gi.action) and st:
                if self._lock_mode == "chop":
                    self._act_chop(st, chop_action=False)
                elif self._lock_mode == "stir":
                    self._act_pot(st, stir_only=False)

            if self._lock_mode == "chop" and (not st or not st.chop_item or st.chop_item.get("chopped")):
                self._lock_mode = None
                self._locked_station = None
                self._motion_gate_ready["chop"] = False
            elif self._lock_mode == "stir" and st and (
                st.pot_cooked
                or st.pot_burned
                or (not st.pot_cooking and not st.pot_items)  # Fix M4
            ):
                self._lock_mode = None
                self._locked_station = None
                self._motion_gate_ready["stir"] = False

            # Fix H4: always run player physics so gravity/grounding work while locked
            self.player.update(0, dt, gw, self._gy())
        else:
            move_to_slot = gi.move_to_slot if self._station_shortcuts_enabled() else None
            clicked_station = self._station_at_point(gi.station_click) if self._station_shortcuts_enabled() else None
            if clicked_station:
                self.player.x = float(clicked_station.cx() - Player.PW // 2)
                self.player.y = float(self._gy() - Player.PH)
                self.player.vy = 0.0

            move_dir = gi.move_dir
            if move_to_slot is not None:
                target = self._station_for_slot(move_to_slot)
                if target:
                    self.player.x = float(target.cx() - Player.PW // 2)
                    self.player.y = float(self._gy() - Player.PH)
                    self.player.vy = 0.0

            self.player.update(move_dir, dt, gw, self._gy())

            handled = False
            if gi.chop:
                st = self._near()
                if st and st.kind == "chop":
                    self._act_chop(st, chop_action=True)
                    handled = True
            if gi.stir and not handled:
                st = self._near()
                if st and st.kind == "pot":
                    self._act_pot(st, stir_only=True)
                    handled = True
            if (gi.confirm or gi.action) and not handled:
                self.do_action()

    def server_tick(self, dt: float, all_inputs: dict):
        """Server: process one game tick with inputs from all players."""
        if self.state != "play":  # H2: freeze when paused or over
            return

        # Process each player's input
        for pid, inp_dict in all_inputs.items():
            gi = GameInput.from_dict(inp_dict)
            self.process_input_for_player(pid, gi, dt)

        # Update stations
        for s in self.stations:
            events = s.update(dt)
            for ev in events:
                if ev == "chop_done":
                    self._pop(s.cx(), s.y - 14, "Chopped!", C["lime"])
                    self.audio.play("chop_done")
                elif ev == "cook_done":
                    self._pop(s.cx(), s.y - 14, "Cooked! Pick it up!", C["green"])
                    self.audio.play("cook_done")
                elif ev == "burned":
                    self._pop(s.cx(), s.y - 14, "BURNED!", C["burn"])
                    self.audio.play("burn_alarm")

        # Update orders
        gw, gh = screen.get_size()
        for o in self.orders:
            ev = o.update(dt)
            if ev == "failed":
                self.score = max(0, self.score - WRONG_SUBMIT_PENALTY)
                self._pop(gw // 2, gh // 2 - 80, f"Order failed! -{WRONG_SUBMIT_PENALTY}", C["red"])
                self.audio.play("fail_wah")

        # Spawn orders
        self.elapsed += dt
        if self.elapsed >= self.next_order:
            self._spawn_order()
            order_interval = 10.0 if self.multiplayer else 15.0
            self.next_order = self.elapsed + order_interval

        # Timer
        self.timer = max(0.0, self.timer - dt)
        if self.timer <= 0:
            self.state = "over"
            # M2: play win/lose fanfare and result BGM
            if self.score >= 100:
                self.audio.play("fanfare_win")
                self.audio.play_bgm("result_win", loops=0)
            else:
                self.audio.play("fail_wah")
                self.audio.play_bgm("result_lose", loops=0)
        elif self.timer < 20 and not self._hurry_bgm_active:
            # M2: hurry BGM when under 20 s
            self._hurry_bgm_active = True
            self.audio.play("tick_tock")
            self.audio.play_bgm("play_hurry_loop")

        # Update popups
        for p in self.popups:
            p.update()
        self.popups = [p for p in self.popups if not p.dead]

    def serialize_state(self) -> dict:
        """Serialize full game state for network broadcast."""
        return {
            "score": self.score,
            "timer": self.timer,
            "elapsed": self.elapsed,
            "next_order": self.next_order,
            "state": self.state,
            "players": {str(pid): p.to_dict() for pid, p in self.players.items()},
            "stations": [s.to_dict() for s in self.stations],
            "orders": [o.to_dict() for o in self.orders],
            # Per-player UI state that clients need to render correctly
            "player_overlays":   {str(pid): v for pid, v in self._player_overlays.items()},
            "player_highlights": {str(pid): v for pid, v in self._player_highlights.items()},
            "station_locks":     {str(k): v for k, v in self._station_locks.items()},
            # H6: sync popup feedback to all clients
            "popups": [
                {"x": p.x, "y": p.y, "msg": p.msg,
                 "color": list(p.color), "life": p.life}
                for p in self.popups
            ],
        }

    def apply_state(self, state: dict):
        """Client: apply server state snapshot."""
        self.score = state.get("score", self.score)
        self.timer = state.get("timer", self.timer)
        self.elapsed = state.get("elapsed", self.elapsed)
        self.next_order = state.get("next_order", self.next_order)
        self.state = state.get("state", self.state)

        # Players
        for pid_str, pdata in state.get("players", {}).items():
            pid = int(pid_str)
            if pid not in self.players:
                name = pdata.get("name", f"Player {pid + 1}")
                self.players[pid] = Player(0, 0, player_id=pid, name=name)
            self.players[pid].apply_dict(pdata)

        # Remove disconnected players
        server_pids = {int(k) for k in state.get("players", {}).keys()}
        for pid in list(self.players.keys()):
            if pid not in server_pids:
                del self.players[pid]

        # Stations
        for i, sdata in enumerate(state.get("stations", [])):
            if i < len(self.stations):
                self.stations[i].apply_dict(sdata)

        # Orders
        server_orders = state.get("orders", [])
        server_ids = {o["id"] for o in server_orders}

        for odata in server_orders:
            oid = odata["id"]
            existing = next((o for o in self.orders if o.id == oid), None)
            if existing:
                existing.apply_dict(odata)
            else:
                recipe_name = odata.get("recipe_name")
                recipe = next((r for r in RECIPES if r["name"] == recipe_name), None)
                if recipe:
                    new_order = Order(recipe)
                    new_order.id = oid
                    new_order.apply_dict(odata)
                    self.orders.append(new_order)

        self.orders = [o for o in self.orders if o.id in server_ids]

        # Sync per-player overlay state so each client renders its own overlay correctly
        for pid_str, active in state.get("player_overlays", {}).items():
            pid = int(pid_str)
            self._player_overlays[pid] = active

        # Sync per-player highlight index (gesture hover state)
        for pid_str, hi in state.get("player_highlights", {}).items():
            pid = int(pid_str)
            self._player_highlights[pid] = hi

        # Sync station locks so clients can show "X is using this!" messages
        self._station_locks = {
            int(k): v for k, v in state.get("station_locks", {}).items()
        }

        # H6: sync popups from server so client sees feedback messages
        # Replace the entire list each frame so life values stay in sync and
        # popups that expired on the server are removed on the client too.
        if "popups" in state:
            self.popups = []
            for d in state["popups"]:
                p = Popup(d["x"], d["y"], d["msg"], tuple(d["color"]))
                p.life = d["life"]
                self.popups.append(p)

        # Keep local overlay object in sync with this client's overlay/highlight state
        local_active = self._player_overlays.get(self.local_player_id, False)
        self.overlay.active = local_active
        if local_active:
            self.overlay.highlighted = self._player_highlights.get(self.local_player_id)
        else:
            self.overlay.highlighted = None

        # Keep self.player reference pointing to the local player object
        if self.local_player_id in self.players:
            self.player = self.players[self.local_player_id]


def main():
    parser = argparse.ArgumentParser(description="Overcook-style pygame game")
    parser.add_argument("-test", action="store_true", help="Use test button labels")
    parser.add_argument("-active", action="store_true", help="Show camera feed instead of action buttons")
    parser.add_argument("--gesture", action="store_true",
                        help="Enable gesture recognition input (camera + hand tracking)")
    parser.add_argument("--flip", dest="flip", action="store_true", default=True,
                        help="Mirror camera horizontally (default: on)")
    parser.add_argument("--no-flip", dest="flip", action="store_false",
                        help="Disable camera mirroring")
    parser.add_argument("--fast-motion", action="store_true",
                        help="Fast-motion preset for rapid chop/stir capture")
    parser.add_argument("--clahe", dest="clahe", action="store_true", default=True,
                        help="Enable CLAHE brightness normalization (default: on)")
    parser.add_argument("--no-clahe", dest="clahe", action="store_false",
                        help="Disable CLAHE brightness normalization")
    parser.add_argument("--clahe-clip", type=float, default=2.0,
                        help="CLAHE clip limit (default: 2.0)")
    parser.add_argument("--clahe-grid", type=int, default=8,
                        help="CLAHE tile grid size (default: 8)")
    parser.add_argument("--device", type=int, default=0,
                        help="Camera device index (default: 0)")
    parser.add_argument("--multiplayer", action="store_true", default=True,
                        dest="multiplayer",
                        help="Enable multiplayer mode (LAN lobby) [default: True]")
    parser.add_argument("--single", action="store_true",
                        help="Play in single player mode instead of multiplayer")
    parser.add_argument("--name", type=str, default="Player",
                        help="Player name for multiplayer")
    args = parser.parse_args()

    ui_mode = "normal"
    if args.test:
        ui_mode = "test"
    if args.active or args.gesture:
        ui_mode = "active"

    # If --single flag is set, use single player mode; otherwise use multiplayer (default)
    if args.single:
        _main_single(ui_mode, args)
    else:
        _main_multiplayer(ui_mode, args)


def _main_single(ui_mode: str, args):
    """Single player game loop."""
    game = Game(
        ui_mode=ui_mode,
        use_gesture=args.gesture,
        flip=args.flip,
        fast_motion=args.fast_motion,
        clahe=args.clahe,
        clahe_clip=args.clahe_clip,
        clahe_grid=args.clahe_grid,
        device=args.device,
    )
    game._start_game_session()
    held      = {"left": False, "right": False}
    _gi_frame: dict = {}
    mpressed     = False
    _click_this_frame = False  # True if MOUSEDOWN occurred this frame (before gesture step)
    station_click = None
    overlay_click = None
    pipeline_frame = None

    _SLOT_KEYS = {
        pygame.K_1: 1, pygame.K_2: 2, pygame.K_3: 3,
        pygame.K_4: 4, pygame.K_5: 5,
    }

    while True:
        dt = min(clock.tick(FPS) / 1000.0, 0.05)
        _gi_frame = {}
        station_click = None
        overlay_click = None
        pipeline_frame = None
        _click_this_frame = False  # reset each frame

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                game.shutdown()
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_LEFT, pygame.K_a): held["left"] = True
                if event.key in (pygame.K_RIGHT, pygame.K_d): held["right"] = True
                if event.key in _SLOT_KEYS and game.state == "play" and game._station_shortcuts_enabled():
                    _gi_frame["move_to_slot"] = _SLOT_KEYS[event.key]
                if event.key in (pygame.K_z, pygame.K_SPACE):
                    if game.state == "play": _gi_frame["confirm"] = True
                    elif game.state in ("title", "over"):
                        game._start_game_session()
                if event.key == pygame.K_c and game.state == "play": _gi_frame["chop"] = True
                if event.key == pygame.K_v and game.state == "play": _gi_frame["stir"] = True
                if event.key == pygame.K_g and game.state == "play": _gi_frame["put_down"] = True
                if event.key == pygame.K_r:
                    if game.state == "play":
                        game.recipe_overlay.active = not game.recipe_overlay.active
                        game._player_overlays[game.local_player_id] = False
                        game.audio.play("page_flip")
                if event.key == pygame.K_RETURN:
                    if game.state in ("title", "over"):
                        game._start_game_session()
                if event.key == pygame.K_ESCAPE:
                    if game.recipe_overlay.active:
                        game.recipe_overlay.active = False
                        game.audio.play("page_flip")
                    elif game._player_overlays.get(game.local_player_id, False):
                        # overlay_cancel is propagated through GameInput so the server
                        # also closes this player's overlay authoritatively
                        _gi_frame["overlay_cancel"] = True
                    elif game.state == "play":
                        game.state = "paused"
                        game.audio.play("ui_pause")
                        game.audio.pause_bgm()
                    elif game.state == "paused":
                        game.state = "play"
                        game.audio.play("ui_resume")
                        game.audio.unpause_bgm()
                    else:
                        game.shutdown()
                        pygame.quit(); sys.exit()
            if event.type == pygame.KEYUP:
                if event.key in (pygame.K_LEFT, pygame.K_a): held["left"]  = False
                if event.key in (pygame.K_RIGHT, pygame.K_d): held["right"] = False
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mpressed = True
                _click_this_frame = True
                click_pos = pygame.mouse.get_pos()
                if game.settings_overlay.handle_mousedown(click_pos):
                    pass  # consumed by settings overlay
                elif game._player_overlays.get(game.local_player_id, False):
                    overlay_click = click_pos
                elif game._station_shortcuts_enabled():
                    station_click = click_pos
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                mpressed = False
                game.settings_overlay.handle_mouseup(event.pos)
            if event.type == pygame.MOUSEMOTION:
                game.settings_overlay.handle_mousemove(event.pos)

        mpos = pygame.mouse.get_pos()
        gi, pipeline_frame = _collect_local_input(
            game, held, _gi_frame, station_click, overlay_click
        )
        game.update(dt, gi, mpos, _click_this_frame or mpressed)

        if game.state == "title":
            game.shutdown()
            return  # return to lobby
        elif game.state == "over": game.draw_over()
        elif game.state == "paused": game.draw_paused()
        else: game.draw(pipeline_frame)

        pygame.display.flip()


def _collect_local_input(game, held, _gi_frame, station_click, overlay_click) -> tuple:
    """Collect gesture + keyboard input for the local player. Returns (GameInput, frame)."""
    pipeline_frame = None
    gesture_gi = GameInput()
    if game.use_gesture:
        hand_inputs, pipeline_frame = game.gesture_step()
        if hand_inputs:
            local_overlay = game._player_overlays.get(game.local_player_id, False)
            # Detect whether ANY hand currently shows thumbs_up (for cooldown logic)
            any_thumbs_up = any(
                h.gesture == "thumbs_up" for h in hand_inputs if not h.stale
            )
            gesture_gi = hand_inputs_to_game_input(
                hand_inputs,
                overlay_active=local_overlay,
                thumbs_cooldown=game._thumbs_up_held,
            )
            # If move is blocked (just exited lock mode), suppress slot movement
            if game._move_blocked:
                gesture_gi.move_to_slot = None
                game._move_blocked = False
            # Station quick-slot gesture is an amateur-mode-only control.
            if not game._station_shortcuts_enabled():
                gesture_gi.move_to_slot = None
            # Update held state: reset when thumbs_up is no longer seen
            game._thumbs_up_held = any_thumbs_up
        else:
            game._thumbs_up_held = False

    move_dir = 0
    if held["left"]: move_dir = -1
    elif held["right"]: move_dir = 1

    keyboard_gi = GameInput(
        move_dir=move_dir,
        move_to_slot=_gi_frame.get("move_to_slot"),
        station_click=station_click,
        confirm=_gi_frame.get("confirm", False),
        chop=_gi_frame.get("chop", False),
        stir=_gi_frame.get("stir", False),
        put_down=_gi_frame.get("put_down", False),
        overlay_click=overlay_click,
        overlay_cancel=_gi_frame.get("overlay_cancel", False),
    )
    return merge_inputs(keyboard_gi, gesture_gi), pipeline_frame


def _main_multiplayer(ui_mode: str, args):
    """Multiplayer game loop with lobby."""
    from .network import GameServer, GameClient, RoomAnnouncer, RoomScanner, get_local_ip
    from .ui.lobby_ui import LobbyUI
    from .constants import NET_PORT, NET_TICK_RATE

    lobby_ui = LobbyUI()
    lobby_state = "lobby_menu"  # lobby_menu, lobby_create, lobby_join, lobby_wait, playing_host, playing_client
    
    server = None
    client = None
    scanner = None
    game = None
    
    held = {"left": False, "right": False}
    mpressed = False
    click_pos = None
    client_paused = False  # client-side local pause (server continues)

    _SLOT_KEYS = {pygame.K_1: 1, pygame.K_2: 2, pygame.K_3: 3, pygame.K_4: 4, pygame.K_5: 5}

    while True:
        dt = min(clock.tick(FPS) / 1000.0, 0.05)
        click_pos = None
        station_click = None
        overlay_click = None
        _gi_frame = {}
        _click_this_frame = False

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                if server: server.stop()
                if client: client.close()
                if scanner: scanner.stop()
                if game: game.shutdown()
                pygame.quit()
                return
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_LEFT, pygame.K_a): held["left"] = True
                if event.key in (pygame.K_RIGHT, pygame.K_d): held["right"] = True
                if event.key == pygame.K_ESCAPE:
                    if lobby_state.startswith("lobby"):
                        if server: server.stop()
                        if client: client.close()
                        if scanner: scanner.stop()
                        pygame.quit()
                        return
                # Game keys (only processed during playing states)
                if lobby_state.startswith("playing") and game:
                    if game.state == "play":
                        if event.key == pygame.K_ESCAPE:
                            if game._player_overlays.get(getattr(game, "local_player_id", 0), False):
                                _gi_frame["overlay_cancel"] = True
                            elif lobby_state == "playing_host":  # M7: only host can pause
                                game.state = "paused"
                                game.audio.play("ui_pause")
                                game.audio.pause_bgm()
                        if event.key in _SLOT_KEYS and game._station_shortcuts_enabled():
                            _gi_frame["move_to_slot"] = _SLOT_KEYS[event.key]
                        if event.key in (pygame.K_z, pygame.K_SPACE):
                            _gi_frame["confirm"] = True
                        if event.key == pygame.K_c:
                            _gi_frame["chop"] = True
                        if event.key == pygame.K_v:
                            _gi_frame["stir"] = True
                    elif game.state == "paused" and event.key == pygame.K_ESCAPE:
                        if lobby_state == "playing_host":  # M7: resume
                            game.state = "play"
                            game.audio.play("ui_resume")
                            game.audio.unpause_bgm()
            if event.type == pygame.KEYUP:
                if event.key in (pygame.K_LEFT, pygame.K_a): held["left"] = False
                if event.key in (pygame.K_RIGHT, pygame.K_d): held["right"] = False
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mpressed = True
                _click_this_frame = True
                click_pos = pygame.mouse.get_pos()
                # Route click through settings overlays first
                if game and game.settings_overlay.handle_mousedown(click_pos):
                    pass  # consumed by game settings overlay
                elif not lobby_state.startswith("playing") and lobby_ui.handle_mousedown(click_pos):
                    pass  # consumed by lobby settings overlay
                elif game and game._player_overlays.get(getattr(game, 'local_player_id', 0), False):
                    overlay_click = click_pos
                elif lobby_state.startswith("playing") and game and game._station_shortcuts_enabled():
                    station_click = click_pos
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                mpressed = False
                if game: game.settings_overlay.handle_mouseup(event.pos)
                if not lobby_state.startswith("playing"): lobby_ui.handle_mouseup(event.pos)
            if event.type == pygame.MOUSEMOTION:
                if game: game.settings_overlay.handle_mousemove(event.pos)
                if not lobby_state.startswith("playing"): lobby_ui.handle_mousemove(event.pos)

        mpos = pygame.mouse.get_pos()

        # ── State Machine ─────────────────────────────────────────────

        _btn_pressed = _click_this_frame or mpressed

        if lobby_state == "lobby_menu":
            action = lobby_ui.update_menu(mpos, _btn_pressed)
            if action == "create":
                host_ip = get_local_ip()
                server = GameServer(host_ip, NET_PORT, room_name=f"{args.name}'s Room")
                server.start()
                lobby_state = "lobby_create"
                lobby_ui.players = [{"id": 0, "name": args.name, "ready": False}]
                lobby_ui.status_text = f"Listening on {host_ip}:{NET_PORT}"
            elif action == "join":
                scanner = RoomScanner()
                scanner.start()
                lobby_state = "lobby_join"
                lobby_ui.rooms = []
                lobby_ui.selected_room = -1
            elif action == "single":
                _main_single(ui_mode, args)
                mpressed = False  # clear lingering click when returning to lobby
            lobby_ui.draw_menu()

        elif lobby_state == "lobby_create":
            action = lobby_ui.update_create(mpos, _btn_pressed)
            if action == "ready":
                server.set_host_ready(not server.host_ready)
            elif action == "start":
                info = server.get_lobby_info()
                if info["all_ready"] and info["count"] > 0:
                    # Collect player names
                    player_names = {p["id"]: p["name"] for p in info["players"]}
                    game = Game(
                        ui_mode=ui_mode,
                        use_gesture=args.gesture,
                        flip=args.flip,
                        fast_motion=args.fast_motion,
                        clahe=args.clahe,
                        clahe_clip=args.clahe_clip,
                        clahe_grid=args.clahe_grid,
                        device=args.device,
                        multiplayer=True,
                        is_server=True,
                        local_player_id=0,
                        player_name=args.name,
                    )
                    game.set_mp_player_names(player_names)
                    game.reset()
                    game.state = "play"
                    game._spawn_order()
                    game._spawn_order()
                    game.audio.play("start_whistle")  # L3
                    game.audio.play_bgm("play_loop")
                    server.start_game()
                    lobby_state = "playing_host"
                    mpressed = False  # prevent lobby click from bleeding into game buttons
                    continue
                else:
                    lobby_ui.status_text = "Not all players ready!"
            elif action == "back":
                server.stop()
                server = None
                lobby_state = "lobby_menu"
                continue

            # Update lobby info from server
            info = server.get_lobby_info()
            lobby_ui.players = info["players"]
            lobby_ui.draw_create(f"{server.host}:{server.port}")

        elif lobby_state == "lobby_join":
            action = lobby_ui.update_join(mpos, _btn_pressed, click_pos=click_pos)
            if action == "connect":
                if lobby_ui.selected_room >= 0 and lobby_ui.selected_room < len(lobby_ui.rooms):
                    room = lobby_ui.rooms[lobby_ui.selected_room]
                    client = GameClient(room["host"], room["port"], args.name)
                    if client.connect():
                        lobby_state = "lobby_wait"
                        lobby_ui.status_text = f"Connected as Player {client.player_id + 1}"
                    else:
                        lobby_ui.status_text = "Connection failed!"
                        client = None
            elif action == "back":
                scanner.stop()
                scanner = None
                lobby_state = "lobby_menu"
                continue

            lobby_ui.rooms = scanner.get_rooms()
            lobby_ui.draw_join()

        elif lobby_state == "lobby_wait":
            action = lobby_ui.update_wait(mpos, _btn_pressed)
            if action == "ready":
                client.send_ready(True)
            elif action == "back":
                client.close()
                client = None
                lobby_state = "lobby_menu"
                continue

            # Check for lobby updates
            try:
                msg = client.lobby_queue.get_nowait()
                lobby_ui.players = msg.get("players", [])
            except Exception:
                pass

            # Check for game start
            try:
                event_msg = client.event_queue.get_nowait()
                if event_msg.get("type") == "game_start":
                    # Collect player names
                    player_names = {p["id"]: p["name"] for p in lobby_ui.players}
                    game = Game(
                        ui_mode=ui_mode,
                        use_gesture=args.gesture,
                        flip=args.flip,
                        fast_motion=args.fast_motion,
                        clahe=args.clahe,
                        clahe_clip=args.clahe_clip,
                        clahe_grid=args.clahe_grid,
                        device=args.device,
                        multiplayer=True,
                        is_server=False,
                        local_player_id=client.player_id,
                        player_name=args.name,
                    )
                    game.set_mp_player_names(player_names)
                    game.reset()
                    game.state = "play"
                    game.audio.play("start_whistle")  # L3
                    game.audio.play_bgm("play_loop")
                    lobby_state = "playing_client"
                    mpressed = False  # prevent lobby click from bleeding into game buttons
            except Exception:
                pass

            lobby_ui.draw_wait()

        elif lobby_state == "playing_host":
            mpos = pygame.mouse.get_pos()

            # H1+H3: handle paused/over states before game logic
            if game.state != "play":
                game.update(dt, GameInput(), mpos, _btn_pressed)
                if game.state == "over":
                    server.broadcast_game_over(game.score)
                    server.stop()
                    game.draw_over()
                elif game.state == "title":
                    # Home button pressed — return to lobby
                    server.stop()
                    game.shutdown()
                    game = None
                    server = None
                    lobby_state = "lobby_menu"
                    mpressed = False
                    pygame.display.flip()
                    continue
                elif game.state == "paused":
                    game.draw_paused()
                pygame.display.flip()
                continue

            # Sync: remove players that disconnected
            alive_pids = set([0] + server.get_alive_player_ids())
            for pid in list(game.players.keys()):
                if pid not in alive_pids:
                    del game.players[pid]
                    game._lock_modes.pop(pid, None)
                    game._player_overlays.pop(pid, None)
                    game._player_highlights.pop(pid, None)
                    game._motion_gates_per_player.pop(pid, None)

            # Host: collect inputs + server_tick + broadcast
            host_gi, pipeline_frame = _collect_local_input(
                game, held, _gi_frame, station_click, overlay_click
            )

            # Merge UI button clicks into host input
            btn_triggered = game.update_ui_buttons(mpos, _btn_pressed)
            if btn_triggered.get("confirm"): host_gi.confirm = True
            if btn_triggered.get("chop"):    host_gi.chop    = True
            if btn_triggered.get("stir"):    host_gi.stir    = True
            if btn_triggered.get("pause"):
                game.state = "paused"
                game.audio.play("ui_pause")
                game.audio.pause_bgm()

            # Collect client inputs
            net_inputs = server.collect_inputs()
            net_inputs[0] = host_gi.to_dict()  # Add host input

            # Server tick
            server_tick_interval = 1.0 / NET_TICK_RATE
            game._server_tick_accum += dt
            
            ticked = False
            while game._server_tick_accum >= server_tick_interval:
                game.server_tick(server_tick_interval, net_inputs)
                game._server_tick_accum -= server_tick_interval
                ticked = True
                # After first tick, keep only continuous inputs (move_dir)
                # and clear one-shot actions to avoid double-firing
                for pid in list(net_inputs.keys()):
                    inp = net_inputs[pid]
                    if isinstance(inp, dict):
                        net_inputs[pid] = {"move_dir": inp.get("move_dir", 0)}

            if ticked:
                server.broadcast_state(game.serialize_state())

            # H1: route to correct draw method
            if game.state == "over":
                server.broadcast_game_over(game.score)
                server.stop()
                game.draw_over()
                pygame.display.flip()
                game.shutdown()
                return
            game.draw(pipeline_frame)
            pygame.display.flip()

        elif lobby_state == "playing_client":
            mpos = pygame.mouse.get_pos()

            # H1+H3: handle paused/over states without sending input to server
            if game.state == "over":
                game.draw_over()
                pygame.display.flip()
                client.close()
                game.shutdown()
                return

            # Local pause: client-side pause (server continues running)
            if client_paused:
                # Receive server state but preserve local pause
                try:
                    state = client.state_queue.get_nowait()
                    saved_state = game.state
                    game.apply_state(state)
                    if game.state != "over":
                        game.state = saved_state
                except Exception:
                    pass
                try:
                    event_msg = client.event_queue.get_nowait()
                    if event_msg.get("type") == "game_over":
                        game.state = "over"
                        game.score = event_msg.get("score", game.score)
                        client_paused = False
                except Exception:
                    pass
                if game.state == "over":
                    game.draw_over()
                    pygame.display.flip()
                    client.close()
                    game.shutdown()
                    return
                game.update(dt, GameInput(), mpos, _btn_pressed)
                if game.state == "play":
                    client_paused = False
                    game.audio.play("ui_resume")
                    game.audio.unpause_bgm()
                elif game.state == "title":
                    # Home button pressed — return to lobby
                    client.close()
                    game.shutdown()
                    game = None
                    client = None
                    client_paused = False
                    lobby_state = "lobby_menu"
                    mpressed = False
                    pygame.display.flip()
                    continue
                else:
                    game.state = "paused"
                game.draw_paused()
                pygame.display.flip()
                continue

            # Client: send local input + receive state + render
            local_gi, pipeline_frame = _collect_local_input(
                game, held, _gi_frame, station_click, overlay_click
            )

            # Merge UI button clicks into local input
            btn_triggered = game.update_ui_buttons(mpos, _btn_pressed)
            if btn_triggered.get("confirm"): local_gi.confirm = True
            if btn_triggered.get("chop"):    local_gi.chop    = True
            if btn_triggered.get("stir"):    local_gi.stir    = True
            if btn_triggered.get("pause") and game.state == "play":
                client_paused = True
                game.state = "paused"
                game.audio.play("ui_pause")
                game.audio.pause_bgm()

            # Send input to server (skip when locally paused)
            if not client_paused:
                client.send_input(local_gi.to_dict())

            # Receive state from server
            try:
                state = client.state_queue.get_nowait()
                game.apply_state(state)
            except Exception:
                pass

            # Check for game over
            try:
                event_msg = client.event_queue.get_nowait()
                if event_msg.get("type") == "game_over":
                    game.state = "over"
                    game.score = event_msg.get("score", game.score)
            except Exception:
                pass

            # H1: route to correct draw method
            if game.state == "paused":
                game.draw_paused()
            else:
                game.draw(pipeline_frame)
            pygame.display.flip()

        # For lobby states that don't call flip internally
        if not lobby_state.startswith("playing"):
            pygame.display.flip()


if __name__ == "__main__":
    main()