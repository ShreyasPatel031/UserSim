# Pre-registration: one fix for the largest before-reveal miss class

Written 2026-11-17 before the fix is run; committed before the backtest.

**Anatomy so far (14 replay days, Nov 2–15; method reproduces the PH agent's 73.8% top 3).**
- 62 top-10 misses: late surge or fade after the reveal 28, boundary (final 9–12) 14, hidden order wrong at 03:45 13, midnight prior moved it wrong 4, ring 2, other 1.
- Among launches in the 04:00 vote top 25, movement after the reveal is related to two inputs known at 03:45:
  - the hidden position itself (worse hidden position, more later climb; mean within-day Spearman +0.19);
  - the 00:05 prior (+0.11).
  The published rule pins the hidden top 5 and lets the prior act only on slots 6+.

**The one fix.** Pin only the hidden top 3. Order slots 4+ with the same leave-one-day-out ridge as now: z(log hidden position), z(movement since 01:00), z(log1p comments), z(00:05 prior). Same inputs, same reads, no new data. The top 3 is unchanged by construction.

**Test.** Same 14 days, paired against the published rule (hidden top 5 pinned).
- Primary: top 10.
- Secondary: top 5.
- Intervals: bootstrap over days (2,000).

**Adopt if** the top-10 paired interval is above 0 and top 5 does not fall by more than 2 points on the point estimate.
