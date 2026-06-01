"""
Ingest events from events.jsonl into the running API.
Usage: python scripts/ingest_events.py [--file data/events.jsonl] [--api http://localhost:8000]
"""

import json
import argparse
import requests
from pathlib import Path


def ingest_events(events_file: str, api_url: str, batch_size: int = 100):
    """Ingest events from JSONL file into the API in batches."""
    events_path = Path(events_file)
    
    if not events_path.exists():
        print(f"Error: Events file not found: {events_file}")
        return
    
    # Load all events
    events = []
    with open(events_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    
    print(f"Loaded {len(events)} events from {events_file}")
    print(f"Ingesting to {api_url} in batches of {batch_size}...")
    
    total_ingested = 0
    total_failed = 0
    
    # Process in batches
    for i in range(0, len(events), batch_size):
        batch = events[i:i + batch_size]
        
        try:
            response = requests.post(
                f"{api_url}/events/ingest",
                json={"events": batch},
                timeout=30
            )
            response.raise_for_status()
            
            result = response.json()
            total_ingested += result.get("ingested_count", 0)
            total_failed += result.get("failed_count", 0)
            
            batch_num = (i // batch_size) + 1
            total_batches = (len(events) + batch_size - 1) // batch_size
            print(f"Batch {batch_num}/{total_batches}: {result['ingested_count']} ingested, {result['failed_count']} failed")
            
        except requests.exceptions.ConnectionError:
            print(f"Error: Cannot connect to API at {api_url}")
            print("Make sure the API is running: docker compose up")
            return
        except Exception as e:
            print(f"Error ingesting batch {i//batch_size + 1}: {e}")
            total_failed += len(batch)
    
    print(f"\n=== Ingestion Complete ===")
    print(f"Total ingested: {total_ingested}")
    print(f"Total failed: {total_failed}")
    
    if total_ingested > 0:
        print(f"\nVerify metrics:")
        print(f"  curl {api_url}/stores/STORE_BLR_001/metrics")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest events into Store Intelligence API")
    parser.add_argument("--file", default="data/events.jsonl", help="Path to events JSONL file")
    parser.add_argument("--api", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--batch-size", type=int, default=100, help="Batch size for ingestion")
    
    args = parser.parse_args()
    ingest_events(args.file, args.api, args.batch_size)
