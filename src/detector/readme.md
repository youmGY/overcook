# gesture_detector.py — 코드 및 알고리즘 설명

## 개요

`gesture_detector.py`는 MediaPipe Hands를 기반으로 웹캠 프레임에서 손동작을 실시간 분류하는 모듈이다.
별도 학습 없이 규칙 기반으로 동작하며, 라즈베리파이 5 같은 저사양 환경을 지원한다.

| 제스처 | 설명 |
|--------|------|
| `chop` | 손이 위아래로 반복 운동 |
| `stir` | 손이 좌우로 반복 운동 |
| `idle` | 위 동작이 아닌 모든 상태 |

---

## 파일 구조

```
gesture_detector.py
├── 상수 정의 (랜드마크 인덱스)
│   ├── 손 랜드마크: WRIST, THUMB_*, INDEX_*, MIDDLE_*, RING_*, PINKY_*
│   └── 포즈 랜드마크: LEFT/RIGHT_SHOULDER, ELBOW, WRIST_P (현재 미사용)
├── Gesture(str, Enum)          — 제스처 종류 열거형
├── GestureDetector             — 핵심 감지기 클래스
│   ├── 클래스 상수 (하이퍼파라미터)
│   ├── __init__                — 초기화
│   ├── detect(bgr_frame)       — 제스처 감지 (주 진입점)
│   ├── close()                 — 리소스 해제
│   └── draw_landmarks(frame)   — 랜드마크 시각화
├── _count_oscillations()       — 방향 전환 횟수 계산 (모듈 함수)
└── _amplitude()                — 진폭 계산 유틸 (모듈 함수)
```

---

## 알고리즘 상세 설명

### 1. 입력 전처리

```python
small = cv2.resize(bgr_frame, (320, 240))
rgb   = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
```

저사양 환경에서 추론 속도를 높이기 위해 320×240으로 리사이즈한 후 MediaPipe에 전달한다.
MediaPipe는 RGB 입력을 요구하므로 BGR→RGB 변환이 필요하다.

---

### 2. 손목 좌표 슬라이딩 윈도우

MediaPipe가 반환하는 21개 랜드마크 중 `WRIST(index=0)`의 x/y 좌표만 사용한다.

```python
self._wy: deque[float]  # y 좌표 버퍼 (chop 감지용)
self._wx: deque[float]  # x 좌표 버퍼 (stir 감지용)
```

버퍼 크기: `BUFFER_SIZE = 45` (30fps 기준 약 1.5초 분량)

#### Gap Filling (화면 이탈 대응)

손이 화면에서 순간 이탈하면 버퍼에 공백이 생겨 진동 패턴이 끊긴다.
`HAND_CACHE_MAX(4)` 프레임 이내의 이탈 구간은 마지막 손목 위치로 채워 연속성을 유지한다.

```
정상:     [0.3, 0.4, 0.5, 0.4, 0.3]
이탈:     [0.3, 0.4,  ?,   ?,  0.3]   ← gap
Gap fill: [0.3, 0.4, 0.4, 0.4, 0.3]  ← 마지막 위치 유지
```

---

### 3. 정지 감지 및 버퍼 초기화

손목 속도를 `max(|Δx|, |Δy|)` 로 계산한다.
속도가 `STILL_SPEED_MAX(0.006)` 미만인 상태가 `STILL_RESET_FRAMES(10)` 프레임 연속되면 버퍼를 초기화한다.

**이유**: chop/stir 동작 후 손을 멈춰도 버퍼에 이전 패턴이 남아 제스처가 계속 감지되는 오작동 방지.

---

### 4. 방향 전환 횟수 카운트 (`_count_oscillations`)

chop/stir를 판정하는 핵심 함수다.

#### 4-1. 이동평균 평활화

```python
k = max(3, n // 10)
s = np.convolve(arr, np.ones(k) / k, mode="valid")
```

- 손떨림·센서 노이즈를 제거한다.
- `n//10` 은 `n//5` 보다 약한 평활화 → 빠른 chop 동작의 진폭 손실 최소화.

#### 4-2. 방향 전환 감지

```python
for i in range(1, len(s)):
    diff    = s[i] - s[i-1]
    cur_dir = 1 if diff > 0 else -1
    if last_dir != 0 and cur_dir != last_dir:
        # 방향 전환 발생 → 진폭 필터 적용
```

연속 두 샘플의 부호가 반전되면 방향 전환으로 감지.

#### 4-3. 진폭 필터

방향 전환이 감지되어도 직전 극값과의 차이가 `OSCILLATION_AMP(0.05)` 미만이면 무시한다.
화면 높이/너비의 5% 미만인 미세한 움직임은 손떨림으로 처리.

#### 4-4. stale reference 방지

진폭 미달이어도 레퍼런스(`last_extreme`)는 항상 갱신한다.
갱신하지 않으면 묵은 값이 누적되어 이후 전환이 과대 또는 과소 측정된다.

```
예시 — 극값이 A=0.3, B=0.32(진폭 0.02 → 미달), C=0.38 순서로 발생

  stale 방식:  C - A = 0.08  (B를 건너뛰어 누적 → 왜곡 가능)
  갱신 방식:   C - B = 0.06  (실제 B→C 구간 측정)
```

---

### 5. 최근 프레임 진폭 게이트

```python
recent_n = min(len(wy_arr), RECENT_FRAMES)   # 25 프레임
r_y_amp  = wy_arr[-recent_n:].max() - wy_arr[-recent_n:].min()
```

전체 버퍼(45프레임)의 방향 전환 횟수만으로는, 과거에 chop을 하고 현재 stir를 할 때
y 버퍼에 이전 chop 패턴이 남아 stir 감지를 방해할 수 있다.

**최근 N프레임의 진폭**이 `OSCILLATION_AMP` 이상일 때만 해당 제스처로 확정하여 이 문제를 해결한다.

---

### 6. 판정 로직

```python
is_chop = (chop_osc >= OSCILLATION_MIN  or
           (y_amp >= OSCILLATION_AMP_LARGE and chop_osc >= 1)) \
          and r_y_amp >= OSCILLATION_AMP

is_stir = (stir_osc >= OSCILLATION_MIN  or
           (x_amp >= OSCILLATION_AMP_LARGE and stir_osc >= 1)) \
          and r_x_amp >= OSCILLATION_AMP
```

| 조건 | 결과 |
|------|------|
| `is_chop and is_stir` | `r_y_amp > r_x_amp × 1.5` → CHOP<br>`r_x_amp > r_y_amp × 1.5` → STIR<br>그 외 → IDLE |
| `is_chop only` | CHOP |
| `is_stir only` | STIR |
| 둘 다 false | IDLE |

**대진폭 shortcut**: `OSCILLATION_AMP_LARGE(0.20)` 이상의 큰 진폭은 방향 전환 1번만으로 제스처로 인정한다.
화면 이탈 후 복귀 같은 극단적 동작을 대응하기 위한 예외 처리다.

---

### 7. Hold 메커니즘 (토글 방지)

```
판정이 IDLE로 바뀌어도 HOLD_FRAMES(8) 동안 이전 제스처를 유지
```

동작 도중 잠깐 손이 멈추거나 이탈해서 생기는 IDLE 깜빡임을 방지한다.

---

## 사용 예시

```python
import cv2
from gesture_detector import GestureDetector, Gesture

detector = GestureDetector(debug=True)
cap = cv2.VideoCapture(0)

while True:
    ret, frame = cap.read()
    if not ret:
        break

    gesture = detector.detect(frame)
    frame   = detector.draw_landmarks(frame)

    print(gesture.value)        # "chop", "stir", "idle"
    print(detector.debug_info)  # 상세 수치 (debug=True 시)

detector.close()
cap.release()
```

---

## debug_info 필드

`debug=True`로 초기화하면 `detector.debug_info` 딕셔너리에 다음 값이 채워진다.

| 키 | 설명 |
|----|------|
| `chop_osc` | y축 방향 전환 횟수 |
| `stir_osc` | x축 방향 전환 횟수 |
| `y_amp` | y축 전체 버퍼 진폭 |
| `x_amp` | x축 전체 버퍼 진폭 |
| `r_y_amp` | y축 최근 N프레임 진폭 |
| `r_x_amp` | x축 최근 N프레임 진폭 |
| `wrist_speed` | 현재 프레임 손목 속도 |
| `still_counter` | 연속 정지 프레임 카운터 |
| `raw` | hold 적용 전 원시 제스처 |
| `hold_counter` | 남은 hold 프레임 수 |

---

## 하이퍼파라미터 요약

| 상수 | 기본값 | 설명 |
|------|--------|------|
| `BUFFER_SIZE` | 45 | 슬라이딩 윈도우 크기 (~1.5초 @ 30fps) |
| `OSCILLATION_MIN` | 3 | 최소 방향 전환 횟수 |
| `OSCILLATION_AMP` | 0.05 | 유효 전환 최소 진폭 (화면 5%) |
| `OSCILLATION_AMP_LARGE` | 0.20 | 대진폭 shortcut 임계값 |
| `AXIS_DOMINANCE` | 1.5 | chop/stir 축 우세 판정 비율 |
| `RECENT_FRAMES` | 25 | 최근 진폭 게이트 윈도우 크기 |
| `HOLD_FRAMES` | 8 | IDLE 전환 지연 프레임 수 |
| `HAND_CACHE_MAX` | 4 | gap filling 최대 프레임 수 |
| `STILL_SPEED_MAX` | 0.006 | 정지 판정 속도 임계값 |
| `STILL_RESET_FRAMES` | 10 | 연속 정지 버퍼 초기화 기준 |

---

## 관련 파일

| 파일 | 역할 |
|------|------|
| `gesture_detector.py` | 핵심 감지기 구현 |
| `test_webcam.py` | 라즈베리파이 5 웹캠 테스트 스크립트 |
| `ai_detector.md` | 구현 명세서 (설계 의도, 알고리즘 스펙) |
| `insturction.md` | 설치 및 실행 방법 |
| `examples/` | chop/stir 동작 예시 영상 |
