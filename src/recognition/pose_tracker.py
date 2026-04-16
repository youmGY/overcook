"""MediaPipe Pose wrapper focused on upper-body joints."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import cv2
import mediapipe as mp


@dataclass(frozen=True)
class PoseTrackerConfig:
    model_complexity: int = 0
    min_detection_confidence: float = 0.5
    min_tracking_confidence: float = 0.5
    enable_segmentation: bool = False


@dataclass
class Joint:
    x: float  # normalized 0~1
    y: float
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


class PoseTracker:
    """Wraps mp.solutions.pose and exposes upper-body joints.

    Note MediaPipe's "left"/"right" labels are from the subject's perspective
    (mirrored from viewer). We keep that convention.
    """

    def __init__(self, config: Optional[PoseTrackerConfig] = None) -> None:
        self.config = config or PoseTrackerConfig()
        self._mp_pose = mp.solutions.pose
        self._pose = self._mp_pose.Pose(
            model_complexity=self.config.model_complexity,
            enable_segmentation=self.config.enable_segmentation,
            min_detection_confidence=self.config.min_detection_confidence,
            min_tracking_confidence=self.config.min_tracking_confidence,
        )

    def process(self, frame_bgr) -> Dict[str, Joint]:
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        results = self._pose.process(frame_rgb)
        joints: Dict[str, Joint] = {}
        if not results.pose_landmarks:
            return joints

        lms = results.pose_landmarks.landmark
        idx_map = {
            "left_shoulder": LM_LEFT_SHOULDER,
            "right_shoulder": LM_RIGHT_SHOULDER,
            "left_elbow": LM_LEFT_ELBOW,
            "right_elbow": LM_RIGHT_ELBOW,
            "left_wrist": LM_LEFT_WRIST,
            "right_wrist": LM_RIGHT_WRIST,
        }
        for name, idx in idx_map.items():
            lm = lms[idx]
            if lm.visibility < self.config.min_detection_confidence:
                continue
            joints[name] = Joint(x=lm.x, y=lm.y, visibility=lm.visibility)
        return joints

    def draw(self, frame_bgr, joints: Dict[str, Joint]) -> None:
        if not joints:
            return
        h, w = frame_bgr.shape[:2]

        def to_px(j: Joint):
            return (int(j.x * w), int(j.y * h))

        name_by_idx = {
            LM_LEFT_SHOULDER: "left_shoulder",
            LM_RIGHT_SHOULDER: "right_shoulder",
            LM_LEFT_ELBOW: "left_elbow",
            LM_RIGHT_ELBOW: "right_elbow",
            LM_LEFT_WRIST: "left_wrist",
            LM_RIGHT_WRIST: "right_wrist",
        }
        for a, b in _UPPER_BODY_EDGES:
            ja = joints.get(name_by_idx[a])
            jb = joints.get(name_by_idx[b])
            if ja is None or jb is None:
                continue
            cv2.line(frame_bgr, to_px(ja), to_px(jb), (255, 200, 0), 2, cv2.LINE_AA)
        for j in joints.values():
            cv2.circle(frame_bgr, to_px(j), 5, (0, 255, 255), -1, cv2.LINE_AA)

    def close(self) -> None:
        self._pose.close()
