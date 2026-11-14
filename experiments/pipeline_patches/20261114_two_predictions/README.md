# Bundle 12a: the two published predictions, written on the VM (prepared 2026-11-14, NOT deployed)

Shreyas (via the orchestrator, 00:52Z Nov 14): the predictions are exactly two, the midnight one and one before the reveal, and they must be stable.
This split of bundle 12 is the minimum for that. Deploying needs Shreyas's direct word: it changes the VM crontab and adds two official
Product Hunt API reads a day (the same query as the hourly recorder).

## What runs (Pacific time, VM crontab block `usersim-b12a`)
| time | job | writes |
|---|---|---|
| 00:20 | midnight: waits for the pipeline's own `results/forecast_<d>.parquet` (up to 40 min; no API, no model run) | `results/web/predictions/<d>_0005.json` + `0005_latest.json` |
| 03:45 | rec: one extra recorder read (pipeline/hourly.py `_snapshot`, same query, same lock; the hourly loop skips a 2nd read per hour) | raw/vote_snapshots/<d>.jsonl + warehouse part, as hourly |
| 03:47 | prereveal: hybrid_vm from the 03:45 read | `results/web/predictions/<d>_prereveal.json` + `prereveal_latest.json` |
| 23:50 | rec: day-close read (votes at 23:50 PT without the Data Feeder; the VM shuts down at 23:55) | as hourly |

The midnight job runs inside 00:05-01:00 PT. It only reads the parquet the pipeline has already written and copies one JSON to the bucket.
It makes no API call and runs no model.

## The before-reveal model: hybrid_vm (only VM-produced inputs)
- Hidden top 5 = recorder `rank_now` order at 03:45 (the 03:00 read if no 03:45 read; reads must be within 65 min of 03:45 and after 23:55 PT).
- Slots 6+ = frozen ridge `hybrid_vmonly_P345_20261114.json` on z(log hidden position) -0.598, z(move since 01:00) -0.015,
  z(log1p recorder commentsCount) +0.114, z(00:05 clean_nosite `pred`) +0.217.
- The recorder's commentsCount is public before the reveal (votes are 0 until 04:00). No Data Feeder feed is used.
- Backtest, 11 days (Nov 2-12, recorder reads, label = official dailyRank, all featured launches): **72.7 / 74.5 / 77.3** top 3 / 5 / 10.
  That is the same as the published feed-based hybrid (72.7 / 74.5 / 77.3). Top 3 and top 5 equal the plain hidden rank (72.7 / 74.5);
  top 10 is +4.5 [+0.0, +9.1] over it, with leave-one-day-out weights (`experiments/ph_predict/hybrid_vmonly.py`, results/hybrid_vmonly.md).
- Fallback order, named in `fallback_used`:
  1. hybrid_vm
  2. hybrid_vm without the clean term (forecast parquet missing)
  3. plain hidden rank (weights file missing)
  4. the 00:05 midnight order (no recorder read within 65 min of 03:45)

## File fields (both files)
`day`, `kind` (0005 | prereveal), `time`, `model` (arm2 | clean_nosite | hybrid_vm ... | plain hidden rank | midnight order),
`fallback_used` (null or the reason), `inputs` (each input present/missing; recorder read time), `written_at` (UTC), `backtest` (accuracy line),
`ranking` [{rank, id, name, score (midnight only)}].

## Tested (dry, on the VM, no upload)
Nov 12 and 13: midnight writes with model clean_nosite, fallback "clean_nosite (arm 2 missing)", as expected before the first arm-2 day
(Nov 14). Prereveal writes hybrid_vm with every input present (03:00 read; no 03:45 read existed yet). Launch names are present.

## Deploy / rollback
`bash deploy_b12a.sh <this folder>` (outside 00:05-01:00 PT): it checks md5s, backs up the crontab, copies 5 files to /home/agent/w/tw12a,
syntax-checks them, adds the cron block and checks that the @reboot run_daily line survived. `bash deploy_b12a.sh rollback` restores the crontab.
