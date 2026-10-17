"""
pipeline.py — run the whole reconciliation pipeline end to end.

Stage 1 → Stage 2 → Stage 3 → eval harness.
Prints a compact summary at each stage.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

BATCH = Path("data/batch_001")


def run(cmd: list[str]) -> None:
    print(f"\n$ {' '.join(cmd)}")
    print("-" * 60)
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print(f"\nFAILED: {' '.join(cmd)}")
        sys.exit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=0.85)
    parser.add_argument("--skip-llm", action="store_true",
                        help="stop after Stage 2 (useful if quota is low)")
    args = parser.parse_args()

    t0 = time.time()

    run([sys.executable, "-m", "src.stage1_exact"])
    run([sys.executable, "-m", "src.stage2_fuzzy", "--threshold", str(args.threshold)])

    if args.skip_llm:
        ledger = "matched_ledger_stage2.csv"
    else:
        run([sys.executable, "-m", "src.stage3_llm"])
        ledger = "matched_ledger_stage3.csv"

    run([sys.executable, "-m", "eval.harness", "--ledger", ledger])

    print(f"\nDone in {time.time() - t0:.1f}s")
    print(f"Final ledger: {BATCH / ledger}")
    print(f"Report:       eval/report.md")


if __name__ == "__main__":
    main()