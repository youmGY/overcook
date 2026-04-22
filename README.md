# Overcook

손 제스처로 조작하는 멀티플레이어 요리 게임. Python + Pygame으로 제작, MediaPipe와 커스텀 ONNX MLP 모델로 실시간 제스처 인식.

## 주요 기능

- **제스처 조작**: 웹캠으로 손 제스처를 인식해 플레이 (MediaPipe + 8-class MLP)
- **LAN 멀티플레이**: 최대 4인 동시 플레이 (서버-권위 구조, TCP/UDP)
- **요리 시스템**: 재료 손질(자르기/볶기) → 완성 → 제출
- **주문 관리**: 45초 타이머 주문, 실패/오제출 시 감점
- **오디오**: BGM + 효과음 완비

## 요구사항

- Python 3.9+
- `pygame`, `mediapipe`, `opencv-python`, `onnxruntime`

## 설치

```bash
git clone <repo-url>
cd overcook
pip install -r requirements.txt
```

## 실행

```bash
# 멀티플레이 (기본, LAN 로비)
python main.py --name "YourName"

# 멀티플레이 + 제스처 제어
python main.py --name "YourName" --gesture

# 솔로 + 키보드
python main.py --solo

# 솔로 + 제스처 제어
python main.py --solo --gesture
```

## 조작법

### 키보드

| 동작 | 키 |
|------|----|
| 스테이션 이동 | `1` ~ `5` |
| 상호작용 / 재료 선택 확인 | `Space` / `E` |
| 자르기 | `Z` (반복) |
| 볶기 | `X` (반복) |
| 일시정지 | `Escape` |

### 제스처

| 제스처 | 일반 상태 | 재료 선택 오버레이 |
|--------|-----------|-------------------|
| 손가락 1~5개 펴기 | 스테이션 1~5로 이동 | 재료 1~5 하이라이트 |
| 엄지 위 (Thumbs Up) | 스테이션 상호작용 | 하이라이트 재료 확인 |
| 자르기 동작 (Chop) | 자르기 카운트 증가 | — |
| 볶기 동작 (Stir) | 볶기 카운트 증가 | — |

**스테이션 배치**: `1`=쓰레기통 · `2`=재료 창고 · `3`=도마 · `4`=냄비(스토브) · `5`=제출대

## 게임 규칙

| 항목 | 값 |
|------|----|
| 게임 시간 | 120초 |
| 주문 타이머 | 45초 |
| 자르기 횟수 (완성) | 4회 |
| 볶기 횟수 (완성) | 5회 |
| 타는 시간 | 완성 후 7초 |

### 레시피

| 요리 | 재료 | 과정 |
|------|------|------|
| 토마토 수프 | 토마토 | 자르기 → 끓이기 |
| 볶음밥 | 쌀, 당근 | 당근 자르기 → 볶기 |
| 버섯 볶음 | 버섯 | 자르기 → 볶기 |
| 채소 카레 | 양파, 당근 | 자르기 → 끓이기 |
| 당근 수프 | 당근 | 자르기 → 끓이기 |

## 아키텍처

```
main.py                         # 진입점
overcook/
├── runloop.py                  # CLI 파싱, 솔로/멀티 게임 루프
├── game.py                     # 게임 상태 머신 + 핵심 로직
├── drawing.py                  # 렌더링 (GameDrawMixin)
├── entities.py                 # Station, Player, Order
├── input.py                    # GameInput, 제스처→입력 변환
├── constants.py                # 게임 상수, 재료, 레시피
├── engine.py                   # Pygame 초기화, 폰트/이미지 유틸
├── audio.py                    # AudioManager (SFX + BGM)
├── network.py                  # LAN 멀티플레이 (GameServer, GameClient)
├── utils.py                    # 드로잉 헬퍼
├── ui/
│   ├── game_ui.py              # 인게임 HUD, 오버레이, 설정
│   └── lobby_ui.py             # 멀티플레이 로비 UI
└── recognition/
    ├── interface.py            # RecognitionPipeline
    ├── gesture.py              # GestureClassifierDNN (8-class ONNX MLP)
    ├── hand_tracker.py         # MediaPipe 손 추적
    ├── motion.py               # Chop / Stir 동작 감지
    ├── camera.py               # OpenCV 웹캠 캡처
    ├── hand_split.py           # 좌우 손 분리
    ├── coords.py               # 좌표 정규화
    └── models/
        └── gesture_mlp_60f_8cls.onnx  # 학습된 제스처 모델
assets/
├── images/                     # 스프라이트, 배경
└── audio/                      # BGM, SFX
train/                          # 학습 및 데이터 수집 스크립트
tests/                          # 단위 테스트
docs/                           # 설계 문서
```

### 제스처 인식 파이프라인

```
웹캠 프레임
  → MediaPipe (21 랜드마크)
  → 회전/스케일 정규화 (60차원 특징벡터)
  → ONNX MLP (8-class: finger_1~5, thumbs_up, fist, finger_3_another)
  → GestureDebouncer (연속 N프레임 확정)
  → motion.py (chop/stir 스트로크 감지)
  → GameInput
```

### 멀티플레이 구조

- 서버-권위(Server-Authoritative): 호스트가 `server_tick()` 실행, 전체 게임 상태를 40Hz로 브로드캐스트
- LAN 자동 탐색: UDP 5556 포트 브로드캐스트
- 게임 통신: TCP 5555 포트
- 플레이어 색상: 보라·빨강·초록·파랑

## 라이선스

MIT — [LICENSE](LICENSE) 참고
