# Bundle 12a.2 = 12a.1 + explanation audit (UNDEPLOYED; orchestrator Nov 14). New named build; 12a and 12a.1 untouched.

two_predictions.py 68d6bb12 -> b31d0074 (only the "backtest" text changes; ranking, model and fallback logic are unchanged):
- 00:05 file: the accuracy line names the model that produced the order, on the 183-day rule (backtest days with at least 10 ranked launches,
  Apr-Oct 2026). arm 2 58.1 / 65.2 / 76.9; clean_nosite fallback 54.5 / 64.7 / 76.0. none_available says no model ran.
  This replaces the single 214-day arm-2 line (60.7 / 68.4 / 75.7) that was shown even when clean_nosite produced the order.
- 03:45 file by what produced the order:
  - hybrid_vm: 72.2 / 75.0 / 77.5, leave-one-day-out replay on 12 days (Nov 2-13); top-10 edge over the hidden order +4.2 [0.0, +8.3],
    not yet established. This replaces the 11-day in-sample 72.7 / 74.5 / 77.3.
  - hidden_rank_only and stale_read: 72.2 / 75.0 / 73.3, the hidden order alone. no_prior: not backtested, plus the hidden-order figure.
  - midnight_order: the 00:05 model's line, plus "(the 00:05 order, shown at 03:45)".
- deploy_b12a.sh pin: two_predictions.py b31d0074 (everything else as 12a.1).
After the today-rows fix and the fixed-prior weights (20261114_hybrid_fixedprior) are live, the hybrid line becomes
79.2 / +5.8 [+1.7, +10.0]. That is a later one-line change, not part of this build.

# Bundle 12a.1 (UNDEPLOYED; NOT the deploy target until E5 re-runs A9-A12 on it + the no-PUBLISH equivalence check)

12a.1 = verified 12a (commit 88b350e8, folder ../20261114_two_predictions/, the current deploy target) plus:
- two_predictions.py: arm-3 publish branch - midnight uses pred_arm3 only when the 00:05 parquet carries a fully filled pred_arm3 column,
  which forecast.py writes ONLY when ~/w/arm3_live/PUBLISH exists (bundle 13); otherwise the logic is the verified one. Backtest label
  for arm 3 from arm3_backtest_label.txt (absent -> "arm 3 (backtest label not set)"); inputs block gains "pred_arm3": "not published".
- lineup_reread.py + run.sh job "lineup" + sched12a 01:00: official-API line-up re-read -> raw/daily/<d>/lineup_0100.json (read-only).
- deploy_b12a.sh: pins + import gate for lineup_reread.py.
With no PUBLISH file the 0005 and prereveal files are written by exactly the verified logic (no pred_arm3 column -> arm3 False -> same
model / fallback / inputs / backtest fields; no extra key).

# Bundle 12a: the two published predictions, written on the VM (prepared 2026-11-14, NOT deployed)

Shreyas (via the orchestrator, 00:52Z Nov 14): the predictions are exactly two, the midnight one and one before the reveal, and they must be stable.
This split of bundle 12 is the minimum for that. Deploying needs Shreyas's direct word: it changes the VM crontab and adds one official
Product Hunt API read a day (03:45 PT; the same query as the hourly recorder, about 100 of the 6,250 points per 15 min).

## What runs (Pacific wall-clock time; review fixes of 01:55Z Nov 14 applied)
The VM runs Debian cron 3.0pl1 with its clock on UTC, and that cron ignores CRON_TZ (review B4). So the crontab gets one line in its own
block, `* * * * * bash /home/agent/w/tw12a/tick.sh`. Each minute, tick.sh starts the jobs in `sched12a.txt` whose America/Los_Angeles HH:MM is
now (DST-aware). It also writes a heartbeat (`last_tick`, copied hourly to results/timed_writes/tick_12a.txt). The deploy waits for a tick to prove it.

| PT | job | writes |
|---|---|---|
| 00:20, retry 00:35 | midnight: waits for the pipeline's own `results/forecast_<d>.parquet` (no API, no model run) | `results/web/predictions/<d>_0005.json` + `0005_latest.json` |
| 03:45 | rec: one extra recorder read (pipeline/hourly.py `_snapshot`, same query and lock) | raw/vote_snapshots/<d>.jsonl + warehouse part |
| 03:47, retry 03:52 | prereveal: hybrid_vm from the 03:45 read (reads up to 90 s after 03:45:00 count; the read used is in `inputs`) | `<d>_prereveal.json` + `prereveal_latest.json` |

- A retry slot is skipped if the file already exists with no fallback.
- Each run is retried once after 60 s and exits with the final rc (review B5).
- Each run writes `results/timed_writes/status_12a_<job>.json` {job, day, rc, written_at, due_pt}. Due times for the freshness audit: midnight 00:25 PT, prereveal 03:50 PT.
- **No 23:50 PT read (review B1):** the instance schedule stops the VM at 23:00 PT (`last -x`: down 07:00-08:05 UTC every day), so it would never run.
  Cost: the VM's hourly series ends with the 23:00 PT read. The last hour of votes before close is not recorded by the VM; the label is
  unaffected, since it is the official dailyRank. Moving the shutdown to 23:55 would add about 55 min of VM time a day (about $0.10), and that is an
  instance-schedule change for Shreyas.
- The 03:45 cut and every read window are built in America/Los_Angeles, not as offsets from midnight (review A9).
- The midnight job runs inside 00:05-01:00 PT. It only reads the parquet the pipeline has already written and copies one JSON to the bucket.

## The before-reveal model: hybrid_vm (only VM-produced inputs)
- Hidden top 5 = recorder `rank_now` order at 03:45 (the 03:00 read if no 03:45 read; reads must be within 65 min of 03:45 and after 23:55 PT).
- Slots 6+ = frozen ridge `hybrid_vmonly_P345_20261114.json` on z(log hidden position) -0.598, z(move since 01:00) -0.015,
  z(log1p recorder commentsCount) +0.114, z(00:05 clean_nosite `pred`) +0.217.
- The recorder's commentsCount is public before the reveal (votes are 0 until 04:00). No Data Feeder feed is used.
- Backtest, 11 days (Nov 2-12, recorder reads, label = official dailyRank, all featured launches): **72.7 / 74.5 / 77.3** top 3 / 5 / 10.
  That is the same as the published feed-based hybrid (72.7 / 74.5 / 77.3). Top 3 and top 5 equal the plain hidden rank (72.7 / 74.5);
  top 10 is +4.5 [+0.0, +9.1] over it, with leave-one-day-out weights (`experiments/ph_predict/hybrid_vmonly.py`, results/hybrid_vmonly.md).
- Fallback order, named in `fallback_used`:
  1. hybrid_vm (fallback_used null)
  2. no_prior: hybrid_vm without the clean term (forecast parquet missing)
  3. hidden_rank_only: plain hidden rank (weights file missing)
  4. midnight_order: the 00:05 order (no recorder read within 65 min of 03:45)

## File fields (both files)
`day`, `kind` (0005 | prereveal), `time`, `model` (00:05: arm2 | clean_nosite; 03:45: hybrid_vm | hidden_rank_only | midnight_order), `fallback_used` (null | clean_nosite_fallback | no_prior | hidden_rank_only | midnight_order | none_available),
`inputs` (each input present/missing; recorder read time), `written_at` (UTC), `backtest` (accuracy line),
`ranking` [{rank, id, name, score (midnight only)}].

## Tested (dry, on the VM, no upload)
Nov 12 and 13: midnight writes with model clean_nosite, fallback "clean_nosite (arm 2 missing)", as expected before the first arm-2 day
(Nov 14). Prereveal writes hybrid_vm with every input present (03:00 read; no 03:45 read existed yet). Launch names are present.

## Deploy / rollback
`bash deploy_b12a.sh <this folder>`, outside 00:05-01:00 PT:
- Checks the md5s and saves a timestamped crontab backup.
- Refuses if the crontab is empty.
- Copies the files to /home/agent/w/tw12a and syntax-checks them.
- Replaces only the exactly-matched `usersim-b12a` block, so bundle 12's block and the @reboot line are untouched in either order (review B2).
- Checks the @reboot run_daily line and waits for a tick.

`bash deploy_b12a.sh rollback` removes only this block and moves the tree aside. It never restores a whole file, and it refuses if the result would lose the @reboot line (review B3).

## Residual fixes (12:36Z Nov 14)
- prereveal: a T-read older than 03:44 PT keeps model hybrid_vm but sets fallback_used "stale_read" (done_ok fails, 03:52 retry runs, page says so).
- midnight: extra 01:30 PT slot; done_ok treats none_available (any fallback) as not done, so a late parquet replaces it.
- deploy_b12a.sh / deploy_b12.sh: the 00:05-01:00 PT guard sits below the rollback branch (rollback always allowed); deploy must run as agent.
- HARD IMPORT GATE (import_gate.py): every module each job imports, imported as cron runs it (cwd, `env -u PYTHONPATH` or the job's own
  PYTHONPATH, /opt/exp/bin/python3, -I where the job uses it); abort on any failure. b12a stages into tw12a.stage and replaces the live tree
  only after the gate. b12 also gates the arm-2 branch (pipeline forecast.py -> ~/w/arm2_live/h25_live -> training_window -> ctrl/honest).
- VM tests 12:50Z: gate ok for two_predictions (8 imports), recorder_extra (5), pipeline forecast.py (11); a missing module inside a
  function fails rc=1; the Nov 14 miss replayed (arm2_live without ctrl.py/honest.py) fails "No module named 'ctrl'" rc=1.
  DRY prereveal 2026-11-14 under env -u PYTHONPATH: hybrid_vm, fallback_used stale_read (read 03:00 PT), as on the night.
