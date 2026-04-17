# AI Gesture Detector — 구현 명세

## 목표

손 동작을 기반으로 아래 3가지 상태를 실시간으로 분류한다.
게임에 사용될 on-device 모델로, 즉각적인 반응이 필요하다.
행동 예시는 `examples/` 폴더를 참고한다.

| 제스처 | 설명 |
|--------|------|
| `chop` | 손이 위아래로 반복 운동 |
| `stir` | 손이 좌우로 반복 운동 |
| `idle` | 위 동작이 아닌 모든 상태 |

---

## 기술 스택

- **MediaPipe Hands** (`model_complexity=0`): 21개 손 랜드마크 추출 — on-device, 실시간
- **NumPy**: 슬라이딩 윈도우 연산
- 별도 학습 데이터 없이 규칙 기반으로 동작

---

## 구현 대상 파일

```
src/detector/gesture_detector.py
```

---

## 아키텍처 개요

```
BGR 프레임
    │
    ▼
[전처리] BGR → 320×240 리사이즈 → RGB 변환
    │
    ▼
[MediaPipe Hands] 손목(WRIST, index=0) x/y 좌표 추출
    │
    ├─ 손 감지 시   : 손목 좌표를 버퍼에 추가, 속도 계산
    └─ 손 이탈 시   : HAND_CACHE_MAX 이내면 마지막 위치로 gap filling
    │
    ▼
[슬라이딩 윈도우 버퍼] _wx(deque), _wy(deque), maxlen=BUFFER_SIZE
    │
    ├─ [정지 감지] 손목 속도 < STILL_SPEED_MAX 가 STILL_RESET_FRAMES 연속 → 버퍼 초기화
    │
    ▼
[_count_oscillations(wy_arr)] → chop_osc  (y축 방향 전환 횟수)
[_count_oscillations(wx_arr)] → stir_osc  (x축 방향 전환 횟수)
    │
    ▼
[최근 N프레임 진폭 게이트] r_y_amp, r_x_amp (과거 버퍼 잔류 차단)
    │
    ▼
[판정 로직] is_chop / is_stir → 축 우세 비교 → raw gesture
    │
    ▼
[Hold 메커니즘] IDLE 전환 지연 (토글 방지)
    │
    ▼
Gesture.CHOP / Gesture.STIR / Gesture.IDLE
```

---

## 클래스 설계

### `Gesture(str, Enum)`

```python
class Gesture(str, Enum):
    IDLE = "idle"
    CHOP = "chop"
    STIR = "stir"
```

---

### `GestureDetector`

#### 생성자

```python
def __init__(
    self,
    min_detection_confidence: float = 0.5,
    min_tracking_confidence:  float = 0.4,
    debug: bool = False,
) -> None:
```

초기화 목록:
- `MediaPipe Hands` (`max_num_hands=1`, `model_complexity=0`)
- 슬라이딩 윈도우 버퍼 `_wy`, `_wx` (`deque(maxlen=BUFFER_SIZE)`)
- 손목 속도 추적 변수: `_wrist_speed`, `_prev_wrist`
- 정지 카운터: `_still_counter`
- Hold 상태: `_hold_counter`, `_held_gesture`
- gap filling 상태: `_last_wrist_pos`, `_wrist_absent`

#### 공개 메서드

| 메서드 | 설명 |
|--------|------|
| `detect(bgr_frame: np.ndarray) -> Gesture` | 한 프레임을 처리하고 제스처 반환 |
| `draw_landmarks(bgr_frame: np.ndarray) -> np.ndarray` | 마지막 detect() 랜드마크를 프레임에 그려 반환 |
| `close() -> None` | MediaPipe 리소스 해제 |

---

## 핵심 알고리즘: `_count_oscillations(buf, amp_threshold)`

좌표 시계열에서 유효한 방향 전환 횟수를 반환하는 모듈 레벨 함수.

### 단계

1. **이동평균 평활화**
   ```python
   k = max(3, n // 10)   # n//5 대신 n//10: 빠른 chop 진폭 손실 최소화
   s = np.convolve(arr, np.ones(k) / k, mode="valid")
   ```
   손떨림·센서 노이즈를 제거한다. 커널이 너무 크면 실제 동작 진폭이 줄어드므로 n//10 사용.

2. **방향 전환 감지**
   연속 두 샘플의 부호가 반전(양→음, 음→양)되면 방향 전환으로 감지한다.

3. **진폭 필터**
   방향 전환 직전 값(실제 극값)이 이전 극값과의 차이가 `amp_threshold` 이상일 때만 카운트한다.

4. **stale reference 방지**
   진폭 미달이어도 레퍼런스(`last_extreme`)는 항상 갱신한다.
   갱신하지 않으면 묵은 값이 누적되어 임계값 판정이 왜곡된다.

```
[평활화된 신호]
    ▲
 /\/\/\   ← 방향 전환 3회 이상, 진폭 ≥ OSCILLATION_AMP → chop/stir 판정
─────────────▶ 프레임
```

---

## detect() 메서드 — 처리 흐름

### 1. 입력 전처리
```python
small = cv2.resize(bgr_frame, (320, 240))
rgb   = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
r     = self._hands.process(rgb)
```

### 2. 버퍼 갱신 및 gap filling

| 상황 | 처리 |
|------|------|
| 손 감지됨 | WRIST x/y 좌표를 버퍼에 추가, 손목 속도 갱신 |
| 손 이탈, `_wrist_absent < HAND_CACHE_MAX` | 마지막 위치로 채워 버퍼 연속성 유지 |
| 손 이탈, 초과 | 버퍼에 추가하지 않음 |

### 3. 정지 감지 및 버퍼 초기화

```
손목 속도 = max(|Δx|, |Δy|)

속도 < STILL_SPEED_MAX  →  still_counter++
still_counter ≥ STILL_RESET_FRAMES  →  _wy.clear(), _wx.clear()
```

동작 종료 후 버퍼에 잔류한 패턴이 제스처로 계속 감지되는 오작동을 방지한다.

### 4. 진동 횟수 / 진폭 계산

```python
chop_osc = _count_oscillations(wy_arr, OSCILLATION_AMP)
stir_osc = _count_oscillations(wx_arr, OSCILLATION_AMP)
y_amp    = wy_arr.max() - wy_arr.min()                          # 전체 버퍼 진폭
r_y_amp  = wy_arr[-RECENT_FRAMES:].max() - wy_arr[-RECENT_FRAMES:].min()  # 최근 N프레임 진폭
```

### 5. 판정

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
| `is_chop and is_stir` | `r_y_amp > r_x_amp × AXIS_DOMINANCE` → CHOP<br>`r_x_amp > r_y_amp × AXIS_DOMINANCE` → STIR<br>그 외 → IDLE |
| `is_chop only` | CHOP |
| `is_stir only` | STIR |
| 둘 다 false | IDLE |

**대진폭 shortcut**: `OSCILLATION_AMP_LARGE` 이상의 진폭은 방향 전환 1번만으로도 인정한다.

### 6. Hold 메커니즘

```
raw != IDLE  →  held_gesture = raw, hold_counter = HOLD_FRAMES, output = raw
raw == IDLE, hold_counter > 0  →  hold_counter--, output = held_gesture
raw == IDLE, hold_counter == 0  →  output = IDLE
```

동작 중 순간적인 IDLE 깜빡임을 방지한다.

---

## 하이퍼파라미터

| 상수 | 기본값 | 설명 |
|------|--------|------|
| `BUFFER_SIZE` | 45 | 슬라이딩 윈도우 프레임 수 (~1.5초 @ 30fps) |
| `OSCILLATION_MIN` | 3 | 최소 방향 전환 횟수 (최소 1.5 사이클) |
| `OSCILLATION_AMP` | 0.05 | 유효 전환으로 인정할 최소 진폭 (정규화 좌표, 화면 5%) |
| `OSCILLATION_AMP_LARGE` | 0.20 | 이 값 이상이면 방향 전환 1개만으로 판정 가능 (shortcut) |
| `AXIS_DOMINANCE` | 1.5 | chop/stir 동시 판정 시 우세 축 결정 비율 |
| `RECENT_FRAMES` | 25 | 최근 N프레임 진폭 게이트 크기 (~0.83초 @ 30fps) |
| `HOLD_FRAMES` | 8 | IDLE 전환 전 이전 제스처 유지 프레임 수 |
| `HAND_CACHE_MAX` | 4 | gap filling 최대 프레임 수 |
| `STILL_SPEED_MAX` | 0.006 | 정지 판정 손목 속도 임계값 (정규화 좌표/프레임) |
| `STILL_RESET_FRAMES` | 10 | 연속 정지 시 버퍼 초기화 기준 프레임 수 |

---

## 좌표계 참고

MediaPipe Hands 정규화 좌표:
- `x`: 0(좌) ~ 1(우)
- `y`: 0(상) ~ 1(하) ← **y 축 하향이 양수**
- `z`: 깊이 (사용 안 함)

---

## 구현 체크리스트

- [ ] `Gesture` Enum 정의 (`IDLE`, `CHOP`, `STIR`)
- [ ] `GestureDetector.__init__`: MediaPipe Hands 초기화, 버퍼/상태 변수 초기화
- [ ] `GestureDetector.detect`: 전처리 → 버퍼 → 정지 감지 → 진동 측정 → 판정 → Hold
- [ ] `GestureDetector.draw_landmarks`: 마지막 추론 결과로 랜드마크 시각화
- [ ] `GestureDetector.close`: 리소스 해제
- [ ] `_count_oscillations`: 평활화 → 방향 전환 카운트 → 진폭 필터
- [ ] `_amplitude`: 버퍼 최대-최소 범위 반환 (유틸 함수)