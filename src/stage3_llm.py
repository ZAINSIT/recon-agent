"""
stage3_llm.py — the LLM on the Stage 2 remainder, bounded by the validator.

For each unresolved settlement:
  1. Build a small candidate set of orders (same normalized reference,
     or similar reference, or nearby amount).
  2. Ask the LLM to propose a match with a reason and evidence.
  3. Run the deterministic validator.
  4. Accept only if the validator accepts.

The LLM never decides. It proposes. The validator disposes.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from src import stage2_fuzzy
from src.llm_provider import LLMError, propose
from src.validator import validate

load_dotenv()

DEFAULT_BATCH = Path("data/batch_001")

LEDGER_COLUMNS = [
    "settlement_id", "stage", "matched_order_ids", "confidence",
    "method_detail", "llm_proposal", "validator_result",
    "validator_reason", "runtime_ms",
]

PROMPT_TEMPLATE = """You are reconciling a bank settlement line against a set of candidate orders.

Settlement:
  reference: {reference}
  amount:    {amount}

Candidate orders (choose at most one):
{candidates}

Propose a match. Reply with a JSON object with exactly these keys:
  reason: one of partial_refund, fee_difference, truncated_ref, substituted_digit, no_match
  matched_order_id: the order id you propose, or null if none
  confidence: one of high, medium, low
  evidence: one short sentence explaining the arithmetic or reference match

Rules:
- reason=partial_refund only if the settlement amount is LESS than the order amount by a plausible refund.
- reason=fee_difference only if the settlement amount is LESS than the order amount by a small fee.
- reason=truncated_ref or substituted_digit only if the amounts agree and the references are close.
- If no candidate fits, use reason=no_match and matched_order_id=null.
"""


def _candidates_for(
    ref: str,
    amount: float,
    orders_by_id: dict[str, dict],
    orders_by_norm: dict[str, str],
    limit: int = 5,
) -> dict[str, dict]:
    """Small candidate set: normalized-equal first, then by reference similarity."""
    norm = stage2_fuzzy.normalize_reference(ref)
    picks: list[str] = []
    if norm in orders_by_norm:
        picks.append(orders_by_norm[norm])
    scored = []
    for order_norm, order_id in orders_by_norm.items():
        if order_id in picks:
            continue
        s = stage2_fuzzy.score_similarity(norm, order_norm)
        scored.append((s, order_id))
    scored.sort(reverse=True)
    for _, order_id in scored[: limit - len(picks)]:
        picks.append(order_id)
    return {oid: orders_by_id[oid] for oid in picks}


def _format_candidates(cands: dict[str, dict]) -> str:
    lines = []
    for oid, o in cands.items():
        lines.append(
            f"  {oid}: amount={o['amount']}, "
            f"refund={o.get('refund_amount', 0.0)}, fee={o.get('fee', 0.0)}"
        )
    return "\n".join(lines)


def run(batch: Path, stage2_ledger: Path, limit: int | None = None) -> pd.DataFrame:
    settlements = pd.read_csv(batch / "settlements.csv")
    orders = pd.read_csv(batch / "orders.csv")
    ledger = pd.read_csv(stage2_ledger)

    orders_by_id = {r["order_id"]: r.to_dict() for _, r in orders.iterrows()}
    orders_by_norm = {
        stage2_fuzzy.normalize_reference(k): k for k in orders_by_id
    }

    rows_by_sid = {r["settlement_id"]: r for r in ledger.to_dict("records")}
    unresolved = ledger[ledger["stage"] == "unresolved"]["settlement_id"]
    unresolved_set = settlements[settlements["settlement_id"].isin(unresolved)]
    if limit is not None:
        unresolved_set = unresolved_set.head(limit)

    accepted = rejected = no_match = 0
    for idx, (_, s) in enumerate(unresolved_set.iterrows()):
        if idx > 0:
            time.sleep(4.0)   # ~15 req/min, under the free-tier ceiling
        t0 = time.perf_counter()
        sid = s["settlement_id"]
        ref = str(s["reference"])
        amount = round(float(s["amount"]), 2)

        cands = _candidates_for(ref, amount, orders_by_id, orders_by_norm)
        prompt = PROMPT_TEMPLATE.format(
            reference=ref, amount=amount, candidates=_format_candidates(cands)
        )

        try:
            proposal = propose(prompt)
        except LLMError as e:
            rows_by_sid[sid] = {
                "settlement_id": sid, "stage": "unresolved",
                "matched_order_ids": json.dumps([]),
                "confidence": "n/a", "method_detail": "llm_error",
                "llm_proposal": json.dumps({"error": str(e)}),
                "validator_result": None, "validator_reason": None,
                "runtime_ms": int((time.perf_counter() - t0) * 1000),
            }
            continue

        result = validate(proposal, cands, amount)
        runtime = int((time.perf_counter() - t0) * 1000)

        if result.accepted and result.matched_order_ids:
            # Accepted with a concrete match.
            accepted += 1
            rows_by_sid[sid] = {
                "settlement_id": sid, "stage": "llm",
                "matched_order_ids": json.dumps(result.matched_order_ids),
                "confidence": proposal.get("confidence", "low"),
                "method_detail": f"llm_{proposal.get('reason')}",
                "llm_proposal": json.dumps(proposal),
                "validator_result": "accepted",
                "validator_reason": None,
                "runtime_ms": runtime,
            }
        elif result.accepted and not result.matched_order_ids:
            # The model proposed no match and the validator agreed.
            no_match += 1
            rows_by_sid[sid] = {
                "settlement_id": sid, "stage": "unresolved",
                "matched_order_ids": json.dumps([]),
                "confidence": "n/a",
                "method_detail": "llm_no_match",
                "llm_proposal": json.dumps(proposal),
                "validator_result": "accepted",
                "validator_reason": "no_match",
                "runtime_ms": runtime,
            }
        else:
            # The validator rejected the proposal.
            rejected += 1
            rows_by_sid[sid] = {
                "settlement_id": sid, "stage": "unresolved",
                "matched_order_ids": json.dumps([]),
                "confidence": "n/a",
                "method_detail": "llm_rejected",
                "llm_proposal": json.dumps(proposal),
                "validator_result": "rejected",
                "validator_reason": result.reason,
                "runtime_ms": runtime,
            }

    out = pd.DataFrame(list(rows_by_sid.values()))
    out = out.set_index("settlement_id").loc[settlements["settlement_id"]].reset_index()
    print(f"  llm accepted: {accepted}")
    print(f"  llm no_match: {no_match}")
    print(f"  llm rejected: {rejected}")
    return out[LEDGER_COLUMNS]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH)
    parser.add_argument("--stage2", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    stage2 = args.stage2 or (args.batch / "matched_ledger_stage2.csv")
    out_path = args.out or (args.batch / "matched_ledger_stage3.csv")

    ledger = run(args.batch, stage2, limit=args.limit)
    ledger.to_csv(out_path, index=False)
    print(f"Wrote {out_path}")
    print(ledger["stage"].value_counts().to_string())


if __name__ == "__main__":
    main()