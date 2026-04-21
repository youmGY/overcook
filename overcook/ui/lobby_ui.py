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
from ..engine import screen
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
        self.btn_settings = Btn(gw - 58, 10, 48, 38, "⚙", (55, 55, 110))

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

    def _get_scaled_background(self):
        """Get background image scaled to current screen size."""
        if not self.bg_img:
            return None
        sz = screen.get_size()
        if self.bg_img_scaled is None or self._last_bg_size != sz:
            self.bg_img_scaled = pygame.transform.scale(self.bg_img, sz)
            self._last_bg_size = sz
        return self.bg_img_scaled

    # ── mouse event forwarding ─────────────────────────────────────────

    def handle_mousedown(self, mpos) -> bool:
        """Forward mousedown to settings overlay. Returns True if consumed."""
        return self.settings_overlay.handle_mousedown(mpos)

    def handle_mouseup(self, mpos):
        self.settings_overlay.handle_mouseup(mpos)

    def handle_mousemove(self, mpos):
        self.settings_overlay.handle_mousemove(mpos)

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

    def draw_create(self, host_ip: str):
        self._maybe_rebuild()
        gw, gh = screen.get_size()
        screen.fill(C["bg"])
        txt(screen, "Room Created", 32, C["gold"], gw // 2, 40)
        txt(screen, f"IP: {host_ip}", 14, (170, 170, 210), gw // 2, 70)

        self._draw_player_list(gw, gh)

        self.btn_ready.draw(screen)
        self.btn_start.draw(screen)
        self.btn_back.draw(screen)
        self.btn_settings.draw(screen)
        self.settings_overlay.draw(screen)

        if self.status_text:
            txt(screen, self.status_text, 18, C["orange"], gw // 2, gh - 145)

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
                txt(screen, f"{room['name']}  ({room['host']}:{room['port']})",
                    14, C["white"], gw // 2, y + 14)
                txt(screen, f"Max {room['max_players']} players",
                    12, (150, 150, 180), gw // 2, y + 32)
                y += 52

        self.btn_connect.draw(screen)
        self.btn_back.draw(screen)
        self.btn_settings.draw(screen)
        self.settings_overlay.draw(screen)

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
            status = "✓ Ready" if ready else "Waiting..."
            scol = C["lime"] if ready else (150, 150, 150)
            txt(screen, status, 14, scol, gw // 2 + 100, y + 20)
            y += 50

    # ── update (returns action string) ────────────────────────────────

    def update_menu(self, mpos, mpressed) -> str:
        if self.settings_overlay.active:
            return ""
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

    def update_create(self, mpos, mpressed) -> str:
        if self.settings_overlay.active:
            return ""
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

    def update_join(self, mpos, mpressed, click_pos=None) -> str:
        if self.settings_overlay.active:
            return ""
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

    def update_wait(self, mpos, mpressed) -> str:
        if self.settings_overlay.active:
            return ""
        if self.btn_settings.update(mpos, mpressed):
            self.settings_overlay.active = True
            return ""
        if self.btn_ready.update(mpos, mpressed):
            return "ready"
        if self.btn_back.update(mpos, mpressed):
            return "back"
        return ""
