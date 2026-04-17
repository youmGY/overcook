"""MediaPipe HandLandmarker wrapper (tasks API, mp 0.10.33+)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from time import perf_counter
from typing import Optional

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

_DEFAULT_MODEL = os.path.join(os.path.dirname(__file__), "hand_landmarker.task")

# Hand landmark connections for drawing
_HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (0, 9), (9, 10), (10, 11), (11, 12),
    (0, 13), (13, 14), (14, 15), (15, 16),
    (0, 17), (17, 18), (18, 19), (19, 20),
    (5, 9), (9, 13), (13, 17),
]


@dataclass(frozen=True)
class HandTrackerConfig:
    max_num_hands: int = 2
    min_detection_confidence: float = 0.7
    min_tracking_confidence: float = 0.6
    model_complexity: int = 0  # kept for compatibility, not used by tasks API
    model_path: str = _DEFAULT_MODEL


class HandTracker:
    def __init__(self, config: Optional[HandTrackerConfig] = None) -> None:
        self.config = config or HandTrackerConfig()
        base_options = python.BaseOptions(
            model_asset_path=self.config.model_path,
        )
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            num_hands=self.config.max_num_hands,
            min_hand_detection_confidence=self.config.min_detection_confidence,
            min_tracking_confidence=self.config.min_tracking_confidence,
        )
        self._detector = vision.HandLandmarker.create_from_options(options)

        self._prev_ts = perf_counter()
        self._fps = 0.0

    @property
    def fps(self) -> float:
        return self._fps

    def process(self, frame_bgr, draw: bool = True):
        """Detect hands and return a result-like object compatible with the
        rest of the pipeline.

        The returned object has:
          .hand_landmarks   — list of landmark lists (each with .x .y .z)
          .handedness       — list of handedness info
          .multi_hand_landmarks  — alias for hand_landmarks
          .multi_handedness      — alias (adapted to old format)
        """
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._detector.detect(mp_image)

        if draw and result.hand_landmarks:
            h, w = frame_bgr.shape[:2]
            for hand_lms in result.hand_landmarks:
                pts = [(int(lm.x * w), int(lm.y * h)) for lm in hand_lms]
                for a, b in _HAND_CONNECTIONS:
                    cv2.line(frame_bgr, pts[a], pts[b], (0, 255, 0), 2, cv2.LINE_AA)
                for pt in pts:
                    cv2.circle(frame_bgr, pt, 4, (0, 0, 255), -1, cv2.LINE_AA)

        now = perf_counter()
        dt = now - self._prev_ts
        self._prev_ts = now
        if dt > 0:
            self._fps = 0.9 * self._fps + 0.1 * (1.0 / dt)

        return _TasksResultAdapter(result)

    def draw_debug_text(self, frame_bgr) -> None:
        cv2.putText(
            frame_bgr,
            f"FPS: {self._fps:5.1f}",
            (10, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame_bgr,
            (
                f"Hands<= {self.config.max_num_hands} | "
                f"det={self.config.min_detection_confidence:.1f}"
            ),
            (10, 52),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

    def close(self) -> None:
        self._detector.close()


class _TasksResultAdapter:
    """Adapts mediapipe.tasks HandLandmarkerResult to the interface expected
    by HandSplitter and the rest of the pipeline."""

    def __init__(self, result) -> None:
        self._result = result

    @property
    def multi_hand_landmarks(self):
        if not self._result.hand_landmarks:
            return None
        return [_LandmarkListAdapter(lms) for lms in self._result.hand_landmarks]

    @property
    def multi_handedness(self):
        if not self._result.handedness:
            return None
        return [_HandednessAdapter(h) for h in self._result.handedness]


class _LandmarkListAdapter:
    """Wraps a list of landmarks to expose a .landmark attribute."""

    def __init__(self, landmarks) -> None:
        self.landmark = landmarks


class _HandednessAdapter:
    """Wraps tasks-API handedness to match solutions-API format.

    solutions: result.multi_handedness[i].classification[0].label
    tasks:     result.handedness[i][0].category_name
    """

    def __init__(self, handedness_list) -> None:
        self.classification = [_CategoryAdapter(handedness_list[0])]


class _CategoryAdapter:
    def __init__(self, category) -> None:
        self.label = category.category_name
