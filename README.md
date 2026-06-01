# Store Intelligence System
### Purplle Tech Challenge 2026 — Round 2

An end-to-end AI-powered store analytics system that converts raw CCTV footage into real-time business intelligence. Built for Brigade Road Bangalore Purplle store.

**North Star Metric**: Offline Store Conversion Rate = Visitors who purchased ÷ Total unique visitors

---

## 🚀 Live Deployment

- **Live API**: https://purplle-store-intelligence-production.up.railway.app
- **Interactive Docs**: https://purplle-store-intelligence-production.up.railway.app/docs
- **GitHub**: https://github.com/uvenkatateja/purplle-store-intelligence

### Quick Test Links (Click to Open)
- [Health Check](https://purplle-store-intelligence-production.up.railway.app/health)
- [Store Metrics](https://purplle-store-intelligence-production.up.railway.app/stores/STORE_BLR_001/metrics?date=2026-04-10)
- [Conversion Funnel](https://purplle-store-intelligence-production.up.railway.app/stores/STORE_BLR_001/funnel?date=2026-04-10)
- [Zone Heatmap](https://purplle-store-intelligence-production.up.railway.app/stores/STORE_BLR_001/heatmap?date=2026-04-10)
- [Anomalies](https://purplle-store-intelligence-production.up.railway.app/stores/STORE_BLR_001/anomalies)

---

## Deployment

### ✅ Already Deployed on Railway!

The API is live at: **https://purplle-store-intelligence-production.up.railway.app**

Test it now:
```bash
# Health check
curl https://purplle-store-intelligence-production.up.railway.app/health

# Get metrics (April 10, 2026 - date of video footage)
curl "https://purplle-store-intelligence-production.up.railway.app/stores/STORE_BLR_001/metrics?date=2026-04-10"

# Get funnel
curl "https://purplle-store-intelligence-production.up.railway.app/stores/STORE_BLR_001/funnel?date=2026-04-10"
```

### Local Docker (Optional)

```bash
# Build and run locally
docker compose up --build -d

# Ingest events
python scripts/ingest_events.py

# Stop
docker compose down
```

---

## Quick Start

### Option 1: Use the Live API (Recommended)

The API is already deployed and running! Just test it:

```bash
# Test the live API
curl "https://purplle-store-intelligence-production.up.railway.app/stores/STORE_BLR_001/metrics?date=2026-04-10"

# Or open in browser
https://purplle-store-intelligence-production.up.railway.app/docs
```

### Option 2: Run Locally

```bash
# 1. Install API dependencies only (lightweight)
pip install -r requirements-api.txt

# 2. Start the API locally
uvicorn app.main:app --reload

# 3. Ingest the pre-generated events
python scripts/ingest_events.py

# 4. Verify the API is working
curl "http://localhost:8000/stores/STORE_BLR_001/metrics?date=2026-04-10"

# 5. Launch the live dashboard
python dashboard.py
```

Local API: **http://localhost:8000**  
Interactive docs: **http://localhost:8000/docs**

---

## Detection Pipeline (Optional)

The detection pipeline has already been run and generated `data/events.jsonl` with 286 events. You don't need to run it again unless you have new video footage.

If you want to process new videos:

### Prerequisites
```bash
pip install ultralytics supervision opencv-python numpy
```

### Place video files in `data/videos/`
```
data/videos/
├── CAM 1.mp4    # Primary entry camera
├── CAM 2.mp4    # Skincare/Makeup floor camera
└── ...          # Additional cameras
```

### Run the pipeline
```bash
bash pipeline/run.sh
```

This processes all clips and writes structured events to `data/events.jsonl`.

### Then ingest into the API
```bash
python scripts/ingest_events.py --file data/events.jsonl --api http://localhost:8000
```

---

## API Endpoints

| Method | Endpoint | Description | Live URL |
|--------|----------|-------------|----------|
| `POST` | `/events/ingest` | Ingest batch of events (up to 500) | [Try it](https://purplle-store-intelligence-production.up.railway.app/docs#/default/ingest_events_events_ingest_post) |
| `GET` | `/stores/{id}/metrics` | Real-time store metrics | [Test](https://purplle-store-intelligence-production.up.railway.app/stores/STORE_BLR_001/metrics?date=2026-04-10) |
| `GET` | `/stores/{id}/funnel` | Conversion funnel | [Test](https://purplle-store-intelligence-production.up.railway.app/stores/STORE_BLR_001/funnel?date=2026-04-10) |
| `GET` | `/stores/{id}/heatmap` | Zone heatmap | [Test](https://purplle-store-intelligence-production.up.railway.app/stores/STORE_BLR_001/heatmap?date=2026-04-10) |
| `GET` | `/stores/{id}/anomalies` | Active anomalies | [Test](https://purplle-store-intelligence-production.up.railway.app/stores/STORE_BLR_001/anomalies) |
| `GET` | `/health` | System health | [Test](https://purplle-store-intelligence-production.up.railway.app/health) |

### Example: Get metrics
```bash
# Live API
curl "https://purplle-store-intelligence-production.up.railway.app/stores/STORE_BLR_001/metrics?date=2026-04-10"

# Response
{
  "store_id": "STORE_BLR_001",
  "date": "2026-04-10",
  "unique_visitors": 134,
  "conversion_rate": 0.0,
  "avg_dwell_per_zone": {
    "SKINCARE": 30040.0,
    "HAIRCARE": 30030.0
  },
  "queue_depth": 0,
  "abandonment_rate": 0.0
}
```

### Example: Get funnel
```bash
# Live API
curl "https://purplle-store-intelligence-production.up.railway.app/stores/STORE_BLR_001/funnel?date=2026-04-10"

# Response
{
  "store_id": "STORE_BLR_001",
  "date": "2026-04-10",
  "funnel": [
    {"stage": "Entry", "visitor_count": 134, "drop_off_pct": 0.0},
    {"stage": "Zone Visit", "visitor_count": 100, "drop_off_pct": 25.37},
    {"stage": "Billing Zone", "visitor_count": 0, "drop_off_pct": 100.0},
    {"stage": "Purchase", "visitor_count": 0, "drop_off_pct": 100.0}
  ]
}
```

### Example: Ingest events
```bash
curl -X POST https://purplle-store-intelligence-production.up.railway.app/events/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "events": [{
      "event_id": "550e8400-e29b-41d4-a716-446655440000",
      "store_id": "STORE_BLR_001",
      "camera_id": "CAM_ENTRY_01",
      "visitor_id": "VIS_000001",
      "event_type": "ENTRY",
      "timestamp": "2026-04-10T12:15:00Z",
      "zone_id": null,
      "dwell_ms": 0,
      "is_staff": false,
      "confidence": 0.92,
      "metadata": {"session_seq": 1}
    }]
  }'
```

---

## Project Structure

```
store-intelligence/
├── pipeline/
│   ├── detect.py          # YOLOv8n + ByteTrack detection script
│   ├── tracker.py         # Re-ID and visitor tracking logic
│   ├── emit.py            # Event schema + JSONL emission
│   └── run.sh             # One command to process all clips
├── app/
│   ├── main.py            # FastAPI entrypoint (all endpoints)
│   ├── models.py          # SQLAlchemy + Pydantic schemas
│   ├── ingestion.py       # Idempotent event ingestion
│   ├── metrics.py         # Real-time metric computation
│   ├── funnel.py          # Session-based funnel logic
│   ├── anomalies.py       # Anomaly detection
│   └── health.py          # Health check
├── tests/
│   ├── test_pipeline.py   # Pipeline unit tests
│   ├── test_metrics.py    # Metrics computation tests
│   ├── test_anomalies.py  # Anomaly detection tests
│   └── test_api.py        # API integration tests
├── docs/
│   ├── DESIGN.md          # Architecture + AI-assisted decisions
│   └── CHOICES.md         # 3 engineering decisions with full reasoning
├── data/
│   ├── store_layout.json  # Zone definitions
│   ├── events.jsonl       # Pre-generated detection events (286 events)
│   └── pos_transactions.csv  # POS transactions (101 records)
├── scripts/
│   ├── ingest_events.py   # Batch ingest events into API
│   ├── generate_seed_events.py
│   └── generate_pos_csv.py
├── dashboard.py           # Rich terminal live dashboard
├── docker-compose.yml
├── Dockerfile
└── README.md
```

---

## Running Tests

```bash
# Install test dependencies
pip install pytest pytest-cov pytest-asyncio httpx

# Run all tests with coverage
pytest --cov=app --cov-report=term-missing

# Run specific test file
pytest tests/test_api.py -v
pytest tests/test_metrics.py -v
pytest tests/test_anomalies.py -v
```

---

## Live Dashboard

```bash
# Start dashboard (API must be running)
python dashboard.py

# Custom store or API URL
python dashboard.py --store-id STORE_BLR_001 --api-url http://localhost:8000 --refresh 3
```

The dashboard shows:
- Unique visitors (live)
- Conversion rate
- Queue depth
- Top zone by dwell time
- Active anomalies (color-coded by severity)

---

## Architecture Decisions

See [`docs/DESIGN.md`](docs/DESIGN.md) for full architecture overview and AI-assisted decisions.

See [`docs/CHOICES.md`](docs/CHOICES.md) for:
1. Why YOLOv8n over other detection models
2. Event schema design rationale
3. SQLite over PostgreSQL

---

## Key Design Choices

**Detection**: YOLOv8n + ByteTrack, processing every 3rd frame. Staff detected by continuous presence >10 minutes. Entry/exit by virtual tripwire at frame midline.

**POS Correlation**: A visitor is "converted" if they were in the BILLING zone within 5 minutes before any POS transaction timestamp. No customer ID required.

**Idempotency**: Every event has a UUID v4 `event_id`. Ingesting the same event twice is a no-op — safe to replay the pipeline output.

**Graceful degradation**: Database unavailable → HTTP 503 with structured JSON body. No stack traces in responses.

---

## Store Details

- **Store ID**: STORE_BLR_001
- **Store Name**: Brigade_Bangalore
- **Date**: 2026-04-10
- **Events Ingested**: 146 events
- **Unique Visitors**: 134
- **Zones**: ENTRY, SKINCARE, MAKEUP, HAIRCARE, BODYCARE, BILLING

---

## 📊 Live Data Summary

The system has processed real CCTV footage and ingested 146 events:

- **134 unique visitors** tracked across the store
- **100 zone visits** (SKINCARE: 62, HAIRCARE: 38)
- **Average dwell time**: ~30 seconds per zone
- **Conversion funnel**: Entry (134) → Zone Visit (100) → Billing (0) → Purchase (0)
- **Data confidence**: HIGH (sufficient sample size)

Test the live API to see real analytics!
