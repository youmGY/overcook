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
LABEL_FIST = "fist"
LABEL_UNKNOWN = "unknown"

_DNN_LABELS = [
    LABEL_FINGER_1,
    LABEL_FINGER_2,
    LABEL_FINGER_3,
    LABEL_FINGER_4,
    LABEL_FINGER_5,
    LABEL_THUMBS_UP,
    LABEL_FIST,
]

_LABEL_TO_COUNT = {
    LABEL_FINGER_1: 1,
    LABEL_FINGER_2: 2,
    LABEL_FINGER_3: 3,
    LABEL_FINGER_4: 4,
    LABEL_FINGER_5: 5,
    LABEL_THUMBS_UP: 1,
    LABEL_FIST: 0,
    LABEL_UNKNOWN: 0,
}

_DEFAULT_ONNX = os.path.join(os.path.dirname(__file__), "models", "gesture_mlp.onnx")

# ---- feature extraction (60-dim: normalized coordinates + thumb cosines) ----


def _normalize_landmarks(lm: np.ndarray, is_left: bool) -> np.ndarray | None:
    """(21, 3) landmarks → rotation/scale-normalized (21, 3). Returns None on failure."""
    lm = lm - lm[0]
    v1 = lm[17].copy()
    v2 = lm[5].copy()
    norm_v1 = np.linalg.norm(v1)
    if norm_v1 < 1e-8:
        return None
    ex = v1 / norm_v1
    v2_perp = v2 - np.dot(v2, ex) * ex
    norm_v2_perp = np.linalg.norm(v2_perp)
    if norm_v2_perp < 1e-8:
        return None
    ey = v2_perp / norm_v2_perp
    ez = np.cross(ex, ey)
    R = np.stack([ex, ey, ez], axis=0)
    lm = (R @ lm.T).T
    lm = lm / norm_v1
    if is_left:
        lm[:, 2] = -lm[:, 2]
    return lm.astype(np.float32)


def _cos_angle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """Cosine of angle at vertex b for points a-b-c."""
    v1 = a - b
    v2 = c - b
    n1 = np.linalg.norm(v1)
    n2 = np.linalg.norm(v2)
    if n1 < 1e-8 or n2 < 1e-8:
        return 0.0
    return float(np.dot(v1, v2) / (n1 * n2))


def _landmarks_to_features(lm_norm: np.ndarray) -> np.ndarray:
    """Normalized (21,3) → 60-dim feature vector."""
    feats = []
    for i in range(21):
        if i == 0:
            continue
        if i == 17:
            continue
        if i == 5:
            feats.append(lm_norm[i, 0])
            feats.append(lm_norm[i, 1])
        else:
            feats.extend(lm_norm[i].tolist())
    # 4 thumb angle cosines
    feats.append(_cos_angle(lm_norm[1], lm_norm[0], lm_norm[5]))  # spread
    feats.append(_cos_angle(lm_norm[0], lm_norm[1], lm_norm[2]))  # CMC
    feats.append(_cos_angle(lm_norm[1], lm_norm[2], lm_norm[3]))  # MCP
    feats.append(_cos_angle(lm_norm[2], lm_norm[3], lm_norm[4]))  # IP
    return np.array(feats, dtype=np.float32)


def extract_features(landmarks_np: np.ndarray, is_left: bool = False) -> np.ndarray | None:
    """Extract 60-dim features (normalized coords + thumb cosines). Returns None on failure."""
    lm_norm = _normalize_landmarks(landmarks_np, is_left)
    if lm_norm is None:
        return None
    return _landmarks_to_features(lm_norm)


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

    def predict(self, landmarks_np: np.ndarray, is_left: bool = False) -> Tuple[str, float, int]:
        """Classify a (21,3) landmark array.

        Returns (label, confidence, finger_count).
        If confidence < threshold or normalization fails, returns (unknown, conf, 0).
        """
        features = extract_features(landmarks_np, is_left)
        if features is None:
            return LABEL_UNKNOWN, 0.0, 0
        features = features.reshape(1, -1)
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
    """Confirm a gesture only after it persists for N consecutive frames.
    
    thumbs_up uses threshold=2 (~66 ms at 30 fps) and clears instantly
    when a different label appears.  finger_N uses the default n=3."""

    n: int = 3
    _pending: Optional[str] = None
    _streak: int = 0
    _confirmed: Optional[str] = field(default=None)

    def update(self, label: str) -> Tuple[str, bool]:
        if label == self._pending:
            self._streak += 1
        else:
            # thumbs_up confirmed state clears immediately when a different
            # raw label appears, so the cooldown resets without waiting for
            # another gesture to accumulate N frames.
            if self._confirmed == LABEL_THUMBS_UP and label != LABEL_THUMBS_UP:
                self._confirmed = None
            self._pending = label
            self._streak = 1

        # thumbs_up confirms after 2 consecutive frames (≈66 ms at 30 fps)
        threshold = 2 if label == LABEL_THUMBS_UP else self.n

        confirmed_now = False
        if self._streak >= threshold and self._confirmed != label:
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
