# Evaluation report

Ledger: `matched_ledger_stage3.csv`

## Headline (held-out split)

## Per-corruption-type breakdown

| Type | Count | Correct | Wrong | Unresolved |
|---|---|---|---|---|
| clean | 322 | 322 | 0 | 0 |
| duplicate | 44 | 44 | 0 | 0 |
| fee_difference | 21 | 4 | 1 | 16 |
| merged | 23 | 17 | 0 | 6 |
| partial_refund | 12 | 0 | 0 | 12 |
| substituted_digit | 26 | 13 | 0 | 13 |
| truncated_ref | 46 | 37 | 0 | 9 |
| unmatched_noise | 15 | 0 | 0 | 0 |

## Duplicate detection

- Orders matched by more than one settlement: **23**
- Extra settlements pointing at those orders: 23

Both lines of a duplicate pair map to the same order. Both matches are correct by ground truth. Two settlements pointing at one order is a finding, not a wrong match. See D-07.

## How to read these numbers

- `wrong_match_rate` is the honest metric: matches that are incorrect.
- `unresolved` counts settlements that matched nothing but should have.
- Stage 1 is the deterministic floor. Wrong matches should be 0; unresolved should equal everything that is not `clean`.
