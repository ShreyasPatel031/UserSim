# Before-reveal (03:45 PT) forecast: error anatomy at top 10, and one fix

E5, Nov 17 2026. Pre-registration of the fix: `PREREG_fix.md` (commit 6167a3bc, before the run).

**Result.** Most top-10 misses come from movement after the reveal, which nothing known at 03:45 predicts well. The pre-registered fix changed no top-10 pick on any of the 14 days, so it is not adopted. No patch.

## Data

- **Days.** 14 replay days, Nov 2–15. These are every day with a pre-reveal recorder read and a final board. Oct 31 and Nov 1 have no pre-reveal read; Nov 16 has no final board yet.
- **03:00 stand-in.** Every replay day uses the 03:00 read, because no 03:45 read was recorded on those days. The live writer did the same until Nov 15.
- **Live days.** The 3 published live days (Nov 14–16) are not separated here: two are in the replay, and the third is not final.
- **Method.** The published one (hybrid_vm):
  - the hidden top 5 from the recorder's position order;
  - slots 6+ by a ridge on hidden position, movement since 01:00, comment count and the 00:05 prior;
  - weights fit leave-one-day-out.
  The replay reproduces the PH agent's figures exactly: **73.8 / 78.6 / 77.9** top 3 / 5 / 10.
- **00:05 prior.** The published 00:05 forecast where it is held (10 days); otherwise the month-forward arm-2 prediction (4 days).
- **Leak rule.**
  - Features use reads at or before the cut only, with no vote counts (votes are 0 before the reveal).
  - Votes at 04:00 / 05:00 / 06:00, final ranks and the ring share of held voters are used only to classify misses, never as inputs.

## Misses at top 10

There are 62 misses in total: 31 false negatives (finished top 10, not predicted) and 31 false positives.

| Class (first rule that fits) | False negatives | False positives | Top 10 if every miss of this class were fixed |
|---|---|---|---|
| **Late surge or fade after the reveal**: at 04:00 the vote order agreed with our call; the launch crossed rank 10 later | **13** | **15** | **87.1** |
| Boundary: final rank 9–12 | 6 | 8 | 82.1 |
| Hidden order wrong at 03:00, but the 04:00 votes were right | 7 | 6 | 82.9 |
| Midnight prior or ridge moved it across rank 10 (hidden order was right) | 2 | 2 | 79.3 |
| Ring or vote spike (30%+ of held voters ring-flagged) | 2 | 0 | 79.3 |
| Other (no 04:00 read) | 1 | 0 | 78.6 |

The current top 10 is 77.9. Per-miss detail is in `misses_top10.csv`:
- hidden position at 01:00 and 03:00;
- 00:05 rank;
- comments, and comment velocity in the last hour;
- maker comment share;
- hunter record;
- vote rank at 04:00 / 05:00 / 06:00;
- ring share.

**Two days carry a third of the misses.**
- Nov 6 (55 launches) scored 30% at top 10: the final top 10 sat at hidden positions 1, 2, 4, 11, 15, 21, 22, 31, 37 and 52.
- Nov 12 scored 50%.
- The other 12 days average 85%.

On Nov 6 the hidden order was close to unrelated to the outcome. That points to the recorder's position field on that day, or a very unusual day, rather than to the model; it is worth a look by whoever owns the recorder.

**Inputs at 03:00 hardly predict movement after the reveal.** Among the 04:00 top 25, the mean within-day Spearman with later climb is:
- hidden position: +0.19 (later positions climb more, partly regression);
- 00:05 prior: +0.11;
- comments: +0.03;
- comment velocity: +0.06;
- hunter launch count: +0.10 (no hunter record on Nov 13–15).
The ring share of held voters correlates +0.17, but it is measured after the day, so it cannot be an input. A pre-launch ring flag would need the makers' earlier launches, and it touches only 2 misses.

## The one fix (pre-registered)

**The fix:** pin only the hidden top 3 instead of the top 5, and let the same leave-one-day-out ridge order slots 4+. This gives the 00:05 prior a say on slots 4–5, where late movers sit.

| Line, same 14 days | Top 3 | Top 5 | Top 10 |
|---|---|---|---|
| Published: hidden top 5 pinned, ridge 6+ | 73.8 [64.3, 83.3] | 78.6 [70.0, 85.7] | 77.9 [67.9, 85.7] |
| **Fix: hidden top 3 pinned, ridge 4+** | 73.8 [64.3, 83.3] | 77.1 [70.0, 82.9] | 77.9 [68.6, 85.7] |
| Fix minus published (paired) | +0.0 | −1.4 [−5.7, +2.9] | **+0.0 [+0.0, +0.0]** |
| Reference: ridge for every slot | 71.4 | 77.1 | 77.9 |
| Reference: hidden order alone | 73.8 | 78.6 | 74.3 |

- The fix changed no top-10 set on any day (0 better, 14 same, 0 worse) and lowered the top 5 slightly. **Not adopted.**
- The ridge's all-day weights:
  - hidden position: −0.63;
  - 00:05 prior: +0.20;
  - comments: +0.10;
  - movement: −0.01.
  The hidden order dominates, and reordering slots 4–5 only swaps launches that are both inside the top 10.
- What the published line adds over the hidden order alone is at top 10 (+3.6 points), and it comes from slots 6+.

## What would move the number

- **The largest class happens after 04:00.** Its oracle is +9.2 points at top 10, but no 03:45 input predicts it beyond about 0.1–0.2 rank correlation. Only a later forecast point can get it.
- **The next two classes are fixable in principle.**
  - Hidden order wrong at 03:00 but right at 04:00 (+5.0 oracle): the real 03:45 read, live since Nov 16, should cut part of this; 13 of these misses come from days that used the 03:00 stand-in.
  - The Nov 6 recorder anomaly.
- **The 80.0% headline (24/30 over 3 live days) sits inside this replay's interval** [67.9, 85.7]. A 3-day figure cannot be told apart from the 77.9 replay.

Files: `anatomy.py` (replay and per-launch table), `classify.py`, `fix.py`, `misses_top10.csv` (ids removed), `fix_result.json`, `days.json`.
