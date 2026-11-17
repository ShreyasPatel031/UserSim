# Weekly and monthly north-star cuts, scored live

Orchestrator request 09:33Z Nov 17. Script: `score.py` (read-only; writes `results.json` here). Counts and launch ids only.

## Which periods

Product Hunt weeks run Monday to Sunday PT (`period_parts.period`). The week that just closed is **Nov 9–15** (close Sun Nov 15 23:59 PT). The one before it is **Nov 2–8**. "Nov 10–16" in the request maps to Nov 9–15. Month: **October 2026**.

**Truth** is the weekly or monthly rank from the first warehouse read after the close that holds every day of the period with no null rank (`results/web/truth_weekly.json`, `truth_monthly.json`):

| period | truth read | launches ranked |
|---|---|---|
| week Nov 9–15 | part `20261116T081800`, **Nov 16 00:18 PT** (PH API `weekly_rank`) | 203 |
| week Nov 2–8 | part `20261109T081821`, Nov 9 00:18 PT | 221 |
| October | part `20261101T141331`, Nov 1 06:13 PT | 908 |

**No weekly-leaderboard page read was captured** for Nov 15 or Nov 16, at 23:45 PT or any other time. `raw/leaderboard/` holds only daily close reads; the Nov 15 one is the daily board read at 00:06 PT on Nov 16. The weekly truth is therefore the API's `weekly_rank` at 00:18 PT Nov 16, about 18 minutes after the close.

## Lines scored

Each line is scored at a call point by hits: how many of its top k are in the final top k, for k = 3, 5, 10. The ceiling is how many of the final top k had already launched by the call.

- **Board (votes only / with predicted entrants).** These are the live `period_writer` files, written at about 01:20 PT the next day. Where no live file exists, the board is replayed from the warehouse reads held at that time; replay is never pooled with live.
- **`weekly_live:<point>`.** The other writer's `results/weekly_live` files (dayend, est, R4, running, running_g, reread).
- **Summed published daily forecasts.** Every launch of the period up to the call day, ranked by its own published 00:05 arm-2 prediction (`raw/daily/<d>/forecast_<d>.parquet`). No votes are used.
- **Summed arm-2 and arm-3 rebuilds.** The same ranking using the month-forward rebuild predictions, which exist for Apr 1 to Nov 12 only.

## 1. Weekly

### Week Nov 9–15 (live)

| line (call) | top 3 | top 5 | top 10 | ceiling |
|---|---|---|---|---|
| **board with entrants**, live (Sun 00:05 call, file 01:27 PT Sun) | 3 | 5 | 9 | 3/5/10 |
| board votes only, live (same call) | 3 | 5 | 9 | 3/5/9 |
| board votes only, live (Sat call) | 3 | 5 | 8 | 3/5/9 |
| board votes only, live (Fri call) | 3 | 4 | 7 | 3/4/7 |
| weekly_live R4 (Sun 08:20 PT) | 3 | 4 | 9 | 3/5/10 |
| weekly_live est (Sun 04:34 PT) | 3 | 4 | 8 | 3/5/9 |
| weekly_live running / running_g (Sat day-end, written 04:33 PT Sun) | 3 | 5 | 9 | 3/5/9 |
| **sum of published daily forecasts** (Sun 00:05, all 7 days held) | **0** | **0** | **3** | 3/5/10 |
| sum of published daily forecasts (Fri 00:05) | 0 | 1 | 3 | 3/5/9 |
| arm-2 and arm-3 rebuilds summed | not scorable: rebuild predictions end Nov 12 (Mon–Thu only: 1/1/3) | | | |

The board with entrants and the votes-only board tie on the one live Sunday call: 3/5/9 each. The backtest gain of +2.6 / +5.1 / +7.1 cannot be checked on a single call. The other writer's four Sunday "dayend / running / running_g / reread" files were written after the close, so they are not forecasts and are not scored.

### Week Nov 2–8 (no live board; the writer started Nov 12)

| line (Sun Nov 8 00:05 call) | top 3 | top 5 | top 10 | ceiling |
|---|---|---|---|---|
| board votes only, replay | 3 | 4 | 9 | 3/5/10 |
| arm-2 rebuild summed | 0 | 1 | 3 | 3/5/10 |
| arm-3 rebuild summed | 0 | 1 | 4 | 3/5/10 |
| sum of published daily forecasts | not scorable: no forecast files for Nov 2, 5, 6 and 7 | | | |

The Nov 5–7 replay boards are stale (days missing; 56 launches held), as already flagged in the track record.

### Backtest of the summed lines (28 weeks, Apr–Oct)

Hits / k × 100, with a week bootstrap.

| call | line | top 3 | top 5 | top 10 |
|---|---|---|---|---|
| Sun 00:05 | arm-2 rebuild summed | 17.9 [10.7, 26.2] | 26.4 [20.0, 33.6] | 40.4 [36.1, 44.6] |
| Sun 00:05 | arm-3 rebuild summed | 15.5 [8.3, 22.6] | 27.1 [19.3, 35.7] | 39.3 [35.0, 43.9] |
| Sun 00:05 | arm 3 minus arm 2 (paired) | −2.4 [−6.0, 0.0] | +0.7 [−2.9, +4.3] | −1.1 [−3.6, +1.4] |

The board track record so far is 1/4/8 (Oct 26 week, stale), 3/4/9 (Nov 2 week, replay) and 3/5/9 (Nov 9 week, live). That is roughly 75–90% at top 10, against about 40% for the summed lines.

Summing the daily forecasts is not a usable weekly forecast. The daily models order launches within a day; they do not carry vote levels across days, which differ by weekday and line-up. The top of the week also depends mostly on votes after launch. Within-week Spearman of the published prediction against the final weekly rank is 0.76, but top-k overlap is poor.

## 2. Monthly: October

| line (call) | top 3 | top 5 | top 10 | ceiling |
|---|---|---|---|---|
| board votes only, replay (Oct 31 00:05) | 3 | 5 | 10 | 3/5/10 |
| board votes only, replay (Oct 29 00:05) | 3 | 5 | 9 | 3/5/9 |
| board, Oct 8 / 15 / 22 calls | no board: the first held read is Oct 28 | | | |
| arm-2 rebuild summed (Oct 31 / 22 / 15) | 1/1/1 · 1/1/1 · 1/1/2 | | | |
| arm-3 rebuild summed (Oct 31 / 22 / 15) | 1/1/2 · 1/2/2 · 1/2/2 | | | |
| sum of published daily forecasts | not scorable: no October forecast files with vote levels (`forecast_0005` has ranks only, from Oct 25) | | | |
| live monthly board | none for October (`monthly_live/` and the `probabilities/*_monthly` files start Nov 11–12) | | | |

Monthly backtest of the summed lines (the 6 months held with a complete truth read: May–Oct; month bootstrap), last-day call:
- arm 2: 5.6 [0, 16.7] / 6.7 [0, 13.3] / 15.0 [8.3, 21.7]
- arm 3: 11.1 [0, 22.2] / 6.7 [0, 13.3] / 16.7 [10.0, 20.0]

## 3. Leak check

- **Published daily predictions.** Each `forecast_<d>.parquet` was written between 00:18 and 00:26 PT on its own day (gsutil times, Nov 3–17). The inputs are arm 2's pre-launch fields (hunter followers, X followers, promotion counts). Among the 84 model columns, none is a weekly, monthly, vote or final-rank field. The only rank-named ones are within-day relative features and `C_prev_best_rank`, which uses the team's earlier launches dated on or before d−2.
- **Rebuild predictions.** These are month-forward: trained on earlier months, with inputs dated before 00:05 of each launch day (the arm3_oos harness).
- **Live board files.** They were written at 17:36 PT Nov 13, 04:45 PT Nov 14 and 01:27 PT Nov 15. That is before the close of Nov 15 23:59 PT. They use the warehouse running votes held at write time, never final weekly votes. The file written Nov 16 for Nov 15 has no board and shows no chance after the close.
- **weekly_live files.** Four Sunday files were written after the close: dayend, running and running_g at 01:10 PT Nov 16, and reread at 05:16 PT Nov 16. They are excluded. All other files were written before the close.
- **Replay boards** use only reads with a timestamp at or before the call (`period_parts.held`).

**Result: no forecast line used final weekly or monthly votes.**

## 4. What is not written live, and the smallest shadow job

**Written live already:**
- the running weekly and monthly boards (`tmp/e5/website/probabilities/<D>_weekly|monthly.json`, daily since Nov 12; the board with entrants since Nov 14);
- the other writer's `results/weekly_live` and `monthly_live` files (since Nov 9–11).

**Not written anywhere:**
- a forecast frozen at the period's open (Monday 00:05 PT, or 00:05 PT on the 1st);
- the summed daily-forecast line;
- October monthly forecasts.

So the open-of-period call and the summed line cannot accumulate.

**Spec, `period_open_shadow.py <D>`.** About 40 lines, CPU only, no Product Hunt requests. Cron at 00:35 PT, after `forecast_<D>.parquet` lands at about 00:20 PT. It runs every day but acts only on Mondays and on the 1st.

1. **Inputs:** `raw/daily/<D>/forecast_<D>.parquet` (arm-2 `pred`), plus the previous six days' forecast parquets for the summed-line rows.
2. **On a Monday, write** `results/period_shadow/week_<D>_open.json` with:
   - Monday's line-up ranked by `pred`, as the open-of-week call (ids and predicted rank only);
   - the backtest ceiling note: on average 16.9% of the final weekly top 10 launched on the Monday (29 weeks, Apr–Oct).
3. **On the 1st, write** `results/period_shadow/month_<YYYY-MM>_open.json`, the same for day 1. Day 1 holds 5.0% of the final monthly top 10 (6 months).
4. **Every day, append** one row per period to `results/period_shadow/sum_<period>.jsonl`. The row is the summed-published ranking at that call (top 30 ids), so the summed line accumulates call by call.
5. **Score** with `weekly_monthly_live/score.py` once `truth_weekly.json` / `truth_monthly.json` mark the period "ok" (Mondays at about 00:20 PT for weeks).
6. **Writer:** the VM, under the single-writer rule. It is not deployed from this container.

## Bottom line

- The live weekly board finished at 3/5/9 for Nov 9–15 (Sunday call, entrants and votes-only alike). That matches the replay Nov 2–8 board at 3/4/9.
- Summing the daily forecasts is about 40% at top 10 in the backtest, and was 0/0/3 live. It should not be shown as a weekly forecast.
- No weekly-page close read exists; the truth is the API weekly rank read at 00:18 PT Nov 16.
