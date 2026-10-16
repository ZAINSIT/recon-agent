# Decision records

## D-07: Duplicates are correct matches, but double-matching is reported separately

**Decided:** Both lines of a duplicate pair map to the same order in ground
truth. The matcher correctly identifies what order each line refers to, so
both count as correct. The fact that two settlements point at one order is
reported as `double_matched_orders` (19 on batch_001), not as a wrong match.

**Rules out:** Treating the second duplicate as a wrong match. That would
conflate "matched the wrong order" with "matched the right order twice,"
which are different failures with different handling.

**Why it matters:** A finance-ops reviewer cares that two settlements hit one
order — that's the double-counting signal. But the matcher did its job. The
finding belongs in the report, not in the precision number.


## D-08: Fuzzy threshold 0.85 — a recall knob with no precision cost on dev

**Decided:** Fuzzy-similarity threshold 0.85.

**What the sweep showed:** On dev (356 rows), precision is 1.0 at every
threshold from 0.60 to 0.99. The threshold trades only recall: 0.8764 at
0.60, falling to 0.8483 at 0.92+. No threshold in this range produces a
wrong match on dev.

**Why 0.85 and not 0.60:** The curve is flat below 0.85, so a looser
threshold buys nothing. 0.85 sits just above the flat region, leaving margin
if the data shifts toward more ambiguous references.

**Why not tighter:** Above 0.92, recall drops ~3pp with no precision gain.

**The one held-out wrong match is not threshold-controlled.** It comes from
the merged-sum path, which ignores the threshold. See D-09.


## D-09: Inferred refund/fee fallbacks removed

**Decided:** `try_refund_or_fee` accepts only deltas that match a refund or
fee actually recorded on the order. The earlier "any shortfall 5–60% is a
refund" fallback was removed.

**Why:** It produced four wrong matches. A truncated or substituted
reference can name a *different* real order, and the fallback then
"explained" a shortfall belonging to another order. Precision rose from
0.9786 to 0.9921 at the cost of 13 rows moving from matched to unresolved.

**Why unresolved is better than a low-confidence wrong match:** In a money
context, a confident wrong answer is worse than an honest "I don't know."
The unresolved rows go to Stage 3, which proposes with a validator.

**Consequence:** `partial_refund` now resolves zero of 12 on the full batch.
The validator refuses to infer a refund when none is recorded. This is the
intended behavior — the model can propose a refund, but the validator will
not accept one without arithmetic to support it.