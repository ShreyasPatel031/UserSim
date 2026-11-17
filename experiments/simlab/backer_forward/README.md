# Forward backer prediction: Nov 13–16 rescore, the complete-rule change, and the nightly job

E5, Nov 17 2026.

**The metric** (unchanged) is recall at N: of the held people who voted for a launch, the share named in advance.
- N is the number of observed backers.
- A backer counts only if the person was held before the list was frozen (a read before 00:00 PT of the day) and was re-read after the day closed.
- Arms: CF-only (the frozen list) and raw (the most active held people over the 30 days before the day).

## 1. Nov 13–16: the CF line still cannot be scored

**Store used:** republished Nov 17 08:56Z. Its upvote events were built at 01:07Z and were read until Nov 16 22:37Z, so they do not include the Nov 16 re-read that landed at 08:24Z.

| Day | Frozen CF list | Listed people re-read after the close | Held people re-read after the close | Observed backers (all held) | Raw arm recall (all held) |
|---|---|---|---|---|---|
| Nov 13 | 2,256 | **0** | 14,989 | 64 (18 launches) | 1.6% |
| Nov 14 | 2,276 | **0** | 8,238 | 78 (25 launches) | 29.5% |
| Nov 15 | 2,263 | **0** | 3,066 | 38 (10 launches) | 5.3% |
| Nov 16 | 2,312 | **0** | 0 (not closed in this store) | — | — |

Pooled raw arm, Nov 13–15: 14.4% [1.6, 29.5] over 53 launches and 180 backers. Three days is too few for the interval to mean much.

- **Why the CF arm has no score.** The listed people were last read around Nov 10–11 (median), and none has been read since.
  - The re-reads after Nov 12 went to other held people.
  - The priority files with the listed ids (`tmp/e5/private/refresh_priority/<day>.tsv`, written Nov 16 18:08Z) were not used by the re-read.
  - This is the same blocker as on Nov 15, and it sits with the population agent and fleet.
- **Leak checks:**
  - lists frozen with reads before 00:00 PT of each day;
  - CF fitted on upvotes dated before the day;
  - no follows used.
  The Nov 13 and Nov 14 lists were built after those days had started, from reads filtered to before the freeze.

## 2. The Nov 17 complete rule against the old 25–29%

The same frozen lists, the same launches (Nov 8–12) and the same store were scored three ways, changing only which people count as "held":

| Held people counted | Launches | Observed backers | CF-only | Raw | CF minus raw |
|---|---|---|---|---|---|
| All held people | 139 | 2,151 | 20.7 [2.9, 27.3] | 18.4 [7.5, 22.8] | +2.3 [−5.6, +5.1] |
| Complete, old rule (Nov 16 store) | 131 | 1,718 | 23.7 [3.2, 28.9] | 20.7 [6.9, 24.7] | +3.0 [−3.9, +4.4] |
| **Complete, Nov 17 rule** | 94 | 631 | **4.9 [0.6, 8.9]** | 5.2 [1.5, 8.1] | −0.3 [−2.1, +1.1] |

- **Under the old rule the line is where it was:** 23.7%, within the earlier 25–29% given a newer store.
- **Under the Nov 17 rule it falls to about 5% for both arms.**
  - Observed backers fall from 1,718 to 631.
  - The people who stay "complete" are mostly not the ones the lists named, nor the most active.
  - The new rule ("no_signed_in_pass") seems to drop the heavy voters who carried the line.
- **This is a change in who is counted, not in the model.** Which population the north-star line should be quoted on needs a decision: all held, old complete, or new complete.

## 3. Nightly job

`backer_forward_nightly.py` scores the last 4 closed days, for all held people and for complete people. It writes `raw/_audit/backer_prediction/<day>.json` with:
- counts and rates;
- the coverage diagnostics: listed people re-read, held people re-read, store read time;
- a `scorable_CF` flag.

There are no person ids in the files. Nov 13–16 are written.

It runs as step 8 of E5's nightly chain (09:47Z), after the population agent's store republish (about 08:56Z). Nov 17 will be scored on the first night after its re-read lands in the store's events.

Files:
- `backer_forward_score.py` (the arm scorer with a held-people filter);
- `backer_forward_nightly.py`;
- per-day files `2026-11-13.json` … `2026-11-16.json`;
- `rescore_nov8_12_*.json`.
