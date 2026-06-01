"""Conversion funnel logic with session-based tracking."""

import os
import structlog
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Set
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import Event, FunnelStage

logger = structlog.get_logger()


class FunnelService:
    """Service for computing conversion funnel metrics."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_conversion_funnel(self, store_id: str, date: datetime) -> List[Dict]:
        """
        Compute conversion funnel: Entry → Zone Visit → Billing Zone → Purchase.

        Note: Because cameras assign independent visitor IDs (no cross-camera Re-ID),
        we use ALL unique customer visitor_ids as the entry population, not just
        those with explicit ENTRY events. This gives a more accurate funnel.
        """
        start_time = datetime.combine(date, datetime.min.time())
        end_time = datetime.combine(date, datetime.max.time())

        # Stage 1: All unique customer visitors seen on any camera
        all_visitors = self._get_all_visitors(store_id, start_time, end_time)

        # Stage 2: Visitors who visited at least one product zone
        zone_visitors = self._get_zone_visitors(store_id, start_time, end_time, all_visitors)

        # Stage 3: Visitors who reached billing
        billing_visitors = self._get_billing_visitors(store_id, start_time, end_time, all_visitors)

        # Stage 4: Visitors who completed a purchase
        purchase_visitors = self._get_purchase_visitors(store_id, start_time, end_time, all_visitors)

        total_visitors = len(all_visitors)

        funnel = [
            {
                "stage": "Entry",
                "visitor_count": total_visitors,
                "drop_off_pct": 0.0
            },
            {
                "stage": "Zone Visit",
                "visitor_count": len(zone_visitors),
                "drop_off_pct": self._calculate_dropoff(total_visitors, len(zone_visitors))
            },
            {
                "stage": "Billing Zone",
                "visitor_count": len(billing_visitors),
                "drop_off_pct": self._calculate_dropoff(len(zone_visitors) or total_visitors, len(billing_visitors))
            },
            {
                "stage": "Purchase",
                "visitor_count": len(purchase_visitors),
                "drop_off_pct": self._calculate_dropoff(len(billing_visitors) or total_visitors, len(purchase_visitors))
            }
        ]

        logger.info(
            "funnel_computed",
            store_id=store_id,
            date=str(date),
            entry=total_visitors,
            zone_visit=len(zone_visitors),
            billing=len(billing_visitors),
            purchase=len(purchase_visitors)
        )

        return funnel
    
    def _get_all_visitors(
        self,
        store_id: str,
        start_time: datetime,
        end_time: datetime
    ) -> set:
        """Get ALL unique customer visitor_ids seen on any camera."""
        rows = self.db.query(Event.visitor_id).filter(
            Event.store_id == store_id,
            Event.timestamp >= start_time,
            Event.timestamp <= end_time,
            Event.is_staff == False
        ).distinct().all()
        return set(r[0] for r in rows)

    def _get_entry_visitors(
        self, 
        store_id: str, 
        start_time: datetime, 
        end_time: datetime
    ) -> Set[str]:
        """Get unique visitors who entered the store (excluding re-entries)."""
        # Get all ENTRY events (not REENTRY)
        entry_events = self.db.query(Event.visitor_id).filter(
            Event.store_id == store_id,
            Event.event_type == 'ENTRY',
            Event.timestamp >= start_time,
            Event.timestamp <= end_time,
            Event.is_staff == False
        ).distinct().all()
        
        return set(visitor_id for (visitor_id,) in entry_events)
    
    def _get_zone_visitors(
        self,
        store_id: str,
        start_time: datetime,
        end_time: datetime,
        all_visitors: set
    ) -> set:
        """Get visitors who visited at least one product zone."""
        product_zones = ['SKINCARE', 'MAKEUP', 'HAIRCARE', 'BODYCARE']

        zone_events = self.db.query(Event.visitor_id).filter(
            Event.store_id == store_id,
            Event.event_type.in_(['ZONE_ENTER', 'ZONE_DWELL']),
            Event.zone_id.in_(product_zones),
            Event.timestamp >= start_time,
            Event.timestamp <= end_time,
            Event.is_staff == False
        ).distinct().all()

        return set(r[0] for r in zone_events)

    def _get_billing_visitors(
        self,
        store_id: str,
        start_time: datetime,
        end_time: datetime,
        all_visitors: set
    ) -> set:
        """Get visitors who reached the billing zone."""
        billing_events = self.db.query(Event.visitor_id).filter(
            Event.store_id == store_id,
            Event.zone_id == 'BILLING',
            Event.timestamp >= start_time,
            Event.timestamp <= end_time,
            Event.is_staff == False
        ).distinct().all()

        return set(r[0] for r in billing_events)
    
    def _get_purchase_visitors(
        self,
        store_id: str,
        start_time: datetime,
        end_time: datetime,
        entry_visitors: set
    ) -> set:
        """
        Get visitors who completed a purchase.
        Billing zone within 5 min before txn (fallback: any zone if billing empty).
        """
        import os
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
                return set()

            pos_df['transaction_time'] = pd.to_datetime(
                pos_df['order_date'] + ' ' + pos_df['order_time'],
                dayfirst=True
            )
            store_transactions = pos_df[
                (pos_df['store_id'].isin(POS_ALIASES) |
                 pos_df.get('store_name', pd.Series(dtype=str)).isin(POS_ALIASES)) &
                (pos_df['transaction_time'] >= start_time) &
                (pos_df['transaction_time'] <= end_time)
            ]

            if store_transactions.empty:
                return set()

            # Prefer billing zone; fallback to any zone
            billing_events = self.db.query(Event).filter(
                Event.store_id == store_id,
                Event.zone_id == 'BILLING',
                Event.timestamp >= start_time,
                Event.timestamp <= end_time,
                Event.is_staff == False,
                Event.visitor_id.in_(entry_visitors)
            ).all()

            if not billing_events:
                billing_events = self.db.query(Event).filter(
                    Event.store_id == store_id,
                    Event.timestamp >= start_time,
                    Event.timestamp <= end_time,
                    Event.is_staff == False,
                    Event.visitor_id.in_(entry_visitors)
                ).all()

            purchase_visitors = set()
            for _, txn in store_transactions.iterrows():
                txn_time = txn['transaction_time']
                if hasattr(txn_time, 'tzinfo') and txn_time.tzinfo is not None:
                    txn_time = txn_time.replace(tzinfo=None)
                window_start = txn_time - timedelta(minutes=5)
                for event in billing_events:
                    evt_ts = event.timestamp
                    if hasattr(evt_ts, 'tzinfo') and evt_ts.tzinfo is not None:
                        evt_ts = evt_ts.replace(tzinfo=None)
                    if window_start <= evt_ts <= txn_time:
                        purchase_visitors.add(event.visitor_id)

            return purchase_visitors

        except Exception as e:
            logger.error("purchase_visitor_error", error=str(e), store_id=store_id)
            return set()
    
    def _calculate_dropoff(self, previous_count: int, current_count: int) -> float:
        """Calculate drop-off percentage between funnel stages."""
        if previous_count == 0:
            return 0.0
        
        dropoff = ((previous_count - current_count) / previous_count) * 100
        return round(dropoff, 2)
