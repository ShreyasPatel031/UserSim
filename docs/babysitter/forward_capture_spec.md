# Forward capture spec: Product Hunt, hourly and daily (babysitter v2, 2026-11-03 ~21:10 UTC)

Status: reviewed by the orchestrator (21:05 UTC: commenters above makers' reach; makers' reach cut to 3 reads); filed to to_grokbot/ 2026-11-03 ~21:10 UTC, runs from the 00:01 PT Nov 4 snapshot.
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
| P3 | Commenters of today's launches (first sight): profile counts, upvotes page 1, activity page 1; added to the pool (1958). Launch-day commenters are the mobilised people and grow the observed pool | once on first sight | route 4 | 500×3 = 1,500 | 3,532 |
| P2-lite | Makers + hunter: profile counts at +4 h and +24 h (the launch read is in P1); followers page 1 diff daily to day 7 | 2 reads + daily | route 4 | 80×2 + 80×7 = 720 | 4,252 |
| P4 | Competitors: for each launch the top 5 Similar Products (raw/ph_alternatives) deduped (~150–200): product header counts, newest followers page 1 (diff), newest reviews page 1 with dates, latest launch votes | launch day, then weekly | route 4 | 200×4 = 800 | 5,052 |
| P5 | Commenters, days 2–7: upvotes page 1 (first-seen) | daily | route 4 | ~3,000 | ~8,050 |
| P6 | Pool likely-voters (~1,761) hourly + rest of active pool (~2,654) 4-hourly: upvotes page 1, first-seen windows (2010) | hourly / 4-hourly | **only on a route the edge test clears** (cheapest JSON route first) | ~42k + 16k | off budget |

Order: P0, P1, P3, P2-lite, P4, P5, P6. At today's 2,500 pages: P0 + P1 in full (P1 with route-4 comments ~2,030), P3 partly
(first ~150 commenters). At 5k: through P4. At ~8k: P5. If the API returns comment authors (P0 test), P1 is ~590 and P0–P3 fit in 2.5k.
Competitor history and full person history (all upvotes, all followers, all reviews) are backfill for the agents, not this feed.

## Files (append-only, one row per snapshot × item, uploaded after every snapshot)
raw/ph_at_launch/<day>/live/: posts_ts, comments_ts, board_ts, people_ts, products_ts, competitors_ts (.jsonl), coverage_ts.jsonl
(per snapshot: snapshot_id, snapshot_ts, tier, pages_planned, fetched_200, failed, 403, 429, empty, timeout, span_s, proxy_MB, usd).
New people from P3 append to raw/ph_people_daily/<day>/pool_additions.jsonl. Heartbeat from_grokbot/ph_live_capture.status.md every
snapshot: last snapshot, tiers run, pages used vs budget, $ today, next snapshot, any 403.

## What the babysitter checks daily (scorecard)
Per tier: rows vs planned, % 200, 403/429 count, first-snapshot lag vs featured_at (+20 min bar), gaps >20 min, fetched_at on
every row, dupes, $ per 1,000 pages, budget used vs ceiling. Per-person completeness goes to the population agent's report.

## Ratchet (Shreyas, 21:20 UTC: "constantly increasing the data we are extracting till the absolute limit")
- Route-4 page budget per PT day starts at 2,500 and ratchets: after each clean PT day (no 403 on a fresh session, coverage ≥95%),
  next day's budget ×1.5 (2.5k → 3.75k → 5.6k → 8.4k → 12.7k → …); per-minute cap one step up on alternate clean days (60 → 75 → 90 → 110 …).
- First block: back off to the last clean level ×0.8, record the edge (pages that day, pages/min, time, block signature) in
  docs/babysitter/limits.md, wait for recovery (probe), resume ratcheting after 2 clean days. No IP or account rotation.
- Every extra page goes to the next unfunded tier (P3 → P2-lite → P4 → P5 → P6 likely-voter hourly reads), then to the population
  agent's history pass.
- The same ratchet applies to the PH API v2 loop (complexity budget per 15 min), X free quota, GitHub. Wayback is not this feed.
- Every row of every feed keeps the PH username (GCS only) for dedupe; salted ids only in the model store.
- coverage_ts / heartbeat add: budget_today, pages_used, tier_reached, clean_day (bool), next_day_budget.
- Babysitter reports each day: budget, pages used, tier reached, errors, next budget.
