"""Recognition package for hand tracking with MediaPipe."""

from .interface import (
    HandInput,
    RecognitionPipeline,
    close_pipeline,
    get_hand_inputs,
)

__all__ = [
    "HandInput",
    "RecognitionPipeline",
    "close_pipeline",
    "get_hand_inputs",
]
