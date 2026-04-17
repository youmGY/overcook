"""Chop / stir / hands-together / palms-down motion detection.

Semantic mapping (see copilot-plan.md):

    chop_motion      : 썰기    (single hand, y-axis oscillation)
    stir_motion      : 조리    (single hand, x-axis oscillation)
    hands_together   : 집기    (both wrists close together, held N frames)
    palms_down       : 놓기    (both hands 5-extended, palm-down, held N frames)

Chop / stir detection uses a sliding-window oscillation counting approach
(ported from gshan branch): wrist x/y coordinates are buffered and direction
reversals with sufficient amplitude are counted.  No Pose dependency is
required for chop/stir — only hand-landmark wrist positions.

완성 is the per-frame ``thumbs_up`` gesture and is handled in
[gesture.py](gesture.py) / [interface.py](interface.py); it does not flow
through this detector.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from time import perf_counter
from typing import Deque, Dict, Optional, Tuple

import numpy as np

# Hand landmark indices for rule-based orientation checks (palms_down).
_WRIST = 0
_THUMB_TIP, _THUMB_IP = 4, 3
_INDEX_TIP, _INDEX_PIP = 8, 6
_MIDDLE_TIP, _MIDDLE_PIP = 12, 10
_RING_TIP, _RING_PIP = 16, 14
_PINKY_TIP, _PINKY_PIP = 20, 18
_FINGERS_UP_MARGIN = 0.05


def _fingers_point_up(landmarks) -> bool:
    """True when four non-thumb fingertips sit clearly above the wrist."""
    if len(landmarks) < 21:
        return False
    wrist_y = landmarks[_WRIST].y
    tips = [
        landmarks[_INDEX_TIP].y,
        landmarks[_MIDDLE_TIP].y,
        landmarks[_RING_TIP].y,
        landmarks[_PINKY_TIP].y,
    ]
    return (wrist_y - sum(tips) / 4.0) > _FINGERS_UP_MARGIN


def _all_fingers_extended(landmarks, handedness: str, flipped: bool) -> bool:
    """Rule-based check: are all five fingers extended?"""
    if len(landmarks) < 21:
        return False
    right_like = (handedness == "Right") ^ flipped
    if right_like:
        thumb_ok = landmarks[_THUMB_TIP].x < landmarks[_THUMB_IP].x
    else:
        thumb_ok = landmarks[_THUMB_TIP].x > landmarks[_THUMB_IP].x
    if not thumb_ok:
        return False
    for tip, pip in (
        (_INDEX_TIP, _INDEX_PIP),
        (_MIDDLE_TIP, _MIDDLE_PIP),
        (_RING_TIP, _RING_PIP),
        (_PINKY_TIP, _PINKY_PIP),
    ):
        if landmarks[tip].y >= landmarks[pip].y:
            return False
    return True


def compute_hand_flags(landmarks, handedness: str, flipped: bool) -> "HandFlags":
    """Build HandFlags from raw MediaPipe landmarks for palms_down detection."""
    if landmarks is None:
        return HandFlags()
    all5 = _all_fingers_extended(landmarks, handedness, flipped)
    up = _fingers_point_up(landmarks)
    return HandFlags(present=True, all5_extended=all5, fingers_up=up)


# Motion labels
MOTION_CHOP = "chop_motion"
MOTION_STIR = "stir_motion"
MOTION_HANDS_TOGETHER = "hands_together"
MOTION_PALMS_DOWN = "palms_down"

# Two-hand event thresholds (unchanged)
_HANDS_TOGETHER_DIST = 0.12
_HANDS_TOGETHER_FRAMES = 8
_PALMS_DOWN_FRAMES = 6
_COOLDOWN_S = 0.3

# ---------------------------------------------------------------------------
#  Sliding-window oscillation parameters (from gshan branch)
# ---------------------------------------------------------------------------

# Minimum direction reversals with sufficient amplitude for chop/stir
_OSCILLATION_MIN = 3

# Minimum amplitude per reversal (normalized coords, 5% of screen)
_OSCILLATION_AMP = 0.05

# Large-amplitude shortcut: if amp >= this, 1 reversal is enough
_OSCILLATION_AMP_LARGE = 0.20

# Chop vs stir axis dominance ratio
_AXIS_DOMINANCE = 1.5

# Recent-frames window for amplitude gate (prevents stale buffer interference)
_RECENT_FRAMES = 25

# Hold frames: maintain gesture for N frames before returning to idle
_HOLD_FRAMES = 8

# Gap filling: max frames to cache wrist position when hand is absent
_HAND_CACHE_MAX = 4

# Still detection: wrist speed below this = "still"
_STILL_SPEED_MAX = 0.006

# Still detection: consecutive still frames before buffer reset
_STILL_RESET_FRAMES = 10


@dataclass
class HandFlags:
    """Per-hand snapshot used to gate motion detection."""

    present: bool = False       # hand is currently tracked
    all5_extended: bool = False  # all five fingers detected as extended
    fingers_up: bool = False     # fingertips clearly above wrist


@dataclass
class MotionDebug:
    """Per-hand debug snapshot exposed for tuning overlays."""

    # Cumulative oscillation counts (monotonically increasing until buffer reset)
    chop_osc: int = 0
    stir_osc: int = 0

    # Delta this frame (new strokes since last frame)
    chop_delta: int = 0
    stir_delta: int = 0

    # Full-buffer amplitudes
    y_amp: float = 0.0
    x_amp: float = 0.0

    # Recent-frames amplitudes (used for actual gating)
    r_y_amp: float = 0.0
    r_x_amp: float = 0.0

    # Instantaneous wrist speed
    wrist_speed: float = 0.0

    # Still counter
    still_counter: int = 0

    # Raw detection result before hold
    raw: str = "idle"

    # Hold counter
    hold_counter: int = 0


# ---------------------------------------------------------------------------
#  Oscillation counter (ported from gshan branch)
# ---------------------------------------------------------------------------

def _count_oscillations(buf: np.ndarray, amp_threshold: float) -> int:
    """Count direction reversals with sufficient amplitude in a coordinate
    time series, after moving-average smoothing.

    A reversal is counted when direction changes and the distance from the
    previous extreme point exceeds *amp_threshold*.
    """
    n = len(buf)
    if n < 10:
        return 0

    # Fixed-size smoothing kernel (not proportional to buffer length)
    k = 5
    s = np.convolve(buf, np.ones(k) / k, mode="valid")

    if len(s) < 3:
        return 0

    changes = 0
    last_dir = 0
    last_extreme = float(s[0])

    for i in range(1, len(s)):
        diff = float(s[i]) - float(s[i - 1])
        if abs(diff) < 1e-5:
            continue
        cur_dir = 1 if diff > 0 else -1

        if last_dir != 0 and cur_dir != last_dir:
            extreme = float(s[i - 1])  # direction change point = actual extreme
            if abs(extreme - last_extreme) >= amp_threshold:
                changes += 1
            # Always update reference to prevent stale extreme
            last_extreme = extreme

        last_dir = cur_dir

    return changes


# ---------------------------------------------------------------------------
#  Per-hand motion state
# ---------------------------------------------------------------------------

@dataclass
class _HandMotionState:
    wy: Deque[float] = field(default_factory=deque)  # unbounded
    wx: Deque[float] = field(default_factory=deque)  # unbounded
    last_wrist_pos: Optional[Tuple[float, float]] = None
    wrist_absent: int = 999
    wrist_speed: float = 0.0
    prev_wrist: Optional[Tuple[float, float]] = None
    still_counter: int = 0
    hold_counter: int = 0
    held_gesture: Optional[str] = None  # MOTION_CHOP or MOTION_STIR or None
    # Previous oscillation counts for delta-based counting
    prev_chop_osc: int = 0
    prev_stir_osc: int = 0
    # Remainder of half-strokes not yet forming a full round-trip
    chop_half_remainder: int = 0
    stir_half_remainder: int = 0

class MotionDetector:
    """Detect chop/stir per hand, plus hands_together and palms_down events.

    Chop and stir are detected via sliding-window oscillation counting on
    wrist x/y coordinates from hand landmarks (no Pose dependency).

    * **chop** — y-axis oscillation (up-down wrist movement)
    * **stir** — x-axis oscillation (left-right wrist movement)

    ``hand_flags`` lets the detector recognise palms_down (both hands have
    all five fingers extended but are NOT pointing up).
    """

    def __init__(self) -> None:
        self._state: Dict[str, _HandMotionState] = {
            "left": _HandMotionState(),
            "right": _HandMotionState(),
        }
        self._together_streak = 0
        self._last_together_t = 0.0
        self._palms_down_streak = 0
        self._last_palms_down_t = 0.0
        # Debug info populated every update(), keyed by "left"/"right".
        self.debug: Dict[str, MotionDebug] = {
            "left": MotionDebug(),
            "right": MotionDebug(),
        }

    def update(
        self,
        hand_flags: Dict[str, HandFlags],
        hand_wrists: Optional[Dict[str, Optional[Tuple[float, float]]]] = None,
        now: Optional[float] = None,
    ) -> Dict[str, Tuple[Optional[str], float, int]]:
        """Feed per-hand flag snapshot + hand wrist positions.

        Args:
            hand_flags: Per-hand flags for palms_down detection.
            hand_wrists: Per-hand wrist (x, y) from hand landmarks. Used for
                chop/stir oscillation and hands_together distance.
                Keys: "left", "right".

        Returns:
            mapping {"left": (label_or_None, confidence, count),
                     "right": (...),
                     "both": (two_hand_event_or_None, conf, 0)}
            count = new motion strokes this frame (0, 1, or rarely 2+).
        """
        if now is None:
            now = perf_counter()

        if hand_wrists is None:
            hand_wrists = {}

        results: Dict[str, Tuple[Optional[str], float, int]] = {
            "left": (None, 0.0, 0),
            "right": (None, 0.0, 0),
            "both": (None, 0.0, 0),
        }

        # --- per-hand chop/stir detection via oscillation counting ---
        for hand in ("left", "right"):
            st = self._state[hand]
            wrist_pos = hand_wrists.get(hand)

            if wrist_pos is not None:
                wx, wy = wrist_pos
                st.wy.append(wy)
                st.wx.append(wx)

                # Wrist speed (max of x/y delta)
                if st.prev_wrist is not None:
                    st.wrist_speed = max(
                        abs(wx - st.prev_wrist[0]),
                        abs(wy - st.prev_wrist[1]),
                    )
                else:
                    st.wrist_speed = 0.0
                st.prev_wrist = (wx, wy)
                st.last_wrist_pos = (wx, wy)
                st.wrist_absent = 0
            else:
                # Gap filling: use last known position
                if st.last_wrist_pos and st.wrist_absent < _HAND_CACHE_MAX:
                    st.wy.append(st.last_wrist_pos[1])
                    st.wx.append(st.last_wrist_pos[0])
                st.wrist_absent += 1
                st.wrist_speed = 0.0
                st.prev_wrist = None

            # Still detection: reset buffers when hand stops moving
            if wrist_pos is not None and st.wrist_speed < _STILL_SPEED_MAX:
                st.still_counter += 1
                if st.still_counter >= _STILL_RESET_FRAMES:
                    st.wy.clear()
                    st.wx.clear()
                    st.prev_chop_osc = 0
                    st.prev_stir_osc = 0
            else:
                st.still_counter = 0

            # Convert to numpy once
            wy_arr = np.array(st.wy, dtype=np.float32) if st.wy else np.empty(0, dtype=np.float32)
            wx_arr = np.array(st.wx, dtype=np.float32) if st.wx else np.empty(0, dtype=np.float32)

            y_amp = float(wy_arr.max() - wy_arr.min()) if len(wy_arr) > 0 else 0.0
            x_amp = float(wx_arr.max() - wx_arr.min()) if len(wx_arr) > 0 else 0.0
            chop_osc = _count_oscillations(wy_arr, _OSCILLATION_AMP)
            stir_osc = _count_oscillations(wx_arr, _OSCILLATION_AMP)
            # Remainder of half-strokes not yet forming a full round-trip
            chop_half_remainder: int = 0
            stir_half_remainder: int = 0
            
            # Recent-frames amplitude gate
            recent_n = min(len(wy_arr), _RECENT_FRAMES)
            if recent_n > 0:
                r_y_amp = float(wy_arr[-recent_n:].max() - wy_arr[-recent_n:].min())
                r_x_amp = float(wx_arr[-recent_n:].max() - wx_arr[-recent_n:].min())
            else:
                r_y_amp = r_x_amp = 0.0

            # Delta: new strokes since last frame
            chop_delta = max(0, chop_osc - st.prev_chop_osc)
            stir_delta = max(0, stir_osc - st.prev_stir_osc)
            st.prev_chop_osc = chop_osc
            st.prev_stir_osc = stir_osc

            # Chop / stir judgment
            is_chop = (
                (chop_osc >= _OSCILLATION_MIN)
                or (y_amp >= _OSCILLATION_AMP_LARGE and chop_osc >= 1)
            ) and r_y_amp >= _OSCILLATION_AMP

            is_stir = (
                (stir_osc >= _OSCILLATION_MIN)
                or (x_amp >= _OSCILLATION_AMP_LARGE and stir_osc >= 1)
            ) and r_x_amp >= _OSCILLATION_AMP

            raw = None
            if is_chop and is_stir:
                if r_y_amp > r_x_amp * _AXIS_DOMINANCE:
                    raw = MOTION_CHOP
                elif r_x_amp > r_y_amp * _AXIS_DOMINANCE:
                    raw = MOTION_STIR
            elif is_chop:
                raw = MOTION_CHOP
            elif is_stir:
                raw = MOTION_STIR

            # Hold mechanism: maintain gesture before dropping to idle
            if raw is not None:
                st.held_gesture = raw
                st.hold_counter = _HOLD_FRAMES
                output = raw
            elif st.hold_counter > 0:
                st.hold_counter -= 1
                output = st.held_gesture
            else:
                output = None

            # Only emit delta for the active motion type
            active_chop_delta = chop_delta if output == MOTION_CHOP else 0
            active_stir_delta = stir_delta if output == MOTION_STIR else 0

            # Populate debug
            self.debug[hand] = MotionDebug(
                chop_osc=chop_osc,
                stir_osc=stir_osc,
                chop_delta=active_chop_delta,
                stir_delta=active_stir_delta,
                y_amp=y_amp,
                x_amp=x_amp,
                r_y_amp=r_y_amp,
                r_x_amp=r_x_amp,
                wrist_speed=st.wrist_speed,
                still_counter=st.still_counter,
                raw=raw or "idle",
                hold_counter=st.hold_counter,
            )

            if output is not None:
                conf = min(1.0, max(r_y_amp, r_x_amp) / _OSCILLATION_AMP)
                # Convert half-stroke deltas to full round-trip counts
                chop_total_halves = active_chop_delta + st.chop_half_remainder
                stir_total_halves = active_stir_delta + st.stir_half_remainder
                chop_rounds = chop_total_halves // 2
                stir_rounds = stir_total_halves // 2
                st.chop_half_remainder = chop_total_halves % 2
                st.stir_half_remainder = stir_total_halves % 2
                count = chop_rounds + stir_rounds
                results[hand] = (output, conf, count)

        # --- two-hand events --------------------------------------------------
        lw = hand_wrists.get("left")
        rw = hand_wrists.get("right")
        together_fired = False
        if lw is not None and rw is not None:
            dx = lw[0] - rw[0]
            dy = lw[1] - rw[1]
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < _HANDS_TOGETHER_DIST:
                self._together_streak += 1
            else:
                self._together_streak = 0
            if (
                self._together_streak >= _HANDS_TOGETHER_FRAMES
                and (now - self._last_together_t) >= _COOLDOWN_S
            ):
                self._last_together_t = now
                conf = min(1.0, 1.0 - dist / _HANDS_TOGETHER_DIST)
                results["both"] = (MOTION_HANDS_TOGETHER, conf, 0)
                together_fired = True
        else:
            self._together_streak = 0

        # palms_down (놓기)
        left_f = hand_flags.get("left", HandFlags())
        right_f = hand_flags.get("right", HandFlags())
        palms_down_now = (
            left_f.present and right_f.present
            and left_f.all5_extended and right_f.all5_extended
            and (not left_f.fingers_up) and (not right_f.fingers_up)
        )
        if palms_down_now:
            self._palms_down_streak += 1
        else:
            self._palms_down_streak = 0

        if (
            not together_fired
            and self._palms_down_streak >= _PALMS_DOWN_FRAMES
            and (now - self._last_palms_down_t) >= _COOLDOWN_S
        ):
            self._last_palms_down_t = now
            results["both"] = (MOTION_PALMS_DOWN, 1.0, 0)

        return results
