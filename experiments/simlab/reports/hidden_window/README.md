# Hidden-window voter signal: scorer and ceiling (orchestrator 01:33Z Nov 13)

Script: hidden_window.py. Re-runnable; it reads raw/_cursor/hidden_window/<day>/upvotes.jsonl.gz automatically when present.

**Signal:** per launch, the held (complete) people whose upvote is seen in re-reads fetched by 01:00 / 02:00 / 02:45 PT, unweighted and
weighted by each person's past top-10 hit rate. Blended as z(clean 00:05) + w z(ln(1 + count)), w leave-one-day-out.

**Real data today:** no Cursor files yet. The store holds 1 / 1 / 6 people re-read in the window across 15 days. Gain 0.0; nothing to measure.

**Ceiling (time proxy: binomial thinning, an assumption).**
- No per-launch vote order is held, so the "share cast before 03:00 PT" (30 / 50 / 70%) is applied as random thinning of each launch's votes.
- 20 draws; top 3 / 5 / 10 / #1-in-top-3 gain vs clean, paired.
- (a) Random held sample of final voters (all 15 clean as-live days):

| coverage | pre-03:00 share 30% | 50% | 70% |
|---|---|---|---|
| 28% | +23.1 [20.6, 25.5] / +13.2 / +7.6 / +4.6 | +24.8 / +15.7 / +9.3 / +5.0 | +28.1 / +16.7 / +11.2 / +6.1 |
| 41% | +25.1 / +15.5 / +9.0 / +4.3 | +27.5 / +17.3 / +10.6 / +6.1 | +28.7 / +19.1 / +12.7 / +7.1 |

- (b) The ACTUAL held voters: real, non-random pool selection; complete people's upvotes of each launch in the store.
  - 12 days where store coverage is 28–49% (Nov 9–11 excluded: reads end Nov 10).
  - Clean baseline top 3 = 63.9.

| pre-03:00 share | combined top 3 / 5 / 10 / #1 | gain vs clean |
|---|---|---|
| 30% | 83.1 / 84.9 / 85.3 / 100 | +19.2 [16.9, 21.4] / +14.9 / +7.8 / +8.3 |
| 50% | 85.1 / 85.2 / 87.0 / 100 | +21.3 [19.2, 23.3] / +15.2 / +9.5 / +8.3 |
| 100% (all held votes, any time) | 83.3 / 80.0 / 85.0 / 100 | +19.4 [11.1, 27.8] / +10.0 / +7.5 / +8.3 |

**Reading:**
- If held people's pre-03:00 votes were a random draw of their final votes, the route would reach about 83–85% top 3, and the gain is already near its maximum at 28% coverage.
- Two cautions:
  1. The thinning assumption ignores late builders: launches whose votes arrive after the reveal. The PH agent found a median 19% of votes after the reveal, and early leaders that did not hold.
  2. The relevant comparison at 01:00–02:45 PT is the hidden-rank blend already deployed (about 67–72% top 3 at 01:00–02:00 on 6 days), not clean alone. So the realistic increment is at most about +11–16 top 3, and likely less.
- The first real nights decide it. The scorer runs as soon as the Cursor files land.
