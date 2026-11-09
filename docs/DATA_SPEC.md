# Target dataset spec (ideal measurement vs what we collect)
Owner: orchestrator. Reviewed daily (10:43 UTC trigger). Rule (Shreyas, Nov 3): decide the measurement from what the model needs,
then price it; default to the maximum inside the caps (GCP $50/day soft, $100 hard; paid data: people job $200/week ≈ 195 GB (Shreyas, Nov 5 00:15Z), other paid data $30/week).
Every gap has an owner and a date, or a written reason.
Verification: data babysitter (session_01WkCrUQbiTbMDT5gLXh6qjb) scores "current" daily in raw/_babysitter/<day>/scorecard.md.
Dashboard: https://claude.ai/artifact/WV14WeCEQQmV1PB8psDfit (rebuilt by tools/coverage_dashboard.py).

Legend. Cadence = how often re-read. Resolution = time precision of each event. Coverage = share of the population seen.

## Measured limits (Nov 4)
| Route | Limit found | At it? |
|---|---|---|
| PH API v2, per key | 6,250 points / rolling 15 min; flat 100 points per request; first: ≤ 20 | yes on the box key (12% left at 08:15Z); heavy passes gated at ≥ 50% left |
| Residential sticky port, one warm browser | ≥ 75 pages/min per IP clean (edge not reached); cold first page is what Cloudflare blocks | no; cost binds first |
| Same, per session, person pulls | 1 person / 3 min clean over 60 min; 1 person / 1.5 min blocked after ~8 people | yes (half pace on 3 VMs) |
| Paid data cost | ~$1/GB; reused browser 0.4–0.6 MB per full person; HTML tab 0.36 MB | people job inside $6/week (1.3 of 5.5 GB used) |
| Route 4 (port 10001, capture pages) | 403 on cold warm-up Nov 3 21:04Z and Nov 4 07:55Z | blocked; hold to Nov 5 07:25Z |
| Box browser (own IP, $0) | human pace ≥ 20 s/load; second Cloudflare challenge after ~15 pages | used for first snapshot only |

## Status Nov 8 (10:50 UTC) — daily review
- Complete people (strict rule incl. follow-list offset end, FAIL_repeat, class 3): 2,045 (1,963 whole + 82 whole signed-out); 13,877 incomplete. Earlier 2,133/2,161 counts were overstated; 179 of 1,522 merged pace-test people now fail the follow-list rule.
- Last week (Oct 29–Nov 4, 23,349 votes) complete-only coverage: 2.21% all / 3.53% top 3; all tracked 42.7%.
- Pulls: no audited fleet. A Cursor agent (usersim-cloud-agent) runs 4 feeder-strat + 6 feeder-fleet VMs on the ungated reuse.tgz 7bAxaq8n: 203 saves since 16:20Z Nov 7, 81 incomplete; byte stop bypassed on 2; fleet recreates VMs after a 403 (IP rotation). Awaiting Shreyas.
- Follow-list fix full18d (offset re-page, Chao1 closure) built and E5-reviewed; needs a non-blocked path. 2,365 people held for it.
- Pipeline: Nov 8 forecast produced on time (first since Nov 4); Nov 5–7 no pre-launch forecast. Live capture healthy since 21:00Z Nov 7 (official API; comments/people/products/content writers on). Maker header fallback added after the Nov 8 failure.
- X pass 1: capped (25 posts, since Aug 1); 1,867 people labelled partial; Shreyas to decide on completion.

## Status Nov 7 (10:50 UTC) — daily review
- Store unchanged: 2,025 whole + 108 whole except the signed-out upvote cap = 2,133 (PH agent counts 2,197 complete incl. older store_v3); 13,586 incomplete kept. 0 pull VMs; 0 whole/day.
- Last-week vote coverage from whole people: 3.32% (top-3 5.36%); all tracked people 46.1%.
- Compute default SA re-enabled 14:58Z Nov 6, disabled again 20:33Z Nov 6 by another admin (with usersim-cloud-agent, spot-restarter, fetch-ladder-ro); usersim-cloud-agent re-enabled 23:23Z. Result: no pre-launch forecast Nov 5, 6, 7; live capture one snapshot all of Nov 6 and none for Nov 7.
- Late Nov 6 forecast and a Nov 5 backtest (top-3 2/3) exist as raw/daily/<day>/forecast_<day>_late.md, not scored.

## Status Nov 6 (10:50 UTC) — daily review
- Store unchanged since Nov 5 12:08Z: 2,025 whole + 108 whole except the signed-out upvote cap = 2,133; 13,586 incomplete kept for a completion pass. Population merge lists since then: 0 people.
- Person pulls: 0 VMs since ~10:00Z Nov 5 (PH blocked every IP even at K4; relaunches refused by the safety check). Rate today: 0 whole/day.
- Last-week vote coverage from whole people: 3.32% (top-3 launches 5.36%); known pool caps ~46%.
- Compute default SA still disabled: no daily pipeline since Nov 4 (Nov 5 and Nov 6 forecasts, Nov 4–5 scores lost), no at-launch/live capture since Nov 5 02:49Z, HN live stopped since Nov 5 06:27Z, exp-1 down. Needs Shreyas.
- have_index/need_list stale since Nov 5 00:10Z (their "complete" flag predates the whole-person gate: 2,524 > 2,133 whole), so the coverage dashboard was not republished from them.

## Status Nov 5 (10:45 UTC) — daily review
- Whole-person rule in force (AGENTS.md). Store: 1,949 whole + 103 whole except the signed-out upvote cap (from 605 at 03:00Z); 13,586 incomplete kept for a completion pass.
- Person pulls: 5 pace VMs, Camoufox, fixed ports, K8 per IP (measured: K16 blocks in 1.5–39 min, K8 holds full hours at 2.5–6.3 whole/min). Expected 15–20 whole/min. Queue = last-week voters first (full17).
- Last-week vote coverage from whole people: 2.31% (gap ~14,780 votes); known pool caps ~46%, so 80% needs new-voter discovery (signed-in pass).
- Down since ~06:30Z: compute default SA disabled in Shreyas's cleanup → daily pipeline (no Nov 5 forecast/Nov 4 score), live/at-launch capture (stale since 02:45Z), exp-1. Needs Shreyas.

## Product Hunt: who votes on launch day (north star 1)
| Question | Ideal measurement | Current (Nov 4) | Gap / owner / date |
|---|---|---|---|
| Vote total per launch over the day | every launch, every 15 min, 00:01–23:59 PT, incl. hidden-period internal score | every 15 min via API v2 since Nov 3; Nov 4 35/35 per slot, 5–16 s late; votes hidden by PH to ~04:00 PT | hidden-period score not exposed anywhere; closed with reason |
| Exposure (board position) | homepage + daily leaderboard order every 15 min, logged-out | first snapshot only (box browser, 76 rows); 346 later snapshots have no position | route 4 hold to Nov 5 07:25Z; then one warm long-lived session, ~5 req/min; Data Feeder; Nov 5 |
| Who votes, when (pool) | every pool member's new upvotes with first-seen ≤ 1 h on launch day; all ~21.5k people | full all-tab pulls: 149 complete (likely voters 131/1,572); 3 VMs at half pace ≈ 1,200–1,400 people/day; daily first-seen reads not yet hourly | likely voters complete by ~Nov 5; hourly likely-voter upvote reads after that, at the measured per-session pace; Data Feeder + babysitter |
| Who votes (outside the pool) | not exposed by PH | pool growth live: +600 today (pool 21,547) from commenters/followers | keep daily; population agent verifies |
| Comments per launch, dated | every new comment per snapshot with commenter id and created_at | API: Nov 3 final 489/521 = 93.9% incl. replies, 218 commenters; Nov 4 current | replies backfill gated by API budget; Data Feeder |
| Team's pre-launch activity | team comments + dated upvotes on others' launches, 30 d before | comments exact-time backfill to May (budget-gated); upvotes dated to launch, not vote | upvote first-seen accrues from daily reads; usable ~Dec 4 |
| Who follows the team, when | daily follow diffs, active pool | follows rota running; full-pull followers now complete or marked hidden (complete_not_visible) / capped (> 2,000) | first honest week ~Nov 10 |
| Team audience at launch | maker/hunter profiles at ≤ featured + 20 min | Nov 4 FAIL at +20 min; profiles via people VMs instead: 11/50 named makers by 10:30Z; 36 of 86 slots REDACTED by PH | route 4 back Nov 5; until then people-VM priority list; Data Feeder |
| Page content at launch | first-snapshot content + raw HTML | 15/37 post pages (box), no description/media/HTML; Nov 4 at-launch files rebuilt from API + box, every row dated | HTML capture on route 4 from Nov 5; Data Feeder |
| Product followers at launch | per launch at first snapshot | 13/35 (box pages only; not in API) | route 4 Nov 5; low model value (PH agent) |
| Maker X followers | per maker at launch | 5/6 handles today via free X read; X page-1 rollout 1,500/8,892 handles (free quota) | rollout ~Nov 14–15 at the free rate; paid top-up is Shreyas's call |
| Late featuring / un-featuring | state per snapshot | absent_from_source flagged per snapshot (2 on Nov 4) | none |

## Hacker News: Caught per post at 15 min (north star 2)
| Question | Ideal measurement | Current (Nov 4) | Gap / owner / date |
|---|---|---|---|
| Early votes/comments per post | every post, every minute from posting to 24 h | hn_minute recorder, per-minute odds 370+ files since 02:01Z with no gaps | babysitter verifies union daily |
| Historical 15-min state | outcome-independent /newest snapshots for ≥ 50% of posts | 2025 Jan–Jun done (22,482 captures); Jul–Dec 26,582/27,428, ETA ~5 h; Sep 2026 only 4.1% of winners (backtest artifact) | Jul–Dec rerun when H2 lands; HN agent; Nov 4 |
| Signals of a later rise (late risers + re-ups = 38 pts of misses) | first-15-min dynamics + off-HN traction on the URL | off-HN traction live since 08:43Z (GitHub stars every 5 min, Reddit, Lobsters, Bluesky; X skipped, no free API); GitHub star history not recoverable after the fact | first read with 4–5 settled days ~Nov 6–7; backtest pull for Reddit/Lobsters/Bluesky priced first; HN agent + Data Feeder |
| Content at posting | title, domain, text, author history | held; author history tested: +0.4 [−1.0, +1.7], closed | none |
| Second-chance pool | /pool reads | sampled every 5 min; entry median 23 h after posting, so no 15-min value | closed for the posting clock |
| Dead/flagged | showdead | 0 of 278 false flags dead | closed |

### Status Nov 9 (10:50 UTC, orchestrator daily review)
- PH people, complete (whole-person rule): about 15,200 (3,123 at 20:42Z Nov 8 plus about 12,100 merged since, summed from the population agent's to_cursor/audit_*.md). Rate over the last 14 h: about 1,200 complete people/hour (about 25k/day), from 10–11 feeder-fleet VMs running full18d into staging. Exact count waits for the next store rebuild.
- Audit gates holding: 0752Z audit staged 3,266, merged 2,958, held 177 (vm_evasion_or_unknown 188 reasons), failed 131 (follow lists without offset end).
- Gap: last-week vote coverage not re-measured since the merges (0.32% before); population agent to report it at the next rebuild.
- Live capture: official-API loop restored 04:38Z Nov 9 (lost 19:30Z Nov 8–04:38Z Nov 9); Nov 9 PT capturing on time. Maker headers 24/32 (stopped at first 403).
- Gaps unchanged: X timelines partial (cap_1); route 4 off; Cursor agent has not used from_cursor/ or its webhook.
