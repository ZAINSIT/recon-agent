# Evaluation report

Ledger: `matched_ledger_stage1.csv`

## Headline (held-out split)

| Metric | Value |
|---|---|
| total | 152 |
| matched | 113 |
| correct | 113 |
| wrong | 0 |
| unresolved | 37 |
| match_rate | 0.7434 |
| wrong_match_rate | 0.0 |
| precision | 1.0 |
| recall | 0.7434 |

## Per-corruption-type breakdown

| Type | Count | Correct | Wrong | Unresolved |
|---|---|---|---|---|
| clean | 357 | 357 | 0 | 0 |
| duplicate | 38 | 38 | 0 | 0 |
| fee_difference | 21 | 0 | 0 | 21 |
| merged | 22 | 0 | 0 | 22 |
| partial_refund | 16 | 0 | 0 | 16 |
| truncated_ref | 39 | 0 | 0 | 39 |
| unmatched_noise | 15 | 0 | 0 | 0 |

## Duplicate detection

- Orders matched by more than one settlement: **19**
- Extra settlements pointing at those orders: 19

Both lines of a duplicate pair map to the same order. Both matches are correct by ground truth. Two settlements pointing at one order is a finding, not a wrong match. See D-07.

## How to read these numbers

- `wrong_match_rate` is the honest metric: matches that are incorrect.
- `unresolved` counts settlements that matched nothing but should have.
- Stage 1 is the deterministic floor. Wrong matches should be 0; unresolved should equal everything that is not `clean`.
