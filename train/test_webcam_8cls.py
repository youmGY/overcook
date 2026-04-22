"""
웹캠 제스처 인식 테스트 — 8클래스 (finger_3_another 포함)

finger_3        : 엄지 + 검지 + 중지 펴기
finger_3_another: 검지 + 중지 + 약지 펴기

사용법:
    python train/test_webcam_8cls.py
    (train/gesture_mlp_60f_8cls.onnx 필요)
    q / ESC 종료
"""

import os
import sys

import cv2
import numpy as np
import onnxruntime as ort
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

# ── 라벨 ──────────────────────────────────────────────────────
GAME_LABELS = [
    'finger_1', 'finger_2', 'finger_3', 'finger_3_another',
    'finger_4', 'finger_5', 'thumbs_up', 'fist',
]

# ── 정규화 & 피처 (train_60f_with_3another.py 와 동일) ───────

def normalize_landmarks(lm: np.ndarray, is_left: bool) -> np.ndarray:
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
    v1 = a - b
    v2 = c - b
    n1 = np.linalg.norm(v1)
    n2 = np.linalg.norm(v2)
    if n1 < 1e-8 or n2 < 1e-8:
        return 0.0
    return float(np.dot(v1, v2) / (n1 * n2))


def landmarks_to_features(lm_norm: np.ndarray) -> np.ndarray:
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

    # 엄지 각도 코사인 4개
    feats.append(_cos_angle(lm_norm[1], lm_norm[0], lm_norm[5]))
    feats.append(_cos_angle(lm_norm[0], lm_norm[1], lm_norm[2]))
    feats.append(_cos_angle(lm_norm[1], lm_norm[2], lm_norm[3]))
    feats.append(_cos_angle(lm_norm[2], lm_norm[3], lm_norm[4]))

    return np.array(feats, dtype=np.float32)


# ── 메인 ──────────────────────────────────────────────────────

def main():
    base_dir = os.path.dirname(__file__)

    # ONNX 모델 로드
    onnx_path = os.path.join(base_dir, 'gesture_mlp_60f_8cls.onnx')
    if not os.path.exists(onnx_path):
        print(f"[ERROR] {onnx_path} 없음. train_60f_with_3another.py 먼저 실행하세요.")
        sys.exit(1)
    session = ort.InferenceSession(onnx_path)
    input_name = session.get_inputs()[0].name

    # MediaPipe HandLandmarker
    task_path = os.path.abspath(
        os.path.join(base_dir, "..", "overcook", "recognition", "models", "hand_landmarker.task")
    )
    if not os.path.exists(task_path):
        # fallback: src 경로
        task_path = os.path.abspath(
            os.path.join(base_dir, "..", "src", "recognition", "hand_landmarker.task")
        )
    if not os.path.exists(task_path):
        print(f"[ERROR] hand_landmarker.task 없음: {task_path}")
        sys.exit(1)

    base_options = mp_python.BaseOptions(model_asset_path=task_path)
    options = vision.HandLandmarkerOptions(
        base_options=base_options, num_hands=1,
        min_hand_detection_confidence=0.7, min_tracking_confidence=0.6,
    )
    detector = vision.HandLandmarker.create_from_options(options)

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[ERROR] 카메라 열기 실패")
        sys.exit(1)

    print("[INFO] q / ESC 종료")
    print(f"[INFO] 클래스: {GAME_LABELS}")

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame = cv2.flip(frame, 1)
        h, w = frame.shape[:2]

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = detector.detect(mp_image)

        if result.hand_landmarks and result.handedness:
            hand_lms = result.hand_landmarks[0]
            lm = np.array([[p.x, p.y, p.z] for p in hand_lms], dtype=np.float32)

            # 랜드마크 그리기
            for i, p in enumerate(hand_lms):
                cx, cy = int(p.x * w), int(p.y * h)
                cv2.circle(frame, (cx, cy), 4, (255, 255, 255), -1)

            # handedness
            h_label = result.handedness[0][0].category_name
            is_left = (h_label == "Left")

            # 정규화 → 피처 추출 → 추론
            lm_norm = normalize_landmarks(lm, is_left)
            if lm_norm is not None:
                feat = landmarks_to_features(lm_norm)
                logits = session.run(None, {input_name: feat.reshape(1, -1)})[0][0]
                probs = np.exp(logits) / np.exp(logits).sum()
                pred = int(np.argmax(probs))
                conf = probs[pred]

                label = GAME_LABELS[pred]
                color = (0, 255, 0) if conf > 0.7 else (0, 255, 255)

                cv2.putText(frame, f"{label} ({conf:.0%})", (10, 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.5, color, 3)
                cv2.putText(frame, f"Hand: {h_label}", (10, h - 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 200, 0), 2)

                # 전체 클래스 확률 분포 표시
                for j, (name, p) in enumerate(zip(GAME_LABELS, probs)):
                    bar_w = int(p * 200)
                    c_bar = (0, 255, 0) if j == pred else (100, 100, 100)
                    # finger_3_another 강조 (노란색)
                    if j == 3:
                        c_bar = (0, 255, 255) if j != pred else (0, 255, 0)
                    y0 = 80 + j * 25
                    cv2.rectangle(frame, (10, y0), (10 + bar_w, y0 + 18), c_bar, -1)
                    cv2.putText(frame, f"{name}: {p:.0%}", (220, y0 + 15),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        cv2.imshow("Gesture Test 8cls (finger_3_another)", frame)
        if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
