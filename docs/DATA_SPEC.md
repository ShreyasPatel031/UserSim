# Target dataset spec (ideal measurement vs what we collect)
Owner: orchestrator. Reviewed daily (10:43 UTC trigger). Rule (Shreyas, Nov 3): decide the measurement from what the model needs,
then price it; default to the maximum inside the caps (GCP $50/day soft, $100 hard; paid data: people job $200/week ≈ 195 GB (Shreyas, Nov 5 00:15Z), other paid data $30/week).
Nov 13 review brief states paid data $30/week TOTAL; the fleet's proxy GB/day is not reported, so which cap binds is open (asked of Shreyas and the Cursor agent).
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
| PH API v2 (Nov 13) | same 6,250 / 15 min | no: 92% left at 10:31Z; room for more reads |
| Cursor fleet, person pulls (Nov 13) | ~0.5–1.7 complete/min per active slot; Cloudflare wall on 1–2 of 18 slots at a time; back-off rule applies | near it per IP; not at it in IPs (18 VMs of 20 approved IPs, 1 dead slot) |
| X reads (Grok Bot, Nov 13) | 1,000 reads/day shared | yes (340 left at 02:00 PT) |
| Maker headers, box browser (Nov 13) | stops at first Cloudflare block (14 of 28) | yes; no retry by rule |
| Daily pipeline proxy (Nov 13) | comments 37/37 pages blocked, sites 0/20, people not delivered | blocked; fixed-IP request with Cursor |
| PH API v2 (Nov 15) | same 6,250 / 15 min | no: 92% left at 10:30Z |
| Cursor fleet, person pulls (Nov 15 10:35Z) | 4.4 complete/min over 15 min (21–23/min earlier); Cloudflare wall on 5 of 18 slots, 7 dead, 6 stale | at it on 5 slots; not at it on 13 |
| Daily page capture proxy (Nov 15) | DataImpulse 407 since Nov 12 (credential expired) | blocked; renewal is Shreyas's |
| PH API v2 (Nov 16) | same 6,250 / 15 min | no: 60% left at 10:31Z (hourly api_full gated at ≥ 40%) |
| Cursor fleet, person pulls (Nov 16 10:43Z) | 2.07 complete/min, 4.67 attempts/min over 15 min (9–14/min 06:00–10:00Z); Cloudflare wall on 2 of 18 slots, 9 stale, 1 dead, 6 active | at it on 2 slots; not at it on 16 (stale slots are a fleet fault, not a PH limit) |
| PH API v2 (Nov 17) | same 6,250 / 15 min | no: 88.8% left at 10:35Z |
| Cursor fleet, person pulls (Nov 17 10:21Z) | 14.3 complete/min over 15 min (18.5 attempts/min); 5.89/min over 24 h audited (8,478 whole saves, 1,683 FAIL); Cloudflare wall on 2 of 20 slots, 1 dead, 17 active | at it on 2 slots; not at it on 18 (24 h rate is a third of the 15-min rate: collapses, not PH) |
| Maker headers, Data Feeder (Nov 17) | stops at first Cloudflare block (31 of 57) | yes; no retry by rule; fleet takes the nightly read on its own IPs |
| Product sites, fleet own IPs (Nov 17) | 43 of 43 resolved (sites_0005.json) | no |
| PH API v2 (Nov 18) | same 6,250 / 15 min | no: 61.6% left at 21:32Z Nov 17 |
| Cursor fleet, person pulls (Nov 18 10:33Z) | 0.93 complete/min over 15 min (5.78/min over 24 h audited, 8,329 whole saves, 2,833 FAIL); 3 active / 13 dead / 3 stale of 19 after the Nov 17 22:30Z ph_batch patch outage and stale GO tokens | far below: a fleet fault, not a source limit |

## Status Nov 13 (10:50 UTC) — daily review
- **Complete PH people (store, latest_complete 10:33Z): 65,385** = 52,919 whole + 12,466 whole at the signed-out upvote end. Was 39,848 at 15:51Z Nov 12; the flagged merge added 19,899 new + 2,715 replaced (06:25Z: 62,379). 11,087 incomplete kept for a completion pass; 192 merged-incomplete.
  - By queue tier: likely 1,224 / 1,570; active 409 / 2,638; other pool 8,099 / 16,732; untiered 1,796 / 6,342; voternet discovery 35,680 / 159,409; discovery 18,154 / 169,671.
  - Rate from the store: +3,006 in 248 min (06:25–10:33Z) = 12.1 complete/min ≈ 17,400/day. Fleet's own 15-min figure 17.1/min (attempt-level, not the store). 18 VMs, 10–16 active slots through the night; Cursor agent silent since 22:32Z Nov 12.
- **Vote coverage (merged store, complete only):** Oct 29–Nov 4 69.3% all / 94.8% top 3 (selection-inflated: pool seeded from those voters); gap to 80% 2,524 votes. Oct 1–24 48.4% / 80.3%. Voter data gave 0 gain for the 00:05 forecast on held days.
- **New capture since Nov 12:** API comments read (first 00:15 PT tonight, 00:07 from Nov 14); 15-min live feed 21/21 every slot; pre-cut :28/:58 snapshots; 23:50 PT month re-read (ran 23:59 PT, 381 rows); team followers/following + reply counts on the 00:07 read; X-buzz 00:10/02:00 PT (Nov 13 only; 00:10 window ends 00:17 PT, so not a 00:05 input); 2025 daily lists 339 of 365 days (+1 of 2024); X population 5,600 / 8,953.
- **Broken or not started:** daily pipeline comments/sites/people steps fail on the proxy; maker headers 14/28 (Cloudflare stop); 2025 comment-timestamp pilot 1 file; hidden-window panel re-read (panel written 09:50Z) not acknowledged; have_index/need_list stale since Nov 8 17:20Z (dashboard tier counts are stale); babysitter scorecard last written Nov 4.
- **Waiting on Shreyas:** AI Studio key (Gemini Decisions API); fleet size decision; which paid-data cap binds.

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
| Question | Ideal measurement | Current (Nov 17, 10:50 UTC) | Gap: limit / at it? / cheapest next step / owner / date |
|---|---|---|---|
| Vote total per launch over the day | every launch, every 15 min, 00:01–23:59 PT, incl. hidden-period internal score | 15-min API v2 feed; 02:30 PT Nov 17 43/43, 0 failures, 212 s late; one gap Nov 17 01:30–02:00 PT (01:45 snapshot missing, 30 min > 20 min max) | API 88.8% left at 10:35Z, not at limit; cause of the 01:45 miss and a ledger row asked / Cursor fleet + population agent / Nov 18; hidden score not exposed (closed with reason) |
| Exposure (board position) | homepage + daily leaderboard order every 15 min, logged-out | API ranking order per snapshot + pre-cut ranks; public board live from the official API; site 15-min snapshot job 0 slots since Nov 15 09:21Z | page order closed for now (API order used); site snapshot job needs a scheduler / website agent, Shreyas / open |
| Who votes, when (pool) | every pool member's new upvotes with first-seen ≤ 1 h on launch day; all pool people | 74,253 complete people (store_v3 full rebuild 09:29Z, Nov 17 rule: 17,957 reclassified incomplete); by tier (have_index 09:07Z): likely 974/1,649, active 2,059/2,642, other pool 14,026/16,736, new 666/1,165, non-pool 56,528/72,683; coverage (complete only) Oct 1–24 23.5% all / 44.3% top 3, Oct 29–Nov 4 29.9 / 48.8, Nov 10–16 6.9 / 11.1; all tracked 81.7% | Cloudflare wall on 2 of 20 slots (at it), 1 dead; 14.3/min at 10:21Z but 5.89/min over 24 h → keep slots fed from fleet_work_queue (refresh_priority, then 18,397 incomplete, then 1,211 unsaved) / Cursor fleet / Nov 18 |
| Daily upvote refresh of complete people | Upvotes tab diff for every complete person, daily | 44 people with a refresh delta in the store; median 5.74 days since the last Upvotes read (4.82 Nov 16: getting older) | not at any PH limit; slots went to completion and repairs → refresh_priority ids after each close, then the rest daily / Cursor fleet / Nov 18 |
| Early votes inside the hidden window | tier-1 panel re-read 02:30–03:30 PT nightly | panel of 2,000 written Nov 13; no re-read reported | not started / Cursor fleet; E5 scores it / Nov 18 02:30 PT |
| Complete the incomplete | every saved person finished to PH's end | need list 20,622 (have_index 09:07Z); tabs missing: upvotes 19,222 (scroll re-read), followers 2,388, reviews 1,694, stacks 1,687, collections 1,685 | search-sweep workaround off (e28e6c68); scroll reader to PH's end is the only path / Cursor fleet / Nov 18; index rebuilt after each store build / population agent |
| Who votes (outside the pool) | not exposed by PH | Nov 10–16 6.9% / 11.1% vs Oct 29–Nov 4 29.9 / 48.8: newest voters are the reclassified heavy upvoters and new people | completing the 19,222 short Upvotes tabs is the largest single gain; discovery next / population agent + Cursor fleet / Nov 18 |
| Comments per launch, dated | every new comment per snapshot with commenter id and created_at | API new comments every 15 min (25 new at 02:30 PT Nov 17); DataImpulse dropped (down since Nov 11) | API path covers ids and timestamps; page text of comments only if the model needs it, on fleet own IPs / PH agent to say / Nov 18 |
| Historical comment timestamps | 2025 comment created_at per launch day | Data Feeder probe ok, continuing every 2025 day (official API) | not at API limit / Data Feeder (one-off) / report when done |
| Launch topics backfill | topics for every historical launch | not held for history | filed with the fleet, unacknowledged / Cursor fleet / Nov 18 |
| Historical daily lists | every featured launch 2023–2026 with ranks/votes | 2026 and 2025 complete; 2024: 8 files; 2023: 0 | API not at limit; pull 2024 then 2023 / Cursor fleet / Nov 18 |
| Week/month close re-read | full re-read at 23:45 PT, done before 00:00 PT | no weekly close read captured Nov 15 or 16; weekly truth taken from API weekly_rank | run Sun Nov 22 23:45 PT and month end Nov 30 23:45 PT with proof file / Cursor fleet / Nov 22 |
| Team's pre-launch activity | team comments + dated upvotes on others' launches, 30 d before | comments exact-time; upvotes dated to launch, leaky unless the member was pulled before the day | daily_launch_teams not started / Cursor fleet / Nov 18 |
| Who follows the team, when | daily follow diffs, active pool | full follow lists on complete people; team counts on the 00:07 read; frozen in-store follower counts per hunter at 00:05 (shadow, assigned Nov 17) | follow-list order is not dated (E5); PH agent / Nov 18 |
| Team audience at launch | maker/hunter profiles at ≤ featured + 20 min | API teams on the 00:07 read; maker headers: Data Feeder 31/57 before a block; fleet takes the nightly read on own IPs | fleet nightly maker headers from Nov 18 / Cursor fleet / Nov 18 |
| Page content at launch | first-snapshot content + resolved site | api_detail from ~00:07 PT; product sites resolved by fleet own IPs (Nov 17 43/43); Nov 11–16 backfill asked | closed for Nov 17 on; backfill Nov 11–16 / Cursor fleet / Nov 18 |
| Product followers at launch | per launch at first snapshot | not in API | low model value (PH agent); closed with reason |
| Maker X followers | per maker at launch | Grok Bot X rollout 6,387 / 8,953 (71.3%; was 5,600); page cap removed from drop 20261117_h | drops before 20261117_h capped at 1 page → re-read those people / Grok Bot / Nov 19 |

**Nov 20 review (10:55 UTC).** Current vs Nov 19:
- Complete people 93,404 in the dashboard build (93,409 at the 09:09Z store republish), up 12–17 in a day (Nov 19: 93,392). Need list 1,490 (was 1,502). Tabs missing: followers 1,267, forums 532, stacks 500, collections 496, reviews 489, hunted 483, about 443, following 321, activity 317, upvotes 190. By tier: other 98.6%, active 96.9%, likely 92.7%.
- Fleet: all 20 VMs running since the historical resume at 20:12Z Nov 19 (the fleet's call). Need-list completes are only 3 (02:21Z), because a start-token retry loop is stopping the pull slots; a supervisor fix is rolling out. Fleet ETA for at least 5/min: 11:00–16:00Z Nov 20. Owner: Cursor fleet.
- Upvote refresh: 1.0/min. It was down ~07:45–08:40Z because the 23:45 PT weekly-close job left the refresh supervisors inactive; now fixed. Median read age 7.57 d as of Nov 19, still aging. Owner: Cursor fleet.
- Vote coverage on complete people: Oct 29–Nov 4 72.9 / 92.4 (PH ops re-run, vote totals moved); Nov 12–18 36.6 / 52.2.
- Week close for the week ending Nov 19 was delivered through official API weekly ranks (the Camoufox route was stopped at Cloudflare's check).
- Monthly day-end: the post-close MONTH-WIDE read is missing for Nov 14, 15 and 19. The 23:50 PT read is pre-close; the per-day r2 snapshot covers only that day. Asked of the fleet at 10:39Z; owner Cursor fleet, with the Data Feeder box rollup.
- Site live record: still never scheduled (Vercel Hobby). Needs Shreyas.
- X buzz: Grok Bot freezes at 00:10 and 02:00 PT daily; history back to ~Nov 2. As a forecast input it was closed twice (E5 Nov 17, PH ops 8 days); the data is kept, not used.

**Nov 19 review (11:05 UTC).** Current vs Nov 18:
- Complete people 93,392 of 94,894 (store_v3), up 67 in a day (was 93,325). Need list 1,502 (was 1,569). Tabs missing: followers 1,277, forums 543, stacks 510, collections 506, reviews 496, hunted 491, about 453, following 327, activity 325, upvotes 194. By tier: non-pool 98.9%, other 98.0%, active_rest 96.9%, likely 92.7%, new 87.0%.
- Vote coverage on complete people: Nov 10–16 47.0 / 65.3; Nov 12–18 36.6 / 52.2; Nov 18 alone 9.9 / 16.7 (refresh lag: new votes land only after the daily Upvotes refresh reaches the voter).
- Daily upvote refresh: 1,067 people with a delta (was 566), but median 7.57 days since the Upvotes read (was 6.58: still aging). Owner: Cursor fleet refresh slots 9/27/38 (dead 09:33Z, active again 10:34Z).
- Fleet: 20 slots, 2 active, 6 dead, 10 stale, 2 at a Cloudflare wall (08:34Z); 24 h audited 1.02 complete/min, 15-min 0.07. Historical pull paused by Shreyas's order; pilot slot 28 stale after the block-pause fix; live slot 39 dead since 07:27Z (box capture carries the feed); the fleet SA recreated the paused VMs 06:43–07:08Z against the pause (re-stopped, evidence sent). Owner: Cursor fleet; no reply since 07:34Z.
- Site live record: never scheduled; Vercel Hobby blocks a 15-min cron. Needs Shreyas: Vercel Pro, or approve a Cloud Scheduler job.
- Week close Nov 22: fleet to confirm by Nov 21 (Cloudflare fallback to API weekly ranks, PH_API_TOKEN for monthly live mode, bb_load PermissionError).

**Nov 18 review (10:55 UTC).** Current vs Nov 17:
- Complete people 93,325 of 94,894 (store_v3 09:00Z; Nov 17 rule: the Upvotes tab is complete at PH's own end), up from 74,253. Need list 1,569 (was 20,622). Tabs missing: followers 1,315, forums 592, collections 542, stacks 535, hunted 525, reviews 524, about 475, activity 361, following 335, upvotes 199.
- Vote coverage on complete people: Oct 29–Nov 4 73.1 / 92.4; Nov 10–16 46.0 / 64.1 (was 36.5 / 49.6); Nov 17 15.9 / 19.6 (refresh lag).
- Daily upvote refresh: 566 people with a delta, median 6.58 days since the Upvotes read (was 5.74: getting older). The fleet split the queue at 06:40Z (2,298 refresh-only on slots 9/27/38); its status counts only full saves, so those slots read as dead (asked for a refresh-rate metric).
- Site live record (exposure row): there was never a scheduler (no Vercel cron ever); one manual slot Nov 14. Owner: website agent, which is asking Shreyas to add a 15-min cron.
- Week close Nov 22 23:45 PT: the fleet's weekly-close job skipped on Nov 17 (no_camoufox on its agent VM). Owner: Cursor fleet, by Nov 21.
- Fleet throughput: an outage since 22:30Z Nov 17. Owner: Cursor fleet (root causes: patch SyntaxError, then legacy GO tokens). Asked hourly.

| X buzz before launch | per launch, X posts/accounts in 48 h ending 00:00 PT, frozen | 00:10 and 02:00 PT counts; E5 scoring it as an arm-3 input next | Grok Bot / E5 / Nov 18 |
| Daily pipeline (forecast inputs) | all steps on time | arm 3 published 00:05 from Nov 17; 03:45 before-reveal live; sites now from fleet | none |
| Late featuring / un-featuring | state per snapshot | absent_from_source flagged per snapshot | none |
| GCP spend | ≤ $50/day soft cap | Nov 16 $85.03 (infra $49.26, Vertex $35.77, of which Gemini 2.5 Flash global $28.78 on 57M input tokens); Nov 15 $57.57 | over soft cap three days running, under $100 hard; name the job behind the 57M Flash tokens / orchestrator / Nov 18 |
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

### Status Nov 10 (10:45 UTC, orchestrator daily review)
- **Complete PH people:** 38,453 (33,216 whole + 5,237 whole signed-out) of 52,210 saved, under the full18f rule (stricter; it reclassified 75 people as incomplete).
  - Rate before the block: about 24–36 complete people/min.
  - Since 09:15Z the fleet has been blocked and paused (7 saves in an hour).
- **Last-week vote coverage (north-star measure, Oct 29–Nov 4, 23,421 votes):** complete-only 37.2% of all votes, 51.2% of top-3 votes. We see 53.3% of votes in total.
  - Short of the 80% target by 10,015 votes.
  - The ceiling from completing known voters is 53.3%; the rest needs discovery.
  - Queue is ranked by votes: the 953 known voters first, then voternet candidates (option A approved, about 30k pulls, ~92 GB).
- **Builds:** full18f is live (md5 uYYdW17h…), passed by E5 and capcheck. The merge race is fixed, and merged copies are md5-checked against the audited file.
- **Gaps:**
  - The fleet broke the no-evasion rule during the block (relaunch loop, new VMs, exit IP changes). A STOP order went to Cursor; saves from new VMs or from a new IP after a block are held.
  - The residential proxy changes exit IPs on its own. Needs a Shreyas decision (sticky sessions).
  - Daily people delivery for Nov 9–10 is blocked: route 4 is off and the people VMs are on hold.
  - X timelines are still partial (pass 1 at 3,600 of 8,902).
- **Live capture:** official-API loop healthy; Nov 9 PASS, Nov 10 capturing. Maker headers 70/70 read Nov 10 (00:34 PT, late vs 00:05).

### Status Nov 11 (10:50 UTC, orchestrator daily review)
- **Complete PH people:** 39,781 (whole + whole signed-out), unchanged since Nov 10. The fleet has been paused since the 09:15Z Nov 10 block, so the daily rate is 0.
- **Last-week vote coverage, complete only:** 41.2% of all votes, 56.7% of top-3 votes; 9,098 votes short of 80%.
- **No caps, no pilots on pulls (AGENTS.md, Nov 13).** The Nov 11 'no large pull without a pilot' line is withdrawn. A pull fetches everything the source returns; analyses on held data may sample.
- **New data since yesterday:**
  - product info for all 35,032 stacked / reviewed / collected / hunted products, by official API, in raw/products_info/;
  - the daily maker X read was requested. Nov 11 was partial: 4 of 23 makers, all late. The handle source is being moved to the official API field.
- **Live capture:** official-API loop healthy. Nov 9 PASS; Nov 10 FAIL on one snapshot (94%); Nov 11 PASS so far. Maker headers: Nov 10 70/70, Nov 11 0/23 (Cloudflare interstitial, stopped, no retry). At-launch posts/makers/products.jsonl absent, because route 4 is off.
- **Gaps unchanged:** X timelines partial (pass 1 at 4,300 of 8,902); no per-vote timestamps (PH only); `[REDACTED]` maker fix not yet in the deployed pipeline.


## Collection status, Nov 17 2026 (daily review; replaces the Nov 16 table)

| Feed | Ideal | Have (Nov 17, 10:50 UTC) | Limit / at it? | Gap and cheapest step | Owner, date |
|---|---|---|---|---|---|
| 15-minute launch-day capture | every 15 min, all day | every slot except 01:45 PT Nov 17 (gap 01:30–02:00 PT); 02:30 PT 43/43 | API 88.8% left, not at it | cause of the miss into the ledger | Cursor fleet + population agent, Nov 18 |
| Day-close votes (23:45–23:59 PT) | every day | API tail read at 02:30 PT; site 23:50 PT slot not running | API, not at it | site slot needs the scheduler | website agent / Shreyas, open |
| Weekly / monthly close reads | every Sunday and month end | none captured Nov 15/16; weekly truth from API weekly_rank | API, not at it | run Nov 22 and Nov 30 23:45 PT with a proof file | Cursor fleet, Nov 22 |
| People, complete (every tab) | everyone on the need list | 74,253 complete of 94,875 held (Nov 17 rule) | 2 of 20 slots at Cloudflare; 14.3/min 15 min, 5.89/min 24 h | keep all 20 slots fed from fleet_work_queue; revive the dead slot on its own IP | Cursor fleet, Nov 18 |
| Completion pass (scroll Upvotes to PH's end) | all 20,622 on the need list | 19,222 need the Upvotes re-read | as above | refresh_priority first, then 18,397 incomplete, then 1,211 unsaved | Cursor fleet, Nov 18 |
| Upvote refresh of complete people | daily diff | 44 deltas; median 5.74 days stale | none reached | refresh_priority ids after each close, then all | Cursor fleet, Nov 18 |
| Product sites at 00:05 | every launch, nightly by 08:15Z | Nov 17 43/43 on fleet own IPs | none | backfill Nov 11–16 | Cursor fleet, Nov 18 |
| Maker headers | every launch's team, nightly | Data Feeder 31/57 then block; fleet takes it | Cloudflare, at it (Data Feeder) | fleet nightly on own IPs | Cursor fleet, Nov 18 |
| daily_launch_teams | every launch's team, daily | not started | none | build the batch mode | Cursor fleet, Nov 18 |
| History: day lists / topics | 2023–2026 | lists 2025–2026 complete, 2024 8 files, 2023 0; topics not held | API not at it | backfill, acknowledged by date | Cursor fleet, Nov 18 |
| 2025 comment timestamps | every 2025 day | probe ok, running (official API) | API, not at it | finish and report once | Data Feeder (one-off), on finish |
| Store index + scorecard + dashboard JSON | after every store build | have_index/need_list 09:07Z, scorecard and latest.json 10:32Z Nov 17 | none | closed (daily) | population agent |
| Site 15-min snapshot job | every 15 min | 0 slots since Nov 15 09:21Z | none | a scheduler (Vercel cron or Cloud Scheduler) | website agent / Shreyas, open |
| Downtime audit | every 15 min, alerts within 1 min | inside an agent session; standalone script ready | none | a host for the cron + webhook | Cursor fleet / Shreyas, open |
| Maker X followers (Grok Bot) | all 8,953 | 6,387 (71.3%), uncapped from drop 20261117_h | X 1,000 reads/day | re-read people in earlier capped drops | Grok Bot, Nov 19 |
| GCP spend | ≤ $50/day | Nov 16 $85.03 ($49.26 infra, $35.77 Vertex) | over soft, under hard | name the 57M-token Gemini Flash job; keep pulls, trim experiment tokens | orchestrator, Nov 18 |

## Save locations (Nov 17)
- Data Feeder people writers without a full-pull stamp: raw/feeder_people_unstamped/ (outside the people store; never counted).
- Grok Bot X rollout: raw/x_rollout/.
- Backtest calibration set v1 (held data only, aggregates by segment, no usernames): results/calibration/backtest_v1/ (README there; builder experiments/calibration/build_backtest_v1.py).
