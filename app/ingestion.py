"""Event ingestion logic with idempotency and validation."""

import structlog
from datetime import datetime
from typing import List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models import Event, EventSchema

logger = structlog.get_logger()


class EventIngestionService:
    """Service for ingesting and validating events."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def ingest_events(
        self, 
        events: List[EventSchema],
        trace_id: str
    ) -> Tuple[int, int, List[Dict[str, Any]]]:
        """
        Ingest a batch of events with idempotency.
        
        Returns:
            Tuple of (success_count, failed_count, errors)
        """
        success_count = 0
        failed_count = 0
        errors = []
        
        for event in events:
            try:
                # Check if event already exists (idempotency)
                existing = self.db.query(Event).filter(
                    Event.event_id == event.event_id
                ).first()
                
                if existing:
                    logger.info(
                        "event_already_exists",
                        event_id=event.event_id,
                        trace_id=trace_id
                    )
                    success_count += 1  # Idempotent - count as success
                    continue
                
                # Create new event
                db_event = Event(
                    event_id=event.event_id,
                    store_id=event.store_id,
                    camera_id=event.camera_id,
                    visitor_id=event.visitor_id,
                    event_type=event.event_type,
                    timestamp=event.timestamp,
                    zone_id=event.zone_id,
                    dwell_ms=event.dwell_ms,
                    is_staff=event.is_staff,
                    confidence=event.confidence,
                    event_metadata=event.metadata.model_dump() if event.metadata else None,
                    created_at=datetime.utcnow()
                )
                
                self.db.add(db_event)
                self.db.commit()
                
                success_count += 1
                
                logger.info(
                    "event_ingested",
                    event_id=event.event_id,
                    store_id=event.store_id,
                    event_type=event.event_type,
                    trace_id=trace_id
                )
                
            except IntegrityError as e:
                self.db.rollback()
                failed_count += 1
                error_detail = {
                    "event_id": event.event_id,
                    "error": "duplicate_key",
                    "message": str(e)
                }
                errors.append(error_detail)
                
                logger.warning(
                    "event_ingestion_failed",
                    event_id=event.event_id,
                    error="integrity_error",
                    trace_id=trace_id
                )
                
            except Exception as e:
                self.db.rollback()
                failed_count += 1
                error_detail = {
                    "event_id": event.event_id,
                    "error": "ingestion_failed",
                    "message": str(e)
                }
                errors.append(error_detail)
                
                logger.error(
                    "event_ingestion_error",
                    event_id=event.event_id,
                    error=str(e),
                    trace_id=trace_id
                )
        
        return success_count, failed_count, errors
    
    def validate_event_schema(self, event_data: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Validate event data against schema.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        required_fields = [
            'event_id', 'store_id', 'camera_id', 'visitor_id',
            'event_type', 'timestamp', 'confidence'
        ]
        
        for field in required_fields:
            if field not in event_data:
                return False, f"Missing required field: {field}"
        
        # Validate event_type
        valid_types = [
            'ENTRY', 'EXIT', 'ZONE_ENTER', 'ZONE_EXIT', 'ZONE_DWELL',
            'BILLING_QUEUE_JOIN', 'BILLING_QUEUE_ABANDON', 'REENTRY'
        ]
        if event_data['event_type'] not in valid_types:
            return False, f"Invalid event_type: {event_data['event_type']}"
        
        # Validate confidence
        confidence = event_data.get('confidence', 0)
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            return False, "confidence must be between 0 and 1"
        
        return True, ""
    
    def get_event_count(self, store_id: str, start_date: datetime, end_date: datetime) -> int:
        """Get count of events for a store in a date range."""
        return self.db.query(Event).filter(
            Event.store_id == store_id,
            Event.timestamp >= start_date,
            Event.timestamp < end_date,
            Event.is_staff == False
        ).count()
    
    def get_unique_visitors(self, store_id: str, start_date: datetime, end_date: datetime) -> int:
        """Get count of unique visitors (excluding staff) for a store in a date range."""
        return self.db.query(Event.visitor_id).filter(
            Event.store_id == store_id,
            Event.timestamp >= start_date,
            Event.timestamp < end_date,
            Event.is_staff == False
        ).distinct().count()
