"""Quick end-to-end test of all API endpoints with real data."""
import requests
import json
import time

BASE  = "http://localhost:8000"
STORE = "STORE_BLR_001"
DATE  = "2026-04-10"

# Wait for API
for _ in range(10):
    try:
        requests.get(f"{BASE}/health", timeout=2)
        break
    except Exception:
        time.sleep(1)

# Re-ingest (idempotent — safe to call again)
events = [json.loads(l) for l in open("data/events.jsonl")]
r1 = requests.post(f"{BASE}/events/ingest", json={"events": events[:100]}).json()
r2 = requests.post(f"{BASE}/events/ingest", json={"events": events[100:]}).json()
print(f"Ingest: {r1['ingested_count']} + {r2['ingested_count']} events (idempotent)")

endpoints = [
    f"/stores/{STORE}/metrics?date={DATE}",
    f"/stores/{STORE}/funnel?date={DATE}",
    f"/stores/{STORE}/heatmap?date={DATE}",
    f"/stores/{STORE}/anomalies",
    "/health",
]

all_ok = True
for path in endpoints:
    resp = requests.get(BASE + path)
    status = "OK" if resp.status_code == 200 else f"FAIL {resp.status_code}"
    print(f"\n=== {status} {path} ===")
    print(json.dumps(resp.json(), indent=2, default=str))
    if resp.status_code != 200:
        all_ok = False

print("\n" + ("ALL ENDPOINTS OK" if all_ok else "SOME ENDPOINTS FAILED"))
