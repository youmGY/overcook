# Chop / Stir 모션 인식 알고리즘

## 개요

카메라로 촬영한 손의 **손목(wrist) 좌표**를 매 프레임 추적하여,
위아래 반복 움직임을 **chop**, 좌우 반복 움직임을 **stir**로 인식한다.

- chop: y축 진동 (손목이 위↔아래)
- stir: x축 진동 (손목이 좌↔우)

---

## 핵심 개념

### 1. 좌표 수집

MediaPipe가 매 프레임 손 랜드마크 21개를 반환한다.
그 중 **wrist(0번 랜드마크)**의 `(x, y)` 좌표(0.0~1.0 정규화)를 사용한다.

```
매 프레임:
  wrist = (0.45, 0.62)  ← 화면 기준 정규화 좌표
  st.wy.append(0.62)    ← y좌표를 deque에 저장
  st.wx.append(0.45)    ← x좌표를 deque에 저장
```

deque의 `maxlen`은 **600** (안전 상한). 실제로는 반전마다 클리어되므로
이 한도에 도달하는 일은 거의 없다.

### 2. EMA (Exponential Moving Average, 지수이동평균)

손목 좌표는 프레임마다 노이즈(떨림)가 있다.
EMA는 **최근 값에 더 큰 가중치**를 주는 스무딩 기법이다.

```
공식: ema_new = α × raw + (1 - α) × ema_old

α = 0.35 (기본값, FPS에 따라 보정)
```

**예시** (y축):

| 프레임 | raw_y | ema_y | 설명 |
|--------|-------|-------|------|
| 1 | 0.50 | 0.50 | 초기값 |
| 2 | 0.55 | 0.52 | 급변하지 않음 |
| 3 | 0.48 | 0.50 | 노이즈 억제 |
| 4 | 0.40 | 0.47 | 실제 하강 반영 |

이 스무딩된 값(`ema_y`)으로 방향 반전을 판단한다.
raw 값 대신 EMA를 쓰면 **한 프레임짜리 떨림으로 가짜 반전이 발생하는 것을 방지**한다.

### 3. 방향(direction)과 꼭짓점(extreme)

손목이 이동 중인 방향을 추적한다.

```
_dir_y =  1  → 현재 아래로 이동 중 (y값 증가 = 화면상 아래)
_dir_y = -1  → 현재 위로 이동 중 (y값 감소 = 화면상 위)
```

`_extreme_y`는 **현재 방향에서의 최대/최소값** (꼭짓점)이다.

**중요: micro-flip 가드** — 방향과 꼭짓점은 **진폭 임계값을 통과한 유효한 반전에서만**
업데이트된다. 노이즈로 인한 미세한 방향 전환(micro-flip)은 무시되어
꼭짓점이 잘못 리셋되는 것을 방지한다.

```
노이즈 예시:
  ema: 0.50 → 0.49 → 0.50  (진폭 0.01, 임계값 0.025 미달)
  → _dir_y, _extreme_y 변경 없음 (무시)
```

---

## 반전 (Reversal) 감지

손목이 **방향을 바꾸고**, 이전 꼭짓점과의 차이가 **임계값 이상**이면 유효한 반전으로 인정한다.

```
조건: abs(ema_y - extreme_y) >= _OSCILLATION_AMP_Y (0.025)
```

### 반전 과정 예시 (chop)

```
시간 →

y좌표   ╲        ╱        ╲        ╱
         ╲      ╱          ╲      ╱
          ╲    ╱            ╲    ╱
           ╲  ╱              ╲  ╱
            ╲╱                ╲╱

        extreme  반전1    extreme  반전2
                            ↑
                        _rev_chop = 2
```

1. 손이 **아래로** → `_dir_y = 1`, `_extreme_y` 갱신
2. 손이 **위로** 전환 → `abs(ema - extreme) >= 0.025` → **반전1** (`_rev_chop += 1`)
3. 손이 **아래로** 전환 → 같은 조건 통과 → **반전2** (`_rev_chop += 1`)

### 반전 시 deque 리셋과 extreme 시드

유효한 반전이 감지되면 deque를 비우고 **이전 꼭짓점 + 현재 위치**를 seed한다.

```python
prev_extreme_y = st._extreme_y
st.wy.clear()
st.wy.append(prev_extreme_y)  # 이전 꼭짓점
st.wy.append(wy_raw)          # 현재 위치
# _extreme_y, _dir_y 업데이트 (유효 반전에서만)
st._extreme_y = st._ema_y
st._dir_y = new_dir_y
```

이렇게 하면:
- 진폭(`r_y_amp`) = `abs(현재 - 꼭짓점)` → **즉시 복구**
- 사람의 속도와 무관하게 **현재 스트로크** 기준으로 측정
- 느린/빠른 사람 모두 정확한 진폭 측정 가능
- 진폭 미달 시 extreme/dir 유지 → micro-flip 가드

---

## 액션 카운트

**반전 2회 = 왕복 1사이클 = 1 action**

```python
chop_new = (st._rev_chop // 2) - (st._prev_rev_chop // 2)
```

| _rev_chop | 계산 | action 발생 |
|-----------|------|------------|
| 1 | (1//2)-(0//2) = 0 | × |
| 2 | (2//2)-(1//2) = 1 | ✓ action 1 |
| 3 | (3//2)-(2//2) = 0 | × |
| 4 | (4//2)-(3//2) = 1 | ✓ action 2 |

"칼로 한 번 썬다" = 내리고 올리는 **완전한 1왕복**이므로 반전 2회로 설정.

---

## 진폭 (Amplitude) 게이트

반전 횟수만으로는 부족하다. 작은 떨림도 반전으로 잡힐 수 있기 때문에, **deque 전체의 진폭**이 임계값 이상인지도 확인한다.

```python
r_y_amp = _recent_amplitude(st.wy, len(st.wy))  # deque 전체의 max - min

is_chop = (chop_osc >= 2) and (r_y_amp >= 0.025)
```

반전마다 deque가 클리어되므로, `len(st.wy)`는 항상 **현재 스트로크의 데이터만** 포함한다.
별도의 FPS 기반 윈도우 계산이 필요 없다.

| 파라미터 | 값 | 의미 |
|----------|----|------|
| `_OSCILLATION_AMP_Y` | 0.025 | chop 최소 진폭 (y축) |
| `_OSCILLATION_AMP_X` | 0.03 | stir 최소 진폭 (x축) |
| `_OSCILLATION_AMP_LARGE_Y` | 0.08 | 큰 진폭이면 반전 2회로도 인정 |
| `_OSCILLATION_AMP_LARGE_X` | 0.12 | 큰 진폭이면 반전 2회로도 인정 |

---

## chop vs stir 판별

y축과 x축 모두 조건을 만족하면 **축 우세(axis dominance)**로 결정한다.

```python
_AXIS_DOMINANCE = 1.1

if r_y_amp > r_x_amp * 1.1:    → chop (y축이 10% 이상 우세)
elif r_x_amp > r_y_amp * 1.1:  → stir (x축이 10% 이상 우세)
else:                          → 반전 횟수가 많은 쪽
```

---

## 홀드 (Hold Counter)

모션이 감지되면 **10프레임 동안 라벨을 유지**한다.

```python
if raw is not None:
    st.hold_counter = 10   # 감지됨 → 카운터 리셋
    output = raw
elif st.hold_counter > 0:
    st.hold_counter -= 1   # 안 감지됐지만 유지
    output = st.held_gesture
else:
    output = None           # 완전히 끝남
```

역할:
- 스트로크 사이의 짧은 공백(반전 직후 데이터 부족)을 메워준다
- 게임에서 chop/stir 라벨이 끊기지 않고 연속 전달된다

---

## 손 유실 시 좌표 예측 (Hand Prediction)

stir 동작 중 손이 옆면(profile)으로 보이면 MediaPipe가 랜드마크 검출에 실패한다.
이때 **마지막 속도(velocity)를 기반으로 좌표를 예측**하여 모션 추적을 유지한다.

```python
_HAND_CACHE_MAX = 30  # 기준: 30fps에서 30프레임

# 실제 cache_max = max(3, round(30 * fps_scale))
# 10fps → fps_scale ≈ 0.33 → cache_max = 10 (약 1초)
```

### 예측 과정

```
프레임1: wrist=None → wrist_absent=1
  pred_x = last_x + vx × 0.85^(1/fps_scale)   ← 감쇠된 속도로 예측
  pred_y = last_y + vy × 0.85^(1/fps_scale)
  → deque에 예측값 추가, 반전 카운트 유지

프레임2: wrist=None → wrist_absent=2
  → 같은 방식, 더 감쇠된 속도로 계속 예측

...

프레임10: wrist=None → wrist_absent=10 ≥ cache_max(10)
  → _reset_motion_track_state() 호출 → 전체 리셋
```

| 파라미터 | 값 | 의미 |
|----------|----|------|
| `_HAND_CACHE_MAX` | 30 | 예측 유지 프레임 수 (FPS 보정 전) |
| 감쇠 계수 | 0.85 | 예측 속도 감쇠 (`0.85^(n/fps_scale)`) |

**chop에 영향 없는 이유**: chop 시 손바닥이 카메라를 향하므로 랜드마크 검출이
끊기지 않아 이 예측 경로를 타지 않는다.

---

## hand_scale 즉시 초기화

손 크기(`hand_scale`)는 진폭 임계값 보정에 사용된다.
첫 감지 시 EMA를 거치지 않고 **즉시 현재 값으로 설정**한다.

```python
if st.wrist_absent >= cache_max:
    st.hand_scale = hand_scale_now      # 첫 감지: 즉시 설정
else:
    st.hand_scale = EMA(st.hand_scale, hand_scale_now)  # 이후: 점진적 갱신
```

이전에는 기본값 `0.12`에서 EMA로 수렴하느라 초기 몇 프레임의
진폭 보정이 부정확했다.

---

## 정지 리셋 (Still Reset)

손이 **60프레임(FPS 보정됨) 동안 움직이지 않으면** 모든 모션 상태를 초기화한다.

```python
_STILL_SPEED_MAX = 0.001  # 이 속도 이하면 "정지"로 판단
_STILL_RESET_FRAMES = 60  # 60프레임 연속 정지 시 리셋
```

리셋 시: deque, EMA, 방향, 반전 카운트 전부 초기화.

---

## 게임 연동

### 완료 시 리셋

게임에서 chop/stir가 완료(잠금 해제)되면 `pipeline.reset_motion()`을 호출하여
모션 버퍼를 명시적으로 비운다. 이전 동작 데이터가 다음 판정에 영향을 주지 않도록 한다.

### 잠금 진입 시 리셋

chop/stir 잠금 모드에 진입할 때도 `reset_motion()`을 호출한다.
이전 이동 동작의 잔여 데이터가 즉시 chop/stir 카운트로 오인되는 것을 방지한다.

### 액션 우선순위

잠금 모드가 아닐 때의 액션 처리 순서:

```
confirm (thumbs_up) → chop → stir
```

confirm을 최우선으로 처리하여, 도마 위에 재료를 놓을 때
동시에 chop이 감지되더라도 confirm(놓기)이 먼저 실행된다.

### MediaPipe 트래킹 설정

```python
min_detection_confidence = 0.2   # 새 손 검출 임계값
min_tracking_confidence  = 0.1   # 기존 손 추적 임계값 (낮춰서 유실 감소)
```

`min_tracking_confidence`를 `0.1`로 낮춰 stir 중 손이 옆면으로 보일 때도
가능한 한 추적을 유지한다.

---

## 전체 흐름 요약

```
매 프레임:
  1. 손목 좌표 수집 → deque에 저장
  2. EMA 스무딩 → 노이즈 제거
  3. 방향 추적 → 반전 감지 (amplitude gate 통과 시)
  4. 반전 시 deque 리셋 (꼭짓점 + 현재값 seed)
  5. 반전 2회 = 1 action → 게임에 전달
  6. 축 우세로 chop vs stir 판별
  7. hold_counter로 라벨 유지 (끊김 방지)
  8. 정지 시 / 게임 완료 시 전체 리셋
```
