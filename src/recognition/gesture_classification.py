"""
Hand Gesture Real-time Recognition (ONNX)
사용법: python gesture_realtime.py

필요 패키지:
  pip install onnxruntime mediapipe opencv-python numpy
"""

import cv2
import numpy as np
import onnxruntime as ort
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

# ============================================================
# 설정
# ============================================================
ONNX_PATH = "gesture_mlp_merged.onnx"
MODEL_PATH = "hand_landmarker.task"  # MediaPipe 모델 파일 경로

LABEL_NAMES = ['finger_1', 'finger_2', 'finger_3', 'finger_4', 'finger_5', 'thumbs_up']

# 굽힘 각도 15개
BENDING_JOINTS = [
    (0, 1, 2), (1, 2, 3), (2, 3, 4),
    (0, 5, 6), (5, 6, 7), (6, 7, 8),
    (0, 9, 10), (9, 10, 11), (10, 11, 12),
    (0, 13, 14), (13, 14, 15), (14, 15, 16),
    (0, 17, 18), (17, 18, 19), (18, 19, 20),
]

# 벌어짐 각도 4개
SPREAD_PAIRS = [(1, 5), (1, 9), (1, 13), (1, 17)]


# ============================================================
# 특성 추출 함수
# ============================================================
def cosine_angle(a, b, c):
    ba = a - b
    bc = c - b
    dot = np.dot(ba, bc)
    norm = np.linalg.norm(ba) * np.linalg.norm(bc)
    if norm < 1e-8:
        return 0.0
    return float(np.clip(dot / norm, -1.0, 1.0))


def cosine_spread(landmarks, a_idx, b_idx):
    va = landmarks[a_idx] - landmarks[0]
    vb = landmarks[b_idx] - landmarks[0]
    dot = np.dot(va, vb)
    norm = np.linalg.norm(va) * np.linalg.norm(vb)
    if norm < 1e-8:
        return 0.0
    return float(np.clip(dot / norm, -1.0, 1.0))


def extract_features(landmarks):
    features = []
    for a, b, c in BENDING_JOINTS:
        features.append(cosine_angle(landmarks[a], landmarks[b], landmarks[c]))
    for a_idx, b_idx in SPREAD_PAIRS:
        features.append(cosine_spread(landmarks, a_idx, b_idx))
    return np.array(features, dtype=np.float32)


# ============================================================
# ONNX 추론 클래스
# ============================================================
class GestureClassifier:
    def __init__(self, onnx_path, model_path):
        # ONNX 런타임
        self.session = ort.InferenceSession(onnx_path)
        self.input_name = self.session.get_inputs()[0].name

        # MediaPipe Hand Landmarker
        base_options = python.BaseOptions(model_asset_path=model_path)
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            num_hands=1,
        )
        self.detector = vision.HandLandmarker.create_from_options(options)

    def predict(self, frame):
        """
        BGR 이미지(numpy array)를 입력받아 (클래스명, 확률, 랜드마크) 반환.
        손이 검출되지 않으면 (None, None, None) 반환.
        """
        # BGR → RGB 변환 후 MediaPipe 이미지 생성
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        # 손 검출
        result = self.detector.detect(mp_image)
        if not result.hand_landmarks:
            return None, None, None

        # 랜드마크 추출
        hand = result.hand_landmarks[0]
        landmarks = np.array([[p.x, p.y, p.z] for p in hand])

        # 특성 추출 → ONNX 추론
        features = extract_features(landmarks).reshape(1, -1)
        logits = self.session.run(None, {self.input_name: features})[0][0]

        # softmax → 확률
        exp = np.exp(logits - logits.max())
        probs = exp / exp.sum()
        class_idx = int(np.argmax(probs))

        return LABEL_NAMES[class_idx], probs[class_idx], landmarks


# ============================================================
# 웹캠 실시간 분류
# ============================================================
def draw_landmarks(frame, landmarks):
    """랜드마크를 프레임에 그리기."""
    h, w = frame.shape[:2]
    # 연결선 정의
    connections = [
        (0,1),(1,2),(2,3),(3,4),
        (0,5),(5,6),(6,7),(7,8),
        (0,9),(9,10),(10,11),(11,12),
        (0,13),(13,14),(14,15),(15,16),
        (0,17),(17,18),(18,19),(19,20),
        (5,9),(9,13),(13,17),
    ]
    pts = [(int(lm[0]*w), int(lm[1]*h)) for lm in landmarks]

    for a, b in connections:
        cv2.line(frame, pts[a], pts[b], (0, 255, 0), 2)
    for pt in pts:
        cv2.circle(frame, pt, 4, (0, 0, 255), -1)


def run_webcam():
    classifier = GestureClassifier(ONNX_PATH, MODEL_PATH)
    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("웹캠을 열 수 없습니다.")
        return

    print("웹캠 시작 (q 키로 종료)")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame = cv2.flip(frame, 1)  # 좌우 반전 (거울 모드)
        label, conf, landmarks = classifier.predict(frame)

        if label is not None:
            # 랜드마크 그리기
            draw_landmarks(frame, landmarks)

            # 결과 텍스트
            text = f"{label} ({conf:.1%})"
            cv2.putText(frame, text, (10, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 3)
        else:
            cv2.putText(frame, "No hand detected", (10, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)

        cv2.imshow("Gesture Recognition", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    run_webcam()