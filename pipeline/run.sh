#!/bin/bash
# run.sh — Process all CCTV clips and emit events to data/events.jsonl
# Usage: bash pipeline/run.sh
# Prerequisites: pip install ultralytics supervision opencv-python

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=== Store Intelligence Detection Pipeline ==="
echo "Store: STORE_BLR_001 (Brigade_Bangalore)"
echo "Output: $PROJECT_ROOT/data/events.jsonl"
echo ""

# Check for video files
VIDEO_DIR="$PROJECT_ROOT/data/videos"
if [ ! -d "$VIDEO_DIR" ]; then
    echo "Warning: Video directory not found at $VIDEO_DIR"
    echo "Place video files (CAM 1.mp4 through CAM 5.mp4) in $VIDEO_DIR"
    echo ""
    echo "Falling back to pre-generated events.jsonl..."
    exit 0
fi

# Run detection pipeline
python "$SCRIPT_DIR/detect.py" \
    --store-layout "$PROJECT_ROOT/data/store_layout.json" \
    --video-dir "$VIDEO_DIR" \
    --output "$PROJECT_ROOT/data/events.jsonl" \
    --base-date "2026-04-10" \
    --base-time "12:00:00"

echo ""
echo "=== Pipeline Complete ==="
echo "Events written to: $PROJECT_ROOT/data/events.jsonl"
echo ""
echo "Next step: Ingest events into the API"
echo "  python scripts/ingest_events.py"
