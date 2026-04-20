# 제스처 인식 → 게임 통합 핸드오프 문서

> 작성일: 2025-04-17

## 1. 실행 방법

```bash
# 제스처 모드 (카메라 + 손 인식 + 키보드/마우스 동시 사용 가능)
DISPLAY=:0 python game.py --gesture

# 기존 모드 (키보드/마우스만, 변경 없음)
DISPLAY=:0 python game.py
```

## 2. 변경 파일 목록

| 파일 | 설명 |
|------|------|
| `game.py` | 제스처 통합 (브릿지 함수, 파이프라인 연결, 메인루프) |
| `ui.py` | `IngredientOverlay`에 하이라이트/확정 2단계 추가 |

## 3. 구조 요약

```
[카메라] → RecognitionPipeline.step()
         → List[HandInput]  (left, right 각 1개)
         → hand_inputs_to_game_input()   ← 변환 함수 (game.py)
         → GameInput
         → merge_inputs(keyboard_gi, gesture_gi)  ← 키보드 입력과 OR 병합
         → game.update(dt, gi, ...)
```

- **카메라 공유**: `--gesture` 모드에서는 `RecognitionPipeline`이 카메라를 소유하고, 게임 UI의 카메라 패널에 `pipeline.last_frame`을 전달하여 이중 캡처 방지.

## 4. 제스처 → 게임 액션 매핑표

| 제스처/모션 | 트리거 조건 | 게임 액션 |
|------------|-----------|----------|
| `finger_1~5` | `confirmed` | **[메인]** `move_to_slot` → 해당 스테이션 이동 |
| | | **[오버레이]** `overlay_select` → 재료 하이라이트 |
| `thumbs_up` | `confirmed` | **[메인]** `confirm` → 스테이션별 상호작용 |
| | | - Pantry: 진입 (빈 손일 때) |
| | | - Chop: 재료 내려놓기 (손에 재료) |
| | | - Stove: 재료 내려놓기 (chopped만) |
| | | - Trash: 버리기 |
| | | - Submit: 제출 |
| | | **[오버레이]** `overlay_confirm` → 재료 확정 |
| `chop_motion` | `motion_count > 0` | `chop` → `chop_hits += 1` (N회 완료 시 다짐) |
| `stir_motion` | `motion_count > 0` | `stir` → `pot_stirs += 1` (N회 완료 시 요리) |

> **주의**: `chop_motion`/`stir_motion`은 `motion_count > 0`일 때만 트리거됩니다. 매 프레임이 아니라 실제 왕복 1회 완료 시에만 카운트가 올라갑니다.

## 5. 핵심 데이터 구조

### HandInput (`src/recognition/interface.py`)

| 필드 | 타입 | 설명 |
|------|------|------|
| `hand_id` | `str` | `"left"` / `"right"` |
| `position` | `(float, float)` | 정규화 좌표 0~1 |
| `gesture` | `str` | `finger_1~5` / `thumbs_up` / `fist` / `unknown` |
| `finger_count` | `int` | 0~5 |
| `target_slot` | `int \| None` | `finger_N`일 때 1~5, 아니면 None |
| `gesture_confirmed` | `bool` | 디바운스 확정된 프레임에서만 True |
| `motion` | `str \| None` | `chop_motion` / `stir_motion` / `thumbs_up` / None |
| `motion_confidence` | `float` | 0.0~1.0 |
| `motion_count` | `int` | 해당 프레임에 완료된 스트로크 수 (보통 0 or 1) |
| `stale` | `bool` | 손이 최근에 감지되지 않으면 True |

### GameInput (`game.py`)

| 필드 | 타입 | 설명 |
|------|------|------|
| `move_to_slot` | `int \| None` | 1~5 (스테이션 슬롯) |
| `station_click` | `tuple \| None` | 마우스 클릭 좌표 |
| `chop` | `bool` | 자르기 액션 |
| `stir` | `bool` | 젓기 액션 |
| `put_down` | `bool` | 내려놓기 |
| `confirm` | `bool` | 확인/상호작용 |
| `move_dir` | `int` | -1 / 0 / +1 |
| `action` | `bool` | confirm 별칭 |
| `overlay_click` | `tuple \| None` | 마우스 오버레이 클릭 |
| `overlay_select` | `int \| None` | 제스처 오버레이 선택 (1-based) |
| `overlay_confirm` | `bool` | 제스처 오버레이 확정 |

## 6. 스테이션 슬롯 매핑

| 슬롯 | 스테이션 |
|------|---------|
| 1 | Trash |
| 2 | Pantry (ing) |
| 3 | Chop |
| 4 | Stove (pot) |
| 5 | Submit |

## 7. 오버레이 재료 선택 흐름 (제스처)

1. Pantry 위치에서 `thumbs_up` → 오버레이 열림 (빈 손일 때)
2. `finger_1~5` → 해당 재료 카드 하이라이트 (시각적 강조)
3. `thumbs_up` → 하이라이트된 재료 확정 → 손에 들고 오버레이 닫힘
- 하이라이트 없이 `thumbs_up` → 오버레이 닫힘 (취소)
- 마우스 클릭으로도 기존처럼 즉시 선택 가능

## 8. 디버깅 / 테스트

```bash
# 게임 로그 확인
tail -f game.log

# 테스트 실행
./.venv/bin/python -m pytest test_game.py -x -q
```
