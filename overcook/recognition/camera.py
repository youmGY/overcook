from __future__ import annotations

import platform
import threading
from dataclasses import dataclass

import cv2


@dataclass(frozen=True)
class CameraConfig:
    device_index: int = 0
    width: int = 640
    height: int = 480
    fps: int = 30
    open_timeout: float = 8.0


def _open_camera_blocking(config: CameraConfig) -> cv2.VideoCapture:
    """Open camera synchronously with a platform-specific backend."""
    system = platform.system()
    if system == "Windows":
        backend = cv2.CAP_DSHOW
    elif system == "Linux":
        backend = cv2.CAP_V4L2
    else:
        backend = cv2.CAP_ANY

    cap = cv2.VideoCapture(config.device_index, backend)
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open camera device {config.device_index}")

    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.height)
    cap.set(cv2.CAP_PROP_FPS, config.fps)
    return cap


def open_camera(config: CameraConfig) -> cv2.VideoCapture:
    """Open the camera with a timeout so a bad device never blocks forever."""
    result: list = []
    error: list = []

    def _worker():
        try:
            result.append(_open_camera_blocking(config))
        except Exception as exc:
            error.append(exc)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join(timeout=config.open_timeout)

    if thread.is_alive():
        raise RuntimeError(
            f"Camera open timed out after {config.open_timeout}s "
            f"(device {config.device_index})"
        )
    if error:
        raise error[0]
    return result[0]


class ThreadedCamera:
    """Wraps cv2.VideoCapture with a background reader thread."""

    def __init__(self, cap: cv2.VideoCapture) -> None:
        self._cap = cap
        self._frame = None
        self._ok = False
        self._lock = threading.Lock()
        self._new_frame_event = threading.Event()
        self._running = True
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self) -> None:
        while self._running:
            ok, frame = self._cap.read()
            with self._lock:
                self._ok = ok
                self._frame = frame
            self._new_frame_event.set()

    def read(self):
        with self._lock:
            return self._ok, self._frame

    def wait_for_new_frame(self, timeout: float = 0.1) -> bool:
        """Block until a new camera frame arrives, or timeout elapses."""
        triggered = self._new_frame_event.wait(timeout=timeout)
        self._new_frame_event.clear()
        return triggered

    def release(self) -> None:
        self._running = False
        self._thread.join(timeout=2.0)
        self._cap.release()
