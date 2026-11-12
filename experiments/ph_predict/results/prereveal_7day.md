# Pre-reveal points P1-P4, 7 days with hidden API ranks (replay, written 09:40Z Nov 12)

Days: 2026-11-02, 03, 04, 08, 09, 10, 11. Truth = official daily rank (all ranked launches, late-featured included).
pred_rank_best = hidden API rank position x w + published 00:05 LM position x (1 - w), w 0.5 at P1, 0.75 at P2-P4.
Replay on held reads (vote_snapshots rank_now <= the point time); the weights were chosen on overlapping days, so this is
not a clean out-of-sample test. Intervals: day bootstrap 95%, n = 7 days.

| point | method | top 3 | top 5 | top 10 | our #1 in top 3 |
|---|---|---|---|---|---|
| P1 | pred_rank_best | 71.4 [57, 86] | 68.6 [63, 77] | 78.6 [74, 83] | 100 [100, 100] |
| P1 | API rank | 71.4 [57, 86] | 57.1 [49, 66] | 70.0 [64, 76] | 100 [100, 100] |
| P2 | pred_rank_best | 76.2 [57, 90] | 77.1 [71, 80] | 80.0 [76, 84] | 100 [100, 100] |
| P2 | API rank | 71.4 [57, 86] | 68.6 [57, 77] | 78.6 [73, 84] | 100 [100, 100] |
| P3 | pred_rank_best | 85.7 [71, 95] | 80.0 [71, 89] | 81.4 [76, 87] | 100 [100, 100] |
| P3 | API rank | 76.2 [57, 90] | 77.1 [71, 80] | 81.4 [73, 87] | 100 [100, 100] |
| P4 | pred_rank_best | 85.7 [71, 95] | 80.0 [71, 89] | 81.4 [76, 87] | 100 [100, 100] |
| P4 | API rank | 76.2 [57, 90] | 77.1 [71, 80] | 81.4 [74, 87] | 100 [100, 100] |
| any | LM (published 00:05) | 47.6 [33, 67] | 60.0 [49, 71] | 77.1 [70, 83] | 42.9 [14, 86] |
