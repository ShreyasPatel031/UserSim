# Forward test of the /try simulator (orchestrator 06:33Z Nov 13)

Script: forward_sim.py `<day>`. Run it each morning on the previous day; it is not scheduled. It runs the deployed site code as it is: step_text / new_run → step_reactions, step_asks and step_launch. It also runs the frozen b20 recipe. Judging uses the strict gemini-2.5-pro same-point judge against real launch-day comments.

**Inputs, all dated before the launch, with no Product Hunt requests:**
- the 00:05 read, plus warehouse rows for any launches missing from it (same submitted text);
- the site's retrieval bank (ends Oct 24) and band models (trained to Nov 10, page band to Aug 31);
- page text only from E5's forward page reads of that day.

| | Nov 11 | Nov 12 (partial) | site backtest figure |
|---|---|---|---|
| line-up / judged (≥ 5 non-team comments) | 26 / 6 | 37 / 2 (comment pulls partial) | |
| reactions, pasted: precision over 6 | 69.4 [44.4, 91.7] | 41.7 [0.0, 83.3] | point precision 0.23 (reactions_eval); this judge pool is more lenient |
| reactions, pasted: recall | 58.3 [44.4, 77.8] | 16.7 | |
| concern top-1, deployed (pasted) | 20.0 [0.0, 60.0] (n = 5) | 50.0 (n = 2) | 2 in 5 |
| concern p@3, b20 (pasted) | 25.0 [8.3, 33.3] (n = 4) | 33.3 (n = 1) | 37 (replication) |
| question top-1, deployed (pasted) | 16.7 [0.0, 50.0] | 0.0 | 1 in 2 |
| question p@3, b20 (pasted) | 16.7 [0.0, 50.0] | 0.0 | |
| constant list (concerns / questions p@3) | 6.7 / 0.0 | 16.7 / 0.0 | |
| band, pasted: real rank inside 10th–90th | 84.6% [69.2, 96.2] (n = 26) | after final ranks (~09:40Z) | about 3 in 4 |
| band, pasted: Spearman with final rank | 0.29 (n = 26) | pending | 0.35 / 0.42 |
| page path | 0 page reads that day | 8 page reads, none with ≥ 5 comments | |

**Reading.** Eight judged launches cannot test anything yet, and the intervals span almost everything. The band (26 launches) is in line with the corrected figures.

The constraint is comments. The bucket's launch-day API pulls give few launches with 5 or more non-team comments: 6 on Nov 11 and 2 so far on Nov 12. The forward record grows only as fast as those pulls. Re-running a day later picks up more comments, because all results are cached per launch.

Judge cost is about $0.03 per day; total spend about $0.3 including generation.
