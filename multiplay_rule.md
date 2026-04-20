# Multiplayer Rules — 손맛 주방

## 개요

- 네트워크 연결 **구현 완료** (TCP + UDP 로비)
- Server-Authoritative: 호스트 RPI5가 서버 겸 Player 0, 나머지가 클라이언트
- 플레이어는 각자 독립적으로 조작하며, 조리대 점유/공유 규칙으로 충돌을 방지

---

## 1. 조리대 점유 규칙

### 공통 (✅ 구현됨)

- 여러 명이 같은 조리대 위치에 있을 수 있지만, **조리대 사용은 한 명만** 가능
- **점유 시작 조건**: 해당 조리대에 재료를 내려놓는 순간 점유 선언
- 점유 중인 조리대에 다른 플레이어가 재료를 놓으려 하면 **차단** (액션 무효 + 팝업)
- **점유 해제 조건**: 조리대 위 재료/요리를 모두 집어가는 순간 자동 해제

> 구현: `Game._station_locks` (dict: station_idx → player_id)
> `_can_use_station()` / `_lock_station()` / `_unlock_station()`

### Chop 조리대

| 규칙 | 상태 | 비고 |
|------|------|------|
| 재료 놓기 → 점유 시작 | ✅ 구현됨 | `_act_chop()`에서 `_lock_station()` 호출 |
| 완성품 픽업 → 점유 해제 | ✅ 구현됨 | `_unlock_station()` 호출 |
| 다른 조리대로 이동 시 점유 즉시 해제 | ❌ 미구현 | `_station_locks` 해제 로직 없음 |
| 빈 상태에서 동시 chop → 선착순 | ✅ 구현됨 | 서버 수신 순서 기준 |

### Stove 조리대

| 규칙 | 상태 | 비고 |
|------|------|------|
| 재료 추가 — 누구나 가능 (점유 무관) | ⚠️ 불일치 | 현재 첫 재료 추가 시 lock → 이후 다른 플레이어 재료 추가 차단됨 |
| Stirring — 선착순 한 명만 가능 | ✅ 구현됨 | stir 시 `_lock_station()` |
| Stirring 완료/중단 → 점유 해제 | ✅ 구현됨 | 완성품/탄 음식 픽업 시 `_unlock_station()` |

> **⚠️ 규칙-구현 불일치**: 규칙은 "재료 추가는 누구나 가능"이지만,
> 현재 코드(`_act_pot()`)는 `pot_items`가 있을 때 `_can_use_station()` 체크를 하므로
> lock 소유자 외에는 재료 추가가 차단됨. **규칙을 따르려면 재료 추가 시 lock 체크를 제거해야 함.**

### 공통 — 동작 중 이동 잠금 (✅ 구현됨)

- Chopping 중 / Stirring 중에는 해당 플레이어의 이동 입력을 **무효 처리**
- `_lock_mode`가 `"chop"` 또는 `"stir"`이면 `move_dir = 0` 강제
- 동작이 완료되거나 중단되어야 이동 가능

### Pantry (재료 선택 UI) — 독립 운영 (✅ 구현됨)

- 각 플레이어는 **자신만의 팬트리 오버레이**를 열고 닫을 수 있음
- 다른 플레이어가 팬트리를 열어도 내 화면에는 표시되지 않음
- 하이라이트(선택 커서) 상태도 플레이어별 독립 관리

> 구현: `Game._player_overlays` (dict: pid → bool) + `Game._overlay_highlights` (dict: pid → int|None)
> 서버 측 `process_input_for_player()`에서 highlight 상태를 save/restore하여 플레이어 간 간섭 방지

---

## 2. 동기화 방식

### 현재 구현: 20Hz 풀 스테이트 브로드캐스트 (✅ 구현됨)

서버가 매 tick(1/20초)마다 `serialize_state()` → `broadcast_state()` 전송.
클라이언트는 `apply_state()`로 전체 상태를 덮어씀.

> 이벤트 기반 동기화가 아닌 **주기적 전체 스냅샷** 방식.
> LAN 환경에서 약 2-4KB/tick, 부하 없음.

### 조리대 상태 — Station.to_dict()

```yaml
station_state:
  - kind             # 조리대 종류 (trash / ing / chop / pot / submit)
  - chop_item        # 도마 위 재료 (id, chopped, chop_hits) 또는 null
  - chop_prog        # 다지기 진행도 (0.0~1.0)
  - pot_items        # 냄비 안 재료 목록
  - pot_cooking      # 조리 중 여부
  - pot_cooked       # 완성 여부
  - pot_burned       # 탄 여부
  - pot_prog         # stirring 진행도 (0.0~1.0)
  - pot_stirs        # stir 횟수
  - pot_burn         # burn 타이머
```

> **주의 — 규칙 원안의 아래 필드들은 Station 엔티티에 없음:**
> - `occupant_id` → `Game._station_locks`에서 별도 관리 (직렬화 안 됨)
> - `stir_occupant_id` → 별도 필드 없음 (`_station_locks`로 통합)
> - `station_id` → 배열 인덱스로 식별

### 플레이어 상태 — Player.to_dict()

```yaml
player_state:
  - player_id
  - name
  - x, y, vx, vy     # 위치 및 속도
  - facing            # 방향
  - holding           # 들고 있는 재료/요리 (dict 또는 null)
```

> **주의 — 규칙 원안의 아래 필드들은 Player 직렬화에 미포함:**
> - `current_slot` → 직렬화 안 됨 (x 좌표에서 추론 가능)
> - `is_chopping` / `is_stirring` → `Game._lock_modes`에서 관리 (직렬화 안 됨)
> - `action_message` → 팝업은 로컬 렌더링, 동기화 안 됨

### 점수 (✅ game_state에 포함)

점수는 별도 이벤트 메시지가 아닌 `game_state.score`로 매 tick 전송됨.

> **규칙 원안의 `score_event` 메시지 타입은 미구현.**
> 현재는 점수 변화가 전체 스냅샷에 포함되므로 기능상 문제는 없으나,
> 점수 획득 시 "누가 어떤 레시피로 +N점" 같은 피드백을 타 클라이언트에 표시하려면
> 별도 이벤트 메시지 추가가 필요함.

---

## 3. 충돌 처리 원칙 (✅ 구현됨)

- 동시 입력 충돌은 **서버 수신 순서** 기준으로 선착순 처리
- 차단된 액션은 해당 클라이언트에 즉시 **팝업 피드백** ("{이름} is using this!" 등)
- 클라이언트는 서버 상태를 정답으로 간주 (`apply_state()`로 로컬 상태 덮어씀)

---

## 4. TODO — 남은 작업

### 우선순위 높음

| # | 항목 | 설명 |
|---|------|------|
| 1 | Stove 재료 추가 lock 해제 | `_act_pot()`에서 재료 추가 시 `_can_use_station()` 체크 제거. 규칙대로 누구나 냄비에 재료를 넣을 수 있어야 함 |
| 2 | Chop 이동 시 점유 해제 | `_process_single_input()`에서 chop station 점유자가 다른 slot으로 이동하면 `_unlock_station()` 호출 |
| 3 | `_station_locks` 직렬화 | 점유 상태가 `game_state`에 포함되지 않으므로 클라이언트가 점유 정보를 모름. `serialize_state()`에 포함 필요 |

### 우선순위 보통

| # | 항목 | 설명 |
|---|------|------|
| 4 | `is_chopping`/`is_stirring` 동기화 | `_lock_modes`를 player 상태에 포함하거나, station 상태에 chopping 플레이어 id 추가 |
| 5 | 점수 이벤트 메시지 | 점수 변동 시 `score_event` 메시지를 별도 전송하여 타 클라이언트에 피드백 표시 |
| 6 | 접속 끊김 시 점유 해제 | 플레이어 연결 끊김 시 해당 플레이어의 `_station_locks` 전체 해제 |

### 우선순위 낮음

| # | 항목 | 설명 |
|---|------|------|
| 7 | Client-side prediction | 현재 full-state 덮어쓰기 방식. 입력 지연감 개선 시 추가 |
| 8 | 스테이션 확장 | 플레이어 수에 따라 chop/pot 조리대 2개로 확장 |
