# Orchestrator 14:31Z — LIVE_PRIORITY_HOLD cleared + build `1vXYiANmKbePdwCkCCbrwA==`

## LIVE_PRIORITY_HOLD

**Cleared by orchestrator 14:31Z.** Live feeds within limits (posts_ts/comments_ts at 14:21Z; check-in `live_feeds_ok=yes`). Fleet will treat live capture as first priority but may use all historical slots again (no orchestrator-imposed scale-up block).

**Live primary:** slot **39** (`FLEET_LIVE_SLOTS`, `ph_fleet_live_capture.sh`). If a monitored live feed goes critical-stale, repoint capacity to slot 39 / daily feeders first (repo: `ph_fleet_live_priority.sh`, `ph_fleet_ensure_live_slot.sh`).

## Legacy `-rN` GO writer (still open ask)

**Writer:** `scripts/vm/ph_fleet_full_experiment.sh` → `nudge_go()` / `write_go()` with `pdeep:fleet-*-rN`.

**Invokers:** tmux **`ph-fleet-keeper`** (`keeper --loop`) and each **`ph_fleet_optimize_checkin.sh`** keeper pass.

**Fix:** `FLEET_KEEPER_NUDGE_GO=0` (in-place `ph_fleet_inplace_restart_slots.sh`), `FLEET_KEEPER_BLOCK_LEGACY_GO=1`, keeper loop **restarted 12:35Z**. Details: `from_cursor/2026-11-18T13:34Z_go_writer_fix.md`.

---

## Staging build `1vXYiANmKbePdwCkCCbrwA==` (Population held_gate)

**Artifact:** `gs://…/usersim_sim/raw/_pacetest/_code/bsit_full15.tgz` (base64 md5 `1vXYiANmKbePdwCkCCbrwA==`).

**Source of held save:** `feeder-pace32-5` at 2026-11-18T14:00:19Z (`audit_20261118T1422Z.tsv` — `build_not_audited`).

**Fleet production build (unchanged):** `full18f_candidate.tgz` md5 **`uYYdW17hoPBJjpMGoR7lKw==`** on all `feeder-fleet-20261108t082000z-*` workers.

### What changed vs `uYYdW17hoPBJjpMGoR7lKw==` (full18f)

`bsit_full15` is **older** than full18f, not a forward release. Compared to full18f (Nov 10 capcheck/E5 package):

| Area | full18f (`uYYd…`) | `1vXYi…` (bsit_full15) |
|------|-------------------|-------------------------|
| `paging_v2.py` | full18b–f follow **offset re-page** (MAX_PASSES, Chao1, `server_end_offset`, repage_* ends) | **No** re-page block; smaller file (~7.9k vs ~16.8k lines) — pre–full18b paging |
| `ph_batch.py` | Repage state in GCS (`_repage_state/`), `op_seen` logging, signed-out upvote merge at **full header** | **Removed** re-page persistence and `op_seen`; older merge behavior |
| `pdeep.py` | `whole()` requires follow lists to close at **`server_end_offset`** with depth/Chao1 gates; `repage_exhausted` → review queue | **Removed** follow offset/Chao1 gates; all not-whole → `requeue` only |

**Recommendation:** Do **not** merge staging saves from `1vXYi…` as an upgrade path; re-pull those people on **full18f** after audit. Fleet did not roll this package to the historical fleet.

### Proof of full-only on **fleet** (full18f + overlays)

Saves upload to `raw/_pacetest/shared` only when the person is whole:

1. **Strategy:** `PH_REQUIRE_FULL_SAVE=1`, `PH_MIN_HEADER_PCT=98`, `PH_MIN_TAB_PCT=95`, `PDEEP_MODE=full` (`fleet_iproyal.env` / `fleet_optimize.env`).

2. **Runtime overlay** `patch_require_full_save.py` (rolled via `supervisor_strat.sh`): before `gsutil cp out/{h}.json` → staging, `_full_enough_for_save()` rejects partial tabs, truncated budget, or header &lt; threshold; logs `incomplete_skip_upload` and **does not upload** the person JSON.

3. **Collector** `pdeep.py` `whole()` (full18f): builds `not_whole` reasons; on failure writes `.rq` to requeue/review and **no** complete staging path.

4. **Population gate:** audit applies the same whole-person rule (held_gate on unknown build is correct for `1vXYi…`).

**Operational evidence:** supervisor `status_*.jsonl` events include `pkg_md5=uYYdW17hoPBJjpMGoR7lKw==` on fleet slots; measure `complete_ppm` counts only complete windows; incomplete pulls are rerun-only per `ph_fleet_measure.py` metric note.