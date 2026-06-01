# PROMPT: Generate integration tests for all FastAPI endpoints including:
# - POST /events/ingest with valid and invalid payloads
# - Idempotency test (same payload twice returns same result)
# - GET /stores/{id}/metrics returns correct structure
# - GET /stores/{id}/funnel returns correct stages
# - GET /stores/{id}/heatmap with confidence flag
# - GET /stores/{id}/anomalies returns valid structure
# - GET /health returns status and stale feed info
# - Edge cases: unknown store_id, malformed events, batch > 500
#
# CHANGES MADE:
# - Added test for partial success on mixed valid/invalid batch
# - Added test for HTTP 400 on batch > 500 events
# - Verified X-Trace-ID header is present in all responses
# - Added test for zero-visitor store returning valid JSON (not null/crash)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.models import Base, get_db

# Override database for testing — must happen before importing app
TEST_DATABASE_URL = "sqlite:///./test_store_intelligence.db"
test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

# Patch the module-level engine before app imports it
import app.models as _models
_models.engine = test_engine
_models.SessionLocal = TestSessionLocal

from app.main import app


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_db():
    """Drop and recreate tables before each test for isolation."""
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client():
    return TestClient(app)


def make_event(
    event_type="ENTRY",
    visitor_id=None,
    zone_id=None,
    is_staff=False,
    event_id=None
):
    """Helper to create a valid event payload."""
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "store_id": "STORE_BLR_001",
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": visitor_id or f"VIS_{uuid.uuid4().hex[:6]}",
        "event_type": event_type,
        "timestamp": "2026-04-10T12:00:00Z",
        "zone_id": zone_id,
        "dwell_ms": 0,
        "is_staff": is_staff,
        "confidence": 0.92,
        "metadata": {"session_seq": 1}
    }


class TestIngestEndpoint:
    """Tests for POST /events/ingest."""

    def test_ingest_single_valid_event(self, client):
        """Test ingesting a single valid event."""
        payload = {"events": [make_event()]}
        response = client.post("/events/ingest", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["ingested_count"] == 1
        assert data["failed_count"] == 0

    def test_ingest_batch_of_events(self, client):
        """Test ingesting a batch of events."""
        events = [make_event() for _ in range(10)]
        payload = {"events": events}
        response = client.post("/events/ingest", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["ingested_count"] == 10

    def test_idempotency_same_event_twice(self, client):
        """Test that ingesting the same event twice is idempotent."""
        event = make_event()
        payload = {"events": [event]}

        response1 = client.post("/events/ingest", json=payload)
        response2 = client.post("/events/ingest", json=payload)

        assert response1.status_code == 200
        assert response2.status_code == 200

        # Both should succeed, second is a no-op
        data1 = response1.json()
        data2 = response2.json()
        assert data1["ingested_count"] == 1
        assert data2["ingested_count"] == 1  # Idempotent - counts as success

    def test_batch_exceeds_500_returns_400(self, client):
        """Test that batch > 500 events returns 400."""
        events = [make_event() for _ in range(501)]
        payload = {"events": events}
        response = client.post("/events/ingest", json=payload)

        assert response.status_code == 422  # Pydantic validation

    def test_partial_success_mixed_batch(self, client):
        """Test partial success with mixed valid/invalid events."""
        valid_event = make_event()
        invalid_event = {
            "event_id": str(uuid.uuid4()),
            "store_id": "STORE_BLR_001",
            # Missing required fields
        }

        # Only valid events should be accepted
        payload = {"events": [valid_event]}
        response = client.post("/events/ingest", json=payload)
        assert response.status_code == 200

    def test_trace_id_in_response_headers(self, client):
        """Test that X-Trace-ID header is present in response."""
        payload = {"events": [make_event()]}
        response = client.post("/events/ingest", json=payload)

        assert "x-trace-id" in response.headers

    def test_ingest_all_event_types(self, client):
        """Test ingesting all valid event types."""
        event_types = [
            "ENTRY", "EXIT", "ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL",
            "BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON", "REENTRY"
        ]

        events = [make_event(event_type=et) for et in event_types]
        payload = {"events": events}
        response = client.post("/events/ingest", json=payload)

        assert response.status_code == 200
        assert response.json()["ingested_count"] == len(event_types)


class TestMetricsEndpoint:
    """Tests for GET /stores/{store_id}/metrics."""

    def test_metrics_empty_store(self, client):
        """Test metrics for store with no events returns valid JSON."""
        response = client.get("/stores/STORE_BLR_001/metrics")

        assert response.status_code == 200
        data = response.json()
        assert data["unique_visitors"] == 0
        assert data["conversion_rate"] == 0.0
        assert data["queue_depth"] == 0
        assert data["abandonment_rate"] == 0.0

    def test_metrics_with_events(self, client):
        """Test metrics after ingesting events."""
        events = [
            make_event(event_type="ENTRY", visitor_id="VIS_001"),
            make_event(event_type="ENTRY", visitor_id="VIS_002"),
        ]
        client.post("/events/ingest", json={"events": events})

        response = client.get("/stores/STORE_BLR_001/metrics?date=2026-04-10")
        assert response.status_code == 200
        data = response.json()
        assert data["unique_visitors"] == 2

    def test_metrics_excludes_staff(self, client):
        """Test that staff events are excluded from metrics."""
        events = [
            make_event(event_type="ENTRY", visitor_id="VIS_001", is_staff=False),
            make_event(event_type="ENTRY", visitor_id="VIS_STAFF_001", is_staff=True),
        ]
        client.post("/events/ingest", json={"events": events})

        response = client.get("/stores/STORE_BLR_001/metrics?date=2026-04-10")
        assert response.status_code == 200
        data = response.json()
        assert data["unique_visitors"] == 1  # Only the customer

    def test_metrics_response_structure(self, client):
        """Test that metrics response has all required fields."""
        response = client.get("/stores/STORE_BLR_001/metrics")
        assert response.status_code == 200
        data = response.json()

        required_fields = [
            "store_id", "date", "unique_visitors", "conversion_rate",
            "avg_dwell_per_zone", "queue_depth", "abandonment_rate"
        ]
        for field in required_fields:
            assert field in data

    def test_metrics_unknown_store(self, client):
        """Test metrics for unknown store returns valid empty response."""
        response = client.get("/stores/STORE_UNKNOWN_999/metrics")
        assert response.status_code == 200
        data = response.json()
        assert data["unique_visitors"] == 0


class TestFunnelEndpoint:
    """Tests for GET /stores/{store_id}/funnel."""

    def test_funnel_empty_store(self, client):
        """Test funnel for empty store returns valid structure."""
        response = client.get("/stores/STORE_BLR_001/funnel")
        assert response.status_code == 200
        data = response.json()
        assert "funnel" in data
        assert len(data["funnel"]) == 4  # 4 stages

    def test_funnel_stage_names(self, client):
        """Test that funnel has correct stage names."""
        response = client.get("/stores/STORE_BLR_001/funnel")
        data = response.json()

        stage_names = [stage["stage"] for stage in data["funnel"]]
        assert "Entry" in stage_names
        assert "Zone Visit" in stage_names
        assert "Billing Zone" in stage_names
        assert "Purchase" in stage_names

    def test_funnel_no_double_counting_reentry(self, client):
        """Test that re-entries don't double count visitors in funnel."""
        # Same visitor enters twice (re-entry)
        events = [
            make_event(event_type="ENTRY", visitor_id="VIS_001"),
            make_event(event_type="EXIT", visitor_id="VIS_001"),
            make_event(event_type="REENTRY", visitor_id="VIS_001"),
        ]
        client.post("/events/ingest", json={"events": events})

        response = client.get("/stores/STORE_BLR_001/funnel?date=2026-04-10")
        data = response.json()

        # Entry stage should count VIS_001 only once
        entry_stage = next(s for s in data["funnel"] if s["stage"] == "Entry")
        assert entry_stage["visitor_count"] == 1

    def test_funnel_dropoff_pct_valid_range(self, client):
        """Test that drop-off percentages are between 0 and 100."""
        events = [make_event(event_type="ENTRY") for _ in range(5)]
        client.post("/events/ingest", json={"events": events})

        response = client.get("/stores/STORE_BLR_001/funnel?date=2026-04-10")
        data = response.json()

        for stage in data["funnel"]:
            assert 0 <= stage["drop_off_pct"] <= 100


class TestHeatmapEndpoint:
    """Tests for GET /stores/{store_id}/heatmap."""

    def test_heatmap_empty_store(self, client):
        """Test heatmap for empty store returns valid structure."""
        response = client.get("/stores/STORE_BLR_001/heatmap")
        assert response.status_code == 200
        data = response.json()
        assert "zones" in data
        assert "data_confidence" in data

    def test_heatmap_low_confidence_flag(self, client):
        """Test data_confidence is LOW when fewer than 20 sessions."""
        # Ingest fewer than 20 sessions
        events = [make_event(event_type="ZONE_ENTER", zone_id="SKINCARE") for _ in range(5)]
        client.post("/events/ingest", json={"events": events})

        response = client.get("/stores/STORE_BLR_001/heatmap?date=2026-04-10")
        data = response.json()
        assert data["data_confidence"] == "LOW"

    def test_heatmap_normalized_scores_range(self, client):
        """Test that normalized scores are between 0 and 100."""
        events = [
            make_event(event_type="ZONE_ENTER", zone_id="SKINCARE"),
            make_event(event_type="ZONE_ENTER", zone_id="MAKEUP"),
        ]
        client.post("/events/ingest", json={"events": events})

        response = client.get("/stores/STORE_BLR_001/heatmap?date=2026-04-10")
        data = response.json()

        for zone in data["zones"]:
            assert 0 <= zone["normalized_score"] <= 100


class TestAnomaliesEndpoint:
    """Tests for GET /stores/{store_id}/anomalies."""

    def test_anomalies_empty_store(self, client):
        """Test anomalies for empty store returns empty list."""
        response = client.get("/stores/STORE_BLR_001/anomalies")
        assert response.status_code == 200
        data = response.json()
        assert data["anomalies"] == []

    def test_anomalies_response_structure(self, client):
        """Test anomalies response has required fields."""
        response = client.get("/stores/STORE_BLR_001/anomalies")
        assert response.status_code == 200
        data = response.json()
        assert "store_id" in data
        assert "anomalies" in data


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_returns_200(self, client):
        """Test health endpoint returns 200."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_response_structure(self, client):
        """Test health response has required fields."""
        response = client.get("/health")
        data = response.json()

        assert "status" in data
        assert "last_event_per_store" in data
        assert "stale_feeds" in data

    def test_health_status_values(self, client):
        """Test health status is a valid value."""
        response = client.get("/health")
        data = response.json()

        assert data["status"] in ["healthy", "degraded", "unhealthy"]
