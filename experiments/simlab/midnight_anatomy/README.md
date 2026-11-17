# Midnight (00:05) forecast: error anatomy at top 10, and one fix

E5, Nov 17 2026. Fix pre-registered in `PREREG_fix.md` (commit aa36f2a9) before the run.

**Result.** The largest class of misses is the hunter record. The model trusts proven hunters too much and under-rates first-time hunters. The pre-registered fix (a month-forward offset for launches with no hunter record) did not clear noise and is not adopted. No patch.

## Live days

| Line | Days | Top 3 | Top 5 | Top 10 |
|---|---|---|---|---|
| Published 00:05, all scorable live days (Oct 29 – Nov 15) | 15 | 55.6 | 62.7 | 74.7 |
| Published arm 2 (Nov 14–15) | 2 | 66.7 | 60.0 | 70.0 |
| Arm 2 rebuild, same live days to Nov 12 | 12 | 63.9 | 71.7 | 73.3 |
| Arm 3 rebuild, same live days to Nov 12 | 12 | 66.7 | 70.0 | 74.2 |
| Before-reveal replay (03:00 read) | 11 | 75.8 | 81.8 | 82.7 |

On the 8 days where all four lines exist (Nov 2–12):

| Line | Top 3 | Top 5 | Top 10 |
|---|---|---|---|
| Published | 45.8 | 55.0 | 75.0 |
| Arm 2 rebuild | 58.3 | 67.5 | 72.5 |
| Arm 3 rebuild | 62.5 | 67.5 | 73.8 |
| Before-reveal | 75.0 | 77.5 | 82.5 |

**What is missing.**
- No 00:05 file was kept for Nov 5–7.
- Arm 2 was published from Nov 14; only Nov 14–15 have final boards.
- Arm 3 was published from Nov 17 and its shadow ran only on Nov 16; neither day has a final board yet.
- So there are no live arm-3 days to score. Nov 17 should be added when it is final.
- The live arm-2 record also ran with known input gaps:
  - hunter history null for most launches on Nov 12–14 (today-rows bug);
  - Gemini pitch score null from Nov 13 until the Nov 16 fix.

## Anatomy: arm-3 rebuild, month-forward, 195 days (2026-04-01 – 2026-11-12)

**The rebuild.** Arm-2 inputs plus E5's A / B / C blocks, the same blocks arm 3 adds. It scores top 10 = 77.7. Against arm 2 on the same folds:
- top 3: +1.9 [+0.2, +3.8];
- top 5: +0.3 [−0.9, +1.6];
- top 10: +1.4 [+0.5, +2.2].
That is in line with the PH agent's arm-3 backtest. There are 864 misses at top 10.

**How each miss is classified.**
- **Input group:** a miss goes to the input group whose day-centred contribution pushed it furthest the wrong way (down for a false negative, up for a false positive).
- **Checked first:** ring (30%+ of held voters ring-flagged; measured after the day, so classification only), then late surge or fade (wrong even in the 03:00 hidden order; only the 11 days with a replay).

| Class | False negatives | False positives | Top 10 if all were fixed |
|---|---|---|---|
| hunter record | 190 | 167 | 87.4 |
| maker team (size, earlier launches) | 86 | 100 | 82.1 |
| launch-day crowding (line-up, weekday) | 64 | 62 | 81.0 |
| pitch and page (Gemini pitch score, text, media) | 35 | 47 | 79.5 |
| no input pushed it far (near tie or unexplained) | 18 | 28 | 78.6 |
| topic prior (topic, nearest past launches) | 15 | 16 | 78.5 |
| late surge or fade (wrong even in the 03:00 hidden order) | 11 | 11 | 78.3 |
| ring or vote spike (30%+ of held voters ring-flagged) | 10 | 4 | 78.2 |

**The hunter record is the largest class: 357 of 864 misses.**
- **False negatives:** 124 of 190 are launches whose hunter has no record.
  - Such launches reach the real top 10 22.3% of the time.
  - The model puts them in its top 10 17.2% of the time.
- **False positives:** all 167 have a hunter record (median past top-5 share 0.60).
  - Launches with a record reach the top 10 59.4% of the time.
  - The model puts them there 65.5% of the time.
- **A hunter record is missing for 42–62% of launches every month**, because most hunters are first-timers. This is a property of the data, not a fetch gap, apart from the Nov 12–14 live bug.

**Inputs that might separate first-time hunters who do well**, as within-day rank correlation with the residual, no-record launches only:
- account age: −0.11;
- hunter follow-graph count: +0.15. This input needs a leak check (follower counts grow with the outcome; the earlier raw-field sweep found the API follower count leaky).
Nothing else exceeds 0.07.

## The one fix (pre-registered)

**The fix.** A month-forward offset δ on launches with no hunter record. δ is the mean residual of no-record launches minus that of launches with a record, fitted on earlier test months only. Test window May 1 – Nov 12 (168 days), because April has no earlier month to fit δ.

| | Top 3 | Top 5 | Top 10 |
|---|---|---|---|
| Arm 3 rebuild | 58.3 [55.2, 61.7] | 66.3 [63.7, 68.7] | 78.6 [76.9, 80.3] |
| Fix | 57.9 [54.6, 61.3] | 66.2 [63.6, 68.6] | 78.8 [77.0, 80.5] |
| Fix minus arm 3 (paired) | -0.4 [-1.0, +0.0] | -0.1 [-0.4, +0.0] | **+0.1 [-0.4, +0.6]** |

- **Not adopted.** The top-10 interval spans 0 and top 3 slips.
- δ is small and shrinking (0.085 in May to 0.022 in November, in log votes).
- The share of no-record launches in the forecast top 10 moves from 23.6% to 25.4%, against 30.5% in the real top 10. So a level shift moves the right group a little but picks the wrong individuals. The newcomers who succeed are not marked by any input the model has.

## What would move the number

- **A pre-launch signal for which first-time hunters will do well.** The follow-graph count is the only candidate, and it first needs a dated, leak-free version (follower counts as of before 00:05).
- **The maker-team class (186 misses, oracle 82.1) is next.** It also concerns the team's history, which is thin for newcomers.
- **The 00:05 point is limited by what happens after launch.** The before-reveal forecast is about 9 points higher at top 10 on the same days.

Files: `arm3_oos.py` (rebuild with contributions), `anatomy.py`, `fix.py`, `live.py`, `anatomy.json`, `fix_result.json`, `live_days.json`, `misses_top10.csv` (ids removed).
