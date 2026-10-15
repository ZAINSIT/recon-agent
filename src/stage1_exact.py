"""
stage1_exact.py — the deterministic floor.

Joins settlements to orders on exact order_id AND exact amount.
No fuzzy. No LLM. Emits one ledger row per settlement.

This is the baseline every later stage is measured against:
maximum precision, low recall. It should match the 'clean' rows
and nothing else. If it produces a wrong match, something is
deeply wrong with the data, not with the matching logic.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd

DEFAULT_BATCH = Path("data/batch_001")
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


def _empty_ledger_row(settlement_id: str, runtime_ms: int) -> dict:
    return {
        "settlement_id": settlement_id,
        "stage": "unresolved",
        "matched_order_ids": json.dumps([]),
        "confidence": "n/a",
        "method_detail": "no_match",
        "llm_proposal": None,
        "validator_result": None,
        "validator_reason": None,
        "runtime_ms": runtime_ms,
    }


def run(batch: Path) -> pd.DataFrame:
    settlements = pd.read_csv(batch / "settlements.csv")
    orders = pd.read_csv(batch / "orders.csv")

    # Index orders by (order_id, amount) for O(1) lookup.
    order_index: dict[tuple[str, float], str] = {}
    for _, row in orders.iterrows():
        order_index[(row["order_id"], round(float(row["amount"]), 2))] = row["order_id"]

    rows: list[dict] = []
    for _, s in settlements.iterrows():
        t0 = time.perf_counter()
        sid = s["settlement_id"]
        ref = str(s["reference"])
        amount = round(float(s["amount"]), 2)

        key = (ref, amount)
        matched_id = order_index.get(key)

        if matched_id is not None:
            row = {
                "settlement_id": sid,
                "stage": "exact",
                "matched_order_ids": json.dumps([matched_id]),
                "confidence": "high",
                "method_detail": "exact_match",
                "llm_proposal": None,
                "validator_result": None,
                "validator_reason": None,
                "runtime_ms": int((time.perf_counter() - t0) * 1000),
            }
        else:
            row = _empty_ledger_row(sid, int((time.perf_counter() - t0) * 1000))

        rows.append(row)

    return pd.DataFrame(rows, columns=LEDGER_COLUMNS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    out = args.out or (args.batch / "matched_ledger_stage1.csv")
    ledger = run(args.batch)
    ledger.to_csv(out, index=False)

    matched = (ledger["stage"] == "exact").sum()
    unresolved = (ledger["stage"] == "unresolved").sum()
    print(f"Wrote {out}")
    print(f"  settlements: {len(ledger)}")
    print(f"  matched:     {matched}")
    print(f"  unresolved:  {unresolved}")


if __name__ == "__main__":
    main()