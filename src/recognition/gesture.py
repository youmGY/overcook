"""Finger-state based gesture classifier with debouncing.

Label set (no ``fist``, ``open`` is replaced by ``finger_5``):

    finger_1   : index only                   → slot 1
    finger_2   : index + middle               → slot 2
    finger_3   : index + middle + ring        → slot 3
    finger_4   : index + middle + ring + pinky (no thumb) → slot 4
    finger_5   : all five extended AND fingers pointing up → slot 5
    thumbs_up  : thumb only                   → 완성 (complete)
    unknown    : anything else

``finger_5`` vs 놓기(palms_down): ``finger_5`` requires fingertips to sit
clearly above the wrist (hand held vertically, palm facing camera). When all
five fingers are extended but the hand is horizontal / palm-down, we return
``unknown`` here so that [motion.py](motion.py)'s ``palms_down`` detector
can claim it instead.

``finger_1`` vs 완성(thumbs_up): both have a single extended finger, but
``finger_1`` is strictly the index and ``thumbs_up`` is strictly the thumb.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

# Hand landmark indices
WRIST = 0
THUMB_TIP, THUMB_IP = 4, 3
INDEX_TIP, INDEX_PIP = 8, 6
MIDDLE_TIP, MIDDLE_PIP = 12, 10
RING_TIP, RING_PIP = 16, 14
PINKY_TIP, PINKY_PIP = 20, 18

# Canonical labels used across the pipeline
LABEL_FINGER_1 = "finger_1"
LABEL_FINGER_2 = "finger_2"
LABEL_FINGER_3 = "finger_3"
LABEL_FINGER_4 = "finger_4"
LABEL_FINGER_5 = "finger_5"
LABEL_THUMBS_UP = "thumbs_up"
LABEL_UNKNOWN = "unknown"

# How far above the wrist (in normalized y) the average fingertip must sit
# for the hand to count as "pointing up".
_FINGERS_UP_MARGIN = 0.05


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


def fingers_point_up(landmarks: Sequence) -> bool:
    """True when the four non-thumb fingertips sit clearly above the wrist.

    This separates a hand held vertically (``finger_5``) from a hand held
    horizontally with the palm facing down (part of the 놓기 / palms_down
    motion detected in motion.py).
    """
    if len(landmarks) < 21:
        return False
    wrist_y = landmarks[WRIST].y
    tips = [
        landmarks[INDEX_TIP].y,
        landmarks[MIDDLE_TIP].y,
        landmarks[RING_TIP].y,
        landmarks[PINKY_TIP].y,
    ]
    avg_tip = sum(tips) / len(tips)
    # y grows downward; smaller y = higher on screen.
    return (wrist_y - avg_tip) > _FINGERS_UP_MARGIN


def classify(states: Sequence[bool], fingers_up: bool) -> Tuple[str, int]:
    """Classify a finger-state pattern into a gesture label.

    ``fingers_up`` comes from :func:`fingers_point_up` and is only consulted
    for the 5-finger case so that palm-down hands are routed to the motion
    detector rather than being reported as ``finger_5``.
    """
    count = sum(1 for s in states if s)
    thumb, index, middle, ring, pinky = states

    if count == 1:
        # Strict separation between thumbs_up (완성) and finger_1 (검지).
        if thumb and not (index or middle or ring or pinky):
            return LABEL_THUMBS_UP, 1
        if index and not (thumb or middle or ring or pinky):
            return LABEL_FINGER_1, 1
        return LABEL_UNKNOWN, 1

    if count == 2:
        # peace sign: index + middle only
        if index and middle and not (thumb or ring or pinky):
            return LABEL_FINGER_2, 2
        return LABEL_UNKNOWN, 2

    if count == 3:
        if index and middle and ring and not (thumb or pinky):
            return LABEL_FINGER_3, 3
        return LABEL_UNKNOWN, 3

    if count == 4:
        if index and middle and ring and pinky and not thumb:
            return LABEL_FINGER_4, 4
        return LABEL_UNKNOWN, 4

    if count == 5:
        if fingers_up:
            return LABEL_FINGER_5, 5
        # 5 extended but fingers not pointing up — let motion.py decide
        # whether this is part of a two-hand palms_down (놓기) event.
        return LABEL_UNKNOWN, 5

    return LABEL_UNKNOWN, count


def target_slot_for(label: str) -> Optional[int]:
    if label in (
        LABEL_FINGER_1,
        LABEL_FINGER_2,
        LABEL_FINGER_3,
        LABEL_FINGER_4,
        LABEL_FINGER_5,
    ):
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
