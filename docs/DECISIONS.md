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