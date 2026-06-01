"""
Visual detection viewer — shows bounding boxes, track IDs, zone lines, and events
as the video plays in real time.

Usage:
    python pipeline/visualize.py --video "data/videos/CAM 1.mp4" --role entry
    python pipeline/visualize.py --video "data/videos/CAM 2.mp4" --role floor --zone SKINCARE --no-trails
    python pipeline/visualize.py --video "data/videos/CAM 4.mp4" --role billing --fullscreen

Controls:
    SPACE  — pause / resume
    Q/ESC  — quit
    S      — save current frame as screenshot
    +/-    — speed up / slow down playback
    F      — toggle fullscreen
    T      — toggle movement trails
"""

import cv2
import argparse
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict, deque

try:
    from ultralytics import YOLO
    import supervision as sv
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False
    print("WARNING: ultralytics/supervision not installed. Running in demo mode.")
    print("Install with: pip install ultralytics supervision")


# ── Colour palette ──────────────────────────────────────────────────────────
COLOURS = {
    "customer":  (0, 200, 0),      # green
    "staff":     (0, 100, 255),    # orange
    "entry":     (255, 255, 0),    # yellow  — entry line
    "exit":      (0, 0, 255),      # red     — exit line
    "zone":      (180, 0, 255),    # purple  — zone boundary
    "trail":     (0, 255, 200),    # teal    — movement trail
    "event_box": (0, 255, 255),    # cyan    — event notification
}

ZONE_COLOURS = {
    "SKINCARE":  (255, 100, 100),
    "MAKEUP":    (255, 50,  200),
    "HAIRCARE":  (100, 200, 255),
    "BODYCARE":  (100, 255, 150),
    "BILLING":   (255, 200, 50),
    "ENTRY":     (200, 200, 200),
}


class DetectionVisualizer:
    """Runs YOLOv8 detection and renders annotated video in a window."""

    def __init__(self, model_path: str = "yolov8n.pt", conf: float = 0.25, show_trails: bool = True):
        if YOLO_AVAILABLE:
            print(f"Loading model: {model_path}")
            self.model = YOLO(model_path)
            self.tracker = sv.ByteTrack()
        else:
            self.model = None
            self.tracker = None

        self.conf = conf
        self.show_trails = show_trails
        self.track_history: dict[int, deque] = defaultdict(lambda: deque(maxlen=30))
        self.track_first_seen: dict[int, datetime] = {}
        self.track_visitor_id: dict[int, str] = {}
        self.visitor_counter = 0
        self.staff_ids: set[int] = set()
        self.event_log: deque = deque(maxlen=8)   # last 8 events shown on screen
        self.entry_count = 0
        self.exit_count = 0
        self.current_queue = 0

    # ── Visitor ID assignment ────────────────────────────────────────────────
    def _get_visitor_id(self, track_id: int, frame_time: datetime) -> str:
        if track_id not in self.track_visitor_id:
            self.visitor_counter += 1
            self.track_visitor_id[track_id] = f"VIS_{self.visitor_counter:04d}"
            self.track_first_seen[track_id] = frame_time
        return self.track_visitor_id[track_id]

    def _is_staff(self, track_id: int, frame_time: datetime) -> bool:
        if track_id in self.staff_ids:
            return True
        first = self.track_first_seen.get(track_id)
        if first and (frame_time - first).total_seconds() > 600:
            self.staff_ids.add(track_id)
            return True
        return False

    # ── Entry / exit detection ───────────────────────────────────────────────
    _prev_cy: dict[int, float] = {}

    def _check_entry_exit(self, track_id: int, cy: float, frame_h: int,
                          visitor_id: str, is_staff: bool):
        mid = frame_h * 0.5
        prev = self._prev_cy.get(track_id)
        event = None
        if prev is not None:
            if prev < mid <= cy:
                self.entry_count += 1
                event = f"ENTRY  {visitor_id}" + (" [STAFF]" if is_staff else "")
                self.event_log.appendleft(("ENTRY", event))
            elif prev > mid >= cy:
                self.exit_count += 1
                event = f"EXIT   {visitor_id}" + (" [STAFF]" if is_staff else "")
                self.event_log.appendleft(("EXIT", event))
        self._prev_cy[track_id] = cy

    # ── Drawing helpers ──────────────────────────────────────────────────────
    def _draw_bbox(self, frame, bbox, track_id, visitor_id, is_staff, conf):
        x1, y1, x2, y2 = map(int, bbox)
        colour = COLOURS["staff"] if is_staff else COLOURS["customer"]

        # Bounding box - thinner line for cleaner look
        cv2.rectangle(frame, (x1, y1), (x2, y2), colour, 1)

        # Label background - smaller and cleaner
        label = f"{visitor_id}" if not is_staff else "STAFF"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
        cv2.rectangle(frame, (x1, y1 - th - 4), (x1 + tw + 4, y1), colour, -1)
        cv2.putText(frame, label, (x1 + 2, y1 - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

    def _draw_trail(self, frame, track_id):
        pts = list(self.track_history[track_id])
        for i in range(1, len(pts)):
            alpha = i / len(pts)
            colour = tuple(int(c * alpha) for c in COLOURS["trail"])
            cv2.line(frame, pts[i - 1], pts[i], colour, 2)

    def _draw_entry_line(self, frame, h, w, role):
        """Draw virtual tripwire line."""
        mid_y = int(h * 0.5)
        if role in ("entry", "entry_secondary"):
            cv2.line(frame, (0, mid_y), (w, mid_y), COLOURS["entry"], 2)
            cv2.putText(frame, "ENTRY LINE", (10, mid_y - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLOURS["entry"], 1)

    def _draw_zone_label(self, frame, zone: str, h: int, w: int):
        """Draw zone name banner at top of frame."""
        colour = ZONE_COLOURS.get(zone, (200, 200, 200))
        cv2.rectangle(frame, (0, 0), (w, 36), colour, -1)
        cv2.putText(frame, f"ZONE: {zone}", (10, 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)

    def _draw_hud(self, frame, h: int, w: int, fps: float,
                  frame_idx: int, total: int, role: str, paused: bool):
        """Draw heads-up display: counters, timestamp, speed."""
        # Semi-transparent dark bar at bottom
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, h - 90), (w, h), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

        elapsed = timedelta(seconds=frame_idx / max(fps, 1))
        ts = str(elapsed).split(".")[0]
        progress = f"{frame_idx}/{total}  ({ts})"

        cv2.putText(frame, f"ENTRY: {self.entry_count}   EXIT: {self.exit_count}",
                    (10, h - 65), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 0), 1)
        cv2.putText(frame, f"QUEUE: {self.current_queue}   VISITORS: {self.visitor_counter}",
                    (10, h - 42), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 1)
        cv2.putText(frame, progress,
                    (10, h - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)

        status = "  PAUSED  " if paused else f"  LIVE  {fps:.0f}fps"
        cv2.putText(frame, status, (w - 160, h - 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (0, 100, 255) if paused else (0, 255, 100), 1)

    def _draw_event_log(self, frame, w: int):
        """Draw last N events on right side."""
        x = w - 280
        cv2.rectangle(frame, (x - 4, 40), (w, 40 + len(self.event_log) * 22 + 8),
                      (0, 0, 0), -1)
        for i, (etype, msg) in enumerate(self.event_log):
            colour = {
                "ENTRY": (0, 255, 100),
                "EXIT":  (0, 80, 255),
            }.get(etype, (200, 200, 200))
            cv2.putText(frame, msg, (x, 58 + i * 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, colour, 1)

    # ── Main processing loop ─────────────────────────────────────────────────
    def run(self, video_path: str, role: str = "entry",
            zone: str = "SKINCARE", skip_frames: int = 1,
            base_timestamp: str = "2026-04-10T12:00:00", fullscreen: bool = False):

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print(f"ERROR: Cannot open video: {video_path}")
            return

        fps_native = cap.get(cv2.CAP_PROP_FPS) or 15
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        base_dt = datetime.fromisoformat(base_timestamp)
        frame_idx = 0
        paused = False
        speed = 1          # playback speed multiplier
        screenshot_n = 0

        window_name = f"Store Intelligence — {Path(video_path).name}  [{role.upper()}]"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        # Start with larger window or fullscreen
        if fullscreen:
            cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        else:
            cv2.resizeWindow(window_name, 1920, 1080)

        print(f"\nVideo: {video_path}")
        print(f"Resolution: {w}×{h}  FPS: {fps_native:.1f}  Frames: {total_frames}")
        print(f"Role: {role}  Zone: {zone}")
        print("\nControls:")
        print("  SPACE = pause/resume")
        print("  Q/ESC = quit")
        print("  S     = screenshot")
        print("  +/-   = speed up/down")
        print("  F     = toggle fullscreen")
        print("  T     = toggle trails")
        print()

        while True:
            if not paused:
                ret, frame = cap.read()
                if not ret:
                    print("End of video.")
                    break
                frame_idx += 1

            frame_time = base_dt + timedelta(seconds=frame_idx / fps_native)

            # ── Run detection every skip_frames ──────────────────────────────
            if YOLO_AVAILABLE and frame_idx % max(skip_frames, 1) == 0:
                results = self.model(frame, conf=self.conf, classes=[0], verbose=False)
                detections = sv.Detections.from_ultralytics(results[0])
                detections = self.tracker.update_with_detections(detections)

                if role == "billing":
                    self.current_queue = len(detections)

                for i in range(len(detections)):
                    bbox = detections.xyxy[i]
                    conf = float(detections.confidence[i])
                    tid = int(detections.tracker_id[i])

                    cx = int((bbox[0] + bbox[2]) / 2)
                    cy = int((bbox[1] + bbox[3]) / 2)

                    visitor_id = self._get_visitor_id(tid, frame_time)
                    is_staff = self._is_staff(tid, frame_time)

                    # Trail
                    self.track_history[tid].append((cx, cy))
                    if self.show_trails:
                        self._draw_trail(frame, tid)

                    # Entry/exit check
                    if role in ("entry", "entry_secondary"):
                        self._check_entry_exit(tid, cy, h, visitor_id, is_staff)

                    # Draw bbox
                    self._draw_bbox(frame, bbox, tid, visitor_id, is_staff, conf)

            elif not YOLO_AVAILABLE:
                # Demo mode — just show raw frame with overlay text
                cv2.putText(frame, "DEMO MODE — install ultralytics to enable detection",
                            (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 100, 255), 2)

            # ── Overlays ─────────────────────────────────────────────────────
            self._draw_entry_line(frame, h, w, role)
            self._draw_zone_label(frame, zone if role == "floor" else role.upper(), h, w)
            self._draw_hud(frame, h, w, fps_native, frame_idx, total_frames, role, paused)
            self._draw_event_log(frame, w)

            cv2.imshow(window_name, frame)

            # ── Key handling ─────────────────────────────────────────────────
            wait_ms = max(1, int(1000 / (fps_native * speed)))
            key = cv2.waitKey(wait_ms) & 0xFF

            if key == ord('q') or key == 27:       # Q or ESC
                break
            elif key == ord(' '):                   # SPACE — pause
                paused = not paused
                print("PAUSED" if paused else "RESUMED")
            elif key == ord('s'):                   # S — screenshot
                fname = f"screenshot_{screenshot_n:03d}.jpg"
                cv2.imwrite(fname, frame)
                print(f"Screenshot saved: {fname}")
                screenshot_n += 1
            elif key == ord('+') or key == ord('='):
                speed = min(speed * 2, 16)
                print(f"Speed: {speed}x")
            elif key == ord('-'):
                speed = max(speed / 2, 0.25)
                print(f"Speed: {speed}x")
            elif key == ord('f'):                   # F — toggle fullscreen
                fullscreen = not fullscreen
                if fullscreen:
                    cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
                    print("Fullscreen ON")
                else:
                    cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_NORMAL)
                    cv2.resizeWindow(window_name, 1920, 1080)
                    print("Fullscreen OFF")
            elif key == ord('t'):                   # T — toggle trails
                self.show_trails = not self.show_trails
                print(f"Trails: {'ON' if self.show_trails else 'OFF'}")

        cap.release()
        cv2.destroyAllWindows()

        print(f"\n=== Session Summary ===")
        print(f"Frames processed : {frame_idx}")
        print(f"Unique visitors  : {self.visitor_counter}")
        print(f"Entry count      : {self.entry_count}")
        print(f"Exit count       : {self.exit_count}")
        print(f"Staff detected   : {len(self.staff_ids)}")


# ── CLI ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Visual detection viewer for CCTV footage",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pipeline/visualize.py --video "data/videos/CAM 1.mp4" --role entry
  python pipeline/visualize.py --video "data/videos/CAM 2.mp4" --role floor --zone SKINCARE
  python pipeline/visualize.py --video "data/videos/CAM 3.mp4" --role floor --zone HAIRCARE
  python pipeline/visualize.py --video "data/videos/CAM 4.mp4" --role billing
  python pipeline/visualize.py --video "data/videos/CAM 5.mp4" --role entry_secondary
        """
    )
    parser.add_argument("--video",  required=True, help="Path to video file")
    parser.add_argument("--role",   default="entry",
                        choices=["entry", "entry_secondary", "floor", "billing"],
                        help="Camera role")
    parser.add_argument("--zone",   default="SKINCARE",
                        choices=["SKINCARE", "MAKEUP", "HAIRCARE", "BODYCARE", "BILLING", "ENTRY"],
                        help="Zone name (for floor cameras)")
    parser.add_argument("--skip",   type=int, default=2,
                        help="Process every Nth frame (default 2 = every other frame)")
    parser.add_argument("--conf",   type=float, default=0.25,
                        help="Detection confidence threshold (default 0.25)")
    parser.add_argument("--model",  default="yolov8n.pt",
                        help="YOLO model path (default yolov8n.pt)")
    parser.add_argument("--base-timestamp", default="2026-04-10T12:00:00",
                        help="Base timestamp for the video clip")
    parser.add_argument("--no-trails", action="store_true",
                        help="Disable movement trails for cleaner view")
    parser.add_argument("--fullscreen", action="store_true",
                        help="Start in fullscreen mode")

    args = parser.parse_args()

    viz = DetectionVisualizer(model_path=args.model, conf=args.conf, show_trails=not args.no_trails)
    viz.run(
        video_path=args.video,
        role=args.role,
        zone=args.zone,
        skip_frames=args.skip,
        base_timestamp=args.base_timestamp,
        fullscreen=args.fullscreen
    )


if __name__ == "__main__":
    main()
