# Bundle 10: full `people` and `launches` tables (prepared Nov 13 2026; awaits Shreyas's approval)

Asked by the orchestrator 14:39Z Nov 13 (Shreyas's rule: nothing that is pulled may be dropped). Pipeline change: deploy only on
Shreyas's direct word to PH ops, outside 00:05-01:00 PT, with backup + md5 (deploy_b10.sh).

## Why
- `people`: the pipeline's writers (daily.py "people" step, pool_grow.py, voters.py) write only `person` + `first_seen`, so
  everyone added after the one-time build_initial.py has blank joined / headline / about / followers. The population store
  (raw/population/store_v3, lossless since 14:35Z Nov 13) now keeps every field of every pull.
- `launches`: 15 columns; the daily list read also holds commentsCount, createdAt, featuredAt, website, media, reviews (2025
  lists), and hunter / maker details. The feature build reads the JSON files directly, so nothing in the forecast changes.

## What changes (new columns only; every existing column keeps its name and type)
| file | change |
|---|---|
| pipeline/people_full.py (new) | builds one full row per person ALREADY in `people` from store_v3 persons.parquet (+ record_sha256 / record_part from records/); `--records` also writes the verbatim record JSON to a new snapshot table `people_records` (keyed by person; keeps `people` small). Rows are never added: that would change incremental.py's known set and the pool's first_seen. Join: salted id = hash(salt, handle) of handles already in `people`; no handle is taken from the store. |
| pipeline/daily.py | `day_rows` adds 16 columns (`launch_extra`): comments_count, created_at, featured_at, website, media_types, reviews_count, reviews_rating, hunter_id, hunter_created_at, hunter_followers, hunter_headline, hunter_website, hunter_has_twitter, maker_ids, makers_detail (JSON, no usernames / twitter handles / names), extra_json (any other key of the read, verbatim). Not-final counts (comments_count, reviews) are nulled at the 00:05 write like votes. New step `people_full` right after `people`: refreshes only people whose store pull changed (`--changed`). |
| pipeline/warehouse.py | KEYS: `people_records: ["person"]`. |
| pipeline/launches_backfill.py (new) | one-off: adds the new columns to every stored launch from data/days; existing columns are taken from the warehouse as they are (keeps fix_launch_days.py's day corrections). |

People columns: 19 -> 38 (+ people_records table). Launches columns: 15 -> 31.

## Deploy (VM, outside 00:05-01:00 PT)
1. `bash deploy_b10.sh <checkout of claude/ph-ops-agent>` (checks pre-b10 md5s daily.py 27f0578d / warehouse.py c89671dc, backs
   up to ~/w/backup_b10/before.tar, copies 4 files, import + step-order check, prints "deploy ok: b10"). If the deployed daily.py md5
   differs, stop: the patch must be rebased on what is deployed.
2. Dry runs (counts only): `cd ~/w/experiments && python3 -m pipeline.people_full` and `python3 -m pipeline.launches_backfill`.
3. One-off writes: `python3 -m pipeline.people_full --write --records`, then `python3 -m pipeline.launches_backfill --write`.
4. From the next 00:05 PT run the `people_full` step refreshes changed people and new launch rows carry the new columns.

## Verification
- `SELECT count(*), count(joined), count(ph_user_id) FROM people` before / after: row count unchanged, joined / ph_user_id up.
- `SELECT count(*) FROM people WHERE first_seen IS NULL` unchanged (first_seen kept).
- `launches`: count unchanged; `count(featured_at)` > 0; `day` of the fix_launch_days launches unchanged.
- Next daily run: step `people_full` ok in pipeline_runs; forecast step unchanged (features.py does not read these tables).

## Rollback
`tar xf ~/w/backup_b10/before.tar -C ~/w/experiments`. The appended table parts stay (snapshot tables, newest row wins); to undo
their effect, re-write the previous rows (the old columns are unchanged, so readers are unaffected either way).

## Tested (in the PH ops container, local warehouse cache copy, no writes)
- people_full.build on the local cache (21,099 people) + store_v3 persons (79,051) + 1 of 39 record parts: 21,067 matched,
  joined filled 20,671 -> 21,059, keys unique, dtypes unchanged (ph_followers Int64, is_maker boolean); a union_by_name
  view of old + new parts keeps 21,099 rows and every first_seen.
- daily.day_rows on the Nov 12 list (37 launches): 31 columns, existing 15 unchanged, no twitterUsername / username keys in the
  new columns; on a 2025 list reviews_rating is filled. Step order: people -> people_full -> ph_upvotes. launches_backfill dry
  run on the local cache: 7,048 launches, cols 31.
- Not tested: the real VM deploy, writes, the full 39 record parts download (1.3 GB) and the daily `--changed` path on a second day.

## Reader risks
- `SELECT * FROM people` in daily.py personas: card() reads only segments / headline / li_headline / stacks (unchanged types);
  headline now filled from the store for more people, so persona cards gain a PH headline line for them.
- incremental.py / voters.py / pool_timing.py read person / first_seen only: unchanged (no rows added, first_seen kept).
- fix_launch_days.py rewrites `SELECT *` rows: it would carry the new columns along (fine).
- Daily cost: people_full downloads persons.parquet (31 MB) + records (1.3 GB) each run; writes only changed rows.
