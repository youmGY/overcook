from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Optional

import cv2
import mediapipe as mp


@dataclass(frozen=True)
class HandTrackerConfig:
    max_num_hands: int = 2
    min_detection_confidence: float = 0.7
    min_tracking_confidence: float = 0.6
    model_complexity: int = 0


class HandTracker:
    def __init__(self, config: Optional[HandTrackerConfig] = None) -> None:
        self.config = config or HandTrackerConfig()
        self._mp_hands = mp.solutions.hands
        self._mp_drawing = mp.solutions.drawing_utils
        self._hands = self._mp_hands.Hands(
            model_complexity=self.config.model_complexity,
            max_num_hands=self.config.max_num_hands,
            min_detection_confidence=self.config.min_detection_confidence,
            min_tracking_confidence=self.config.min_tracking_confidence,
        )

        self._prev_ts = perf_counter()
        self._fps = 0.0

    @property
    def fps(self) -> float:
        return self._fps

    def process(self, frame_bgr, draw: bool = True):
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        results = self._hands.process(frame_rgb)

        if draw and results.multi_hand_landmarks:
            for hand_landmarks in results.multi_hand_landmarks:
                self._mp_drawing.draw_landmarks(
                    frame_bgr,
                    hand_landmarks,
                    self._mp_hands.HAND_CONNECTIONS,
                )

        now = perf_counter()
        dt = now - self._prev_ts
        self._prev_ts = now
        if dt > 0:
            self._fps = 0.9 * self._fps + 0.1 * (1.0 / dt)

        return results

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
                f"det={self.config.min_detection_confidence:.1f} | "
                f"mc={self.config.model_complexity}"
            ),
            (10, 52),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

    def close(self) -> None:
        self._hands.close()
