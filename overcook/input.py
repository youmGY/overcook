"""Unified game input abstraction (SRP: input handling only).

GameInput is the single data structure that the Game class consumes.
Concrete input sources (keyboard, gesture) are converted into GameInput
before reaching the game logic.
"""
from __future__ import annotations

import dataclasses
from typing import Optional


@dataclasses.dataclass
class GameInput:
    """Frame-level aggregated input from all sources."""

    move_to_slot: Optional[int] = None
    station_click: Optional[tuple] = None
    chop: bool = False
    stir: bool = False
    confirm: bool = False
    move_dir: int = 0
    action: bool = False
    overlay_click: Optional[tuple] = None
    overlay_select: Optional[int] = None    # 1-based ingredient index (gesture)
    overlay_confirm: bool = False            # thumbs_up in overlay (gesture)


def hand_inputs_to_game_input(hands, overlay_active: bool = False) -> GameInput:
    """Convert List[HandInput] → GameInput following the gesture-action table.

    When the ingredient overlay is active, finger_N highlights an ingredient
    and thumbs_up confirms the selection.  Otherwise finger_N maps to
    move_to_slot and thumbs_up maps to confirm (station-specific action).
    """
    gi = GameInput()
    for h in hands:
        if h.stale:
            continue

        # Motion-based actions (only on actual completed strokes)
        if h.motion == "chop_motion" and h.motion_count > 0:
            gi.chop = True
        elif h.motion == "stir_motion" and h.motion_count > 0:
            gi.stir = True

        # Gesture-confirmed actions (debounced, fires once)
        if not h.gesture_confirmed:
            continue

        if h.target_slot is not None:
            if overlay_active:
                gi.overlay_select = h.target_slot
            else:
                gi.move_to_slot = h.target_slot

        if h.motion == "thumbs_up" or h.gesture == "thumbs_up":
            if overlay_active:
                gi.overlay_confirm = True
            else:
                gi.confirm = True
    return gi


def merge_inputs(keyboard_gi: GameInput, gesture_gi: GameInput) -> GameInput:
    """OR-merge two GameInput instances (keyboard takes priority for move_to_slot)."""
    return GameInput(
        move_to_slot=keyboard_gi.move_to_slot or gesture_gi.move_to_slot,
        station_click=keyboard_gi.station_click,
        chop=keyboard_gi.chop or gesture_gi.chop,
        stir=keyboard_gi.stir or gesture_gi.stir,
        confirm=keyboard_gi.confirm or gesture_gi.confirm,
        move_dir=keyboard_gi.move_dir or gesture_gi.move_dir,
        action=keyboard_gi.action or gesture_gi.action,
        overlay_click=keyboard_gi.overlay_click,
        overlay_select=gesture_gi.overlay_select,
        overlay_confirm=gesture_gi.overlay_confirm,
    )
