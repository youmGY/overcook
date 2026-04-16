"""Unified recognition pipeline and HandInput interface for Part B."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from .camera import CameraConfig, open_camera
from .gesture import (
    LABEL_FIST,
    LABEL_UNKNOWN,
    classify,
    finger_states,
    target_slot_for,
)
from .hand_split import HandSplitter
from .hand_tracker import HandTracker, HandTrackerConfig
from .motion import MotionDetector
from .pose_tracker import PoseTracker, PoseTrackerConfig


@dataclass
class HandInput:
    """Per-frame, per-hand input payload for Part B (game engine).

    Fields mirror copilot-plan.md section 7.
    """

    hand_id: str                          # "left" or "right"
    position: Tuple[float, float]          # normalized (x, y) in 0~1
    gesture: str                           # finger_1..4 | fist | open | unknown
    finger_count: int                      # 0~5
    target_slot: Optional[int]             # 1..4 when finger_N, else None
    gesture_confirmed: bool                # debounce-confirmed this frame
    motion: Optional[str]                  # chop_motion | stir_motion | hands_together | None
    motion_confidence: float               # 0.0~1.0
    stale: bool = False                    # last-seen state used (no fresh detection)


class RecognitionPipeline:
    """Hands + Pose → HandInput list.

    Usage:
        pipe = RecognitionPipeline()
        while running:
            inputs = pipe.step()
            # feed ``inputs`` into the game loop
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
        self._last_motion_both: Tuple[Optional[str], float] = (None, 0.0)

    @property
    def last_frame(self):
        """The most recently read BGR frame (None before first step)."""
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

        # Per-hand gesture
        per_hand_label: dict = {}
        per_hand_count: dict = {}
        per_hand_confirmed: dict = {}
        fist_flags = {"left": False, "right": False}
        for hand_id in ("left", "right"):
            state = hands[hand_id]
            if state.landmarks is None:
                label, confirmed = state.debouncer.update(LABEL_UNKNOWN)
                per_hand_label[hand_id] = label
                per_hand_count[hand_id] = 0
                per_hand_confirmed[hand_id] = False
                continue
            # Map splitter's "left"/"right" back to MediaPipe's perspective
            # for the thumb direction check.
            mp_label = "Right" if hand_id == "left" else "Left"
            if self.flip:
                mp_label = "Left" if mp_label == "Right" else "Right"
            states = finger_states(state.landmarks, mp_label, flipped=self.flip)
            raw_label, count = classify(states)
            label, just_confirmed = state.debouncer.update(raw_label)
            per_hand_label[hand_id] = label
            per_hand_count[hand_id] = count
            per_hand_confirmed[hand_id] = just_confirmed
            fist_flags[hand_id] = (label == LABEL_FIST)

        # Motion detection
        motion_results = self._motion.update(pose_joints, fist_flags)
        self._last_motion_both = motion_results.get("both", (None, 0.0))

        # Assemble HandInput list
        outputs: List[HandInput] = []
        for hand_id in ("left", "right"):
            state = hands[hand_id]
            pos = state.position_norm or (0.0, 0.0)
            label = per_hand_label[hand_id]
            count = per_hand_count[hand_id]
            confirmed = per_hand_confirmed[hand_id]
            per_motion, per_conf = motion_results.get(hand_id, (None, 0.0))
            # hands_together is a global event — attach to both hands.
            both_label, both_conf = self._last_motion_both
            if both_label is not None:
                per_motion = both_label
                per_conf = max(per_conf, both_conf)

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


# ---------------------------------------------------------------------------
# Singleton convenience API for Part B
# ---------------------------------------------------------------------------

_global_pipeline: Optional[RecognitionPipeline] = None


def get_hand_inputs() -> List[HandInput]:
    """Return the latest per-hand inputs from a lazily-created global pipeline.

    Part B game loops may call this each tick. Call ``close_pipeline()`` at
    shutdown to release the camera.
    """
    global _global_pipeline
    if _global_pipeline is None:
        _global_pipeline = RecognitionPipeline()
    return _global_pipeline.step()


def close_pipeline() -> None:
    global _global_pipeline
    if _global_pipeline is not None:
        _global_pipeline.close()
        _global_pipeline = None
