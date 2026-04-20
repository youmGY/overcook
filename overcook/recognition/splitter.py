"""Split MediaPipe Hands results into independently-tracked left/right hands."""
from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Dict, List, Optional, Tuple

from .smoothing import EMASmoother, PALM_LANDMARK_INDEX
from .gesture import GestureDebouncer

# How long (seconds) to keep emitting a stale state for a missing hand.
# Fist/side-view often causes longer temporary dropouts than open-palm poses.
_STALE_KEEP_S = 1.2
# If a new detection of opposite handedness lands closer to our last position
# than this (normalized), treat it as an ID swap and retain previous assignment.
_SWAP_DIST = 0.15
_SWAP_HOLD_S = 0.2


@dataclass
class HandState:
    hand_id: str  # "left" or "right"
    landmarks: Optional[List[Any]] = None  # raw mediapipe landmark list
    position_norm: Optional[Tuple[float, float]] = None  # smoothed palm center
    last_seen_t: float = 0.0
    stale: bool = True
    smoother: EMASmoother = field(default_factory=EMASmoother)
    debouncer: GestureDebouncer = field(default_factory=GestureDebouncer)


class HandSplitter:
    """Assigns each MediaPipe hand detection to a stable left/right slot."""

    def __init__(self) -> None:
        self.left = HandState(hand_id="left")
        self.right = HandState(hand_id="right")
        self._last_swap_hold_until = 0.0

    def update(self, results, flipped: bool = False) -> Dict[str, HandState]:
        """Update with MediaPipe Hands ``results``. Returns {"left":..., "right":...}."""
        now = perf_counter()

        detections: List[Tuple[str, Any]] = []  # (label, landmark_list)
        if results and results.multi_hand_landmarks and results.multi_handedness:
            for lms, handed in zip(results.multi_hand_landmarks, results.multi_handedness):
                label = handed.classification[0].label  # "Left" or "Right"
                # MediaPipe's handedness assumes a non-mirrored camera image.
                # If the viewer sees a mirrored (selfie) frame, swap labels so
                # the user's actual left hand is tracked as "left".
                if flipped:
                    label = "Right" if label == "Left" else "Left"
                detections.append((label.lower(), lms.landmark))

        # Resolve detections with swap-guard.
        assigned = {"left": None, "right": None}  # type: Dict[str, Optional[List[Any]]]
        for label, lms in detections:
            target = label if label in ("left", "right") else None
            if target is None:
                continue
            # ID swap guard: if our prior "opposite" hand is closer to this
            # detection than our prior "same" hand, keep previous mapping
            # briefly to avoid flicker.
            palm = lms[PALM_LANDMARK_INDEX]
            det_xy = (palm.x, palm.y)
            same = self.left if target == "left" else self.right
            other = self.right if target == "left" else self.left
            if (
                not same.stale
                and not other.stale
                and same.position_norm is not None
                and other.position_norm is not None
                and now < self._last_swap_hold_until + 1.0
            ):
                d_same = _dist(det_xy, same.position_norm)
                d_other = _dist(det_xy, other.position_norm)
                if d_other + 1e-6 < d_same and d_other < _SWAP_DIST:
                    # Treat as swap: assign to the opposite slot instead.
                    target = "left" if target == "right" else "right"
                    self._last_swap_hold_until = now + _SWAP_HOLD_S

            if assigned[target] is None:
                assigned[target] = lms

        # Write back detected hands
        for slot, state in (("left", self.left), ("right", self.right)):
            lms = assigned[slot]
            if lms is not None:
                palm = lms[PALM_LANDMARK_INDEX]
                smoothed = state.smoother.update((palm.x, palm.y))
                state.landmarks = lms
                state.position_norm = smoothed
                state.last_seen_t = now
                state.stale = False
            else:
                # missing: keep stale for a short window
                if now - state.last_seen_t > _STALE_KEEP_S:
                    state.landmarks = None
                    state.position_norm = None
                    state.stale = True
                    state.smoother.reset()
                    state.debouncer.reset()
                else:
                    state.stale = True

        return {"left": self.left, "right": self.right}


def _dist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
