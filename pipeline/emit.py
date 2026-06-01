"""Event schema and emission to JSONL."""

import json
import uuid
from datetime import datetime
from typing import Dict, Optional, TextIO
from pathlib import Path


class EventEmitter:
    """Emits structured events to JSONL file."""
    
    def __init__(self, output_path: str):
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_handle: Optional[TextIO] = None
        self.event_count = 0
        
    def __enter__(self):
        self.file_handle = open(self.output_path, 'w', encoding='utf-8')
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.file_handle:
            self.file_handle.close()
    
    def emit_event(
        self,
        store_id: str,
        camera_id: str,
        visitor_id: str,
        event_type: str,
        timestamp: datetime,
        zone_id: Optional[str] = None,
        dwell_ms: int = 0,
        is_staff: bool = False,
        confidence: float = 0.0,
        metadata: Optional[Dict] = None
    ):
        """
        Emit a structured event.
        
        Args:
            store_id: Store identifier
            camera_id: Camera identifier
            visitor_id: Visitor identifier
            event_type: Type of event (ENTRY, EXIT, ZONE_DWELL, etc.)
            timestamp: Event timestamp
            zone_id: Zone identifier (optional)
            dwell_ms: Dwell time in milliseconds
            is_staff: Whether this is a staff member
            confidence: Detection confidence (0-1)
            metadata: Additional metadata
        """
        event = {
            "event_id": str(uuid.uuid4()),
            "store_id": store_id,
            "camera_id": camera_id,
            "visitor_id": visitor_id,
            "event_type": event_type,
            "timestamp": timestamp.isoformat() + 'Z',
            "zone_id": zone_id,
            "dwell_ms": dwell_ms,
            "is_staff": is_staff,
            "confidence": round(confidence, 4),
            "metadata": metadata or {}
        }
        
        if self.file_handle:
            self.file_handle.write(json.dumps(event) + '\n')
            self.file_handle.flush()
            self.event_count += 1
    
    def get_event_count(self) -> int:
        """Get total number of events emitted."""
        return self.event_count


def validate_event_schema(event: Dict) -> bool:
    """
    Validate event against required schema.
    
    Args:
        event: Event dictionary
    
    Returns:
        True if valid, False otherwise
    """
    required_fields = [
        'event_id', 'store_id', 'camera_id', 'visitor_id',
        'event_type', 'timestamp', 'confidence'
    ]
    
    for field in required_fields:
        if field not in event:
            return False
    
    valid_event_types = [
        'ENTRY', 'EXIT', 'ZONE_ENTER', 'ZONE_EXIT', 'ZONE_DWELL',
        'BILLING_QUEUE_JOIN', 'BILLING_QUEUE_ABANDON', 'REENTRY'
    ]
    
    if event['event_type'] not in valid_event_types:
        return False
    
    if not isinstance(event['confidence'], (int, float)) or not 0 <= event['confidence'] <= 1:
        return False
    
    return True
