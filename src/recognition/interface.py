"""Unified recognition pipeline and HandInput interface for Part B."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# Hand landmark index for wrist
_LM_WRIST = 0

import numpy as np

from .camera import CameraConfig, open_camera
from .gesture import (
    LABEL_THUMBS_UP,
    LABEL_UNKNOWN,
    GestureClassifierDNN,
    landmarks_to_numpy,
    target_slot_for,
)
from .hand_split import HandSplitter
from .hand_tracker import HandTracker, HandTrackerConfig
from .motion import MotionDebug, MotionDetector, compute_hand_flags


@dataclass
class HandInput:
    """Per-frame, per-hand input payload for Part B (game engine)."""

    hand_id: str                           # "left" or "right"
    position: Tuple[float, float]          # normalized (x, y) in 0~1
    gesture: str                           # finger_1..5 | thumbs_up | unknown
    finger_count: int                      # 0~5
    target_slot: Optional[int]             # 1..5 when finger_N, else None
    gesture_confirmed: bool                # debounce-confirmed this frame
    motion: Optional[str]                  # chop/stir/hands_together/palms_down/thumbs_up/None
    motion_confidence: float               # 0.0~1.0
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

        self._cap = open_camera(self.camera_cfg)
        self._hands = HandTracker(self.hand_cfg)
        self._splitter = HandSplitter()
        self._motion = MotionDetector()
        self._gesture_dnn = GestureClassifierDNN(
            onnx_path=gesture_onnx_path,
            confidence_threshold=gesture_confidence,
        )

        self._last_frame = None

    @property
    def last_frame(self):
        return self._last_frame

    @property
    def fps(self) -> float:
        return self._hands.fps

    @property
    def motion_debug(self) -> Dict[str, MotionDebug]:
        return self._motion.debug

    def _mp_handedness_label(self, hand_id: str) -> str:
        """Map splitter's viewer-perspective hand_id to MediaPipe subject label."""
        mp_label = "Right" if hand_id == "left" else "Left"
        if self.flip:
            mp_label = "Left" if mp_label == "Right" else "Right"
        return mp_label

    def step(self, draw_overlay: bool = False) -> List[HandInput]:
        ok, frame = self._cap.read()
        if not ok:
            return []
        if self.flip:
            import cv2

            frame = cv2.flip(frame, 1)

        hand_results = self._hands.process(frame, draw=draw_overlay)
        hands = self._splitter.update(hand_results, flipped=self.flip)

        # Per-hand gesture (DNN) + hand flags (rule-based for motion)
        per_hand_label: Dict[str, str] = {}
        per_hand_count: Dict[str, int] = {}
        per_hand_confirmed: Dict[str, bool] = {}
        hand_flags: Dict[str, object] = {}

        for hand_id in ("left", "right"):
            state = hands[hand_id]
            if state.landmarks is None:
                label, _ = state.debouncer.update(LABEL_UNKNOWN)
                per_hand_label[hand_id] = label
                per_hand_count[hand_id] = 0
                per_hand_confirmed[hand_id] = False
                hand_flags[hand_id] = compute_hand_flags(None, "", False)
                continue

            mp_label = self._mp_handedness_label(hand_id)

            # DNN gesture classification
            lm_np = landmarks_to_numpy(state.landmarks)
            raw_label, _conf, count = self._gesture_dnn.predict(lm_np)
            label, just_confirmed = state.debouncer.update(raw_label)

            per_hand_label[hand_id] = label
            per_hand_count[hand_id] = count
            per_hand_confirmed[hand_id] = just_confirmed

            # Rule-based flags for motion.py's palms_down detection
            hand_flags[hand_id] = compute_hand_flags(
                state.landmarks, mp_label, self.flip,
            )

        # Extract wrist positions from hand landmarks for chop/stir detection
        hand_wrists: Dict[str, Optional[Tuple[float, float]]] = {}
        for hand_id in ("left", "right"):
            state = hands[hand_id]
            if state.landmarks is not None:
                wlm = state.landmarks[_LM_WRIST]
                hand_wrists[hand_id] = (wlm.x, wlm.y)
            else:
                hand_wrists[hand_id] = None

        # Motion detection (chop / stir / hands_together / palms_down)
        motion_results = self._motion.update(hand_flags, hand_wrists)
        both_label, both_conf = motion_results.get("both", (None, 0.0))

        outputs: List[HandInput] = []
        for hand_id in ("left", "right"):
            state = hands[hand_id]
            pos = state.position_norm or (0.0, 0.0)
            label = per_hand_label[hand_id]
            count = per_hand_count[hand_id]
            confirmed = per_hand_confirmed[hand_id]
            per_motion, per_conf = motion_results.get(hand_id, (None, 0.0))

            if both_label is not None:
                per_motion = both_label
                per_conf = max(per_conf, both_conf)

            # Promote thumbs_up gesture → motion field on confirmation frame
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
                    stale=state.stale,
                )
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
