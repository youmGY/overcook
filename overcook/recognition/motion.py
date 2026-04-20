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
from itertools import islice
from time import perf_counter
from typing import Deque, Dict, Optional, Tuple

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
#  Sliding-window oscillation parameters
# ---------------------------------------------------------------------------

_OSCILLATION_MIN_CHOP = 2
_OSCILLATION_MIN_STIR = 2

_OSCILLATION_AMP_X = 0.03
_OSCILLATION_AMP_Y = 0.025

_OSCILLATION_AMP_LARGE_X = 0.12
_OSCILLATION_AMP_LARGE_Y = 0.08

_MIN_ACTIVE_SPEED = 0.005
_SPEED_WINDOW = 5

_AXIS_DOMINANCE = 1.3
_AMP_WINDOW = 30
_HAND_CACHE_MAX = 15
_STILL_SPEED_MAX = 0.002
_STILL_RESET_FRAMES = 30
_HOLD_FRAMES = 10
_BUFFER_MAXLEN = 120
_DESIGN_FPS = 30
_FPS_WARMUP_MIN = 8
_HAND_SCALE_REF = 0.12
_HAND_SCALE_MIN_FACTOR = 0.6
_HAND_SCALE_MAX_FACTOR = 1.6
_HAND_SCALE_EMA_ALPHA = 0.25


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
    if not buf:
        return 0.0
    it = islice(reversed(buf), n)
    first = next(it, None)
    if first is None:
        return 0.0
    lo = hi = first
    for value in it:
        if value < lo:
            lo = value
        elif value > hi:
            hi = value
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
    last_wrist_vel: Tuple[float, float] = (0.0, 0.0)
    wrist_absent: int = 999
    wrist_speed: float = 0.0
    _speed_buf: Deque[float] = field(default_factory=lambda: deque(maxlen=_SPEED_WINDOW))
    _speed_sum: float = 0.0
    avg_speed: float = 0.0
    prev_wrist: Optional[Tuple[float, float]] = None
    still_counter: int = 0
    hold_counter: int = 0
    held_gesture: Optional[str] = None
    _ema_y: Optional[float] = None
    _ema_x: Optional[float] = None
    _dir_y: int = 0
    _dir_x: int = 0
    _extreme_y: float = 0.0
    _extreme_x: float = 0.0
    _rev_chop: int = 0
    _rev_stir: int = 0
    _prev_rev_chop: int = 0
    _prev_rev_stir: int = 0
    hand_scale: float = _HAND_SCALE_REF

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
        *,
        fps: Optional[float] = None,
        hand_scales: Optional[Dict[str, Optional[float]]] = None,
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
        if hand_scales is None:
            hand_scales = {}

        results: Dict[str, Tuple[Optional[str], float, int]] = {
            "left": (None, 0.0, 0),
            "right": (None, 0.0, 0),
            "both": (None, 0.0, 0),
        }

        fps_eff = fps if (fps is not None and fps >= _FPS_WARMUP_MIN) else _DESIGN_FPS
        fps_scale = fps_eff / _DESIGN_FPS
        amp_window = max(8, round(_AMP_WINDOW * fps_scale))
        still_reset = max(6, round(_STILL_RESET_FRAMES * fps_scale))
        hold = max(3, round(_HOLD_FRAMES * fps_scale))
        cache_max = max(3, round(_HAND_CACHE_MAX * fps_scale))

        for hand in ("left", "right"):
            st = self._state[hand]
            wrist_pos = hand_wrists.get(hand)
            hand_scale_now = hand_scales.get(hand)
            if hand_scale_now is not None:
                st.hand_scale = (
                    (1.0 - _HAND_SCALE_EMA_ALPHA) * st.hand_scale
                    + _HAND_SCALE_EMA_ALPHA * hand_scale_now
                )

            hand_factor = max(
                _HAND_SCALE_MIN_FACTOR,
                min(_HAND_SCALE_MAX_FACTOR, st.hand_scale / _HAND_SCALE_REF),
            )

            amp_x_thresh = _OSCILLATION_AMP_X * hand_factor
            amp_y_thresh = _OSCILLATION_AMP_Y * hand_factor
            amp_large_x_thresh = _OSCILLATION_AMP_LARGE_X * hand_factor
            amp_large_y_thresh = _OSCILLATION_AMP_LARGE_Y * hand_factor
            active_speed_thresh = (_MIN_ACTIVE_SPEED / fps_scale) * hand_factor
            still_speed_thresh = (_STILL_SPEED_MAX / fps_scale) * hand_factor

            if wrist_pos is not None:
                wx, wy = wrist_pos
                st.wy.append(wy)
                st.wx.append(wx)

                # Wrist speed (max of x/y delta)
                if st.prev_wrist is not None:
                    dx = wx - st.prev_wrist[0]
                    dy = wy - st.prev_wrist[1]
                    st.wrist_speed = max(abs(dx), abs(dy))
                    st.last_wrist_vel = (dx, dy)
                else:
                    st.wrist_speed = 0.0
                    st.last_wrist_vel = (0.0, 0.0)
                _push_speed(st, st.wrist_speed)
                st.prev_wrist = (wx, wy)
                st.last_wrist_pos = (wx, wy)
                st.wrist_absent = 0
            else:
                if st.last_wrist_pos and st.wrist_absent < cache_max:
                    vx, vy = st.last_wrist_vel
                    damp = 0.7 ** ((st.wrist_absent + 1) / fps_scale)
                    pred_x = max(0.0, min(1.0, st.last_wrist_pos[0] + vx * damp))
                    pred_y = max(0.0, min(1.0, st.last_wrist_pos[1] + vy * damp))
                    st.wy.append(pred_y)
                    st.wx.append(pred_x)
                    st.last_wrist_pos = (pred_x, pred_y)
                st.wrist_absent += 1
                st.wrist_speed = 0.0
                _push_speed(st, 0.0)
                st.prev_wrist = None

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

            _EMA_ALPHA_BASE = 0.35
            ema_alpha = 1.0 - (1.0 - _EMA_ALPHA_BASE) ** (1.0 / fps_scale)
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

                if st._dir_y != 0:
                    new_dir_y = 1 if st._ema_y > st._extreme_y else (-1 if st._ema_y < st._extreme_y else st._dir_y)
                    if new_dir_y != st._dir_y:
                        if abs(st._ema_y - st._extreme_y) >= amp_y_thresh:
                            st._rev_chop += 1
                        st._extreme_y = st._ema_y
                        st._dir_y = new_dir_y
                    elif (st._dir_y == 1 and st._ema_y > st._extreme_y) or (st._dir_y == -1 and st._ema_y < st._extreme_y):
                        st._extreme_y = st._ema_y
                elif len(st.wy) >= 3:
                    st._dir_y = 1 if st._ema_y > st.wy[-2] else -1
                    st._extreme_y = st._ema_y

                if st._dir_x != 0:
                    new_dir_x = 1 if st._ema_x > st._extreme_x else (-1 if st._ema_x < st._extreme_x else st._dir_x)
                    if new_dir_x != st._dir_x:
                        if abs(st._ema_x - st._extreme_x) >= amp_x_thresh:
                            st._rev_stir += 1
                        st._extreme_x = st._ema_x
                        st._dir_x = new_dir_x
                    elif (st._dir_x == 1 and st._ema_x > st._extreme_x) or (st._dir_x == -1 and st._ema_x < st._extreme_x):
                        st._extreme_x = st._ema_x
                elif len(st.wx) >= 3:
                    st._dir_x = 1 if st._ema_x > st.wx[-2] else -1
                    st._extreme_x = st._ema_x

            r_y_amp = _recent_amplitude(st.wy, amp_window)
            r_x_amp = _recent_amplitude(st.wx, amp_window)
            chop_osc = st._rev_chop
            stir_osc = st._rev_stir

            is_chop = (
                (chop_osc >= _OSCILLATION_MIN_CHOP)
                or (r_y_amp >= amp_large_y_thresh and chop_osc >= 2)
            ) and r_y_amp >= amp_y_thresh

            moving = st.avg_speed >= active_speed_thresh
            is_stir = moving and (
                (stir_osc >= _OSCILLATION_MIN_STIR)
                or (r_x_amp >= amp_large_x_thresh and stir_osc >= 2)
            ) and r_x_amp >= amp_x_thresh

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

            if raw is not None:
                st.held_gesture = raw
                st.hold_counter = hold
                output = raw
            elif st.hold_counter > 0:
                st.hold_counter -= 1
                output = st.held_gesture
            else:
                output = None

            # Count one full round trip as 1 action (two reversals = 1 cycle).
            chop_new = (st._rev_chop // 2) - (st._prev_rev_chop // 2)
            stir_new = (st._rev_stir // 2) - (st._prev_rev_stir // 2)
            st._prev_rev_chop = st._rev_chop
            st._prev_rev_stir = st._rev_stir

            active_chop_delta = chop_new if output == MOTION_CHOP else 0
            active_stir_delta = stir_new if output == MOTION_STIR else 0

            dbg = self.debug[hand]
            dbg.chop_osc = chop_osc
            dbg.stir_osc = stir_osc
            dbg.chop_delta = active_chop_delta
            dbg.stir_delta = active_stir_delta
            dbg.r_y_amp = r_y_amp
            dbg.r_x_amp = r_x_amp
            dbg.wrist_speed = st.wrist_speed
            dbg.still_counter = st.still_counter
            dbg.raw = raw or "idle"
            dbg.hold_counter = st.hold_counter

            if output is not None:
                amp_ref = amp_y_thresh if output == MOTION_CHOP else amp_x_thresh
                conf = min(1.0, max(r_y_amp, r_x_amp) / amp_ref)
                count = active_chop_delta + active_stir_delta
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
