"""Chop / stir motion detection.

Semantic mapping:

    chop_motion      : 썰기    (single hand, y-axis oscillation)
    stir_motion      : 조리    (single hand, x-axis oscillation)

Chop / stir detection uses a sliding-window oscillation counting approach:
wrist x/y coordinates are buffered and direction reversals with sufficient
amplitude are counted.  Only hand-landmark wrist positions are required.

완성 is the per-frame ``thumbs_up`` gesture and is handled in
[gesture.py](gesture.py) / [interface.py](interface.py); it does not flow
through this detector.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from time import perf_counter
from typing import Deque, Dict, Optional, Tuple

import numpy as np

# Motion labels
MOTION_CHOP = "chop_motion"
MOTION_STIR = "stir_motion"

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


class MotionDetector:
    """Detect chop/stir per hand via wrist oscillation counting.

    * **chop** — y-axis oscillation (up-down wrist movement)
    * **stir** — x-axis oscillation (left-right wrist movement)
    """

    def __init__(self) -> None:
        self._state: Dict[str, _HandMotionState] = {
            "left": _HandMotionState(),
            "right": _HandMotionState(),
        }
        self.debug: Dict[str, MotionDebug] = {
            "left": MotionDebug(),
            "right": MotionDebug(),
        }

    def update(
        self,
        hand_wrists: Optional[Dict[str, Optional[Tuple[float, float]]]] = None,
        now: Optional[float] = None,
    ) -> Dict[str, Tuple[Optional[str], float, int]]:
        """Feed per-hand wrist positions and detect chop/stir.

        Args:
            hand_wrists: Per-hand wrist (x, y) from hand landmarks.
                Keys: "left", "right".

        Returns:
            mapping {"left": (label_or_None, confidence, count),
                     "right": (...)}
            count = new motion strokes this frame (0, 1, or rarely 2+).
        """
        if now is None:
            now = perf_counter()

        if hand_wrists is None:
            hand_wrists = {}

        results: Dict[str, Tuple[Optional[str], float, int]] = {
            "left": (None, 0.0, 0),
            "right": (None, 0.0, 0),
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
                count = active_chop_delta + active_stir_delta
                results[hand] = (output, conf, count)

        return results
