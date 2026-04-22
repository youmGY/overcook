"""
AVI 영상(gesture_input, CLAHE 적용 후)을 프레임별로 MediaPipe + MLP 추론하여
gesture_dnn.log의 예측 결과와 비교하는 스크립트.

사용법:
    python train/verify_avi_vs_log.py
"""
import os, re, sys
import numpy as np
import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import onnxruntime as ort

# ── 경로 설정 ──
BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(BASE, "..")

VIDEO_PATH = os.path.join(ROOT, "recordings", "gesture_input_20260422_160620.avi")
LOG_PATH   = os.path.join(ROOT, "gesture_dnn.log")
ONNX_PATH  = os.path.join(BASE, "gesture_mlp_60f_8cls.onnx")
HAND_MODEL = os.path.join(ROOT, "overcook", "recognition", "models", "hand_landmarker.task")

LABELS = ['finger_1','finger_2','finger_3','finger_3_another',
          'finger_4','finger_5','thumbs_up','fist']

# ── 피처 추출 (train_60f_with_3another.py 동일) ──

def normalize_landmarks(lm, is_left):
    lm = lm - lm[0]
    v1 = lm[17].copy()
    v2 = lm[5].copy()
    n1 = np.linalg.norm(v1)
    if n1 < 1e-8:
        return None
    ex = v1 / n1
    v2p = v2 - np.dot(v2, ex) * ex
    n2 = np.linalg.norm(v2p)
    if n2 < 1e-8:
        return None
    ey = v2p / n2
    ez = np.cross(ex, ey)
    R = np.stack([ex, ey, ez], axis=0)
    lm = (R @ lm.T).T
    lm = lm / n1
    if is_left:
        lm[:, 2] = -lm[:, 2]
    return lm.astype(np.float32)


def cos_angle(a, b, c):
    v1 = a - b; v2 = c - b
    n1 = np.linalg.norm(v1); n2 = np.linalg.norm(v2)
    if n1 < 1e-8 or n2 < 1e-8:
        return 0.0
    return float(np.dot(v1, v2) / (n1 * n2))


def landmarks_to_features(lm_norm):
    feats = []
    for i in range(21):
        if i == 0: continue
        if i == 17: continue
        if i == 5:
            feats.append(lm_norm[i, 0])
            feats.append(lm_norm[i, 1])
        else:
            feats.extend(lm_norm[i].tolist())
    feats.append(cos_angle(lm_norm[1], lm_norm[0], lm_norm[5]))
    feats.append(cos_angle(lm_norm[0], lm_norm[1], lm_norm[2]))
    feats.append(cos_angle(lm_norm[1], lm_norm[2], lm_norm[3]))
    feats.append(cos_angle(lm_norm[2], lm_norm[3], lm_norm[4]))
    return np.array(feats, dtype=np.float32)

# ── 로그 파싱 ──

def parse_log(path):
    entries = []
    pat = re.compile(r'pred=(\S+)\s+\(([\d.]+)%\)')
    with open(path, encoding='utf-8') as f:
        for line in f:
            m = pat.search(line)
            if m:
                entries.append(m.group(1))
    return entries

# ── 메인 ──

def main():
    log_preds = parse_log(LOG_PATH)
    print(f"로그 예측 수: {len(log_preds)}")

    # MediaPipe 초기화 (게임과 동일: detect_for_video, ts += 33)
    base_options = python.BaseOptions(model_asset_path=HAND_MODEL)
    options = vision.HandLandmarkerOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.VIDEO,
        num_hands=2,
        min_hand_detection_confidence=0.2,
        min_tracking_confidence=0.2,
    )
    detector = vision.HandLandmarker.create_from_options(options)

    # ONNX 세션
    sess = ort.InferenceSession(ONNX_PATH)
    input_name = sess.get_inputs()[0].name

    cap = cv2.VideoCapture(VIDEO_PATH)
    if not cap.isOpened():
        print(f"[ERROR] 영상 열기 실패: {VIDEO_PATH}")
        return

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"영상 프레임 수: {total_frames}")

    ts_ms = 0
    video_preds = []
    frame_idx = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_idx += 1

        # 게임과 동일: BGR→RGB, detect_for_video
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        ts_ms += 33
        result = detector.detect_for_video(mp_image, ts_ms)

        if not result.hand_landmarks:
            # 손 미검출 → 해당 프레임은 로그에 기록 안 됨, 스킵
            continue

        # 게임 파이프라인: 첫 번째 손(또는 우측 손) 사용
        # 로그에는 검출된 손마다 기록됨 — 여기선 모든 손에 대해 예측
        for h_idx, hand_lms in enumerate(result.hand_landmarks):
            handedness_list = result.handedness[h_idx]
            mp_label = handedness_list[0].category_name  # "Left" or "Right"
            # 영상은 flip 후 저장됨 → MediaPipe handedness가 반전됨
            # 게임에서: _mp_handedness_label(hand_id) 가 flip을 보정함
            # 따라서 MediaPipe "Right" = 실제 왼손, "Left" = 실제 오른손
            is_left = (mp_label == "Right")  # flip 보정

            lm_np = np.array([[lm.x, lm.y, lm.z] for lm in hand_lms], dtype=np.float32)
            lm_norm = normalize_landmarks(lm_np, is_left)
            if lm_norm is None:
                continue

            feats = landmarks_to_features(lm_norm).reshape(1, -1)
            logits = sess.run(None, {input_name: feats})[0][0]
            exp = np.exp(logits - logits.max())
            probs = exp / exp.sum()
            idx = int(np.argmax(probs))
            pred = LABELS[idx]
            video_preds.append((frame_idx, pred, float(probs[idx])))

    cap.release()
    print(f"영상 추론 예측 수: {len(video_preds)}")

    # 비교
    n_compare = min(len(log_preds), len(video_preds))
    match = 0
    mismatch = 0
    for i in range(n_compare):
        log_p = log_preds[i]
        vid_p = video_preds[i][1]
        vid_frame = video_preds[i][0]
        vid_conf = video_preds[i][2]
        status = "OK" if log_p == vid_p else "MISMATCH"
        if log_p == vid_p:
            match += 1
        else:
            mismatch += 1
        print(f"[{i+1:3d}] frame={vid_frame:4d} log={log_p:<20s} video={vid_p:<20s} conf={vid_conf:.1%} {status}")

    print(f"\n=== 결과: {match}/{n_compare} 일치, {mismatch} 불일치 ===")
    if len(log_preds) != len(video_preds):
        print(f"[WARN] 예측 수 차이: log={len(log_preds)}, video={len(video_preds)}")

if __name__ == "__main__":
    main()
