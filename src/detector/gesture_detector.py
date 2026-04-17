"""
손 제스처 감지기 (MediaPipe Hands 기반)

동작 원리
=========
1. **MediaPipe Hands**: 손 관절(21개) 좌표를 추출한다.
   - 좌표계: (x, y, z) 모두 0~1 정규화. y축은 화면 아래 방향이 양수

2. **동적 제스처 (chop, stir)**: 슬라이딩 윈도우 버퍼의 방향 전환 횟수로 판정
   - chop: y 좌표 버퍼에서 상하 반복 운동 감지
   - stir: x 좌표 버퍼에서 좌우 반복 운동 감지
   - 이동평균으로 손떨림 노이즈 제거 후 최소 진폭 이상의 방향 전환을 카운트

3. **최근 프레임 진폭 게이트**: 버퍼 전체가 아닌 최근 N프레임 진폭으로 판정
   - 이전 제스처 잔류(chop 히스토리가 stir 감지를 방해하는 문제) 방지

4. **정지 감지**: 손이 STILL_RESET_FRAMES 연속 정지 시 버퍼 초기화
   - chop/stir 종료 후에도 버퍼 잔류로 계속 감지되는 오작동 방지
"""

from __future__ import annotations

import collections
import math
from enum import Enum
from typing import Optional

import mediapipe as mp
import numpy as np


# ── MediaPipe 손 랜드마크 인덱스 (21개) ─────────────────────────────────────
WRIST = 0
THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP = 1, 2, 3, 4
INDEX_MCP,  INDEX_PIP,  INDEX_DIP,  INDEX_TIP  = 5,  6,  7,  8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP = 9,  10, 11, 12
RING_MCP,   RING_PIP,   RING_DIP,   RING_TIP   = 13, 14, 15, 16
PINKY_MCP,  PINKY_PIP,  PINKY_DIP,  PINKY_TIP  = 17, 18, 19, 20

# ── MediaPipe 포즈 랜드마크 인덱스 ──────────────────────────────────────────
LEFT_SHOULDER,  RIGHT_SHOULDER  = 11, 12
LEFT_ELBOW,     RIGHT_ELBOW     = 13, 14
LEFT_WRIST_P,   RIGHT_WRIST_P   = 15, 16  # 포즈의 손목 (suffix _P: Pose)

# 검지~소지 TIP / MCP 인덱스 쌍
FINGER_TIP_MCP = [
    (INDEX_TIP,  INDEX_MCP),
    (MIDDLE_TIP, MIDDLE_MCP),
    (RING_TIP,   RING_MCP),
    (PINKY_TIP,  PINKY_MCP),
]


class Gesture(str, Enum):
    IDLE = "idle"
    CHOP = "chop"
    STIR = "stir"


class GestureDetector:
    """
    MediaPipe Hands 기반 요리 게임용 제스처 감지기.

    사용 예:
        detector = GestureDetector()
        gesture  = detector.detect(bgr_frame)   # cv2.VideoCapture 프레임
        detector.close()
    """

    # ── 하이퍼파라미터 ─────────────────────────────────────────────────────────
    # 동적 제스처 슬라이딩 윈도우 프레임 수 (~1.5초 @ 30fps)
    BUFFER_SIZE: int = 45              # 30→45: 느린 동작(~1Hz)과 화면 이탈 구간 대응

    # 방향 전환 최소 횟수 (chop/stir 판정 기준)
    OSCILLATION_MIN: int = 3           # 2→3: 최소 1.5사이클 이상 반복해야 인정

    # 방향 전환 최소 진폭 (정규화 좌표 단위, 화면 크기 대비 비율)
    # 0.05 = 화면 높이/너비의 5% — 작은 손떨림(2~3%)은 무시
    OSCILLATION_AMP: float = 0.05     # 0.025→0.05: 스윙당 최소 폭 2배 강화

    # 대진폭 shortcut: 이 값 이상의 진폭이면 방향 전환 1개만으로 chop/stir 인정
    # 화면의 20% 이상 움직인 경우만 해당 (화면 이탈 복귀 등 극단적 동작)
    OSCILLATION_AMP_LARGE: float = 0.20  # 0.10→0.20: shortcut 오발 방지

    # Chop vs Stir 축 우세 비율 (진폭 비율이 이 값 초과 시 해당 축으로 확정)
    AXIS_DOMINANCE: float = 1.5

    # 현재성 판정 윈도우: 버퍼 전체 대신 최근 N프레임 진폭으로 판정
    # 이전 제스처가 버퍼에 남아 현재 제스처를 덮어쓰는 문제 방지
    # (chop → stir 전환 시 y-버퍼 잔류가 stir 감지를 막는 현상 해결)
    RECENT_FRAMES: int = 25  # ~0.83초 @ 30fps

    # 제스처 Hold: idle로 바뀌기 전 이전 제스처를 유지하는 프레임 수 (토글 방지)
    HOLD_FRAMES: int = 8            # 줄이면: idle 전환 응답 속도 빨라짐.

    # 화면 이탈 구간 gap filling 최대 프레임 수 (chop 화면 이탈 대응)
    HAND_CACHE_MAX: int = 4

    # 정지 감지: 손목 속도가 이 값 미만이면 "정지"로 판정
    # chop은 보통 0.01~0.03이므로 0.006 이하는 실질적으로 정지/미세 떨림
    STILL_SPEED_MAX: float = 0.006    # 0.003→0.006: 미세 손떨림도 정지로 처리

    # 정지 감지: 이 프레임 수 연속 정지 시 동적 버퍼 초기화 (잔류 감지 방지)
    # 6프레임 ≈ 0.2초 @ 30fps
    STILL_RESET_FRAMES: int = 10      # 줄이면: 멈추면 더 빠르게 idle로 복귀

    def __init__(
        self,
        min_detection_confidence: float = 0.5,
        min_tracking_confidence: float = 0.4,
        debug: bool = False,
    ) -> None:
        self._hands = mp.solutions.hands.Hands(
            max_num_hands=1,
            model_complexity=0,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        # 손목 좌표 슬라이딩 윈도우 (동적 제스처용)
        self._wy: collections.deque[float] = collections.deque(maxlen=self.BUFFER_SIZE)
        self._wx: collections.deque[float] = collections.deque(maxlen=self.BUFFER_SIZE)
        # 마지막 손목 위치 캐시 — 화면 이탈 구간에서 버퍼 연속성 유지용
        self._last_wrist_pos: Optional[tuple] = None   # (x, y)
        self._wrist_absent: int = 999

        # 손목 속도 추적 (정지 감지용)
        self._wrist_speed: float = 0.0
        self._prev_wrist: Optional[tuple] = None

        # 정지 감지 카운터 (연속 정지 프레임 수)
        self._still_counter: int = 0
        # 제스처 Hold (토글 방지)
        self._hold_counter: int = 0
        self._held_gesture: Gesture = Gesture.IDLE
        # 마지막 추론 결과 (draw_landmarks 에서 사용)
        self._last_results = None
        # 디버그 정보 (외부에서 detector.debug_info 로 읽기)
        self._debug: bool = debug
        self.debug_info: dict = {}

    # ── Public API ─────────────────────────────────────────────────────────────
    def detect(self, bgr_frame: np.ndarray) -> Gesture:
        """
        BGR 프레임을 입력받아 안정화된 제스처를 반환한다.

        처리 흐름:
          1. BGR → RGB 변환 후 MediaPipe Hands 추론
          2. 손목 x/y 좌표를 슬라이딩 윈도우 버퍼에 추가
          3. 정지 감지: 연속 정지 시 버퍼 초기화 (잔류 패턴 제거)
          4. 동적 제스처(chop, stir) 판정 (최근 프레임 진폭 기반)
          5. IDLE 전환 시 HOLD_FRAMES 동안 이전 제스처를 유지 (토글 방지)
          6. debug_info 에 주요 수치 저장
        """
        import cv2

        # 입력 해상도를 줄여 MediaPipe 추론 부하 감소
        small = cv2.resize(bgr_frame, (320, 240))
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        r = self._hands.process(rgb)
        self._last_results = r

        hand = r.multi_hand_landmarks[0] if r.multi_hand_landmarks else None

        # 손목 좌표 버퍼 갱신
        if hand:
            w = hand.landmark[WRIST]
            self._wy.append(w.y)
            self._wx.append(w.x)
            # 손목 속도
            if self._prev_wrist is not None:
                self._wrist_speed = max(
                    abs(w.x - self._prev_wrist[0]),
                    abs(w.y - self._prev_wrist[1]))
            else:
                self._wrist_speed = 0.0
            self._prev_wrist = (w.x, w.y)
            self._last_wrist_pos = (w.x, w.y)
            self._wrist_absent = 0
        else:
            # 화면 이탈 구간 gap filling: 마지막 손목 위치로 채워 극값 보존
            if self._last_wrist_pos and self._wrist_absent < self.HAND_CACHE_MAX:
                self._wy.append(self._last_wrist_pos[1])
                self._wx.append(self._last_wrist_pos[0])
            self._wrist_absent += 1
            self._wrist_speed = 0.0
            self._prev_wrist = None

        # 정지 감지: 손이 멈추면 버퍼 초기화 (잔류 감지 방지)
        if hand and self._wrist_speed < self.STILL_SPEED_MAX:
            self._still_counter += 1
            if self._still_counter >= self.STILL_RESET_FRAMES:
                self._wy.clear()
                self._wx.clear()
        else:
            self._still_counter = 0

        # 버퍼를 1회만 numpy 변환 (detection 공유)
        wy_arr = np.array(self._wy, dtype=np.float32) if self._wy else np.empty(0, dtype=np.float32)
        wx_arr = np.array(self._wx, dtype=np.float32) if self._wx else np.empty(0, dtype=np.float32)
        y_amp    = float(wy_arr.max() - wy_arr.min()) if len(wy_arr) > 0 else 0.0
        x_amp    = float(wx_arr.max() - wx_arr.min()) if len(wx_arr) > 0 else 0.0
        chop_osc = _count_oscillations(wy_arr, self.OSCILLATION_AMP)
        stir_osc = _count_oscillations(wx_arr, self.OSCILLATION_AMP)

        # 최근 N프레임 진폭 — 과거 버퍼 잔류 차단
        recent_n = min(len(wy_arr), self.RECENT_FRAMES)
        if recent_n > 0:
            r_y_amp = float(wy_arr[-recent_n:].max() - wy_arr[-recent_n:].min())
            r_x_amp = float(wx_arr[-recent_n:].max() - wx_arr[-recent_n:].min())
        else:
            r_y_amp = r_x_amp = 0.0

        # 동적 제스처 판정
        is_chop = ((chop_osc >= self.OSCILLATION_MIN) or
                   (y_amp >= self.OSCILLATION_AMP_LARGE and chop_osc >= 1)) \
                  and r_y_amp >= self.OSCILLATION_AMP
        is_stir = ((stir_osc >= self.OSCILLATION_MIN) or
                   (x_amp >= self.OSCILLATION_AMP_LARGE and stir_osc >= 1)) \
                  and r_x_amp >= self.OSCILLATION_AMP

        raw = Gesture.IDLE
        if is_chop and is_stir:
            if r_y_amp > r_x_amp * self.AXIS_DOMINANCE:
                raw = Gesture.CHOP
            elif r_x_amp > r_y_amp * self.AXIS_DOMINANCE:
                raw = Gesture.STIR
        elif is_chop:
            raw = Gesture.CHOP
        elif is_stir:
            raw = Gesture.STIR

        # Hold 메커니즘 (IDLE 전환 시 잠시 이전 제스처 유지)
        if raw != Gesture.IDLE:
            self._held_gesture = raw
            self._hold_counter = self.HOLD_FRAMES
            output = raw
        elif self._hold_counter > 0:
            self._hold_counter -= 1
            output = self._held_gesture
        else:
            output = Gesture.IDLE

        if self._debug:
            self.debug_info = {
                "chop_osc":      chop_osc,
                "stir_osc":      stir_osc,
                "y_amp":         round(y_amp, 3),
                "x_amp":         round(x_amp, 3),
                "r_y_amp":       round(r_y_amp, 3),
                "r_x_amp":       round(r_x_amp, 3),
                "wrist_speed":   round(self._wrist_speed, 4),
                "still_counter": self._still_counter,
                "raw":           raw.value,
                "hold_counter":  self._hold_counter,
            }
        return output

    def close(self) -> None:
        """MediaPipe 리소스를 해제한다."""
        self._hands.close()

    def draw_landmarks(self, bgr_frame: np.ndarray) -> np.ndarray:
        """마지막 detect() 에서 추론한 손 랜드마크를 BGR 프레임에 그려 반환한다."""
        r = self._last_results
        if r is None or not r.multi_hand_landmarks:
            return bgr_frame

        mp_draw = mp.solutions.drawing_utils
        mp_hands = mp.solutions.hands

        for hand_lm in r.multi_hand_landmarks:
            mp_draw.draw_landmarks(
                bgr_frame, hand_lm, mp_hands.HAND_CONNECTIONS,
                landmark_drawing_spec=mp_draw.DrawingSpec(
                    color=(30, 140, 255), thickness=2, circle_radius=4),
                connection_drawing_spec=mp_draw.DrawingSpec(
                    color=(10, 100, 255), thickness=2),
            )

        return bgr_frame

# ── 모듈 레벨 유틸 함수 ──────────────────────────────────────────────────────

def _count_oscillations(buf: collections.deque, amp_threshold: float) -> int:
    """
    좌표 시계열에서 유효한 방향 전환 횟수를 반환한다.

    개선 포인트 (v2):
      1. 커널 크기 n//5 → 더 강한 평활화로 정지 구간의 미세 노이즈 제거
      2. 극값을 방향 전환 직전 위치(s[i-1])에서 측정 → 실제 peak/valley에 정확히 대응
      3. 진폭 미달 전환에도 극값 레퍼런스를 갱신 → stale reference 버그 수정
         (누적 방식: 레퍼런스가 묵은 값에 고착되지 않음)

    파라미터:
      buf           : 손목 좌표 슬라이딩 윈도우 (deque)
      amp_threshold : 유효 전환으로 인정할 최소 진폭

    예시 동작:
      정지 구간이 있어도 그 전후의 극값 차이가 amp_threshold 이상이면 전환으로 카운트.
      결과값 >= 2 → 반복 운동(chop 또는 stir) 판정
    """
    if isinstance(buf, np.ndarray):
        arr = buf
    else:
        arr = np.array(buf, dtype=np.float32)
    n = len(arr)
    if n < 10:
        return 0

    k = max(3, n // 10)                         # 가벼운 평활화: n//5(k=9)는 빠른 chop 진폭을 절반으로 깎음
    s = np.convolve(arr, np.ones(k) / k, mode="valid")

    if len(s) < 3:
        return 0

    changes = 0
    last_dir = 0
    last_extreme = float(s[0])

    for i in range(1, len(s)):
        diff = float(s[i]) - float(s[i - 1])
        if abs(diff) < 1e-5:
            continue
        cur_dir = 1 if diff > 0 else -1

        if last_dir != 0 and cur_dir != last_dir:
            extreme = float(s[i - 1])           # 방향 전환 직전이 실제 극값
            if abs(extreme - last_extreme) >= amp_threshold:
                changes += 1
            # 진폭 미달이라도 레퍼런스는 항상 갱신 (stale extreme 방지)
            last_extreme = extreme

        last_dir = cur_dir

    return changes


def _amplitude(buf) -> float:
    """버퍼 내 좌표의 최대-최소 범위(진폭)를 반환한다."""
    if isinstance(buf, np.ndarray):
        return float(buf.max() - buf.min()) if len(buf) > 0 else 0.0
    if not buf:
        return 0.0
    return float(max(buf) - min(buf))
