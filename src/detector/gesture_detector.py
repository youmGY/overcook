"""
손 제스처 감지기 (MediaPipe Holistic 기반)

동작 원리
=========
1. **MediaPipe Holistic**: 포즈(33 관절) + 양손(각 21 관절) 좌표를 단일 추론으로 추출한다.
   - 좌표계: (x, y, z) 모두 0~1 정규화. y축은 화면 아래 방향이 양수
   - z축: 손목 기준 상대 깊이 (화면 앞쪽이 음수)

2. **정적 제스처 (grab, release)**: 단일 프레임에서 판정
   - 손가락 말림 여부: TIP-WRIST 3D 거리 / MCP-WRIST 3D 거리 비율로 판단 → 방향 무관
   - grab: 3개 이상 손가락 말림 + 팔꿈치 굽힘 + 손목이 팔꿈치보다 위

3. **동적 제스처 (chop, stir)**: 슬라이딩 윈도우 버퍼의 방향 전환 횟수로 판정
   - chop: y 좌표 버퍼에서 상하 반복 운동 감지
   - stir: x 좌표 버퍼에서 좌우 반복 운동 감지
   - 이동평균으로 손떨림 노이즈 제거 후 최소 진폭 이상의 방향 전환을 카운트

4. **상태 머신 (FSM)**: 정적 제스처 감지 시 버퍼를 초기화하고 쿨다운 동안
   동적 제스처를 비활성화하여 오탐을 방지한다.

5. **축 우세 판정**: chop / stir 동시 만족 시 y/x 진폭 비율로 우세 축을 선택한다.
"""

from __future__ import annotations

import collections
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
    IDLE    = "idle"
    GRAB    = "grab"
    RELEASE = "release"
    CHOP    = "chop"
    STIR    = "stir"


class GestureDetector:
    """
    MediaPipe Holistic 기반 요리 게임용 제스처 감지기.

    사용 예:
        detector = GestureDetector()
        gesture  = detector.detect(bgr_frame)   # cv2.VideoCapture 프레임
        detector.close()
    """

    # ── 하이퍼파라미터 ─────────────────────────────────────────────────────────
    # Grab: TIP-WRIST 거리 / MCP-WRIST 거리 비율이 아래 값 미만이면 "말림(curled)"
    CURL_RATIO: float = 1.5

    # Release: 위 비율이 아래 값 초과이면 "펴짐(extended)"
    EXTEND_RATIO: float = 1.3          # 1.6 → 1.3: 수평 자세에서 z 포함 3D 거리가 짧아지는 현상 보정

    # Release: 손목 + 4 MCP y 값의 표준편차 최대값 (손이 수평 = 손바닥 아래 향함)
    FLAT_Y_STD_MAX: float = 0.10       # 0.07 → 0.10: 더 넉넉하게 허용

    # Release: |엄지 x 차| / |손목 x 차| 비율 최대값 (엄지끼리 가장 가까움)
    THUMB_DIST_RATIO: float = 0.6      # 0.5 → 0.6: 약간 더 넉넉하게

    # 동적 제스처 슬라이딩 윈도우 프레임 수 (~1초 @ 30fps)
    BUFFER_SIZE: int = 30              # 45→30: 버퍼 초기화 후 빠른 재감지

    # 방향 전환 최소 횟수 (chop/stir 판정 기준)
    OSCILLATION_MIN: int = 2

    # 방향 전환 최소 진폭 (정규화 좌표 단위)
    OSCILLATION_AMP: float = 0.025     # 0.04 → 0.025: 작은 움직임도 감지

    # Chop vs Stir 축 우세 비율 (진폭 비율이 이 값 초과 시 해당 축으로 확정)
    AXIS_DOMINANCE: float = 1.5

    # 정적 제스처 감지 후 동적 제스처 비활성화 프레임 수
    STATIC_COOLDOWN: int = 8           # 12→8: 빠른 복귀

    # 제스처 Hold: idle로 바뀌기 전 이전 제스처를 유지하는 프레임 수 (토글 방지)
    HOLD_FRAMES: int = 8

    # Grab: 손목 속도가 이 값 초과이면 grab 판정 안 함 (chop/stir 중 grab 오감지 방지)
    # 정규화 좌표 단위 / 프레임. chop은 보통 0.01~0.03, grab은 < 0.005
    GRAB_SPEED_MAX: float = 0.012

    # Grab: 두 손목 사이 최대 정규화 거리 (두 손이 맞닿아야 grab)
    # 값은 카메라-사용자 거리에 따라 달라짐 → --debug 모드에서 grab_dist 수치 확인 후 튜닝
    # 전형적: 손 맞닿음 ≈ 0.05~0.15, 양 어깨 폭 ≈ 0.3~0.5
    GRAB_DIST_MAX: float = 0.20

    # Grab: 손이 겹쳐서 MediaPipe가 한 손을 놓쳤을 때 보완하는 캐시 유지 프레임 수
    HAND_CACHE_MAX: int = 4

    def __init__(
        self,
        min_detection_confidence: float = 0.6,
        min_tracking_confidence: float = 0.6,
    ) -> None:
        self._holistic = mp.solutions.holistic.Holistic(
            model_complexity=0,           # 경량 모델: 라즈베리파이 최적화
            enable_segmentation=False,    # 분할 맵 불필요 → 연산 절약
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        # 손목 좌표 슬라이딩 윈도우 (동적 제스처용)
        self._wy: collections.deque[float] = collections.deque(maxlen=self.BUFFER_SIZE)
        self._wx: collections.deque[float] = collections.deque(maxlen=self.BUFFER_SIZE)

        # 손목 속도 추적 (두 손 각각, grab 오감지 방지)
        self._wrist_speed: float = 0.0
        self._rh_speed: float = 0.0
        self._lh_speed: float = 0.0
        self._prev_rw: Optional[tuple] = None   # 직전 프레임 오른손 손목 (x, y)
        self._prev_lw: Optional[tuple] = None   # 직전 프레임 왼손 손목 (x, y)

        # 손 랜드마크 캐시 (grab 시 겹침으로 인한 MediaPipe 손 loss 보완)
        self._lh_cache = None
        self._rh_cache = None
        self._lh_age: int = 999   # 마지막으로 본 이후 경과 프레임
        self._rh_age: int = 999

        self._cooldown: int = 0
        # 제스처 Hold (토글 방지)
        self._hold_counter: int = 0
        self._held_gesture: Gesture = Gesture.IDLE
        # 마지막 추론 결과 (draw_landmarks 에서 사용)
        self._last_results = None
        # 디버그 정보 (외부에서 detector.debug_info 로 읽기)
        self.debug_info: dict = {}

    # ── Public API ─────────────────────────────────────────────────────────────
    def detect(self, bgr_frame: np.ndarray) -> Gesture:
        """
        BGR 프레임을 입력받아 안정화된 제스처를 반환한다.

        처리 흐름:
          1. BGR → RGB 변환 후 MediaPipe Holistic 추론
          2. 손목 x/y 좌표를 슬라이딩 윈도우 버퍼에 추가
          3. 정적 제스처(grab, release) 우선 판정 → 감지 시 버퍼 초기화 + 쿨다운 설정
          4. 쿨다운이 0이면 동적 제스처(chop, stir) 판정 (축 우세로 ambiguous 해소)
          5. IDLE 전환 시 HOLD_FRAMES 동안 이전 제스처를 유지 (토글 방지)
          6. debug_info 에 주요 수치 저장
        """
        import cv2

        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        r = self._holistic.process(rgb)
        self._last_results = r  # draw_landmarks() 에서 사용

        lh: Optional[object] = r.left_hand_landmarks
        rh: Optional[object] = r.right_hand_landmarks
        pose: Optional[object] = r.pose_landmarks

        # 손목 좌표 버퍼 갱신 (오른손 우선, 없으면 왼손) — chop/stir 감지용
        ref_hand = rh if rh else lh
        if ref_hand:
            w = ref_hand.landmark[WRIST]
            self._wy.append(w.y)
            self._wx.append(w.x)

        # 손목 속도 추적 (두 손 각각) — grab 오감지 방지
        if rh:
            rw_lm = rh.landmark[WRIST]
            if self._prev_rw is not None:
                self._rh_speed = max(
                    abs(rw_lm.x - self._prev_rw[0]),
                    abs(rw_lm.y - self._prev_rw[1]))
            self._prev_rw = (rw_lm.x, rw_lm.y)
        else:
            self._rh_speed = 0.0
            self._prev_rw = None

        if lh:
            lw_lm = lh.landmark[WRIST]
            if self._prev_lw is not None:
                self._lh_speed = max(
                    abs(lw_lm.x - self._prev_lw[0]),
                    abs(lw_lm.y - self._prev_lw[1]))
            self._prev_lw = (lw_lm.x, lw_lm.y)
        else:
            self._lh_speed = 0.0
            self._prev_lw = None

        self._wrist_speed = max(self._rh_speed, self._lh_speed)

        # 손 랜드마크 캐시 갱신 (grab 시 두 손 겹침으로 한 손 loss 보완용)
        if lh:
            self._lh_cache = lh
            self._lh_age = 0
        else:
            self._lh_age += 1
        if rh:
            self._rh_cache = rh
            self._rh_age = 0
        else:
            self._rh_age += 1

        # grab 판정에 사용할 손: 현재 프레임 우선, 없으면 캐시 (최대 HAND_CACHE_MAX 프레임)
        lh_grab = lh if lh else (
            self._lh_cache if self._lh_age <= self.HAND_CACHE_MAX else None)
        rh_grab = rh if rh else (
            self._rh_cache if self._rh_age <= self.HAND_CACHE_MAX else None)

        if self._cooldown > 0:
            self._cooldown -= 1

        # ── 디버그 정보 수집 ──────────────────────────────────────────────
        dbg: dict = {}
        for side, hand_lm in (("R", rh), ("L", lh)):
            if hand_lm:
                lm = hand_lm.landmark
                ratios = {
                    "idx": round(_tip_ratio(lm, INDEX_TIP,  INDEX_MCP),  2),
                    "mid": round(_tip_ratio(lm, MIDDLE_TIP, MIDDLE_MCP), 2),
                    "rng": round(_tip_ratio(lm, RING_TIP,   RING_MCP),   2),
                    "pnk": round(_tip_ratio(lm, PINKY_TIP,  PINKY_MCP),  2),
                }
                curled = sum(1 for v in ratios.values() if v < self.CURL_RATIO)
                extended = sum(1 for v in ratios.values() if v > self.EXTEND_RATIO)
                y_vals = [lm[WRIST].y] + [lm[m].y for m in (INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP)]
                dbg[side] = {
                    "ratios":   ratios,
                    "curled":   curled,
                    "extended": extended,
                    "y_std":    round(float(np.std(y_vals)), 3),
                    "wrist_xy": (round(lm[WRIST].x, 3), round(lm[WRIST].y, 3)),
                }
            else:
                dbg[side] = None

        if pose and rh:
            dbg["elbow_angle_R"] = round(_joint_angle(
                pose.landmark, RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST_P), 1)
            dbg["wrist_above_elbow_R"] = (
                pose.landmark[RIGHT_WRIST_P].y < pose.landmark[RIGHT_ELBOW].y)
        if pose and lh:
            dbg["elbow_angle_L"] = round(_joint_angle(
                pose.landmark, LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST_P), 1)
            dbg["wrist_above_elbow_L"] = (
                pose.landmark[LEFT_WRIST_P].y < pose.landmark[LEFT_ELBOW].y)

        if lh and rh:
            lw = lh.landmark[WRIST]; rw = rh.landmark[WRIST]
            lt = lh.landmark[THUMB_TIP]; rt = rh.landmark[THUMB_TIP]
            wd = abs(rw.x - lw.x)
            dbg["thumb_ratio"] = round(abs(rt.x - lt.x) / wd, 3) if wd > 0.02 else None

        dbg["chop_osc"]    = _count_oscillations(self._wy, self.OSCILLATION_AMP)
        dbg["stir_osc"]    = _count_oscillations(self._wx, self.OSCILLATION_AMP)
        dbg["y_amp"]       = round(_amplitude(self._wy), 3)
        dbg["x_amp"]       = round(_amplitude(self._wx), 3)
        dbg["wrist_speed"] = round(self._wrist_speed, 4)   # grab 차단 임계값: GRAB_SPEED_MAX

        # 두 손목 사이 거리 (grab 판정 핵심 — grab_dist < GRAB_DIST_MAX 이면 grab 가능)
        if lh_grab and rh_grab:
            lw_g = lh_grab.landmark[WRIST]; rw_g = rh_grab.landmark[WRIST]
            dbg["grab_dist"] = round(
                float(np.sqrt((lw_g.x - rw_g.x)**2 + (lw_g.y - rw_g.y)**2)), 3)
        else:
            dbg["grab_dist"] = None

        dbg["cooldown"]    = self._cooldown

        # ── 정적 제스처 판정 ──────────────────────────────────────────────
        raw = Gesture.IDLE
        if lh_grab and rh_grab and self._is_grab(lh_grab, rh_grab):
            raw = Gesture.GRAB
        elif lh and rh and self._is_release(lh, rh):
            raw = Gesture.RELEASE
        # ── 동적 제스처 판정 (쿨다운 중에는 skip) ────────────────────────
        elif self._cooldown == 0:
            is_chop = dbg["chop_osc"] >= self.OSCILLATION_MIN
            is_stir = dbg["stir_osc"] >= self.OSCILLATION_MIN
            if is_chop and is_stir:
                y_amp = _amplitude(self._wy)
                x_amp = _amplitude(self._wx)
                if y_amp > x_amp * self.AXIS_DOMINANCE:
                    raw = Gesture.CHOP
                elif x_amp > y_amp * self.AXIS_DOMINANCE:
                    raw = Gesture.STIR
            elif is_chop:
                raw = Gesture.CHOP
            elif is_stir:
                raw = Gesture.STIR

        dbg["raw"] = raw.value

        # 정적 제스처이면 즉시 버퍼 초기화 + 쿨다운
        if raw in (Gesture.GRAB, Gesture.RELEASE):
            self._reset_motion_buf()

        # ── Hold 메커니즘 (IDLE 전환 시 잠시 이전 제스처 유지) ──────────
        if raw != Gesture.IDLE:
            self._held_gesture = raw
            self._hold_counter = self.HOLD_FRAMES
            output = raw
        elif self._hold_counter > 0:
            self._hold_counter -= 1
            output = self._held_gesture
        else:
            output = Gesture.IDLE

        dbg["hold_counter"] = self._hold_counter
        self.debug_info = dbg
        return output

    def close(self) -> None:
        """MediaPipe 리소스를 해제한다."""
        self._holistic.close()

    def draw_landmarks(self, bgr_frame: np.ndarray) -> np.ndarray:
        """
        마지막 detect() 에서 추론한 랜드마크를 BGR 프레임에 그려 반환한다.

        표시 항목:
          - 포즈 골격 (초록):  어깨·팔꿈치·손목 등 33개 관절 + 연결선
          - 왼손 관절 (파랑):  21개 관절 + 손가락 연결선
          - 오른손 관절 (주황): 21개 관절 + 손가락 연결선
        """
        r = self._last_results
        if r is None:
            return bgr_frame

        mp_draw = mp.solutions.drawing_utils
        mp_hl   = mp.solutions.holistic

        # 포즈 골격 (연두/초록)
        if r.pose_landmarks:
            mp_draw.draw_landmarks(
                bgr_frame, r.pose_landmarks, mp_hl.POSE_CONNECTIONS,
                landmark_drawing_spec=mp_draw.DrawingSpec(
                    color=(0, 200, 80), thickness=1, circle_radius=2),
                connection_drawing_spec=mp_draw.DrawingSpec(
                    color=(0, 140, 60), thickness=1),
            )

        # 왼손 (파랑 계열)
        if r.left_hand_landmarks:
            mp_draw.draw_landmarks(
                bgr_frame, r.left_hand_landmarks, mp_hl.HAND_CONNECTIONS,
                landmark_drawing_spec=mp_draw.DrawingSpec(
                    color=(255, 100, 30), thickness=2, circle_radius=4),
                connection_drawing_spec=mp_draw.DrawingSpec(
                    color=(255, 60, 10), thickness=2),
            )

        # 오른손 (주황 계열)
        if r.right_hand_landmarks:
            mp_draw.draw_landmarks(
                bgr_frame, r.right_hand_landmarks, mp_hl.HAND_CONNECTIONS,
                landmark_drawing_spec=mp_draw.DrawingSpec(
                    color=(30, 140, 255), thickness=2, circle_radius=4),
                connection_drawing_spec=mp_draw.DrawingSpec(
                    color=(10, 100, 255), thickness=2),
            )

        return bgr_frame

    # ── Grab 판정 ───────────────────────────────────────────────────────────
    def _is_grab(self, lh_lm, rh_lm) -> bool:
        """
        Grab 판정 기준 (양손 맞닿음 방식):

        0. **손목 속도 체크** — 빠른 손 움직임(chop/stir) 중에는 판정 안 함
           두 손 중 최대 속도가 GRAB_SPEED_MAX 초과 시 False

        1. **양손 손가락 말림** — 두 손 모두 3개 이상 말린 손가락
           TIP-WRIST / MCP-WRIST 비율 < CURL_RATIO (방향 무관)

        2. **두 손이 맞닿음** — 손목 간 거리 < GRAB_DIST_MAX
           --debug 모드의 grab_dist 수치를 보고 GRAB_DIST_MAX 튜닝 권장
           (카메라-사용자 거리에 따라 0.10~0.25 범위)
        """
        # 빠른 손 움직임 중이면 grab 판정 안 함
        if self._wrist_speed > self.GRAB_SPEED_MAX:
            return False

        # 양손 모두 손가락이 말려야 함
        for hand_lm in (lh_lm, rh_lm):
            lm = hand_lm.landmark
            curled = sum(
                1 for tip_idx, mcp_idx in FINGER_TIP_MCP
                if _tip_ratio(lm, tip_idx, mcp_idx) < self.CURL_RATIO
            )
            if curled < 3:
                return False

        # 두 손목 거리 (맞닿음 확인)
        lw = lh_lm.landmark[WRIST]
        rw = rh_lm.landmark[WRIST]
        dist = float(np.sqrt((lw.x - rw.x) ** 2 + (lw.y - rw.y) ** 2))
        return dist < self.GRAB_DIST_MAX

    # ── Release 판정 ────────────────────────────────────────────────────────
    def _is_release(self, lh_lm, rh_lm) -> bool:
        """
        Release 판정 기준:

        1. **양손 손가락 펴짐**
           - TIP-WRIST 3D 거리 / MCP-WRIST 3D 거리 비율 > EXTEND_RATIO
           - 검지~소지 4개 모두 충족해야 함

        2. **손바닥이 아래를 향함 (수평 자세)**
           - 손목 + 4 MCP y 좌표의 표준편차 < FLAT_Y_STD_MAX
           - 손이 수평으로 펼쳐진 경우 모든 관절의 y 좌표가 비슷해짐

        3. **엄지끼리 가장 가깝게 위치**
           - |두 엄지 TIP x 거리| / |두 손목 x 거리| < THUMB_DIST_RATIO
           - 두 손 사이에서 엄지끼리가 가장 가까운 구조
        """
        for hand_lm in (lh_lm, rh_lm):
            lm = hand_lm.landmark
            extended = sum(
                1 for tip_idx, mcp_idx in FINGER_TIP_MCP
                if _tip_ratio(lm, tip_idx, mcp_idx) > self.EXTEND_RATIO
            )
            if extended < 4:
                return False
            y_vals = [lm[WRIST].y] + [lm[m].y for m in (INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP)]
            if float(np.std(y_vals)) > self.FLAT_Y_STD_MAX:
                return False

        lw = lh_lm.landmark[WRIST]
        rw = rh_lm.landmark[WRIST]
        lt = lh_lm.landmark[THUMB_TIP]
        rt = rh_lm.landmark[THUMB_TIP]

        wrist_x_dist = abs(rw.x - lw.x)
        if wrist_x_dist < 0.02:  # 두 손이 너무 가까우면 판정 보류
            return False
        thumb_x_dist = abs(rt.x - lt.x)
        return (thumb_x_dist / wrist_x_dist) <= self.THUMB_DIST_RATIO

    # ── Chop / Stir 판정 ────────────────────────────────────────────────────
    def _is_chop(self) -> bool:
        """Chop: y 버퍼에서 상하 반복 운동(방향 전환)을 감지한다."""
        return _count_oscillations(self._wy, self.OSCILLATION_AMP) >= self.OSCILLATION_MIN

    def _is_stir(self) -> bool:
        """Stir: x 버퍼에서 좌우 반복 운동(방향 전환)을 감지한다."""
        return _count_oscillations(self._wx, self.OSCILLATION_AMP) >= self.OSCILLATION_MIN

    def _reset_motion_buf(self) -> None:
        """동적 제스처 버퍼를 초기화하고 쿨다운을 설정한다."""
        self._wy.clear()
        self._wx.clear()
        self._cooldown = self.STATIC_COOLDOWN


# ── 모듈 레벨 유틸 함수 ──────────────────────────────────────────────────────

def _v3(lm, idx: int) -> np.ndarray:
    """랜드마크 리스트에서 idx번 좌표를 (x, y, z) ndarray로 반환한다."""
    l = lm[idx]
    return np.array([l.x, l.y, l.z], dtype=np.float32)


def _tip_ratio(lm, tip_idx: int, mcp_idx: int) -> float:
    """
    (TIP-WRIST 3D 거리) / (MCP-WRIST 3D 거리) 비율을 반환한다.

    손가락 말림 여부를 방향에 무관하게 판단하는 핵심 지표:
      - 완전히 펴진 손가락: 비율 ≈ 2.0~2.5 (TIP이 MCP보다 손목에서 훨씬 멀다)
      - 완전히 말린 손가락: 비율 ≈ 0.9~1.3 (TIP이 손목 근처로 돌아온다)
    """
    wrist = _v3(lm, WRIST)
    tip   = _v3(lm, tip_idx)
    mcp   = _v3(lm, mcp_idx)
    mcp_dist = float(np.linalg.norm(mcp - wrist))
    if mcp_dist < 1e-6:
        return 1.0
    return float(np.linalg.norm(tip - wrist)) / mcp_dist


def _joint_angle(pose_lm, a_idx: int, b_idx: int, c_idx: int) -> float:
    """
    b_idx 관절에서 a→b→c 방향의 각도(도)를 반환한다.

    - 팔꿈치(b) 기준으로 어깨(a)와 손목(c) 사이 각도를 계산
    - 180°: 팔이 완전히 펴진 상태
    - 90°: 팔꿈치가 직각으로 굽혀진 상태
    """
    a = np.array([pose_lm[a_idx].x, pose_lm[a_idx].y])
    b = np.array([pose_lm[b_idx].x, pose_lm[b_idx].y])
    c = np.array([pose_lm[c_idx].x, pose_lm[c_idx].y])
    v1 = a - b
    v2 = c - b
    denom = np.linalg.norm(v1) * np.linalg.norm(v2)
    if denom < 1e-8:
        return 180.0
    cos_a = float(np.clip(np.dot(v1, v2) / denom, -1.0, 1.0))
    return float(np.degrees(np.arccos(cos_a)))


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
    n = len(buf)
    if n < 10:
        return 0

    arr = np.array(buf, dtype=np.float32)
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


def _amplitude(buf: collections.deque) -> float:
    """버퍼 내 좌표의 최대-최소 범위(진폭)를 반환한다."""
    if not buf:
        return 0.0
    a = np.array(buf, dtype=np.float32)
    return float(a.max() - a.min())
