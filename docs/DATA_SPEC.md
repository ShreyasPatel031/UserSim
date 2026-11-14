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
| Question | Ideal measurement | Current (Nov 13) | Gap: limit / at it? / cheapest next step / owner / date |
|---|---|---|---|
| Vote total per launch over the day | every launch, every 15 min, 00:01–23:59 PT, incl. hidden-period internal score | 15-min API v2 live feed: Nov 13 21/21 every slot, 1–18 s late; pre-cut :28/:58 snapshots (5 tonight to 02:28 PT) give the hidden rank | API 92% left, not at limit; hidden score not exposed (closed with reason); none |
| Exposure (board position) | homepage + daily leaderboard order every 15 min, logged-out | API ranking order per snapshot (board_ts) + pre-cut ranks; no logged-out page order (route 4 under STOP) | page order closed for now: API order used; reopen only if route 4 gate clears; Data Feeder |
| Who votes, when (pool) | every pool member's new upvotes with first-seen ≤ 1 h on launch day; all pool people | 65,385 complete people (52,919 whole + 12,466 signed-out end); pool tiers likely 1,224/1,570, active 409/2,638, other 8,099/16,732; vote coverage Oct 29–Nov 4 69.3% (inflated), Oct 1–24 48.4%; store +12.1/min (~17k/day) | per-IP Cloudflare limit, near it; 18 of 20 approved IPs used, 1 dead slot → fill 20 IPs; Cursor agent; reply by 14:00Z Nov 13, 20 IPs by 00:00Z Nov 14 |
| Early votes inside the hidden window (new) | tier-1 panel re-read 02:30–03:30 PT nightly (~400–500 early votes/night expected) | panel of 2,000 most active complete people written 09:50Z (raw/_cursor/hidden_window/); no re-read yet | not started; Cursor agent, first night Nov 14 02:30 PT (10:30Z); E5 scores it |
| Complete the incomplete (new) | every saved person finished to PH's end | 11,087 incomplete + 192 merged-incomplete kept; 12,466 at signed-out upvote end queued for signed-in | completion-pass queue from population agent by 18:00Z Nov 13; Cursor runs it in the batch slots |
| Who votes (outside the pool) | not exposed by PH | discovery tiers 53,834 complete of 329,080 queued; pool growth 22,120 (+52 today) | need list 345,460 rows ≈ 20 days at today's rate; have_index/need_list stale since Nov 8 → population agent refresh by 18:00Z Nov 13 |
| Comments per launch, dated | every new comment per snapshot with commenter id and created_at | API: 00:07 PT read with votesCount (first landed 00:15 PT tonight; 00:07 from Nov 14), new comments every 15 min, replies merged; daily-pipeline comments step blocked on proxy (37/37) | API not at limit; Data Feeder confirms 00:07 landing on Nov 14 (PH agent checks at 00:20 PT); pipeline step redundant for comments |
| Historical comment timestamps (new) | 2025 comment created_at per launch day | not started (1 file in comments_2025/) | API budget 92% free; Data Feeder pulls all 365 days, no pilot, no cap (AGENTS.md Nov 13); start now |
| Historical daily lists (new) | every featured launch 2024–2026 with ranks/votes | 2025: 339 of 365 days (manifest 10:46Z); 2024: 1 day | API not at limit; finish 2025 today, then 2024 if PH agent wants it; Data Feeder; 18:00Z Nov 13 |
| Week/month close re-read (new) | full re-read at 23:50 PT each night, done before 00:00 PT | ran 23:59 PT Nov 12, 381 rows; starved the 00:07 slot | late; fix (start earlier/finish by 00:00 PT) in for Nov 13 night; Data Feeder; 08:00Z Nov 14 |
| Team's pre-launch activity | team comments + dated upvotes on others' launches, 30 d before | comments exact-time; upvotes dated to launch, leaky unless the member was pulled before the day (E5 Nov 13) | forward only: pulls before launch day (hidden-window panel helps); E5 shadow; none new |
| Who follows the team, when | daily follow diffs, active pool | full follow lists on complete people; team followers/following counts on the 00:07 read from Nov 13 | follow-list order is not dated (E5); use 00:07 counts; none |
| Team audience at launch | maker/hunter profiles at ≤ featured + 20 min | API teams 44 rows (00:07); maker headers 14 of 28 (box browser, Cloudflare stop) | headers at limit by rule; API counts replace them; Data Feeder keeps best-effort; closed with reason |
| Page content at launch | first-snapshot content + raw HTML | api_detail from ~00:07 PT (productLinks, thumbnail, monthlyRank); sites step 0/20 on the proxy; no HTML | proxy blocked → daily pipeline on a fixed IP; Cursor agent; before 07:00Z Nov 14 |
| Product followers at launch | per launch at first snapshot | not in API (introspection); asked on the 00:07 read | low model value (PH agent); Data Feeder answers by 08:30Z Nov 14 |
| Maker X followers | per maker at launch | X population 5,600 / 8,953 (62.5%); follower counts 115/120 team handles; product X accounts pending | 1,000 reads/day shared, at it; paid top-up inside $30/week is Shreyas's call; Grok Bot; finish ~Nov 16 at free rate |
| X buzz before launch (new) | per launch, X posts/accounts in 48 h ending 00:00 PT, frozen | 00:10 and 02:00 PT counts for Nov 13 only; 00:10 window ends 00:17 PT (not a 00:05 input) | strictly pre-launch count asked; backfill Nov 9–12 scheduled 16:05 PT Nov 13 (00:05Z Nov 14); Grok Bot |
| Daily pipeline (forecast inputs) | all steps on time | forecast step ok (clean model, 00:18 PT); comments/sites/people steps fail on the proxy | Cursor agent, fixed IP for the pipeline VM, before 07:00Z Nov 14 |
| Late featuring / un-featuring | state per snapshot | absent_from_source flagged per snapshot; 21st launch appeared Nov 13 | none |
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


## Collection status, Nov 14 2026 (daily review)

| Feed | Ideal | Have (Nov 14, 10:45 UTC) | Gap and cheapest step | Owner |
|---|---|---|---|---|
| 15-minute launch-day capture (posts, comments, ranks) | every 15 min, all day, every day | none since Nov 13 19:00 UTC; Nov 14 folder empty | site-run snapshot endpoint is built (site/live_board/<day>_ts/); needs the site deployed + a scheduler; Cursor fleet needs a PH API token | Shreyas (hosting, token), Cursor fleet |
| Day-close votes (23:45-23:59 PT) | every day | missed Nov 4, 5, 6, 13 | site 23:50 PT slot once deployed; VM read needs the instance schedule moved to 23:55 PT | Shreyas |
| First comment reads (00:03 and 00:27 PT) | every night | on time on 2 of 11 nights; missed Nov 14 | filed with the Cursor fleet (API only) | Cursor fleet |
| VM hourly recorder (rank, votes, comments) | hourly 00:06-23:00 PT + 03:45 PT | running; 2,025 rows missing from the warehouse for Nov 4-7 (raw intact) | bundle 12a (03:45 read) and bundle 12 (loader fix) | Shreyas's word, PH agent |
| Pipeline comments step | all comments nightly | Nov 14: 21 of 21 pages blocked or unparseable | move to the official API; diagnosis due after 13:10 UTC | PH agent |
| Pipeline sites step / website URL at 00:05 | every launch | 0 of 29 on Nov 14; 2 of 28 usable URLs | resolved URL field at the 00:05 read | Cursor fleet / PH agent |
| People, complete (every tab) | everyone on the need list | 72,000+ complete of ~80,100 saved; about 2-3 per minute on 2-4 of 20 VMs | fleet back to 20; completion queue (10,301 + 297 + 13,338 legacy) | Cursor fleet |
| History day lists | 2023-2026 | 2026 and 2025 complete (365); 2024: 8 files; 2023: 0 | pull 2024 then 2023 (expected about +2 top 3) | Cursor fleet; PH agent fallback on Shreyas's word |
| 2025 comments | all 4,923 launches | 1 file | ranked below the day lists (+0.6 top 3 expected) | Cursor fleet |
| Weekly / monthly close reads | every Sunday and month end | none yet; first due Sun Nov 15 23:45 PT | filed; needs a token on the fleet or the site scheduler | Cursor fleet |
| Downtime audit | every 15 min, alerts within 1 min | every 30 min inside an agent session; standalone script ready | a host for the cron + webhook file | Shreyas, Cursor fleet |
