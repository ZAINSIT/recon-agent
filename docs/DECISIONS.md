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