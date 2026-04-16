"""Finger-state based gesture classifier with debouncing."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

# Hand landmark indices
THUMB_TIP, THUMB_IP = 4, 3
INDEX_TIP, INDEX_PIP = 8, 6
MIDDLE_TIP, MIDDLE_PIP = 12, 10
RING_TIP, RING_PIP = 16, 14
PINKY_TIP, PINKY_PIP = 20, 18

# Canonical labels used across the pipeline
LABEL_FIST = "fist"
LABEL_OPEN = "open"
LABEL_UNKNOWN = "unknown"


def finger_states(
    landmarks: Sequence,  # list of objects with .x .y (normalized)
    handedness: str,  # "Left" or "Right" (MediaPipe)
    flipped: bool = False,
) -> List[bool]:
    """Return a list [thumb, index, middle, ring, pinky] of True=extended.

    The image may be mirrored (selfie view). When ``flipped`` is True, the
    thumb direction is reversed before comparison.
    """
    if len(landmarks) < 21:
        return [False] * 5

    states: List[bool] = []

    # Thumb: compare x of tip vs ip. Direction depends on handedness/flip.
    # MediaPipe's handedness is from the subject's view.
    # For a Right hand in non-flipped image, thumb tip is to the LEFT of ip
    # when extended (tip.x < ip.x). In flipped (selfie) view, inverted.
    right_like = (handedness == "Right") ^ flipped
    if right_like:
        thumb_extended = landmarks[THUMB_TIP].x < landmarks[THUMB_IP].x
    else:
        thumb_extended = landmarks[THUMB_TIP].x > landmarks[THUMB_IP].x
    states.append(thumb_extended)

    # Other four fingers: tip.y < pip.y → extended (y grows downward).
    for tip, pip in (
        (INDEX_TIP, INDEX_PIP),
        (MIDDLE_TIP, MIDDLE_PIP),
        (RING_TIP, RING_PIP),
        (PINKY_TIP, PINKY_PIP),
    ):
        states.append(landmarks[tip].y < landmarks[pip].y)
    return states


def classify(states: Sequence[bool]) -> Tuple[str, int]:
    """Return (label, finger_count). See copilot-plan.md table."""
    count = sum(1 for s in states if s)
    if count == 0:
        return LABEL_FIST, 0
    if count == 5:
        return LABEL_OPEN, 5

    thumb, index, middle, ring, pinky = states
    # Canonical finger-count patterns. Accept a couple of common variants.
    if count == 1:
        # index only (or thumb only)
        if index and not any([middle, ring, pinky]):
            return "finger_1", 1
        if thumb and not any([index, middle, ring, pinky]):
            return "finger_1", 1
        return LABEL_UNKNOWN, 1
    if count == 2:
        # peace sign (index+middle) or thumb+index
        if index and middle and not ring and not pinky:
            return "finger_2", 2
        if thumb and index and not middle and not ring and not pinky:
            return "finger_2", 2
        return LABEL_UNKNOWN, 2
    if count == 3:
        # index+middle+ring, or thumb+index+middle
        if index and middle and ring and not pinky:
            return "finger_3", 3
        if thumb and index and middle and not ring and not pinky:
            return "finger_3", 3
        return LABEL_UNKNOWN, 3
    if count == 4:
        # all but thumb
        if index and middle and ring and pinky and not thumb:
            return "finger_4", 4
        return LABEL_UNKNOWN, 4
    return LABEL_UNKNOWN, count


def target_slot_for(label: str) -> Optional[int]:
    if label in ("finger_1", "finger_2", "finger_3", "finger_4"):
        return int(label.split("_")[1])
    return None


@dataclass
class GestureDebouncer:
    """Confirm a gesture only after it persists for N consecutive frames."""

    n: int = 4
    _pending: Optional[str] = None
    _streak: int = 0
    _confirmed: Optional[str] = field(default=None)

    def update(self, label: str) -> Tuple[str, bool]:
        """Feed a raw per-frame label. Return (effective_label, confirmed_now).

        - effective_label: last confirmed label if current hasn't passed debounce,
          otherwise the just-confirmed label.
        - confirmed_now: True on the frame a new confirmation takes effect.
        """
        if label == self._pending:
            self._streak += 1
        else:
            self._pending = label
            self._streak = 1

        confirmed_now = False
        if self._streak >= self.n and self._confirmed != label:
            self._confirmed = label
            confirmed_now = True

        effective = self._confirmed or LABEL_UNKNOWN
        return effective, confirmed_now

    @property
    def confirmed(self) -> Optional[str]:
        return self._confirmed

    def reset(self) -> None:
        self._pending = None
        self._streak = 0
        self._confirmed = None
