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
_OSCILLATION_MIN = 2

# Minimum amplitude per reversal (normalized coords)
_OSCILLATION_AMP_X = 0.03      # stir (horizontal) — wider FOV, normal threshold
_OSCILLATION_AMP_Y = 0.025     # chop (vertical)  — narrower FOV, relaxed threshold

# Large-amplitude shortcut: if amp >= this, 1 reversal is enough
_OSCILLATION_AMP_LARGE_X = 0.12
_OSCILLATION_AMP_LARGE_Y = 0.08

# Minimum wrist speed (per-frame) to consider motion intentional.
# Below this, oscillation is attributed to hand tremor / tracker noise.
_MIN_ACTIVE_SPEED = 0.005

# Number of recent frames for smoothed wrist speed calculation.
_SPEED_WINDOW = 5

# Chop vs stir axis dominance ratio
_AXIS_DOMINANCE = 1.3

# Dual-window sizes for oscillation detection:
# Short window: fast reaction to transitions and fast movements (~0.5s)
_WIN_SHORT = 15
# Long window: catches slow movements that need more context (~1.0s)
_WIN_LONG = 30

# Gap filling: max frames to extrapolate wrist position when hand is absent.
# With fist/side-view, MediaPipe drops detection for many consecutive frames.
# 15 frames ≈ 0.5s of extrapolation bridges typical dropout bursts.
_HAND_CACHE_MAX = 15

# Still detection: wrist speed below this = "still"
_STILL_SPEED_MAX = 0.002

# Still detection: consecutive still frames before buffer reset
_STILL_RESET_FRAMES = 30

# Hold frames: maintain detection for N frames after raw goes idle.
# Bridges detection gaps from partial hand visibility.
_HOLD_FRAMES = 10

# Maximum buffer length (frames) — prevents unbounded growth
_BUFFER_MAXLEN = 120


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
    if n < 6:
        return 0

    # Fixed-size smoothing kernel
    k = min(5, n // 2)
    if k < 2:
        k = 2
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
    wy: Deque[float] = field(default_factory=lambda: deque(maxlen=_BUFFER_MAXLEN))
    wx: Deque[float] = field(default_factory=lambda: deque(maxlen=_BUFFER_MAXLEN))
    last_wrist_pos: Optional[Tuple[float, float]] = None
    last_wrist_vel: Tuple[float, float] = (0.0, 0.0)  # velocity for extrapolation
    wrist_absent: int = 999
    wrist_speed: float = 0.0
    _speed_buf: Deque[float] = field(default_factory=lambda: deque(maxlen=_SPEED_WINDOW))
    avg_speed: float = 0.0
    prev_wrist: Optional[Tuple[float, float]] = None
    still_counter: int = 0
    hold_counter: int = 0
    held_gesture: Optional[str] = None
    # Incremental reversal tracker — O(1) per frame, buffer-independent.
    # Tracks EMA-smoothed direction and counts reversals with amplitude gate.
    _ema_y: Optional[float] = None
    _ema_x: Optional[float] = None
    _dir_y: int = 0   # 1=increasing, -1=decreasing, 0=unknown
    _dir_x: int = 0
    _extreme_y: float = 0.0  # last extreme y value
    _extreme_x: float = 0.0
    _rev_chop: int = 0  # total chop reversals (reset on still)
    _rev_stir: int = 0
    _prev_rev_chop: int = 0  # previous frame's total (for delta)
    _prev_rev_stir: int = 0


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
                    dx = wx - st.prev_wrist[0]
                    dy = wy - st.prev_wrist[1]
                    st.wrist_speed = max(abs(dx), abs(dy))
                    # Store velocity for gap extrapolation
                    st.last_wrist_vel = (dx, dy)
                else:
                    st.wrist_speed = 0.0
                    st.last_wrist_vel = (0.0, 0.0)
                # Smoothed average speed over recent frames
                st._speed_buf.append(st.wrist_speed)
                st.avg_speed = sum(st._speed_buf) / len(st._speed_buf)
                st.prev_wrist = (wx, wy)
                st.last_wrist_pos = (wx, wy)
                st.wrist_absent = 0
            else:
                # Velocity-based extrapolation: predict next position from
                # last known position + velocity.  This preserves the oscillation
                # pattern during brief landmark dropouts instead of flatline.
                if st.last_wrist_pos and st.wrist_absent < _HAND_CACHE_MAX:
                    vx, vy = st.last_wrist_vel
                    # Dampen velocity over consecutive missing frames
                    damp = 0.7 ** (st.wrist_absent + 1)
                    pred_x = st.last_wrist_pos[0] + vx * damp
                    pred_y = st.last_wrist_pos[1] + vy * damp
                    # Clamp to valid normalized range
                    pred_x = max(0.0, min(1.0, pred_x))
                    pred_y = max(0.0, min(1.0, pred_y))
                    st.wy.append(pred_y)
                    st.wx.append(pred_x)
                    st.last_wrist_pos = (pred_x, pred_y)
                st.wrist_absent += 1
                st.wrist_speed = 0.0
                st._speed_buf.append(0.0)
                st.avg_speed = sum(st._speed_buf) / len(st._speed_buf)
                st.prev_wrist = None

            # Still detection: reset buffers when hand stops moving
            if wrist_pos is not None and st.wrist_speed < _STILL_SPEED_MAX:
                st.still_counter += 1
                if st.still_counter >= _STILL_RESET_FRAMES:
                    st.wy.clear()
                    st.wx.clear()
                    st._ema_y = None
                    st._ema_x = None
                    st._dir_y = st._dir_x = 0
                    st._rev_chop = st._rev_stir = 0
                    st._prev_rev_chop = st._prev_rev_stir = 0
            else:
                st.still_counter = 0

            # Convert to numpy once
            wy_arr = np.array(st.wy, dtype=np.float32) if st.wy else np.empty(0, dtype=np.float32)
            wx_arr = np.array(st.wx, dtype=np.float32) if st.wx else np.empty(0, dtype=np.float32)

            # ── Dual-window oscillation detection ──
            # Short window: responsive to fast movement and quick transitions
            # Long window: catches slow oscillations that need more context
            # If EITHER fires → motion is detected.
            sn = min(len(wy_arr), _WIN_SHORT)
            ln = min(len(wy_arr), _WIN_LONG)
            wy_short = wy_arr[-sn:] if sn > 0 else wy_arr
            wx_short = wx_arr[-sn:] if sn > 0 else wx_arr
            wy_long = wy_arr[-ln:] if ln > 0 else wy_arr
            wx_long = wx_arr[-ln:] if ln > 0 else wx_arr

            # Short window
            s_y_amp = float(wy_short.max() - wy_short.min()) if len(wy_short) > 0 else 0.0
            s_x_amp = float(wx_short.max() - wx_short.min()) if len(wx_short) > 0 else 0.0
            s_chop_osc = _count_oscillations(wy_short, _OSCILLATION_AMP_Y)
            s_stir_osc = _count_oscillations(wx_short, _OSCILLATION_AMP_X)

            # Long window
            l_y_amp = float(wy_long.max() - wy_long.min()) if len(wy_long) > 0 else 0.0
            l_x_amp = float(wx_long.max() - wx_long.min()) if len(wx_long) > 0 else 0.0
            l_chop_osc = _count_oscillations(wy_long, _OSCILLATION_AMP_Y)
            l_stir_osc = _count_oscillations(wx_long, _OSCILLATION_AMP_X)

            # Best of both: use whichever window gives better detection
            chop_osc = max(s_chop_osc, l_chop_osc)
            stir_osc = max(s_stir_osc, l_stir_osc)
            r_y_amp = max(s_y_amp, l_y_amp)
            r_x_amp = max(s_x_amp, l_x_amp)

            # Very-recent activity check (~8 frames): user must be moving NOW
            _VERY_RECENT = 8
            vr_n = min(len(wy_arr), _VERY_RECENT)
            if vr_n >= 3:
                vr_y_amp = float(wy_arr[-vr_n:].max() - wy_arr[-vr_n:].min())
                vr_x_amp = float(wx_arr[-vr_n:].max() - wx_arr[-vr_n:].min())
            else:
                vr_y_amp = vr_x_amp = 0.0

            # Chop: NO speed gate — hand naturally has speed=0 at reversal points.
            # Only require oscillation count + amplitude.
            is_chop = (
                (chop_osc >= _OSCILLATION_MIN)
                or (r_y_amp >= _OSCILLATION_AMP_LARGE_Y and chop_osc >= 1)
            ) and r_y_amp >= _OSCILLATION_AMP_Y

            # Stir: speed gate helps filter tremor on x-axis
            moving = st.avg_speed >= _MIN_ACTIVE_SPEED
            is_stir = moving and (
                (stir_osc >= _OSCILLATION_MIN)
                or (r_x_amp >= _OSCILLATION_AMP_LARGE_X and stir_osc >= 1)
            ) and r_x_amp >= _OSCILLATION_AMP_X

            # Determine raw detection with fallback for ambiguous diagonal motion
            raw = None
            if is_chop and is_stir:
                if r_y_amp > r_x_amp * _AXIS_DOMINANCE:
                    raw = MOTION_CHOP
                elif r_x_amp > r_y_amp * _AXIS_DOMINANCE:
                    raw = MOTION_STIR
                else:
                    # Ambiguous diagonal — pick the axis with more oscillations
                    raw = MOTION_CHOP if chop_osc >= stir_osc else MOTION_STIR
            elif is_chop:
                raw = MOTION_CHOP
            elif is_stir:
                raw = MOTION_STIR

            # Short hold: maintain detection for a few frames after raw goes idle.
            # This bridges brief gate failures at direction-reversal points.
            if raw is not None:
                st.held_gesture = raw
                st.hold_counter = _HOLD_FRAMES
                output = raw
            elif st.hold_counter > 0:
                st.hold_counter -= 1
                output = st.held_gesture
            else:
                output = None

            # --- Incremental reversal counting (O(1), buffer-independent) ---
            # EMA-smooth the raw coordinates to filter jitter, then detect
            # direction reversals with sufficient amplitude → 1 reversal = 1 count.
            _EMA_ALPHA = 0.35
            if wrist_pos is not None:
                wx_raw, wy_raw = wrist_pos
                if st._ema_y is None:
                    st._ema_y = wy_raw
                    st._ema_x = wx_raw
                    st._extreme_y = wy_raw
                    st._extreme_x = wx_raw
                else:
                    st._ema_y = _EMA_ALPHA * wy_raw + (1 - _EMA_ALPHA) * st._ema_y
                    st._ema_x = _EMA_ALPHA * wx_raw + (1 - _EMA_ALPHA) * st._ema_x

                # Y-axis (chop) reversal detection
                if st._dir_y != 0:
                    new_dir_y = 1 if st._ema_y > st._extreme_y else (-1 if st._ema_y < st._extreme_y else st._dir_y)
                    if new_dir_y != st._dir_y:
                        if abs(st._ema_y - st._extreme_y) >= _OSCILLATION_AMP_Y:
                            st._rev_chop += 1
                        st._extreme_y = st._ema_y
                        st._dir_y = new_dir_y
                    elif (st._dir_y == 1 and st._ema_y > st._extreme_y) or \
                         (st._dir_y == -1 and st._ema_y < st._extreme_y):
                        st._extreme_y = st._ema_y
                else:
                    # Bootstrap direction
                    if len(st.wy) >= 3:
                        st._dir_y = 1 if st._ema_y > st.wy[-2] else -1
                        st._extreme_y = st._ema_y

                # X-axis (stir) reversal detection
                if st._dir_x != 0:
                    new_dir_x = 1 if st._ema_x > st._extreme_x else (-1 if st._ema_x < st._extreme_x else st._dir_x)
                    if new_dir_x != st._dir_x:
                        if abs(st._ema_x - st._extreme_x) >= _OSCILLATION_AMP_X:
                            st._rev_stir += 1
                        st._extreme_x = st._ema_x
                        st._dir_x = new_dir_x
                    elif (st._dir_x == 1 and st._ema_x > st._extreme_x) or \
                         (st._dir_x == -1 and st._ema_x < st._extreme_x):
                        st._extreme_x = st._ema_x
                else:
                    if len(st.wx) >= 3:
                        st._dir_x = 1 if st._ema_x > st.wx[-2] else -1
                        st._extreme_x = st._ema_x

            # Delta: new reversals this frame
            chop_new = st._rev_chop - st._prev_rev_chop
            stir_new = st._rev_stir - st._prev_rev_stir
            st._prev_rev_chop = st._rev_chop
            st._prev_rev_stir = st._rev_stir

            # Only emit delta for the active motion type
            active_chop_count = chop_new if output == MOTION_CHOP else 0
            active_stir_count = stir_new if output == MOTION_STIR else 0

            # Populate debug
            self.debug[hand] = MotionDebug(
                chop_osc=chop_osc,
                stir_osc=stir_osc,
                chop_delta=active_chop_count,
                stir_delta=active_stir_count,
                y_amp=r_y_amp,
                x_amp=r_x_amp,
                r_y_amp=r_y_amp,
                r_x_amp=r_x_amp,
                wrist_speed=st.wrist_speed,
                still_counter=st.still_counter,
                raw=raw or "idle",
                hold_counter=st.hold_counter,
            )

            if output is not None:
                amp_ref = _OSCILLATION_AMP_Y if output == MOTION_CHOP else _OSCILLATION_AMP_X
                conf = min(1.0, max(r_y_amp, r_x_amp) / amp_ref)
                count = active_chop_count + active_stir_count
                results[hand] = (output, conf, count)

        return results
