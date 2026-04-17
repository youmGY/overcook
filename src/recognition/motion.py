"""Chop / stir / hands-together / palms-down motion detection.

Semantic mapping (see copilot-plan.md):

    chop_motion      : 썰기    (single hand, wrist oscillation parallel to
                        elbow→shoulder normal vector)
    stir_motion      : 조리    (single hand, wrist oscillation perpendicular to
                        elbow→shoulder normal vector)
    hands_together   : 집기    (both wrists close together, held N frames)
    palms_down       : 놓기    (both hands 5-extended, palm-down, held N frames)

완성 is the per-frame ``thumbs_up`` gesture and is handled in
[gesture.py](gesture.py) / [interface.py](interface.py); it does not flow
through this detector.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from time import perf_counter
from typing import Deque, Dict, List, Optional, Tuple

from .pose_tracker import Joint

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

_WINDOW_SECONDS = 0.6
_MIN_REVERSALS = 3
_MIN_AMPLITUDE = 0.04  # normalized units
_MIN_PEAK_SPEED = 0.35  # per second, normalized units
_COOLDOWN_S = 0.3

# Ratio threshold: the dominant axis speed must be >= R_MIN times the
# non-dominant axis speed for a frame to count toward chop or stir.
# 2.0 means "the main movement direction is at least twice as fast as the
# other direction".  This is intentionally moderate — a pure up-down chop
# easily reaches 5-10×, while a sloppy but valid chop still clears 2×.
# Going higher (e.g. 3.0) would reject diagonal-ish motions that users
# still perceive as chopping; going lower (e.g. 1.2) would let ambiguous
# motions through.
_R_MIN = 1.2

_HANDS_TOGETHER_DIST = 0.12
_HANDS_TOGETHER_FRAMES = 8

_PALMS_DOWN_FRAMES = 6

# Small epsilon to avoid division by zero in ratio checks.
_EPS = 1e-9


@dataclass
class HandFlags:
    """Per-hand snapshot used to gate motion detection."""

    present: bool = False       # hand is currently tracked
    all5_extended: bool = False  # all five fingers detected as extended
    fingers_up: bool = False     # fingertips clearly above wrist


@dataclass
class MotionDebug:
    """Per-hand debug snapshot exposed for tuning overlays."""

    # Latest instantaneous speeds (from most recent frame pair)
    v_par: float = 0.0
    v_perp: float = 0.0
    ratio_par_over_perp: float = 0.0  # v_par / v_perp (inf → pure parallel)

    # Window-level stats for parallel axis (chop candidate)
    rev_par: int = 0
    speed_par: float = 0.0
    amp_par: float = 0.0

    # Window-level stats for perpendicular axis (stir candidate)
    rev_perp: int = 0
    speed_perp: float = 0.0
    amp_perp: float = 0.0


# ---------------------------------------------------------------------------
#  3-D vector helpers
# ---------------------------------------------------------------------------

def _vec3_sub(a: Tuple[float, float, float],
              b: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vec3_dot(a: Tuple[float, float, float],
              b: Tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _vec3_scale(a: Tuple[float, float, float],
                s: float) -> Tuple[float, float, float]:
    return (a[0] * s, a[1] * s, a[2] * s)


def _vec3_norm(a: Tuple[float, float, float]) -> float:
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _unit_normal(shoulder: Joint, elbow: Joint) -> Optional[Tuple[float, float, float]]:
    """Return unit vector from *elbow* toward *shoulder*, or None if degenerate."""
    v = (shoulder.x - elbow.x, shoulder.y - elbow.y, shoulder.z - elbow.z)
    length = _vec3_norm(v)
    if length < _EPS:
        return None
    return (v[0] / length, v[1] / length, v[2] / length)


def _decompose(
    d: Tuple[float, float, float],
    n: Tuple[float, float, float],
) -> Tuple[float, Tuple[float, float, float]]:
    """Decompose *d* into parallel scalar and perpendicular vector w.r.t. *n*."""
    d_par = _vec3_dot(d, n)
    d_perp = _vec3_sub(d, _vec3_scale(n, d_par))
    return d_par, d_perp


# ---------------------------------------------------------------------------
#  Per-hand sample: (t, d_parallel, d_perp_x, d_perp_y, d_perp_z)
# ---------------------------------------------------------------------------

_Sample = Tuple[float, float, float, float, float]


@dataclass
class _HandMotionState:
    samples: Deque[_Sample] = field(default_factory=lambda: deque())
    last_event_t: Dict[str, float] = field(default_factory=dict)
    # Latest instantaneous speeds (updated each frame for debug overlay)
    last_v_par: float = 0.0
    last_v_perp: float = 0.0


def _prune(samples: Deque[_Sample], now: float) -> None:
    while samples and (now - samples[0][0]) > _WINDOW_SECONDS:
        samples.popleft()


# ---------------------------------------------------------------------------
#  Reversal detection – parallel (1-D scalar)
# ---------------------------------------------------------------------------

def _parallel_reversals(
    samples: Deque[_Sample],
) -> Tuple[int, float, float]:
    """Reversals, peak speed, amplitude along the parallel (d_∥) axis.

    Only frames where ∥-speed dominates ⊥-speed by *_R_MIN* are counted.
    """
    if len(samples) < 3:
        return 0, 0.0, 0.0

    times = [s[0] for s in samples]
    d_pars = [s[1] for s in samples]
    d_perps = [(s[2], s[3], s[4]) for s in samples]

    peak_speed = 0.0
    reversals = 0
    prev_sign = 0

    # Track min/max of d_par across *qualified* frames for amplitude.
    par_min: Optional[float] = None
    par_max: Optional[float] = None

    for i in range(1, len(samples)):
        dt = times[i] - times[i - 1]
        if dt <= 0:
            continue
        v_par = abs(d_pars[i] - d_pars[i - 1]) / dt
        dv_perp = _vec3_sub(d_perps[i], d_perps[i - 1])
        v_perp = _vec3_norm(dv_perp) / dt

        # Ratio gate: only consider this frame if parallel dominates.
        if v_par < _R_MIN * (v_perp + _EPS):
            continue

        peak_speed = max(peak_speed, v_par)

        # Track amplitude from qualified frames.
        if par_min is None:
            par_min = par_max = d_pars[i]
        else:
            par_min = min(par_min, d_pars[i])
            par_max = max(par_max, d_pars[i])

        # Sign of the parallel velocity (signed, not abs).
        v_par_signed = (d_pars[i] - d_pars[i - 1]) / dt
        sign = 1 if v_par_signed > 0.005 else (-1 if v_par_signed < -0.005 else 0)
        if sign != 0 and prev_sign != 0 and sign != prev_sign:
            reversals += 1
        if sign != 0:
            prev_sign = sign

    amplitude = (par_max - par_min) if par_min is not None else 0.0
    return reversals, peak_speed, amplitude


# ---------------------------------------------------------------------------
#  Reversal detection – perpendicular (2-D vector in plane ⊥ n̂)
# ---------------------------------------------------------------------------

def _perp_reversals(
    samples: Deque[_Sample],
) -> Tuple[int, float, float]:
    """Reversals, peak speed, amplitude in the perpendicular plane.

    Only frames where ⊥-speed dominates ∥-speed by *_R_MIN* are counted.
    A reversal is detected when consecutive qualified velocity vectors
    have a negative dot product (angle > 90°).
    """
    if len(samples) < 3:
        return 0, 0.0, 0.0

    times = [s[0] for s in samples]
    d_pars = [s[1] for s in samples]
    d_perps: List[Tuple[float, float, float]] = [(s[2], s[3], s[4]) for s in samples]

    peak_speed = 0.0
    reversals = 0
    prev_v_perp: Optional[Tuple[float, float, float]] = None

    # Collect qualified d_perp points for amplitude calculation.
    qualified_perps: List[Tuple[float, float, float]] = []

    for i in range(1, len(samples)):
        dt = times[i] - times[i - 1]
        if dt <= 0:
            continue
        v_par = abs(d_pars[i] - d_pars[i - 1]) / dt
        dv_perp = _vec3_sub(d_perps[i], d_perps[i - 1])
        v_perp = _vec3_norm(dv_perp) / dt

        # Ratio gate: only consider this frame if perpendicular dominates.
        if v_perp < _R_MIN * (v_par + _EPS):
            continue

        peak_speed = max(peak_speed, v_perp)
        qualified_perps.append(d_perps[i])

        # Velocity vector for reversal detection (not normalized – magnitude
        # doesn't matter, only direction).
        v_vec = _vec3_scale(dv_perp, 1.0 / dt)
        if prev_v_perp is not None and _vec3_dot(v_vec, prev_v_perp) < 0:
            reversals += 1
        prev_v_perp = v_vec

    # Amplitude: max pairwise distance among qualified perpendicular points.
    amplitude = 0.0
    n = len(qualified_perps)
    for i in range(n):
        for j in range(i + 1, n):
            d = _vec3_norm(_vec3_sub(qualified_perps[i], qualified_perps[j]))
            if d > amplitude:
                amplitude = d

    return reversals, peak_speed, amplitude


class MotionDetector:
    """Detect chop/stir per hand, plus hands_together and palms_down events.

    Chop and stir are discriminated by decomposing wrist motion relative to
    the elbow into components parallel and perpendicular to the
    elbow→shoulder **normal vector**:

    * **chop** — dominant oscillation *parallel* to the normal (along the
      upper-arm axis).
    * **stir** — dominant oscillation *perpendicular* to the normal.

    A frame's velocity is only counted toward chop (or stir) when the
    dominant-axis speed exceeds the other axis speed by a factor of
    ``_R_MIN`` (default 2.0).

    ``hand_flags`` passed to :meth:`update` lets the detector recognise
    palms_down (both hands have all five fingers extended but are NOT
    pointing up). This is how we disambiguate ``finger_5`` (movement
    command) from 놓기 (both palms facing downward).
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
        joints: Dict[str, Joint],
        hand_flags: Dict[str, HandFlags],
        now: Optional[float] = None,
    ) -> Dict[str, Tuple[Optional[str], float]]:
        """Feed pose joints + per-hand flag snapshot. Return motion events.

        Returns:
            mapping {"left": (label_or_None, confidence),
                     "right": (...),
                     "both": (two_hand_event_or_None, conf)}

            The ``both`` slot carries ``hands_together`` (집기) or
            ``palms_down`` (놓기); ``hands_together`` takes priority when
            both would fire.
        """
        if now is None:
            now = perf_counter()

        results: Dict[str, Tuple[Optional[str], float]] = {
            "left": (None, 0.0),
            "right": (None, 0.0),
            "both": (None, 0.0),
        }

        for hand in ("left", "right"):
            shoulder = joints.get(f"{hand}_shoulder")
            elbow = joints.get(f"{hand}_elbow")
            wrist = joints.get(f"{hand}_wrist")
            st = self._state[hand]
            if elbow is None or wrist is None or shoulder is None:
                _prune(st.samples, now)
                continue

            # Compute the normal vector (elbow → shoulder).
            n_hat = _unit_normal(shoulder, elbow)
            if n_hat is None:
                _prune(st.samples, now)
                continue

            # Displacement: wrist relative to elbow (3-D).
            d = (wrist.x - elbow.x, wrist.y - elbow.y, wrist.z - elbow.z)

            # Decompose into parallel scalar and perpendicular vector.
            d_par, d_perp = _decompose(d, n_hat)

            st.samples.append((now, d_par, d_perp[0], d_perp[1], d_perp[2]))
            _prune(st.samples, now)

            # Compute instantaneous speeds from last two samples for debug.
            if len(st.samples) >= 2:
                s_prev, s_cur = st.samples[-2], st.samples[-1]
                dt_inst = s_cur[0] - s_prev[0]
                if dt_inst > 0:
                    st.last_v_par = abs(s_cur[1] - s_prev[1]) / dt_inst
                    dv_p = _vec3_sub(
                        (s_cur[2], s_cur[3], s_cur[4]),
                        (s_prev[2], s_prev[3], s_prev[4]),
                    )
                    st.last_v_perp = _vec3_norm(dv_p) / dt_inst

            # --- chop: parallel oscillation ---
            rev_par, speed_par, amp_par = _parallel_reversals(st.samples)

            # --- stir: perpendicular oscillation ---
            rev_perp, speed_perp, amp_perp = _perp_reversals(st.samples)

            # Populate debug info for this hand.
            ratio = st.last_v_par / (st.last_v_perp + _EPS)
            self.debug[hand] = MotionDebug(
                v_par=st.last_v_par,
                v_perp=st.last_v_perp,
                ratio_par_over_perp=ratio,
                rev_par=rev_par,
                speed_par=speed_par,
                amp_par=amp_par,
                rev_perp=rev_perp,
                speed_perp=speed_perp,
                amp_perp=amp_perp,
            )

            if (
                rev_par >= _MIN_REVERSALS
                and speed_par >= _MIN_PEAK_SPEED
                and amp_par >= _MIN_AMPLITUDE
                and (now - st.last_event_t.get(MOTION_CHOP, 0.0)) >= _COOLDOWN_S
            ):
                conf = min(1.0, (speed_par / _MIN_PEAK_SPEED) * 0.5 + (rev_par / 6.0))
                st.last_event_t[MOTION_CHOP] = now
                results[hand] = (MOTION_CHOP, conf)
                continue

            if (
                rev_perp >= _MIN_REVERSALS
                and speed_perp >= _MIN_PEAK_SPEED
                and amp_perp >= _MIN_AMPLITUDE
                and (now - st.last_event_t.get(MOTION_STIR, 0.0)) >= _COOLDOWN_S
            ):
                conf = min(1.0, (speed_perp / _MIN_PEAK_SPEED) * 0.5 + (rev_perp / 6.0))
                st.last_event_t[MOTION_STIR] = now
                results[hand] = (MOTION_STIR, conf)

        # --- two-hand events --------------------------------------------------
        lw = joints.get("left_wrist")
        rw = joints.get("right_wrist")
        together_fired = False
        if lw is not None and rw is not None:
            dx = lw.x - rw.x
            dy = lw.y - rw.y
            dz = lw.z - rw.z
            dist = math.sqrt(dx * dx + dy * dy + dz * dz)
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
                results["both"] = (MOTION_HANDS_TOGETHER, conf)
                together_fired = True
        else:
            self._together_streak = 0

        # palms_down (놓기): both hands have 5 extended fingers AND are NOT
        # pointing up. Hands_together gets priority so that tightly-grouped
        # palms-down hands don't fire both events at once.
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
            results["both"] = (MOTION_PALMS_DOWN, 1.0)

        return results
