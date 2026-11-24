# Structural shortlist written by the VM (orchestrator 13:30Z Nov 24)

**Cause of the missing Nov 24 file:** the nightly write ran as a scheduled task delivered into the PH ops agent session (02:21 PT). On Nov 24 that session's worker was down from about 10:00Z to 13:30Z, so the task queued and the file was not written before E5's re-rank. The frozen four-inputs and promo_posts rows were delayed for the same reason.

**Change, on usersim-pipeline:**
- ~/w/tw12a/run.sh 208a1587 → 8f032a1c: job case `shortlist`, DUE 01:20.
- ~/w/tw12a/sched12a.txt 5dca79f9 → 73c5b085: `01:20 shortlist`, plus retry `02:40 shortlist`.
- ~/w/experiments/ph_predict/structural_shortlist.py (cef1eb53, new):
  - `live <d>` builds the shortlist from the frozen 00:05 parquet, with no refit;
  - it uploads to results/structural/<d>/shortlist.json;
  - `SKIP_DONE=1` leaves an on-time file alone.

**Schema (same as Nov 23):**
- Every launch with structural score and rank (arm 3; arm 2 alongside), plus top10/15/20 id lists.
- `frozen_at`: the parquet's write time.
- `model_version`, `on_time` (written before 03:45 PT) and `backfill`.
- No truth.

**Checks:**
- check passed.
- Rehearsal on 2026-11-24 from scratch copies, with uploads refused by a gsutil stub and log/status in scratch: rc 0, 42 launches, top 20, frozen_at 08:23:22Z.

**Rollback:** `bash ~/w/stage/20261124_structural_shortlist_vm/deploy_shortlist.sh rollback` (restores run.sh / sched12a.txt and removes the script).
