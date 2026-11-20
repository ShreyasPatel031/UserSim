# Exit IP status logging — fleet-wide audit (orchestrator 19:52Z)

**Ask:** Every slot’s `status_*.jsonl` must record **current exit IP** at least **hourly**, and on every **block** and **resume**, starting **today**, so Population’s 60‑minute post‑block no‑rotation check can rule out silent IP changes (slots **39**, **41**, **43** were blind).

## Root cause

| Slot | Issue |
|------|--------|
| **9+ (pdeep/refresh)** | `exit_ip` only on successful `browser_open` (~line 1205 in `ph_batch.py`) — **not** on `stopped_on_block` / `browser_open_failed` / `supervisor_run_end` |
| **41, 43** | CF wall → no browser open since **Nov 18 / Nov 10**; **19:23Z** blocks had **no** `exit_ip` row |
| **39** (live) | **`phlive`** only — no `ph_batch`, status log idle since **Nov 15** |

## Fix (shipped in repo; rolling to fleet)

| Piece | Behavior |
|-------|----------|
| **`exit_ip_util.py`** | Same probe as `exit_info()` (ipinfo via sticky `PROXY_URL` + `PROXY_PORT`); appends JSONL + `gsutil` flush to `status/{VM}.jsonl` |
| **`exit_ip_heartbeat.sh`** | Background **`exit_ip_hourly`** every **3600s** on every VM with overlays |
| **`patch_exit_ip_audit.py`** | `Status.put` enriches **block + resume** events with `exit_ip` / ASN / org |
| **`supervisor_strat.sh`** | Starts heartbeat; **`exit_ip_resume`** at batch launch; **`exit_ip_on_block`** before `supervisor_run_end` |
| **`ph_fleet_live_capture.sh`** | Starts heartbeat on slot **39** |

## When it is in place

| Milestone | Time (PT) | Notes |
|-----------|-----------|-------|
| Overlays on GCS + code on `ads` | **Thu Nov 20 ~12:55 PM** | This commit |
| **Fleet roll** (all **20** RUNNING VMs, in-place) | **~1:00–1:45 PM** | `ph_fleet_roll_patches.sh` (no VM count change; **LIVE_PRIORITY_HOLD**) |
| **First hourly row** on every slot | **≤1 hour after roll** on each VM | Event `exit_ip_hourly` |
| **Block/resume rows** (e.g. **41/43**) | **Next block or relaunch** after roll | Events `exit_ip_on_block`, `exit_ip_resume`, plus patched `stopped_on_block` / … |

**Answer:** Expect **full hourly coverage on all 20 slots by ~2:00–3:00 PM PT Nov 20**; **41/43** get immediate `exit_ip` on their **next** block/relaunch (already blocked today — first row at resume or hourly, whichever comes first).

## Verify

```bash
# Per slot (GCS):
gsutil cat gs://…/status/feeder-fleet-20261108t082000z-41.jsonl | grep exit_ip | tail -5
```

Population audit should see `event` in (`exit_ip`, `exit_ip_hourly`, `exit_ip_on_block`, `exit_ip_resume`) with `exit_ip` and `proxy_port` populated.