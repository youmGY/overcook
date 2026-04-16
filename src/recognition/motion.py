"""Chop / stir / hands-together / palms-down motion detection.

Semantic mapping (see copilot-plan.md):

    chop_motion      : 썰기    (single hand, wrist up-down vs elbow)
    stir_motion      : 조리    (single hand, wrist left-right vs elbow)
    hands_together   : 집기    (both wrists close together, held N frames)
    palms_down       : 놓기    (both hands 5-extended, palm-down, held N frames)

완성 is the per-frame ``thumbs_up`` gesture and is handled in
[gesture.py](gesture.py) / [interface.py](interface.py); it does not flow
through this detector.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from time import perf_counter
from typing import Deque, Dict, Optional, Tuple

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
_MIN_AMPLITUDE = 0.04  # normalized (wrist - elbow) in pose coord space
_MIN_PEAK_SPEED = 0.35  # per second, normalized units
_COOLDOWN_S = 0.3

_HANDS_TOGETHER_DIST = 0.12
_HANDS_TOGETHER_FRAMES = 8

_PALMS_DOWN_FRAMES = 6


@dataclass
class HandFlags:
    """Per-hand snapshot used to gate motion detection."""

    present: bool = False       # hand is currently tracked
    all5_extended: bool = False  # all five fingers detected as extended
    fingers_up: bool = False     # fingertips clearly above wrist


@dataclass
class _HandMotionState:
    samples: Deque[Tuple[float, float, float]] = field(default_factory=lambda: deque())  # (t, rel_x, rel_y)
    last_event_t: Dict[str, float] = field(default_factory=dict)


def _prune(samples: Deque[Tuple[float, float, float]], now: float) -> None:
    while samples and (now - samples[0][0]) > _WINDOW_SECONDS:
        samples.popleft()


def _reversals_and_peak_speed(
    samples: Deque[Tuple[float, float, float]], axis: int
) -> Tuple[int, float, float]:
    """Count sign changes of velocity along axis. Return (reversals, peak_speed, amplitude)."""
    if len(samples) < 3:
        return 0, 0.0, 0.0
    vals = [s[1 + axis] for s in samples]
    times = [s[0] for s in samples]
    amplitude = max(vals) - min(vals)

    peak_speed = 0.0
    reversals = 0
    prev_sign = 0
    for i in range(1, len(vals)):
        dt = times[i] - times[i - 1]
        if dt <= 0:
            continue
        v = (vals[i] - vals[i - 1]) / dt
        peak_speed = max(peak_speed, abs(v))
        sign = 1 if v > 0.005 else (-1 if v < -0.005 else 0)
        if sign != 0 and prev_sign != 0 and sign != prev_sign:
            reversals += 1
        if sign != 0:
            prev_sign = sign
    return reversals, peak_speed, amplitude


class MotionDetector:
    """Detect chop/stir per hand, plus hands_together and palms_down events.

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
            elbow = joints.get(f"{hand}_elbow")
            wrist = joints.get(f"{hand}_wrist")
            st = self._state[hand]
            if elbow is None or wrist is None:
                _prune(st.samples, now)
                continue
            rel_x = wrist.x - elbow.x
            rel_y = wrist.y - elbow.y
            st.samples.append((now, rel_x, rel_y))
            _prune(st.samples, now)

            # chop: y-axis (axis=1)
            rev_y, speed_y, amp_y = _reversals_and_peak_speed(st.samples, axis=1)
            if (
                rev_y >= _MIN_REVERSALS
                and speed_y >= _MIN_PEAK_SPEED
                and amp_y >= _MIN_AMPLITUDE
                and (now - st.last_event_t.get(MOTION_CHOP, 0.0)) >= _COOLDOWN_S
            ):
                conf = min(1.0, (speed_y / _MIN_PEAK_SPEED) * 0.5 + (rev_y / 6.0))
                st.last_event_t[MOTION_CHOP] = now
                results[hand] = (MOTION_CHOP, min(1.0, conf))
                continue

            # stir: x-axis (axis=0)
            rev_x, speed_x, amp_x = _reversals_and_peak_speed(st.samples, axis=0)
            if (
                rev_x >= _MIN_REVERSALS
                and speed_x >= _MIN_PEAK_SPEED
                and amp_x >= _MIN_AMPLITUDE
                and (now - st.last_event_t.get(MOTION_STIR, 0.0)) >= _COOLDOWN_S
            ):
                conf = min(1.0, (speed_x / _MIN_PEAK_SPEED) * 0.5 + (rev_x / 6.0))
                st.last_event_t[MOTION_STIR] = now
                results[hand] = (MOTION_STIR, min(1.0, conf))

        # --- two-hand events --------------------------------------------------
        lw = joints.get("left_wrist")
        rw = joints.get("right_wrist")
        together_fired = False
        if lw is not None and rw is not None:
            dx = lw.x - rw.x
            dy = lw.y - rw.y
            dist = (dx * dx + dy * dy) ** 0.5
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
