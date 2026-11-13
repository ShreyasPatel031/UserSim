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

## Not tested

- Any live request: PH GraphQL cursor paging in the scraper, comment thread pages ≥2, leaderboard `?page=N` (unverified that the site pages this way), reddit `after` paging, GitHub pages, Apple review pages.
- Run time and cost of the uncapped scraper. It sleeps 6.5 s per request, so the run grows with the number of posts.
- A real budget overflow carried across two runs.
