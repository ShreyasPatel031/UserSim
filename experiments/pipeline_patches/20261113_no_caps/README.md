# Bundle 11: no caps, no silent drops (prepared 2026-11-13, NOT deployed)

The orchestrator asked at 15:13Z Nov 13, under the no-caps / no-dropped-fields rule in AGENTS.md.
Deploying it needs Shreyas's direct word. `deploy_b11.sh` refuses to run 00:05–01:00 PT, checks md5s, backs up first and only copies files.
It works with or without bundle 10: `daily_over_b10.py` is the same patch applied on top of b10.

## Changes

| # | where | was | now |
|---|---|---|---|
| 1 | scrapers_deploy/daily.py (bucket; scraper VM) | PH `posts(first:N=20)` newest only; `comments(first:10)`; HN `hits[:20]`; GitHub `per_page 5`; reddit `content[:4000]`, first RSS page (25); Apple search `limit 3`, review page 1 | every post of the last 24 h by cursor; every comment by cursor; every HN page (`hitsPerPage 1000`, all `nbPages`); GitHub `per_page 100`, all pages; reddit `limit 100` + `after` paging, full text; Apple `limit 200`, review pages 1–10. The User-Agent no longer carries a personal address (`SCR_UA` overrides) |
| 2 | pipeline/daily.py `s_people` | `PERSON_CAP=8000` truncated the people list (fetch mode) | no truncation. `PERSON_BUDGET` (same default) is a budget guard only: overflow goes to `raw/requests/pipeline/people_{upvotes,follows}/pending.txt`, and the next run reads those queues first |
| 2 | pipeline/daily.py `s_comments` | thread page 1 only (50 threads) | pages 2.. while `has_next` (up to 200); `launch_state.complete` recorded |
| 2 | page-1 upvotes / following | the delivery files are page 1; people with more were flagged and then dropped | flagged people go to the durable scroll-deeper queue (below). Paging those lists is the population fleet's full pull |
| 3 | `/tmp/deeper_<d>.json` | written to /tmp; nothing read it | `raw/requests/pipeline/scroll_deeper/pending.txt` (written to a temp object, then moved); fetch mode reads it first |
| 3 | `s_ranks` | unlinked 31 day files, then re-pulled | re-pulls into a temp folder, verifies each file (JSON list, non-empty unless the old one was empty, no shrink > 10%), then `os.replace`; a failed day keeps the old file and the step says `partial` |
| 4 | ph_predict/vm_leaderboard.py | `/all` page 1 only; regex with a 6,000-character window per Post | every `?page=N` until no new post; JSON decode of each Post object (regex kept as fallback); temp file + move; an `.incomplete` marker when a page failed |
| 4 | new commenters | counted; pulled only if the people step ran | every new commenter also goes to `raw/requests/pipeline/new_commenters/pending.txt`; `queue_unpulled_commenters.py --write` queues the backlog once |
| 5 | pipeline/daily.py `s_people` source + pipeline/warehouse.py KEYS | read `raw/ph_people_daily/<day>/{upvotes_page1,following_page1,fetch_state_rows}.jsonl`, last delivered Nov 2-3: failed "no delivery" every day Nov 8-13 | default `PEOPLE_SRC=store_v3`: reads the population store (events + tabs, full depth). See "People step from store_v3". `PEOPLE_SRC=delivery` / `fetch` remain |

## People step from store_v3 (orchestrator 15:26Z, unmatched tables 15:4xZ Nov 13)

The people step now reads `raw/population/store_v3/{events,tabs}.parquet` (`people_from_store` in daily.py). The old page-1 delivery
folders stopped on Nov 2-3. Nothing in the store's upvotes or follows is dropped: every distinct (person, target) pair lands either in
the existing table (unchanged columns) or in a new unmatched table keyed on the store's own salted ids.

| table | what | columns |
|---|---|---|
| events (existing) | upvotes of a person the warehouse knows by handle, on a launch in `launches` | person, launch_id, date = launch day, kind "upvote", date_quality "launch_day" (the warehouse convention for every upvote) |
| **events_unmatched** (new, snapshot) | every other store upvote | person_id (salted), target_id, kind, date (PT day of the store's ts_lo, else ts_hi), date_quality (the store's ts_quality: snapshot / bounded / ...), reason = person_no_handle or launch_not_in_warehouse |
| follows (existing) | both sides have a warehouse handle | person, followee, observed_on = PT day the store first saw it, new_since_last = True |
| **follows_unmatched** (new, snapshot) | every other store follow | person_id (salted), followee_id (salted), first_seen (PT day), reason = person_no_handle or followee_no_handle |
| fetch_state (existing) | one row per person and source (`store_v3_upvotes`, `store_v3_follows`) when the store's tab pull is newer than the last row | person, source, last_fetched, status 200, items, complete |
| people (existing) | new commenters, first_seen = d, as before | person, first_seen |

- **warehouse.py**: `KEYS` gains `events_unmatched: [person_id, target_id, kind]` and `follows_unmatched: [person_id, followee_id]`
  (`warehouse.py` over the current file, `warehouse_over_b10.py` over bundle 10's).
- **Mapping**: the store keys people on `"p_" + sha256(salt + "producthunt:" + lower(username))[:16]` (pool_size, bundle 10). Every
  username the warehouse already holds is hashed with the salt (read from the bucket, never printed) and matched. No handle is read
  from the store; the unmatched tables hold salted ids only (the test asserts the id format).
- **Incremental**: a pair already in its table is not written again (both matched and unmatched tables).
- **Check**: per kind, distinct store pairs must equal the pairs present in the matched table plus the unmatched table after this run;
  otherwise the step fails and writes nothing. Unreadable store, salt, or empty events/tabs also fail the step.

Dry run (local warehouse copy, store_v3 15:02Z, no writes; `test_people_store.py`):

| kind | store pairs | in matched table (already / written now) | in unmatched table (written now) | unmatched by reason |
|---|---|---|---|---|
| upvote | 2,291,122 | 305,187 (192,041 / 113,146) | 1,985,935 | person_no_handle 1,093,781; launch_not_in_warehouse 892,154 |
| follows | 11,240,665 | 1,099,141 (124,606 / 974,535) | 10,141,524 | person_no_handle 8,618,011; followee_no_handle 1,523,513 |

Check: 305,187 + 1,985,935 = 2,291,122 and 1,099,141 + 10,141,524 = 11,240,665 (both pass). Warehouse people found in store_v3
persons: 21,069 of 21,099. fetch_state rows 44,112. Run time 219 s, peak memory 7.2 GB (the first run writes about 13.3 M rows,
mostly follows_unmatched; later runs write only what the store added). Check the pipeline VM's memory before the first run.
A 3,000-person slice also balances (upvote 104,430 = 12,061 + 92,369; follows 349,082 = 44,460 + 304,622).

## Deploy (after Shreyas's yes, outside 00:05–01:00 PT)

1. `bash deploy_b11.sh pipeline <checkout>` on usersim-pipeline.
   - It picks `daily.py` + `warehouse.py` (over 27f0578d / c89671dc) or `daily_over_b10.py` + `warehouse_over_b10.py` (over b10 6e80e47e / d5a50870) and checks imports and KEYS.
2. `bash deploy_b11.sh scraper <checkout>`.
   - It replaces the bucket's scrapers_deploy/daily.py (expected 2f661bb4) with 2a808470.
3. `bash deploy_b11.sh leaderboard <checkout>` on the VM that runs vm_leaderboard.py (expected e9f4ef72).
4. Once: `python -m pipeline.queue_unpulled_commenters --write` (counts only).
5. Rollback:
   - pipeline and leaderboard: `tar xf ~/w/backup_b11/before_<part>.tar -C ~/w/experiments`;
   - scraper: `gsutil cp ~/w/backup_b11/scrapers_daily.py gs://.../scrapers_deploy/daily.py`.

## Tested (no requests, no writes)

- `s_ranks` on a fake collect_ph with 31 days: a failed day and a shrinking day keep their old files, and the step returns `partial`. The other days are replaced, and no temp folder is left behind.
- Queue write in dry mode: dedup works.
- Leaderboard parser on synthetic HTML: a Post whose dailyRank sits more than 6,000 characters in is found by the new parser and missed by the old one.
- `daily_over_b10.py` is the b11 diff applied cleanly to b10's daily.py.
- All files parse.
- People step from store_v3: full-store dry run against the local warehouse copy with the per-kind check (table above); 3,000-person slice; unmatched tables carry salted ids only.

## Not tested

- Any live request: PH GraphQL cursor paging in the scraper, comment thread pages ≥2, leaderboard `?page=N` (unverified that the site pages this way), reddit `after` paging, GitHub pages, Apple review pages.
- Run time and cost of the uncapped scraper. It sleeps 6.5 s per request, so the run grows with the number of posts.
- A real budget overflow carried across two runs.
- The store_v3 people step on the pipeline VM (memory, gsutil download of ~250 MB events each run) and a second-day run (incremental dedup against tables already written; tested only as set logic, not against written parts).
- Readers of the follows rows written with a store first-seen day as `observed_on` (older than the run day for the first backfill).
