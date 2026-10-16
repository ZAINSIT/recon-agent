"""
generate.py — synthetic reconciliation batch generator.

Produces three files in data/batch_001/:
  orders.csv         the ground truth of what actually happened
  settlements.csv    what the bank sent (corrupted in known ways)
  ground_truth.csv   the mapping settlement -> correct order(s) + corruption type

The corruption model is deterministic given --seed. Same seed -> same batch.
This is the foundation of the project; if ground truth is wrong,
every metric downstream is wrong.
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import pandas as pd
from faker import Faker

CorruptionType = Literal[
    "clean",
    "truncated_ref",
    "substituted_digit",
    "merged",
    "partial_refund",
    "fee_difference",
    "duplicate",
    "unmatched_noise",
]

# Corruption frequencies. Must sum to 1.0.
# Chosen to mirror what a real bank feed looks like: mostly clean,
# a long tail of messy shapes.
CORRUPTION_MIX: dict[CorruptionType, float] = {
    "clean":           0.65,
    "truncated_ref":   0.08,
    "substituted_digit": 0.05,
    "merged":          0.05,
    "partial_refund":  0.05,
    "fee_difference":  0.05,
    "duplicate":       0.04,
    "unmatched_noise": 0.03,
}

CURRENCY = "INR"
REF_PREFIX = "ORD"


@dataclass
class Order:
    order_id: str
    amount: float
    currency: str
    customer_id: str
    created_at: str
    status: str
    refund_amount: float
    fee: float


@dataclass
class SettlementLine:
    settlement_id: str
    reference: str          # may be corrupted
    amount: float           # may be corrupted
    currency: str
    settled_at: str
    narration: str


@dataclass
class GroundTruthRow:
    settlement_id: str
    corruption_type: CorruptionType
    correct_order_ids: str  # JSON list
    correct_amount_delta: float
    split: str = "unassigned"


def _make_order_id(seq: int) -> str:
    return f"{REF_PREFIX}-2026-{seq:05d}"


def build_orders(n: int, rng: random.Random, fake: Faker) -> list[Order]:
    """Generate n clean orders. This is the truth."""
    base = datetime(2026, 9, 1, 9, 0, 0)
    orders: list[Order] = []
    for i in range(1, n + 1):
        amount = round(rng.uniform(50, 5000), 2)
        # ~8% of orders have a refund; ~30% have a fee recorded
        refund = round(amount * rng.uniform(0.1, 0.6), 2) if rng.random() < 0.08 else 0.0
        fee = round(amount * rng.uniform(0.005, 0.02), 2) if rng.random() < 0.30 else 0.0
        orders.append(
            Order(
                order_id=_make_order_id(i),
                amount=amount,
                currency=CURRENCY,
                customer_id=f"CUST-{fake.random_int(1000, 9999)}",
                created_at=(base + timedelta(minutes=i * 7)).isoformat(),
                status="paid",
                refund_amount=refund,
                fee=fee,
            )
        )
    return orders


def _corrupt_reference(order_id: str, rng: random.Random) -> str:
    """Produce a plausible mangled reference from a clean order_id."""
    style = rng.choice(["truncate_suffix", "drop_zeros", "spaces", "lowercase"])
    if style == "truncate_suffix":
        return order_id[:-rng.randint(1, 3)]
    if style == "drop_zeros":
        # ORD-2026-00042 -> ORD-2026-42
        head, tail = order_id.rsplit("-", 1)
        return f"{head}-{int(tail)}"
    if style == "spaces":
        return order_id.replace("-", " ")
    return order_id.lower()


def _substitute_digit(order_id: str, rng: random.Random) -> str:
    """
    Change one digit in the reference to a different digit.

    'ORD-2026-00173' -> 'ORD-2026-00179' (or similar).

    The result is NOT recoverable by normalized-exact lookup:
    it does not equal any real order id. It must be found by
    similarity scoring, which is what exercises the threshold.
    """
    digits = [i for i, c in enumerate(order_id) if c.isdigit()]
    if not digits:
        return order_id
    pos = rng.choice(digits)
    original = order_id[pos]
    replacement = rng.choice([d for d in "0123456789" if d != original])
    return order_id[:pos] + replacement + order_id[pos + 1:]


def build_settlements(
    orders: list[Order],
    rng: random.Random,
    fake: Faker,
) -> tuple[list[SettlementLine], list[GroundTruthRow]]:
    """
    Walk orders, pick a corruption type per settlement, and emit
    a settlement line + ground-truth row.

    'unmatched_noise' is generated in a second pass: it has no source
    order, so it must not consume one. Every real order must appear in
    exactly one ground-truth row.
    """
    # Types that map to real orders, and therefore consume one.
    mapped_types = [
        "clean",
        "truncated_ref",
        "substituted_digit",
        "merged",
        "partial_refund",
        "fee_difference",
        "duplicate",
    ]
    # Renormalise the weights over the mapped types only.
    total_w = sum(CORRUPTION_MIX[t] for t in mapped_types)
    mapped_weights = [CORRUPTION_MIX[t] / total_w for t in mapped_types]

    settlements: list[SettlementLine] = []
    truths: list[GroundTruthRow] = []

    seq = 0
    i = 0
    while i < len(orders):
        remaining = len(orders) - i
        allowed = mapped_types if remaining >= 2 else [
            t for t in mapped_types if t != "merged"
        ]
        allowed_w = [CORRUPTION_MIX[t] for t in allowed]
        ctype = rng.choices(allowed, weights=allowed_w, k=1)[0]

        order = orders[i]
        seq += 1
        sid = f"STL-{seq:05d}"

        settled_at = (
            datetime.fromisoformat(order.created_at) + timedelta(hours=rng.randint(1, 48))
        ).isoformat()

        if ctype == "clean":
            settlements.append(SettlementLine(sid, order.order_id, order.amount,
                                              CURRENCY, settled_at, f"UPI/{order.order_id}"))
            truths.append(GroundTruthRow(sid, ctype, json.dumps([order.order_id]), 0.0))
            i += 1

        elif ctype == "truncated_ref":
            ref = _corrupt_reference(order.order_id, rng)
            settlements.append(SettlementLine(sid, ref, order.amount,
                                              CURRENCY, settled_at, f"UPI/{ref}"))
            truths.append(GroundTruthRow(sid, ctype, json.dumps([order.order_id]), 0.0))
            i += 1
        elif ctype == "substituted_digit":
            ref = _substitute_digit(order.order_id, rng)
            settlements.append(
                SettlementLine(
                    settlement_id=sid,
                    reference=ref,
                    amount=order.amount,
                    currency=CURRENCY,
                    settled_at=settled_at,
                    narration=f"UPI/{ref}",
                )
            )
            truths.append(GroundTruthRow(sid, ctype, json.dumps([order.order_id]), 0.0))
            i += 1

        elif ctype == "merged":
            k = min(rng.choice([2, 2, 3]), remaining)
            group = orders[i : i + k]
            total = round(sum(o.amount for o in group), 2)
            refs = ",".join(o.order_id for o in group)
            settlements.append(SettlementLine(sid, refs, total, CURRENCY,
                                              settled_at, f"BULK SETTLEMENT {len(group)} ORDERS"))
            truths.append(GroundTruthRow(sid, ctype,
                                         json.dumps([o.order_id for o in group]), 0.0))
            i += k

        elif ctype == "partial_refund":
            delta = order.refund_amount or round(order.amount * 0.3, 2)
            settlements.append(SettlementLine(sid, order.order_id,
                                              round(order.amount - delta, 2),
                                              CURRENCY, settled_at,
                                              f"UPI/{order.order_id} REFUND ADJ"))
            truths.append(GroundTruthRow(sid, ctype, json.dumps([order.order_id]),
                                         -round(delta, 2)))
            i += 1

        elif ctype == "fee_difference":
            delta = order.fee or round(order.amount * 0.01, 2)
            settlements.append(SettlementLine(sid, order.order_id,
                                              round(order.amount - delta, 2),
                                              CURRENCY, settled_at,
                                              f"UPI/{order.order_id} FEE DED"))
            truths.append(GroundTruthRow(sid, ctype, json.dumps([order.order_id]),
                                         -round(delta, 2)))
            i += 1

        elif ctype == "duplicate":
            settlements.append(SettlementLine(sid, order.order_id, order.amount,
                                              CURRENCY, settled_at, f"UPI/{order.order_id}"))
            truths.append(GroundTruthRow(sid, ctype, json.dumps([order.order_id]), 0.0))
            seq += 1
            dup_sid = f"STL-{seq:05d}"
            settlements.append(SettlementLine(dup_sid, order.order_id, order.amount,
                                              CURRENCY, settled_at,
                                              f"UPI/{order.order_id} DUPLICATE"))
            truths.append(GroundTruthRow(dup_sid, ctype,
                                         json.dumps([order.order_id]), 0.0))
            i += 1

        else:
            raise ValueError(f"unknown corruption type: {ctype}")

    # Second pass: unmatched_noise settlements have no source order.
    # Target count is CORRUPTION_MIX['unmatched_noise'] * len(orders),
    # rounded to the nearest int.
    n_noise = round(CORRUPTION_MIX["unmatched_noise"] * len(orders))
    base_time = datetime(2026, 9, 1, 9, 0, 0)
    for _ in range(n_noise):
        seq += 1
        sid = f"STL-{seq:05d}"
        fake_ref = f"ORD-2026-{rng.randint(90000, 99999)}"
        settled_at = (base_time + timedelta(hours=rng.randint(1, 720))).isoformat()
        settlements.append(SettlementLine(sid, fake_ref,
                                          round(rng.uniform(50, 5000), 2),
                                          CURRENCY, settled_at,
                                          f"UPI/{fake_ref} UNKNOWN"))
        truths.append(GroundTruthRow(sid, "unmatched_noise", json.dumps([]), 0.0))

    return settlements, truths

def write_batch(
    out_dir: Path,
    orders: list[Order],
    settlements: list[SettlementLine],
    truths: list[GroundTruthRow],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([asdict(o) for o in orders]).to_csv(
        out_dir / "orders.csv", index=False
    )
    pd.DataFrame([asdict(s) for s in settlements]).to_csv(
        out_dir / "settlements.csv", index=False
    )
    pd.DataFrame([asdict(t) for t in truths]).to_csv(
        out_dir / "ground_truth.csv", index=False
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n", type=int, default=500, help="number of orders")
    parser.add_argument("--out", type=Path, default=Path("data/batch_001"))
    args = parser.parse_args()

    rng = random.Random(args.seed)
    Faker.seed(args.seed)
    fake = Faker("en_IN")

    orders = build_orders(args.n, rng, fake)
    settlements, truths = build_settlements(orders, rng, fake)
    write_batch(args.out, orders, settlements, truths)

    # Print a summary so the operator can see the mix at a glance.
    df = pd.DataFrame([asdict(t) for t in truths])
    print(f"Wrote batch to {args.out}")
    print(f"  orders:      {len(orders)}")
    print(f"  settlements: {len(settlements)}")
    print()
    print("Corruption mix (actual):")
    print(df["corruption_type"].value_counts(normalize=True).round(3).to_string())


if __name__ == "__main__":
    main()