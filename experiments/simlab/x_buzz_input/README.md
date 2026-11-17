# Does pre-launch X buzz add to the midnight forecast? Not on this evidence; closed as an input

Orchestrator request 10:34Z Nov 17. Script: `xb.py`; results in `result.json`. Counts and launch ids only.

## What exists

**Live frozen X buzz**
- `raw/ph_at_launch/<d>/x_buzz_0010.jsonl` exists for Nov 13, 15, 16 and 17.
  - Nov 13 has one mixed window (48 h ending 00:17 PT), so its pre-launch count was taken from the backfill.
  - Nov 14 has no 00:10 file.
  - Nov 17 is not final yet.
- `x_buzz_0200` and `results/grok_forecast/<d>_0030|0200.json` exist for the same days.

**Backfill**
- `x_buzz_backfill.jsonl` covers Nov 8–14. It is the same 48-hour pre-launch window, searched afterwards on Nov 15. Its post-launch fields are leaks and are not used.
- The Nov 2–4 files are empty.

**History (Sep–Oct)**
- No Grok buzz exists before Nov 8.
- The warehouse inputs already in arm 2 and arm 3 are `promo_posts_x` (pre-launch X posts, non-null for 96% of launches, above 0 for 8.2%), `promo_founder_x`, and the `x_*` follower counts.
- A month-forward test of Grok buzz is therefore impossible.

## 1. Grok's frozen top 10 against the final board

Hits at top 3 / 5 / 10. The before-reveal forecast and arm-3 live exist only on some days.

| day | Grok 00:30 | Grok 02:00 (not a midnight input) | arm 2 published 00:05 | arm 3 live | before-reveal 03:45 |
|---|---|---|---|---|---|
| Nov 13 | 33 / 20 / 60 | 33 / 20 / 60 | 67 / 80 / 80 | — | — |
| Nov 15 | 67 / 60 / 70 | 67 / 60 / 80 | 67 / 40 / 70 | — | 100 / 100 / 90 |
| Nov 16 | 0 / 20 / 40 | 0 / 20 / 30 | 33 / 80 / 70 | 0 / 80 / 70 | 67 / 80 / 80 |
| **mean, 3 days** | **33 / 33 / 57** | 33 / 33 / 57 | 56 / 67 / 73 | | |

Grok's buzz-only top 10 is below the 00:05 model on the same days. It wins on one cut (Nov 15, top 5). With n = 3 days nothing is decided, but it gives no sign of being a better forecast.

## 2. Buzz as an input to the 00:05 forecast

**Method.** The base is the published 00:05 forecast (arm 2), since arm 3 is live only from Nov 16. The adjusted forecast adds β₁ × log1p(pre-launch posts) and β₂ × "no usable count", fitted on each day's within-day residual. β is fitted leave-one-day-out on the other days, with ridge 1. The run covers 9 days (Nov 8–16): 6 backfill days, 2 live days, and Nov 13 from the backfill.

**Paired, adjusted minus base** (top 3 / 5 / 10, day bootstrap):
- −3.7 [−11.1, 0.0]
- +2.2 [0.0, +6.7]
- +2.2 [0.0, +4.4]

**Fitted β₁** is about 0.00–0.01 on every held-out day, which is effectively zero. The small changes in hits come from near-ties at the top.

**Signal checks** (launches with a count, day bootstrap):
- Spearman of log posts with day-centred final votes: **+0.16 [+0.04, +0.27]**. Buzz does track votes.
- Spearman of log posts with the 00:05 forecast's residual: **+0.02 [−0.11, +0.13]**. Nothing is left over once the forecast's existing inputs are in (promotion counts, X followers, hunter record).

**n is too small to decide.** Nine days, only two of them live and clean, cannot detect a gain of 1–2 points. Even so, the near-zero residual correlation is the more informative result.

## 3. Name collisions ("missing")

- Grok records excluded generic-name matches as a count of 0, with a note. They are flagged here by note text (generic / collision / unrelated / ambiguous).
- Flagged launches per day: Nov 13 6 of 20; Nov 15 4 of 15; Nov 16 0 of 38; Nov 17 0 of 43. The backfill flags none, so it may count collisions silently.
- No count is ever null; zeros are 60–80% of launches on the live days.
- **Does "missing" carry signal?** Mean residual of flagged minus unflagged is +0.03 [−0.02, +0.06]. No.

## Leak checks

- **Pre-launch window:** 48 hours ending 00:00 PT on the launch day. The live files were fetched at 00:21–00:24 PT, but the window itself ends at 00:00, so the count is frozen before 00:15.
- **Launch-day window:** 00:00 to 00:21 PT. It ends after 00:15, so it is **not used**.
- **Grok's 00:30 forecast** reads that launch-day window, about 6 minutes past the 00:15 rule. It is shown as its own line only.
- **Grok's 02:00 forecast** uses posts up to 02:00 PT and is reference only.
- **Backfill:** the pre-launch window is fixed, but the search ran on Nov 15, after the outcome. Two possible effects:
  - deleted posts would be missed;
  - a search ranking may favour launches that did well.
  Neither would hide a signal, and both could inflate one, yet the residual correlation is still about 0.

## Decision (rule: deploy / scored shadow if informative / close)

- **Not deployed.** Nothing clears noise; top 3 leans negative.
- **As an input: closed.** Buzz tracks votes but adds nothing beyond the 00:05 model's own inputs. History already holds a pre-launch X post count (`promo_posts_x`).
- **Grok's top 10 as a scored shadow: not informative** (33 / 33 / 57 on 3 days, against 56 / 67 / 73 for the 00:05 model). Reopen only if about 30 clean live days accumulate and show a positive residual correlation.
