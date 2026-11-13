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
| 5 | pipeline/daily.py `s_people` source | read `raw/ph_people_daily/<day>/{upvotes_page1,following_page1,fetch_state_rows}.jsonl`, last delivered Nov 2-3: failed "no delivery" every day Nov 8-13 | default `PEOPLE_SRC=store_v3`: reads the population store (events + tabs, full depth). See "People step from store_v3". `PEOPLE_SRC=delivery` / `fetch` remain |

## People step from store_v3 (orchestrator 15:26Z Nov 13)

The people step now reads `raw/population/store_v3/{events,tabs}.parquet` (`people_from_store` in daily.py). The old page-1 delivery
folders stopped on Nov 2-3. It writes the same tables with the same columns and types; no new tables or columns.

- **events**: store upvotes become `(person, launch_id, date = launch day, kind "upvote", date_quality "launch_day")`, as every other
  upvote in the warehouse (PH shows no upvote time; the store's own `ts_quality` for upvotes is `snapshot` / `bounded`, not an
  event time). Only person x launch pairs not already in `events` are written.
- **follows**: `(person, followee, observed_on = PT day the store first saw the follow, new_since_last = True)`, only pairs not already
  in `follows`. The store keeps every observation; the warehouse keeps one row per new pair.
- **fetch_state**: one row per person and source (`store_v3_upvotes`, `store_v3_follows`) when the store's tab pull is newer than the
  last row written: `last_fetched` = that pull's PT day, `status` 200, `items` = tab count, `complete` = the store's tab flag. New
  source names, so the `upvotes_page1` / `upvotes_scroll` readers (newest_item) are unaffected.
- **people**: new commenters (`/tmp/new_people_<d>.json` from the comments step), `first_seen = d`, as before.
- **Mapping**: the store keys people on `"p_" + sha256(salt + "producthunt:" + lower(username))[:16]` (the same rule as pool_size and
  bundle 10). Every username the warehouse already holds (people, events, comments, follows person and followee) is hashed with the
  salt (read from the bucket, never printed) and matched. Store people and followees with no warehouse username are counted in the
  step output, not written (no new people rows: bundle 10 rule). They stay in the store.
- **Incremental**: dedup against the warehouse on every run, so a second run with the same store writes nothing new.
- **Fails loudly**: unreadable store file, unreadable salt, or empty events/tabs -> `status: failed: ...`.

Dry run (local warehouse copy, store_v3 15:02Z, no writes):

| | rows |
|---|---|
| warehouse people found in store_v3 persons | 21,069 of 21,099 (99.9%) |
| store people with any upvote / follow event | 699,142 (mapped to a warehouse username: 43,584) |
| events (new upvotes) | 113,146 |
| upvotes on launches not in the warehouse launches table (no launch day, not written) | 943,392 |
| follows (new pairs) | 974,535 |
| follows whose followee has no warehouse username (not written) | 1,523,711 |
| fetch_state rows | 44,112 |
| run time / peak memory | 23 s / 3.4 GB |

A 3,000-person sample: 974 of 2,991 store people mapped; 5,571 events, 40,119 follows, 1,964 fetch_state rows; columns and dtypes match
the existing tables.

First deploy run writes about 1.1 M rows (mostly follows); later runs write only what the store added. Peak memory 3.4 GB: check the
pipeline VM's free memory before the first run.

## Deploy (after Shreyas's yes, outside 00:05–01:00 PT)

1. `bash deploy_b11.sh pipeline <checkout>` on usersim-pipeline.
   - It picks `daily.py` (over 27f0578d) or `daily_over_b10.py` (over b10 6e80e47e) and checks imports.
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
- People step from store_v3: full-store dry run against the local warehouse copy (table above); 3,000-person slice.

## Not tested

- Any live request: PH GraphQL cursor paging in the scraper, comment thread pages ≥2, leaderboard `?page=N` (unverified that the site pages this way), reddit `after` paging, GitHub pages, Apple review pages.
- Run time and cost of the uncapped scraper. It sleeps 6.5 s per request, so the run grows with the number of posts.
- A real budget overflow carried across two runs.
- The store_v3 people step on the pipeline VM (memory, gsutil download of ~250 MB events each run) and a second-day run (dedup).
- Readers of the follows rows written with a store first-seen day as `observed_on` (older than the run day for the first backfill).
