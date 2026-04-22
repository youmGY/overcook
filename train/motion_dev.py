"""Chop / Stir wrist trajectory + reversal count debug visualizer.

Usage:
    python visualize_motion_debug.py          # 기본 실행
    python visualize_motion_debug.py --hand right   # 오른손만
    python visualize_motion_debug.py --save          # 자동 캡처 저장

키보드:
    s  — 현재 그래프를 PNG 캡처 저장
    q  — 종료
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import deque
from datetime import datetime
from time import perf_counter

import cv2
import numpy as np

# --- matplotlib non-interactive backend for embedding -----------------------
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

# --- project imports --------------------------------------------------------
sys.path.insert(0, os.path.dirname(__file__))
from overcook.recognition.interface import RecognitionPipeline
from overcook.recognition.hand_tracker import HandTrackerConfig
from overcook.recognition.camera import CameraConfig

# ---------------------------------------------------------------------------
#  Config
# ---------------------------------------------------------------------------
TRAIL_LEN = 180          # trajectory 버퍼 길이 (프레임)
GRAPH_W, GRAPH_H = 640, 480  # 그래프 이미지 크기
SAVE_DIR = "debug_captures"

# ---------------------------------------------------------------------------
#  Ring-buffer helper
# ---------------------------------------------------------------------------

class TrailBuffer:
    def __init__(self, maxlen: int = TRAIL_LEN):
        self.xs = deque(maxlen=maxlen)
        self.ys = deque(maxlen=maxlen)
        self.chop_revs = deque(maxlen=maxlen)
        self.stir_revs = deque(maxlen=maxlen)
        self.chop_deltas = deque(maxlen=maxlen)
        self.stir_deltas = deque(maxlen=maxlen)
        self.speeds = deque(maxlen=maxlen)
        self.timestamps = deque(maxlen=maxlen)
        self.labels = deque(maxlen=maxlen)

    def push(self, wx, wy, dbg, label: str, t: float):
        self.xs.append(wx)
        self.ys.append(wy)
        self.chop_revs.append(dbg.chop_osc)
        self.stir_revs.append(dbg.stir_osc)
        self.chop_deltas.append(dbg.chop_delta)
        self.stir_deltas.append(dbg.stir_delta)
        self.speeds.append(dbg.wrist_speed)
        self.timestamps.append(t)
        self.labels.append(label)


# ---------------------------------------------------------------------------
#  Matplotlib → OpenCV image helper
# ---------------------------------------------------------------------------

def fig_to_cv(fig: Figure, w: int, h: int) -> np.ndarray:
    """Render a Matplotlib figure to a BGR numpy array of size (h, w)."""
    canvas = FigureCanvasAgg(fig)
    canvas.draw()
    buf = np.frombuffer(canvas.buffer_rgba(), dtype=np.uint8)
    buf = buf.reshape(canvas.get_width_height()[::-1] + (4,))
    img = cv2.cvtColor(buf, cv2.COLOR_RGBA2BGR)
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)


# ---------------------------------------------------------------------------
#  Draw debug graph
# ---------------------------------------------------------------------------

def draw_debug_graph(trail: TrailBuffer, hand_id: str) -> np.ndarray:
    """Return a BGR image with 4 subplots for one hand."""
    n = len(trail.xs)
    if n < 2:
        blank = np.zeros((GRAPH_H, GRAPH_W, 3), dtype=np.uint8)
        cv2.putText(blank, f"Waiting for {hand_id} hand data...",
                    (20, GRAPH_H // 2), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (200, 200, 200), 1)
        return blank

    t0 = trail.timestamps[0]
    ts = np.array(trail.timestamps) - t0
    xs = np.array(trail.xs)
    ys = np.array(trail.ys)

    fig, axes = plt.subplots(2, 2, figsize=(8, 6), dpi=100)
    fig.suptitle(f"[{hand_id.upper()}] Motion Debug", fontsize=12, fontweight="bold")

    # --- (0,0) Wrist Y trajectory (chop axis) ------------------------------
    ax = axes[0, 0]
    ax.plot(ts, ys, color="royalblue", linewidth=1.2, label="wrist Y")
    # Mark reversal deltas
    for i, d in enumerate(trail.chop_deltas):
        if d > 0:
            ax.axvline(ts[i], color="red", alpha=0.5, linewidth=0.8)
    ax.set_title("Wrist Y (chop axis)")
    ax.set_ylabel("Y (norm)")
    ax.invert_yaxis()
    ax.legend(loc="upper right", fontsize=7)
    ax.grid(True, alpha=0.3)

    # --- (0,1) Wrist X trajectory (stir axis) ------------------------------
    ax = axes[0, 1]
    ax.plot(ts, xs, color="darkorange", linewidth=1.2, label="wrist X")
    for i, d in enumerate(trail.stir_deltas):
        if d > 0:
            ax.axvline(ts[i], color="green", alpha=0.5, linewidth=0.8)
    ax.set_title("Wrist X (stir axis)")
    ax.set_ylabel("X (norm)")
    ax.legend(loc="upper right", fontsize=7)
    ax.grid(True, alpha=0.3)

    # --- (1,0) Reversal counts (cumulative) --------------------------------
    ax = axes[1, 0]
    chop_r = np.array(trail.chop_revs)
    stir_r = np.array(trail.stir_revs)
    ax.step(ts, chop_r, where="post", color="red", linewidth=1.5, label="chop rev")
    ax.step(ts, stir_r, where="post", color="green", linewidth=1.5, label="stir rev")
    ax.set_title("Reversal Count (cumulative)")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("count")
    ax.legend(loc="upper left", fontsize=7)
    ax.grid(True, alpha=0.3)

    # --- (1,1) Detection label timeline ------------------------------------
    ax = axes[1, 1]
    label_map = {"idle": 0, "chop_motion": 1, "stir_motion": 2}
    label_colors = {"idle": "gray", "chop_motion": "red", "stir_motion": "green"}
    labels_num = [label_map.get(l, 0) for l in trail.labels]
    ax.fill_between(ts, labels_num, step="post", alpha=0.4, color="steelblue")
    ax.set_yticks([0, 1, 2])
    ax.set_yticklabels(["idle", "chop", "stir"])
    ax.set_title("Detection Result")
    ax.set_xlabel("time (s)")
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    img = fig_to_cv(fig, GRAPH_W, GRAPH_H)
    plt.close(fig)
    return img


# ---------------------------------------------------------------------------
#  2D trajectory mini-map
# ---------------------------------------------------------------------------

def draw_trajectory_map(trail: TrailBuffer, hand_id: str, size: int = 200) -> np.ndarray:
    """Draw a small X-Y scatter trail for one hand."""
    img = np.zeros((size, size, 3), dtype=np.uint8)
    n = len(trail.xs)
    if n < 2:
        return img

    xs = np.array(trail.xs)
    ys = np.array(trail.ys)

    # Normalize to [margin, size-margin]
    margin = 15
    def _norm(v):
        lo, hi = v.min(), v.max()
        rng = hi - lo if hi - lo > 1e-6 else 1e-6
        return ((v - lo) / rng * (size - 2 * margin) + margin).astype(int)

    px = _norm(xs)
    py = _norm(ys)

    # Draw fading trail
    for i in range(1, n):
        alpha = i / n
        color = (
            int(100 * (1 - alpha) + 255 * alpha),
            int(200 * alpha),
            int(100 * alpha),
        )
        cv2.line(img, (px[i - 1], py[i - 1]), (px[i], py[i]), color, 1)

    # Current position
    cv2.circle(img, (px[-1], py[-1]), 4, (0, 255, 255), -1)
    cv2.putText(img, f"{hand_id[0].upper()} traj", (5, 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
    return img


# ---------------------------------------------------------------------------
#  Save helper
# ---------------------------------------------------------------------------

def save_capture(cam_frame, graph_img, hand_id: str):
    os.makedirs(SAVE_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = os.path.join(SAVE_DIR, f"motion_debug_{hand_id}_{stamp}.png")
    # Combine camera + graph side by side
    h = max(cam_frame.shape[0], graph_img.shape[0])
    cam_resized = cv2.resize(cam_frame, (int(cam_frame.shape[1] * h / cam_frame.shape[0]), h))
    graph_resized = cv2.resize(graph_img, (int(graph_img.shape[1] * h / graph_img.shape[0]), h))
    combined = np.hstack([cam_resized, graph_resized])
    cv2.imwrite(fname, combined)
    print(f"[saved] {fname}")


# ---------------------------------------------------------------------------
#  Main loop
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Motion debug visualizer")
    parser.add_argument("--hand", choices=["left", "right", "both"], default="both",
                        help="어떤 손을 시각화할지 (default: both)")
    parser.add_argument("--save", action="store_true",
                        help="chop/stir 감지 시 자동 캡처 저장")
    parser.add_argument("--camera", type=int, default=0, help="카메라 인덱스")
    args = parser.parse_args()

    hands_to_show = ["left", "right"] if args.hand == "both" else [args.hand]

    pipeline = RecognitionPipeline(
        camera_cfg=CameraConfig(device_index=args.camera),
        hand_cfg=HandTrackerConfig(),
        flip=True,
    )

    trails = {h: TrailBuffer() for h in ("left", "right")}
    auto_saved = {h: False for h in ("left", "right")}

    print("=== Motion Debug Visualizer ===")
    print("  s : 캡처 저장")
    print("  q : 종료")
    print()

    try:
        while True:
            inputs = pipeline.step(draw_overlay=True)
            frame = pipeline.last_frame
            if frame is None:
                continue

            now = perf_counter()
            dbg = pipeline.motion_debug

            for inp in inputs:
                hid = inp.hand_id
                if inp.position != (0.0, 0.0):
                    trails[hid].push(
                        inp.position[0], inp.position[1],
                        dbg[hid],
                        inp.motion or "idle",
                        now,
                    )

            # --- Build display ------------------------------------------------
            # Camera view (with trajectory overlay)
            cam_display = frame.copy()
            cam_h, cam_w = cam_display.shape[:2]

            for hid in hands_to_show:
                t = trails[hid]
                if len(t.xs) > 1:
                    pts = np.array(
                        [(int(x * cam_w), int(y * cam_h))
                         for x, y in zip(t.xs, t.ys)],
                        dtype=np.int32,
                    )
                    color = (0, 100, 255) if hid == "right" else (255, 100, 0)
                    cv2.polylines(cam_display, [pts[-60:]], False, color, 2)

                # HUD text
                d = dbg[hid]
                y_off = 25 if hid == "left" else cam_h // 2 + 25
                texts = [
                    f"{hid.upper()}: {d.raw}",
                    f"chop_rev={d.chop_osc}  stir_rev={d.stir_osc}",
                    f"amp_y={d.r_y_amp:.4f}  amp_x={d.r_x_amp:.4f}",
                    f"speed={d.wrist_speed:.4f}  still={d.still_counter}",
                ]
                for i, txt in enumerate(texts):
                    cv2.putText(cam_display, txt, (10, y_off + i * 22),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                                (0, 255, 0), 1, cv2.LINE_AA)

            # Graph panel(s)
            graphs = []
            for hid in hands_to_show:
                g = draw_debug_graph(trails[hid], hid)
                graphs.append(g)

                # Auto-save on detection
                if args.save:
                    d = dbg[hid]
                    if d.raw in ("chop_motion", "stir_motion"):
                        if not auto_saved[hid]:
                            save_capture(cam_display, g, hid)
                            auto_saved[hid] = True
                    else:
                        auto_saved[hid] = False

            # Trajectory mini-maps
            traj_maps = []
            for hid in hands_to_show:
                traj_maps.append(draw_trajectory_map(trails[hid], hid, 200))

            # --- Compose final window ----------------------------------------
            # Resize camera to match graph height
            if len(graphs) == 1:
                graph_panel = graphs[0]
            else:
                graph_panel = np.vstack(graphs)

            target_h = graph_panel.shape[0]
            cam_resized = cv2.resize(
                cam_display,
                (int(cam_w * target_h / cam_h), target_h),
            )

            # Trajectory mini-maps stacked
            if traj_maps:
                traj_col = np.vstack(traj_maps)
                # Pad traj column to match height
                if traj_col.shape[0] < target_h:
                    pad = np.zeros(
                        (target_h - traj_col.shape[0], traj_col.shape[1], 3),
                        dtype=np.uint8,
                    )
                    traj_col = np.vstack([traj_col, pad])
                elif traj_col.shape[0] > target_h:
                    traj_col = cv2.resize(
                        traj_col,
                        (traj_col.shape[1], target_h),
                    )
                combined = np.hstack([cam_resized, traj_col, graph_panel])
            else:
                combined = np.hstack([cam_resized, graph_panel])

            cv2.imshow("Motion Debug", combined)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            elif key == ord("s"):
                for hid in hands_to_show:
                    g = draw_debug_graph(trails[hid], hid)
                    save_capture(cam_display, g, hid)

    except KeyboardInterrupt:
        pass
    finally:
        pipeline.close()
        cv2.destroyAllWindows()
        print("Done.")


if __name__ == "__main__":
    main()
 