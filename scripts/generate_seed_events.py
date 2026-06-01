"""
Generate realistic seed events.jsonl for STORE_BLR_001 on 2026-04-10.
Matches the POS transactions CSV time range: 12:15 - 21:39.
Run: python scripts/generate_seed_events.py
"""

import json
import uuid
import random
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)

STORE_ID = "STORE_BLR_001"
BASE_DATE = datetime(2026, 4, 10, 12, 0, 0)

CAMERAS = {
    "CAM_ENTRY_01": "entry",
    "CAM_FLOOR_01": "floor",
    "CAM_FLOOR_02": "floor",
    "CAM_BILLING_01": "billing",
    "CAM_ENTRY_02": "entry_secondary",
}

FLOOR_ZONES = {
    "CAM_FLOOR_01": ["SKINCARE", "MAKEUP"],
    "CAM_FLOOR_02": ["HAIRCARE", "BODYCARE"],
}

SKU_ZONES = {
    "SKINCARE": "SKINCARE",
    "MAKEUP": "MAKEUP",
    "HAIRCARE": "HAIRCARE",
    "BODYCARE": "BODYCARE",
}

events = []
visitor_counter = 1
session_counter = {}


def make_event(
    camera_id, visitor_id, event_type, timestamp,
    zone_id=None, dwell_ms=0, is_staff=False,
    confidence=None, metadata=None
):
    if confidence is None:
        confidence = round(random.uniform(0.72, 0.98), 3)
    return {
        "event_id": str(uuid.uuid4()),
        "store_id": STORE_ID,
        "camera_id": camera_id,
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "zone_id": zone_id,
        "dwell_ms": dwell_ms,
        "is_staff": is_staff,
        "confidence": confidence,
        "metadata": metadata or {}
    }


def next_visitor():
    global visitor_counter
    vid = f"VIS_{visitor_counter:06d}"
    visitor_counter += 1
    session_counter[vid] = 0
    return vid


def next_seq(visitor_id):
    session_counter[visitor_id] = session_counter.get(visitor_id, 0) + 1
    return session_counter[visitor_id]


# --- Generate 2 staff members ---
for s in range(1, 3):
    staff_id = f"VIS_STAFF_{s:03d}"
    session_counter[staff_id] = 0
    t = BASE_DATE + timedelta(minutes=random.randint(0, 10))

    events.append(make_event("CAM_ENTRY_01", staff_id, "ENTRY", t,
                              is_staff=True, confidence=0.97,
                              metadata={"session_seq": next_seq(staff_id)}))

    # Staff roam all zones
    for zone_cam, zones in FLOOR_ZONES.items():
        for zone in zones:
            zt = t + timedelta(minutes=random.randint(5, 20))
            events.append(make_event(zone_cam, staff_id, "ZONE_ENTER", zt,
                                     zone_id=zone, is_staff=True,
                                     metadata={"sku_zone": SKU_ZONES.get(zone), "session_seq": next_seq(staff_id)}))
            dwell_t = zt + timedelta(minutes=random.randint(30, 60))
            events.append(make_event(zone_cam, staff_id, "ZONE_DWELL", dwell_t,
                                     zone_id=zone, dwell_ms=random.randint(30000, 90000),
                                     is_staff=True,
                                     metadata={"sku_zone": SKU_ZONES.get(zone), "session_seq": next_seq(staff_id)}))


# --- Generate 35 customer sessions ---
# Spread across 12:15 to 21:30
for i in range(35):
    visitor_id = next_visitor()
    offset_minutes = random.randint(15, 570)  # 12:15 to 21:30
    entry_time = BASE_DATE + timedelta(minutes=offset_minutes)

    # ENTRY
    events.append(make_event("CAM_ENTRY_01", visitor_id, "ENTRY", entry_time,
                              metadata={"session_seq": next_seq(visitor_id)}))

    # Visit 1-3 zones
    num_zones = random.randint(1, 3)
    visited_zones = []
    zone_time = entry_time + timedelta(minutes=random.randint(1, 3))

    for _ in range(num_zones):
        cam = random.choice(list(FLOOR_ZONES.keys()))
        zone = random.choice(FLOOR_ZONES[cam])
        if zone in visited_zones:
            continue
        visited_zones.append(zone)

        events.append(make_event(cam, visitor_id, "ZONE_ENTER", zone_time,
                                 zone_id=zone,
                                 metadata={"sku_zone": SKU_ZONES.get(zone), "session_seq": next_seq(visitor_id)}))

        dwell_seconds = random.randint(20, 180)
        if dwell_seconds >= 30:
            dwell_time = zone_time + timedelta(seconds=30)
            events.append(make_event(cam, visitor_id, "ZONE_DWELL", dwell_time,
                                     zone_id=zone, dwell_ms=dwell_seconds * 1000,
                                     metadata={"sku_zone": SKU_ZONES.get(zone), "session_seq": next_seq(visitor_id)}))

        events.append(make_event(cam, visitor_id, "ZONE_EXIT",
                                 zone_time + timedelta(seconds=dwell_seconds),
                                 zone_id=zone,
                                 metadata={"sku_zone": SKU_ZONES.get(zone), "session_seq": next_seq(visitor_id)}))

        zone_time += timedelta(seconds=dwell_seconds + random.randint(10, 60))

    # ~60% go to billing
    goes_to_billing = random.random() < 0.60
    if goes_to_billing:
        billing_time = zone_time + timedelta(minutes=random.randint(1, 3))
        queue_depth = random.randint(0, 4)

        if queue_depth > 0:
            events.append(make_event("CAM_BILLING_01", visitor_id, "BILLING_QUEUE_JOIN",
                                     billing_time, zone_id="BILLING",
                                     metadata={"queue_depth": queue_depth, "session_seq": next_seq(visitor_id)}))
        else:
            events.append(make_event("CAM_BILLING_01", visitor_id, "ZONE_ENTER",
                                     billing_time, zone_id="BILLING",
                                     metadata={"session_seq": next_seq(visitor_id)}))

        # ~20% abandon queue
        abandons = queue_depth > 0 and random.random() < 0.20
        if abandons:
            abandon_time = billing_time + timedelta(minutes=random.randint(2, 5))
            events.append(make_event("CAM_BILLING_01", visitor_id, "BILLING_QUEUE_ABANDON",
                                     abandon_time, zone_id="BILLING",
                                     metadata={"session_seq": next_seq(visitor_id)}))

    # EXIT
    exit_time = zone_time + timedelta(minutes=random.randint(2, 10))
    events.append(make_event("CAM_ENTRY_01", visitor_id, "EXIT", exit_time,
                             metadata={"session_seq": next_seq(visitor_id)}))

    # ~10% re-enter
    if random.random() < 0.10:
        reentry_time = exit_time + timedelta(minutes=random.randint(2, 8))
        events.append(make_event("CAM_ENTRY_01", visitor_id, "REENTRY", reentry_time,
                                 metadata={"session_seq": next_seq(visitor_id)}))
        # Quick exit after re-entry
        events.append(make_event("CAM_ENTRY_01", visitor_id, "EXIT",
                                 reentry_time + timedelta(minutes=random.randint(3, 10)),
                                 metadata={"session_seq": next_seq(visitor_id)}))


# Sort by timestamp
events.sort(key=lambda e: e["timestamp"])

# Write to file
output_path = Path(__file__).parent.parent / "data" / "events.jsonl"
output_path.parent.mkdir(parents=True, exist_ok=True)

with open(output_path, "w") as f:
    for event in events:
        f.write(json.dumps(event) + "\n")

print(f"Generated {len(events)} events → {output_path}")

# Summary
from collections import Counter
type_counts = Counter(e["event_type"] for e in events)
staff_count = sum(1 for e in events if e["is_staff"])
print("\nEvent type breakdown:")
for et, count in sorted(type_counts.items()):
    print(f"  {et}: {count}")
print(f"\nStaff events: {staff_count}")
print(f"Customer events: {len(events) - staff_count}")
