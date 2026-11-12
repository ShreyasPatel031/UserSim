# Early hours on the stack prior; pool upvote timing; live hidden-rank blends (orchestrator 08:34Z Nov 12)

Scripts: experiments/simlab/early_stack.py (dump backtest, 5,550 launches, 238 days, month-forward from April, 186 scored days)
and experiments/simlab/live_blend.py (6 live days). Counts only; identities hashed in memory, nothing written.

## 1. Does the stack's 00:05 gain survive once launch-day comments are in?

The stack is the deployable version (clean LM + thread features th_*; productLinks and media are not known at 00:05 live).

At 00:05, STACK0 top 3 is 60.4 [57.0, 63.6] vs clean LM 56.3. The paired gain is +4.1 [+1.3, +7.0], which reproduces the
orchestrator's +4.7 and the PH agent's +3.7.

Models:
- E: the current early model.
- S: E plus the stack inputs.
- EZ, SZ: the same feature sets fit the stack's way (within-day z of every feature, target z(−log rank), alpha 10).

Top 3 (95% day bootstrap):

| cut | STACK0 | E | S | EZ | SZ | S − E | SZ − E | SZ − STACK0 | E − STACK0 |
|---|---|---|---|---|---|---|---|---|---|
| 00:05 | 60.4 | 58.2 | 59.9 | 60.0 | 59.9 | +1.6 [0.0, 3.2] | +1.6 [−0.5, 3.6] | −0.5 [−2.2, 1.1] | −2.2 [−4.5, 0.0] |
| +1 h | 60.4 | 60.6 | 62.5 | 61.3 | 62.7 | +2.0 [−0.2, 4.1] | **+2.2 [0.2, 4.3]** | +2.3 [−0.5, 5.0] | +0.2 [−3.2, 3.6] |
| +2 h | 60.4 | 63.1 | 62.5 | 63.8 | 63.4 | −0.5 [−2.7, 1.6] | +0.4 [−1.8, 2.5] | +3.0 [−0.2, 6.3] | +2.7 [−0.9, 6.1] |
| +3 h | 60.4 | 65.8 | 63.8 | 65.2 | 64.7 | −2.0 [−3.9, 0.0] | −1.1 [−3.2, 0.9] | +4.3 [0.9, 7.7] | +5.4 [2.0, 8.8] |
| +4 h | 60.4 | 64.9 | 63.3 | 65.8 | 63.6 | −1.6 [−3.4, 0.2] | −1.3 [−3.0, 0.7] | +3.2 [0.0, 6.6] | +4.5 [1.1, 7.7] |

Cap guard (days with at most one capped launch), S − E: +1.7 / +2.2 / −0.4 / −3.0 / −2.6. All intervals span 0.

Reading:
- The stack inputs carry the 00:05 lead into hour 1 (+2 points over E).
- From +2 h the launch-day comments carry the same information. th_n_pre is pre-launch commenting, and the comment counts
  absorb it. Adding the thread features then adds nothing, and costs 1–2 points at +3/+4 h.
- The schedule this supports:
  - 00:05: the stack line. It beats the current early model at 00:05 by 2.2 [0.0, 4.5].
  - +1 h: SZ, a shadow candidate (recipe early_model_recipe_v2_stack_1h.json).
  - +2 h on: E unchanged.
- Caveat: the dumps keep the top 20 threads read after the day. This applies to both E and S.

## 2. Pool members' upvote times

No upvote in held data has a real timestamp. The question cannot be answered from held data.
- The v3 events carry 1,385,591 upvotes:
  - 1,157,578 are snapshots with no time.
  - 228,004 are bounded: between the launch time and the profile read.
  - The narrowest window is 2.3 h; the median is about 180 days.
- In the raw pulls (ph_upvotes_full, 227,105 rows; signed-in scroll, 3,765 rows), `upvoted_at` is null in every row.
  ph_people_daily is daily snapshots, so day-level at best.
- Route: every held upvote came from profile reads (people_live:vm, ph_upvotes_full_p1, ph_people_daily_p1). That is page
  loads per person, and only the 5k-person pool is covered. So the count is not available live without page loads either.

## 3. Hidden rank blended with priors, live days

Days: Nov 2, 3, 4, 8, 9, 10 (Nov 11 has no clean live row yet). Counts are top-3 hits out of 18; values are top 3 / 5 / 10.

| cut (w) | published alone | published blend | clean alone | clean blend |
|---|---|---|---|---|
| 00:30 (0.25) | 7 · 38.9 / 60.0 / 76.7 | 10 · 55.6 / 63.3 / 73.3 | 10 · 55.6 / 66.7 / 78.3 | 10 · 55.6 / 63.3 / 76.7 |
| 01:00 (0.5) | 7 | 12 · 66.7 / 66.7 / 78.3 | 10 | **13 · 72.2 / 66.7 / 78.3** |
| 02:00 (0.75) | 7 | **13 · 72.2 / 76.7 / 80.0** | 10 | 12 · 66.7 / 73.3 / 80.0 |

Clean blend minus published blend, top 3: +0.0 [−16.7, 16.7] at 00:30, +5.6 [−11.1, 22.2] at 01:00 and −5.6 [−16.7, 0.0] at
02:00. That is one launch either way, consistent with the orchestrator's 10:35Z check.

The stack prior is not scored live. Hunters cannot be matched to live comment authors in held data: Nov 4 comments_ts has no
usernames, and on Nov 10 no launches.poster appears among commenters. th_n_pre then counts the hunter's own intro, giving
about 1 for every launch. The PH agent's live clean_stack line, which matches by user id from Nov 12, is the forward test.

## 1b. With the link / media block (orchestrator fields/A.pkl; page reads Oct 29 / Nov 11, not proven launch-time, not live at 00:05)

STACK0L (clean + thread + links) at 00:05 is 61.1 top 3, +4.8 [+1.8, +7.9] over clean. Over STACK0 (no links) it is +0.7 [−0.7, +2.2].

SZL is the early model fit the stack's way, with the link block added. Top 3:

| cut | E | SZ (no links) | SZL (links) | SZL − E | SZL − STACK0L |
|---|---|---|---|---|---|
| 00:05 | 58.2 | 59.9 | 60.2 | +2.0 [−0.2, 4.3] | −0.9 [−2.7, 0.9] |
| +1 h | 60.6 | 62.7 | 61.6 | +1.1 [−1.1, 3.2] | +0.5 [−2.2, 3.4] |
| +2 h | 63.1 | 63.4 | 64.0 | +0.9 [−1.4, 3.2] | +2.9 [−0.5, 6.5] |
| +3 h | 65.8 | 64.7 | 65.9 | +0.2 [−2.0, 2.3] | +4.8 [+1.4, 8.1] |
| +4 h | 64.9 | 63.6 | 65.2 | +0.4 [−1.8, 2.5] | +4.1 [+0.7, 7.3] |

Reading:
- The links do not change the conclusion. The stack's lead is an hour-0/1 effect.
- With links, the stack-method early model no longer loses at +3 / +4 h, but it doesn't beat E either.
- The +1 h shadow candidate stays the no-links SZ, which is deployable now.
