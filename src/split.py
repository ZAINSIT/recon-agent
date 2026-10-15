"""
split.py — assign every ground-truth row to 'dev' or 'heldout'.

The held-out split is committed BEFORE any tuning. This is the discipline
that makes the final held-out number mean something: if you tune the fuzzy
threshold on the full batch and *then* split, the held-out number is just
a second dev number.

Writes:
  data/batch_001/ground_truth.csv   (adds/updates the 'split' column)
  data/batch_001/heldout.json       (the held-out ids + a hash of them)

heldout.json is committed. ground_truth.csv is regenerated from the seed,
so it is not committed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

import pandas as pd

DEFAULT_BATCH = Path("data/batch_001")
DEFAULT_HELDOUT_FRACTION = 0.30


def compute_split(
    settlement_ids: list[str],
    seed: int,
    heldout_fraction: float,
) -> dict[str, str]:
    """Deterministic assignment of settlement_id -> 'dev' | 'heldout'."""
    rng = random.Random(seed)
    # Sort first so the assignment does not depend on file order.
    ids = sorted(settlement_ids)
    rng.shuffle(ids)
    n_heldout = round(len(ids) * heldout_fraction)
    heldout = set(ids[:n_heldout])
    return {sid: ("heldout" if sid in heldout else "dev") for sid in settlement_ids}


def hash_id_list(ids: list[str]) -> str:
    """SHA-256 of the sorted, newline-joined ids. Any change to the list
    changes the hash, so a reviewer can verify the split was not re-salted."""
    payload = "\n".join(sorted(ids)).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--heldout-fraction", type=float, default=DEFAULT_HELDOUT_FRACTION
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Fail if the existing heldout.json does not match a fresh split.",
    )
    args = parser.parse_args()

    gt_path = args.batch / "ground_truth.csv"
    heldout_path = args.batch / "heldout.json"

    if not gt_path.exists():
        raise SystemExit(f"missing {gt_path}; run generate.py first")

    gt = pd.read_csv(gt_path)

    assignment = compute_split(
        gt["settlement_id"].tolist(), args.seed, args.heldout_fraction
    )
    gt["split"] = gt["settlement_id"].map(assignment)

    heldout_ids = [sid for sid, s in assignment.items() if s == "heldout"]
    payload = {
        "seed": args.seed,
        "heldout_fraction": args.heldout_fraction,
        "n_total": len(assignment),
        "n_heldout": len(heldout_ids),
        "n_dev": len(assignment) - len(heldout_ids),
        "heldout_hash": hash_id_list(heldout_ids),
        "heldout_ids": sorted(heldout_ids),
    }

    # --verify: compare against the committed file, refuse to overwrite.
    if args.verify:
        if not heldout_path.exists():
            raise SystemExit(f"--verify given but {heldout_path} does not exist")
        existing = json.loads(heldout_path.read_text())
        if existing["heldout_hash"] != payload["heldout_hash"]:
            raise SystemExit(
                "SPLIT MISMATCH\n"
                f"  committed: {existing['heldout_hash']}\n"
                f"  recomputed: {payload['heldout_hash']}\n"
                "The held-out split has changed since it was committed. "
                "This invalidates any tuning done against the previous split."
            )
        print(f"Split verified: {payload['heldout_hash']}")
        return

    # Normal run: write the split back and the committed manifest.
    gt.to_csv(gt_path, index=False)
    heldout_path.write_text(json.dumps(payload, indent=2) + "\n")

    print(f"Wrote split to {gt_path}")
    print(f"Wrote manifest to {heldout_path}")
    print(f"  total:   {payload['n_total']}")
    print(f"  dev:     {payload['n_dev']}")
    print(f"  heldout: {payload['n_heldout']}")
    print(f"  hash:    {payload['heldout_hash']}")


if __name__ == "__main__":
    main()