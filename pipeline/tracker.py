"""Re-ID and tracking logic for visitor identification."""

import numpy as np
from typing import Dict, Set, Optional
from datetime import datetime, timedelta


class VisitorTracker:
    """Tracks visitors across frames and handles Re-ID."""
    
    def __init__(self):
        self.active_tracks: Dict[int, Dict] = {}  # track_id -> track_info
        self.visitor_mapping: Dict[int, str] = {}  # track_id -> visitor_id
        self.exited_visitors: Set[str] = set()  # visitor_ids that have exited
        self.visitor_counter = 0
        self.staff_tracks: Set[int] = set()  # track_ids identified as staff
        
    def update_track(
        self, 
        track_id: int, 
        bbox: np.ndarray, 
        confidence: float,
        frame_time: datetime
    ) -> str:
        """
        Update track information and return visitor_id.
        
        Args:
            track_id: Tracking ID from ByteTrack
            bbox: Bounding box [x1, y1, x2, y2]
            confidence: Detection confidence
            frame_time: Timestamp of current frame
        
        Returns:
            visitor_id string
        """
        # Check if this is a new track
        if track_id not in self.active_tracks:
            # Check if this might be a re-entry
            visitor_id = self._check_reentry(bbox, frame_time)
            
            if visitor_id is None:
                # New visitor
                self.visitor_counter += 1
                visitor_id = f"VIS_{self.visitor_counter:06d}"
            
            self.visitor_mapping[track_id] = visitor_id
            self.active_tracks[track_id] = {
                'visitor_id': visitor_id,
                'first_seen': frame_time,
                'last_seen': frame_time,
                'bbox_history': [bbox],
                'confidence_history': [confidence],
                'frame_count': 1
            }
        else:
            # Update existing track
            visitor_id = self.visitor_mapping[track_id]
            track_info = self.active_tracks[track_id]
            track_info['last_seen'] = frame_time
            track_info['bbox_history'].append(bbox)
            track_info['confidence_history'].append(confidence)
            track_info['frame_count'] += 1
            
            # Keep only last 30 frames of history
            if len(track_info['bbox_history']) > 30:
                track_info['bbox_history'] = track_info['bbox_history'][-30:]
                track_info['confidence_history'] = track_info['confidence_history'][-30:]
        
        return visitor_id
    
    def _check_reentry(self, bbox: np.ndarray, frame_time: datetime) -> Optional[str]:
        """
        Check if this detection might be a re-entry of a previous visitor.
        
        Simple heuristic: if a visitor exited within last 2 minutes and
        new detection appears in similar location, consider it a re-entry.
        
        Returns:
            visitor_id if re-entry detected, None otherwise
        """
        # For now, return None (no re-entry detection)
        # In production, this would use appearance features or more sophisticated Re-ID
        return None
    
    def mark_exit(self, track_id: int) -> Optional[str]:
        """
        Mark a track as exited.
        
        Returns:
            visitor_id of the exited track
        """
        if track_id in self.visitor_mapping:
            visitor_id = self.visitor_mapping[track_id]
            self.exited_visitors.add(visitor_id)
            
            # Clean up old track data
            if track_id in self.active_tracks:
                del self.active_tracks[track_id]
            
            return visitor_id
        
        return None
    
    def is_staff(self, track_id: int) -> bool:
        """
        Determine if a track belongs to staff.
        
        Heuristic: If a track has been present for more than 10 minutes
        continuously, classify as staff.
        
        Args:
            track_id: Tracking ID
        
        Returns:
            True if staff, False otherwise
        """
        if track_id in self.staff_tracks:
            return True
        
        if track_id in self.active_tracks:
            track_info = self.active_tracks[track_id]
            duration = (track_info['last_seen'] - track_info['first_seen']).total_seconds()
            
            # If present for more than 10 minutes, mark as staff
            if duration > 600:  # 10 minutes
                self.staff_tracks.add(track_id)
                return True
        
        return False
    
    def get_track_info(self, track_id: int) -> Optional[Dict]:
        """Get information about a track."""
        return self.active_tracks.get(track_id)
    
    def cleanup_stale_tracks(self, current_time: datetime, timeout_seconds: int = 30):
        """Remove tracks that haven't been seen recently."""
        stale_tracks = []
        
        for track_id, track_info in self.active_tracks.items():
            time_since_seen = (current_time - track_info['last_seen']).total_seconds()
            if time_since_seen > timeout_seconds:
                stale_tracks.append(track_id)
        
        for track_id in stale_tracks:
            self.mark_exit(track_id)
