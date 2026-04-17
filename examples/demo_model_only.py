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
    p.add_argument("--flip", action="store_true", default=True, help="Mirror horizontally")
    p.add_argument("--no-flip", dest="flip", action="store_false")
    p.add_argument("--max-hands", type=int, default=2, choices=[1, 2])
    return p.parse_args()


def _put(frame, text, x, y, color=(255, 255, 255), scale=0.5):
    cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


def main() -> None:
    args = parse_args()

    cfg = CameraConfig(device_index=args.device, width=640, height=480, fps=30)
    cap = open_camera(cfg)
    tracker = HandTracker(HandTrackerConfig(max_num_hands=args.max_hands))
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

        h, w = frame.shape[:2]

        # Hand detection
        result = tracker.process(frame, draw=True)
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
