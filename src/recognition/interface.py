"""Unified recognition pipeline and HandInput interface for Part B."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .camera import CameraConfig, open_camera
from .gesture import (
    LABEL_THUMBS_UP,
    LABEL_UNKNOWN,
    classify,
    finger_states,
    fingers_point_up,
    target_slot_for,
)
from .hand_split import HandSplitter
from .hand_tracker import HandTracker, HandTrackerConfig
from .motion import HandFlags, MotionDetector
from .pose_tracker import PoseTracker, PoseTrackerConfig


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
    """Hands + Pose → HandInput list.

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
        pose_cfg: Optional[PoseTrackerConfig] = None,
        flip: bool = True,
    ) -> None:
        self.camera_cfg = camera_cfg or CameraConfig()
        self.hand_cfg = hand_cfg or HandTrackerConfig()
        self.pose_cfg = pose_cfg or PoseTrackerConfig()
        self.flip = flip

        self._cap = open_camera(self.camera_cfg)
        self._hands = HandTracker(self.hand_cfg)
        self._pose = PoseTracker(self.pose_cfg)
        self._splitter = HandSplitter()
        self._motion = MotionDetector()

        self._last_frame = None

    @property
    def last_frame(self):
        return self._last_frame

    @property
    def fps(self) -> float:
        return self._hands.fps

    def step(self, draw_overlay: bool = False) -> List[HandInput]:
        ok, frame = self._cap.read()
        if not ok:
            return []
        if self.flip:
            import cv2

            frame = cv2.flip(frame, 1)

        hand_results = self._hands.process(frame, draw=draw_overlay)
        pose_joints = self._pose.process(frame)
        if draw_overlay:
            self._pose.draw(frame, pose_joints)

        hands = self._splitter.update(hand_results, flipped=self.flip)

        # Per-hand gesture classification
        per_hand_label: Dict[str, str] = {}
        per_hand_count: Dict[str, int] = {}
        per_hand_confirmed: Dict[str, bool] = {}
        hand_flags: Dict[str, HandFlags] = {}

        for hand_id in ("left", "right"):
            state = hands[hand_id]
            if state.landmarks is None:
                label, _ = state.debouncer.update(LABEL_UNKNOWN)
                per_hand_label[hand_id] = label
                per_hand_count[hand_id] = 0
                per_hand_confirmed[hand_id] = False
                hand_flags[hand_id] = HandFlags()
                continue

            # Translate splitter's "left"/"right" (viewer perspective) back to
            # MediaPipe's subject-perspective label for the thumb check.
            mp_label = "Right" if hand_id == "left" else "Left"
            if self.flip:
                mp_label = "Left" if mp_label == "Right" else "Right"
            states = finger_states(state.landmarks, mp_label, flipped=self.flip)
            up = fingers_point_up(state.landmarks)
            raw_label, count = classify(states, up)
            label, just_confirmed = state.debouncer.update(raw_label)

            per_hand_label[hand_id] = label
            per_hand_count[hand_id] = count
            per_hand_confirmed[hand_id] = just_confirmed
            hand_flags[hand_id] = HandFlags(
                present=True,
                all5_extended=all(states),
                fingers_up=up,
            )

        # Motion detection (chop / stir / hands_together / palms_down)
        motion_results = self._motion.update(pose_joints, hand_flags)
        both_label, both_conf = motion_results.get("both", (None, 0.0))

        outputs: List[HandInput] = []
        for hand_id in ("left", "right"):
            state = hands[hand_id]
            pos = state.position_norm or (0.0, 0.0)
            label = per_hand_label[hand_id]
            count = per_hand_count[hand_id]
            confirmed = per_hand_confirmed[hand_id]
            per_motion, per_conf = motion_results.get(hand_id, (None, 0.0))

            # Two-hand events override per-hand chop/stir for this frame.
            if both_label is not None:
                per_motion = both_label
                per_conf = max(per_conf, both_conf)

            # Promote ``thumbs_up`` gesture (완성) to the motion field on the
            # frame it first debounces, so Part B can treat it as an event.
            if (
                per_motion is None
                and label == LABEL_THUMBS_UP
                and confirmed
            ):
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
            try:
                self._pose.close()
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
