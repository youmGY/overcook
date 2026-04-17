"""Recognition package — hand tracking & gesture classification pipeline."""

from .camera import CameraConfig
from .hand_tracker import HandTrackerConfig
from .interface import (
    HandInput,
    RecognitionPipeline,
    close_pipeline,
    get_hand_inputs,
)

__all__ = [
    "CameraConfig",
    "HandTrackerConfig",
    "HandInput",
    "RecognitionPipeline",
    "close_pipeline",
    "get_hand_inputs",
]
