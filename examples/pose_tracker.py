"""MediaPipe PoseLandmarker wrapper (tasks API, mp 0.10.33+)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Optional

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

_MODELS_DIR = os.path.join(os.path.dirname(__file__), os.pardir, "overcook", "recognition", "models")
_DEFAULT_MODEL = os.path.join(_MODELS_DIR, "pose_landmarker_lite.task")


@dataclass(frozen=True)
class PoseTrackerConfig:
    model_complexity: int = 0  # kept for compat; tasks API uses model file
    min_detection_confidence: float = 0.5
    min_tracking_confidence: float = 0.5
    enable_segmentation: bool = False
    model_path: str = _DEFAULT_MODEL


@dataclass
class Joint:
    x: float  # normalized 0~1
    y: float
    z: float  # relative depth from MediaPipe
    visibility: float


# Upper-body landmark indices (MediaPipe Pose)
LM_LEFT_SHOULDER = 11
LM_RIGHT_SHOULDER = 12
LM_LEFT_ELBOW = 13
LM_RIGHT_ELBOW = 14
LM_LEFT_WRIST = 15
LM_RIGHT_WRIST = 16

_UPPER_BODY_EDGES = [
    (LM_LEFT_SHOULDER, LM_LEFT_ELBOW),
    (LM_LEFT_ELBOW, LM_LEFT_WRIST),
    (LM_RIGHT_SHOULDER, LM_RIGHT_ELBOW),
    (LM_RIGHT_ELBOW, LM_RIGHT_WRIST),
    (LM_LEFT_SHOULDER, LM_RIGHT_SHOULDER),
]

_IDX_MAP = {
    "left_shoulder": LM_LEFT_SHOULDER,
    "right_shoulder": LM_RIGHT_SHOULDER,
    "left_elbow": LM_LEFT_ELBOW,
    "right_elbow": LM_RIGHT_ELBOW,
    "left_wrist": LM_LEFT_WRIST,
    "right_wrist": LM_RIGHT_WRIST,
}


class PoseTracker:
    def __init__(self, config: Optional[PoseTrackerConfig] = None) -> None:
        self.config = config or PoseTrackerConfig()
        base_options = python.BaseOptions(
            model_asset_path=self.config.model_path,
        )
        options = vision.PoseLandmarkerOptions(
            base_options=base_options,
            min_pose_detection_confidence=self.config.min_detection_confidence,
            min_tracking_confidence=self.config.min_tracking_confidence,
            output_segmentation_masks=self.config.enable_segmentation,
        )
        self._detector = vision.PoseLandmarker.create_from_options(options)

    def process(self, frame_bgr) -> Dict[str, Joint]:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._detector.detect(mp_image)

        joints: Dict[str, Joint] = {}
        if not result.pose_landmarks:
            return joints

        lms = result.pose_landmarks[0]  # first person
        for name, idx in _IDX_MAP.items():
            lm = lms[idx]
            vis = lm.visibility if hasattr(lm, "visibility") and lm.visibility is not None else 1.0
            if vis < self.config.min_detection_confidence:
                continue
            z = lm.z if hasattr(lm, "z") and lm.z is not None else 0.0
            joints[name] = Joint(x=lm.x, y=lm.y, z=z, visibility=vis)
        return joints

    def draw(self, frame_bgr, joints: Dict[str, Joint]) -> None:
        if not joints:
            return
        h, w = frame_bgr.shape[:2]

        def to_px(j: Joint):
            return (int(j.x * w), int(j.y * h))

        name_by_idx = {v: k for k, v in _IDX_MAP.items()}
        for a, b in _UPPER_BODY_EDGES:
            ja = joints.get(name_by_idx.get(a, ""))
            jb = joints.get(name_by_idx.get(b, ""))
            if ja is None or jb is None:
                continue
            cv2.line(frame_bgr, to_px(ja), to_px(jb), (255, 200, 0), 2, cv2.LINE_AA)
        for j in joints.values():
            cv2.circle(frame_bgr, to_px(j), 5, (0, 255, 255), -1, cv2.LINE_AA)

    def close(self) -> None:
        self._detector.close()
