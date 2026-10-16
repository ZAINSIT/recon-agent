"""
stage2_fuzzy.py — deterministic fuzzy matching on the Stage 1 remainder.

Runs AFTER Stage 1. Takes the settlements Stage 1 left unresolved and tries
three deterministic strategies, in order of confidence:

  1. Normalized-reference match   (truncated_ref, spacing/zero-padding variants)
  2. Merged-payment detection      (one settlement = sum of 2-3 unmatched orders)
  3. Refund / fee adjustment       (clean reference, amount differs by a plausible delta)

No LLM. The LLM only appears in Stage 3, on what's left after this.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import pandas as pd

DEFAULT_BATCH = Path("data/batch_001")
DEFAULT_THRESHOLD = 0.85  # similarity in [0, 1]; tuned on dev, not heldout

LEDGER_COLUMNS = [
    "settlement_id",
    "stage",
    "matched_order_ids",
    "confidence",
    "method_detail",
    "llm_proposal",
    "validator_result",
    "validator_reason",
    "runtime_ms",
]


# ---------- normalization ----------

def normalize_reference(ref: str) -> str:
    """
    Canonical form for comparison.

    'ORD-2026-00042', 'ORD 2026 42', 'ord-2026-42' all -> 'ord-2026-42'.

    Rules: lowercase, split on any non-alphanumeric, drop leading zeros
    in numeric segments, rejoin with '-'.
    """
    parts = re.split(r"[^a-z0-9]+", ref.lower())
    parts = [p for p in parts if p]
    # Drop leading zeros in purely numeric segments.
    out = []
    for p in parts:
        if p.isdigit():
            out.append(str(int(p)))
        else:
            out.append(p)
    return "-".join(out)


def levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(min(
                prev[j] + 1,        # delete
                curr[j - 1] + 1,    # insert
                prev[j - 1] + (ca != cb),  # substitute
            ))
        prev = curr
    return prev[-1]


def score_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    dist = levenshtein(a, b)
    return 1.0 - (dist / max(len(a), len(b)))


# ---------- the three strategies ----------

def try_normalized(
    settlement_ref: str,
    amount: float,
    orders_by_norm: dict[str, str],
    orders_by_id: dict[str, dict],
    threshold: float,
    amount_tolerance: float = 0.01,
) -> tuple[list[str], str, float] | None:
    """
    Normalized-reference match, gated on amount agreement.

    A truncated reference can collide with a real, different order
    (e.g. ORD-2026-0017 is both a truncation of ORD-2026-00173 and
    a real ORD-2026-00017). The reference alone cannot disambiguate.
    Require the amount to agree before accepting the match; if it
    doesn't, fall through to refund/fee logic.
    """
    norm = normalize_reference(settlement_ref)

    candidate = orders_by_norm.get(norm)
    if candidate is not None:
        order_amount = float(orders_by_id[candidate]["amount"])
        if abs(order_amount - amount) <= amount_tolerance:
            return [candidate], "normalized_exact", 1.0
        # Amount disagrees: this is a reference collision, not a match.
        # Fall through to the fuzzy path, and if that finds nothing,
        # the refund/fee logic will handle "right ref, wrong amount".

    best_id, best_score = None, 0.0
    for order_norm, order_id in orders_by_norm.items():
        s = score_similarity(norm, order_norm)
        if s > best_score:
            best_score, best_id = s, order_id
    if best_score >= threshold and best_id is not None:
        order_amount = float(orders_by_id[best_id]["amount"])
        if abs(order_amount - amount) <= amount_tolerance:
            return [best_id], f"fuzzy_ref:{best_score:.2f}", best_score
    return None


def try_merged_sum(
    amount: float,
    unmatched_orders: list[tuple[str, float]],
    tolerance: float = 0.01,
) -> tuple[list[str], str] | None:
    """
    One settlement covering 2-3 orders. Brute-force over pairs/triples.
    Returns (order_ids, method_detail) or None.
    """
    n = len(unmatched_orders)
    # pairs
    for i in range(n):
        for j in range(i + 1, n):
            total = unmatched_orders[i][1] + unmatched_orders[j][1]
            if abs(total - amount) <= tolerance:
                return (
                    [unmatched_orders[i][0], unmatched_orders[j][0]],
                    "merged_sum_2",
                )
    # triples (bounded; only if the list is small enough to afford it)
    if n <= 60:
        for i in range(n):
            for j in range(i + 1, n):
                for k in range(j + 1, n):
                    total = (
                        unmatched_orders[i][1]
                        + unmatched_orders[j][1]
                        + unmatched_orders[k][1]
                    )
                    if abs(total - amount) <= tolerance:
                        return (
                            [
                                unmatched_orders[i][0],
                                unmatched_orders[j][0],
                                unmatched_orders[k][0],
                            ],
                            "merged_sum_3",
                        )
    return None


def try_refund_or_fee(
    settlement_ref: str,
    amount: float,
    orders_by_id: dict[str, dict],
    tolerance: float = 0.01,
) -> tuple[list[str], str, float] | None:
    """
    Clean reference, amount is lower. Accept only when the difference
    matches a refund or fee that is actually recorded on the order.

    The inferred fallbacks (any shortfall 5-60% -> refund) were removed:
    they produced four wrong matches on batch_001, because a truncated or
    substituted reference can name a different real order, and the
    fallback then "explained" a shortfall that belonged to a different
    order entirely. Unresolved is honest; a low-confidence wrong match
    is not. Rows this leaves open go to Stage 3.
    """
    norm = normalize_reference(settlement_ref)
    for order_id, row in orders_by_id.items():
        if normalize_reference(order_id) != norm:
            continue
        delta = round(amount - float(row["amount"]), 2)
        if delta >= 0:
            return None  # not a shortfall
        refund = float(row.get("refund_amount") or 0.0)
        fee = float(row.get("fee") or 0.0)
        if refund and abs(delta + refund) <= tolerance:
            return [order_id], "refund_recorded", delta
        if fee and abs(delta + fee) <= tolerance:
            return [order_id], "fee_recorded", delta
        # No recorded refund or fee matches this delta. Leave it open.
        return None
    return None


# ---------- driver ----------

def run(batch: Path, stage1_ledger: Path, threshold: float) -> pd.DataFrame:
    settlements = pd.read_csv(batch / "settlements.csv")
    orders = pd.read_csv(batch / "orders.csv")
    ledger1 = pd.read_csv(stage1_ledger)

    orders_by_id = {r["order_id"]: r.to_dict() for _, r in orders.iterrows()}
    orders_by_norm = {normalize_reference(k): k for k in orders_by_id}

    # Start from Stage 1's ledger; only rewrite the unresolved rows.
    ledger = ledger1.copy()
    stage1_matched_ids = set(
        ledger.loc[ledger["stage"] == "exact", "settlement_id"]
    )
    unsettled = settlements[~settlements["settlement_id"].isin(stage1_matched_ids)]

    # Orders already consumed by Stage 1 cannot be reused.
    consumed: set[str] = set()
    for s in ledger.loc[ledger["stage"] == "exact", "matched_order_ids"]:
        consumed.update(json.loads(s))
    unmatched_orders = [
        (oid, float(r["amount"]))
        for oid, r in orders_by_id.items()
        if oid not in consumed
    ]

    rows_by_sid = {r["settlement_id"]: r for r in ledger.to_dict("records")}

    for _, s in unsettled.iterrows():
        t0 = time.perf_counter()
        sid = s["settlement_id"]
        ref = str(s["reference"])
        amount = round(float(s["amount"]), 2)

        result = try_normalized(ref, amount, orders_by_norm, orders_by_id, threshold)
        method = None
        matched: list[str] = []
        confidence = "medium"

        if result is not None:
            matched, method, score = result
            confidence = "high" if score >= 0.99 else "medium"

        if not matched:
            merged = try_merged_sum(amount, unmatched_orders)
            if merged is not None:
                matched, method = merged
                confidence = "medium"

        if not matched:
            rf = try_refund_or_fee(ref, amount, orders_by_id)
            if rf is not None:
                matched, method, _ = rf
                confidence = "high" if "recorded" in method else "low"

        if matched:
            rows_by_sid[sid] = {
                "settlement_id": sid,
                "stage": "fuzzy",
                "matched_order_ids": json.dumps(matched),
                "confidence": confidence,
                "method_detail": method,
                "llm_proposal": None,
                "validator_result": None,
                "validator_reason": None,
                "runtime_ms": int((time.perf_counter() - t0) * 1000),
            }
            # Consume the orders so a later settlement can't reuse them.
            for oid in matched:
                consumed.add(oid)
            unmatched_orders = [x for x in unmatched_orders if x[0] not in matched]

    out = pd.DataFrame(list(rows_by_sid.values()))
    # Preserve the original settlement order.
    out = out.set_index("settlement_id").loc[settlements["settlement_id"]].reset_index()
    return out[LEDGER_COLUMNS]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH)
    parser.add_argument(
        "--stage1",
        type=Path,
        default=None,
        help="Stage 1 ledger; defaults to <batch>/matched_ledger_stage1.csv",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="output ledger; defaults to <batch>/matched_ledger_stage2.csv",
    )
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = parser.parse_args()

    stage1 = args.stage1 or (args.batch / "matched_ledger_stage1.csv")
    out_path = args.out or (args.batch / "matched_ledger_stage2.csv")

    ledger = run(args.batch, stage1, args.threshold)
    ledger.to_csv(out_path, index=False)

    stages = ledger["stage"].value_counts().to_dict()
    print(f"Wrote {out_path}  (threshold={args.threshold})")
    for k, v in sorted(stages.items()):
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()