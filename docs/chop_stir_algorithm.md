# Chop / Stir 알고리즘 — 카메라부터 게임까지

> 이 문서는 overcook 게임에서 **chop(썰기)** 과 **stir(젓기)** 가
> 어떻게 동작하는지를 처음 보는 사람도 이해할 수 있도록 전체 흐름을 정리한 것이다.

---

## 목차

1. [전체 파이프라인 한눈에 보기](#1-전체-파이프라인-한눈에-보기)
2. [STEP 1 — 카메라 → 손 랜드마크](#2-step-1--카메라--손-랜드마크)
3. [STEP 2 — 손목 좌표 수집](#3-step-2--손목-좌표-수집)
4. [STEP 3 — EMA 스무딩 (노이즈 제거)](#4-step-3--ema-스무딩-노이즈-제거)
5. [STEP 4 — 방향 추적과 반전 감지](#5-step-4--방향-추적과-반전-감지)
6. [STEP 5 — 액션 카운트 (반전 → 게임 동작)](#6-step-5--액션-카운트-반전--게임-동작)
7. [STEP 6 — chop vs stir 판별](#7-step-6--chop-vs-stir-판별)
8. [STEP 7 — 홀드 (Hold Counter)](#8-step-7--홀드-hold-counter)
9. [STEP 8 — GameInput 변환](#9-step-8--gameinput-변환)
10. [STEP 9 — 게임 Lock Mode](#10-step-9--게임-lock-mode)
11. [보조 메커니즘](#11-보조-메커니즘)
12. [파라미터 일람표](#12-파라미터-일람표)
13. [전체 흐름 요약](#13-전체-흐름-요약)

---

## 1. 전체 파이프라인 한눈에 보기

```
┌──────────┐    ┌───────────┐    ┌──────────────┐    ┌──────────┐    ┌──────────┐
│  카메라   │ →  │ MediaPipe │ →  │ MotionDetect │ →  │ GameInput│ →  │  Game    │
│ (frame)  │    │ (landmarks│    │ (chop/stir   │    │ (chop=T, │    │ (lock    │
│          │    │  21 points)│    │  reversal    │    │  stir=T) │    │  mode)   │
└──────────┘    └───────────┘    │  counting)   │    └──────────┘    └──────────┘
                                 └──────────────┘
```

| 단계 | 파일 | 입력 | 출력 |
|------|------|------|------|
| 카메라 촬영 | `recognition/camera.py` | USB 카메라 프레임 | BGR 이미지 |
| CLAHE 보정 | `recognition/interface.py` | BGR 이미지 | 밝기 보정된 이미지 |
| 손 추적 | `recognition/hand_tracker.py` | 보정된 이미지 | 손 랜드마크 21개 × 2손 |
| 모션 감지 | `recognition/motion.py` | 손목 (x,y) 매 프레임 | `"chop_motion"` / `"stir_motion"` + count |
| 입력 변환 | `input.py` | HandInput 리스트 | GameInput (chop=T/F, stir=T/F) |
| 게임 처리 | `game.py` | GameInput | lock mode → 도마 자르기 / 냄비 젓기 |

---

## 2. STEP 1 — 카메라 → 손 랜드마크

```python
# recognition/interface.py — RecognitionPipeline.step()
ok, frame = self._cap.read()          # 1. 카메라에서 한 프레임 읽기
frame = cv2.flip(frame, 1)            # 2. 좌우 반전 (거울 모드)
frame = _apply_clahe(frame, ...)      # 3. CLAHE 밝기 보정
hand_results = self._hands.process(frame)  # 4. MediaPipe 손 추적
```

MediaPipe HandLandmarker가 프레임에서 **손 하나당 21개의 랜드마크**를 반환한다.
각 좌표는 `(x, y)` — **0.0~1.0 정규화** (화면 왼쪽 위가 원점).

```
          8   12  16  20          ← 손가락 끝 (TIP)
          |   |   |   |
     4    7  11  15  19           ← 각 관절
      \   |   |   |   |
       3  6  10  14  18
        \ |   |   |   |
         [5] [9] [13][17]        ← 손가락 뿌리 (MCP)
          \   |   /   /
           \  |  /   /
            [  0  ]               ← 0번: WRIST ★ 이것만 사용
```

**chop/stir 감지에는 0번 wrist 좌표만 사용한다.**

### MediaPipe 설정

```python
min_detection_confidence = 0.2   # 새 손을 처음 발견할 때의 최소 신뢰도
min_tracking_confidence  = 0.1   # 이미 추적 중인 손을 유지하는 최소 신뢰도
```

`min_tracking_confidence`를 낮추면 stir 중 손이 옆면(profile)으로 보여
검출이 약해져도 가능한 한 추적을 유지한다.

---

## 3. STEP 2 — 손목 좌표 수집

`recognition/motion.py` — `MotionDetector.update()` 내부:

```python
# 매 프레임, 각 손(left/right)에 대해:
wx, wy = wrist_pos            # 손목의 정규화 좌표 (0.0~1.0)
st.wx.append(wx)              # x좌표 → deque에 저장 (stir용)
st.wy.append(wy)              # y좌표 → deque에 저장 (chop용)
```

- deque `maxlen = 600` (안전 상한)
- 실제로는 **유효한 반전마다 deque를 비우므로** 이 한도에 도달하지 않는다

### 손목 속도 계산

```python
dx = wx - prev_wx
dy = wy - prev_wy
speed = max(abs(dx), abs(dy))   # x/y 중 큰 변화량
```

속도는 5프레임 이동평균(`avg_speed`)으로도 집계되어 정지 감지 등에 쓰인다.

---

## 4. STEP 3 — EMA 스무딩 (노이즈 제거)

손목 좌표는 프레임마다 떨림이 있다.
**EMA(Exponential Moving Average, 지수이동평균)** 로 노이즈를 제거한다.

```
공식: ema_new = α × raw + (1 − α) × ema_old

α = 0.35 (기본값, FPS에 따라 보정)
```

**예시 (y축):**

| 프레임 | raw_y | ema_y | 설명 |
|--------|-------|-------|------|
| 1 | 0.50 | 0.50 | 초기값 = raw |
| 2 | 0.55 | 0.52 | 약간만 반영 |
| 3 | 0.48 | 0.50 | 떨림 억제 |
| 4 | 0.40 | 0.47 | 실제 하강 반영 |

raw 값 대신 **EMA를 기준으로 방향 반전을 판단**한다.
→ 한 프레임짜리 떨림으로 가짜 반전이 발생하는 것을 방지.

---

## 5. STEP 4 — 방향 추적과 반전 감지

### 5-1. 방향(direction)과 꼭짓점(extreme)

```
_dir_y =  1  → 아래로 이동 중 (y값 증가 = 화면 아래쪽)
_dir_y = -1  → 위로 이동 중 (y값 감소 = 화면 위쪽)
_dir_y =  0  → 아직 방향 미결정 (데이터 3개 미만)
```

`_extreme_y`는 **현재 방향에서 도달한 최대/최소값** (꼭짓점).
손이 같은 방향으로 계속 이동하면 extreme이 갱신된다.

### 5-2. 유효한 반전 (Reversal)

손목이 **방향을 바꾸고**, extreme과의 차이가 **임계값 이상**이면 유효한 반전이다.

```
조건: abs(ema_y − extreme_y) ≥ AMP_Y (0.025)
```

**반전 과정 시각화 (chop = y축 상하 운동):**

```
시간 →

y좌표   ╲        ╱        ╲        ╱
         ╲      ╱          ╲      ╱
          ╲    ╱            ╲    ╱
           ╲  ╱              ╲  ╱
            ╲╱                ╲╱
         extreme ↑반전1   extreme ↑반전2
                              ↑
                         _rev_chop = 2
```

1. 손이 **아래로** 이동 → `_dir_y=1`, `_extreme_y` 갱신
2. 손이 **위로** 전환 → `abs(ema − extreme) ≥ 0.025` → **반전1** (`_rev_chop += 1`)
3. 다시 **아래로** 전환 → 같은 검사 통과 → **반전2** (`_rev_chop += 1`)

### 5-3. Micro-flip 가드

방향과 extreme은 **임계값을 통과한 유효 반전에서만** 업데이트된다.
노이즈로 인한 미세 진동(micro-flip)은 무시한다.

```
노이즈: ema 0.50 → 0.49 → 0.50  (차이 0.01, 임계값 0.025)
→ _dir_y, _extreme_y 변경 없음 → 가짜 반전 방지 ✓
```

### 5-4. 반전 시 deque 리셋

유효 반전이 발생하면 deque를 비우고, **이전 꼭짓점 + 현재 좌표**로 다시 채운다.

```python
prev_extreme_y = st._extreme_y
st.wy.clear()                    # deque 초기화
st.wy.append(prev_extreme_y)    # ① 이전 꼭짓점
st.wy.append(wy_raw)            # ② 현재 위치
st._extreme_y = st._ema_y       # 새 극값 시작
st._dir_y = new_dir_y           # 방향 전환
```

효과:
- 진폭(`r_y_amp`) = `max − min` = `abs(현재 − 꼭짓점)` → **즉시 복구**
- 과거 데이터가 쌓이지 않아 **현재 스트로크만** 기준으로 진폭 측정
- 느린 사람이든 빠른 사람이든 정확

---

## 6. STEP 5 — 액션 카운트 (반전 → 게임 동작)

**반전 2회 = 왕복 1사이클 = action 1회**

```python
chop_new = (st._rev_chop // 2) − (st._prev_rev_chop // 2)
```

| _rev_chop | 계산 | action? |
|-----------|------|---------|
| 0 | 0 − 0 = 0 | × |
| 1 | 0 − 0 = 0 | × |
| 2 | 1 − 0 = **1** | ✓ action 1 |
| 3 | 1 − 1 = 0 | × |
| 4 | 2 − 1 = **1** | ✓ action 2 |

"칼로 한 번 내리고 올린다" = 완전한 1왕복 → 반전 2회.

### 진폭 게이트 (Amplitude Gate)

반전 횟수만으로는 부족하다. deque 전체의 진폭도 임계값 이상이어야 한다:

```python
r_y_amp = max(st.wy) − min(st.wy)   # deque 전체 진폭

is_chop = (rev_chop ≥ 2) and (r_y_amp ≥ 0.025)
```

반전마다 deque가 리셋되므로, deque에는 항상 **현재 스트로크 데이터만** 들어있다.

---

## 7. STEP 6 — chop vs stir 판별

y축(chop)과 x축(stir) 모두 조건을 만족하면 **축 우세(axis dominance)** 로 판별:

```
if r_y_amp > r_x_amp × 1.1  →  chop  (y축이 10% 이상 우세)
if r_x_amp > r_y_amp × 1.1  →  stir  (x축이 10% 이상 우세)
else                         →  반전 횟수가 더 많은 쪽
```

단일 축만 조건을 만족하면 판별 없이 바로 결정:
- y축만 통과 → chop
- x축만 통과 → stir
- 둘 다 미통과 → idle (모션 없음)

---

## 8. STEP 7 — 홀드 (Hold Counter)

모션이 감지되면 **10프레임(FPS 보정) 동안 라벨을 유지**한다.

```python
if raw is not None:          # 이번 프레임에 모션 감지됨
    hold_counter = 10
    output = raw
elif hold_counter > 0:       # 안 감지됐지만 여전히 유지 구간
    hold_counter -= 1
    output = held_gesture    # 이전에 감지된 라벨 유지
else:                        # 완전히 끝남
    output = None
```

역할:
- 반전 직후 데이터가 부족한 짧은 공백을 메워준다
- 게임에서 chop/stir 라벨이 끊기지 않고 연속 전달

---

## 9. STEP 8 — GameInput 변환

`recognition/interface.py`의 `RecognitionPipeline.step()`이
`MotionDetector`의 결과를 `HandInput`에 담는다:

```python
# HandInput (손 하나의 정보)
HandInput(
    motion = "chop_motion",  # 또는 "stir_motion" 또는 None
    motion_count = 1,        # 이번 프레임에 완료된 왕복 횟수 (0 또는 1+)
    ...
)
```

`input.py`의 `hand_inputs_to_game_input()`이 HandInput → GameInput 변환:

```python
# motion_count > 0 일 때만 True
if h.motion == "chop_motion" and h.motion_count > 0:
    gi.chop = True
elif h.motion == "stir_motion" and h.motion_count > 0:
    gi.stir = True
```

**핵심**: `motion_count > 0` — 실제 왕복이 완료된 프레임에서만 `chop=True`.
모션이 감지 중이지만 아직 왕복이 안 끝났으면 `chop=False`.

키보드와 제스처 입력은 `merge_inputs()`로 OR 병합:

```python
merged.chop = keyboard.chop or gesture.chop
merged.stir = keyboard.stir or gesture.stir
```

---

## 10. STEP 9 — 게임 Lock Mode

`game.py`에서 chop/stir의 게임 로직을 처리한다.

### 10-1. Lock Mode란?

플레이어가 도마/냄비 앞에서 자르기/젓기를 시작하면 **lock mode**에 진입한다.
lock mode 동안은:
- **이동이 차단**된다 (플레이어가 도마/냄비에 고정)
- chop/stir 입력만 유효하다
- 작업 완료 시 자동으로 lock이 해제된다

### 10-2. Lock 진입 과정

**Chop lock 진입** — `_act_chop()`:

```python
# 플레이어가 재료를 들고 도마 앞에서 action
st.chop_item = dict(h)          # 재료를 도마에 놓기
self.player.holding = None      # 손에서 내려놓기
st.chop_prog = 0.0              # 진행률 0%
self._lock_mode = "chop"        # ★ lock mode 진입
self._locked_station = st       # 잠긴 스테이션 기록
self._motion_gate_ready["chop"] = False  # 모션 게이트 비활성화
self._pipeline.reset_motion()   # ★ 모션 버퍼 리셋
```

**Stir lock 진입** — `_act_pot()`:

```python
# 냄비에 재료가 있고, 아직 요리가 안 시작된 상태에서 stir 입력
st.pot_on = True
st.pot_cooking = True
st.pot_stirs = 0
st.pot_prog = 0.0
self._lock_mode = "stir"        # ★ lock mode 진입
self._locked_station = st
self._motion_gate_ready["stir"] = False
self._pipeline.reset_motion()   # ★ 모션 버퍼 리셋
```

**왜 진입할 때 reset_motion()을 호출하는가?**
→ 이전 이동(slot 전환 등)의 잔여 손목 데이터가 즉시 chop/stir 카운트로 오인되는 것을 방지.

### 10-3. Lock 중 동작 — `_process_lock_mode()`

이 메서드는 **싱글플레이의 `update()`와 멀티플레이의 `_process_single_input()`
양쪽에서 공통으로 호출**된다.

```
[Game.update()]  ──────→  _process_lock_mode()  ← 공유
[_process_single_input()] ──→  _process_lock_mode()  ← 공유
```

```python
def _process_lock_mode(self, act_flags, gi, dt, gw):
    st = self._locked_station

    # 1. 이동 차단 (속도 0으로 물리 업데이트)
    self.player.update(0, dt, gw, gy)

    # 2. 모션 게이트 — 첫 neutral 프레임 대기
    if self._lock_mode == "chop" and not gi.chop:
        self._motion_gate_ready["chop"] = True   # 한 번 chop이 False가 되어야 활성화

    # 3. Chop/Stir 액션 처리
    if self._lock_mode == "chop" and act_flags["chop"]:
        if gi.chop and not self._motion_gate_ready["chop"]:
            pass   # 아직 게이트 비활성 → 무시
        else:
            self._act_chop(st, chop_action=True)

    # 4. Confirm = 완성품 집기
    if act_flags["confirm"] and st:
        self._act_chop(st, chop_action=False)   # 잘린 재료 픽업
```

### 모션 게이트 (Motion Gate Ready)

lock 진입 직후, 이전 프레임의 잔여 chop/stir 신호가 남아있을 수 있다.
**모션 게이트**는 한 번 `chop=False` (신호 없음) 프레임이 와야 비로소 입력을 받기 시작한다:

```
프레임:  | lock 진입 | chop=T | chop=F | chop=T | chop=T |
게이트:  | False     | False  | True←  | True   | True   |
실제동작: | 무시      | 무시   | -      | ★ 자르기| ★ 자르기|
```

### 10-4. Chop 실제 동작 — `_act_chop(st, chop_action=True)`

```python
st.chop_hits += 1                                  # 자르기 횟수 +1
st.chop_prog = st.chop_hits / CHOP_ACTIONS         # 진행률 갱신
# CHOP_ACTIONS = 4 → 4왕복이면 자르기 완료
```

`CHOP_ACTIONS = 4` → 손을 4번 왕복하면 (= 반전 8회) 재료가 잘린다.

### 10-5. Stir 실제 동작 — `_act_pot(st, stir_only=True)`

```python
st.pot_stirs += 1                                  # 젓기 횟수 +1
st.pot_prog = st.pot_stirs / STIR_ACTIONS           # 진행률 갱신
# STIR_ACTIONS = 5 → 5왕복이면 요리 완료
```

`STIR_ACTIONS = 5` → 손을 5번 왕복하면 요리가 완성된다.

**과도한 젓기 주의:**

```python
OVER_STIR_THRESHOLD = STIR_ACTIONS + 5  # = 10
if st.pot_stirs >= 10:
    st.pot_burned = True   # 음식이 타버린다!
```

### 10-6. Lock 해제 조건

```python
# Chop lock 해제:
if not st.chop_item or st.chop_item.get("chopped"):
    self._lock_mode = None
    self._pipeline.reset_motion()   # ★ 다시 리셋

# Stir lock 해제:
if st.pot_cooked or st.pot_burned or (not st.pot_cooking and not st.pot_items):
    self._lock_mode = None
    self._pipeline.reset_motion()   # ★ 다시 리셋
```

**왜 해제할 때도 reset_motion()을 호출하는가?**
→ chop/stir 동작의 잔여 데이터가 이후 이동이나 다른 스테이션에 영향을 주지 않도록.

**총 4곳에서 reset_motion() 호출:**
1. chop lock 진입
2. stir lock 진입
3. chop lock 해제
4. stir lock 해제

### 10-7. Free Actions (Lock이 아닐 때)

lock mode가 아닐 때 chop/stir 신호가 들어오면 `_process_free_actions()`에서 처리:

```python
def _process_free_actions(self, act_flags):
    handled = False
    if act_flags["chop"]:          # 1순위: chop
        st = self._near()
        if st and st.kind == "chop":
            self._act_chop(st, chop_action=True)
            handled = True
    if act_flags["stir"] and not handled:   # 2순위: stir
        st = self._near()
        if st and st.kind == "pot":
            self._act_pot(st, stir_only=True)
            handled = True
    if act_flags["confirm"] and not handled:   # 3순위: confirm
        self.do_action()
```

**우선순위: chop → stir → confirm**

이 메서드도 싱글/멀티 양쪽에서 공통 호출된다.

---

## 11. 보조 메커니즘

### 11-1. 손 유실 시 좌표 예측 (Hand Prediction)

stir 중 손이 **옆면(profile)** 으로 보이면 MediaPipe가 검출에 실패할 수 있다.
이때 **마지막 속도를 감쇠시켜 좌표를 예측**하여 모션 추적을 유지한다.

```python
# 손이 안 보이지만 캐시 한도 내:
damp = 0.85 ^ ((absent_frames + 1) / fps_scale)
pred_x = last_x + vx × damp
pred_y = last_y + vy × damp
st.wx.append(pred_x)   # 예측값을 deque에 추가
st.wy.append(pred_y)

# 캐시 한도 초과 (기본 30프레임, FPS 보정):
→ 전체 모션 상태 리셋
```

| 파라미터 | 기본값 | 의미 |
|----------|--------|------|
| `_HAND_CACHE_MAX` | 30 | 예측 유지 최대 프레임 (FPS 보정 전) |
| 감쇠 계수 | 0.85 | 예측 속도 감쇠율 |

chop에는 영향 없음: chop 시 손바닥이 카메라를 향하므로 검출이 끊기지 않는다.

### 11-2. hand_scale 보정

카메라와 손 사이 거리에 따라 진폭 임계값을 자동 조정한다.

```python
# 손 크기 = max(손바닥 너비, 손바닥 길이) — 정규화 좌표 기준
hand_factor = hand_scale / 0.12   # 기준값 대비 비율 (0.6~1.6 클램프)

amp_y_threshold = 0.025 × hand_factor   # 가까우면 크게, 멀면 작게
amp_x_threshold = 0.03  × hand_factor
```

첫 감지 시 EMA 없이 즉시 설정하여 초기 몇 프레임의 보정 오차를 방지한다.

### 11-3. 정지 리셋 (Still Reset)

손이 **60프레임(FPS 보정) 연속 정지**하면 전체 모션 상태를 초기화한다.

```python
_STILL_SPEED_MAX   = 0.001   # 이 속도 이하 = "정지"
_STILL_RESET_FRAMES = 60     # 연속 정지 프레임 수 (FPS 보정 전)
```

리셋 대상: deque, EMA, 방향, 꼭짓점, 반전 카운트, 속도 버퍼, hold counter.

### 11-4. FPS 보정

Raspberry Pi에서 ~10fps로 동작하므로 모든 프레임 기반 파라미터에 FPS 보정을 적용한다.

```python
fps_scale = actual_fps / 30        # 기준 30fps
amp_window = round(30 × fps_scale)   # 10fps → 10 프레임
still_reset = round(60 × fps_scale)  # 10fps → 20 프레임
hold = round(10 × fps_scale)         # 10fps → 3 프레임
cache_max = round(30 × fps_scale)    # 10fps → 10 프레임
```

EMA alpha도 FPS에 맞게 보정:

```python
ema_alpha = 1 − (1 − 0.35) ^ (1 / fps_scale)
```

---

## 12. 파라미터 일람표

### 모션 감지 (`recognition/motion.py`)

| 파라미터 | 기본값 | 설명 |
|----------|--------|------|
| `_OSCILLATION_MIN_CHOP` | 2 | chop 인정 최소 반전 수 |
| `_OSCILLATION_MIN_STIR` | 2 | stir 인정 최소 반전 수 |
| `_OSCILLATION_AMP_Y` | 0.025 | chop 최소 진폭 (y축) |
| `_OSCILLATION_AMP_X` | 0.03 | stir 최소 진폭 (x축) |
| `_OSCILLATION_AMP_LARGE_Y` | 0.08 | 큰 진폭이면 반전 2회로도 인정 (y) |
| `_OSCILLATION_AMP_LARGE_X` | 0.12 | 큰 진폭이면 반전 2회로도 인정 (x) |
| `_AXIS_DOMINANCE` | 1.1 | chop/stir 판별 시 축 우세 비율 |
| `_HOLD_FRAMES` | 10 | 라벨 유지 프레임 |
| `_HAND_CACHE_MAX` | 30 | 손 유실 시 예측 유지 프레임 |
| `_STILL_SPEED_MAX` | 0.001 | 정지 판단 속도 임계값 |
| `_STILL_RESET_FRAMES` | 60 | 정지 리셋까지 프레임 수 |
| `_BUFFER_MAXLEN` | 600 | deque 최대 길이 (안전 상한) |
| `_DESIGN_FPS` | 30 | FPS 보정 기준값 |
| `_HAND_SCALE_REF` | 0.12 | hand_scale 기준값 |
| `_HAND_SCALE_EMA_ALPHA` | 0.25 | hand_scale EMA 가중치 |
| `_EMA_ALPHA_BASE` | 0.35 | 좌표 스무딩 EMA 가중치 |
| 감쇠 계수 | 0.85 | 손 유실 예측 속도 감쇠 |

### 게임 (`overcook/constants.py`)

| 파라미터 | 값 | 설명 |
|----------|-----|------|
| `CHOP_ACTIONS` | 4 | 자르기 완료까지 필요한 왕복 수 |
| `STIR_ACTIONS` | 5 | 요리 완료까지 필요한 왕복 수 |
| `OVER_STIR_THRESHOLD` | 10 | 이 이상 젓으면 음식이 탐 |
| `BURN_TIME` | 7.0 | 탄 음식 표시 시간 (초) |

---

## 13. 전체 흐름 요약

```
[A. 카메라 → 모션 감지]

  카메라 프레임
       ↓
  CLAHE 밝기 보정
       ↓
  MediaPipe HandLandmarker → 손 21개 랜드마크
       ↓
  wrist (0번) 좌표만 추출 → deque에 저장
       ↓
  EMA 스무딩 → 노이즈 제거된 좌표
       ↓
  방향 추적 → 반전 감지 (진폭 ≥ 임계값)
       ↓                       ↓ 미달
  반전마다 deque 리셋          micro-flip 무시
  (꼭짓점 + 현재값 seed)
       ↓
  반전 2회 = 1 action
       ↓
  축 우세로 chop vs stir 판별
       ↓
  hold_counter로 10프레임 라벨 유지


[B. GameInput 변환]

  HandInput(motion="chop_motion", motion_count=1)
       ↓
  hand_inputs_to_game_input()
       ↓
  GameInput(chop=True)   ← motion_count > 0일 때만
       ↓
  merge_inputs(keyboard, gesture)  ← OR 병합


[C. 게임 Lock Mode]

  GameInput(chop=True) 수신
       ↓
  Lock 진입: _act_chop() → _lock_mode="chop", reset_motion()
       ↓
  Lock 중:  _process_lock_mode()
            ├─ 이동 차단
            ├─ 모션 게이트 (첫 neutral 대기)
            └─ chop/stir 입력 → hits/stirs 증가
       ↓
  완료:    chop_hits=4 → chop_item["chopped"]=True
       ↓
  Lock 해제: _lock_mode=None, reset_motion()


[D. 싱글/멀티 공유 구조]

  Game.update() ─────────→ _process_lock_mode()  ← 공유
                ─────────→ _apply_movement()      ← 공유
                ─────────→ _process_free_actions() ← 공유

  _process_single_input() → _process_lock_mode()  ← 공유
                          → _apply_movement()      ← 공유
                          → _process_free_actions() ← 공유
```
