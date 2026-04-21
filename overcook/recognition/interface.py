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
from .hand_split import HandSplitter
from .hand_tracker import HandTracker, HandTrackerConfig
from .motion import MotionDebug, MotionDetector, compute_hand_flags


_MISSING_GESTURE_HOLD_FRAMES = 10


def _hand_scale_from_landmarks(landmarks) -> Optional[float]:
    """Estimate per-hand scale from landmark geometry in normalized coords."""
    if landmarks is None or len(landmarks) < 21:
        return None
    # Palm width + palm length are both fairly stable across poses.
    i_mcp = landmarks[5]
    p_mcp = landmarks[17]
    wrist = landmarks[0]
    m_mcp = landmarks[9]
    palm_w = ((i_mcp.x - p_mcp.x) ** 2 + (i_mcp.y - p_mcp.y) ** 2) ** 0.5
    palm_l = ((wrist.x - m_mcp.x) ** 2 + (wrist.y - m_mcp.y) ** 2) ** 0.5
    return max(1e-4, max(palm_w, palm_l))


def _apply_clahe(frame_bgr, clahe_obj):
    """Normalize brightness in LAB space to reduce over/under exposure issues."""
    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    l2 = clahe_obj.apply(l_channel)
    return cv2.cvtColor(cv2.merge((l2, a_channel, b_channel)), cv2.COLOR_LAB2BGR)


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
    hand_id: str
    position: Tuple[float, float]
    gesture: str
    finger_count: int
    target_slot: Optional[int]
    gesture_confirmed: bool
    motion: Optional[str]
    motion_confidence: float
    motion_count: int = 0
    stale: bool = False


class RecognitionPipeline:
    """Hands + DNN gesture -> HandInput list."""

    def __init__(
        self,
        camera_cfg: Optional[CameraConfig] = None,
        hand_cfg: Optional[HandTrackerConfig] = None,
        flip: bool = True,
        gesture_onnx_path: Optional[str] = None,
        gesture_confidence: float = 0.6,
        clahe: bool = True,
        clahe_clip: float = 2.0,
        clahe_grid: int = 8,
    ) -> None:
        self.camera_cfg = camera_cfg or CameraConfig()
        self.hand_cfg = hand_cfg or HandTrackerConfig()
        self.flip = flip
        self._clahe = clahe
        self._clahe_clip = clahe_clip
        self._clahe_grid = clahe_grid
        self._clahe_obj = None
        if self._clahe:
            self._clahe_obj = cv2.createCLAHE(
                clipLimit=max(0.1, self._clahe_clip),
                tileGridSize=(max(2, self._clahe_grid), max(2, self._clahe_grid)),
            )

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

    def _mp_handedness_label(self, hand_id: str) -> str:
        mp_label = "Right" if hand_id == "left" else "Left"
        if self.flip:
            mp_label = "Left" if mp_label == "Right" else "Right"
        return mp_label

    def step(self, draw_overlay: bool = False) -> List[HandInput]:
        ok, frame = self._cap.read()
        if not ok:
            return []
        if self.flip:
            frame = cv2.flip(frame, 1)
        if self._clahe:
            frame = _apply_clahe(frame, self._clahe_obj)

        hand_results = self._hands.process(frame, draw=draw_overlay)
        hands = self._splitter.update(hand_results, flipped=self.flip)

        per_hand_label: Dict[str, str] = {}
        per_hand_count: Dict[str, int] = {}
        per_hand_confirmed: Dict[str, bool] = {}
        hand_flags: Dict[str, object] = {}

        for hand_id in ("left", "right"):
            state = hands[hand_id]
            if state.landmarks is None:
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
                hand_flags[hand_id] = compute_hand_flags(None, "", False)
                self._missing_hold[hand_id] += 1
                continue

            self._missing_hold[hand_id] = 0
            mp_label = self._mp_handedness_label(hand_id)

            lm_np = landmarks_to_numpy(state.landmarks)
            is_left = (mp_label == "Left")
            raw_label, _conf, count = self._gesture_dnn.predict(lm_np, is_left)
            label, just_confirmed = state.debouncer.update(raw_label)

            per_hand_label[hand_id] = label
            per_hand_count[hand_id] = _count_from_label(label, fallback=count)
            per_hand_confirmed[hand_id] = just_confirmed
            if label != LABEL_UNKNOWN:
                self._last_stable_label[hand_id] = label
                self._last_stable_count[hand_id] = per_hand_count[hand_id]

            hand_flags[hand_id] = compute_hand_flags(state.landmarks, mp_label, self.flip)

        hand_wrists: Dict[str, Optional[Tuple[float, float]]] = {}
        hand_scales: Dict[str, Optional[float]] = {}
        for hand_id in ("left", "right"):
            state = hands[hand_id]
            if state.landmarks is not None:
                sum_x = 0.0
                sum_y = 0.0
                count = len(state.landmarks)
                for lm in state.landmarks:
                    sum_x += lm.x
                    sum_y += lm.y
                hand_wrists[hand_id] = (sum_x / count, sum_y / count)
                hand_scales[hand_id] = _hand_scale_from_landmarks(state.landmarks)
            else:
                hand_wrists[hand_id] = None
                hand_scales[hand_id] = None

        motion_results = self._motion.update(
            hand_flags,
            hand_wrists,
            fps=self._hands.fps,
            hand_scales=hand_scales,
        )
        both_label, both_conf, _both_cnt = motion_results.get("both", (None, 0.0, 0))

        outputs: List[HandInput] = []
        for hand_id in ("left", "right"):
            state = hands[hand_id]
            pos = state.position_norm or (0.0, 0.0)
            label = per_hand_label[hand_id]
            count = per_hand_count[hand_id]
            confirmed = per_hand_confirmed[hand_id]
            per_motion, per_conf, per_count = motion_results.get(hand_id, (None, 0.0, 0))

            if both_label is not None:
                per_motion = both_label
                per_conf = max(per_conf, both_conf)
                per_count = 0

            if per_motion is None and label == LABEL_THUMBS_UP:
                per_motion = LABEL_THUMBS_UP
                per_conf = 1.0
                per_count = 0

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

        self._last_frame = frame
        return outputs

    def close(self) -> None:
        try:
            self._hands.close()
        finally:
            self._cap.release()


_global_pipeline: Optional[RecognitionPipeline] = None


def get_hand_inputs() -> List[HandInput]:
    global _global_pipeline
    if _global_pipeline is None:
        _global_pipeline = RecognitionPipeline()
    return _global_pipeline.step()


def close_pipeline() -> None:
    global _global_pipeline
    if _global_pipeline is not None:
        _global_pipeline.close()
        _global_pipeline = None
