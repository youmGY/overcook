"""
Lobby UI screens for multiplayer Overcook.

States:
  lobby_menu   → Create Room / Join Room / Single
  lobby_create → Waiting for players, show list + Ready/Start
  lobby_join   → Scanning for rooms, show list
  lobby_wait   → Connected to host, waiting for start
"""

import os
import pygame
from ..engine import screen, F
from ..constants import C, NET_PORT, PLAYER_COLORS
from ..utils import rr, txt
from ..audio import AudioManager
from .game_ui import Btn, SettingsOverlay


class LobbyUI:
    """Manages lobby state and rendering."""

    def __init__(self):
        self._last_size = (0, 0)
        self._last_bg_size = (0, 0)
        self._make_btns()
        # lobby_join state
        self.rooms: list = []
        self.selected_room: int = -1
        # lobby_create / lobby_wait state
        self.players: list = []  # [{"id": 0, "name": "Host", "ready": False}, ...]
        self.status_text: str = ""

        # Audio & settings
        self.audio = AudioManager()
        self.audio.play_bgm("intro_bgm")
        self.settings_overlay = SettingsOverlay(self.audio)

        # Load background image
        self.bg_img = None
        self.bg_img_scaled = None
        self._load_background()

        # Gesture & camera visualization
        self.use_gesture = False
        self.hand_img = None
        self.hand_img_scaled = None
        self._last_hand_img_size = (0, 0)
        self._load_hand_image()
        
        # Gesture state for lobby hover tracking
        self.hovered_button = None
        self._thumbs_up_time = 0.0
        self._thumbs_up_duration = 0.55  # Hold time to avoid accidental clicks
        self._thumbs_cooldown = 0.0      # Cooldown after click
        self._hover_lock_time = 0.0      # Time stayed on same button
        self._hover_lock_duration = 0.18 # Require short stable hover before click
        self._last_hovered_button = None
        self._cursor_pos = None          # Smoothed cursor position in screen coords
        self._cursor_alpha = 0.28        # Lower value = less sensitive movement
        self.last_hand_inputs = None  # Store hand inputs for drawing
        self.last_pipeline_frame = None  # Store camera frame for display

    def _maybe_rebuild(self):
        """Rebuild buttons if screen size changed."""
        sz = screen.get_size()
        if sz != self._last_size:
            self._last_size = sz
            self._make_btns()

    def _make_btns(self):
        gw, gh = screen.get_size()
        cx = gw // 2
        bw, bh = 220, 52

        self.btn_create = Btn(cx - bw // 2, gh // 2 + 50, bw, bh,
                              "Create Room", (50, 80, 130))
        self.btn_join = Btn(cx - bw // 2, gh // 2 + 115, bw, bh,
                            "Join Room", (80, 50, 135))
        self.btn_solo = Btn(cx - bw // 2, gh // 2 + 175, bw, bh,
                            "Single Play", (60, 60, 60))

        self.btn_ready = Btn(cx - bw // 2 - 60, gh - 80, bw // 2 + 40, bh,
                             "Ready", (40, 120, 60))
        self.btn_start = Btn(cx + 10, gh - 80, bw // 2 + 40, bh,
                             "Start!", (130, 80, 30))
        self.btn_back = Btn(20, gh - 60, 100, 40, "← Back", (80, 40, 40))
        self.btn_connect = Btn(cx + 60, gh - 80, 120, bh,
                               "Connect", (50, 100, 50))

        # Settings button: top-right corner
        self.btn_settings = Btn(gw - 90, 10, 80, 38, "Settings", (55, 55, 110))

    def rebuild(self):
        self._make_btns()

    def _load_background(self):
        """Load the Start_screen background image."""
        try:
            root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            bg_path = os.path.join(root, "assets", "images", "ui", "Start_screen.png")
            if os.path.exists(bg_path):
                self.bg_img = pygame.image.load(bg_path).convert()
            else:
                print(f"Warning: Start_screen.png not found at {bg_path}")
                self.bg_img = None
        except Exception as e:
            print(f"Error loading background image: {e}")
            self.bg_img = None

    def _load_hand_image(self):
        """Load the hand.png image for gesture visualization."""
        try:
            root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            hand_path = os.path.join(root, "assets", "images", "hand.png")
            if os.path.exists(hand_path):
                self.hand_img = pygame.image.load(hand_path).convert_alpha()
            else:
                print(f"Warning: hand.png not found at {hand_path}")
                self.hand_img = None
        except Exception as e:
            print(f"Error loading hand image: {e}")
            self.hand_img = None

    def _get_scaled_background(self):
        """Get background image scaled to current screen size."""
        if not self.bg_img:
            return None
        sz = screen.get_size()
        if self.bg_img_scaled is None or self._last_bg_size != sz:
            self.bg_img_scaled = pygame.transform.scale(self.bg_img, sz)
            self._last_bg_size = sz
        return self.bg_img_scaled

    def _get_scaled_hand(self, target_w: int, target_h: int):
        """Get hand image scaled to target size."""
        if not self.hand_img:
            return None
        if self.hand_img_scaled is None or self._last_hand_img_size != (target_w, target_h):
            self.hand_img_scaled = pygame.transform.scale(self.hand_img, (target_w, target_h))
            self._last_hand_img_size = (target_w, target_h)
        return self.hand_img_scaled

    # ── mouse event forwarding ─────────────────────────────────────────

    def handle_mousedown(self, mpos) -> bool:
        """Forward mousedown to settings overlay. Returns True if consumed."""
        return self.settings_overlay.handle_mousedown(mpos)

    def handle_mouseup(self, mpos):
        self.settings_overlay.handle_mouseup(mpos)

    def handle_mousemove(self, mpos):
        self.settings_overlay.handle_mousemove(mpos)

    def _draw_hand_visualization(self, hand_inputs):
        """Draw moving hand.png that follows the gesture pointer."""
        if not hand_inputs or not self.hand_img:
            return

        gw, gh = screen.get_size()
        hand_size = 96
        hand_img_scaled = self._get_scaled_hand(hand_size, hand_size)
        if not hand_img_scaled:
            return

        # Move the hand image with the smoothed pointer position.
        if self._cursor_pos is None:
            return

        cx, cy = self._cursor_pos
        hand_x = int(cx - hand_size * 0.35)
        hand_y = int(cy - hand_size * 0.25)
        hand_x = max(0, min(gw - hand_size, hand_x))
        hand_y = max(0, min(gh - hand_size, hand_y))
        screen.blit(hand_img_scaled, (hand_x, hand_y))

    def _draw_camera_feed(self):
        """Draw camera feed at bottom-right corner of screen."""
        if self.last_pipeline_frame is None:
            return
        
        gw, gh = screen.get_size()
        
        # Camera panel dimensions (bottom-right)
        cam_w, cam_h = 200, 150
        cam_x = gw - cam_w - 10
        cam_y = gh - cam_h - 10
        
        # Draw background panel
        pygame.draw.rect(screen, (30, 30, 50), (cam_x - 2, cam_y - 2, cam_w + 4, cam_h + 4))
        pygame.draw.rect(screen, (80, 90, 120), (cam_x - 2, cam_y - 2, cam_w + 4, cam_h + 4), 2)
        
        try:
            # last_pipeline_frame is BGR; convert to RGB and mirror for selfie view.
            frame = self.last_pipeline_frame[:, :, ::-1]
            frame = frame[:, ::-1, :]

            src_h, src_w = frame.shape[:2]
            scale = min(cam_w / float(src_w), cam_h / float(src_h))
            new_w = max(1, int(src_w * scale))
            new_h = max(1, int(src_h * scale))

            offset_x = (cam_w - new_w) // 2
            offset_y = (cam_h - new_h) // 2

            frame_swapped = frame.swapaxes(0, 1)
            surf = pygame.surfarray.make_surface(frame_swapped)
            surf = pygame.transform.smoothscale(surf, (new_w, new_h))
            screen.blit(surf, (cam_x + offset_x, cam_y + offset_y))
        except Exception:
            pass

    # ── drawing ───────────────────────────────────────────────────────

    def draw_menu(self):
        self._maybe_rebuild()
        gw, gh = screen.get_size()

        # Draw background image if available, otherwise fill with solid color
        bg = self._get_scaled_background()
        if bg:
            screen.blit(bg, (0, 0))
        else:
            screen.fill(C["bg"])

        self.btn_create.draw(screen)
        self.btn_join.draw(screen)
        self.btn_solo.draw(screen)
        self.btn_settings.draw(screen)
        self.settings_overlay.draw(screen)
        
        # Draw camera feed and hand visualization
        if self.last_pipeline_frame is not None:
            self._draw_camera_feed()
        if self.last_hand_inputs:
            self._draw_hand_visualization(self.last_hand_inputs)

    def draw_create(self):
        self._maybe_rebuild()
        gw, gh = screen.get_size()
        screen.fill(C["bg"])
        txt(screen, "Room Created", 32, C["gold"], gw // 2, 40)
        host_name = next((p.get("name", "Host") for p in self.players if p.get("id") == 0), None)
        if not host_name:
            host_name = self.players[0].get("name", "Host") if self.players else "Host"
        txt(screen, f"Host: {host_name}", 14, (170, 170, 210), gw // 2, 70)

        self._draw_player_list(gw, gh)

        self.btn_ready.draw(screen)
        self.btn_start.draw(screen)
        self.btn_back.draw(screen)
        self.btn_settings.draw(screen)
        self.settings_overlay.draw(screen)

        if self.status_text:
            txt(screen, self.status_text, 18, C["orange"], gw // 2, gh - 145)
        
        # Draw camera feed and hand visualization
        if self.last_pipeline_frame is not None:
            self._draw_camera_feed()
        if self.last_hand_inputs:
            self._draw_hand_visualization(self.last_hand_inputs)

    def draw_join(self):
        self._maybe_rebuild()
        gw, gh = screen.get_size()
        screen.fill(C["bg"])
        txt(screen, "Find Room", 32, C["gold"], gw // 2, 40)
        txt(screen, "Scanning LAN...", 14, (150, 150, 180), gw // 2, 70)

        # Room list
        if not self.rooms:
            txt(screen, "No rooms found yet", 18, (120, 120, 150), gw // 2, gh // 2)
        else:
            y = 100
            for i, room in enumerate(self.rooms):
                sel = (i == self.selected_room)
                col = C["ov_sel"] if sel else C["ov_card"]
                brd = C["ov_border"] if sel else (60, 60, 100)
                rx = gw // 2 - 200
                rr(screen, col, (rx, y, 400, 44), 8)
                pygame.draw.rect(screen, brd, (rx, y, 400, 44), 2, border_radius=8)
                txt(screen, f"{room['name']}",
                    14, C["white"], gw // 2, y + 14)
                txt(screen, f"Max {room['max_players']} players",
                    12, (150, 150, 180), gw // 2, y + 32)
                y += 52

        self.btn_connect.draw(screen)
        self.btn_back.draw(screen)
        self.btn_settings.draw(screen)
        self.settings_overlay.draw(screen)
        
        # Draw camera feed and hand visualization
        if self.last_pipeline_frame is not None:
            self._draw_camera_feed()
        if self.last_hand_inputs:
            self._draw_hand_visualization(self.last_hand_inputs)

    def draw_wait(self):
        self._maybe_rebuild()
        gw, gh = screen.get_size()
        screen.fill(C["bg"])
        txt(screen, "Waiting for Start", 32, C["gold"], gw // 2, 40)

        self._draw_player_list(gw, gh)

        self.btn_ready.draw(screen)
        self.btn_back.draw(screen)
        self.btn_settings.draw(screen)
        self.settings_overlay.draw(screen)

        if self.status_text:
            txt(screen, self.status_text, 18, C["orange"], gw // 2, gh - 145)
        
        # Draw camera feed and hand visualization
        if self.last_pipeline_frame is not None:
            self._draw_camera_feed()
        if self.last_hand_inputs:
            self._draw_hand_visualization(self.last_hand_inputs)

    def _draw_player_list(self, gw, gh):
        y = 100
        for p in self.players:
            pid = p.get("id", 0)
            pc = PLAYER_COLORS[pid % len(PLAYER_COLORS)]
            name = p.get("name", f"Player {pid + 1}")
            ready = p.get("ready", False)
            col_bg = (30, 50, 30) if ready else (40, 30, 50)
            rr(screen, col_bg, (gw // 2 - 180, y, 360, 40), 8)
            pygame.draw.rect(screen, pc["body"], (gw // 2 - 180, y, 360, 40), 2, border_radius=8)
            txt(screen, name, 18, pc["body"], gw // 2 - 60, y + 20)
            status = "Ready" if ready else "Waiting..."
            scol = C["lime"] if ready else (150, 150, 150)
            txt(screen, status, 14, scol, gw // 2 + 100, y + 20)
            y += 50

    # ── update (returns action string) ────────────────────────────────

    def _update_gesture_hover(self, hand_inputs):
        """Update button hover based on gesture hand position. Returns True if thumbs_up click detected."""
        self.hovered_button = None

        if not hand_inputs:
            self._thumbs_up_time = 0.0
            self._hover_lock_time = 0.0
            self._last_hovered_button = None
            return False

        dt = 1.0 / 30.0
        if self._thumbs_cooldown > 0.0:
            self._thumbs_cooldown = max(0.0, self._thumbs_cooldown - dt)

        # Pick first active hand.
        hand = None
        for h in hand_inputs:
            if not h.stale:
                hand = h
                break

        if not hand or hand.position is None:
            self._thumbs_up_time = 0.0
            self._hover_lock_time = 0.0
            self._last_hovered_button = None
            return False

        gw, gh = screen.get_size()
        raw_x = float(hand.position[0]) * gw
        raw_y = float(hand.position[1]) * gh

        # Smooth cursor to reduce sensitivity and jitter.
        if self._cursor_pos is None:
            self._cursor_pos = (raw_x, raw_y)
        else:
            px, py = self._cursor_pos
            a = self._cursor_alpha
            self._cursor_pos = (px + (raw_x - px) * a, py + (raw_y - py) * a)

        pos_x = int(self._cursor_pos[0])
        pos_y = int(self._cursor_pos[1])

        # Check which button is being pointed at
        all_buttons = [
            self.btn_create, self.btn_join, self.btn_solo, self.btn_settings,
            self.btn_ready, self.btn_start, self.btn_back, self.btn_connect
        ]

        hovered = None
        for btn in all_buttons:
            if not btn:
                continue
            # Add hit margin so aiming is easier.
            hit = btn.rect.inflate(24, 16)
            if hit.collidepoint(pos_x, pos_y):
                hovered = btn
                break

        self.hovered_button = hovered
        if hovered is None:
            self._thumbs_up_time = 0.0
            self._hover_lock_time = 0.0
            self._last_hovered_button = None
            return False

        # Require the pointer to stay on the same button briefly.
        if hovered is self._last_hovered_button:
            self._hover_lock_time += dt
        else:
            self._hover_lock_time = 0.0
            self._last_hovered_button = hovered
            self._thumbs_up_time = 0.0

        # Thumbs up click: either debounced confirmation pulse or hold gesture.
        thumbs_pulse = bool(getattr(hand, "gesture_confirmed", False) and hand.gesture == "thumbs_up")
        if self._hover_lock_time >= self._hover_lock_duration and thumbs_pulse and self._thumbs_cooldown <= 0.0:
            self._thumbs_up_time = 0.0
            self._thumbs_cooldown = 0.45
            return True

        if hand.gesture == "thumbs_up" and self._hover_lock_time >= self._hover_lock_duration:
            self._thumbs_up_time += dt
            if self._thumbs_up_time >= self._thumbs_up_duration and self._thumbs_cooldown <= 0.0:
                self._thumbs_up_time = 0.0
                self._thumbs_cooldown = 0.45
                return True
        else:
            self._thumbs_up_time = 0.0

        return False

    def update_menu(self, mpos, mpressed, hand_inputs=None) -> str:
        if self.settings_overlay.active:
            return ""
        
        # Handle gesture input
        if hand_inputs:
            if self._update_gesture_hover(hand_inputs):
                if self.hovered_button == self.btn_create:
                    return "create"
                elif self.hovered_button == self.btn_join:
                    return "join"
                elif self.hovered_button == self.btn_solo:
                    return "single"
                elif self.hovered_button == self.btn_settings:
                    self.settings_overlay.active = True
        else:
            self._thumbs_up_time = 0.0
        
        # Handle mouse input
        if self.btn_settings.update(mpos, mpressed):
            self.settings_overlay.active = True
            return ""
        if self.btn_create.update(mpos, mpressed):
            return "create"
        if self.btn_join.update(mpos, mpressed):
            return "join"
        if self.btn_solo.update(mpos, mpressed):
            return "single"
        return ""

    def update_create(self, mpos, mpressed, hand_inputs=None) -> str:
        if self.settings_overlay.active:
            return ""
        
        # Handle gesture input
        if hand_inputs:
            if self._update_gesture_hover(hand_inputs):
                if self.hovered_button == self.btn_ready:
                    return "ready"
                elif self.hovered_button == self.btn_start:
                    return "start"
                elif self.hovered_button == self.btn_back:
                    return "back"
                elif self.hovered_button == self.btn_settings:
                    self.settings_overlay.active = True
        else:
            self._thumbs_up_time = 0.0
        
        # Handle mouse input
        if self.btn_settings.update(mpos, mpressed):
            self.settings_overlay.active = True
            return ""
        if self.btn_ready.update(mpos, mpressed):
            return "ready"
        if self.btn_start.update(mpos, mpressed):
            return "start"
        if self.btn_back.update(mpos, mpressed):
            return "back"
        return ""

    def update_join(self, mpos, mpressed, hand_inputs=None, click_pos=None) -> str:
        if self.settings_overlay.active:
            return ""
        
        # Handle gesture input
        if hand_inputs:
            if self._update_gesture_hover(hand_inputs):
                if self.hovered_button == self.btn_connect:
                    return "connect"
                elif self.hovered_button == self.btn_back:
                    return "back"
                elif self.hovered_button == self.btn_settings:
                    self.settings_overlay.active = True
        else:
            self._thumbs_up_time = 0.0
        
        # Handle mouse input
        if self.btn_settings.update(mpos, mpressed):
            self.settings_overlay.active = True
            return ""
        if click_pos:
            gw, _ = screen.get_size()
            y = 100
            for i in range(len(self.rooms)):
                rx = gw // 2 - 200
                if pygame.Rect(rx, y, 400, 44).collidepoint(click_pos):
                    self.selected_room = i
                    break
                y += 52
        if self.btn_connect.update(mpos, mpressed):
            return "connect"
        if self.btn_back.update(mpos, mpressed):
            return "back"
        return ""

    def update_wait(self, mpos, mpressed, hand_inputs=None) -> str:
        if self.settings_overlay.active:
            return ""
        
        # Handle gesture input
        if hand_inputs:
            if self._update_gesture_hover(hand_inputs):
                if self.hovered_button == self.btn_ready:
                    return "ready"
                elif self.hovered_button == self.btn_back:
                    return "back"
                elif self.hovered_button == self.btn_settings:
                    self.settings_overlay.active = True
        else:
            self._thumbs_up_time = 0.0
        
        # Handle mouse input
        if self.btn_settings.update(mpos, mpressed):
            self.settings_overlay.active = True
            return ""
        if self.btn_ready.update(mpos, mpressed):
            return "ready"
        if self.btn_back.update(mpos, mpressed):
            return "back"
        return ""
