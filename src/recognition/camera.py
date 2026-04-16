from __future__ import annotations

from dataclasses import dataclass

import cv2


@dataclass(frozen=True)
class CameraConfig:
    device_index: int = 0
    width: int = 640
    height: int = 480
    fps: int = 30


def open_camera(config: CameraConfig) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(config.device_index)
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open camera device {config.device_index}")

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.height)
    cap.set(cv2.CAP_PROP_FPS, config.fps)

    return cap
