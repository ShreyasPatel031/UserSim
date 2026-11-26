# Steady 20-IP Pool & External Apify Bridge (`usersim_core/fleet/`)

Turnkey coordination utilities supporting the 20-VM IPRoyal puller fleet (`feeder-fleet-20261108t082000z-*`) and external Marketplace signal collection.

## 1. Root Causes Addressed (Diagnosed with `fleet-cursor`, `2026-11-26T03:50Z`)
1. **`cf_wall` Restart Loop & `no_alternate_ip`:** `ph_fleet_utilization_recover.sh` restarted `phsuper` in place on the same burned exit IP while `ph_iproyal_block_rotate.sh` only ran during manual `optimize_checkin` (not on the 15-minute `ph_fleet_fix_tick.sh`). In addition, binding all 20 VMs `1:1` left zero unquarantined `.purl` headroom and previously allowed two blocked slots (`32` and `41`) to swap onto each other's burned IP.
2. **Upvote Refresh Supervisors Down (`slots 9, 27`):** Left only slot `38` refreshing active voters (`2.2/min`), causing median held-voter upvote staleness to drift to `13.1` days (whereas `<24h` freshness through `D-1` lifts voter presence AUC from `0.562` to `0.898`).
3. **Pre-Reveal `api_comments` Spacing Gaps (`30-240m`):** Single-writer stalls on slot `39` left gaps during the `00:05-03:45 PT` pre-reveal window needed for post-midnight launch discovery and order-free early comment signals.
4. **Stale GCS Rotation Telemetry:** `mailbox/from_cursor/iproyal_rotate.log.full` had stopped updating in GCS on Nov 20 despite host rotations continuing through Nov 24.

## 2. Turnkey 15-Minute Hook (`ph_fleet_15m_steady_hook.sh` + `steady_ip_pool.py`)
- **Non-destructive (`AGENTS.md` L152):** Never stops, pauses, or deletes any GCE VM.
- **AGENTS.md Backoff Enforcement (`L28-30`):** Places `cf_wall` slots into stateful exponential cooldown (`10m -> 20m -> 40m -> 80m -> 120m cap`) at `0.5x` worker concurrency (stepping back up to `1.0x` only after `60m` clean traffic) and maintains global IP quarantine leases so two slots can never ping-pong onto a burned `.purl`.
- **In-Place Recovery for Non-Blocked Slots:** Distinguishes `dead` supervisors (`batch=false`, no `cf_wall`) and `stale` hung workers from `cf_wall`, restarting only non-blocked supervisors immediately.
- **15-Minute GCS Ledger Sync:** Uploads current `iproyal_assignments.json`, `iproyal_rotate.log.full`, and `steady_slot_actions_latest.json` to `gs://usersim-bakeoff-347838016394/usersim_sim/mailbox/from_cursor/` every tick.

```bash
# Invoke from fleet-cursor's 15-minute ph_fleet_fix_tick.sh:
PYTHONPATH=/agent/repos/usersim bash /agent/repos/usersim/usersim_core/fleet/ph_fleet_15m_steady_hook.sh
```

## 3. Recommended Information Demand Spec (Inputs & Freshness Targets)
Per `AGENTS.md` L145-156, `fleet-cursor` owns slot assignment, scaling, and VM supervision. The downstream model & calibration pipeline requests the following steady-state data freshness SLAs:
- **Live PH Lineup & Pre-Reveal Comments (`<15m` max gap, `00:00-04:00 PT` critical):**
  - Rolling `15m` `api_detail` + `lineup_0100.json` so post-midnight launches (e.g., `#3 Hiring Right Now` on `2026-11-25`) enter the candidate set before vote reveal (`04:00 PT`).
  - Continuous `15m` `api_comments` (`comments_ts`) with hot-standby failover so `00:05-03:45 PT` gaps stay `<=15m`.
  - Live `sites_0005.json` URL redirect resolution.
- **Active Held-Voter Upvote Refresh (`<=24h` fresh by `00:05 PT` daily):**
  - Daily newest-first `Upvotes` diff down to first held item for 14-day and 30-day active complete people (`~3,655-8,500` people), keeping `D-1` voter activity current.
- **Bounded High-Signal Complete-People Completion (`need_list=1,197`):**
  - Prioritize Top-10 launch backers & commenters from `Apr-Nov 2026` (`whole-person` mode; audit `stacks` `0/0` empty-tab edge case so valid 0-stack users are not blocked from saving).
- **External Anti-Bot Sources Offloaded from the 20 PH IPs:**
  - Pre-launch X/Twitter search, LinkedIn company profiles, and G2/Capterra reviews are pulled via `usersim_core/apify_pull.py` into `gs://usersim-bakeoff-347838016394/usersim_sim/raw/apify_v1/` — the 20 PH IPRoyal IPs do **not** need to scrape X, LinkedIn, or G2.
