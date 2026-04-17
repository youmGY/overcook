from __future__ import annotations

import threading
from dataclasses import dataclass

import cv2
import numpy as np


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


class ThreadedCamera:
    """Wraps cv2.VideoCapture with a background reader thread.

    read() always returns the latest frame immediately without blocking
    the caller on the camera driver.
    """

    def __init__(self, cap: cv2.VideoCapture) -> None:
        self._cap = cap
        self._frame: np.ndarray | None = None
        self._ok = False
        self._lock = threading.Lock()
        self._running = True
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self) -> None:
        while self._running:
            ok, frame = self._cap.read()
            with self._lock:
                self._ok = ok
                self._frame = frame

    def read(self):
        with self._lock:
            return self._ok, self._frame

    def release(self) -> None:
        self._running = False
        self._thread.join(timeout=2.0)
        self._cap.release()
