# PROMPT: Generate pytest tests for anomaly detection service including:
# - BILLING_QUEUE_SPIKE detection at various thresholds
# - DEAD_ZONE detection when no activity for 30+ minutes
# - CONVERSION_DROP detection vs 7-day average
# - Severity levels (INFO, WARN, CRITICAL)
# - Edge cases: no events, all staff events, empty store
#
# CHANGES MADE:
# - Added test for CRITICAL severity when queue_depth > 10
# - Fixed dead zone test to require prior activity (avoids false positives on new stores)
# - Added test for suggested_action field presence on all anomalies
# - Included test for no anomalies when store is operating normally

import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from models import Base, Event
from anomalies import AnomalyDetectionService


@pytest.fixture
def test_db():
    """Create test database."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    yield db
    db.close()


class TestQueueSpikeDetection:
    """Test BILLING_QUEUE_SPIKE anomaly detection."""

    def test_no_spike_when_queue_normal(self, test_db):
        """Test no anomaly when queue depth is normal."""
        base_time = datetime.utcnow() - timedelta(minutes=5)

        event = Event(
            event_id="evt_q1",
            store_id="STORE_BLR_001",
            camera_id="CAM_BILLING_01",
            visitor_id="VIS_000001",
            event_type="BILLING_QUEUE_JOIN",
            timestamp=base_time,
            zone_id="BILLING",
            is_staff=False,
            confidence=0.95,
            event_metadata={"queue_depth": 2}
        )
        test_db.add(event)
        test_db.commit()

        service = AnomalyDetectionService(test_db)
        anomalies = service.detect_anomalies("STORE_BLR_001")

        queue_anomalies = [a for a in anomalies if a["anomaly_type"] == "BILLING_QUEUE_SPIKE"]
        assert len(queue_anomalies) == 0

    def test_warn_spike_when_queue_high(self, test_db):
        """Test WARN severity when queue depth is 6-10."""
        base_time = datetime.utcnow() - timedelta(minutes=2)

        event = Event(
            event_id="evt_q2",
            store_id="STORE_BLR_001",
            camera_id="CAM_BILLING_01",
            visitor_id="VIS_000001",
            event_type="BILLING_QUEUE_JOIN",
            timestamp=base_time,
            zone_id="BILLING",
            is_staff=False,
            confidence=0.95,
            event_metadata={"queue_depth": 7}
        )
        test_db.add(event)
        test_db.commit()

        service = AnomalyDetectionService(test_db)
        anomalies = service.detect_anomalies("STORE_BLR_001")

        queue_anomalies = [a for a in anomalies if a["anomaly_type"] == "BILLING_QUEUE_SPIKE"]
        assert len(queue_anomalies) == 1
        assert queue_anomalies[0]["severity"] == "WARN"

    def test_critical_spike_when_queue_very_high(self, test_db):
        """Test CRITICAL severity when queue depth > 10."""
        base_time = datetime.utcnow() - timedelta(minutes=2)

        event = Event(
            event_id="evt_q3",
            store_id="STORE_BLR_001",
            camera_id="CAM_BILLING_01",
            visitor_id="VIS_000001",
            event_type="BILLING_QUEUE_JOIN",
            timestamp=base_time,
            zone_id="BILLING",
            is_staff=False,
            confidence=0.95,
            event_metadata={"queue_depth": 12}
        )
        test_db.add(event)
        test_db.commit()

        service = AnomalyDetectionService(test_db)
        anomalies = service.detect_anomalies("STORE_BLR_001")

        queue_anomalies = [a for a in anomalies if a["anomaly_type"] == "BILLING_QUEUE_SPIKE"]
        assert len(queue_anomalies) == 1
        assert queue_anomalies[0]["severity"] == "CRITICAL"

    def test_anomaly_has_suggested_action(self, test_db):
        """Test that every anomaly includes a suggested_action."""
        base_time = datetime.utcnow() - timedelta(minutes=2)

        event = Event(
            event_id="evt_q4",
            store_id="STORE_BLR_001",
            camera_id="CAM_BILLING_01",
            visitor_id="VIS_000001",
            event_type="BILLING_QUEUE_JOIN",
            timestamp=base_time,
            zone_id="BILLING",
            is_staff=False,
            confidence=0.95,
            event_metadata={"queue_depth": 8}
        )
        test_db.add(event)
        test_db.commit()

        service = AnomalyDetectionService(test_db)
        anomalies = service.detect_anomalies("STORE_BLR_001")

        for anomaly in anomalies:
            assert "suggested_action" in anomaly
            assert len(anomaly["suggested_action"]) > 0


class TestDeadZoneDetection:
    """Test DEAD_ZONE anomaly detection."""

    def test_dead_zone_detected_after_prior_activity(self, test_db):
        """Test dead zone flagged only when zone had earlier activity."""
        now = datetime.utcnow()

        # Earlier activity in SKINCARE (>30 min ago)
        early_event = Event(
            event_id="evt_dz1",
            store_id="STORE_BLR_001",
            camera_id="CAM_FLOOR_01",
            visitor_id="VIS_000001",
            event_type="ZONE_ENTER",
            timestamp=now - timedelta(minutes=45),
            zone_id="SKINCARE",
            is_staff=False,
            confidence=0.95
        )
        test_db.add(early_event)
        test_db.commit()

        service = AnomalyDetectionService(test_db)
        anomalies = service.detect_anomalies("STORE_BLR_001")

        dead_zone_anomalies = [a for a in anomalies if a["anomaly_type"] == "DEAD_ZONE"]
        skincare_dead = [a for a in dead_zone_anomalies if "SKINCARE" in a["description"]]
        assert len(skincare_dead) >= 1

    def test_no_dead_zone_with_recent_activity(self, test_db):
        """Test no dead zone when zone has recent activity."""
        now = datetime.utcnow()

        # Recent activity in SKINCARE (5 min ago)
        recent_event = Event(
            event_id="evt_dz2",
            store_id="STORE_BLR_001",
            camera_id="CAM_FLOOR_01",
            visitor_id="VIS_000001",
            event_type="ZONE_ENTER",
            timestamp=now - timedelta(minutes=5),
            zone_id="SKINCARE",
            is_staff=False,
            confidence=0.95
        )
        test_db.add(recent_event)
        test_db.commit()

        service = AnomalyDetectionService(test_db)
        anomalies = service.detect_anomalies("STORE_BLR_001")

        dead_zone_anomalies = [a for a in anomalies if a["anomaly_type"] == "DEAD_ZONE"]
        skincare_dead = [a for a in dead_zone_anomalies if "SKINCARE" in a["description"]]
        assert len(skincare_dead) == 0

    def test_no_false_positive_on_new_store(self, test_db):
        """Test no dead zone anomaly for a store with no history at all."""
        service = AnomalyDetectionService(test_db)
        anomalies = service.detect_anomalies("STORE_BLR_001")

        dead_zone_anomalies = [a for a in anomalies if a["anomaly_type"] == "DEAD_ZONE"]
        # No prior activity means no dead zone (can't be dead if never alive)
        assert len(dead_zone_anomalies) == 0

    def test_dead_zone_severity_is_info(self, test_db):
        """Test that dead zone anomalies have INFO severity."""
        now = datetime.utcnow()

        early_event = Event(
            event_id="evt_dz3",
            store_id="STORE_BLR_001",
            camera_id="CAM_FLOOR_01",
            visitor_id="VIS_000001",
            event_type="ZONE_ENTER",
            timestamp=now - timedelta(minutes=45),
            zone_id="HAIRCARE",
            is_staff=False,
            confidence=0.95
        )
        test_db.add(early_event)
        test_db.commit()

        service = AnomalyDetectionService(test_db)
        anomalies = service.detect_anomalies("STORE_BLR_001")

        dead_zone_anomalies = [a for a in anomalies if a["anomaly_type"] == "DEAD_ZONE"]
        for anomaly in dead_zone_anomalies:
            assert anomaly["severity"] == "INFO"


class TestConversionDropDetection:
    """Test CONVERSION_DROP anomaly detection."""

    def test_no_conversion_drop_with_no_history(self, test_db):
        """Test no conversion drop when there is no 7-day baseline."""
        service = AnomalyDetectionService(test_db)
        anomalies = service.detect_anomalies("STORE_BLR_001")

        conversion_anomalies = [a for a in anomalies if a["anomaly_type"] == "CONVERSION_DROP"]
        assert len(conversion_anomalies) == 0

    def test_no_anomalies_empty_store(self, test_db):
        """Test that an empty store produces no anomalies."""
        service = AnomalyDetectionService(test_db)
        anomalies = service.detect_anomalies("STORE_BLR_001")

        assert isinstance(anomalies, list)
        assert len(anomalies) == 0

    def test_all_staff_events_no_anomaly(self, test_db):
        """Test that all-staff events don't trigger customer anomalies."""
        now = datetime.utcnow()

        staff_events = [
            Event(
                event_id=f"evt_staff_{i}",
                store_id="STORE_BLR_001",
                camera_id="CAM_FLOOR_01",
                visitor_id="VIS_STAFF_001",
                event_type="ZONE_ENTER",
                timestamp=now - timedelta(minutes=i),
                zone_id="SKINCARE",
                is_staff=True,
                confidence=0.95
            )
            for i in range(5)
        ]

        for event in staff_events:
            test_db.add(event)
        test_db.commit()

        service = AnomalyDetectionService(test_db)
        anomalies = service.detect_anomalies("STORE_BLR_001")

        # Staff-only activity should not trigger conversion drop
        conversion_anomalies = [a for a in anomalies if a["anomaly_type"] == "CONVERSION_DROP"]
        assert len(conversion_anomalies) == 0


class TestAnomalyResponseStructure:
    """Test anomaly response structure and fields."""

    def test_anomaly_fields_present(self, test_db):
        """Test that all required fields are present in anomaly response."""
        now = datetime.utcnow()

        event = Event(
            event_id="evt_struct1",
            store_id="STORE_BLR_001",
            camera_id="CAM_BILLING_01",
            visitor_id="VIS_000001",
            event_type="BILLING_QUEUE_JOIN",
            timestamp=now - timedelta(minutes=2),
            zone_id="BILLING",
            is_staff=False,
            confidence=0.95,
            event_metadata={"queue_depth": 9}
        )
        test_db.add(event)
        test_db.commit()

        service = AnomalyDetectionService(test_db)
        anomalies = service.detect_anomalies("STORE_BLR_001")

        for anomaly in anomalies:
            assert "anomaly_type" in anomaly
            assert "severity" in anomaly
            assert "description" in anomaly
            assert "suggested_action" in anomaly
            assert "detected_at" in anomaly

    def test_severity_values_valid(self, test_db):
        """Test that severity values are only INFO, WARN, or CRITICAL."""
        now = datetime.utcnow()

        events = [
            Event(
                event_id="evt_sev1",
                store_id="STORE_BLR_001",
                camera_id="CAM_BILLING_01",
                visitor_id="VIS_000001",
                event_type="BILLING_QUEUE_JOIN",
                timestamp=now - timedelta(minutes=2),
                zone_id="BILLING",
                is_staff=False,
                confidence=0.95,
                event_metadata={"queue_depth": 8}
            ),
            Event(
                event_id="evt_sev2",
                store_id="STORE_BLR_001",
                camera_id="CAM_FLOOR_01",
                visitor_id="VIS_000002",
                event_type="ZONE_ENTER",
                timestamp=now - timedelta(minutes=50),
                zone_id="MAKEUP",
                is_staff=False,
                confidence=0.95
            ),
        ]

        for event in events:
            test_db.add(event)
        test_db.commit()

        service = AnomalyDetectionService(test_db)
        anomalies = service.detect_anomalies("STORE_BLR_001")

        valid_severities = {"INFO", "WARN", "CRITICAL"}
        for anomaly in anomalies:
            assert anomaly["severity"] in valid_severities
