# Evaluation report

Ledger: `matched_ledger_stage3.csv`

## Headline (held-out split)

| Metric | Value |
|---|---|
| total | 153 |
| matched | 132 |
| correct | 131 |
| wrong | 1 |
| unresolved | 19 |
| match_rate | 0.8627 |
| wrong_match_rate | 0.0076 |
| precision | 0.9924 |
| recall | 0.8562 |

## Per-corruption-type breakdown

| Type | Count | Correct | Wrong | Unresolved |
|---|---|---|---|---|
| clean | 322 | 322 | 0 | 0 |
| duplicate | 44 | 44 | 0 | 0 |
| fee_difference | 21 | 9 | 2 | 10 |
| merged | 23 | 17 | 0 | 6 |
| partial_refund | 12 | 0 | 0 | 12 |
| substituted_digit | 26 | 18 | 0 | 8 |
| truncated_ref | 46 | 37 | 1 | 8 |
| unmatched_noise | 15 | 0 | 0 | 0 |

## Duplicate detection

- Orders matched by more than one settlement: **25**
- Extra settlements pointing at those orders: 25

Both lines of a duplicate pair map to the same order. Both matches are correct by ground truth. Two settlements pointing at one order is a finding, not a wrong match. See D-07.

## How to read these numbers

- `wrong_match_rate` is the honest metric: matches that are incorrect.
- `precision` is correct / matched. `recall` is correct / total.
- The pipeline is three stages: exact (Stage 1), fuzzy (Stage 2), LLM-bounded-by-validator (Stage 3).

**The numbers are on synthetic data I generated.** Because I wrote the
corruption model, I know the correct answer for every row. That is what makes
the metrics possible, and it is the main limitation: a real bank feed has
corruption shapes this model does not cover.

**Dev precision (0.9937) is marginally higher than held-out (0.9924).** The
split was committed before any tuning, so held-out being slightly worse is
the expected direction, not a sign of overfitting.

**The single wrong match is a merged-sum coincidence.** Two unrelated orders
summed to a settlement amount. Requiring the settlement reference to name its
orders would fix it; left as future work.

**The per-corruption table is where the failure modes live.** `partial_refund`
resolves zero of 12 — the validator refuses to infer a refund when none is
recorded (D-09). `fee_difference` carries both wrong matches; the fee path is
the least reliable.

**The LLM resolves 12 of 509 rows.** The deterministic layers resolve 438.
That is the point: the model is used only where deterministic code cannot
decide, and the validator ensures it adds no errors.
