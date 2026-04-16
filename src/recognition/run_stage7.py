"""Integrated Stage 7 demo: full recognition pipeline with debug overlay."""
from __future__ import annotations

import argparse
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

    print("[Stage7] Started. Press 'q' to quit.")
    last_combine_t = 0.0

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
                color = (0, 255, 0) if hi.gesture_confirmed else (200, 200, 200)
                if hi.stale:
                    color = (100, 100, 100)
                slot_txt = f" slot={hi.target_slot}" if hi.target_slot else ""
                motion_txt = f" motion={hi.motion}" if hi.motion else ""
                text = (
                    f"{hi.hand_id[0].upper()}: {hi.gesture}"
                    f" (n={hi.finger_count}){slot_txt}{motion_txt}"
                )
                cv2.putText(
                    frame, text, (10, y_cursor),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1, cv2.LINE_AA,
                )
                y_cursor += 22

                # palm-center dot
                px = int(hi.position[0] * fw)
                py = int(hi.position[1] * fh)
                if not hi.stale:
                    cv2.circle(frame, (px, py), 6, color, -1, cv2.LINE_AA)

            # Global "COMBINE!" flash on hands_together
            now = perf_counter()
            if any(hi.motion == "hands_together" for hi in inputs):
                last_combine_t = now
            if now - last_combine_t < 0.6:
                cv2.putText(
                    frame, "COMBINE!", (fw // 2 - 110, fh // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 165, 255), 4, cv2.LINE_AA,
                )

            # FPS
            cv2.putText(
                frame, f"FPS: {pipe.fps:5.1f}", (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2, cv2.LINE_AA,
            )

            cv2.imshow("Stage7 - Integrated Pipeline", frame)
            if (cv2.waitKey(1) & 0xFF) == ord("q"):
                break
    finally:
        pipe.close()
        cv2.destroyAllWindows()
        print("[Stage7] Closed.")


if __name__ == "__main__":
    main()
