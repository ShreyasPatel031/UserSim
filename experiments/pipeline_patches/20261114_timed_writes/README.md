# Bundle 12: timed writes as cron jobs on the pipeline VM (prepared 2026-11-13, NOT deployed)

> The tarball eecc0f55 / ff04f7b9 predates the inputs_backup job (997a2487) and hr_clean_arm2; it is rebuilt with both on Nov 14 morning and this README gets the new commit + md5 before any deploy.

Asked by the orchestrator at 22:45Z Nov 13. Deploying needs Shreyas's direct word.

## Why
Every published point after 00:05 PT (P030 mrep, P1/P2 hr_clean, P3/P345 hybrid), the shadows, the why files and every website file are
written today by the PH ops Claude session's 2-hourly routine. If that session is stopped (usage limit, restart), they stop too, and the
00:30 / 01:00 points are written at the 02:17 PT run, not at their clock times. Bundle 12 runs the same scripts as cron jobs on
usersim-pipeline at their real clock times. No session is needed. The session's routine stays as a catch-up: every job skips when
its output exists, so both can run.

## What it installs (nothing of the deployed pipeline is changed)
- `/home/agent/w/tw/`: code from a pinned tarball `gs://.../deploy/b12/tw_code_eecc0f55.tgz` (md5 **ff04f7b9**, 2.8 MB; built by
  `build_b12.sh eecc0f55`). It holds experiments/ph_predict (*.py, results/frozen, small result files), experiments/pipeline (warehouse reader),
  h25/ (the shadow scripts as run today), and E5's pinned code (why_writer @ fcbcd617, team_shadow @ 4e4dd4e9, follow_shadow @ 3c399c39,
  as plain copies with `.pin` files; no git on the VM).
- Own results dir, own warehouse cache (`USERSIM_CACHE=/home/agent/w/tw/cache`, rsynced from the bucket tables), own tmp and logs.
  The pipeline's data dir is used read-only through a symlink.
- A crontab block between `# BEGIN usersim-b12` / `# END usersim-b12` (`tw.cron`, Pacific times). The existing
  `@reboot ... run_daily.sh` line is kept and checked after install.
- Smoke test before deploy (done here on a local copy of the tarball): every module imports; a dry run of P1 for Nov 13 from the tarball
  gives the same hr_clean ranks as the routine-written file (20 of 20).

## Schedule (Pacific)
| time | job | needs |
|---|---|---|
| 00:20 | shadow_clean (makerfix_shadow: unfixed/makerfix/clean/clean_nosite) then conf_live | the pipeline's forecast parquet (waits up to 30 min) |
| 00:30 | P030 (published mrep) | forecast parquet, clean shadow (waits until 00:55), comments_ts |
| 00:45 | P0 | same |
| 01:00 | P1 | same |
| 01:05 | shadow_h25, shadow_readable, e5 (follow + team), why (why file, drivers, top-3 confidence) | 00:05 read, store_v3 |
| 01:10 | dayend (weekly/monthly day-end + running ranks for yesterday), web_forecast, scoreboard | |
| 02:00 / 03:00 / 03:45 / 04:00 | P2 / P3 / P345 / P4 (each followed by web_forecast + scoreboard) | |
| 04:05 / 04:20 / 04:35 | R0 / R0q + weekly_est / R0h | live capture |
| 05:05 / 06:05 / 08:05 | R1 + C05 + V05 / R2 + C06 / R4 (+ weekly r4) + V08 | |
| 08:10 | daily_scores (makerfix_score, confidence score; Mondays weekly score + growth fit; 1st monthly score), scoreboard | |
| 10:05 / 12:05 / 16:05 | V10 + why_after (+ team relog) / C12 + V12 / C16 | |
| 22:30 | inputs_backup: arm-2 inputs (VM ph_predict/data minus vote_sim arrays, + deployed arm-2 code) to `raw/model_inputs/arm2/<week Monday>/`, changed files only, manifest rewritten, `raw/model_inputs/arm2/latest.json` pointer (orchestrator 23:46Z) | |
| 02:15, 05:15, 09:15, 13:15, 17:15, 21:15 | catch-up: every job above; each skips if its output exists | |

Each job logs one line, `<job> <day> written at <UTC> | inputs: x:present y:missing | <script status>`, to
`/home/agent/w/tw/logs/<day>.log`, copied to `gs://.../results/timed_writes/<day>.log`.

## Inside 00:05-01:00 PT: how collisions are avoided
- Only four jobs run in the window: shadow_clean (00:20), P030 (00:30), P0 (00:45) and conf_live. web_forecast / scoreboard refuse in the window
  and run at 01:10.
- **API budget: zero.** None of the jobs makes a Product Hunt request (bucket reads and local CPU only). `PH_TOKEN` is unset in the job
  environment. No Gemini or other LLM calls.
- **Pipeline order:** shadow_clean starts only after the pipeline's `forecast_<d>.parquet` is in the bucket, i.e. after the launches and
  forecast steps. It reads the data dir and never writes into it (all outputs go to the tw tree). P030 waits for the clean shadow.
- **CPU / IO:** every job runs `nice -n 19 ionice -c3` with 2 LightGBM threads. The pipeline's later steps (comments, people, ranks) are
  network-bound. The shadow trains 5 seeds in about 2-3 min.
- **Locks:** one flock per job; a second start of the same job exits.
- **Warehouse:** own cache, so the pipeline's ~/.usersim_sim is never synced or locked by these jobs.
- P030 is written without the h25_th / readable_v2_th shadow columns (those shadows run at 01:05, outside the window). The published mrep
  column only needs the clean shadow.

## Deploy / rollback
```
gcloud compute ssh usersim-pipeline ...   # outside 00:05-01:00 PT
bash deploy_b12.sh eecc0f55 ff04f7b9      # fetch tarball, md5 check, back up crontab (+ any earlier tw tree), extract, smoke-test imports, install cron block
bash deploy_b12.sh rollback               # restore the crontab backup; move the tw tree to backup_b12/
```
After deploy, the PH ops routine keeps running as catch-up (no double writes: every write skips when its output exists).

## Not included / follow-ups
- hr_clean_arm2 (approved 21:06Z as a forward shadow, to be added after tonight's runs) goes in by rebuilding the tarball at the new commit
  (`build_b12.sh <commit>`) and redeploying with the new md5.
- The VM powers off 23:55-00:05 PT, so nothing runs then (nothing is due).
