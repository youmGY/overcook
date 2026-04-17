"""Centralised audio manager for SFX and BGM."""
from __future__ import annotations

import os
import pygame

_ASSET_DIR = os.path.join(os.path.dirname(__file__), "assets")
_SFX_DIR = os.path.join(_ASSET_DIR, "sfx")
_BGM_DIR = os.path.join(_ASSET_DIR, "bgm")

# Volume defaults
_SFX_VOL = 0.8
_BGM_VOL = 0.4


class AudioManager:
    """Load-once, play-anywhere wrapper around pygame.mixer."""

    def __init__(self, sfx_vol: float = _SFX_VOL, bgm_vol: float = _BGM_VOL):
        pygame.mixer.init()
        pygame.mixer.set_num_channels(16)
        self._sfx: dict[str, pygame.mixer.Sound] = {}
        self._sfx_vol = sfx_vol
        self._bgm_vol = bgm_vol
        self._current_bgm: str | None = None
        self._bgm_paused = False
        self._load_sfx()

    # ── SFX ──────────────────────────────────────────────────────────
    def _load_sfx(self):
        if not os.path.isdir(_SFX_DIR):
            return
        for fname in os.listdir(_SFX_DIR):
            if not fname.endswith((".ogg", ".wav")):
                continue
            name = os.path.splitext(fname)[0]
            path = os.path.join(_SFX_DIR, fname)
            try:
                snd = pygame.mixer.Sound(path)
                snd.set_volume(self._sfx_vol)
                self._sfx[name] = snd
            except Exception:
                pass

    def play(self, name: str):
        """Play a loaded SFX by name (filename without extension)."""
        snd = self._sfx.get(name)
        if snd:
            snd.play()

    # ── BGM ──────────────────────────────────────────────────────────
    def play_bgm(self, name: str, loops: int = -1, fade_ms: int = 500):
        """Start a BGM track.  *name* is a filename stem in assets/bgm/."""
        if name == self._current_bgm and pygame.mixer.music.get_busy():
            return
        path = self._resolve_bgm(name)
        if not path:
            return
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.set_volume(self._bgm_vol)
            pygame.mixer.music.play(loops, fade_ms=fade_ms)
            self._current_bgm = name
            self._bgm_paused = False
        except Exception:
            pass

    def stop_bgm(self, fade_ms: int = 300):
        pygame.mixer.music.fadeout(fade_ms)
        self._current_bgm = None
        self._bgm_paused = False

    def pause_bgm(self):
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.pause()
            self._bgm_paused = True

    def unpause_bgm(self):
        if self._bgm_paused:
            pygame.mixer.music.unpause()
            self._bgm_paused = False

    def set_bgm_volume(self, vol: float):
        self._bgm_vol = vol
        pygame.mixer.music.set_volume(vol)

    def _resolve_bgm(self, name: str) -> str | None:
        for ext in (".ogg", ".wav", ".mp3"):
            p = os.path.join(_BGM_DIR, name + ext)
            if os.path.isfile(p):
                return p
        return None
