"""
Lobby UI screens for multiplayer Overcook.

States:
  lobby_menu   → Create Room / Join Room / Single
  lobby_create → Waiting for players, show list + Ready/Start
  lobby_join   → Scanning for rooms, show list
  lobby_wait   → Connected to host, waiting for start
"""

import os
import math
import time
import pygame
from ..engine import screen, F
from ..constants import C, NET_PORT, PLAYER_COLORS
from ..utils import rr, txt
from ..audio import AudioManager
from .game_ui import Btn, SettingsOverlay, load_nickname, save_nickname


class KoreanComposer:
    """두벌식 한글 조합기."""

    CHO  = ['ㄱ','ㄲ','ㄴ','ㄷ','ㄸ','ㄹ','ㅁ','ㅂ','ㅃ','ㅅ','ㅆ','ㅇ','ㅈ','ㅉ','ㅊ','ㅋ','ㅌ','ㅍ','ㅎ']
    JUNG = ['ㅏ','ㅐ','ㅑ','ㅒ','ㅓ','ㅔ','ㅕ','ㅖ','ㅗ','ㅘ','ㅙ','ㅚ','ㅛ','ㅜ','ㅝ','ㅞ','ㅟ','ㅠ','ㅡ','ㅢ','ㅣ']
    JONG = ['','ㄱ','ㄲ','ㄳ','ㄴ','ㄵ','ㄶ','ㄷ','ㄹ','ㄺ','ㄻ','ㄼ','ㄽ','ㄾ','ㄿ','ㅀ','ㅁ','ㅂ','ㅄ','ㅅ','ㅆ','ㅇ','ㅈ','ㅊ','ㅋ','ㅌ','ㅍ','ㅎ']
    JONG_COMBO = {
        ('ㄱ','ㅅ'):'ㄳ', ('ㄴ','ㅈ'):'ㄵ', ('ㄴ','ㅎ'):'ㄶ',
        ('ㄹ','ㄱ'):'ㄺ', ('ㄹ','ㅁ'):'ㄻ', ('ㄹ','ㅂ'):'ㄼ',
        ('ㄹ','ㅅ'):'ㄽ', ('ㄹ','ㅌ'):'ㄾ', ('ㄹ','ㅍ'):'ㄿ',
        ('ㄹ','ㅎ'):'ㅀ', ('ㅂ','ㅅ'):'ㅄ',
    }
    VOWEL_COMBO = {
        ('ㅗ','ㅏ'):'ㅘ', ('ㅗ','ㅐ'):'ㅙ', ('ㅗ','ㅣ'):'ㅚ',
        ('ㅜ','ㅓ'):'ㅝ', ('ㅜ','ㅔ'):'ㅞ', ('ㅜ','ㅣ'):'ㅟ',
        ('ㅡ','ㅣ'):'ㅢ',
    }
    JONG_SPLIT  = {v: k for k, v in JONG_COMBO.items()}
    VOWEL_SPLIT = {v: k for k, v in VOWEL_COMBO.items()}

    def __init__(self):
        self.committed = ''
        self._cho = self._jung = self._jong = None

    def _is_vowel(self, j):     return j in self.JUNG
    def _is_consonant(self, j): return j in self.CHO

    @property
    def text(self):
        return self.committed + self._preview()

    def _preview(self):
        if self._cho is None:
            return ''
        if self._jung is None:
            return self._cho
        ci = self.CHO.index(self._cho)
        vi = self.JUNG.index(self._jung)
        ji = self.JONG.index(self._jong) if self._jong else 0
        return chr(0xAC00 + (ci * 21 + vi) * 28 + ji)

    def _commit(self):
        p = self._preview()
        if p:
            self.committed += p
        self._cho = self._jung = self._jong = None

    def input(self, jamo):
        if self._cho is None:
            if self._is_vowel(jamo):
                self.committed += jamo
            else:
                self._cho = jamo
        elif self._jung is None:
            if self._is_vowel(jamo):
                self._jung = jamo
            else:
                self.committed += self._cho
                self._cho = jamo
        elif self._jong is None:
            if self._is_consonant(jamo):
                if jamo in self.JONG:
                    self._jong = jamo
                else:
                    self._commit()
                    self._cho = jamo
            else:
                compound = self.VOWEL_COMBO.get((self._jung, jamo))
                if compound:
                    self._jung = compound
                else:
                    self._commit()
                    self.committed += jamo
        else:
            if self._is_vowel(jamo):
                jong = self._jong
                self._jong = None
                if jong in self.JONG_SPLIT:
                    a, b = self.JONG_SPLIT[jong]
                    self._jong = a
                    jong = b
                self._commit()
                self._cho = jong
                self._jung = jamo
            else:
                combo = self.JONG_COMBO.get((self._jong, jamo))
                if combo and combo in self.JONG:
                    self._jong = combo
                else:
                    self._commit()
                    self._cho = jamo if jamo in self.JONG else None
                    if self._cho is None:
                        self.committed += jamo

    def backspace(self):
        if self._jong is not None:
            if self._jong in self.JONG_SPLIT:
                self._jong = self.JONG_SPLIT[self._jong][0]
            else:
                self._jong = None
        elif self._jung is not None:
            if self._jung in self.VOWEL_SPLIT:
                self._jung = self.VOWEL_SPLIT[self._jung][0]
            else:
                self._jung = None
        elif self._cho is not None:
            self._cho = None
        elif self.committed:
            last = self.committed[-1]
            self.committed = self.committed[:-1]
            if '\uAC00' <= last <= '\uD7A3':
                code = ord(last) - 0xAC00
                ji = code % 28
                vi = (code // 28) % 21
                ci = code // 28 // 21
                self._cho = self.CHO[ci]
                self._jung = self.JUNG[vi]
                self._jong = self.JONG[ji] if ji else None

    def commit_and_get(self):
        self._commit()
        return self.committed

    def clear(self):
        self.committed = ''
        self._cho = self._jung = self._jong = None


# 두벌식 QWERTY → 자모 매핑
_QWERTY_TO_JAMO = {
    'q':'ㅂ','w':'ㅈ','e':'ㄷ','r':'ㄱ','t':'ㅅ',
    'y':'ㅛ','u':'ㅕ','i':'ㅑ','o':'ㅐ','p':'ㅔ',
    'a':'ㅁ','s':'ㄴ','d':'ㅇ','f':'ㄹ','g':'ㅎ',
    'h':'ㅗ','j':'ㅓ','k':'ㅏ','l':'ㅣ',
    'z':'ㅋ','x':'ㅌ','c':'ㅊ','v':'ㅍ',
    'b':'ㅠ','n':'ㅜ','m':'ㅡ',
    # shift 쌍자음/이중모음
    'Q':'ㅃ','W':'ㅉ','E':'ㄸ','R':'ㄲ','T':'ㅆ',
    'O':'ㅒ','P':'ㅖ',
}


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
        
        # Nickname
        self.nickname: str = load_nickname()
        self._nickname_editing: bool = False
        self._korean_composer: KoreanComposer = KoreanComposer()
        self._vk_shift: bool = False
        self._vk_lang: str = "KR"   # "KR" or "EN"
        self._vk_rects: dict = {}  # key label → pygame.Rect for virtual keyboard

        # Gesture state for lobby hover tracking
        self.hovered_button = None
        self._thumbs_up_time = 0.0
        self._thumbs_progress = 0.0
        self._thumbs_up_duration = 1.0   # Hold for 1s to activate
        self._thumbs_cooldown = 0.0      # Cooldown after click
        self._hover_lock_time = 0.0      # Time stayed on same button
        self._hover_lock_duration = 0.18 # Require short stable hover before click
        self._last_hovered_button = None
        self._last_gesture_ts = time.monotonic()
        self._cursor_pos = None          # Smoothed cursor position in screen coords
        self._cursor_alpha = 0.28        # Lower value = less sensitive movement
        # Expand usable gesture range to screen edges.
        # Example: 0.12 means 12% inner margin maps to full [0..1] range.
        self._cursor_edge_margin_x = 0.12
        self._cursor_edge_margin_y = 0.10
        self.last_hand_inputs = None  # Store hand inputs for drawing
        self.last_pipeline_frame = None  # Store camera frame for display

    @staticmethod
    def _remap_edge(value: float, margin: float) -> float:
        margin = max(0.0, min(0.45, float(margin)))
        low = margin
        high = 1.0 - margin
        if high <= low:
            return max(0.0, min(1.0, value))
        remapped = (value - low) / (high - low)
        return max(0.0, min(1.0, remapped))

    def _maybe_rebuild(self):
        """Rebuild buttons if screen size changed."""
        sz = screen.get_size()
        if sz != self._last_size:
            self._last_size = sz
            self._make_btns()

    def _gesture_dt(self) -> float:
        now = time.monotonic()
        dt = now - self._last_gesture_ts
        self._last_gesture_ts = now
        return max(0.0, min(0.10, dt))

    def _decay_gesture_hold(self, dt: float):
        # Gentle decay prevents accidental cancellation from brief detection flicker.
        self._thumbs_up_time = max(0.0, self._thumbs_up_time - dt * 2.0)
        self._hover_lock_time = max(0.0, self._hover_lock_time - dt * 3.0)
        self._thumbs_progress = min(1.0, self._thumbs_up_time / max(0.001, self._thumbs_up_duration))

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

        # Profile (nickname) button: below settings button
        self.btn_nickname = Btn(gw - 90, 52, 80, 38, "Profile", (70, 100, 70))


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
        """Forward mousedown to settings overlay or nickname VK. Returns True if consumed."""
        if self._nickname_editing:
            for key, rect in self._vk_rects.items():
                if rect.collidepoint(mpos):
                    self._handle_vk_key(key)
                    return True
            return True  # consume all clicks while editing
        return self.settings_overlay.handle_mousedown(mpos)

    def _handle_vk_key(self, key: str):
        if key == "__DEL__":
            self._korean_composer.backspace()
        elif key == "__OK__":
            self._confirm_nickname()
        elif key == "__CANCEL__":
            self._nickname_editing = False
            self._vk_shift = False
        elif key == "__SHIFT__":
            self._vk_shift = not self._vk_shift
        elif key == "__LANG__":
            self._vk_lang = "EN" if self._vk_lang == "KR" else "KR"
            self._vk_shift = False
        else:
            self._process_char_input(key)

    def handle_mouseup(self, mpos):
        self.settings_overlay.handle_mouseup(mpos)

    def handle_mousemove(self, mpos):
        self.settings_overlay.handle_mousemove(mpos)

    def handle_keydown(self, event) -> bool:
        """Handle keyboard input for nickname editing. Returns True if consumed."""
        if not self._nickname_editing:
            return False
        if event.key == pygame.K_RETURN or event.key == pygame.K_KP_ENTER:
            self._confirm_nickname()
        elif event.key == pygame.K_ESCAPE:
            self._nickname_editing = False
        elif event.key == pygame.K_BACKSPACE:
            self._korean_composer.backspace()
        elif event.key in (pygame.K_LSHIFT, pygame.K_RSHIFT):
            self._vk_shift = not self._vk_shift
        elif (event.key in (0xff31, 0x0138, 0x40000156, 0x40000090)  # XK_Hangul, SDL1, SDLK_LANG1(SDL2), 한영키
              or event.key == getattr(pygame, 'K_HANGUL', -1)
              or event.key == getattr(pygame, 'K_RALT', -1)):
            # 한/영 키
            self._vk_lang = "EN" if self._vk_lang == "KR" else "KR"
            self._vk_shift = False
        else:
            ch = event.unicode
            if ch:
                if self._vk_lang == "KR":
                    ch = _QWERTY_TO_JAMO.get(ch, ch)
                self._process_char_input(ch)
        return True

    def _process_char_input(self, ch: str):
        """Route a character through the composer with 5-char length guard."""
        if not ch:
            return
        code = ord(ch[0])
        composer = self._korean_composer
        # Korean jamo → IME composer
        if 0x3131 <= code <= 0x318E:
            cur_len = len(composer.text)
            if cur_len < 5 or composer._cho is not None:
                composer.input(ch)
        # Pre-composed Korean syllable (OS IME)
        elif 0xAC00 <= code <= 0xD7A3:
            composer._commit()
            if len(composer.text) < 5:
                composer.committed += ch
        # ASCII printable (English)
        elif 32 <= code < 127:
            composer._commit()
            if len(composer.text) < 5:
                composer.committed += ch

    def _confirm_nickname(self):
        name = self._korean_composer.commit_and_get().strip()
        if name:
            self.nickname = name[:5]
            save_nickname(self.nickname)
        self._nickname_editing = False
        self._vk_shift = False

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

    def _draw_thumbs_hold_indicator(self):
        if self._cursor_pos is None:
            return
        if self.hovered_button is None:
            return
        if self._thumbs_progress <= 0.0:
            return

        cx, cy = int(self._cursor_pos[0]), int(self._cursor_pos[1])
        radius = 20
        progress = max(0.0, min(1.0, self._thumbs_progress))

        # Base ring.
        pygame.draw.circle(screen, (220, 220, 220), (cx, cy), radius, 2)

        # Progress arc starting at top and moving clockwise.
        rect = pygame.Rect(cx - radius, cy - radius, radius * 2, radius * 2)
        start = -math.pi / 2.0
        end = start + (math.pi * 2.0 * progress)
        if end > start:
            pygame.draw.arc(screen, (80, 230, 140), rect, start, end, 4)

        if 12 in F:
            remain = max(0.0, self._thumbs_up_duration - self._thumbs_up_time)
            txt(screen, f"Hold 👍 {remain:0.1f}s", 12, (220, 235, 220), cx, cy + radius + 10)

    def _draw_nickname_overlay(self):
        gw, gh = screen.get_size()
        ov = pygame.Surface((gw, gh), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 170))
        screen.blit(ov, (0, 0))

        key_h = 34
        key_gap = 4
        # Compute panel height dynamically so buttons never overflow
        ph = (28 + 26 + 28            # title + current + gap
              + 52 + 10               # input box + gap
              + 3 * (key_h + key_gap) # 3 keyboard rows
              + 6 + 38                # gap + bottom buttons
              + 20)                   # bottom padding
        pw = 600
        px, py = gw // 2 - pw // 2, gh // 2 - ph // 2
        rr(screen, (25, 30, 55), (px, py, pw, ph), 12)
        pygame.draw.rect(screen, (80, 100, 160), (px, py, pw, ph), 2, border_radius=12)

        cy = py + 28
        txt(screen, "닉네임 입력 (최대 5글자)", 18, C["gold"], gw // 2, cy)
        cy += 26
        txt(screen, "Current: " + self.nickname, 14, (160, 160, 200), gw // 2, cy)
        cy += 28

        # Text input box
        box_w, box_h = 380, 52
        box_x = gw // 2 - box_w // 2
        rr(screen, (15, 18, 38), (box_x, cy, box_w, box_h), 8)
        pygame.draw.rect(screen, (120, 140, 200), (box_x, cy, box_w, box_h), 2, border_radius=8)
        composer = self._korean_composer
        blink = "|" if (pygame.time.get_ticks() // 500) % 2 == 0 else ""
        display_text = composer.text + blink
        txt(screen, display_text or "|", 32, C["white"], gw // 2, cy + box_h // 2)
        txt(screen, f"{len(composer.text)}/5", 12, (140, 140, 180),
            box_x + box_w + 16, cy + box_h // 2)
        cy += box_h + 10

        # ── Virtual keyboard ────────────────────────────────────────────
        # Layouts
        KR_ROWS = [
            ['ㅂ','ㅈ','ㄷ','ㄱ','ㅅ','ㅛ','ㅕ','ㅑ','ㅐ','ㅔ'],
            ['ㅁ','ㄴ','ㅇ','ㄹ','ㅎ','ㅗ','ㅓ','ㅏ','ㅣ'],
            ['__SHIFT__','ㅋ','ㅌ','ㅊ','ㅍ','ㅠ','ㅜ','ㅡ','__DEL__'],
        ]
        KR_ROWS_SHIFT = [
            ['ㅃ','ㅉ','ㄸ','ㄲ','ㅆ','ㅛ','ㅕ','ㅑ','ㅒ','ㅖ'],
            ['ㅁ','ㄴ','ㅇ','ㄹ','ㅎ','ㅗ','ㅓ','ㅏ','ㅣ'],
            ['__SHIFT__','ㅋ','ㅌ','ㅊ','ㅍ','ㅠ','ㅜ','ㅡ','__DEL__'],
        ]
        EN_ROWS = [
            list('qwertyuiop'),
            list('asdfghjkl'),
            ['__SHIFT__'] + list('zxcvbnm') + ['__DEL__'],
        ]
        EN_ROWS_SHIFT = [
            list('QWERTYUIOP'),
            list('ASDFGHJKL'),
            ['__SHIFT__'] + list('ZXCVBNM') + ['__DEL__'],
        ]
        if self._vk_lang == "KR":
            rows = KR_ROWS_SHIFT if self._vk_shift else KR_ROWS
        else:
            rows = EN_ROWS_SHIFT if self._vk_shift else EN_ROWS

        self._vk_rects = {}
        row_w_total = pw - 24
        for row in rows:
            n = len(row)
            key_w = (row_w_total - key_gap * (n - 1)) // n
            rx = gw // 2 - row_w_total // 2
            for key in row:
                is_del   = key == "__DEL__"
                is_shift = key == "__SHIFT__"
                bg_color = (70, 35, 35) if is_del else \
                           ((80, 80, 30) if (is_shift and self._vk_shift) else \
                           ((50, 60, 40) if is_shift else (38, 44, 80)))
                r = pygame.Rect(rx, cy, key_w, key_h)
                self._vk_rects[key] = r
                rr(screen, bg_color, r, 5)
                pygame.draw.rect(screen, (70, 80, 130), r, 1, border_radius=5)
                if is_shift:
                    label = "Sft*" if self._vk_shift else "Sft"
                elif is_del:
                    label = "Del"
                else:
                    label = key
                if 14 in F:
                    ks = F[14].render(label, True, C["white"])
                    screen.blit(ks, ks.get_rect(center=r.center))
                rx += key_w + key_gap
            cy += key_h + key_gap

        cy += 6
        # Bottom row: lang toggle | OK | Cancel
        btn_h = 38
        third = (pw - 24 - key_gap * 2) // 3
        bx = gw // 2 - (third * 3 + key_gap * 2) // 2

        lang_r = pygame.Rect(bx, cy, third, btn_h)
        self._vk_rects["__LANG__"] = lang_r
        lang_label = "→ EN" if self._vk_lang == "KR" else "→ KR"
        rr(screen, (45, 60, 95), lang_r, 8)
        pygame.draw.rect(screen, (80, 110, 170), lang_r, 1, border_radius=8)
        if 14 in F:
            ls = F[14].render(lang_label, True, C["white"])
            screen.blit(ls, ls.get_rect(center=lang_r.center))

        ok_r = pygame.Rect(bx + third + key_gap, cy, third, btn_h)
        self._vk_rects["__OK__"] = ok_r
        rr(screen, (40, 100, 50), ok_r, 8)
        pygame.draw.rect(screen, (70, 160, 80), ok_r, 1, border_radius=8)
        if 14 in F:
            os_ = F[14].render("OK", True, C["white"])
            screen.blit(os_, os_.get_rect(center=ok_r.center))

        cancel_r = pygame.Rect(bx + (third + key_gap) * 2, cy, third, btn_h)
        self._vk_rects["__CANCEL__"] = cancel_r
        rr(screen, (80, 40, 40), cancel_r, 8)
        pygame.draw.rect(screen, (140, 80, 80), cancel_r, 1, border_radius=8)
        if 14 in F:
            cs = F[14].render("Cancel", True, C["white"])
            screen.blit(cs, cs.get_rect(center=cancel_r.center))

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
            # last_pipeline_frame is BGR and already flipped by the pipeline;
            # just convert to RGB (no extra mirror).
            frame = self.last_pipeline_frame[:, :, ::-1]

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
        self.btn_nickname.draw(screen)
        self.btn_settings.draw(screen)
        self.settings_overlay.draw(screen)

        # Nickname editing overlay
        if self._nickname_editing:
            self._draw_nickname_overlay()

        # Draw camera feed and hand visualization
        if self.last_pipeline_frame is not None:
            self._draw_camera_feed()
        if self.last_hand_inputs:
            self._draw_hand_visualization(self.last_hand_inputs)
        self._draw_thumbs_hold_indicator()

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
        self._draw_thumbs_hold_indicator()

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
        self._draw_thumbs_hold_indicator()

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
        self._draw_thumbs_hold_indicator()

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
        dt = self._gesture_dt()

        if not hand_inputs:
            self._decay_gesture_hold(dt)
            self._last_hovered_button = None
            return False

        if self._thumbs_cooldown > 0.0:
            self._thumbs_cooldown = max(0.0, self._thumbs_cooldown - dt)

        # Pick first active hand.
        hand = None
        for h in hand_inputs:
            if not h.stale:
                hand = h
                break

        if not hand or hand.position is None:
            self._decay_gesture_hold(dt)
            self._last_hovered_button = None
            return False

        gw, gh = screen.get_size()
        # Stretch inner tracking area so pointer can still reach screen edges.
        norm_x = self._remap_edge(float(hand.position[0]), self._cursor_edge_margin_x)
        norm_y = self._remap_edge(float(hand.position[1]), self._cursor_edge_margin_y)
        raw_x = norm_x * gw
        raw_y = norm_y * gh

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
            self.btn_create, self.btn_join, self.btn_solo, self.btn_nickname, self.btn_settings,
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
            self._decay_gesture_hold(dt)
            self._last_hovered_button = None
            return False

        # Require the pointer to stay on the same button briefly.
        if hovered is self._last_hovered_button:
            self._hover_lock_time += dt
        else:
            self._hover_lock_time = 0.0
            self._last_hovered_button = hovered
            self._decay_gesture_hold(dt)

        # Hold thumbs-up for 1s while hovering a stable button.
        if hand.gesture == "thumbs_up" and self._hover_lock_time >= self._hover_lock_duration:
            self._thumbs_up_time = min(self._thumbs_up_duration, self._thumbs_up_time + dt)
            if self._thumbs_up_time >= self._thumbs_up_duration and self._thumbs_cooldown <= 0.0:
                self._thumbs_up_time = 0.0
                self._thumbs_progress = 0.0
                self._thumbs_cooldown = 0.5
                return True
        else:
            # Do not hard reset on a single unstable frame.
            self._thumbs_up_time = max(0.0, self._thumbs_up_time - dt * 2.4)

        self._thumbs_progress = min(1.0, self._thumbs_up_time / max(0.001, self._thumbs_up_duration))

        return False

    def update_menu(self, mpos, mpressed, hand_inputs=None) -> str:
        if self.settings_overlay.active:
            return ""
        if self._nickname_editing:
            return ""  # all clicks handled by handle_mousedown

        # Handle gesture input
        if hand_inputs:
            if self._update_gesture_hover(hand_inputs):
                if self.hovered_button == self.btn_create:
                    return "create"
                elif self.hovered_button == self.btn_join:
                    return "join"
                elif self.hovered_button == self.btn_solo:
                    return "single"
                elif self.hovered_button == self.btn_nickname:
                    self._korean_composer.clear()
                    self._nickname_editing = True
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
        if self.btn_nickname.update(mpos, mpressed):
            self._korean_composer.clear()
            self._nickname_editing = True
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
