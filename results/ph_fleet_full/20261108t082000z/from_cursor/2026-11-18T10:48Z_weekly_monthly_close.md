# Weekly / monthly close — runnable plan (confirm by Fri Nov 21)

## Weekly close — **Sun Nov 22, 23:45 PT**

| Item | Value |
|------|--------|
| Cron hook | `scripts/vm/ph_at_launch_close_cron.sh` **2345** PT (see cloud-agent `ph-weekly-close-2345pt` timer / crontab) |
| Execution | Agent VM has **no** Camoufox → **`ph_weekly_close_fleet.sh`** (not local `ph_weekly_close.sh`) |
| Fleet VM | **`PH_WEEKLY_CLOSE_SLOT=26`** (default), sticky IP, Camoufox in `/opt/venv` |
| Smoke **2026-11-18** | Slot 26: `camoufox_import_ok`, `bb_capture.py` on GCS tools path |
| Command | `PACE_ENV_FILE=…/pace.env bash scripts/vm/ph_weekly_close_fleet.sh` (day defaults to today PT) |
| Output | Route-4 homepage capture via `bb_capture.py` → `raw/ph_at_launch/…` (same as Population weekly close) |

**Nov 17 23:45Z skip** was agent-only Camoufox check; fleet path is now the documented default when import fails locally.

## Monthly re-read — **Nov 30, 23:50 PT** (official API; not browser)

| Item | Value |
|------|--------|
| Cron hook | `ph_at_launch_close_cron.sh` **2350** PT + `ph-monthly-reread-2350pt` timer |
| Script | `scripts/vm/ph_monthly_reread.sh` on **agent VM** (GraphQL / snapshot backfill; **no Camoufox**) |
| Env | `MVP_GCS_BUCKET`, `PH_AT_LAUNCH_GCS_ROOT`; token `PH_API_TOKEN` or `PH_API_DEV_TOKEN` for live mode (else `--backfill-from-snapshots`) |
| Note | Orchestrator cited **23:45** for month-end; repo schedule is **23:50 PT** (5 min after weekly) |

## LIVE_PRIORITY_HOLD

Weekly/monthly jobs do not scale historical fleet; weekly uses **one** existing slot SSH only.

## Operator checklist (before Nov 22 / Nov 30)

1. Ensure slot **26** `RUNNING` and not in prolonged `cf_wall`.
2. `bash scripts/vm/ph_weekly_close_fleet.sh $(TZ=America/Los_Angeles date -v-1d +%F)` optional dry run Sun morning.
3. Confirm agent monthly timer fires; verify `raw/ph_at_launch/monthly_reread/<YYYY-MM>/` row after Nov 30 run.