ai_detector.md 파일을 바탕으로 기능을 구현할 수 있는 방법을 생각 및 정리하고 구현해라.
- 동작하는 원리를 상세히 알려줘야 한다.

각 방법을 라즈베리파이 5에서 테스트해볼 수 있는 파이썬 스크립드도 만들어줘
필요한 패키지는 uv로 설치해줘

---

## 구현 결과

- `gesture_detector.py` : 핵심 감지기 클래스 (MediaPipe Holistic 기반)
- `test_webcam.py`       : 라즈베리파이 5 웹캠 테스트 스크립트

### 패키지 설치

```bash
uv sync
```

> **주의**: `opencv-python` 대신 `opencv-python-headless`를 사용한다.
> Qt XCB 플러그인 의존성이 없어 Raspberry Pi 5에서 디스플레이 오류 없이 동작한다.
> 이미지 처리 기능(cv2.putText, cv2.cvtColor 등)은 그대로 사용 가능하고,
> 화면 출력은 pygame으로 대체한다.

### 실행 방법

```bash
# 모니터 연결 + 로컬 터미널 (가장 기본)
uv run python src/detector/test_webcam.py

# SSH 접속 + 모니터가 라즈베리파이에 연결된 경우
DISPLAY=:0 uv run python src/detector/test_webcam.py

# SSH 접속 + X forwarding (클라이언트 PC에 창 표시)
# 접속: ssh -X pi@<ip>
uv run python src/detector/test_webcam.py

# X 없이 프레임버퍼 직접 출력 (HDMI 모니터 연결 필수)
SDL_VIDEODRIVER=fbcon uv run python src/detector/test_webcam.py
```

### Qt XCB 오류가 계속 발생하는 경우

```
qt.qpa.xcb: could not connect to display
qt.qpa.plugin: Could not load the Qt platform plugin "xcb"
```

위 오류는 `opencv-python` (Qt 포함) 설치 시 발생한다.
`pyproject.toml`에서 `opencv-python-headless`로 교체 후 `uv sync`로 해결된다.