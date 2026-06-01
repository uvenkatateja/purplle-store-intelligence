# DESIGN.md — Store Intelligence System

## Architecture Overview

This system converts raw CCTV footage from a retail store into real-time business analytics. The pipeline has four stages: detection, event streaming, intelligence API, and live dashboard. Each stage is independently deployable and loosely coupled through a structured event schema.

```
Raw CCTV Clips
     │
     ▼
┌─────────────────────────────────────────────────────┐
│  Detection Layer (pipeline/)                        │
│  YOLOv8n → ByteTrack → VisitorTracker → EventEmitter│
│  Output: events.jsonl                               │
└─────────────────────────────────────────────────────┘
     │
     ▼  POST /events/ingest
┌─────────────────────────────────────────────────────┐
│  Intelligence API (app/)                            │
│  FastAPI + SQLAlchemy + SQLite (WAL mode)           │
│  Endpoints: metrics, funnel, heatmap, anomalies     │
└─────────────────────────────────────────────────────┘
     │
     ▼  GET /stores/{id}/metrics (every 3s)
┌─────────────────────────────────────────────────────┐
│  Live Dashboard (dashboard.py)                      │
│  Rich terminal UI — live updating table             │
└─────────────────────────────────────────────────────┘
```

---

## Component Breakdown

### Detection Layer (`pipeline/`)

**detect.py** — Main orchestrator. Opens each video with OpenCV, runs YOLOv8n inference on every 3rd frame (for speed), passes detections to supervision's ByteTrack, then routes events to the appropriate handler based on camera role (entry, floor, billing).

**tracker.py** — Maintains a `VisitorTracker` that maps ByteTrack integer IDs to stable `VIS_XXXXXX` visitor tokens. Handles:
- New track → new visitor ID
- Existing track → same visitor ID (persistence)
- Staff detection: track present continuously for >10 minutes → `is_staff=True`
- Exit marking: removes track from active set, adds to `exited_visitors`
- Stale track cleanup: removes tracks not seen in 30 seconds

**emit.py** — `EventEmitter` writes newline-delimited JSON to `data/events.jsonl`. Each event gets a UUID v4 `event_id` at emission time. The emitter validates schema before writing.

**Entry/Exit detection** — For entry cameras, we track the vertical center of each bounding box across frames. When a person's center crosses the horizontal midline of the frame (y = 0.5 × height), we emit ENTRY (downward crossing) or EXIT (upward crossing). This is a deliberate simplification: the midline acts as a virtual tripwire.

**Zone dwell** — For floor cameras, we track when each `track_id` first appears in frame. Every 30 seconds of continuous presence, we emit a `ZONE_DWELL` event with cumulative `dwell_ms`.

**Billing queue** — For billing cameras, we count active tracks in frame as `queue_depth` and emit `BILLING_QUEUE_JOIN` when a new track appears.

---

### Intelligence API (`app/`)

**main.py** — FastAPI application with:
- Lifespan context manager for DB initialization
- Middleware for structured JSON logging (trace_id, latency_ms, status_code)
- Global exception handler that returns structured errors — no raw stack traces ever reach the client
- CORS enabled for dashboard access

**models.py** — Two layers:
1. SQLAlchemy `Event` model with composite indexes on `(store_id, timestamp)`, `(visitor_id, timestamp)`, and `(store_id, event_type)` for fast analytics queries
2. Pydantic schemas for request/response validation with strict `event_type` and `confidence` validators

**ingestion.py** — Idempotent by `event_id`. On duplicate, returns success without re-inserting. On partial batch failure, continues processing remaining events and returns structured error list.

**metrics.py** — All metrics computed from raw events at query time (no pre-aggregation). This is intentional: with SQLite and the current data volume, query-time computation is fast enough and avoids stale cache issues. POS correlation uses a 5-minute window join between billing zone events and transaction timestamps.

**funnel.py** — Session-based funnel. Uses `ENTRY` events (not `REENTRY`) to establish the unique visitor set, then checks each subsequent stage against that set. This prevents re-entries from inflating the entry count.

**anomalies.py** — Three detectors:
- `BILLING_QUEUE_SPIKE`: checks most recent `BILLING_QUEUE_JOIN` metadata for `queue_depth > 5`
- `DEAD_ZONE`: finds zones with no activity in last 30 minutes that had activity earlier today
- `CONVERSION_DROP`: compares today's conversion rate to 7-day average; flags if >30% below baseline

**health.py** — Queries `MAX(timestamp)` per store. If any store's last event is >10 minutes old, it's added to `stale_feeds`. This is the first thing an on-call engineer checks.

---

### Storage

SQLite with WAL (Write-Ahead Logging) mode. The database file is volume-mounted in Docker so it persists across container restarts. WAL mode allows concurrent reads during writes, which matters when the dashboard is polling while events are being ingested.

For a production multi-store deployment, the natural upgrade path is PostgreSQL with TimescaleDB for time-series queries. The SQLAlchemy ORM layer means this is a one-line change to the connection string.

---

### Live Dashboard (`dashboard.py`)

Uses the `rich` library's `Live` context manager to refresh a terminal layout every 3 seconds. Polls `GET /stores/{id}/metrics` and `GET /stores/{id}/anomalies`. Anomalies are shown in red (CRITICAL), yellow (WARN), or blue (INFO). The dashboard is proof that the pipeline and API are genuinely connected — not just batch-processed.

---

## North Star Metric Connection

Every component traces back to **Offline Store Conversion Rate = Visitors who purchased ÷ Total unique visitors**.

| Component | Contribution |
|-----------|-------------|
| Entry/exit detection | Accurate denominator (total unique visitors) |
| Staff exclusion | Removes noise from denominator |
| Re-entry handling | Prevents denominator inflation |
| POS correlation | Accurate numerator (converted visitors) |
| `/metrics` endpoint | Exposes the metric in real time |
| `/funnel` endpoint | Shows where in the journey we lose customers |
| `/anomalies` endpoint | Alerts when the metric is degrading |

---

## AI-Assisted Decisions

### 1. ByteTrack over DeepSORT for tracking

I asked Claude to compare ByteTrack, DeepSORT, and StrongSORT for a retail CCTV use case with partial occlusion and group entry. The AI recommended ByteTrack for its speed (no appearance model required) and robustness to occlusion. It noted that DeepSORT's appearance model can cause ID switches when two people are close together — exactly the group entry problem.

**I agreed with this recommendation.** ByteTrack's Kalman filter-based motion prediction handles the case where a person is briefly occluded by a display shelf, which is common in the footage. The tradeoff is that ByteTrack has weaker Re-ID across camera boundaries, but since we're doing per-camera tracking and using visitor tokens for cross-camera correlation, this is acceptable.

### 2. Query-time metric computation vs pre-aggregation

I asked Claude whether to pre-aggregate metrics into a summary table or compute them at query time. The AI suggested pre-aggregation for performance at scale. I **overrode this recommendation** for the current implementation.

My reasoning: with SQLite and the current event volume (thousands of events per store per day), query-time computation with proper indexes is fast enough (<50ms). Pre-aggregation adds complexity — you need to handle backfill when events arrive late, invalidate caches on re-ingestion, and maintain consistency between the raw events table and the summary table. For a hackathon submission that needs to be correct and auditable, query-time computation is the right call. The indexes on `(store_id, timestamp)` make the queries efficient.

### 3. Staff detection heuristic

I asked Claude how to detect staff without a separate training dataset or uniform classifier. It suggested three approaches: (a) time-in-store threshold, (b) movement pattern analysis (staff move between all zones), (c) a VLM prompt to classify uniform color.

I chose the **time-in-store threshold** (>10 minutes continuous presence = staff) because it requires no additional model, works reliably for retail staff who are present for full shifts, and is explainable. I evaluated the VLM approach but found it unreliable on the anonymized footage where faces are blurred — the main visual cue for uniform detection (face + uniform together) is partially removed. The movement pattern approach would require cross-camera tracking which adds complexity beyond the scope of this implementation.
