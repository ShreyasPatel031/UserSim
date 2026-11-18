# Orchestrator 02:34Z — py_compile, dead/stale causes, recovery

## py_compile (`ph_batch.py` slot 5)

```bash
sudo /opt/venv/bin/python -m py_compile /opt/ph/reuse/ph_batch.py
echo compile_exit=$?
```

**Output:** (empty) **`compile_exit=0`**

(Same on dead slots **5**, **33** sampled 02:35Z — not a SyntaxError fleet-wide.)

Earlier artifact: `from_cursor/slot5_py_compile_2026-11-18T0135Z.txt`

## Why slots show dead / stale (not import failure)

| Class | Slots (02:30Z measure) | Cause |
|-------|------------------------|--------|
| **dead** | 5,13,28,30,32,33,34,36,39* | Supervisor relaunching `pdeep` but **0-byte run logs**: `pdeep` often exits immediately with **no stdout** (`deep_list empty` or exit before `FINGERPRINT` / `paged`). `batch=false` in measure = no recent pull heartbeat. Slot **39** = `phlive` only (expected dead for pdeep). |
| **stale** | 26,29,35,40,41,42 | `phsuper` + batch up but **no complete saves in 15m** (`win_complete=0`); many **0-byte** or fingerprint-only runs while recovering from syntax / held-patch rollout. |
| **cf_wall** | 31 (33 was cooldown) | **Cloudflare** on **same IP** — `cf_cooldown_until` / walls in status; supervisor **does not relaunch** during cooldown (same-IP backoff). |
| **active** | 9,27,38 (upvote repull) | Pulling; fleet **0.2 cppm** from sparse completes, not full 15-slot historical throughput. |

**Contributing fixes already in flight:**

1. **`patch_upvotes_ph_end.py` held** in GCS `supervisor_strat.sh`; tarball restore of `ph_batch.py` / `paging_v2.py` on historical slots 01:38Z.
2. Some VMs still had **old supervisor** re-applying `UPVOTES_PH_END_PATCH` until **02:36Z supervisor sync** from GCS.
3. **`FORCE=1` refill** 02:36Z — **4734** handles, **~316/slot** → fresh `pdeep_list.<vm>.txt` + new per-slot `GO.*` tokens.

## Actions this message (02:36Z)

- Synced **`supervisor_strat.sh`** (no upvotes_ph_end) on slots **5–42** (excl. 39).
- **`ph_fleet_refill_lists.py` FORCE=1**
- **`ph_fleet_inplace_restart_slots.sh`** on dead **5,13,28,30,32,33,34,36** and stale/wall **26,29,31,35,40,41,42** (same IP, no rotate).

**LIVE_PRIORITY_HOLD:** no new VMs / no scale-up.

## Target

Get **≥15 active** historical pullers; confirm on next `ph_fleet_measure` + 15m tick. Re-enable `patch_upvotes_ph_end.py` only after steady `complete_ppm`.