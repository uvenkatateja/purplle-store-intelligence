"""Anomaly detection for operational issues."""

import structlog
from datetime import datetime, timedelta
from typing import List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import Event, Anomaly

logger = structlog.get_logger()


class AnomalyDetectionService:
    """Service for detecting operational anomalies."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def detect_anomalies(self, store_id: str) -> List[Dict]:
        """
        Detect active anomalies for a store.
        
        Detects:
        - BILLING_QUEUE_SPIKE: Unusual queue buildup
        - DEAD_ZONE: No visits in 30+ minutes
        - CONVERSION_DROP: Conversion rate below 7-day average
        
        Args:
            store_id: Store identifier
        
        Returns:
            List of detected anomalies
        """
        anomalies = []
        now = datetime.utcnow()
        
        # Detect queue spike
        queue_anomaly = self._detect_queue_spike(store_id, now)
        if queue_anomaly:
            anomalies.append(queue_anomaly)
        
        # Detect dead zones
        dead_zone_anomalies = self._detect_dead_zones(store_id, now)
        anomalies.extend(dead_zone_anomalies)
        
        # Detect conversion drop
        conversion_anomaly = self._detect_conversion_drop(store_id, now)
        if conversion_anomaly:
            anomalies.append(conversion_anomaly)
        
        logger.info(
            "anomalies_detected",
            store_id=store_id,
            anomaly_count=len(anomalies)
        )
        
        return anomalies
    
    def _detect_queue_spike(self, store_id: str, now: datetime) -> Dict:
        """Detect unusual billing queue buildup."""
        # Get most recent queue depth
        recent_queue_event = self.db.query(Event).filter(
            Event.store_id == store_id,
            Event.event_type == 'BILLING_QUEUE_JOIN',
            Event.timestamp >= now - timedelta(minutes=10)
        ).order_by(Event.timestamp.desc()).first()
        
        if not recent_queue_event or not recent_queue_event.event_metadata:
            return None
        
        queue_depth = recent_queue_event.event_metadata.get('queue_depth', 0)
        
        # Threshold: queue depth > 5 is considered a spike
        if queue_depth > 5:
            return {
                "anomaly_type": "BILLING_QUEUE_SPIKE",
                "severity": "CRITICAL" if queue_depth > 10 else "WARN",
                "description": f"Billing queue depth at {queue_depth} customers",
                "suggested_action": "Open additional billing counter or expedite checkout process",
                "detected_at": now
            }
        
        return None
    
    def _detect_dead_zones(self, store_id: str, now: datetime) -> List[Dict]:
        """Detect zones with no visits in the last 30 minutes."""
        threshold_time = now - timedelta(minutes=30)
        
        # Get all zones
        all_zones = ['SKINCARE', 'MAKEUP', 'HAIRCARE', 'BODYCARE', 'BILLING']
        
        # Get zones with recent activity
        active_zones = self.db.query(Event.zone_id).filter(
            Event.store_id == store_id,
            Event.timestamp >= threshold_time,
            Event.zone_id.in_(all_zones),
            Event.is_staff == False
        ).distinct().all()
        
        active_zone_ids = set(zone_id for (zone_id,) in active_zones if zone_id)
        
        # Find dead zones
        dead_zones = set(all_zones) - active_zone_ids
        
        anomalies = []
        for zone in dead_zones:
            # Check if zone had activity earlier today (to avoid false positives)
            today_start = datetime.combine(now.date(), datetime.min.time())
            earlier_activity = self.db.query(Event).filter(
                Event.store_id == store_id,
                Event.zone_id == zone,
                Event.timestamp >= today_start,
                Event.timestamp < threshold_time,
                Event.is_staff == False
            ).first()
            
            # Only flag as anomaly if zone had earlier activity
            if earlier_activity:
                anomalies.append({
                    "anomaly_type": "DEAD_ZONE",
                    "severity": "INFO",
                    "description": f"Zone {zone} has no customer activity in last 30 minutes",
                    "suggested_action": f"Check if {zone} zone is accessible and well-lit",
                    "detected_at": now
                })
        
        return anomalies
    
    def _detect_conversion_drop(self, store_id: str, now: datetime) -> Dict:
        """Detect conversion rate drop compared to 7-day average."""
        # Get today's conversion rate
        today_start = datetime.combine(now.date(), datetime.min.time())
        today_end = now
        
        today_visitors = self.db.query(Event.visitor_id).filter(
            Event.store_id == store_id,
            Event.timestamp >= today_start,
            Event.timestamp <= today_end,
            Event.is_staff == False
        ).distinct().count()
        
        if today_visitors == 0:
            return None
        
        # Get converted visitors today
        today_converted = self._get_converted_count(store_id, today_start, today_end)
        today_conversion_rate = today_converted / today_visitors if today_visitors > 0 else 0
        
        # Get 7-day average conversion rate
        seven_days_ago = now - timedelta(days=7)
        avg_conversion_rate = self._get_avg_conversion_rate(store_id, seven_days_ago, today_start)
        
        if avg_conversion_rate == 0:
            return None
        
        # Detect if today's rate is significantly lower (>30% drop)
        drop_threshold = 0.7  # 30% drop
        if today_conversion_rate < (avg_conversion_rate * drop_threshold):
            drop_pct = ((avg_conversion_rate - today_conversion_rate) / avg_conversion_rate) * 100
            
            return {
                "anomaly_type": "CONVERSION_DROP",
                "severity": "WARN",
                "description": f"Conversion rate {drop_pct:.1f}% below 7-day average ({today_conversion_rate:.2%} vs {avg_conversion_rate:.2%})",
                "suggested_action": "Review customer experience, check for operational issues or staff availability",
                "detected_at": now
            }
        
        return None
    
    def _get_converted_count(self, store_id: str, start_time: datetime, end_time: datetime) -> int:
        """Get count of converted visitors in time range."""
        import os
        import pandas as pd
        POS_CANDIDATES = [
            "data/pos_transactions.csv",
            "data/Brigade_Bangalore_10_April_26 (1)bc6219c (1).csv",
            "data/Brigade_Bangalore_10_April_26.csv",
        ]
        POS_ALIASES = ["STORE_BLR_001", "ST1008", "Brigade_Bangalore"]

        try:
            pos_df = None
            for path in POS_CANDIDATES:
                if os.path.exists(path):
                    pos_df = pd.read_csv(path)
                    break
            if pos_df is None:
                return 0

            pos_df['transaction_time'] = pd.to_datetime(
                pos_df['order_date'] + ' ' + pos_df['order_time'],
                dayfirst=True
            )
            store_transactions = pos_df[
                pos_df['store_id'].isin(POS_ALIASES) &
                (pos_df['transaction_time'] >= start_time) &
                (pos_df['transaction_time'] <= end_time)
            ]

            if store_transactions.empty:
                return 0

            # Use all events as candidates (billing cam was empty)
            candidate_events = self.db.query(Event).filter(
                Event.store_id == store_id,
                Event.timestamp >= start_time,
                Event.timestamp <= end_time,
                Event.is_staff == False
            ).all()

            converted_visitors = set()
            for _, txn in store_transactions.iterrows():
                txn_time = txn['transaction_time']
                if hasattr(txn_time, 'tzinfo') and txn_time.tzinfo is not None:
                    txn_time = txn_time.replace(tzinfo=None)
                window_start = txn_time - timedelta(minutes=5)
                for event in candidate_events:
                    evt_ts = event.timestamp
                    if hasattr(evt_ts, 'tzinfo') and evt_ts.tzinfo is not None:
                        evt_ts = evt_ts.replace(tzinfo=None)
                    if window_start <= evt_ts <= txn_time:
                        converted_visitors.add(event.visitor_id)

            return len(converted_visitors)

        except Exception as e:
            logger.error("converted_count_error", error=str(e))
            return 0
    
    def _get_avg_conversion_rate(self, store_id: str, start_time: datetime, end_time: datetime) -> float:
        """Calculate average conversion rate over a time period."""
        total_visitors = self.db.query(Event.visitor_id).filter(
            Event.store_id == store_id,
            Event.timestamp >= start_time,
            Event.timestamp < end_time,
            Event.is_staff == False
        ).distinct().count()
        
        if total_visitors == 0:
            return 0.0
        
        converted = self._get_converted_count(store_id, start_time, end_time)
        
        return converted / total_visitors
