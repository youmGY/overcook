# 🍳 Overcook Multiplayer — 개발 문서

## 실행 명령어

### 싱글플레이어 (Solo)

```bash
# 기본 (키보드 + 마우스)
python game.py

# 제스처 입력 (카메라 + 손 인식)
python game.py --gesture

# 테스트 모드 (카메라 UI 없음)
python game.py -test

# 카메라 피드 표시 (제스처 없이)
python game.py -active
```

### 멀티플레이어 (LAN)

```bash
# 기본 (키보드 + 마우스)
python game.py --multiplayer --name "이름"

# 제스처 입력 포함
python game.py --multiplayer --name "이름" --gesture
```

### 전체 옵션 목록

| 옵션 | 설명 |
|------|------|
| `--multiplayer` | 멀티플레이어 모드 (LAN 로비 진입) |
| `--name "이름"` | 멀티플레이어에서 사용할 플레이어 이름 |
| `--gesture` | 카메라 + MediaPipe 제스처 인식 입력 활성화 |
| `--flip` | 카메라 좌우 반전 (기본값: True) |
| `-active` | 카메라 피드 UI 표시 |
| `-test` | 테스트 모드 (카메라 UI 숨김) |

---

## 개요

기존 싱글플레이어 Overcook 요리 게임을 **4인 Co-op LAN 멀티플레이어**로 확장.  
**Server-Authoritative 모델**을 채택하여 호스트 RPI5가 서버 겸 플레이어 역할, 나머지 RPI5가 클라이언트로 접속.

---

## 아키텍처

```
┌─────────────────────────────────────────────────────┐
│            Host RPI5 (Server + Player 0)            │
│  ┌──────────┐  ┌────────────┐  ┌────────────────┐   │
│  │ 게임 로직 │  │ TCP Server │  │ UDP Announcer  │   │
│  │ (Game     │←→│ (port 5555)│  │ (port 5556)    │   │
│  │  class)   │  │            │  │ 1초마다 방 공고│   │
│  └──────────┘  └──┬──┬──┬──┘  └────────────────┘   │
│                   │  │  │                           │
└───────────────────┼──┼──┼───────────────────────────┘
                    │  │  │  TCP 연결
          ┌─────────┘  │  └──────────┐
          ▼            ▼             ▼
   ┌────────────┐ ┌────────────┐ ┌────────────┐
   │ Client RPI │ │ Client RPI │ │ Client RPI │
   │ Player 1   │ │ Player 2   │ │ Player 3   │
   └────────────┘ └────────────┘ └────────────┘
```

### 왜 Server-Authoritative인가

- 모든 플레이어가 **같은 5개 스테이션**을 공유 — 상태 충돌 방지를 위해 중앙 관리 필요
- Player 1이 chop한 음식을 Player 2가 pick up하는 등 **상태 공유** 필수
- P2P는 동기화 복잡도 높고 치팅에 취약

---

## 변경된 파일 요약

| 파일 | 유형 | 변경 내용 |
|------|------|-----------|
| `engine.py` | 수정 | 전체화면(`FULLSCREEN`) 디폴트로 변경 |
| `constants.py` | 수정 | 네트워크 상수, 플레이어 색상 프리셋 추가 |
| `entities.py` | 수정 | `Player`에 `player_id/name/color` 추가, 직렬화(`to_dict`/`apply_dict`) 추가, 이름 라벨 렌더링 |
| `game.py` | 수정 | `GameInput` 직렬화, `Game` 클래스 멀티플레이어 확장, `main()` 분리 |
| `network.py` | **신규** | `GameServer`, `GameClient`, `RoomAnnouncer`, `RoomScanner` |
| `lobby_ui.py` | **신규** | 로비 UI (방 만들기/찾기/대기실) |

---

## Threading 구조

### 서버 측 (호스트) — 총 3종류 스레드

```
Main Thread (pygame 렌더링 + 로컬 입력)
    │
    ├── [daemon] Accept Thread (_accept_loop)
    │       소켓 accept() 대기, 새 클라이언트 연결 시 _ClientSlot 생성
    │       → 클라이언트마다 Recv Thread 추가 생성
    │
    ├── [daemon] Recv Thread × N개 (_recv_loop, 클라이언트당 1개)
    │       각 클라이언트의 TCP 소켓에서 JSON 메시지 수신
    │       "ready" → slot.ready 갱신
    │       "player_input" → slot.input_queue에 push (maxsize=8)
    │
    └── [daemon] RoomAnnouncer Thread (_run)
            UDP 브로드캐스트로 1초마다 방 정보 송출
            게임 시작 시 stop()으로 중단
```

**동기화 방식**:
- `self._lock` (threading.Lock): `_clients` 리스트 접근 보호 (accept/recv/broadcast 간 동기화)
- `slot.input_queue` (queue.Queue, maxsize=8): 각 클라이언트의 입력을 락-프리로 전달
- `self._stop` (threading.Event): graceful shutdown 시그널

### 클라이언트 측 — 1종류 스레드

```
Main Thread (pygame 렌더링 + 로컬 입력 + 서버로 입력 전송)
    │
    └── [daemon] Recv Thread (_recv_loop)
            서버에서 오는 JSON 메시지 수신
            "lobby_update"  → lobby_queue (최신 것만 유지)
            "game_state"    → state_queue (최신 것만 유지, 이전 것 drop)
            "game_start"    → event_queue
            "game_over"     → event_queue
```

**동기화 방식**:
- `lobby_queue` (Queue, maxsize=16): 로비 상태 업데이트
- `state_queue` (Queue, maxsize=4): 게임 상태 스냅샷 — **최신 것만 유지** (오래된 것 자동 폐기)
- `event_queue` (Queue, maxsize=16): 이벤트 메시지 (game_start, game_over)

### 방 탐색 — 1종류 스레드

```
[daemon] RoomScanner Thread (_run)
    UDP 소켓(port 5556)에서 room_announce 메시지 수신
    self._rooms dict에 저장 (self._lock으로 보호)
    3.5초 타임아웃된 방은 자동 제거 (evict)
```

---

## 네트워크 프로토콜

### 전송 형식
Newline-delimited JSON over TCP (`\n`으로 구분)

```python
# 송신
data = (json.dumps(payload) + "\n").encode("utf-8")
sock.sendall(data)

# 수신
line = reader.readline()  # makefile("rb")로 생성된 buffered reader
msg = json.loads(line)
```

### 로비 단계 메시지

| 메시지 | 방향 | 필드 | 설명 |
|--------|------|------|------|
| `join` | 클라→서버 | `name` | 방 입장 요청 |
| `join_ack` | 서버→클라 | `ok`, `player_id`, `name` | 입장 승인/거절 (`full`, `in_progress`) |
| `ready` | 클라→서버 | `ready` | Ready 상태 전환 |
| `lobby_update` | 서버→클라 | `players[]`, `all_ready`, `count` | 로비 상태 브로드캐스트 |
| `game_start` | 서버→클라 | — | 게임 시작 신호 |

### 게임 플레이 메시지

| 메시지 | 방향 | 필드 | 설명 |
|--------|------|------|------|
| `player_input` | 클라→서버 | `input{}` | 플레이어 입력 (GameInput.to_dict()) |
| `game_state` | 서버→클라 | `state{}` | 전체 게임 상태 스냅샷 (20 tick/sec) |
| `game_over` | 서버→클라 | `score` | 게임 종료 + 최종 점수 |

### UDP 방 탐색 메시지

| 메시지 | 방향 | 포트 | 필드 |
|--------|------|------|------|
| `room_announce` | 호스트→브로드캐스트 | 5556 | `name`, `host`, `port`, `max_players` |

---

## 게임 상태 직렬화

### serialize_state() — 서버가 20 tick/sec으로 브로드캐스트

```python
{
    "score": 150,
    "timer": 183.5,
    "elapsed": 56.5,
    "next_order": 71.5,
    "state": "play",
    "players": {
        "0": {"x": 100, "y": 200, "vx": 0, "vy": 0, "facing": 1,
              "holding": {"id": "tomato_c", "label": "Chopped Tomato", "chopped": true},
              "player_id": 0, "name": "Host"},
        "1": {"x": 300, "y": 200, ...}
    },
    "stations": [
        {"kind": "trash", "x": 20, "y": 380, "chop_item": null, ...},
        {"kind": "ing", ...},
        {"kind": "chop", "chop_item": {"id": "carrot", ...}, "chop_hits": 2, ...},
        {"kind": "pot", "pot_items": [...], "pot_cooking": true, ...},
        {"kind": "submit", ...}
    ],
    "orders": [
        {"id": 1, "recipe_name": "Tomato Soup", "t": 42.3, "status": "active"},
        {"id": 3, "recipe_name": "Fried Rice", "t": 51.0, "status": "active"}
    ]
}
```

**크기**: 약 2-4KB/tick (JSON). LAN 환경에서 부하 없음.

### apply_state() — 클라이언트가 수신 후 적용

1. `self.score`, `self.timer` 등 스칼라 값 갱신
2. `players` dict: 기존 Player 객체에 `apply_dict()`, 새 플레이어면 생성, 사라진 플레이어면 삭제
3. `stations`: 인덱스 기준 `apply_dict()` — 스테이션 구조(5개, 위치 고정)는 양쪽 동일
4. `orders`: ID 기준 매칭, 기존 Order는 `apply_dict()`, 새 Order는 Recipe 이름으로 생성
5. `state` → "over"이면 게임 종료 상태 전환

---

## 엔티티 변경 사항

### Player 클래스

```python
# 기존
class Player:
    def __init__(self, x, y):

# 변경 후
class Player:
    def __init__(self, x, y, player_id: int = 0, name: str = "Player 1"):
        self.player_id = player_id
        self.name = name
        self._color_idx = player_id % len(PLAYER_COLORS)
```

- `player_id`: 0(호스트), 1~3(클라이언트) — 색상 인덱스로도 사용
- `name`: 로비에서 설정한 플레이어 이름
- `_pc(key)`: `PLAYER_COLORS[_color_idx]`에서 body/dark/hat 색상 조회
- `draw(surf, is_local=True)`: 기존 하드코딩된 `C["char_body"]` 등을 `self._pc("body")`로 교체. 머리 위에 이름 라벨 표시. `is_local=True`이면 이름 아래 밑줄(내 캐릭터 표시)

### 4가지 플레이어 색상

```python
PLAYER_COLORS = [
    {"body": ( 83,  65, 183), "dark": ( 57,  40, 137), "hat": ( 38,  33, 105), "name": "Purple"},  # P0
    {"body": (183,  85,  65), "dark": (137,  57,  40), "hat": (105,  38,  33), "name": "Red"},     # P1
    {"body": ( 65, 183,  85), "dark": ( 40, 137,  57), "hat": ( 33, 105,  38), "name": "Green"},   # P2
    {"body": ( 65, 135, 183), "dark": ( 40,  97, 137), "hat": ( 33,  78, 105), "name": "Blue"},    # P3
]
```

### Station / Order 직렬화

`to_dict()`: 현재 상태를 dict로 반환 (chop_item, pot_items, 진행도 등 포함)  
`apply_dict(d)`: dict에서 상태 복원 (클라이언트 쪽에서 서버 상태 적용)

---

## Game 클래스 멀티플레이어 확장

### 새로 추가된 필드

```python
class Game:
    def __init__(self, ..., multiplayer=False, is_server=False,
                 local_player_id=0, player_name="Player 1"):
        self.multiplayer = multiplayer       # 멀티플레이어 모드 여부
        self.is_server = is_server           # 서버(호스트)인지 여부
        self.local_player_id = local_player_id  # 이 클라이언트가 조종하는 플레이어 ID
        self.players: Dict[int, Player] = {} # 모든 플레이어 (pid → Player)
        self._mp_player_names: Dict[int, str] = {}  # 로비에서 수집한 이름 목록
        self._lock_modes: Dict[int, tuple] = {}  # pid → (mode, station_idx) 플레이어별 잠금 상태
```

### 핵심 메서드

#### `reset()` — 멀티플레이어 경로 추가

```python
if self.multiplayer:
    # _mp_player_names에서 플레이어 수만큼 생성, 균등 간격 배치
    for pid, name in sorted(self._mp_player_names.items()):
        self.players[pid] = Player(px, gy - PH, player_id=pid, name=name)
    self.player = self.players[self.local_player_id]
else:
    # 기존 싱글플레이어 동작 유지
    self.players = {0: Player(gw // 2 - 15, gy - 50, player_id=0, name=...)}
    self.player = self.players[0]
```

#### `process_input_for_player(pid, gi, dt)` — 서버 전용

서버가 각 플레이어의 입력을 처리할 때 사용.  
`self.player`를 해당 pid의 Player로 임시 교체 → `_process_single_input()` 호출 → 원래 player로 복원.

```python
def process_input_for_player(self, pid, gi, dt):
    saved = self.player
    self.player = self.players[pid]
    # _lock_modes에서 해당 플레이어의 잠금 상태 복원
    self._process_single_input(gi, dt)
    # 잠금 상태 저장
    self.player = saved
```

**왜 이렇게 했는가**: 기존 `_act_chop()`, `_act_pot()` 등이 모두 `self.player`를 참조하므로, 이 메서드들을 수정하지 않고 `self.player` 스왑으로 재사용.

#### `server_tick(dt, all_inputs)` — 서버의 매 틱 처리

```
1. all_inputs의 각 플레이어 입력을 process_input_for_player()로 처리
2. 스테이션 상태 업데이트 (chop 진행, pot 쿠킹/번, 등)
3. 주문(Order) 타이머 업데이트
4. 새 주문 스폰
5. 게임 타이머 감소 → 0이면 "over"
6. 팝업 업데이트
```

#### `serialize_state()` / `apply_state()` — 상태 동기화

- `serialize_state()`: score, timer, players, stations, orders → dict
- `apply_state()`: dict로부터 모든 엔티티 상태 갱신 (클라이언트용)

---

## main() 분리 구조

```python
def main():
    # argparse: 기존 옵션 + --multiplayer, --name 추가
    if args.multiplayer:
        _main_multiplayer(ui_mode, args)
    else:
        _main_solo(ui_mode, args)  # 기존 싱글플레이어 루프 (변경 없음)
```

### _main_multiplayer() — 멀티플레이어 게임 루프

상태 머신 기반:

```
lobby_menu → lobby_create (호스트) → playing_host
           → lobby_join (스캔) → lobby_wait (접속) → playing_client
```

#### 상태별 동작

| 상태 | 동작 |
|------|------|
| `lobby_menu` | Create Room / Join Room / Solo 버튼 |
| `lobby_create` | GameServer 시작, UDP 브로드캐스트, Ready/Start 버튼 |
| `lobby_join` | RoomScanner로 방 목록 표시, 클릭하여 선택, Connect |
| `lobby_wait` | GameClient 연결됨, lobby_queue에서 플레이어 목록 수신, Ready 전송 |
| `playing_host` | 호스트 입력 수집 → server.collect_inputs() + 호스트 입력 → server_tick() → broadcast_state() |
| `playing_client` | 로컬 입력 → client.send_input() → client.state_queue에서 상태 수신 → apply_state() |

#### 서버 틱 누산기 (playing_host)

```python
server_tick_interval = 1.0 / NET_TICK_RATE  # 1/20 = 0.05초
server_tick_accum += dt

while server_tick_accum >= server_tick_interval:
    game.server_tick(server_tick_interval, net_inputs)
    server.broadcast_state(game.serialize_state())
    server_tick_accum -= server_tick_interval
```

- 렌더링은 60 FPS, 네트워크 상태 전송은 20 tick/sec
- 렌더링 FPS에 독립적인 고정 시간 간격 로직 처리

---

## GameInput 직렬화

```python
@dataclasses.dataclass
class GameInput:
    def to_dict(self) -> dict:
        return {
            "move_to_slot": self.move_to_slot,
            "chop": self.chop, "stir": self.stir,
            "put_down": self.put_down, "confirm": self.confirm,
            "move_dir": self.move_dir, "action": self.action,
            "overlay_select": self.overlay_select,
            "overlay_confirm": self.overlay_confirm,
        }
    
    @classmethod
    def from_dict(cls, d: dict) -> "GameInput":
        return cls(move_to_slot=d.get("move_to_slot"), ...)
```

`station_click`과 `overlay_click`은 로컬 좌표이므로 네트워크로 전송하지 않음.  
대신 `move_to_slot` (1~5 스테이션 슬롯)으로 추상화하여 전송.

---

## engine.py 변경

```python
# 기존: 1024×600 윈도우 모드
screen = pygame.display.set_mode((W, H), pygame.RESIZABLE)

# 변경: 전체화면 디폴트
_info = pygame.display.Info()
screen = pygame.display.set_mode((_info.current_w, _info.current_h), pygame.FULLSCREEN)
```

---

## 실행 방법

```bash
# 싱글플레이어 (기존과 동일)
python game.py
python game.py --gesture

# 멀티플레이어
python game.py --multiplayer --name "나의이름"
```

### 멀티플레이어 흐름

1. **호스트**: `--multiplayer` → Create Room → Ready → 다른 플레이어 접속 대기 → Start
2. **클라이언트**: `--multiplayer` → Join Room → 방 선택 → Connect → Ready → 호스트가 Start하면 자동 시작
3. 모든 플레이어가 같은 5개 스테이션 공유, 서로 다른 색상으로 구분

---

## 제약사항 및 향후 개선

| 항목 | 현재 | 향후 |
|------|------|------|
| 최대 인원 | 4명 | 상수 변경으로 확장 가능 |
| 지연 보상 | 없음 (full state snapshot) | Client-side prediction 추가 가능 |
| 스테이션 수 | 5개 고정 공유 | 플레이어 수에 따라 chop/pot 2개로 확장 가능 |
| 연결 끊김 | 해당 플레이어 제거, 나머지 계속 | 재접속 기능 추가 가능 |
| 제스처 입력 | 각 RPI5에서 로컬 처리 후 GameInput으로 전송 | 변경 불필요 |
