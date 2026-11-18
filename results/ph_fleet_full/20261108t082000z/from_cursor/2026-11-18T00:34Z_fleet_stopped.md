# Fleet stopped — 2026-11-18T00:34Z (orchestrator)

## Slot 5: `py_compile` / import

```bash
sudo /opt/venv/bin/python -m py_compile /opt/ph/reuse/ph_batch.py
# (no output — success)

sudo /opt/venv/bin/python -c "import ph_batch"
# (no error)
```

**There is no current `SyntaxError` on slot 5.** The prior `UPVOTES_PH_END` broken `_uv` line was already repaired; `patch_upvotes_ph_end.py` in overlays now emits the multi-line `_run` / `_tm` / `_uv` form.

## Empty run logs (orchestrator evidence)

Recent logs (`run_20261118T0031Z` … `0036Z`) are **0 bytes** because `pdeep` often exits with **no stdout**:

- Supervisor launches: `ph_batch.py --mode pdeep --token …` → `execv` → `pdeep.py`.
- With `PDEEP_MODE=full` (from `strategy.env` via `load_strategy`), manual run: **`exit=0`**, **`deep_list empty`** path (`return 0`, event `done people=0`) — nothing printed to the run log.
- The last non-empty log (`run_20261118T0006Z`) is only `FINGERPRINT_REUSED port 12323` — browser identity step, then the batch ends before `paged` lines (same-token retry loop + empty/no-pull exit).

So the fleet “fully stopped” symptom is **not** `ph_batch` dying at import; it is **near-zero productive pulls** (empty queues / immediate `pdeep` exit / supervisor relaunching empty runs).

## Fixes applied this turn

1. **`supervisor_strat.sh` line 124** — avoid bash redirect error when `cf_backoff_n` is missing (`[[ -f … ]]` before `tr`). That stderr line appeared every supervisor loop on all slots.
2. **`scripts/vm/ph_weekly_close_fleet.sh`** — weekly close runs on a **fleet VM with Camoufox** (default slot **26**), not the cloud-agent image.

## Weekly close (Nov 22 and thereafter)

- **23:45 PT** must use **route-4 homepage “Last week”** (`ph_weekly_close.sh` / `bb_capture.py`), not API-only.
- Cloud-agent cron (`ph_at_launch_close_cron.sh`) correctly **SKIPs** when Camoufox is absent on the agent VM.
- **Plan:** at 23:45 PT invoke  
  `bash scripts/vm/ph_weekly_close_fleet.sh [YYYY-MM-DD]`  
  (optional `PH_WEEKLY_CLOSE_SLOT=26`). That SSHs to a running feeder VM, runs `bb_capture.py`, and writes through the existing GCS tools path.
- For **2026-11-22** (Saturday): same cron/timer fires at **23:45 PT** with `DAY=2026-11-22` (or default “today PT” if run on that calendar day).

## Fleet recovery (still in progress)

- `ph_fleet_syntax_fix_restart.sh` remains the rollout for dead/stale historical slots (`py_compile` gate + `phsuper` restart); slot **39** stays on `phlive` only.
- **LIVE_PRIORITY_HOLD:** no historical fleet scale-up while live feeds are critical.