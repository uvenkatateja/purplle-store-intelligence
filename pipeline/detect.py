"""Main detection and tracking script using YOLOv8 + supervision."""

import cv2
import json
import argparse
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from ultralytics import YOLO
import supervision as sv

from tracker import VisitorTracker
from emit import EventEmitter


class CCTVProcessor:
    """Processes CCTV footage and emits structured events."""
    
    def __init__(
        self,
        model_path: str = "yolov8n.pt",
        confidence_threshold: float = 0.25,
        process_every_n_frames: int = 3
    ):
        """
        Initialize CCTV processor.
        
        Args:
            model_path: Path to YOLO model
            confidence_threshold: Minimum confidence for detections
            process_every_n_frames: Process every Nth frame for speed
        """
        print(f"Loading YOLO model: {model_path}")
        self.model = YOLO(model_path)
        self.confidence_threshold = confidence_threshold
        self.process_every_n_frames = process_every_n_frames
        
        # Initialize ByteTrack tracker
        self.tracker = sv.ByteTrack()
        
        # Initialize visitor tracker
        self.visitor_tracker = VisitorTracker()
        
        # Track state for entry/exit detection
        self.previous_positions: Dict[int, Tuple[float, float]] = {}
        
    def process_video(
        self,
        video_path: str,
        camera_id: str,
        store_id: str,
        camera_role: str,
        zone_id: str,
        emitter: EventEmitter,
        base_timestamp: datetime
    ):
        """
        Process a single video file.
        
        Args:
            video_path: Path to video file
            camera_id: Camera identifier
            store_id: Store identifier
            camera_role: Role of camera (entry, floor, billing)
            zone_id: Zone this camera covers
            emitter: Event emitter
            base_timestamp: Base timestamp for the video
        """
        print(f"Processing {video_path} (Camera: {camera_id}, Role: {camera_role})")
        
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print(f"Error: Could not open video {video_path}")
            return
        
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_idx = 0
        
        print(f"Video info: {total_frames} frames at {fps} FPS")
        
        # Zone-specific tracking
        zone_dwell_tracking: Dict[int, Dict] = {}  # track_id -> {enter_time, last_emit_time}
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            # Calculate frame timestamp
            frame_time = base_timestamp + timedelta(seconds=frame_idx / fps)
            
            # Process only every Nth frame
            if frame_idx % self.process_every_n_frames == 0:
                # Run detection
                results = self.model(frame, conf=self.confidence_threshold, classes=[0], verbose=False)
                
                # Extract detections
                detections = sv.Detections.from_ultralytics(results[0])
                
                # Update tracker
                detections = self.tracker.update_with_detections(detections)
                
                # Process each detection
                for detection_idx in range(len(detections)):
                    bbox = detections.xyxy[detection_idx]
                    confidence = detections.confidence[detection_idx]
                    track_id = detections.tracker_id[detection_idx]
                    
                    # Update visitor tracker
                    visitor_id = self.visitor_tracker.update_track(
                        track_id, bbox, confidence, frame_time
                    )
                    
                    # Check if staff
                    is_staff = self.visitor_tracker.is_staff(track_id)
                    
                    # Handle entry/exit detection for entry cameras
                    if camera_role == "entry":
                        self._handle_entry_exit(
                            track_id, bbox, frame.shape, visitor_id,
                            store_id, camera_id, frame_time, confidence, is_staff, emitter
                        )
                    
                    # Handle zone events for floor cameras
                    elif camera_role == "floor":
                        self._handle_zone_events(
                            track_id, visitor_id, zone_id, frame_time,
                            store_id, camera_id, confidence, is_staff,
                            zone_dwell_tracking, emitter
                        )
                    
                    # Handle billing zone for billing cameras
                    elif camera_role == "billing":
                        self._handle_billing_events(
                            track_id, visitor_id, frame_time,
                            store_id, camera_id, confidence, is_staff,
                            zone_dwell_tracking, emitter
                        )
                
                # Cleanup stale tracks
                self.visitor_tracker.cleanup_stale_tracks(frame_time, timeout_seconds=5)
            
            frame_idx += 1
            
            # Progress indicator
            if frame_idx % 100 == 0:
                progress = (frame_idx / total_frames) * 100
                print(f"Progress: {progress:.1f}% ({frame_idx}/{total_frames} frames)")
        
        cap.release()
        print(f"Completed processing {video_path}")
    
    def _handle_entry_exit(
        self,
        track_id: int,
        bbox: np.ndarray,
        frame_shape: Tuple,
        visitor_id: str,
        store_id: str,
        camera_id: str,
        frame_time: datetime,
        confidence: float,
        is_staff: bool,
        emitter: EventEmitter
    ):
        """Handle entry/exit detection based on crossing middle line."""
        height, width = frame_shape[:2]
        middle_y = height * 0.5
        
        # Calculate center of bounding box
        center_x = (bbox[0] + bbox[2]) / 2
        center_y = (bbox[1] + bbox[3]) / 2
        
        # Check if we have previous position
        if track_id in self.previous_positions:
            prev_x, prev_y = self.previous_positions[track_id]
            
            # Check if crossed middle line
            if prev_y < middle_y and center_y >= middle_y:
                # Crossed downward - ENTRY
                emitter.emit_event(
                    store_id=store_id,
                    camera_id=camera_id,
                    visitor_id=visitor_id,
                    event_type="ENTRY",
                    timestamp=frame_time,
                    zone_id=None,
                    dwell_ms=0,
                    is_staff=is_staff,
                    confidence=confidence,
                    metadata={"session_seq": 1}
                )
            
            elif prev_y > middle_y and center_y <= middle_y:
                # Crossed upward - EXIT
                emitter.emit_event(
                    store_id=store_id,
                    camera_id=camera_id,
                    visitor_id=visitor_id,
                    event_type="EXIT",
                    timestamp=frame_time,
                    zone_id=None,
                    dwell_ms=0,
                    is_staff=is_staff,
                    confidence=confidence,
                    metadata={}
                )
                
                # Mark as exited
                self.visitor_tracker.mark_exit(track_id)
        
        # Update previous position
        self.previous_positions[track_id] = (center_x, center_y)
    
    def _handle_zone_events(
        self,
        track_id: int,
        visitor_id: str,
        zone_id: str,
        frame_time: datetime,
        store_id: str,
        camera_id: str,
        confidence: float,
        is_staff: bool,
        zone_dwell_tracking: Dict,
        emitter: EventEmitter
    ):
        """Handle zone enter/dwell events."""
        # Check if track just entered this zone
        if track_id not in zone_dwell_tracking:
            # Emit ZONE_ENTER
            emitter.emit_event(
                store_id=store_id,
                camera_id=camera_id,
                visitor_id=visitor_id,
                event_type="ZONE_ENTER",
                timestamp=frame_time,
                zone_id=zone_id,
                dwell_ms=0,
                is_staff=is_staff,
                confidence=confidence,
                metadata={"sku_zone": zone_id}
            )
            
            zone_dwell_tracking[track_id] = {
                'enter_time': frame_time,
                'last_emit_time': frame_time
            }
        else:
            # Check if should emit ZONE_DWELL (every 30 seconds)
            track_info = zone_dwell_tracking[track_id]
            time_since_last_emit = (frame_time - track_info['last_emit_time']).total_seconds()
            
            if time_since_last_emit >= 30:
                dwell_ms = int((frame_time - track_info['enter_time']).total_seconds() * 1000)
                
                emitter.emit_event(
                    store_id=store_id,
                    camera_id=camera_id,
                    visitor_id=visitor_id,
                    event_type="ZONE_DWELL",
                    timestamp=frame_time,
                    zone_id=zone_id,
                    dwell_ms=dwell_ms,
                    is_staff=is_staff,
                    confidence=confidence,
                    metadata={"sku_zone": zone_id}
                )
                
                track_info['last_emit_time'] = frame_time
    
    def _handle_billing_events(
        self,
        track_id: int,
        visitor_id: str,
        frame_time: datetime,
        store_id: str,
        camera_id: str,
        confidence: float,
        is_staff: bool,
        zone_dwell_tracking: Dict,
        emitter: EventEmitter
    ):
        """Handle billing zone events."""
        # Similar to zone events but for billing
        if track_id not in zone_dwell_tracking:
            # Count current queue depth
            queue_depth = len(zone_dwell_tracking)
            
            emitter.emit_event(
                store_id=store_id,
                camera_id=camera_id,
                visitor_id=visitor_id,
                event_type="BILLING_QUEUE_JOIN",
                timestamp=frame_time,
                zone_id="BILLING",
                dwell_ms=0,
                is_staff=is_staff,
                confidence=confidence,
                metadata={"queue_depth": queue_depth}
            )
            
            zone_dwell_tracking[track_id] = {
                'enter_time': frame_time,
                'last_emit_time': frame_time
            }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Process CCTV footage and emit events")
    parser.add_argument("--store-layout", required=True, help="Path to store_layout.json")
    parser.add_argument("--video-dir", required=True, help="Directory containing video files")
    parser.add_argument("--output", default="data/events.jsonl", help="Output JSONL file")
    parser.add_argument("--base-date", default="2026-04-10", help="Base date for timestamps (YYYY-MM-DD)")
    parser.add_argument("--base-time", default="12:00:00", help="Base time for timestamps (HH:MM:SS)")
    
    args = parser.parse_args()
    
    # Load store layout
    with open(args.store_layout, 'r') as f:
        store_layout = json.load(f)
    
    store_id = store_layout['store_id']
    cameras = store_layout['cameras']
    
    # Parse base timestamp
    base_timestamp = datetime.fromisoformat(f"{args.base_date}T{args.base_time}")
    
    # Initialize processor
    processor = CCTVProcessor()
    
    # Process each camera
    with EventEmitter(args.output) as emitter:
        for cam_key, cam_info in cameras.items():
            video_file = Path(args.video_dir) / cam_info['file']
            
            if not video_file.exists():
                print(f"Warning: Video file not found: {video_file}")
                continue
            
            # Determine camera role and zone
            role = cam_info['role']
            
            # Map role to zone_id
            zone_mapping = {
                'entry': 'ENTRY',
                'floor': 'SKINCARE',  # Default, will be overridden
                'billing': 'BILLING'
            }
            
            zone_id = zone_mapping.get(role, 'UNKNOWN')
            
            # For floor cameras, determine zone from layout
            if role == 'floor':
                for zone in store_layout.get('zones', []):
                    if zone.get('camera') == cam_key:
                        zone_id = zone['zone_id']
                        break
            
            processor.process_video(
                video_path=str(video_file),
                camera_id=cam_key,
                store_id=store_id,
                camera_role=role,
                zone_id=zone_id,
                emitter=emitter,
                base_timestamp=base_timestamp
            )
        
        print(f"\nTotal events emitted: {emitter.get_event_count()}")
        print(f"Events saved to: {args.output}")


if __name__ == "__main__":
    main()
