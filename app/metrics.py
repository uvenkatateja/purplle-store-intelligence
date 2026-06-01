"""Real-time metrics computation for store analytics."""

import structlog
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import Event

logger = structlog.get_logger()


class MetricsService:
    """Service for computing real-time store metrics."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_store_metrics(self, store_id: str, date: Optional[datetime] = None) -> Dict:
        """
        Compute real-time metrics for a store.
        
        Args:
            store_id: Store identifier
            date: Date for metrics (defaults to today)
        
        Returns:
            Dictionary with metrics
        """
        if date is None:
            date = datetime.utcnow().date()
        
        start_time = datetime.combine(date, datetime.min.time())
        end_time = datetime.combine(date, datetime.max.time())
        
        # Get unique visitors (excluding staff)
        unique_visitors = self.db.query(Event.visitor_id).filter(
            Event.store_id == store_id,
            Event.timestamp >= start_time,
            Event.timestamp <= end_time,
            Event.is_staff == False
        ).distinct().count()
        
        # Get converted visitors (those in BILLING zone)
        converted_visitors = self._get_converted_visitors(store_id, start_time, end_time)
        
        # Calculate conversion rate
        conversion_rate = (
            converted_visitors / unique_visitors if unique_visitors > 0 else 0.0
        )
        
        # Get average dwell per zone
        avg_dwell_per_zone = self._get_avg_dwell_per_zone(store_id, start_time, end_time)
        
        # Get current queue depth
        queue_depth = self._get_current_queue_depth(store_id)
        
        # Get abandonment rate
        abandonment_rate = self._get_abandonment_rate(store_id, start_time, end_time)
        
        logger.info(
            "metrics_computed",
            store_id=store_id,
            date=str(date),
            unique_visitors=unique_visitors,
            conversion_rate=conversion_rate
        )
        
        return {
            "store_id": store_id,
            "date": str(date),
            "unique_visitors": unique_visitors,
            "conversion_rate": round(conversion_rate, 4),
            "avg_dwell_per_zone": avg_dwell_per_zone,
            "queue_depth": queue_depth,
            "abandonment_rate": round(abandonment_rate, 4)
        }
    
    # Map logical store_id → POS store identifiers (handles real CSV having ST1008)
    POS_STORE_MAP = {
        "STORE_BLR_001": ["STORE_BLR_001", "ST1008", "Brigade_Bangalore"],
    }

    POS_FILE_CANDIDATES = [
        "data/pos_transactions.csv",
        "data/Brigade_Bangalore_10_April_26 (1)bc6219c (1).csv",
        "data/Brigade_Bangalore_10_April_26.csv",
    ]

    def _load_pos_df(self) -> pd.DataFrame:
        """Load POS CSV from whichever file exists."""
        import os
        for path in self.POS_FILE_CANDIDATES:
            if os.path.exists(path):
                df = pd.read_csv(path)
                # Normalise date: handles DD-MM-YYYY and YYYY-MM-DD
                try:
                    df['transaction_time'] = pd.to_datetime(
                        df['order_date'] + ' ' + df['order_time'],
                        dayfirst=True   # handles 10-04-2026
                    )
                except Exception:
                    df['transaction_time'] = pd.to_datetime(
                        df['order_date'] + ' ' + df['order_time']
                    )
                logger.info("pos_file_loaded", path=path, rows=len(df))
                return df
        logger.warning("no_pos_file_found")
        return pd.DataFrame()

    def _get_converted_visitors(
        self,
        store_id: str,
        start_time: datetime,
        end_time: datetime
    ) -> int:
        """
        Get count of visitors who made a purchase.

        Strategy 1 (preferred): visitor was in BILLING zone within 5 min before txn.
        Strategy 2 (fallback):  visitor was active in ANY zone within 5 min before txn
                                — used when billing camera has no detections (empty CAM 4).
        """
        try:
            pos_df = self._load_pos_df()
            if pos_df.empty:
                return 0

            # Accept any store alias
            aliases = self.POS_STORE_MAP.get(store_id, [store_id])
            store_txns = pos_df[
                pos_df['store_id'].isin(aliases) |
                pos_df.get('store_name', pd.Series(dtype=str)).isin(aliases)
            ]
            store_txns = store_txns[
                (store_txns['transaction_time'] >= start_time) &
                (store_txns['transaction_time'] <= end_time)
            ]

            if store_txns.empty:
                return 0

            # Strategy 1: billing zone events
            billing_events = self.db.query(Event).filter(
                Event.store_id == store_id,
                Event.zone_id == 'BILLING',
                Event.timestamp >= start_time,
                Event.timestamp <= end_time,
                Event.is_staff == False
            ).all()

            # Strategy 2 fallback: any customer event (when billing cam is empty)
            use_fallback = len(billing_events) == 0
            if use_fallback:
                logger.info("billing_zone_empty_using_fallback_correlation",
                            store_id=store_id)
                all_events = self.db.query(Event).filter(
                    Event.store_id == store_id,
                    Event.timestamp >= start_time,
                    Event.timestamp <= end_time,
                    Event.is_staff == False
                ).all()
                candidate_events = all_events
            else:
                candidate_events = billing_events

            converted_visitor_ids = set()
            for _, txn in store_txns.iterrows():
                txn_time = txn['transaction_time']
                # Make txn_time timezone-naive for comparison
                if hasattr(txn_time, 'tzinfo') and txn_time.tzinfo is not None:
                    txn_time = txn_time.replace(tzinfo=None)
                window_start = txn_time - timedelta(minutes=5)

                for event in candidate_events:
                    evt_ts = event.timestamp
                    if hasattr(evt_ts, 'tzinfo') and evt_ts.tzinfo is not None:
                        evt_ts = evt_ts.replace(tzinfo=None)
                    if window_start <= evt_ts <= txn_time:
                        converted_visitor_ids.add(event.visitor_id)

            return len(converted_visitor_ids)

        except FileNotFoundError:
            logger.warning("pos_transactions_file_not_found", store_id=store_id)
            return 0
        except Exception as e:
            logger.error("conversion_calculation_error", error=str(e), store_id=store_id)
            return 0
    
    def _get_avg_dwell_per_zone(
        self, 
        store_id: str, 
        start_time: datetime, 
        end_time: datetime
    ) -> Dict[str, float]:
        """Calculate average dwell time per zone in milliseconds."""
        dwell_events = self.db.query(
            Event.zone_id,
            func.avg(Event.dwell_ms).label('avg_dwell')
        ).filter(
            Event.store_id == store_id,
            Event.event_type == 'ZONE_DWELL',
            Event.timestamp >= start_time,
            Event.timestamp <= end_time,
            Event.is_staff == False,
            Event.zone_id.isnot(None)
        ).group_by(Event.zone_id).all()
        
        result = {}
        for zone_id, avg_dwell in dwell_events:
            result[zone_id] = round(avg_dwell, 2) if avg_dwell else 0.0
        
        return result
    
    def _get_current_queue_depth(self, store_id: str) -> int:
        """Get current queue depth in billing zone."""
        # Get the most recent BILLING_QUEUE_JOIN event
        latest_queue_event = self.db.query(Event).filter(
            Event.store_id == store_id,
            Event.event_type == 'BILLING_QUEUE_JOIN',
            Event.is_staff == False
        ).order_by(Event.timestamp.desc()).first()
        
        if latest_queue_event and latest_queue_event.event_metadata:
            return latest_queue_event.event_metadata.get('queue_depth', 0)
        
        return 0
    
    def _get_abandonment_rate(
        self, 
        store_id: str, 
        start_time: datetime, 
        end_time: datetime
    ) -> float:
        """Calculate billing queue abandonment rate."""
        # Count BILLING_QUEUE_JOIN events
        queue_joins = self.db.query(Event).filter(
            Event.store_id == store_id,
            Event.event_type == 'BILLING_QUEUE_JOIN',
            Event.timestamp >= start_time,
            Event.timestamp <= end_time,
            Event.is_staff == False
        ).count()
        
        # Count BILLING_QUEUE_ABANDON events
        queue_abandons = self.db.query(Event).filter(
            Event.store_id == store_id,
            Event.event_type == 'BILLING_QUEUE_ABANDON',
            Event.timestamp >= start_time,
            Event.timestamp <= end_time,
            Event.is_staff == False
        ).count()
        
        if queue_joins == 0:
            return 0.0
        
        return queue_abandons / queue_joins
    
    def get_zone_visit_counts(
        self, 
        store_id: str, 
        start_time: datetime, 
        end_time: datetime
    ) -> Dict[str, int]:
        """Get visit counts per zone."""
        zone_visits = self.db.query(
            Event.zone_id,
            func.count(Event.visitor_id.distinct()).label('visit_count')
        ).filter(
            Event.store_id == store_id,
            Event.event_type.in_(['ZONE_ENTER', 'ZONE_DWELL']),
            Event.timestamp >= start_time,
            Event.timestamp <= end_time,
            Event.is_staff == False,
            Event.zone_id.isnot(None)
        ).group_by(Event.zone_id).all()
        
        result = {}
        for zone_id, count in zone_visits:
            result[zone_id] = count
        
        return result
