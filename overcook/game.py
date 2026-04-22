#!/usr/bin/env python3
"""
오버쿡 스타일 요리 게임 (pygame)
실행: python game.py
설치: pip install pygame

조작: 화면 버튼 (← →  이동 | Action 버튼)
      키보드:  ← → 이동 | Z / Space = 행동
"""

import os
import pygame
import random
import logging
import time
from typing import Optional

try:
    import cv2
except Exception:
    cv2 = None

from .engine import screen, F
from .constants import (
    C, INGS, ING_KEYS, RECIPES,
    BURN_TIME, ORDER_TIME, GAME_TIME, CHOP_ACTIONS, STIR_ACTIONS,
    OVER_STIR_THRESHOLD, WRONG_SUBMIT_PENALTY, BURN_SUBMIT_PENALTY, INTERACTION_RANGE,
)
from .ui import Popup, Btn, RecipeOverlay, IngredientOverlay, SettingsOverlay
from .entities import Station, Player, Order
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
from .input import (
    GESTURE_STATION_SLOTS,
    GameInput,
    hand_inputs_to_game_input,
    merge_inputs,
)
from .drawing import GameDrawMixin


class Game(GameDrawMixin):
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
        audio: "AudioManager | None" = None,
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

        # Pause-screen recording state
        self._recording_active: bool = False
        self._record_writer = None
        self._record_path: Optional[str] = None
        self._record_fps: int = 30
        self._recordings_dir = os.path.join(_ROOT, "recordings")
        self._record_stop_after_over_draws: int = -1

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

        self.audio = audio if audio is not None else AudioManager()
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
            max_hands = 1
            min_det = 0.15 if fast_motion else 0.2
            min_track = 0.1
            self._pipeline = RecognitionPipeline(
                camera_cfg=CameraConfig(device_index=device, width=640, height=480, fps=fps),
                hand_cfg=HandTrackerConfig(
                    max_num_hands=max_hands,
                    min_detection_confidence=min_det,
                    min_tracking_confidence=min_track,
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
        self._stop_recording("shutdown")
        if self._pipeline:
            self._pipeline.close()
            self._pipeline = None
        if self._camera:
            self._camera.release()
            self._camera = None

    def _record_btn_style(self) -> tuple[str, tuple[int, int, int]]:
        if self._recording_active:
            return "Stop Rec", (155, 45, 45)
        return "Record", (150, 35, 35)

    def _start_recording(self):
        if self._recording_active:
            return
        if cv2 is None:
            self._pop(self.gw // 2, 70, "OpenCV unavailable: cannot record", C["red"])
            return
        os.makedirs(self._recordings_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self._record_path = os.path.join(self._recordings_dir, f"overcook_{stamp}.mp4")
        self._record_writer = None
        self._recording_active = True
        self._record_stop_after_over_draws = -1
        self._pop(self.gw // 2, 70, "Recording started", C["gold"])

    def _stop_recording(self, _reason: str = ""):
        if not self._recording_active and self._record_writer is None:
            return
        try:
            if self._record_writer is not None:
                self._record_writer.release()
        finally:
            was_active = self._recording_active
            self._record_writer = None
            self._recording_active = False
            self._record_stop_after_over_draws = -1
            if was_active and self._record_path:
                self._pop(self.gw // 2, 70, f"Saved: {os.path.basename(self._record_path)}", C["lime"])

    def _arm_record_stop_on_game_over(self):
        """Stop recording after the game-over screen is rendered at least once."""
        if self._recording_active and self._record_stop_after_over_draws < 0:
            self._record_stop_after_over_draws = 1

    def _record_frame(self):
        if not self._recording_active or cv2 is None:
            return
        try:
            frame_rgb = pygame.surfarray.array3d(screen)
            frame_rgb = frame_rgb.swapaxes(0, 1)
            frame_bgr = frame_rgb[:, :, ::-1]
            h, w = frame_bgr.shape[:2]

            if self._record_writer is None:
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                self._record_writer = cv2.VideoWriter(self._record_path, fourcc, self._record_fps, (w, h))
                if not self._record_writer or not self._record_writer.isOpened():
                    self._record_writer = None
                    self._recording_active = False
                    self._pop(self.gw // 2, 70, "Failed to start recorder", C["red"])
                    return

            self._record_writer.write(frame_bgr)
        except Exception:
            self._stop_recording("record_error")

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
        self.btn_over_restart = Btn(gw // 2 - 200, gh // 2 + 50, 180, 64, "Restart", (120, 50, 50))
        self.btn_over_home    = Btn(gw // 2 + 20,  gh // 2 + 50, 180, 64, "Home",    (80, 60, 120))
        _bw, _bh, _gap = 120, 52, 12
        _total = 4 * _bw + 3 * _gap
        _bx = gw // 2 - _total // 2
        _by = gh // 2 + 20
        self.btn_pause_continue  = Btn(_bx,                        _by, _bw, _bh, "Continue", (40, 120, 60))
        self.btn_pause_restart   = Btn(_bx + (_bw + _gap),         _by, _bw, _bh, "Restart",  (120, 50, 50))
        self.btn_pause_home      = Btn(_bx + (_bw + _gap) * 2,     _by, _bw, _bh, "Home",     (80, 60, 120))
        self.btn_pause_settings  = Btn(_bx + (_bw + _gap) * 3,     _by, _bw, _bh, "Settings", (55, 55, 110))
        rec_label, rec_col = self._record_btn_style()
        self.btn_pause_record    = Btn(gw // 2 - 90, _by + _bh + 12, 180, 46, rec_label, rec_col)

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
            if self._pipeline:
                self._pipeline.reset_motion()
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
                if self._pipeline:
                    self._pipeline.reset_motion()
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
                penalty = BURN_SUBMIT_PENALTY
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
                self._pop(st.cx(), st.y - 30, f"+{pts} pts!", C["green"])
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

        # Station items must remain in place until explicitly picked up.
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
        def _apply_hint_visibility(msg: str) -> str:
            if self.multiplayer and "Stir to start" in msg:
                return ""
            # Keep advanced mode clean by hiding beginner instructional prompts.
            if not self.settings_overlay.amateur_mode:
                beginner_tokens = (
                    "Action:",
                    "Press Chop",
                    "Press Stir",
                    "Chop button:",
                    "Stir button:",
                    "Stir to start",
                    "Click an ingredient card",
                    # "Chop it first",
                )
                if any(tok in msg for tok in beginner_tokens):
                    return ""
            return msg

        if self._lock_mode == "chop" and self._locked_station:
            st = self._locked_station
            return _apply_hint_visibility(f"Chopping! Press Chop ({st.chop_hits}/{CHOP_ACTIONS})")
        if self._lock_mode == "stir" and self._locked_station:
            st = self._locked_station
            return _apply_hint_visibility(f"Stirring! Press Stir ({st.pot_stirs}/{STIR_ACTIONS})")
        # 로컬 플레이어의 overlay 상태 확인
        local_overlay_active = self._player_overlays.get(self.local_player_id, False)
        if local_overlay_active:
            return _apply_hint_visibility("Click an ingredient card  |  ESC to cancel")
        st = self._near()
        if not st: return _apply_hint_visibility("")
        h = self.player.holding
        k = st.kind
        if k == "ing":
            return _apply_hint_visibility("Action: Open pantry" if not h else "Action: Drop item first")
        if k == "chop":
            if h and not h.get("chopped") and INGS.get(h.get("id", "").replace("_c", ""), {}).get("can_chop"):
                return _apply_hint_visibility("Action: Place on board  |  Chop!: Start chopping")
            if not h and st.chop_item and st.chop_item.get("chopped"):
                return _apply_hint_visibility("Action: Pick chopped item")
            if not h and st.chop_item:
                return _apply_hint_visibility(f"Chop button: {st.chop_hits}/{CHOP_ACTIONS}")
        if k == "pot":
            burned = st.pot_burned
            if burned: return _apply_hint_visibility("Action: Pick up burned dish (trash to discard)")
            if h and not st.pot_cooked:
                base = h.get("id", "").replace("_c", "")
                if INGS.get(base, {}).get("can_chop") and not h.get("chopped"):
                    return _apply_hint_visibility("Chop it first before adding to pot!")
                return _apply_hint_visibility("Action: Add to pot")
            if not h and st.pot_items and not st.pot_cooking and not st.pot_cooked:
                return _apply_hint_visibility(f"Stir to start cooking! (max {OVER_STIR_THRESHOLD - 1} stirs)")
            if not h and st.pot_cooked: return _apply_hint_visibility("Action: Pick cooked dish")
            if not h and st.pot_cooking: return _apply_hint_visibility(f"Stir button: {st.pot_stirs}/{STIR_ACTIONS} (burn at {OVER_STIR_THRESHOLD})")
        if k == "submit":
            if h and h.get("cooked"):
                if h.get("burned"): return _apply_hint_visibility("Action: Submit burned dish (penalty!)")
                return _apply_hint_visibility("Action: Submit dish!")
            dish, _ = self._find_submit_dish()
            return _apply_hint_visibility("Action: Submit dish!" if dish else "Action: Nothing to submit")
        if k == "trash":
            if h: return _apply_hint_visibility("Action: Trash item")
            return _apply_hint_visibility("Action: Clear chop boards")
        return _apply_hint_visibility("")

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
            if self.state == "title":
                if self.btn_start.update(mpos, mpressed):
                    self._start_game_session()
                    self.audio.play("ui_click")
            else:
                if self.btn_over_restart.update(mpos, mpressed):
                    self._stop_recording("restart")
                    self._start_game_session()
                    self.audio.play("ui_click")
                if self.btn_over_home.update(mpos, mpressed):
                    self._stop_recording("home")
                    self.audio.stop_bgm()
                    self.audio.play_bgm("intro_bgm")
                    self.state = "title"
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
                self._stop_recording("restart")
                self._start_game_session()
                self.audio.play("ui_click")
            if self.btn_pause_home.update(mpos, mpressed):
                self._stop_recording("home")
                self.audio.stop_bgm()
                self.audio.play_bgm("intro_bgm")
                self.state = "title"
                self.audio.play("ui_click")
            if self.btn_pause_settings.update(mpos, mpressed):
                self.settings_overlay.active = True
                self.audio.play("ui_click")
            if self.btn_pause_record.update(mpos, mpressed):
                if self._recording_active:
                    self._stop_recording("manual")
                else:
                    self._start_recording()
                rec_label, rec_col = self._record_btn_style()
                self.btn_pause_record.label = rec_label
                self.btn_pause_record.base = rec_col
                self.audio.play("ui_click")
            return

        # Solo: handle local overlay (pantry ingredient selection)
        # In multiplayer, this path is not taken — use _process_single_input via server_tick instead.
        # Keep simulation running while overlay is open, but block gameplay input for this frame.
        local_overlay_active = self._player_overlays.get(self.local_player_id, False)
        overlay_block_frame = False
        if local_overlay_active:
            overlay_block_frame = True
            if gi.overlay_cancel:
                self._player_overlays[self.local_player_id] = False
                self.overlay.highlighted = None
                self._player_highlights[self.local_player_id] = None
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

        if self.recipe_overlay.active: return

        # Tick stations first so completion state (chopped/cooked) is up-to-date
        # before we evaluate lock-mode exit and process this frame's input.
        station_events = []
        for s in self.stations:
            station_events.extend((s, ev) for ev in s.update(dt))

        if overlay_block_frame:
            # Pantry open: no movement/action input, but keep world timers progressing.
            self.player.update(0, dt, gw, self._gy())
        elif self._lock_mode:
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

            self._process_lock_mode(act_flags, gi, dt, gw)
        else:
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

            self._apply_movement(gi, dt, gw)
            self._process_free_actions(act_flags)

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
            self._arm_record_stop_on_game_over()
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

    def _process_lock_mode(self, act_flags, gi, dt, gw):
        """Shared lock-mode processing for solo and multiplayer."""
        st = self._locked_station

        # Physics (movement blocked during lock)
        self.player.update(0, dt, gw, self._gy())

        # Arm counting only after first neutral frame post lock-entry.
        if self._lock_mode == "chop" and not gi.chop:
            self._motion_gate_ready["chop"] = True
        elif self._lock_mode == "stir" and not gi.stir:
            self._motion_gate_ready["stir"] = True

        # Chop/stir action (guarded by confirm to prevent double-action)
        if (
            self._lock_mode == "chop"
            and act_flags["chop"]
            and st
            and not act_flags["confirm"]
        ):
            if gi.chop and not self._motion_gate_ready["chop"]:
                pass
            elif self._near() is st:
                self._act_chop(st, chop_action=True)
        elif (
            self._lock_mode == "stir"
            and act_flags["stir"]
            and st
            and not act_flags["confirm"]
        ):
            if gi.stir and not self._motion_gate_ready["stir"]:
                pass
            elif self._near() is st:
                self._act_pot(st, stir_only=True)

        # Confirm while locked picks up the finished item
        if act_flags["confirm"] and st:
            if self._lock_mode == "chop":
                self._act_chop(st, chop_action=False)
            elif self._lock_mode == "stir":
                self._act_pot(st, stir_only=False)

        # Lock exit check
        if self._lock_mode == "chop" and (not st or not st.chop_item or st.chop_item.get("chopped")):
            self._lock_mode = None
            self._locked_station = None
            self._motion_gate_ready["chop"] = False
            self._thumbs_up_held = True
            self._move_blocked = True
            if self._pipeline:
                self._pipeline.reset_motion()
        elif self._lock_mode == "stir" and st and (
            st.pot_cooked
            or st.pot_burned
            or (not st.pot_cooking and not st.pot_items)
        ):
            self._lock_mode = None
            self._locked_station = None
            self._motion_gate_ready["stir"] = False
            self._thumbs_up_held = True
            self._move_blocked = True
            if self._pipeline:
                self._pipeline.reset_motion()

    def _apply_movement(self, gi, dt, gw):
        """Shared non-lock movement: station shortcuts, slot teleport, physics."""
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

    def _process_free_actions(self, act_flags):
        """Shared non-lock action processing: chop → stir → confirm."""
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
            act_flags = {
                "confirm": gi.confirm or gi.action,
                "chop": gi.chop,
                "stir": gi.stir,
            }
            self._process_lock_mode(act_flags, gi, dt, gw)
        else:
            self._apply_movement(gi, dt, gw)
            act_flags = {
                "confirm": gi.confirm or gi.action,
                "chop": gi.chop,
                "stir": gi.stir,
            }
            self._process_free_actions(act_flags)

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
            self._arm_record_stop_on_game_over()
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
