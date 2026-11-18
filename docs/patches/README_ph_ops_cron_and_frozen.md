# Two ready-to-apply drafts (NOT applied; for Shreyas, with the model switch)

1. `frozen_0005_snapshot.patch` — forecast.py saves today's served 00:05 feature rows to `data/frozen_0005/<day>.parquet`
   (+ bucket `results/frozen_0005/`); makerfix_shadow.py reads that snapshot instead of rebuilding features later.
   Why: on Nov 12 the shadow's deployed replay differed from the published 00:05 forecast in 15 of 37 positions (inputs
   filled after 00:05). Apply: `git apply docs/patches/frozen_0005_snapshot.patch`, deploy as usual (merge to main).
2. `ph_ops_cron.sh` + `ph_ops_crontab.txt` — the PH agent's timed shadow writes (00:05 clean shadow, confidence, P030-P4,
   R/C points, weekly/monthly day-end, est, R4, running ranks, web_forecast_0005, scoreboard) as one idempotent script run
   at :17 and :47 on usersim-pipeline (00:05-23:00 PT). Each step runs only when its bucket output is missing; nothing
   runs 00:05-01:00 PT, so the day-end lines move from 00:17 PT to the first run after 01:00 PT. Removes the dependency
   on an agent session (Nov 12: P2-P4 / R0 writes missed during a usage-limit pause). Install line in the crontab file.
