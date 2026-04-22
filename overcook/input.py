"""Unified game input: dataclass, gesture conversion, and merge helpers."""
from __future__ import annotations

import dataclasses
from typing import Optional

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
