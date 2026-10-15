"""
harness.py — compare a matched ledger against ground truth.

Reads:
  data/batch_001/ground_truth.csv
  data/batch_001/matched_ledger_stage1.csv   (or whichever ledger is passed)

Writes:
  eval/metrics.json    (raw numbers, ignored by git)
  eval/report.md       (human-readable, committed)

The 'wrong match rate' is the metric that matters. Match rate alone
rewards lowering thresholds; wrong match rate punishes it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from collections import Counter

import pandas as pd

DEFAULT_BATCH = Path("data/batch_001")
DEFAULT_LEDGER = "matched_ledger_stage1.csv"



def _to_set(s) -> set[str]:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return set()
    try:
        return set(json.loads(s))
    except (TypeError, json.JSONDecodeError):
        return set()


def evaluate(gt: pd.DataFrame, ledger: pd.DataFrame) -> dict:
    merged = gt.merge(ledger, on="settlement_id", how="left", suffixes=("_gt", "_l"))
    merged["predicted"] = merged["matched_order_ids"].apply(_to_set)
    merged["truth"] = merged["correct_order_ids"].apply(_to_set)

    merged["is_match"] = merged["predicted"].apply(len) > 0
    merged["is_correct"] = (
         (merged["predicted"].apply(len) > 0)
         & (merged["predicted"] == merged["truth"])
    )
    merged["is_correctly_unmatched"] = (
    (merged["predicted"].apply(len) == 0)
    & (merged["truth"].apply(len) == 0)
    )
    # A wrong match: predicted something, but not the truth.
    merged["is_wrong"] = merged["is_match"] & ~merged["is_correct"]
    # Unresolved: predicted nothing when something was expected, or vice versa.
    merged["is_unresolved"] = (~merged["is_match"]) & (merged["truth"].apply(len) > 0)

    out: dict = {}
    for split in ("dev", "heldout"):
        s = merged[merged["split"] == split]
        if len(s) == 0:
            continue
        total = len(s)
        matched = int(s["is_match"].sum())
        correct = int(s["is_correct"].sum())
        wrong = int(s["is_wrong"].sum())
        unresolved = int(s["is_unresolved"].sum())
        correctly_unmatched = int(s["is_correctly_unmatched"].sum())
        out[split] = {
            "total": total,
            "matched": matched,
            "correct": correct,
            "wrong": wrong,
            "correctly_unmatched": correctly_unmatched,
            "unresolved": unresolved,
            "match_rate": round(matched / total, 4),
            "wrong_match_rate": round(wrong / max(matched, 1), 4),
            "precision": round(correct / max(matched, 1), 4),
            "recall": round(correct / max(total, 1), 4),
        }

    # Per-corruption breakdown, on all rows.
        # Per-corruption breakdown, on all rows.
    by_type: dict = {}
    for ctype, group in merged.groupby("corruption_type"):
        by_type[ctype] = {
            "count": len(group),
            "correct": int(group["is_correct"].sum()),
            "wrong": int(group["is_wrong"].sum()),
            "unresolved": int(group["is_unresolved"].sum()),
        }
    out["by_corruption_type"] = by_type

    # Double matches: orders matched by more than one settlement.
    # A duplicate pair maps both lines to the same order. Both matches are
    # correct (the ground truth says both refer to that order), but two
    # settlements pointing at one order is a finding worth reporting.
    all_matched: list[str] = []
    for s in merged["predicted"]:
        all_matched.extend(s)
    counts = Counter(all_matched)
    double_matched = {k: v for k, v in counts.items() if v > 1}

    out["double_matched_orders"] = len(double_matched)
    out["double_matched_detail"] = {
        "orders": len(double_matched),
        "extra_settlements": sum(v - 1 for v in double_matched.values()),
    }

    return out


def write_report(metrics: dict, ledger_name: str, out_path: Path) -> None:
    lines: list[str] = []
    lines.append("# Evaluation report\n")
    lines.append(f"Ledger: `{ledger_name}`\n")
    lines.append("## Headline (held-out split)\n")
    h = metrics.get("heldout") or metrics.get("dev")
    if h:
        lines.append("| Metric | Value |")
        lines.append("|---|---|")
        for k in ("total", "matched", "correct", "wrong", "unresolved",
                  "match_rate", "wrong_match_rate", "precision", "recall"):
            lines.append(f"| {k} | {h[k]} |")
        lines.append("")

    lines.append("## Per-corruption-type breakdown\n")
    lines.append("| Type | Count | Correct | Wrong | Unresolved |")
    lines.append("|---|---|---|---|---|")
    for ctype, v in sorted(metrics["by_corruption_type"].items()):
        lines.append(
            f"| {ctype} | {v['count']} | {v['correct']} | {v['wrong']} | {v['unresolved']} |"
        )
    lines.append("")
    lines.append("## Duplicate detection\n")
    dm = metrics.get("double_matched_detail", {})
    lines.append(
        f"- Orders matched by more than one settlement: **{dm.get('orders', 0)}**\n"
        f"- Extra settlements pointing at those orders: {dm.get('extra_settlements', 0)}\n"
    )
    lines.append(
        "Both lines of a duplicate pair map to the same order. Both matches are "
        "correct by ground truth. Two settlements pointing at one order is a "
        "finding, not a wrong match. See D-07.\n"
    )

    lines.append("## How to read these numbers\n")
    lines.append(
        "- `wrong_match_rate` is the honest metric: matches that are incorrect.\n"
        "- `unresolved` counts settlements that matched nothing but should have.\n"
        "- Stage 1 is the deterministic floor. Wrong matches should be 0; "
        "unresolved should equal everything that is not `clean`.\n"
    )

    out_path.write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH)
    parser.add_argument("--ledger", default=DEFAULT_LEDGER)
    parser.add_argument("--report", type=Path, default=Path("eval/report.md"))
    parser.add_argument("--metrics", type=Path, default=Path("eval/metrics.json"))
    args = parser.parse_args()

    gt = pd.read_csv(args.batch / "ground_truth.csv")
    ledger = pd.read_csv(args.batch / args.ledger)

    metrics = evaluate(gt, ledger)
    args.metrics.write_text(json.dumps(metrics, indent=2) + "\n")
    write_report(metrics, args.ledger, args.report)

    print(json.dumps(metrics.get("heldout") or metrics.get("dev"), indent=2))
    print(f"\nWrote {args.metrics} and {args.report}")


if __name__ == "__main__":
    main()