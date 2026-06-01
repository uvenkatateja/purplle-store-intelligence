"""Health check endpoint for monitoring."""

import structlog
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import Event

logger = structlog.get_logger()


class HealthService:
    """Service for health checks and system monitoring."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_health_status(self) -> Dict:
        """
        Get system health status.
        
        Returns:
            Health status with last event timestamps and stale feed warnings
        """
        try:
            # Get last event timestamp per store
            last_events = self.db.query(
                Event.store_id,
                func.max(Event.timestamp).label('last_timestamp')
            ).group_by(Event.store_id).all()
            
            last_event_per_store = {}
            stale_feeds = []
            now = datetime.utcnow()
            stale_threshold = now - timedelta(minutes=10)
            
            for store_id, last_timestamp in last_events:
                last_event_per_store[store_id] = last_timestamp
                
                # Check if feed is stale (>10 minutes old)
                if last_timestamp and last_timestamp < stale_threshold:
                    stale_feeds.append(store_id)
            
            status = "healthy" if not stale_feeds else "degraded"
            
            logger.info(
                "health_check",
                status=status,
                stale_feed_count=len(stale_feeds)
            )
            
            return {
                "status": status,
                "last_event_per_store": last_event_per_store,
                "stale_feeds": stale_feeds,
                "checked_at": now
            }
            
        except Exception as e:
            logger.error("health_check_failed", error=str(e))
            return {
                "status": "unhealthy",
                "error": str(e),
                "checked_at": datetime.utcnow()
            }
    
    def check_database_connection(self) -> bool:
        """Check if database is accessible."""
        try:
            from sqlalchemy import text
            self.db.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error("database_connection_failed", error=str(e))
            return False
    
    def get_system_stats(self) -> Dict:
        """Get system statistics."""
        try:
            total_events = self.db.query(func.count(Event.event_id)).scalar()
            total_stores = self.db.query(func.count(Event.store_id.distinct())).scalar()
            total_visitors = self.db.query(func.count(Event.visitor_id.distinct())).scalar()
            
            # Get event counts by type
            event_type_counts = self.db.query(
                Event.event_type,
                func.count(Event.event_id).label('count')
            ).group_by(Event.event_type).all()
            
            event_types = {event_type: count for event_type, count in event_type_counts}
            
            return {
                "total_events": total_events,
                "total_stores": total_stores,
                "total_visitors": total_visitors,
                "event_types": event_types
            }
            
        except Exception as e:
            logger.error("system_stats_failed", error=str(e))
            return {}
