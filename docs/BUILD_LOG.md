# Build log

## 2026-10-15 — Day 1: generator

### What broke

**Misaligned type assignment (first run).** Types were assigned to positions
before the loop, but `merged` consumes 2–3 orders and `duplicate` emits two
lines, so the assignment drifted. Result: `duplicate` at 0.093 against a 0.040
target, `clean` at 0.654 against 0.700. Fixed by choosing the type per
settlement inside the loop.

**`unmatched_noise` consumed a real order.** The synthetic settlement advanced
`i`, so the order at that position was dropped from every settlement and every
ground-truth row. 12 orders were orphaned. Fixed by generating `unmatched_noise`
in a second pass, after the main loop, so it consumes no orders.

**Infinite loop from a missing increment.** After moving type assignment inside
the loop, one branch lost its `i += ...`, so `while i < len(orders)` never
terminated. Fixed by ensuring every branch advances `i`, and adding an
`else: raise ValueError` to catch unknown types loudly instead of looping.

### Decisions

- Corruption mix: 70/8/5/5/5/4/3. `duplicate` reports at ~2× its weight in
  ground-truth rows because each event emits two lines; the weight means
  "fraction of orders that trigger a duplicate event," not "fraction of
  settlements that are duplicates."
- `merged` is excluded from the type pool when fewer than 2 orders remain.
- `unmatched_noise` count is `round(0.03 * n)`, not a probability per order.
  It's a fixed tail, not a per-order draw.

### Invariant

`scripts/check_invariant.py` verifies every `order_id` appears in exactly one
ground-truth row, except duplicate orders which appear exactly twice. Passing
on batch_001 with seed 42: 500 orders, 0 missing, 19 duplicate pairs.

### Observed mix (batch_001, seed 42, n=500)

clean 0.703 · truncated_ref 0.077 · duplicate 0.075 · merged 0.043 ·
fee_difference 0.041 · partial_refund 0.031 · unmatched_noise 0.030

Tail types run noisy at n=500: partial_refund landed at 0.031 against a 0.050
target. Expected count 25, observed ~15, within ~1.5σ. Not a bug; recorded so
the eval report can note it.

### Hand verification

20 rows checked manually against the corruption-type checklist (three walked
through in full: merged, partial_refund, clean). All consistent.

## 2026-10-15 — Day 2: split and Stage 1

### What broke

**Pandas merge suffixes only apply to colliding column names.** The harness
assumed every column from both frames would get `_gt` / `_l` suffixes.
`corruption_type` existed only in ground truth, so it stayed unsuffixed, and
`groupby("corruption_type_gt")` raised KeyError. Fixed by using the actual
name. Habit: after any merge, print `merged.columns` and check.

**Precision exceeded 1.0 (1.0177).** `is_correct` was `predicted == truth`,
which is True when both are empty — so correctly-left-unmatched rows counted
as correct matches. Precision became correct/matched > 1, which is impossible.
Fixed by requiring `len(predicted) > 0`. Habit: any ratio bounded by [0,1]
that exceeds 1 means the metric is wrong, not that the result is great.

**Empty files caused silent failures, twice.** `touch` creates empty files;
pasting code is a separate step. Both `generate.py` and `harness.py` were
touched but left empty. Failures were silent (no output) rather than loud.
Habit: after writing any file, `wc -l` before running.

### Stage 1 results (held-out, 152 rows)

- correct: 113
- wrong: 0
- correctly_unmatched: 2
- unresolved: 37
- precision: 1.0
- recall: 0.7434

Stage 1 is the deterministic floor. Precision is perfect by construction;
the work of Stage 2 is to raise recall without collapsing precision.

### The split

`heldout.json` committed before any matcher was written. Hash:
`sha256:2a53fee6...`. `python -m src.split --verify` recomputes and checks it. 


## 2026-10-16 — Day 3: fuzzy matcher and the threshold

### What broke

**The threshold was inert.** The first sweep (0.50–0.99) returned identical
results at every value. Cause: the corruption model produced references
recoverable by normalized-exact lookup, so the fuzzy-similarity path was
never exercised. 71 rows resolved by `normalized_exact`, 20 by
`merged_sum_N`, 0 by `fuzzy_ref`. Fixed by adding a `substituted_digit`
corruption type (5%) that forces genuine similarity scoring. Batch
regenerated, split re-committed before any tuning.

**The threshold was then a step function.** With token-overlap similarity,
every reference sharing the `ord-2026-` prefix scored 0.5, so the sweep
had two states, not a curve. Fixed by replacing token-overlap with
Levenshtein edit-distance similarity. Now scores form a gradient and the
threshold trades recall for precision.

**Inferred refund/fee fallbacks produced four wrong matches.** A truncated
or substituted reference can name a different real order; the fallback then
explained a shortfall belonging to another order. Removed the inferred
paths; kept recorded-refund and recorded-fee matching. Precision 0.9786 ->
0.9921, recall 0.8954 -> 0.8235, wrong 3 -> 1.

**Changed a function signature, forgot the caller.** `try_normalized` gained
two parameters; the call site in `run()` still passed three. TypeError at
runtime. Habit: after a signature change, grep the function name.

### Result (held-out, threshold 0.85)

- matched 127, correct 126, wrong 1, unresolved 24, correctly_unmatched 2
- precision 0.9921, recall 0.8235
- The remaining wrong match is a `merged_sum_2` coincidence: two unrelated
  orders summed to a settlement amount. Left as a known limitation; a real
  merged settlement's reference names its orders, and requiring that check
  is left as future work.

### Threshold

Swept 0.60–0.99 on dev. Chose 0.85 (knee). Held-out run once. See D-08.