#!/usr/bin/env python3
"""Lightweight model-only viewer — hand landmarks + gesture + motion on camera feed.

Shows real-time:
  - Hand landmark skeleton overlay
  - DNN gesture label & confidence
  - Motion detection (chop/stir) state
  - Wrist speed & oscillation counts

Usage:
    uv run python examples/demo_model_only.py
    uv run python examples/demo_model_only.py --flip --device 0
"""
from __future__ import annotations

import argparse
import sys

import cv2
import numpy as np

from overcook.recognition.camera import CameraConfig, open_camera
from overcook.recognition.hand_tracker import HandTracker, HandTrackerConfig
from overcook.recognition.splitter import HandSplitter
from overcook.recognition.gesture import GestureClassifierDNN, landmarks_to_numpy, target_slot_for
from overcook.recognition.motion import MotionDetector


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Model-only hand/gesture/motion viewer")
    p.add_argument("--device", type=int, default=0, help="Camera index")
    p.add_argument("--fps", type=int, default=30, help="Requested camera FPS (e.g., 30/60)")
    p.add_argument("--flip", action="store_true", default=True, help="Mirror horizontally")
    p.add_argument("--no-flip", dest="flip", action="store_false")
    p.add_argument("--max-hands", type=int, default=2, choices=[1, 2])
    p.add_argument(
        "--infer-interval",
        type=int,
        default=1,
        help="Run hand landmark inference every N frames (1=every frame)",
    )
    p.add_argument(
        "--input-scale",
        type=float,
        default=1.0,
        help="Scale factor for hand detector input (0.5~1.0)",
    )
    p.add_argument(
        "--min-det",
        type=float,
        default=0.2,
        help="Min hand detection confidence (lower can help fast reacquisition)",
    )
    p.add_argument(
        "--min-track",
        type=float,
        default=0.2,
        help="Min hand tracking confidence (lower can reduce dropouts)",
    )
    p.add_argument(
        "--fast-motion",
        action="store_true",
        help="Preset for rapid chop/stir: prioritize hand capture over CPU savings",
    )
    p.add_argument(
        "--clahe",
        action="store_true",
        help="Apply CLAHE brightness normalization before inference",
    )
    p.add_argument("--clahe-clip", type=float, default=2.0, help="CLAHE clip limit")
    p.add_argument("--clahe-grid", type=int, default=8, help="CLAHE tile grid size")
    p.add_argument("--low-res", action="store_true", help="Use 320x240 for higher FPS")
    p.add_argument(
        "--draw-landmarks",
        action="store_true",
        default=True,
        help="Draw hand skeleton overlay (disable for higher FPS)",
    )
    p.add_argument("--no-draw-landmarks", dest="draw_landmarks", action="store_false")
    p.add_argument(
        "--minimal-overlay",
        action="store_true",
        help="Draw only FPS text (skip heavy debug panel)",
    )
    return p.parse_args()


def _put(frame, text, x, y, color=(255, 255, 255), scale=0.5):
    cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


def _apply_clahe(frame_bgr: np.ndarray, clip_limit: float, grid: int) -> np.ndarray:
    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=max(0.1, clip_limit), tileGridSize=(max(2, grid), max(2, grid)))
    l2 = clahe.apply(l)
    return cv2.cvtColor(cv2.merge((l2, a, b)), cv2.COLOR_LAB2BGR)


def main() -> None:
    args = parse_args()

    if args.fast_motion:
        args.max_hands = 1
        args.infer_interval = 1
        args.input_scale = 1.0
        args.min_det = min(args.min_det, 0.15)
        args.min_track = min(args.min_track, 0.15)
        if args.fps < 60:
            args.fps = 60

    width, height = (320, 240) if args.low_res else (640, 480)
    cfg = CameraConfig(device_index=args.device, width=width, height=height, fps=max(1, args.fps))
    cap = open_camera(cfg)
    tracker = HandTracker(
        HandTrackerConfig(
            max_num_hands=args.max_hands,
            min_detection_confidence=max(0.01, min(1.0, args.min_det)),
            min_tracking_confidence=max(0.01, min(1.0, args.min_track)),
            detect_every_n_frames=max(1, args.infer_interval),
            input_scale=max(0.1, min(1.0, args.input_scale)),
        )
    )
    splitter = HandSplitter()
    gesture_dnn = GestureClassifierDNN()
    motion = MotionDetector()

    # Cumulative stroke counters per hand
    total_chop = {"left": 0, "right": 0}
    total_stir = {"left": 0, "right": 0}
    # Combo tracking: consecutive strokes of the same type without idle gap
    combo_type = {"left": None, "right": None}   # "chop" | "stir" | None
    combo_count = {"left": 0, "right": 0}

    print("Press 'q' or ESC to quit, 'r' to reset counters.")

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if args.flip:
            frame = cv2.flip(frame, 1)

        model_frame = _apply_clahe(frame, args.clahe_clip, args.clahe_grid) if args.clahe else frame

        h, w = frame.shape[:2]

        # Hand detection
        result = tracker.process(model_frame, draw=args.draw_landmarks)
        hands = splitter.update(result, flipped=args.flip)

        # Per-hand gesture + wrist
        hand_wrists = {}
        gesture_info = {}

        for hand_id in ("left", "right"):
            state = hands[hand_id]
            if state.landmarks is not None:
                lm_np = landmarks_to_numpy(state.landmarks)
                label, conf, count = gesture_dnn.predict(lm_np)
                gesture_info[hand_id] = (label, conf, count)
                wlm = state.landmarks[0]  # wrist
                hand_wrists[hand_id] = (wlm.x, wlm.y)
            else:
                gesture_info[hand_id] = ("none", 0.0, 0)
                hand_wrists[hand_id] = None

        # Motion detection
        motion_results = motion.update(hand_wrists)

        # Update cumulative counters & combo tracking
        for hand_id in ("left", "right"):
            m_label, m_conf, m_count = motion_results.get(hand_id, (None, 0.0, 0))
            if m_label == "chop_motion" and m_count > 0:
                total_chop[hand_id] += m_count
                if combo_type[hand_id] == "chop":
                    combo_count[hand_id] += m_count
                else:
                    combo_type[hand_id] = "chop"
                    combo_count[hand_id] = m_count
            elif m_label == "stir_motion" and m_count > 0:
                total_stir[hand_id] += m_count
                if combo_type[hand_id] == "stir":
                    combo_count[hand_id] += m_count
                else:
                    combo_type[hand_id] = "stir"
                    combo_count[hand_id] = m_count
            elif m_label is None:
                # Idle — reset combo and totals
                combo_type[hand_id] = None
                combo_count[hand_id] = 0
                total_chop[hand_id] = 0
                total_stir[hand_id] = 0

        # Draw info panel
        y_off = 24
        _put(frame, f"FPS: {tracker.fps:.0f}", 10, y_off, (0, 255, 0), 0.6)
        y_off += 28

        if args.minimal_overlay:
            cv2.imshow("Model Output Viewer", frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("r"):
                for hid in ("left", "right"):
                    total_chop[hid] = total_stir[hid] = 0
                    combo_type[hid] = None
                    combo_count[hid] = 0
            continue

        for hand_id in ("left", "right"):
            color = (255, 200, 100) if hand_id == "left" else (100, 200, 255)
            label, conf, count = gesture_info[hand_id]
            stale = hands[hand_id].stale

            status = "STALE" if stale else "OK"
            _put(frame, f"[{hand_id.upper()}] {status}", 10, y_off, color, 0.55)
            y_off += 22

            _put(frame, f"  Gesture: {label} ({conf:.2f}) fingers={count}", 10, y_off, color, 0.45)
            y_off += 20

            slot = target_slot_for(label)
            _put(frame, f"  Slot: {slot}", 10, y_off, color, 0.45)
            y_off += 20

            # Motion
            m_label, m_conf, m_count = motion_results.get(hand_id, (None, 0.0, 0))
            dbg = motion.debug.get(hand_id)
            motion_str = m_label or "idle"
            _put(frame, f"  Motion: {motion_str} (conf={m_conf:.2f}, strokes={m_count})", 10, y_off, color, 0.45)
            y_off += 20

            # Combo & totals
            combo_str = f"{combo_type[hand_id]}x{combo_count[hand_id]}" if combo_type[hand_id] else "—"
            _put(frame, f"  Combo: {combo_str}   Total: chop={total_chop[hand_id]} stir={total_stir[hand_id]}",
                 10, y_off, (0, 255, 200), 0.45)
            y_off += 20

            if dbg:
                _put(frame, f"  osc: chop={dbg.chop_osc} stir={dbg.stir_osc}  "
                            f"amp: y={dbg.r_y_amp:.3f} x={dbg.r_x_amp:.3f}  "
                            f"spd={dbg.wrist_speed:.4f}",
                     10, y_off, (180, 180, 180), 0.38)
                y_off += 18
                _put(frame, f"  still={dbg.still_counter} hold={dbg.hold_counter} raw={dbg.raw}",
                     10, y_off, (180, 180, 180), 0.38)
                y_off += 18

            y_off += 8

        cv2.imshow("Model Output Viewer", frame)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        if key == ord("r"):
            for hid in ("left", "right"):
                total_chop[hid] = total_stir[hid] = 0
                combo_type[hid] = None
                combo_count[hid] = 0

    tracker.close()
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
