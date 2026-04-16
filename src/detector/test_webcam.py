#!/usr/bin/env python3
"""
라즈베리파이 5 웹캠 제스처 테스트 스크립트

opencv-python-headless + pygame 조합으로 Qt 의존성 없이 동작한다.

실행:
    uv run python src/detector/test_webcam.py           # 기본
    uv run python src/detector/test_webcam.py --debug   # 콘솔에 수치 출력

    # SSH 접속 + 모니터 연결 시:
    DISPLAY=:0 uv run python src/detector/test_webcam.py

    # 프레임버퍼 직접 출력 (X 없이):
    SDL_VIDEODRIVER=fbcon uv run python src/detector/test_webcam.py

종료: 'q' 키 또는 창 닫기
"""

from __future__ import annotations

import pathlib
import sys
import time

import cv2
import numpy as np
import pygame

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from gesture_detector import Gesture, GestureDetector

W, H = 640, 480
DEBUG_MODE = "--debug" in sys.argv

# ── 제스처별 색상 (BGR for cv2) ───────────────────────────────────────────────
GESTURE_COLOR_BGR: dict[Gesture, tuple[int, int, int]] = {
    Gesture.IDLE:    (120, 120, 120),
    Gesture.GRAB:    (  0, 165, 255),
    Gesture.RELEASE: (  0, 220,   0),
    Gesture.CHOP:    (100,   0, 255),
    Gesture.STIR:    (  0, 200, 255),
}

HINTS = [
    "GRAB    : fist + bent arm, fist up",
    "RELEASE : both hands open, palms down",
    "CHOP    : vertical repeated motion",
    "STIR    : horizontal repeated motion",
    "v       : toggle landmark overlay",
]


# ── 화면 렌더링 ───────────────────────────────────────────────────────────────

def draw_overlay(frame: np.ndarray, gesture: Gesture, fps: float) -> None:
    h, w = frame.shape[:2]
    color = GESTURE_COLOR_BGR[gesture]

    overlay = frame.copy()
    cv2.rectangle(overlay, (8, 8), (w - 8, 75), (0, 0, 0), cv2.FILLED)
    cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)

    cv2.putText(frame, gesture.value.upper(),
                (20, 58), cv2.FONT_HERSHEY_SIMPLEX, 1.8, color, 3, cv2.LINE_AA)
    cv2.putText(frame, f"FPS: {fps:.0f}",
                (w - 140, 46), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (200, 200, 200), 2, cv2.LINE_AA)

    for i, hint in enumerate(HINTS):
        y = h - 16 - (len(HINTS) - 1 - i) * 22
        cv2.putText(frame, hint, (12, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (170, 170, 170), 1, cv2.LINE_AA)


def frame_to_surface(frame: np.ndarray) -> pygame.Surface:
    """BGR numpy 배열을 pygame Surface로 변환한다."""
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return pygame.surfarray.make_surface(np.transpose(rgb, (1, 0, 2)))


# ── 디버그 출력 ───────────────────────────────────────────────────────────────

def print_debug(dbg: dict, output: Gesture) -> None:
    """
    detector.debug_info 를 읽기 쉬운 형태로 콘솔에 출력한다.

    출력 항목:
      - 각 손의 손가락 TIP/MCP 거리 비율 (curl 판단 기준: < 1.5 = 말림)
      - curled / extended 카운트
      - y_std: 손 수평 여부 (release 판단 기준: < 0.10)
      - elbow_angle: 팔꿈치 각도 (grab 판단: < 155°)
      - thumb_ratio: 엄지 간격 비율 (release 판단: < 0.6)
      - chop_osc / stir_osc: 방향 전환 횟수 (2 이상이면 동작 감지)
      - y_amp / x_amp: 손목 운동 진폭
      - raw → output: 필터 전/후 제스처
    """
    ts = time.strftime("%H:%M:%S")
    lines = [f"[DEBUG {ts}]"]

    for side in ("R", "L"):
        h = dbg.get(side)
        if h:
            r = h["ratios"]
            lines.append(
                f"  {side}-hand  ratios idx={r['idx']} mid={r['mid']} "
                f"rng={r['rng']} pnk={r['pnk']}  "
                f"curled={h['curled']}/4  extended={h['extended']}/4  "
                f"y_std={h['y_std']}  wrist=({h['wrist_xy'][0]},{h['wrist_xy'][1]})"
            )
            angle_key = f"elbow_angle_{side}"
            above_key = f"wrist_above_elbow_{side}"
            if angle_key in dbg:
                lines.append(
                    f"  {side}-pose   elbow_angle={dbg[angle_key]}°  "
                    f"wrist_above_elbow={dbg.get(above_key)}"
                )
        else:
            lines.append(f"  {side}-hand  (not detected)")

    if dbg.get("thumb_ratio") is not None:
        lines.append(f"  thumb_ratio={dbg['thumb_ratio']}  (release: < 0.6)")

    grab_dist_str = dbg.get("grab_dist")
    lines.append(
        f"  grab_dist={grab_dist_str}(grab: <{0.20})  "
        f"wrist_speed={dbg.get('wrist_speed','?')}(grab block>{0.012})"
    )
    lines.append(
        f"  chop osc={dbg['chop_osc']}  y_amp={dbg['y_amp']}  |  "
        f"stir osc={dbg['stir_osc']}  x_amp={dbg['x_amp']}  "
        f"cooldown={dbg['cooldown']}  hold={dbg['hold_counter']}"
    )
    lines.append(f"  raw={dbg['raw']}  ->  output={output.value}")
    print("\n".join(lines))


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main() -> None:
    pygame.init()
    try:
        screen = pygame.display.set_mode((W, H))
        pygame.display.set_caption("Gesture Detector  (q: quit)")
    except pygame.error as e:
        print(f"[ERROR] 디스플레이 초기화 실패: {e}", file=sys.stderr)
        print("  모니터 연결 후 로컬 터미널에서 실행하거나:", file=sys.stderr)
        print("  SSH 접속 시:      DISPLAY=:0 python test_webcam.py", file=sys.stderr)
        print("  프레임버퍼 출력:  SDL_VIDEODRIVER=fbcon python test_webcam.py", file=sys.stderr)
        sys.exit(1)

    clock = pygame.time.Clock()

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[ERROR] 카메라를 열 수 없습니다.", file=sys.stderr)
        sys.exit(1)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, H)
    cap.set(cv2.CAP_PROP_FPS, 30)

    detector = GestureDetector()
    show_landmarks = True       # 'v' 키로 토글
    prev_gesture: Gesture | None = None
    gesture_start = time.time()
    fps_frames = 0
    fps_time   = time.time()
    fps        = 0.0
    frame_count = 0

    print("=" * 60)
    print(f" Gesture Detector Test  |  'q' to quit"
          + ("  [DEBUG MODE]" if DEBUG_MODE else ""))
    print("=" * 60)
    print(f"{'time':>8}  {'prev':>12}  ->  {'curr':>12}  {'held(s)':>8}")
    print("-" * 60)

    running = True
    try:
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_q:
                        running = False
                    elif event.key == pygame.K_v:
                        show_landmarks = not show_landmarks
                        print(f"[Landmarks] {'ON' if show_landmarks else 'OFF'}")

            ret, frame = cap.read()
            if not ret:
                continue

            frame = cv2.flip(frame, 1)
            gesture = detector.detect(frame)

            # 랜드마크 시각화 (detect() 이후에 그려야 last_results 가 최신)
            if show_landmarks:
                detector.draw_landmarks(frame)
            frame_count += 1

            fps_frames += 1
            now = time.time()
            if now - fps_time >= 1.0:
                fps = fps_frames / (now - fps_time)
                fps_frames = 0
                fps_time = now

            # 디버그 출력: 15 프레임마다
            if DEBUG_MODE and frame_count % 15 == 0:
                print_debug(detector.debug_info, gesture)

            draw_overlay(frame, gesture, fps)
            screen.blit(frame_to_surface(frame), (0, 0))
            pygame.display.flip()
            clock.tick(60)

            if gesture != prev_gesture:
                duration = now - gesture_start
                prev_str = prev_gesture.value if prev_gesture else "start"
                print(
                    f"{time.strftime('%H:%M:%S'):>8}  "
                    f"{prev_str:>12}  ->  {gesture.value:>12}  "
                    f"{duration:>7.1f}s"
                )
                prev_gesture  = gesture
                gesture_start = now

    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        pygame.quit()
        detector.close()
        print("\n종료.")


if __name__ == "__main__":
    main()
