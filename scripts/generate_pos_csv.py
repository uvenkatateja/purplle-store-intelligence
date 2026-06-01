"""
Generate pos_transactions.csv for STORE_BLR_001 on 2026-04-10.
101 transactions, time range 12:15 to 21:39.
Run: python scripts/generate_pos_csv.py
"""

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)

STORE_ID = "STORE_BLR_001"
STORE_NAME = "Brigade_Bangalore"

PRODUCTS = [
    ("Lakme Absolute Skin Natural Mousse", "Foundation", 699),
    ("Maybelline Fit Me Foundation", "Foundation", 549),
    ("L'Oreal Paris Revitalift Serum", "Serum", 1299),
    ("Neutrogena Hydro Boost Gel", "Moisturiser", 899),
    ("Biotique Bio Honey Gel", "Moisturiser", 249),
    ("Dove Body Lotion", "Body Lotion", 349),
    ("Himalaya Neem Face Wash", "Face Wash", 199),
    ("Plum Green Tea Toner", "Toner", 449),
    ("Minimalist Niacinamide Serum", "Serum", 599),
    ("WOW Skin Science Vitamin C Serum", "Serum", 799),
    ("Mamaearth Onion Hair Oil", "Hair Oil", 399),
    ("Pantene Pro-V Shampoo", "Shampoo", 299),
    ("TRESemme Keratin Smooth Shampoo", "Shampoo", 449),
    ("Streax Hair Serum", "Hair Serum", 199),
    ("Garnier Micellar Water", "Cleanser", 349),
    ("Nykaa Cosmetics Lipstick", "Lipstick", 499),
    ("Sugar Cosmetics Matte Lipstick", "Lipstick", 599),
    ("Colorbar Eyeshadow Palette", "Eye Makeup", 1299),
    ("Faces Canada Blush", "Blush", 699),
    ("Kama Ayurveda Rose Water", "Toner", 549),
]

SALESPERSON_IDS = ["SP_001", "SP_002", "SP_003", "SP_004"]

# Generate 101 transactions spread across 12:15 to 21:39
base_date = datetime(2026, 4, 10)
start_minutes = 12 * 60 + 15   # 12:15
end_minutes = 21 * 60 + 39     # 21:39
total_minutes = end_minutes - start_minutes  # 564 minutes

# Spread transactions with higher density in afternoon (14:00-18:00)
transaction_times = []
for _ in range(101):
    # Weighted random: 60% in 14:00-18:00, 40% rest of day
    if random.random() < 0.60:
        # Peak hours: 14:00-18:00
        offset = random.randint(14 * 60 - 12 * 60, 18 * 60 - 12 * 60)
    else:
        offset = random.randint(15, total_minutes)
    transaction_times.append(start_minutes + offset)

transaction_times.sort()

rows = []
for i, total_minutes_offset in enumerate(transaction_times):
    txn_time = base_date + timedelta(minutes=total_minutes_offset)
    product = random.choice(PRODUCTS)
    
    # Some transactions have multiple items
    num_items = random.choices([1, 2, 3], weights=[0.6, 0.3, 0.1])[0]
    total_amount = sum(random.choice(PRODUCTS)[2] for _ in range(num_items))
    
    rows.append({
        "order_id": f"ORD_{i+1:05d}",
        "order_date": txn_time.strftime("%Y-%m-%d"),
        "order_time": txn_time.strftime("%H:%M:%S"),
        "store_id": STORE_ID,
        "store_name": STORE_NAME,
        "product_name": product[0],
        "sub_category": product[1],
        "total_amount": total_amount,
        "salesperson_id": random.choice(SALESPERSON_IDS),
    })

output_path = Path(__file__).parent.parent / "data" / "pos_transactions.csv"
output_path.parent.mkdir(parents=True, exist_ok=True)

with open(output_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)

print(f"Generated {len(rows)} transactions → {output_path}")
print(f"Time range: {rows[0]['order_time']} to {rows[-1]['order_time']}")
print(f"Total revenue: ₹{sum(r['total_amount'] for r in rows):,}")
