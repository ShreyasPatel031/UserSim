# Target dataset spec (ideal measurement vs what we collect)
Owner: orchestrator. Reviewed daily (10:43 UTC trigger). Rule (Shreyas, Nov 3): decide the measurement from what the model needs,
then price it; default to the maximum inside the caps. Every gap has an owner and a date, or a written reason.
Verification: data babysitter (session_01WkCrUQbiTbMDT5gLXh6qjb) scores "current" daily in raw/_babysitter/<day>/scorecard.md.

Legend. Cadence = how often re-read. Resolution = time precision of each event. Coverage = share of the population seen.

## Product Hunt: who votes on launch day (north star 1)
| Question | Ideal measurement | Current (Nov 3) | Gap / owner / date |
|---|---|---|---|
| Vote total per launch over the day | every launch, every 15 min, 00:01–23:59 PT, incl. hidden-period internal score | once a day (01:45 PT on Nov 3); 15-min capture starts Nov 4 00:0x PT | first snapshot files + checker PASS; Data Feeder + PH checker; Nov 4 |
| Exposure (board position) | homepage + daily leaderboard order every 15 min, section/fold, logged-out, exit country, hourly repeat read for shuffle | none | spec filed (1945 + addenda); Data Feeder; Nov 4 |
| Who votes, when (pool, ~35% of votes) | every pool member's new upvotes with first-seen ≤ 1 h on launch day; all ~21k people | once a day, active pool (~4.3k) | hourly likely-voter set + 4-hourly rest, pilot filed (2010); route priced; Data Feeder; Nov 4; then scale to the measured edge (babysitter) |
| Who votes (outside the pool, ~65%) | not exposed by PH (signed-in check Nov 3: no voter list anywhere) | n/a | pool growth is the only lever: add voters seen as commenters/followers to the pool; owner orchestrator; spec by Nov 5 |
| Comments per launch, dated | every new comment per snapshot: username, created_at ISO, is_maker/is_hunter | daily page read | in the 1945 spec; Nov 4 |
| Team's pre-launch activity (A2/A3) | team members' comments and dated upvotes on others' launches, 30 d before | comments exact-time (held); upvotes dated to the upvoted launch (leaky) | upvote first-seen from hourly reads accrues from Nov 4; usable ~Dec 4 |
| Who follows the team, when | follows diff daily for active pool, weekly whole pool, d−1 cut | one diff (Oct 26→Nov 2); daily active + 1/7 pool from Nov 4 05:00 ET | first honest week ~Nov 10 |
| Team audience at launch | maker/hunter/product follower counts at ≤ featured_at + 20 min, hourly after | Wayback backfill 42% (null on boards); live from Nov 4 | low value after today's null; keep as part of the capture |
| Page content at launch | first-snapshot content + raw HTML; re-save on change | pages read ~88 d after launch (backtest) | in spec addendum; Nov 4 |
| Late featuring / un-featuring | first-appearance time per launch, state per snapshot | late_featured counts daily (bundle 7) | in spec addendum; Nov 4 |

## Hacker News: Caught per post at 15 min (north star 2)
| Question | Ideal measurement | Current (Nov 3) | Gap / owner / date |
|---|---|---|---|
| Early votes/comments per post | every post, every minute from posting to 24 h | live hn_minute recorder (ours + Data Feeder's box copy) since Nov 1 | gaps logged; babysitter verifies union daily |
| Historical 15-min state | outcome-independent /newest snapshots dense enough for ≥ 50% of posts | Sep–Oct 2026 ~5%; 2025 Jan–Jun 63% pulled (done ~05:00 UTC Nov 4), Jul–Dec 16% | second polite Wayback worker set from the babysitter's IP; Nov 4 |
| Content at posting | title, domain, Show/Ask text, author's earlier titles | held (BigQuery); author history run in progress | none |
| Front-page exposure | /front and /news order per minute | hn_minute has rank for front page; /new page position? | confirm with HN agent; Nov 4 |
| Second-chance pool | /pool reads with timestamps | live since ~Nov 1 | 2 weeks of labels by ~Nov 15 |
| Dead/flagged | showdead | checked: 0 of 278 false flags dead; closed | none |
