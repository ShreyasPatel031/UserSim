# Population data: target per-person schema, priority, cost (population data agent, 2026-11-03)
Scope: public Product Hunt and X activity only (what a viewer sees; signed-in only where it shows the same public list deeper).
Raw rows keyed by username live only in gs://usersim-bakeoff-347838016394/usersim_sim/raw/; the store the models read keys on
`person_id = "p_" + sha256(salt + "producthunt:" + lower(ph_username))[:16]`, hex, utf-8, salt = raw/population/_salt stripped of
whitespace, username lowercased with any leading "@" removed. X accounts: same with the literal "x:" and the X username.
Test vectors (with the real salt): "example_user" -> p_97eb5d57c445ef1f; X "example_user" -> p_2a9f6e09425fb3f2.
Reference implementation: tools/population/store.py Ids. Reports: counts only.

## Inventory, Nov 3 (tools/population/inventory.py; pool 20,947)
| Source | People | Items/person med / p90 | Days back med / p90 | Oldest | Dated |
|---|---|---|---|---|---|
| PH upvotes page 1, full pool (Nov 1) | 20,078 with ≥1 | 11 / 20 | 274 / 2,267 (by launch date) | 2013 | 0% exact; 100% launch-day proxy |
| …of which complete (has_more false) | 13,038 (65%) | | | | |
| …truncated (has_more true) | 7,027 (35%) | 20 | 410 | | |
| Store v3g PH upvotes (warehouse, 2026 launches only) | 19,220 | 3 / 20 | 192 / 287 | 2026-01-01 | launch-day proxy |
| Store v3g PH comments (launch-page crawl) | 16,711 | 1 / 4 | 162 / 277 | 2025-04-12 | 100% exact |
| PH daily upvote refresh page 1 (Nov 2 / Nov 3) | 22 / 124 | 11 / 20 | | | first-seen between reads |
| PH following page 1 (Nov 2 + Nov 3 rota pilot) | 3,900 | 8 / 20 | n/a | n/a | none; 66% of lists complete |
| PH followers of makers/hunters (at-launch capture, Nov 3) | 63 targets | 10 / 20 | n/a | n/a | first-seen by diff only |
| PH profile (bio, links, counts, badges) | 20,937 | 1 snapshot | | | 16,794 fetched-dated, 4,143 upper bound |
| X handles (self-linked or matched) | 9,015 (7,681 conf ≥ 0.8) | | | | |
| X profiles (follower counts) | 1,823 | 1 snapshot | | | 29 fetched, 1,794 upper bound |
| X posts in store | 1,719 | 13 / 24 | 151 / 1,672 | 2011 | day |
| X pre-launch posts / launch engagement (makers, hunters) | 192 / 96 | 9.5 / 61 | 39 / 57 | 2026-09-01 | exact |

Size of what is missing (from profile totals): the pool has 2.23 M upvotes in all; we hold ~227 k (10%). 66.5% of people
are complete on page 1 (≤ 20 upvotes); the rest need ~104 k more pages (20 per page) for full history, ~46 k if capped at
500 upvotes/person (676 people have > 500). Profiles: 59% made a product, 39% hunted, 26% have reviews, 18% collections,
23% stacks. Followings total 638 k (~47 k pages). PH shows no upvote cast time anywhere (Data Feeder 1855 reply), and
page-1 order is by vote time while launch dates go back years (truncated people: median 410 days), so a launch date is a
poor stand-in for when a vote was cast except for votes on that day's launches.

Dating rule for upvotes without a cast time: list order is newest-vote-first, so vote k was cast at or after every older
vote's launch; lower bound L(k) = max(launched_at of items k..end), upper bound = fetched_at of the first read that
shows it (or the previous item's upper bound). Forward re-reads tighten the upper bound to the read interval.

## Target schema per person
PH (one row per event; every row has fetched_at, event_ts + ts_quality ∈ {exact, bounded, launch_day, first_seen}, source):
1. upvotes: full list, position, post_id, launched_at, bounds [L, U] as above; re-read page 1 for first-seen.
2. comments + forum posts (Activity tab): text, created_at exact, post/thread id, parent author (reply ties).
3. following (complete, paged) and followers (complete if ≤ 500): first_seen per edge from re-reads.
4. made / hunted launches; reviews (rating, created_at); collections and stacks (product lists).
5. profile snapshot weekly: followers/following/upvotes totals, badges, streak, links (counts history).
X (only for self-linked handles): profile snapshot (counts), posts/replies/reposts with created_at, following list.

## Priority order (value for launch-day turnout; cost per 1,000 pool people, estimates until the pilot measures)
Page cost range: $0.03/1k pages (Nov 1 light mode, 0.66 GB for 20,947 pages) to $0.27/1k (Nov 3 HTML refresh).
| # | Item | Why | Pages / 1k people | $ / 1k people | Status |
|---|---|---|---|---|---|
| 1 | Full PH upvote history (no Sep 1 floor), capped 2,000/person | who they vote for repeatedly (makers, topics, reciprocity), activity rate | ~2,200 (cap 500) – 5,000 | $0.07 – 1.35 | pilot asked (below) |
| 1b | Activity tab: comments + forum posts, exact times | dated activity rhythm, reply ties to makers | ~2,000 (unverified) | $0.06 – 0.54 | in pilot |
| 2 | Forward first-seen reads of page 1 (hourly likely voters, daily rest) | the only cast-time signal; turnout labels | 24 × ~1.8k + daily | ~$20/week cap | asked 2010; blocked by route 4 403 |
| 3 | Complete following lists + weekly diff | who they follow, dated follows | ~2,250 once, ~1,000/week | $0.07 – 0.6 | page 1 held; rota from Nov 4 |
| 4 | Made/hunted, reviews, collections, stacks | taste, maker identity | ~1,400 | $0.04 – 0.37 | after 1 |
| 5 | Profile snapshot weekly | follower/upvote count history | 1,000/week | $0.03 – 0.27 | rota |
| 6 | X profile counts for 9,015 handles | reach | – | twitterapi.io ~$0.2/1k (est.) | blocked (credit used) |
| 7 | X posts last 30 d for active-pool handles | pre-launch mobilisation | ~50 posts/person | ~$7/1k people (est.) | blocked; needs Shreyas |
| 8 | GitHub public events for self-linked handles (725) | dev activity rhythm | free API | $0 | population agent, own VM |
Full pool for 1 + 1b: ~88–146 k pages, ~$3–39, 1–2 days at 60 pages/min; the pilot sets the real number.

## Identity and scope decisions (orchestrator, Nov 3 20:00 UTC)
- Model-facing ids: salted person_id only; v3g's `ph:<username>` ids are never used downstream.
- Other platforms: only handles a person links from their own PH or X profile. Counts in v3g: LinkedIn handles 7,186 people
  (all ph_self_link); LinkedIn profile rows 3,641 people = 655 from raw/li_apify (all 655 match a PH self-linked handle) +
  2,986 `li_search_url_matches_self_link` (identity found by search, treated as inferred). Both LinkedIn profile sets are
  outside PH/X and are excluded from the population store and anything a model reads; nothing deleted. GitHub: 725 people
  self-linked (+8 extra links) → public events via the free API (rule: self-linked only).

## Route budget (babysitter, raw/_babysitter/limits.md)
PH route 4: ≤ 60 pages/min, one session, ≤ ~2,500 pages per PT day shared by all jobs; live capture first. Measured good-page
costs: follows p1 $0.061/1k, upvotes p1 $0.27/1k (268 KB), post/profile ~$0.17/1k; a blocked load still costs ~$0.0024.
At that budget the full pool for items 1 + 1b (~88–146 k pages) is 5–8 weeks unless the daily budget rises; the pilot decides
whether larger page sizes or the JSON query cut that.

## Priority order, revised (orchestrator agreed Nov 3 20:25 UTC)
Evidence: tools/population/turnout_fields.py. Per-day Spearman with "voted for a launch featured that day" (Oct 15–31, ~19.5k
people/day): comments last 7 d 0.20, upvotes last 7 d 0.19, last 30 d 0.16, profile totals 0.02–0.07, comments ever 0.02;
follows of ≥1k-follower accounts 0.21 (read after, leaky). Recency, not depth, drives whether someone turns up.
New order for route-4 pages: (2) forward first-seen reads ≥ (1b) Activity comments > (3) dated following > (1) full upvote
history capped 500 > (4)–(5). Full history is for which launch a person votes for (affinity); that test is next.
GitHub events: run by Grok Bot on its box (raw/population/github/20261103/), no population VM.

## Which-launch test (affinity), Oct 1–25 (tools/population/affinity_fields.py)
6,067 pool person-days with a vote; for each, every featured launch that day is scored. Within person-day AUC / coverage, and
the pairwise conditional-logit coefficient (standardised) with final votes (LATE popularity) in the model:
| Field | AUC | Coverage | Coef beyond popularity |
|---|---|---|---|
| final votes count (LATE, popularity) | 0.82 | 100% | 2.00 |
| follows a team member (following p1 read Nov 2; LATE) | 0.64 | 63% | 0.88 |
| upvoted the team's earlier launch (page-1 history) | 0.62 | 72% | 0.25 |
| commented on the team's earlier launch | 0.60 | 33% | 0.21 |
| commented on this launch before its day | 0.58 | 17% | 2.22 |
| topic share of last-30-d upvotes | 0.55 | 68% | 0.12 |
| a team member upvoted the person's own launch (reciprocity) | 0.51 | 3.5% | 0.54 |
Reading: popularity dominates, but the follow graph and past votes for the same team add on top; topics add little.
For collection: complete + dated following lists (3) and deeper upvote history (1) feed the which-launch side; reciprocity
needs makers' own histories (low coverage now). Follows are read after the vote, so part of 0.88 may be follow-after-vote;
dated follows (rota diffs) settle that.

## Rule: PH API token work (orchestrator, Nov 4 19:37 UTC)
The PH box API key is shared with the live launch-snapshot loop, which has priority. On Nov 4 the comment-time by-id lookup
(126 calls, ~12.6k points; suggested by this agent for F1) drained the key, and the 11:15 and 11:30 PT live snapshots were lost.
From now on the population agent proposes no PH API-token job without the orchestrator first, priced in points against the
live loop's remaining budget. Comment times are not a model input; the 311 unknown full-pull comment times stay unknown.
