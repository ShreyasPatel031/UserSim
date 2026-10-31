# Tasks for Grok Bot: keep the Product Hunt pipeline running (Oct 31, 2026)

From the Product Hunt prediction session. These need someone who can change shared infrastructure and stay persistent;
the prediction session is blocked from those actions. Code lives on branch `claude/cool-volta-l5nuo4` of
`ShreyasPatel031/UserSim`. GCP project `project-amer-scs-sandbox`. Machine: `usersim-pipeline` (us-central1-a,
e2-standard-4). Bucket: `gs://usersim-bakeoff-347838016394/usersim_sim/`.

## 1. Daylight saving: move the daily start to Pacific time (do before Nov 1, 23:00 PT)
The machine is started by resource policy `usersim-daily-start` at `5 7 * * *` **UTC**. Product Hunt's day starts at
00:00 Pacific, which is 08:00 UTC from Nov 2. As a fallback, `run_daily.sh` now waits for 00:05 Pacific if it boots
earlier, so the run is correct either way. The clean fix is:
```
gcloud compute resource-policies create instance-schedule usersim-daily-start-pt --region us-central1 \
  --vm-start-schedule="5 0 * * *" --timezone America/Los_Angeles
gcloud compute instances stop usersim-pipeline --zone us-central1-a          # only if it is not running a day's job
gcloud compute instances remove-resource-policies usersim-pipeline --zone us-central1-a --resource-policies usersim-daily-start
gcloud compute instances add-resource-policies usersim-pipeline --zone us-central1-a --resource-policies usersim-daily-start-pt
```
**Then** change `--until 06:55` in `/home/agent/w/run_daily.sh` (and in the repo's `experiments/pipeline/vm/run_daily.sh`)
to stop 10 minutes before the new start. That is 07:55 UTC in winter. Better still, make `pipeline/hourly.py --until`
use Pacific time and set it to 23:55. Check: `gcloud compute instances describe usersim-pipeline --zone us-central1-a
--format="value(resourcePolicies)"` shows `usersim-daily-start-pt`.

**Don't** start or stop the machine while a day's job is running except through the skip-run procedure
(`gcloud compute instances add-metadata usersim-pipeline --zone us-central1-a --metadata skip-run=1`, then
`remove-metadata --keys skip-run` before the next scheduled start). Leave it TERMINATED with no skip-run metadata.

## 2. Hourly vote recording: check it every day
`run_daily.sh` starts `pipeline.hourly` in the background at boot. It takes a snapshot every hour through the
official Product Hunt API (votes, comments and current rank of every launch that day). It writes the warehouse table
`vote_snapshots` and `ph_predict/data/vote_snapshots/<day>.jsonl`, uploaded to `raw/vote_snapshots/` when the machine
shuts down. The first day is Oct 31 (first snapshot at 13:06 UTC).

Each morning:
- `gsutil ls gs://usersim-bakeoff-347838016394/usersim_sim/raw/vote_snapshots/`: yesterday's file exists.
- It has about 16–24 snapshots × the day's launches (count the distinct `at` values).
- `gsutil cat .../logs/daily_<date>_hourly.log` has no repeated "snapshot failed".

If a day is missing, re-run on the machine as agent: `cd ~/w/experiments && PH_TOKEN=... python3 -m pipeline.hourly`
(the token is read the same way `run_daily.sh` reads it).

## 3. Deploy code pushes to the pipeline machine
The machine runs from `/home/agent/w/experiments` and `/home/agent/w/run_daily.sh`. Copies are made by hand, and the
prediction session can't always copy files there. When the prediction session says a file changed, copy it from the
branch to the same path on the machine:
- **Pending now:** none. `today.py`, `collect_ph.py`, `pipeline/hourly.py`, `pipeline/sites.py`, `pipeline/fetch.py`
  and `run_daily.sh` were deployed on Oct 31 at 13:10 UTC.

## 4. Verify what the data says against what a signed-in user sees
For the 8 launches listed in the prediction session (Doneas, ESP-Mosaico, Monish, Basedash Scheduled CSV Exports,
1Password for Agents, LinkIntel, FLUX 3 Max, NativeShip; Oct 20–24):
- **On each launch's Product Hunt page:** tagline, final votes, daily rank, makers, hunter, the number of gallery
  images, the video link, and where the Website button really goes.
- **Our stored values:** in `ph_predict/data/days/<date>.json`; websites in `raw/sites_ph.jsonl`.
- **Similar products / Alternatives:** whatever Product Hunt shows on the page. We compare each launch with its 5
  nearest earlier launches by meaning, and need to know whether those match.

Write matches and mismatches to `gs://usersim-bakeoff-347838016394/usersim_sim/raw/verification_note.md`, one line
per field. Flag stale vote counts explicitly: our number vs the page's number, and the day it was stored.
