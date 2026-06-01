# CHOICES.md — Engineering Decision Log

## Decision 1: Detection Model — YOLOv8n

### Options Considered

| Model | Speed (CPU) | Accuracy | Occlusion Handling | Notes |
|-------|-------------|----------|--------------------|-------|
| YOLOv8n | ~30ms/frame | Good | Moderate | Smallest YOLO variant |
| YOLOv8s | ~50ms/frame | Better | Good | 2× slower than nano |
| RT-DETR | ~80ms/frame | Best | Good | Transformer-based, heavy |
| MediaPipe | ~15ms/frame | Moderate | Poor | Optimized for mobile |
| YOLOv9 | ~60ms/frame | Better | Good | Newer, less ecosystem |

### What AI Suggested

I asked Claude to evaluate these models for a retail CCTV use case with 1080p footage at 15fps, running on a machine that may not have a GPU. Claude recommended YOLOv8s as the best balance of speed and accuracy, noting that YOLOv8n might miss small or partially occluded people.

### What I Chose and Why

**YOLOv8n** — I disagreed with the AI's recommendation of YOLOv8s for the following reasons:

1. **Processing every 3rd frame**: By skipping 2 out of 3 frames, we effectively reduce the processing requirement by 3×. This means YOLOv8n at 30ms/frame on every 3rd frame is equivalent to ~10ms effective throughput — fast enough for real-time processing even on CPU.

2. **Retail context**: In a retail store, people move slowly compared to, say, a sports event. Missing a detection on one frame is acceptable because ByteTrack's Kalman filter will interpolate the position. The tracker compensates for occasional missed detections.

3. **Deployment reality**: The challenge specifies docker compose up on an arbitrary machine. YOLOv8n runs on CPU without CUDA. YOLOv8s is 2× slower and would make the pipeline impractical on CPU-only machines.

4. **Confidence threshold**: I set the threshold at 0.25 (lower than the default 0.5) to catch partial occlusions. This means more false positives, but the tracker filters them out — a detection that appears for only 1-2 frames without a consistent trajectory is discarded by ByteTrack.

**Where I'd upgrade**: If this were a production deployment with GPU infrastructure, I'd switch to YOLOv8s or RT-DETR for better accuracy on the partial occlusion cases. The code is structured so this is a one-line change to the model path.

---

## Decision 2: Event Schema Design

### Options Considered

**Option A: Flat event log** — Every detection frame emits an event. Simple, but produces millions of events per day and makes analytics queries expensive.

**Option B: Aggregated sessions** — Emit one record per visitor session with all zone visits embedded. Compact, but loses temporal granularity and makes real-time streaming impossible.

**Option C: Typed event catalogue (chosen)** — Emit discrete events at meaningful state transitions: ENTRY, EXIT, ZONE_ENTER, ZONE_EXIT, ZONE_DWELL (every 30s), BILLING_QUEUE_JOIN, BILLING_QUEUE_ABANDON, REENTRY. This is the event sourcing pattern.

### What AI Suggested

I asked Claude to design an event schema for a retail analytics system. It suggested Option C (typed events) and recommended including `session_seq` in metadata to allow reconstruction of visitor journeys. It also suggested making `zone_id` nullable for ENTRY/EXIT events rather than using a sentinel value like "NONE" — cleaner for SQL queries.

**I agreed with both suggestions.** The `session_seq` field is particularly useful for the follow-up question scenario: if a reviewer asks "walk me through visitor VIS_000042's journey", you can reconstruct it by filtering on `visitor_id` and ordering by `session_seq`.

### Why This Schema

1. **event_id as UUID v4**: Globally unique, generated at emission time. Enables idempotent ingestion — the API can safely receive the same event twice without double-counting.

2. **ISO-8601 UTC timestamps**: Derived from clip start time + frame offset. This means the timestamps are deterministic and reproducible — running the pipeline twice on the same clip produces the same timestamps.

3. **is_staff as a boolean field**: Rather than filtering staff at the pipeline level, we include their events with `is_staff=True`. This means the raw event log is complete and auditable. The API layer filters them out for customer metrics. If the staff classification heuristic is wrong, you can re-classify without re-running the pipeline.

4. **confidence field**: Never suppressed, even for low-confidence detections. A detection at 0.3 confidence is still information — it tells you something was there, just uncertain. Suppressing it would hide the uncertainty. The API can filter by confidence threshold if needed.

5. **metadata as flexible JSON**: `queue_depth`, `sku_zone`, and `session_seq` live here. This allows adding new metadata fields without a schema migration.

### Tradeoff Acknowledged

The typed event catalogue produces more events than aggregated sessions, but far fewer than frame-level logging. For 5 stores × 8 hours × ~20 visitors/hour, we're looking at roughly 5,000-10,000 events per day — trivially manageable in SQLite.

---

## Decision 3: SQLite over PostgreSQL

### Options Considered

| Database | Setup Complexity | Performance | Scalability | Notes |
|----------|-----------------|-------------|-------------|-------|
| SQLite (WAL) | Zero | Good for <1M rows | Single node | File-based |
| PostgreSQL | Medium | Excellent | Multi-node | Industry standard |
| TimescaleDB | High | Excellent for time-series | Multi-node | PostgreSQL extension |
| DuckDB | Low | Excellent for analytics | Single node | OLAP-optimized |

### What AI Suggested

I asked Claude which database to use for a retail analytics API that needs to handle event ingestion and real-time analytics queries. It recommended PostgreSQL for production-readiness and scalability, noting that SQLite has limitations with concurrent writes.

**I partially disagreed.** Here's my reasoning:

### What I Chose and Why

**SQLite with WAL mode** for the following reasons:

1. **Acceptance gate requirement**: `docker compose up` must work with no manual steps. PostgreSQL requires a separate container, initialization scripts, and health check coordination. SQLite is a file — zero setup.

2. **WAL mode solves the concurrency problem**: SQLite in WAL (Write-Ahead Logging) mode allows concurrent reads during writes. The dashboard polling every 3 seconds while events are being ingested is the primary concurrency pattern here. WAL handles this correctly.

3. **Data volume**: 5 stores × 8 hours × ~20 visitors/hour × ~10 events/visitor = ~8,000 events/day. SQLite handles millions of rows efficiently with proper indexes. We're nowhere near the limit.

4. **Append-heavy workload**: The events table is append-only (no updates, no deletes). SQLite is highly optimized for this pattern.

5. **Portability**: The database is a single file that can be volume-mounted in Docker, backed up with `cp`, and inspected with any SQLite client. This is operationally simpler than managing a PostgreSQL cluster.

### Scalability Path

If this system were deployed to all 40 stores with real-time streaming:
- 40 stores × 8 hours × 50 visitors/hour × 10 events/visitor = ~160,000 events/day
- Still manageable in SQLite, but approaching the point where PostgreSQL makes sense

The upgrade path is: change `DATABASE_URL` in `docker-compose.yml` from `sqlite:///./store_intelligence.db` to `postgresql://user:pass@db:5432/store_intelligence`. The SQLAlchemy ORM layer means no application code changes are needed.

**The first thing that breaks at 40 live stores**: concurrent writes from 40 simultaneous ingest streams. SQLite's write lock would become a bottleneck. That's the trigger to migrate to PostgreSQL.
