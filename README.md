# Store Intelligence System
### Purplle Tech Challenge 2026 — Round 2

An end-to-end AI-powered store analytics system that converts raw CCTV footage into real-time business intelligence. Built for Brigade Road Bangalore Purplle store.

**North Star Metric**: Offline Store Conversion Rate = Visitors who purchased ÷ Total unique visitors

---

## Deployment to Railway

### Option 1: Direct Railway Deployment (Recommended)

1. **Push to GitHub**
   ```bash
   git init
   git add .
   git commit -m "Store Intelligence API"
   git push origin main
   ```

2. **Deploy on Railway**
   - Go to [railway.app](https://railway.app)
   - Click "New Project" → "Deploy from GitHub repo"
   - Select your repository
   - Railway will auto-detect the Dockerfile and deploy
   - Your API will be live at `https://your-app.railway.app`

3. **Ingest events to Railway**
   ```bash
   python scripts/ingest_events.py --api https://your-app.railway.app
   ```

### Option 2: Local Docker (For Testing Only)

```bash
# Build and run locally
docker compose up --build -d

# Ingest events
python scripts/ingest_events.py

# View logs
docker compose logs -f

# Stop
docker compose down
```

**Note**: Local Docker build takes ~10 minutes due to dependencies. Railway deployment is faster and recommended.

---

## Quick Start (Local)

```bash
# 1. Install API dependencies only (lightweight)
pip install -r requirements-api.txt

# 2. Start the API locally
uvicorn app.main:app --reload

# 3. Ingest the pre-generated events
python scripts/ingest_events.py

# 4. Verify the API is working
curl http://localhost:8000/stores/STORE_BLR_001/metrics

# 5. Launch the live dashboard
python dashboard.py
```

The API is available at **http://localhost:8000**

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

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/events/ingest` | Ingest batch of events (up to 500) |
| `GET` | `/stores/{id}/metrics` | Real-time store metrics |
| `GET` | `/stores/{id}/funnel` | Conversion funnel |
| `GET` | `/stores/{id}/heatmap` | Zone heatmap |
| `GET` | `/stores/{id}/anomalies` | Active anomalies |
| `GET` | `/health` | System health |

### Example: Ingest events
```bash
curl -X POST http://localhost:8000/events/ingest \
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

### Example: Get metrics
```bash
curl "http://localhost:8000/stores/STORE_BLR_001/metrics?date=2026-04-10"
```

### Example: Get funnel
```bash
curl "http://localhost:8000/stores/STORE_BLR_001/funnel?date=2026-04-10"
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
- **Cameras**: 5 (2 entry, 2 floor, 1 billing)
- **Zones**: ENTRY, SKINCARE, MAKEUP, HAIRCARE, BODYCARE, BILLING
