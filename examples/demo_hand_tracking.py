from __future__ import annotations

import argparse

import cv2

from overcook.recognition.camera import CameraConfig, open_camera
from overcook.recognition.hand_tracker import HandTracker, HandTrackerConfig
from examples.pose_tracker import PoseTracker, PoseTrackerConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage 2: MediaPipe Hands (+ optional Pose) realtime pipeline"
    )
    parser.add_argument("--device", type=int, default=0, help="Camera index")
    parser.add_argument(
        "--low-res",
        action="store_true",
        help="Use 320x240 for better performance on low-end devices",
    )
    parser.add_argument(
        "--flip",
        action="store_true",
        help="Mirror image horizontally for selfie-style view",
    )
    parser.add_argument(
        "--max-hands",
        type=int,
        default=2,
        choices=[1, 2],
        help="Maximum number of detected hands",
    )
    parser.add_argument(
        "--enable-pose",
        action="store_true",
        help="Also run MediaPipe Pose and overlay upper-body joints",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    width, height = (320, 240) if args.low_res else (640, 480)
    camera_config = CameraConfig(
        device_index=args.device,
        width=width,
        height=height,
        fps=30,
    )
    tracker_config = HandTrackerConfig(
        max_num_hands=args.max_hands,
        min_detection_confidence=0.7,
        min_tracking_confidence=0.6,
        model_complexity=0,
    )

    cap = open_camera(camera_config)
    tracker = HandTracker(tracker_config)
    pose = PoseTracker(PoseTrackerConfig()) if args.enable_pose else None

    print("[Stage2] Started. Press 'q' to quit.")
    print(
        f"[Stage2] Camera={args.device} "
        f"Resolution={width}x{height} max_hands={args.max_hands} "
        f"pose={'on' if args.enable_pose else 'off'}"
    )

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("[Stage2] Frame capture failed.")
                break

            if args.flip:
                frame = cv2.flip(frame, 1)

            tracker.process(frame, draw=True)
            if pose is not None:
                joints = pose.process(frame)
                pose.draw(frame, joints)
            tracker.draw_debug_text(frame)

            title = "Stage2 - Hands" + (" + Pose" if args.enable_pose else "")
            cv2.imshow(title, frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
    finally:
        tracker.close()
        if pose is not None:
            pose.close()
        cap.release()
        cv2.destroyAllWindows()
        print("[Stage2] Closed.")


if __name__ == "__main__":
    main()
