"""Integrated Stage 7 demo: full recognition pipeline with debug overlay."""
from __future__ import annotations

import argparse
import csv
import os
from time import perf_counter

import cv2

from .camera import CameraConfig
from .hand_tracker import HandTrackerConfig
from .interface import RecognitionPipeline
from .pose_tracker import PoseTrackerConfig


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Stage 7: Integrated recognition pipeline demo")
    p.add_argument("--device", type=int, default=0)
    p.add_argument("--low-res", action="store_true")
    p.add_argument("--flip", action="store_true", help="Selfie-style mirror")
    p.add_argument("--log", type=str, default=None,
                   help="Path to CSV log file for motion debug (e.g. motion_log.csv)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    w, h = (320, 240) if args.low_res else (640, 480)
    pipe = RecognitionPipeline(
        camera_cfg=CameraConfig(device_index=args.device, width=w, height=h, fps=30),
        hand_cfg=HandTrackerConfig(),
        pose_cfg=PoseTrackerConfig(),
        flip=args.flip,
    )

    # CSV logger setup
    log_file = None
    log_writer = None
    if args.log:
        log_file = open(args.log, "w", newline="", encoding="utf-8")
        log_writer = csv.writer(log_file)
        log_writer.writerow([
            "time", "hand", "gesture", "gesture_confirmed", "motion_event",
            "v_par", "v_perp", "ratio",
            "chop_rev", "chop_spd", "chop_amp",
            "stir_rev", "stir_spd", "stir_amp",
        ])
        print(f"[Stage7] Logging motion debug to: {os.path.abspath(args.log)}")

    print("[Stage7] Started. Press 'q' to quit.")
    t0 = perf_counter()
    flash_text = ""
    flash_until = 0.0

    MOTION_TO_KOREAN = {
        "chop_motion": "CHOP",
        "stir_motion": "STIR",
        "hands_together": "PICK UP",   # 집기
        "palms_down": "DROP",          # 놓기
        "thumbs_up": "COMPLETE!",      # 완성
    }

    try:
        while True:
            inputs = pipe.step(draw_overlay=True)
            frame = pipe.last_frame
            if frame is None:
                break

            # Per-hand overlays
            fh, fw = frame.shape[:2]
            y_cursor = 80
            for hi in inputs:
                color = (0, 255, 0) if hi.gesture_confirmed else (220, 220, 220)
                if hi.stale:
                    color = (150, 150, 150)
                bg_color = (0, 0, 0)
                slot_txt = f" slot={hi.target_slot}" if hi.target_slot else ""
                motion_txt = f" motion={hi.motion}" if hi.motion else ""
                text = (
                    f"{hi.hand_id[0].upper()}: {hi.gesture}"
                    f" (n={hi.finger_count}){slot_txt}{motion_txt}"
                )
                cv2.putText(
                    frame, text, (10, y_cursor),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, bg_color, 3, cv2.LINE_AA,
                )
                cv2.putText(
                    frame, text, (10, y_cursor),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1, cv2.LINE_AA,
                )
                y_cursor += 22

                # palm-center dot
                px = int(hi.position[0] * fw)
                py = int(hi.position[1] * fh)
                if not hi.stale:
                    cv2.circle(frame, (px, py), 6, color, -1, cv2.LINE_AA)

            # Global event flash
            now = perf_counter()
            for hi in inputs:
                if hi.motion in ("hands_together", "palms_down", "thumbs_up"):
                    flash_text = MOTION_TO_KOREAN.get(hi.motion, hi.motion)
                    flash_until = now + 0.6
                    break
            if now < flash_until and flash_text:
                cv2.putText(
                    frame, flash_text, (fw // 2 - 140, fh // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 6, cv2.LINE_AA,
                )
                cv2.putText(
                    frame, flash_text, (fw // 2 - 140, fh // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 165, 255), 3, cv2.LINE_AA,
                )

            # CSV logging
            if log_writer:
                elapsed = perf_counter() - t0
                dbg_log = pipe.motion_debug
                for hi in inputs:
                    d = dbg_log[hi.hand_id]
                    log_writer.writerow([
                        f"{elapsed:.3f}", hi.hand_id, hi.gesture,
                        hi.gesture_confirmed, hi.motion or "",
                        f"{d.v_par:.4f}", f"{d.v_perp:.4f}",
                        f"{d.ratio_par_over_perp:.2f}",
                        d.rev_par, f"{d.speed_par:.4f}", f"{d.amp_par:.4f}",
                        d.rev_perp, f"{d.speed_perp:.4f}", f"{d.amp_perp:.4f}",
                    ])

            # Motion debug overlay (v_par/v_perp ratio + window stats)
            dbg = pipe.motion_debug
            dbg_y = fh - 10
            for hand in ("right", "left"):
                d = dbg[hand]
                # Line 1: instantaneous speeds and ratio
                r_txt = f"{d.ratio_par_over_perp:5.1f}" if d.ratio_par_over_perp < 999 else "  inf"
                line1 = f"{hand[0].upper()} v_par={d.v_par:.2f} v_perp={d.v_perp:.2f} ratio={r_txt}"
                # Line 2: window stats (chop candidate / stir candidate)
                line2 = (
                    f"  CHOP rev={d.rev_par} spd={d.speed_par:.2f} amp={d.amp_par:.3f}"
                    f" | STIR rev={d.rev_perp} spd={d.speed_perp:.2f} amp={d.amp_perp:.3f}"
                )
                for txt in (line2, line1):
                    cv2.putText(
                        frame, txt, (10, dbg_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 3, cv2.LINE_AA,
                    )
                    cv2.putText(
                        frame, txt, (10, dbg_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1, cv2.LINE_AA,
                    )
                    dbg_y -= 16
                dbg_y -= 4  # gap between hands

            # Threshold reference line
            thr_txt = f"[Thresholds] R_MIN=2.0  N_min={3}  V_min={0.35}  A_min={0.04}"
            cv2.putText(
                frame, thr_txt, (10, dbg_y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 3, cv2.LINE_AA,
            )
            cv2.putText(
                frame, thr_txt, (10, dbg_y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (100, 200, 255), 1, cv2.LINE_AA,
            )

            # FPS
            fps_text = f"FPS: {pipe.fps:5.1f}"
            cv2.putText(
                frame, fps_text, (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA,
            )
            cv2.putText(
                frame, fps_text, (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2, cv2.LINE_AA,
            )

            cv2.imshow("Stage7 - Integrated Pipeline", frame)
            if (cv2.waitKey(1) & 0xFF) == ord("q"):
                break
    finally:
        pipe.close()
        cv2.destroyAllWindows()
        if log_file:
            log_file.close()
            print(f"[Stage7] Log saved: {os.path.abspath(args.log)}")
        print("[Stage7] Closed.")


if __name__ == "__main__":
    main()
