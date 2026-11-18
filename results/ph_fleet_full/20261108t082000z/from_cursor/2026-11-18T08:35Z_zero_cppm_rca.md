# 08:35Z — 0 cppm after job split (RCA + fix)

**status.json ~08:32Z:** 0 active, 12 dead, 6 stale, 1 cf_wall, **0 complete_ppm** (upvote slots 9/27/38 counted dead too).

## Sample log — historical pdeep slot **28**

```
LOGFILE=/opt/ph/reuse/run_20261118T0834Z.log  (0 bytes)
supervisor: launch pdeep:fleet-20261108t082000z-r14 reason=same_tok_retry ... every ~40s
```

No `FINGERPRINT` / `paged` — child exits immediately; supervisor relaunches on the **same** token forever.

GCS `GO.feeder-fleet-…-28` = `pdeep:fleet-20261108t082000z-r14` (legacy **experiment `-rN`** token, not `orch-restart-*` / not job-split work).

Same pattern on most historical slots (5→`-r44`, 13→`-r55`, …); only 31/33/34 still hold `orch-restart-*` from the 06:38Z in-place roll. **Job split fixed pdeep_list but left bad GO objects on GCS.**

## Upvote slots 9/27/38

Run log is **healthy** through ~08:09 (`upvotes endCursor chain …` on slot 9). GCS GO is correct `repullupvotes:…0705Z`. **Measure marks them dead** because **complete_ppm counts full complete person saves in 15m**, not upvote-tab refresh on already-complete people — so refresh-only work reads as “0 cppm / dead” even while repull was pulling.

## Other

- Slot **5**: `BLOCK challenge … 403` → **cf_wall** (same-IP back-off; no rotate).

## Fix (same-IP only, LIVE_PRIORITY_HOLD)

1. **Normalize GO** on all historical slots: `ph_fleet_restore_pdeep_go.sh` + in-place phsuper (`orch-restore-*` / fresh upvote GO on 9/27/38); clear `last_token` / `same_tok_retry_at`.
2. **`ph_fleet_roll_patches.sh`:** write **per-slot** `pdeep:fleet-{run}-orch-roll-{ts}-{slot}` — never bare `pdeep:fleet-{run_id}` or legacy `-rN`.
3. Keep **stale_unhang** from overwriting GO (`FLEET_STALE_UNHANG_WRITE_GO=0`).
4. **No** historical scale-up; live capture already **fresh** (~08:16Z posts_ts).