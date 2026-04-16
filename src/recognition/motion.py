"""Chop / stir / hands-together motion detection."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from time import perf_counter
from typing import Deque, Dict, Optional, Tuple

from .pose_tracker import Joint

# Motion labels
MOTION_CHOP = "chop_motion"
MOTION_STIR = "stir_motion"
MOTION_HANDS_TOGETHER = "hands_together"

_WINDOW_SECONDS = 0.6
_MIN_REVERSALS = 3
_MIN_AMPLITUDE = 0.04  # normalized (wrist - elbow) in pose coord space
_MIN_PEAK_SPEED = 0.35  # per second, normalized units
_COOLDOWN_S = 0.3

_HANDS_TOGETHER_DIST = 0.12
_HANDS_TOGETHER_FRAMES = 8


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
    """Detect chop/stir per hand and hands-together across both hands.

    Chop/stir are only reported when the corresponding hand is in "fist" gesture
    state (passed by caller) to reduce false positives.
    """

    def __init__(self) -> None:
        self._state: Dict[str, _HandMotionState] = {
            "left": _HandMotionState(),
            "right": _HandMotionState(),
        }
        self._together_streak = 0
        self._last_together_t = 0.0

    def update(
        self,
        joints: Dict[str, Joint],
        fist_flags: Dict[str, bool],
        now: Optional[float] = None,
    ) -> Dict[str, Tuple[Optional[str], float]]:
        """Feed pose joints + per-hand fist flags. Return motion events per hand.

        Returns:
            mapping {"left": (label_or_None, confidence),
                     "right": (...),
                     "both": (hands_together_or_None, conf)}
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
                # keep samples but don't append; let them age out
                _prune(st.samples, now)
                continue
            rel_x = wrist.x - elbow.x
            rel_y = wrist.y - elbow.y
            st.samples.append((now, rel_x, rel_y))
            _prune(st.samples, now)

            if not fist_flags.get(hand, False):
                continue

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

        # hands_together
        lw = joints.get("left_wrist")
        rw = joints.get("right_wrist")
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
        else:
            self._together_streak = 0

        return results
