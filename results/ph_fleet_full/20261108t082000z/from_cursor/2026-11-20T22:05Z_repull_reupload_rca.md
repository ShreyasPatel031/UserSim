# Repullupvotes re-upload RCA — orchestrator 21:59Z / 22:01Z

**Ask:** (1) Why are **hundreds** of staged saves since **~20:50Z** old pulls (`run.finished_utc` Nov 5–17, retired slot labels)? (2) **True** fresh upvote-refresh rate since **20:35Z** interval fix? What are refresh slots **actually uploading**?

## (1) Why old pulls re-upload

| Step | What happens |
|------|----------------|
| **Mode** | Slots **9 / 27 / 38** run `repullupvotes` with GO `repullupvotes:fleet-upvote-20261108t082000z-20261120T0834Z`. |
| **Read path** | Overlay `patch_repull_upvotes_staging.py` loads the **existing complete person** from **`raw/_pacetest/shared/{handle}.json`** (Population store), not a new pdeep pull. |
| **Work** | Re-walk Upvotes GraphQL, merge list, write back to **`shared/`** (whole-person gate treats any repull as uploadable). |
| **Bug** | Staging patch set `run.finished_utc = res.get("run", {}).get("finished_utc") or now()` — **`finished_utc` from the original pull was preserved** even though `upvotes_refreshed_at` was today. |
| **Population** | Audits **`run.finished_utc`** for “fresh pull”; **0/361** since 20:35Z count as Nov 20 pulls despite **~4–5/min** fleet status rows. |

**Not causes:** exit-IP light roll, IP rotation, or retired VMs writing now — **VM label on old objects** is from **`run` metadata inside the JSON**, not the current writer (all uploads since **20:35Z** are from **9/27/38**).

**Sample (GCS, 20:50Z+):** `zohrah_shaah` — `finished_utc` **2026-11-17**, `upvotes_refreshed_at` **2026-11-20T21:20:31Z**, `items_added` **0**.

## (2) True fresh refresh rate since 20:35Z

| Metric | Value | Notes |
|--------|-------|-------|
| **Status “complete” rows (9/27/38)** | **~4–5/min** fleet-wide | `reuse_browser_v1`, `rc=0`, `header_pct≈100` — **misleading** for store coverage |
| **Population staged “fresh pull”** | **0** (20:35Z → 22:01Z) | Matches **`finished_utc`** bug |
| **Uploads with new upvote rows (`items_added>0`)** | **Small fraction** of uploads (Population: many **0**-delta replaces) | True coverage gain only when delta **>0** |
| **Browser/GraphQL throughput** | **~2 ppm/slot** post-restart + interval fix | Real **read** work; most merges **replace-in-place** with **no** new votes |

**Interval fix (20:35Z):** faster **person cadence** (~20–40s vs ~180s) → more **re-uploads/hour**, not more **fresh pulls** until **`finished_utc`** is fixed.

## What refresh slots upload

Each cycle uploads a **full person JSON** (complete schema) to `raw/_pacetest/shared/`:

- **Unchanged:** most fields from the **Nov** pull; `run.timing`, original slot ids, etc.
- **Updated today:** `upvotes` list (when PH shows new votes), `upvotes_refreshed_at`, `upvotes.refresh.delta`.
- **Wrong for audits until fix:** `run.finished_utc` (stale).

## Fix rolling (same turn)

| Change | Purpose |
|--------|---------|
| `patch_repull_finished_utc_fixup.py` | Set **`run.finished_utc = now()`**, keep prior in **`finished_utc_prior_pull`**. |
| `ph_fleet_measure.py` | **`complete_ppm`** = **pdeep `pfull` only**; **`upvote_refresh_ppm_15m`** = repull **uploads**; add **`upvote_refresh_fresh_ppm_15m`** (heuristic). |

**Roll:** patch + inplace supervisor restart on **9/27/38** (no hist scale; **LIVE_PRIORITY_HOLD**).

**Expect after roll:** Population sees **Nov 20 `finished_utc`** on new staged rows; store queue progress when **`items_added>0`**. ETA **~15–30 min** after patch live for first auditable fresh pulls.

**Artifacts:** `patch_repull_upvotes_staging.py`, `patch_repull_finished_utc_fixup.py`, Population audits `audit_20261120T2121Z.tsv`.