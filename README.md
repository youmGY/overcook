# 🍳 Overcook

**오버쿡 스타일 요리 게임** — Pygame 기반, MediaPipe 손 제스처 인식 지원

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)

## 게임 소개

주어진 시간 안에 주문에 맞는 요리를 완성하세요!
재료를 선택하고, 다지고(chop), 끓이고(stir), 접시에 담아 제출하면 점수를 획득합니다.
키보드 또는 **손 제스처**(웹캠)로 플레이할 수 있습니다.

## 설치

```bash
# 의존성 설치
pip install -r requirements.txt

# 또는 uv 사용
uv sync
```

## 실행

```bash
# 키보드 모드 (기본)
python main.py

# 제스처 인식 모드 (웹캠 필요)
python main.py --gesture

# 패키지로 실행
python -m overcook
```

## 조작법

### 키보드

| 키 | 동작 |
|---|---|
| `←` `→` / `A` `D` | 캐릭터 이동 |
| `1`–`5` | 스테이션 슬롯 직접 이동 |
| `Z` / `Space` | 확인 (재료 놓기 / 상호작용) |
| `C` | 다지기 (Chop) |
| `V` | 젓기 (Stir) |
| `R` | 레시피 보기 |
| `ESC` | 일시정지 / 메뉴 닫기 |
| `Enter` | 게임 시작 / 재시작 |

### 제스처 (웹캠)

| 제스처 | 동작 |
|---|---|
| 손 좌우 이동 | 캐릭터 이동 |
| 검지 손가락 가리키기 | 슬롯 선택 |
| ✊ 주먹 | 확인 |
| ✋ → ✊ 빠른 반복 | 다지기 (Chop) |
| 🤚 손목 흔들기 | 젓기 (Stir) |

## 프로젝트 구조

```
overcook/
├── main.py                  # 진입점 (argparse + 게임 루프)
├── pyproject.toml            # 프로젝트 설정
├── requirements.txt          # 의존성 목록
├── assets/                   # 이미지 리소스
├── sounds/                   # 사운드 리소스
│
├── overcook/                 # 핵심 패키지
│   ├── __init__.py
│   ├── __main__.py           # python -m overcook 지원
│   ├── constants.py          # 색상, 재료, 레시피, 타이밍 상수
│   ├── engine.py             # Pygame 초기화, 폰트, 이미지 캐시
│   ├── utils.py              # 그리기 유틸리티 (rr, txt, bar)
│   ├── entities.py           # Station, Player, Order 엔티티
│   ├── ui.py                 # Popup, Btn, RecipeOverlay UI 컴포넌트
│   ├── input.py              # GameInput 데이터클래스, 입력 병합 로직
│   ├── game.py               # Game 클래스 (상태 관리, 게임 로직)
│   │
│   └── recognition/          # 제스처 인식 모듈
│       ├── __init__.py       # 공개 API (CameraConfig, RecognitionPipeline, …)
│       ├── camera.py         # 카메라 캡처 (ThreadedCamera)
│       ├── gesture.py        # ONNX 기반 제스처 분류
│       ├── hand_tracker.py   # MediaPipe 손 랜드마크 추적
│       ├── interface.py      # 파이프라인 오케스트레이터
│       ├── motion.py         # 모션 감지 (chop, stir)
│       ├── smoothing.py      # EMA 좌표 스무딩
│       ├── splitter.py       # 좌/우 손 분리 추적
│       └── models/           # ML 모델 파일
│           ├── gesture_mlp.onnx
│           ├── hand_landmarker.task
│           └── pose_landmarker_lite.task
│
├── examples/                 # 데모 스크립트 (런타임 비포함)
│   ├── demo_hand_tracking.py # 손 추적 데모
│   ├── demo_full_pipeline.py # 전체 파이프라인 디버그 데모
│   └── pose_tracker.py       # 포즈 추적 (데모 전용)
│
├── tests/                    # 유닛 테스트
│   └── test_game.py
│
└── tools/                    # 개발 도구
    ├── assets.py             # 에셋 정의
    ├── gen_assets.py         # 에셋 생성 스크립트
    └── game_patch_guide.py   # 패치 가이드
```

## 아키텍처

**Clean Code & SOLID 원칙** 적용:

- **SRP**: 각 모듈이 단일 책임 담당 (입력, 엔티티, UI, 게임 로직 분리)
- **OCP**: 새 레시피/재료는 `constants.py`만 수정하면 추가 가능
- **DIP**: `Game` 클래스는 `GameInput` 인터페이스를 통해 입력 소스에 비의존적

## 테스트

```bash
python -m unittest discover -s tests
```

## 라이선스

MIT