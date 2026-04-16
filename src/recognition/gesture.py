"""DNN-based hand gesture classifier (ONNX) with debouncing.

Replaces the previous rule-based finger_states / classify logic.
The ONNX model outputs 6 classes; if max softmax probability falls below
a confidence threshold the result is mapped to ``unknown``.

Label set:
    finger_1..5, thumbs_up, unknown
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np
import onnxruntime as ort

# Canonical labels
LABEL_FINGER_1 = "finger_1"
LABEL_FINGER_2 = "finger_2"
LABEL_FINGER_3 = "finger_3"
LABEL_FINGER_4 = "finger_4"
LABEL_FINGER_5 = "finger_5"
LABEL_THUMBS_UP = "thumbs_up"
LABEL_UNKNOWN = "unknown"

_DNN_LABELS = [
    LABEL_FINGER_1,
    LABEL_FINGER_2,
    LABEL_FINGER_3,
    LABEL_FINGER_4,
    LABEL_FINGER_5,
    LABEL_THUMBS_UP,
]

_LABEL_TO_COUNT = {
    LABEL_FINGER_1: 1,
    LABEL_FINGER_2: 2,
    LABEL_FINGER_3: 3,
    LABEL_FINGER_4: 4,
    LABEL_FINGER_5: 5,
    LABEL_THUMBS_UP: 1,
    LABEL_UNKNOWN: 0,
}

_DEFAULT_ONNX = os.path.join(os.path.dirname(__file__), "gesture_mlp_merged.onnx")

# ---- feature extraction (matches training pipeline) ----

_BENDING_JOINTS = [
    (0, 1, 2), (1, 2, 3), (2, 3, 4),
    (0, 5, 6), (5, 6, 7), (6, 7, 8),
    (0, 9, 10), (9, 10, 11), (10, 11, 12),
    (0, 13, 14), (13, 14, 15), (14, 15, 16),
    (0, 17, 18), (17, 18, 19), (18, 19, 20),
]

_SPREAD_PAIRS = [(1, 5), (1, 9), (1, 13), (1, 17)]


def _cosine_angle(a, b, c):
    ba = a - b
    bc = c - b
    dot = np.dot(ba, bc)
    norm = np.linalg.norm(ba) * np.linalg.norm(bc)
    if norm < 1e-8:
        return 0.0
    return float(np.clip(dot / norm, -1.0, 1.0))


def _cosine_spread(landmarks, a_idx, b_idx):
    va = landmarks[a_idx] - landmarks[0]
    vb = landmarks[b_idx] - landmarks[0]
    dot = np.dot(va, vb)
    norm = np.linalg.norm(va) * np.linalg.norm(vb)
    if norm < 1e-8:
        return 0.0
    return float(np.clip(dot / norm, -1.0, 1.0))


def extract_features(landmarks_np: np.ndarray) -> np.ndarray:
    """Extract 19-dim feature vector (15 bending + 4 spread angles)."""
    feats = []
    for a, b, c in _BENDING_JOINTS:
        feats.append(_cosine_angle(landmarks_np[a], landmarks_np[b], landmarks_np[c]))
    for a_idx, b_idx in _SPREAD_PAIRS:
        feats.append(_cosine_spread(landmarks_np, a_idx, b_idx))
    return np.array(feats, dtype=np.float32)


def landmarks_to_numpy(landmarks) -> np.ndarray:
    """Convert MediaPipe landmark list (objects with .x .y .z) to (21,3) array."""
    return np.array([[lm.x, lm.y, lm.z] for lm in landmarks], dtype=np.float32)


# ---- DNN classifier ----

class GestureClassifierDNN:
    """ONNX MLP classifier for single-hand gesture recognition."""

    def __init__(
        self,
        onnx_path: Optional[str] = None,
        confidence_threshold: float = 0.6,
    ) -> None:
        path = onnx_path or _DEFAULT_ONNX
        self._session = ort.InferenceSession(path)
        self._input_name = self._session.get_inputs()[0].name
        self._threshold = confidence_threshold

    def predict(self, landmarks_np: np.ndarray) -> Tuple[str, float, int]:
        """Classify a (21,3) landmark array.

        Returns (label, confidence, finger_count).
        If confidence < threshold, returns (unknown, conf, 0).
        """
        features = extract_features(landmarks_np).reshape(1, -1)
        logits = self._session.run(None, {self._input_name: features})[0][0]
        exp = np.exp(logits - logits.max())
        probs = exp / exp.sum()
        idx = int(np.argmax(probs))
        conf = float(probs[idx])

        if conf < self._threshold:
            return LABEL_UNKNOWN, conf, 0

        label = _DNN_LABELS[idx]
        count = _LABEL_TO_COUNT[label]
        return label, conf, count


# ---- slot mapping ----

def target_slot_for(label: str) -> Optional[int]:
    if label in (
        LABEL_FINGER_1,
        LABEL_FINGER_2,
        LABEL_FINGER_3,
        LABEL_FINGER_4,
        LABEL_FINGER_5,
    ):
        return int(label.split("_")[1])
    return None


# ---- debouncer (unchanged) ----

@dataclass
class GestureDebouncer:
    """Confirm a gesture only after it persists for N consecutive frames."""

    n: int = 4
    _pending: Optional[str] = None
    _streak: int = 0
    _confirmed: Optional[str] = field(default=None)

    def update(self, label: str) -> Tuple[str, bool]:
        if label == self._pending:
            self._streak += 1
        else:
            self._pending = label
            self._streak = 1

        confirmed_now = False
        if self._streak >= self.n and self._confirmed != label:
            self._confirmed = label
            confirmed_now = True

        effective = self._confirmed or LABEL_UNKNOWN
        return effective, confirmed_now

    @property
    def confirmed(self) -> Optional[str]:
        return self._confirmed

    def reset(self) -> None:
        self._pending = None
        self._streak = 0
        self._confirmed = None
