import json
from collections import Counter
from pathlib import Path

import pandas as pd

batch = Path("data/batch_001")
orders = pd.read_csv(batch / "orders.csv")
gt = pd.read_csv(batch / "ground_truth.csv")

matched = []
for s in gt["correct_order_ids"]:
    matched.extend(json.loads(s))

c = Counter(matched)
order_ids = set(orders["order_id"])

print("orders:", len(order_ids))
print("orders appearing in ground truth:", len(c))
print("orders missing from ground truth:", len(order_ids - set(c)))
print("orders appearing more than once:", sum(1 for v in c.values() if v > 1))
print()

dup_rows = (gt["corruption_type"] == "duplicate").sum()
print("duplicate ground-truth rows:", dup_rows)
print("duplicate events (pairs):", dup_rows // 2)
print("orders matched twice:", sum(1 for v in c.values() if v == 2))

# Fail loudly if the invariant is broken.
missing = len(order_ids - set(c))
if missing != 0:
    raise SystemExit(f"INVARIANT FAILED: {missing} orders missing from ground truth")
print()
print("INVARIANT OK: every order appears in ground truth")
