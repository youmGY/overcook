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
from itertools import islice
from typing import Deque, Dict, Optional, Tuple

# Motion labels
MOTION_CHOP = "chop_motion"
MOTION_STIR = "stir_motion"

# ---------------------------------------------------------------------------
#  Sliding-window oscillation parameters (from gshan branch)
# ---------------------------------------------------------------------------

# Minimum direction reversals with sufficient amplitude for chop/stir.
# 1 means one-way reversal (편도) is enough to count.
_OSCILLATION_MIN = 1

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

# Recent amplitude window used for confidence and gate checks.
_AMP_WINDOW = 30

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

# Design FPS: all frame-count constants above were tuned for this rate.
# At runtime, constants are scaled by (actual_fps / _DESIGN_FPS).
_DESIGN_FPS = 30

# FPS must exceed this to be trusted (avoids instability during startup).
_FPS_WARMUP_MIN = 8


@dataclass
class MotionDebug:
    """Per-hand debug snapshot exposed for tuning overlays."""

    # Cumulative oscillation counts (monotonically increasing until buffer reset)
    chop_osc: int = 0
    stir_osc: int = 0

    # Delta this frame (new strokes since last frame)
    chop_delta: int = 0
    stir_delta: int = 0

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


def _recent_amplitude(buf: Deque[float], n: int) -> float:
    """Return max-min over the most recent ``n`` samples."""
    if not buf:
        return 0.0
    it = islice(reversed(buf), n)
    first = next(it, None)
    if first is None:
        return 0.0
    lo = hi = first
    for v in it:
        if v < lo:
            lo = v
        elif v > hi:
            hi = v
    return hi - lo


def _push_speed(st: "_HandMotionState", speed: float) -> None:
    if len(st._speed_buf) == st._speed_buf.maxlen:
        st._speed_sum -= st._speed_buf[0]
    st._speed_buf.append(speed)
    st._speed_sum += speed
    st.avg_speed = st._speed_sum / len(st._speed_buf)


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
    _speed_sum: float = 0.0
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
        *,
        fps: Optional[float] = None,
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
        if hand_wrists is None:
            hand_wrists = {}

        results: Dict[str, Tuple[Optional[str], float, int]] = {
            "left": (None, 0.0, 0),
            "right": (None, 0.0, 0),
        }

        # --- FPS-adaptive scaling ---
        # Use design FPS until actual FPS is stable (avoids startup glitches).
        fps_eff = fps if (fps is not None and fps >= _FPS_WARMUP_MIN) else _DESIGN_FPS
        scale = fps_eff / _DESIGN_FPS  # <1 at low FPS

        amp_window = max(8, round(_AMP_WINDOW * scale))
        still_reset = max(6, round(_STILL_RESET_FRAMES * scale))
        hold       = max(3, round(_HOLD_FRAMES * scale))
        cache_max  = max(3, round(_HAND_CACHE_MAX * scale))

        # Per-frame displacement is larger at low FPS for the same physical
        # speed, so scale speed thresholds inversely.
        active_speed_thresh = _MIN_ACTIVE_SPEED / scale
        still_speed_thresh  = _STILL_SPEED_MAX / scale

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
                _push_speed(st, st.wrist_speed)
                st.prev_wrist = (wx, wy)
                st.last_wrist_pos = (wx, wy)
                st.wrist_absent = 0
            else:
                # Velocity-based extrapolation: predict next position from
                # last known position + velocity.  This preserves the oscillation
                # pattern during brief landmark dropouts instead of flatline.
                if st.last_wrist_pos and st.wrist_absent < cache_max:
                    vx, vy = st.last_wrist_vel
                    # Dampen velocity over consecutive missing frames.
                    # Scale exponent so damping is time-consistent across FPS.
                    damp = 0.7 ** ((st.wrist_absent + 1) / scale)
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
                _push_speed(st, 0.0)
                st.prev_wrist = None

            # Still detection: reset buffers when hand stops moving
            if wrist_pos is not None and st.wrist_speed < still_speed_thresh:
                st.still_counter += 1
                if st.still_counter >= still_reset:
                    st.wy.clear()
                    st.wx.clear()
                    st._ema_y = None
                    st._ema_x = None
                    st._dir_y = st._dir_x = 0
                    st._rev_chop = st._rev_stir = 0
                    st._prev_rev_chop = st._prev_rev_stir = 0
                    st._speed_buf.clear()
                    st._speed_sum = 0.0
                    st.avg_speed = 0.0
            else:
                st.still_counter = 0

            # --- Incremental reversal counting (O(1), buffer-independent) ---
            # EMA-smooth the raw coordinates to filter jitter, then detect
            # direction reversals with sufficient amplitude → 1 reversal = 1 count.
            # Scale alpha so EMA time-constant stays consistent across FPS.
            _EMA_ALPHA_BASE = 0.35
            ema_alpha = 1.0 - (1.0 - _EMA_ALPHA_BASE) ** (1.0 / scale)
            if wrist_pos is not None:
                wx_raw, wy_raw = wrist_pos
                if st._ema_y is None:
                    st._ema_y = wy_raw
                    st._ema_x = wx_raw
                    st._extreme_y = wy_raw
                    st._extreme_x = wx_raw
                else:
                    st._ema_y = ema_alpha * wy_raw + (1 - ema_alpha) * st._ema_y
                    st._ema_x = ema_alpha * wx_raw + (1 - ema_alpha) * st._ema_x

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

            # Recent amplitude on buffered coordinates (for gate + confidence)
            r_y_amp = _recent_amplitude(st.wy, amp_window)
            r_x_amp = _recent_amplitude(st.wx, amp_window)

            # Use incremental reversal totals as oscillation counters.
            chop_osc = st._rev_chop
            stir_osc = st._rev_stir

            # Chop: NO speed gate — hand naturally has speed=0 at reversal points.
            is_chop = (
                (chop_osc >= _OSCILLATION_MIN)
                or (r_y_amp >= _OSCILLATION_AMP_LARGE_Y and chop_osc >= 1)
            ) and r_y_amp >= _OSCILLATION_AMP_Y

            # Stir: keep speed gate to reject horizontal tremor.
            moving = st.avg_speed >= active_speed_thresh
            is_stir = moving and (
                (stir_osc >= _OSCILLATION_MIN)
                or (r_x_amp >= _OSCILLATION_AMP_LARGE_X and stir_osc >= 1)
            ) and r_x_amp >= _OSCILLATION_AMP_X

            # Determine raw detection with fallback for ambiguous diagonal motion.
            raw = None
            if is_chop and is_stir:
                if r_y_amp > r_x_amp * _AXIS_DOMINANCE:
                    raw = MOTION_CHOP
                elif r_x_amp > r_y_amp * _AXIS_DOMINANCE:
                    raw = MOTION_STIR
                else:
                    raw = MOTION_CHOP if chop_osc >= stir_osc else MOTION_STIR
            elif is_chop:
                raw = MOTION_CHOP
            elif is_stir:
                raw = MOTION_STIR

            # Short hold: maintain detection for a few frames after raw goes idle.
            if raw is not None:
                st.held_gesture = raw
                st.hold_counter = hold
                output = raw
            elif st.hold_counter > 0:
                st.hold_counter -= 1
                output = st.held_gesture
            else:
                output = None

            # Delta: new reversals this frame
            chop_new = st._rev_chop - st._prev_rev_chop
            stir_new = st._rev_stir - st._prev_rev_stir
            st._prev_rev_chop = st._rev_chop
            st._prev_rev_stir = st._rev_stir

            # Only emit delta for the active motion type
            active_chop_count = chop_new if output == MOTION_CHOP else 0
            active_stir_count = stir_new if output == MOTION_STIR else 0

            # Populate debug
            dbg = self.debug[hand]
            dbg.chop_osc = chop_osc
            dbg.stir_osc = stir_osc
            dbg.chop_delta = active_chop_count
            dbg.stir_delta = active_stir_count
            dbg.r_y_amp = r_y_amp
            dbg.r_x_amp = r_x_amp
            dbg.wrist_speed = st.wrist_speed
            dbg.still_counter = st.still_counter
            dbg.raw = raw or "idle"
            dbg.hold_counter = st.hold_counter

            if output is not None:
                amp_ref = _OSCILLATION_AMP_Y if output == MOTION_CHOP else _OSCILLATION_AMP_X
                conf = min(1.0, max(r_y_amp, r_x_amp) / amp_ref)
                count = active_chop_count + active_stir_count
                results[hand] = (output, conf, count)

        return results
