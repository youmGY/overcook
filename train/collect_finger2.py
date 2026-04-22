"""
웹캠으로 finger_2 랜드마크 수집

Space: 현재 프레임의 랜드마크 저장
q / ESC: 종료 & 저장

사용법:
    python train/collect_finger2.py
출력:
    train/landmarks_finger2.npz  (landmarks, labels, handedness)
    기존 파일이 있으면 이어서 저장.
"""

import os
import sys

import cv2
import numpy as np
import onnxruntime as ort
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

HAGRID_PEACE = 10  # peace → LABEL_REMAP에서 finger_2(1)로 매핑됨
GAME_LABELS = ['finger_1', 'finger_2', 'finger_3', 'finger_3_another', 'finger_4', 'finger_5', 'thumbs_up', 'fist']
CORRECT_IDX = 1  # finger_2


# ── 정규화 & 피처 (기존 모델 추론용) ──────────────────────────

def normalize_landmarks(lm: np.ndarray, is_left: bool):
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


def _cos_angle(a, b, c):
    v1 = a - b
    v2 = c - b
    n1 = np.linalg.norm(v1)
    n2 = np.linalg.norm(v2)
    if n1 < 1e-8 or n2 < 1e-8:
        return 0.0
    return float(np.dot(v1, v2) / (n1 * n2))


def landmarks_to_features(lm_norm: np.ndarray):
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
    feats.append(_cos_angle(lm_norm[1], lm_norm[0], lm_norm[5]))
    feats.append(_cos_angle(lm_norm[0], lm_norm[1], lm_norm[2]))
    feats.append(_cos_angle(lm_norm[1], lm_norm[2], lm_norm[3]))
    feats.append(_cos_angle(lm_norm[2], lm_norm[3], lm_norm[4]))
    return np.array(feats, dtype=np.float32)

def main():
    base_dir = os.path.dirname(__file__)
    save_path = os.path.join(base_dir, 'landmarks_finger2.npz')

    # 기존 데이터 로드
    if os.path.exists(save_path):
        data = np.load(save_path)
        lm_list = list(data['landmarks'])
        lb_list = list(data['labels'])
        hd_list = list(data['handedness'])
        print(f"기존 데이터 로드: {len(lm_list)}개")
    else:
        lm_list = []
        lb_list = []
        hd_list = []

    # 60-dim ONNX 모델 로드
    onnx_path = os.path.join(base_dir, 'gesture_mlp_60f_8cls.onnx')
    session = None
    if os.path.exists(onnx_path):
        session = ort.InferenceSession(onnx_path)
        input_name = session.get_inputs()[0].name
        print(f"[INFO] 60f 모델 로드: {onnx_path}")
    else:
        print(f"[WARN] 60f 모델 없음: {onnx_path} — 판정 표시 안 함")

    # MediaPipe HandLandmarker
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

    count = len(lm_list)
    print("[INFO] Space=저장, q/ESC=종료")

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame = cv2.flip(frame, 1)
        h, w = frame.shape[:2]

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = detector.detect(mp_image)

        detected = False
        lm_current = None
        is_left_current = None

        if result.hand_landmarks and result.handedness:
            detected = True
            hand_lms = result.hand_landmarks[0]
            lm_current = np.array([[p.x, p.y, p.z] for p in hand_lms], dtype=np.float32)
            h_label = result.handedness[0][0].category_name
            is_left_current = (h_label == "Left")

            # 랜드마크 그리기
            for p in hand_lms:
                cx, cy = int(p.x * w), int(p.y * h)
                cv2.circle(frame, (cx, cy), 4, (0, 255, 0), -1)

            cv2.putText(frame, f"Hand: {h_label}", (10, h - 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 200, 0), 2)

            # 모델 추론
            if session is not None:
                lm_norm = normalize_landmarks(lm_current.copy(), is_left_current)
                if lm_norm is not None:
                    feat = landmarks_to_features(lm_norm)
                    logits = session.run(None, {input_name: feat.reshape(1, -1)})[0][0]
                    probs = np.exp(logits) / np.exp(logits).sum()
                    pred = int(np.argmax(probs))
                    pred_label = GAME_LABELS[pred]
                    conf = probs[pred]

                    # 정답(finger_2)이면 초록, 오답이면 빨강
                    color = (0, 255, 0) if pred == CORRECT_IDX else (0, 0, 255)
                    cv2.putText(frame, f"Model: {pred_label} ({conf:.0%})", (10, h - 50),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

                    # 확률 바
                    for j, (name, p) in enumerate(zip(GAME_LABELS, probs)):
                        bar_w = int(p * 150)
                        c_bar = (0, 255, 0) if j == pred else (100, 100, 100)
                        if j == CORRECT_IDX:  # finger_2 강조
                            c_bar = (255, 255, 0) if j != pred else (0, 255, 0)
                        y0 = 80 + j * 22
                        cv2.rectangle(frame, (w - 280, y0), (w - 280 + bar_w, y0 + 16), c_bar, -1)
                        cv2.putText(frame, f"{name}: {p:.0%}", (w - 120, y0 + 13),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

        # 상태 표시
        status = "DETECTED" if detected else "NO HAND"
        cv2.putText(frame, f"finger_2 collector | {status}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0) if detected else (0, 0, 255), 2)
        cv2.putText(frame, f"Saved: {count}", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

        cv2.imshow("Collect finger_2", frame)
        key = cv2.waitKey(1) & 0xFF

        if key == ord(' ') and detected and lm_current is not None:
            lm_list.append(lm_current)
            lb_list.append(HAGRID_PEACE)
            hd_list.append(0 if is_left_current else 1)
            count += 1
            print(f"  저장 #{count}")

        if key in (ord('q'), 27):
            break

    cap.release()
    cv2.destroyAllWindows()

    if count > 0:
        np.savez(
            save_path,
            landmarks=np.array(lm_list, dtype=np.float32),
            labels=np.array(lb_list, dtype=np.int64),
            handedness=np.array(hd_list, dtype=np.int64),
        )
        print(f"\n저장 완료: {save_path} ({count}개)")
    else:
        print("\n저장된 데이터 없음.")


if __name__ == "__main__":
    main()
