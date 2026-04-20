"""Coordinate transforms, EMA smoothing and deadzone utilities."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

Point = Tuple[float, float]


def normalized_to_screen(nx: float, ny: float, width: int, height: int) -> Tuple[int, int]:
    """Map MediaPipe normalized coordinates (0~1) to pixel coordinates."""
    px = int(max(0.0, min(1.0, nx)) * (width - 1))
    py = int(max(0.0, min(1.0, ny)) * (height - 1))
    return px, py


@dataclass
class EMASmoother:
    """Exponential moving average smoother for a 2D point."""

    alpha: float = 0.4
    _state: Optional[Point] = None

    def reset(self) -> None:
        self._state = None

    def update(self, point: Optional[Point]) -> Optional[Point]:
        if point is None:
            return self._state
        if self._state is None:
            self._state = point
            return self._state
        a = self.alpha
        sx, sy = self._state
        nx, ny = point
        self._state = (a * nx + (1 - a) * sx, a * ny + (1 - a) * sy)
        return self._state


def apply_deadzone(prev: Optional[Point], curr: Point, threshold_px: float = 3.0) -> Point:
    """Return prev if curr is within threshold pixels of prev; else curr."""
    if prev is None:
        return curr
    dx = curr[0] - prev[0]
    dy = curr[1] - prev[1]
    if (dx * dx + dy * dy) ** 0.5 < threshold_px:
        return prev
    return curr


# Palm-center landmark index (middle finger MCP is close to palm center).
PALM_LANDMARK_INDEX = 9
