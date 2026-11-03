# Forward capture spec: Product Hunt, hourly and daily (babysitter DRAFT v1, 2026-11-03 ~21:00 UTC)

Status: draft for the orchestrator's review; not filed to Data Feeder yet.
Sources: orchestrator 20:55 UTC field list; to_grokbot 1945 live-capture spec + addenda A–N; 1958 pool growth; 2010 hourly pool
upvotes; extractor code (experiments/ph_predict/vm_scroll.py, vmfetch.py, vm_profile_tabs.py, parse_prof.py, build_profile.py;
vm_profile_all.py from origin/claude/eager-pasteur-jffjnl 8fff2c75); competitor-audience spec (claude/ph-ops-agent 3f882fe6).
Usernames stay in GCS. Every row carries fetched_at (UTC, actual) and snapshot_ts (UTC, planned) and the route used.

## Rule for the budget
Two routes, two budgets:
- **API route (PH API v2, pipeline key, no browser):** not limited by Cloudflare. Carries every field it can.
- **Route 4 (Camoufox + one DataImpulse sticky session, anonymous):** measured edge on Nov 3 (see limits.md). Daily page budget
  starts at **2,500 pages per PT day** and is raised only by the daily-ceiling test (2.5k → 5k → 10k across days, 60 pages/min,
  log first 403 and recovery per step). Tiers below are spent top-down; when the day's budget runs out, lower tiers wait.
- One process owns all route-4 fetches (one VM, one sticky session, ≤2 browsers, ≤60 pages/min); stop at the first 403 on a fresh
  session; never rotate IP or account.

## Tiers (pages per PT day, ~40 launches, ~80 makers/hunters, ~500 commenters, top-5 competitors each)

| Tier | What | Cadence | Route | Pages/day | Cumulative route-4 |
|---|---|---|---|---|---|
| P0 | Launch series: votesCount, commentsCount, dailyRank, weeklyRank, reviewsCount, featuredAt, launch list (incl. late-featured: first_seen time) | every 15 min day 1; hourly days 2–7; daily to day 30 | API | ~3,840 calls | 0 |
| P0 | Comments via API if PH API v2 returns comment id, createdAt (ISO) and a user id/username that is not [REDACTED]: Data Feeder to test on 3 launches tonight and say yes/no | every 15 min day 1 | API | ~3,840 calls | 0 |
| P1 | Board order: /leaderboard/daily/<day>/all + homepage; section, position, fold, votes shown real/hidden (addenda H, K, L, M) | every 15 min | route 4 | 192 | 192 |
| P1 | First snapshot per launch (≤ featured_at + 20 min): post page (content, media, topics, links, makers/hunter unredacted, first maker comment, raw JSON gz) + product page | once | route 4 | 80 | 272 |
| P1 | Makers + hunter at launch (≤ featured_at + 20 min): profile counts (followers, following, points, made, hunted, reviews, badges), followers page 1, activity page 1, upvotes page 1 | once | route 4 | 320 | 592 |
| P1 | Comments with username + ISO created_at + is_maker/is_hunter + parent_id, from the post page — **only if the API test above says no** | hourly day 1 (15-min for hours 0–4) | route 4 | 40×(16+20) = 1,440 | 2,032 |
| P2 | Makers + hunter: profile counts | hourly day 1 | route 4 | 80×23 = 1,840 | 3,872 |
| P2 | Makers + hunter: followers page 1 diff (new followers, first_seen) | every 4 h day 1, then daily to day 7 | route 4 | 80×(5+6) = 880 | 4,752 |
| P3 | Commenters of today's launches (first sight): profile counts, upvotes page 1, activity page 1; added to the pool (1958) | once on first sight | route 4 | 500×3 = 1,500 | 6,252 |
| P4 | Competitors: for each launch the top 5 Similar Products (raw/ph_alternatives) deduped (~150–200): product header counts, newest followers page 1 (diff), newest reviews page 1 with dates, latest launch votes | launch day, then weekly | route 4 | 200×4 = 800 | 7,052 |
| P5 | Commenters, days 2–7: upvotes page 1 (first-seen) | daily | route 4 | ~3,000 | ~10,000 |
| P6 | Pool likely-voters (~1,761) hourly + rest of active pool (~2,654) 4-hourly: upvotes page 1, first-seen windows (2010) | hourly / 4-hourly | **only on a route the edge test clears** (cheapest JSON route first) | ~42k + 16k | off budget |

At today's 2,500 pages: P0 + P1 run in full (P1 with route-4 comments is ~2,030). P2 starts when the daily-ceiling test clears 5k;
P3–P4 at ~7k; P5 at ~10k. If the API returns comment authors (P0 test), P1 shrinks to ~590 and P2 + P3 fit at 2.5k–5k.
Competitor history and full person history (all upvotes, all followers, all reviews) are backfill for the agents, not this feed.

## Files (append-only, one row per snapshot × item, uploaded after every snapshot)
raw/ph_at_launch/<day>/live/: posts_ts, comments_ts, board_ts, people_ts, products_ts, competitors_ts (.jsonl), coverage_ts.jsonl
(per snapshot: snapshot_id, snapshot_ts, tier, pages_planned, fetched_200, failed, 403, 429, empty, timeout, span_s, proxy_MB, usd).
New people from P3 append to raw/ph_people_daily/<day>/pool_additions.jsonl. Heartbeat from_grokbot/ph_live_capture.status.md every
snapshot: last snapshot, tiers run, pages used vs budget, $ today, next snapshot, any 403.

## What the babysitter checks daily (scorecard)
Per tier: rows vs planned, % 200, 403/429 count, first-snapshot lag vs featured_at (+20 min bar), gaps >20 min, fetched_at on
every row, dupes, $ per 1,000 pages, budget used vs ceiling. Per-person completeness goes to the population agent's report.
