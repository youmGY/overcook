"""Unified recognition pipeline and HandInput interface for Part B."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2

from .camera import CameraConfig, ThreadedCamera, open_camera
from .gesture import (
    LABEL_THUMBS_UP,
    LABEL_UNKNOWN,
    GestureClassifierDNN,
    landmarks_to_numpy,
    target_slot_for,
)
from .splitter import HandSplitter
from .hand_tracker import HandTracker, HandTrackerConfig
from .motion import MotionDebug, MotionDetector


# Frames to keep the last stable gesture when landmarks disappear briefly.
_MISSING_GESTURE_HOLD_FRAMES = 10


def _count_from_label(label: str, fallback: int = 0) -> int:
    if label.startswith("finger_"):
        try:
            return int(label.split("_")[1])
        except (IndexError, ValueError):
            return fallback
    if label == LABEL_THUMBS_UP:
        return 1
    if label == LABEL_UNKNOWN:
        return 0
    return fallback


@dataclass
class HandInput:
    """Per-frame, per-hand input payload for Part B (game engine)."""

    hand_id: str                           # "left" or "right"
    position: Tuple[float, float]          # normalized (x, y) in 0~1
    gesture: str                           # finger_1..5 | thumbs_up | unknown
    finger_count: int                      # 0~5
    target_slot: Optional[int]             # 1..5 when finger_N, else None
    gesture_confirmed: bool                # debounce-confirmed this frame
    motion: Optional[str]                  # chop/stir/thumbs_up/None
    motion_confidence: float               # 0.0~1.0
    motion_count: int = 0                  # new chop/stir strokes this frame (0, 1, rarely 2+)
    stale: bool = False


class RecognitionPipeline:
    """Hands + DNN gesture → HandInput list.

    Usage:
        pipe = RecognitionPipeline()
        while running:
            inputs = pipe.step()
        pipe.close()
    """

    def __init__(
        self,
        camera_cfg: Optional[CameraConfig] = None,
        hand_cfg: Optional[HandTrackerConfig] = None,
        flip: bool = True,
        gesture_onnx_path: Optional[str] = None,
        gesture_confidence: float = 0.6,
    ) -> None:
        self.camera_cfg = camera_cfg or CameraConfig()
        self.hand_cfg = hand_cfg or HandTrackerConfig()
        self.flip = flip

        self._cap = ThreadedCamera(open_camera(self.camera_cfg))
        self._hands = HandTracker(self.hand_cfg)
        self._splitter = HandSplitter()
        self._motion = MotionDetector()
        self._gesture_dnn = GestureClassifierDNN(
            onnx_path=gesture_onnx_path,
            confidence_threshold=gesture_confidence,
        )

        self._last_frame = None
        self._missing_hold: Dict[str, int] = {"left": 0, "right": 0}
        self._last_stable_label: Dict[str, str] = {
            "left": LABEL_UNKNOWN,
            "right": LABEL_UNKNOWN,
        }
        self._last_stable_count: Dict[str, int] = {"left": 0, "right": 0}

    @property
    def last_frame(self):
        return self._last_frame

    @property
    def fps(self) -> float:
        return self._hands.fps

    @property
    def motion_debug(self) -> Dict[str, MotionDebug]:
        return self._motion.debug

    def _build_hand_inputs(self, hands, per_hand_label, per_hand_count, per_hand_confirmed, motion_results):
        """Build HandInput list from per-hand data."""
        outputs: List[HandInput] = []
        for hand_id in ("left", "right"):
            state = hands[hand_id]
            pos = state.position_norm or (0.0, 0.0)
            label = per_hand_label[hand_id]
            count = per_hand_count[hand_id]
            confirmed = per_hand_confirmed[hand_id]
            per_motion, per_conf, per_count = motion_results.get(hand_id, (None, 0.0, 0))

            # When no active motion and gesture is thumbs_up → promote to motion field.
            # No hold exists anymore, so motion is None the instant the user stops moving.
            if per_motion is None and label == LABEL_THUMBS_UP and confirmed:
                per_motion = LABEL_THUMBS_UP
                per_conf = 1.0

            outputs.append(
                HandInput(
                    hand_id=hand_id,
                    position=(float(pos[0]), float(pos[1])),
                    gesture=label,
                    finger_count=count,
                    target_slot=target_slot_for(label),
                    gesture_confirmed=confirmed,
                    motion=per_motion,
                    motion_confidence=float(per_conf),
                    motion_count=per_count,
                    stale=state.stale,
                )
            )
        return outputs

    def step(self, draw_overlay: bool = False) -> List[HandInput]:
        ok, frame = self._cap.read()
        if not ok:
            return []
        if self.flip:
            frame = cv2.flip(frame, 1)

        hand_results = self._hands.process(frame, draw=draw_overlay)
        hands = self._splitter.update(hand_results, flipped=self.flip)

        # Per-hand DNN gesture classification
        per_hand_label: Dict[str, str] = {}
        per_hand_count: Dict[str, int] = {}
        per_hand_confirmed: Dict[str, bool] = {}

        for hand_id in ("left", "right"):
            state = hands[hand_id]
            if state.landmarks is None:
                # Briefly keep the last stable gesture across landmark dropouts
                # (common with fist and side-view poses).
                if (
                    self._missing_hold[hand_id] < _MISSING_GESTURE_HOLD_FRAMES
                    and self._last_stable_label[hand_id] != LABEL_UNKNOWN
                ):
                    per_hand_label[hand_id] = self._last_stable_label[hand_id]
                    per_hand_count[hand_id] = self._last_stable_count[hand_id]
                else:
                    label, _ = state.debouncer.update(LABEL_UNKNOWN)
                    per_hand_label[hand_id] = label
                    per_hand_count[hand_id] = 0
                per_hand_confirmed[hand_id] = False
                self._missing_hold[hand_id] += 1
                continue

            self._missing_hold[hand_id] = 0
            lm_np = landmarks_to_numpy(state.landmarks)
            raw_label, _conf, count = self._gesture_dnn.predict(lm_np)
            label, just_confirmed = state.debouncer.update(raw_label)

            per_hand_label[hand_id] = label
            per_hand_count[hand_id] = _count_from_label(label, fallback=count)
            per_hand_confirmed[hand_id] = just_confirmed
            if label != LABEL_UNKNOWN:
                self._last_stable_label[hand_id] = label
                self._last_stable_count[hand_id] = per_hand_count[hand_id]

        # Extract hand centroid for chop/stir detection.
        # Using the mean of ALL 21 landmarks — robust to any hand orientation.
        # When only fingers or hand-edge are visible, specific landmarks
        # (wrist/MCP) overlap and become unstable; the full centroid stays stable.
        hand_wrists: Dict[str, Optional[Tuple[float, float]]] = {}
        for hand_id in ("left", "right"):
            state = hands[hand_id]
            if state.landmarks is not None:
                sx = 0.0
                sy = 0.0
                n = len(state.landmarks)
                for lm in state.landmarks:
                    sx += lm.x
                    sy += lm.y
                cx = sx / n
                cy = sy / n
                hand_wrists[hand_id] = (cx, cy)
            else:
                hand_wrists[hand_id] = None

        # Motion detection (chop / stir)
        motion_results = self._motion.update(hand_wrists, fps=self._hands.fps)

        outputs = self._build_hand_inputs(
            hands, per_hand_label, per_hand_count, per_hand_confirmed, motion_results,
        )
        self._last_frame = frame
        return outputs

    def close(self) -> None:
        try:
            self._hands.close()
        finally:
            self._cap.release()


_global_pipeline: Optional[RecognitionPipeline] = None


def get_hand_inputs() -> List[HandInput]:
    """Return the latest per-hand inputs from a lazily-created global pipeline."""
    global _global_pipeline
    if _global_pipeline is None:
        _global_pipeline = RecognitionPipeline()
    return _global_pipeline.step()


def close_pipeline() -> None:
    global _global_pipeline
    if _global_pipeline is not None:
        _global_pipeline.close()
        _global_pipeline = None
