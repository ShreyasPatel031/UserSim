# voter_harness on the merged store (orchestrator 05:38Z Nov 13): still 0 gain

**Store.** Built by merge_store.py: store_v3 (Nov 10) plus the 22,614 merged or replaced pulls in audit_20261113T0453Z.tsv.
- Pulls were parsed with the population agent's own full_pull.load_full, with 0 parse errors after re-downloading 17 files that had hit transient 502s.
- 2,715 people were replaced and 20,796 are new.
- Complete people: **61,468**, against 39,774 in store_v3. This is store_v3 complete ∪ the latest_complete.txt read (40,687, still the Nov 12 23:42Z file) ∪ the merged people. 911 people were dropped because they have no full-pull rows.
- Events: 2.23M upvotes and 10.2M follow edges.
- To do: re-check against the new latest_complete.txt when the quality pass lands.

**Vote coverage** (covered upvotes / launch votes):

| | store_v3 | merged |
|---|---|---|
| test days Oct 29 – Nov 8 | 0.26 – 0.42 | 0.52 – 0.69 |
| Nov 9 / Nov 10 | 0.13 / 0.00 | 0.35 / 0.14 |
| Oct 29 – Nov 4, all launches | 0.42 | 0.70 |
| Oct 29 – Nov 4, top-3 launches | 0.60 | 0.99 |
| Oct 29 – Nov 4, median per launch | 0.30 | 0.50 |

**Caution on coverage.** The pool was seeded from voters of these launches, so coverage on these days is inflated by construction. Top-3 launches are near 1.0 because their voters were sampled.

What a 00:05 forecast can actually use is the STRICT reads, fetched before 00:00 PT of the test day. Active people under that rule:
- 0 on Oct 29 – 31;
- about 3,500 on Nov 2 – 8;
- 5,453 on Nov 9 and 7,783 on Nov 10.

**Forecast.** Clean scores 63.3 / 72.0 / 74.0 on top 3/5/10. Combined = z(clean) + w · z(ln expected votes), with w chosen leave-one-day-out.
- With and without hunter + maker follow edges, under STRICT, LENIENT and HIDDEN timing, w = 0 is chosen on every one of the 10 days.
- So the gain is exactly 0.0 on top 3/5/10 in every cell.
- Edge-follower feature on its own, STRICT: −3.3 [−10.0, 0.0] / 0.0 / +1.0 [0.0, +3.0]. LENIENT: 0.

**Verdict.** About 1.7× the people and double the vote coverage still add nothing over the clean 00:05 score.
