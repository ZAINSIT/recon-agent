"""
tune_threshold.py — sweep the fuzzy threshold on DEV ONLY.

For each threshold, run Stage 2, evaluate on the dev split, and record
match rate and wrong-match rate. The held-out split is never touched here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import stage2_fuzzy  # noqa: E402

BATCH = Path("data/batch_001")
STAGE1 = BATCH / "matched_ledger_stage1.csv"
THRESHOLDS = [0.60, 0.70, 0.75, 0.80, 0.85, 0.88, 0.90, 0.92, 0.95, 0.99]


def eval_on_split(ledger: pd.DataFrame, split: str) -> dict:
    gt = pd.read_csv(BATCH / "ground_truth.csv")
    gt = gt[gt["split"] == split]
    m = gt.merge(ledger, on="settlement_id")

    def to_set(s):
        if pd.isna(s):
            return set()
        return set(json.loads(s))

    m["pred"] = m["matched_order_ids"].apply(to_set)
    m["truth"] = m["correct_order_ids"].apply(to_set)
    m["is_match"] = m["pred"].apply(len) > 0
    m["is_correct"] = m["is_match"] & (m["pred"] == m["truth"])
    m["is_wrong"] = m["is_match"] & ~m["is_correct"]

    total = len(m)
    matched = int(m["is_match"].sum())
    correct = int(m["is_correct"].sum())
    wrong = int(m["is_wrong"].sum())
    return {
        "total": total,
        "matched": matched,
        "correct": correct,
        "wrong": wrong,
        "match_rate": round(matched / total, 4),
        "wrong_match_rate": round(wrong / max(matched, 1), 4),
        "precision": round(correct / max(matched, 1), 4),
        "recall": round(correct / total, 4),
    }


def main() -> None:
    rows = []
    for t in THRESHOLDS:
        ledger = stage2_fuzzy.run(BATCH, STAGE1, t)
        dev = eval_on_split(ledger, "dev")
        rows.append({"threshold": t, **dev})
        print(
            f"t={t:.2f}  match={dev['match_rate']:.4f}  "
            f"recall={dev['recall']:.4f}  wrong={dev['wrong']}  "
            f"precision={dev['precision']:.4f}"
        )

    df = pd.DataFrame(rows)
    df.to_csv("eval/threshold_sweep.csv", index=False)
    print("\nWrote eval/threshold_sweep.csv")


if __name__ == "__main__":
    main()