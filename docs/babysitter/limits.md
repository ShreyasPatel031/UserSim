# Throttling edges (babysitter, living table)

Method: step the rate up in stages (×1.5 per stage, 30 min per stage), log 200 / 429 / 403 / captcha / empty-page / timeout
per stage, find the first stage where errors rise, set the operating point just below it. Once a block is hit: honour
Retry-After, back off, no IP or account rotation. One PH account only. Rows marked *measured* come from logs in the bucket;
*planned* rows have not been stepped yet.

| Source | Route | Safe rate (measured) | Edge rate | What the block looks like | Recovery time | Status |
|---|---|---|---|---|---|---|
| Product Hunt, anonymous pages (/@user, /upvotes, /following, /posts, /leaderboard) | route 4: Camoufox + one DataImpulse sticky residential session, US exit, temp GCP VM | 54–75 pages/min with 4 browsers for ≤15 min bursts: 750 pages 99.5% ok (17:14–17:28 UTC), 131 pages 98.5% ok (10:18); Feeder's noon-ET limit test 98–100% ok up to 80 pages/min; 1 worker at 9/min for 4.4 h: 0.17% 403 | not a rate edge alone: the block came at ~19:16 UTC after ~3,400 pages in the day (makers bulk 2,374 overnight + 131 + 750 + the scale test), with two VMs/sessions open at once and a browser-count step-up | Cloudflare 403 on every *first* navigation of a fresh browser, including the homepage; no cf clearance cookie; each blocked attempt still downloads ~2.4 MB (challenge assets) = $0.0024; one port (10011) got 1/5 through; leaderboard page 403 three times in 20 min | unknown yet; probe every 10 min from 19:52 UTC (`from_grokbot/ph_route4_block.status.md`); will be filled in when the probe clears | **measured, edge hit 2026-11-03** |
| Product Hunt, signed-in box browser (Shreyas's account) | box Chrome, human-paced | not measured (3 profile reads on Nov 3 for the cast-time check, no block) | planned: Grok Bot tests a few human-paced loads before 23:30 PT as the fallback for the first snapshot | — | — | planned; this account may get blocked (Shreyas) |
| Product Hunt API v2 (official) | pipeline key | 1,500 of 6,250 per 15 min reserved for team history; live v1 uses ~38 posts/min | 6,250 complexity per 15 min (documented) | 429 with reset header | window end | known, not stepped |
| Wayback Machine (captures + CDX) | box IP, 4 workers, 1.5 s pause each | 23.6 captures/min aggregate now (Wayback latency ~10 s/capture, slowing since ~15:00 UTC); 53/min at 04:08–04:15; 15k+ captures today with 0×429, 0×403, 0.6% timeouts | not reached from the box; step plan 4 → 6 → 8 workers filed | from GCP VMs (hn-sim-1) and from this cloud session's egress: pure TCP/TLS timeouts (tunnel dies at 10 s, 39 B received), no HTTP status at all, while archive.org and the availability API answer | hn-sim-1 never recovered during Nov 3 (job moved to the box) | measured (box safe; cloud IPs blocked) |
| GitHub REST / GraphQL | box gh login | ≤4,000 req/h self-cap, 22,776 requests in ~7 h, no 429 | 5,000/h authenticated (documented), 60/h unauthenticated per IP | 403 with X-RateLimit-Remaining 0 or 429 + Retry-After (secondary limit) | reset header (≤1 h) | known; this session's egress reports 15,000/h core, 10,000/h GraphQL (unused capacity) |
| Quality News (news.social-protocols.org, volunteer-run) | box, 1 worker, ≥3.4 s | 7.7 pages/min realised (cap 17.6) over 19.7 h | not stepped on purpose (volunteer site); one 502 at 19:38 UTC → 30-min stop | 502 / 5xx | 30 min self-imposed | measured, not to be stepped |
| X free quota (get_users_by_usernames) | agent session | 55 handles/day today | ~100 reads/month | 429 / quota exhausted | monthly reset | known |
| HN Algolia / Firebase | any IP | not measured here | Algolia documents 10,000 req/h | 429 | window | planned if needed |

## PH route 4: where it tipped on 2026-11-03 (orchestrator ask 19:49)
| Window (UTC) | What ran on route 4 | VMs / sticky sessions | Pages | Peak pages/min | Result |
|---|---|---|---|---|---|
| 02:28–06:50 | makers bulk, 1 worker | 1 / 1 | 2,374 | ~9 | 99.7% ok (4×403) |
| 09:45–09:53 | at-launch daily, 3 workers | 1 / 1 | ~220 | ~33 | 100% ok |
| 10:18–10:20 | people upvotes, 4 workers | 1 / 1 | 131 | ~75 | 98.5% ok (1×403) |
| 17:20–17:27 | follows-rota pilot, 4 workers | 1 / 1 | 750 | **130–137 for 5 min** (42, 71, 103, 137, 133, 135, 129 per minute) | 99.5% ok (2×403 in the 71/min minute) |
| 17:27–19:11 | nothing found on route 4 | 0 | 0 | 0 | — |
| 19:11–19:46 | full rota (scale.py, 2 browsers) + diag | 1 / 1 (ports 10007, 10011) | 14 + ~15 | <1 | every first navigation 403 from 19:16 |
| 19:26– | live capture v1 (leaderboard page) | 1 / 1 (second VM) | a few | <1 | 403 at 19:32, 19:48, 19:50 |

Reading: the block did not come from load at the moment it appeared (route 4 was idle 17:27–19:11, and the first blocked pages were the
first of a fresh session). It came ~1 h 50 min after the day's heaviest burst: ~3,500 pages in the day, ending in 750 pages at
~130/min for 5 min from one sticky session. Two VMs/sessions were open only after the block. So the edge is a reputation/volume edge on
the exit IP pool, not a per-minute rate edge we observed directly. Correction: the pilot ran at ~130/min, not the 54/min in the first
scorecard (that number divided by VM wall time including setup).

**Ratchet (Shreyas 21:20 UTC)**: the operating point below is a floor, not a cap. Each clean PT day: route-4 daily budget ×1.5, per-minute cap +1 step on alternate days; first block → last clean ×0.8, record here, resume after 2 clean days.

**Provisional operating point for Nov 4** (until a staged test says otherwise): ≤60 pages/min, one VM, one sticky session, ≤2 browsers;
no burst above 60/min; ≤~2,500 route-4 pages per PT day across all jobs, live capture first; stop the run at the first 403 on a fresh session.
Staged test after the live capture has run 2 h clean: 40 → 60 → 90 pages/min, 30 min per step, stop at >2% 403.

## Log of edge events
- 2026-11-03 20:55 UTC: PH route 4 re-blocked (probe 403, cf-ray a54e46be…) ~25 min after recovery, after only ~240 people-reader pages
  (20:40–20:49, ~25 pages/min, all 200). Recovery window was 20:10–20:51 (200 after challenge each time). Reading: the exit/fingerprint
  reputation had not reset; the second edge is ~15× lower than the first (~3,500 pages). Next: probe-only until clear, live capture first.
  **Revised reading (Grok Bot 21:00 note):** the 20:55 403 was the probe's FIRST navigation on a fresh session right after a VM reset;
  the reader's 240 pages on its established session were all 200. The 19:16 blocks were also first navigations of fresh sessions, and the
  20:18 warm-up on a new port failed. Grok Bot logged 6 VM resets today (~20:05, 20:12, 20:37, 20:50, 20:58, 21:00 UTC), each a fresh
  session. **Hypothesis: Cloudflare blocks fresh sessions; established sessions keep working. The binding constraint may be session
  churn, not volume.**
- 2026-11-03 20:59 UTC: Shreyas overrode the stop ("keep going"). full.py pulls today's 74 makers/hunters on ONE long-lived session
  (port 10001), ~20/min rising to ~30, never above 40; warm-up 403 → wait 15 min, retry once, then stop; no rotation. Deploys now
  self-reload without VM resets.

## Test of the fresh-session hypothesis (run on every route-4 day until settled)
Log every route-4 page with `session_id`, `session_age_s`, `nav_index` (1 = first navigation of that session) and status.
1. One long-lived session; no VM resets; the probe runs inside that session instead of opening a new one.
2. Compare 403 rates: first navigations vs navigations 2+, by session age bucket (<1 min, 1–10, 10–60, >60 min).
3. Volume ramp inside the established session only (20 → 30 → 40 → 60 → 90 pages/min, 30 min per step), so volume and freshness are
   measured separately.
4. Verdict rules: if first-navigation 403s are ≫ later ones and later ones stay ~0% across the ramp, the operating rule becomes
   "keep one warm session alive all day; never reset" and the daily ceiling is set by the ramp alone. If later navigations also fail
   past some page count, that count is the volume edge.
- 2026-11-03 19:16 UTC: PH route 4, Cloudflare 403 on all fresh sessions (full rota VM, then the live-capture VM at 19:32). Jobs stopped
  19:52 by Grok Bot/Data Feeder on the orchestrator's decision; one probe every 10 min. Recovery: pending.
- 2026-11-03 20:01 UTC: fresh GCP VM in us-east1 (usersim-babysitter-probe, e2-micro, IP 104.196.53.204): Wayback CDX 3/3 HTTP 200 (0.5–2.7 s), captures 3/3 HTTP 302 to the nearest timestamp (0.2–0.9 s), no timeouts. So the timeouts are per-IP (hn-sim-1, the cloud session's egress), not all of GCP: a second polite worker set on a fresh GCP IP is possible.
- 2026-11-03 ~04:00 UTC: Wayback from hn-sim-1 (GCP) TCP timeouts; moved to the box. Cloud-session egress shows the same signature at 19:52 UTC.

## PH person pulls from a VM (Data Feeder results, Nov 3; babysitter recipe check Nov 4)
- **Recipe that works** (from_grokbot/20261104T0125_HOWTO_ph_vm_residential_proxy.md): Camoufox humanize + geoip through one DataImpulse
  sticky port, signed out; first load is a 403 challenge that clears in ~15–42 s (wait for `ApolloSSRDataTransport`, not for the challenge
  text to vanish); then pages and same-origin `/frontend/graphql` calls return 200. Babysitter check Nov 4 01:56 UTC: cleared in 14.9 s,
  /@user, activity, upvotes, followers, following all 200 with page data (200–530 KB per page).
- **Per-VM limit (Data Feeder, Nov 3):** anonymous /@user/upvotes, one sticky port, 1–2 browsers: **no 403/429 at any steady pace up to
  80 pages/min per IP.** The only blocks were each browser's cold first page before Cloudflare clearance. Warm in-page fetch ~31 KB
  (~$0.03 per 1,000). **The edge is cold starts, not rate:** keep sessions warm; never restart a session to "retry".
- Browsers per VM: Data Feeder's capacity test on feeder-phpeople-1 (port 10002, 02:05–~02:50 UTC Nov 4) sets the number; operating
  point from it, not re-measured. Babysitter's own 10002 test was stopped at 02:16 UTC after the warm-up (port belongs to feeder-phpeople-1).
- **Ports:** 10001 = daily at-launch capture; 10002–10004 = feeder-phpeople-1/2/3 (Shreyas approved Nov 3). Any other port needs sign-off.
  Two VMs on one sticky port share one exit IP and corrupt both tests. Nobody moves a blocked job to another port.
- Exit network check: port 10500 exited from a hosting AS (Ashburn) on Nov 3 while 10001/10002 exited residential/business ISPs;
  every job should log its exit IP's AS before use.
- 2026-11-04 02:24–02:40 UTC, babysitter port 10005 (own port, Shreyas via Data Feeder): cold warm-up blocked twice (CF challenge not
  cleared in 74 s and, after a 10-min back-off, 76 s). Exit 51.146.214.2, AS6079 RCN (residential cable), Ashburn VA, so not a hosting
  exit. Both runs used fingerprint_preset=True; the clean 10002 run at 01:56 UTC (14.9 s) did not, the 10002 warm-up at 02:14 UTC with the
  preset cleared in 18.7 s. 10005 parked by Data Feeder ("slow Cloudflare on its exit IP"); babysitter assigned 10006, the last port,
  to be run with Data Feeder's recipe (no preset). 10006 not run yet (blocked by this session's permission check, 02:45 UTC).
- **Browsers per VM (Data Feeder capacity test, feeder-phpeople-1, e2-medium 2 vCPU / 4 GB, port 10002, 2026-11-04 02:05–03:00 UTC):**
  limit is RAM, not Product Hunt: 0 HTTP 403/429 at every level. Each Camoufox browser with 3–5 tabs uses ~1.6–1.8 GB.
  1 browser: 3 tabs 21.7 req/min, **5 tabs 30.0 req/min (best)**, 8 tabs 30.3, 12 tabs 36.4 (RAM 26 MB free, load 21). 2 browsers ran
  RAM to 369 MB free; one "challenge not cleared in 60 s" line with no 403 (44/44 were 200), likely a slow render under memory pressure.
  Operating point on e2-medium: 1 browser × 5 tabs ≈ 30 req/min per VM. Next (orchestrator, 03:35 UTC): resize phpeople-1/2/3 to
  e2-standard-4 (16 GB) one at a time, ramp 2→4→6 browsers per fixed port, capped at 60 pages/min per IP until the babysitter's
  port 10006 rate-edge result (in-page fetch, 80→240/min, one browser) sets the per-IP ceiling.
- **Per-IP rate edge, port 10006 (babysitter script, run by Data Feeder, 2026-11-04 03:52–04:25 UTC):** exit 88.223.44.25 (AS7459 Grande
  Communications, residential, Dallas); Camoufox per Data Feeder's recipe (no preset), cold warm-up cleared in 19.0 s; one browser,
  sequential in-page fetch of profile tabs (/@u, activity, upvotes, followers, following) for likely-tier people.

  | target/min | achieved/min | fetches | 200 | blocked | median s | MB |
  |---|---|---|---|---|---|---|
  | 80 | 72.8 | 582 | 582 | 0 | 0.73 | 208.7 |
  | 120 | 66.2 | 530 | 530 | 0 | 0.83 | 186.3 |
  | 160 | 75.2 | 602 | 602 | 0 | 0.75 | 209.9 |

  1,714 fetches in 24 min, 1,709 × 200, 5 × 404 (no such page), **0 × 403/429/challenge**. One sequential browser tops out at ~66–75
  fetches/min (latency-bound), so **the per-IP edge is above 75/min and was not reached.** Next lever: parallel fetches inside the one
  warm page (Promise.all of 2–4), same port, same stop rule.
- **Cost is the binding constraint, not Cloudflare:** a full tab HTML fetch is ~0.36 MB (not the 31 KB of a page-1 fragment), so ~$0.35 per
  1,000 at $1/GB: at 75/min ≈ $1.6/h ≈ $38/day per IP, against the $30/week paid-data cap. Before scaling: fetch the site's GraphQL JSON
  (raw/_babysitter/scale_test/ops/ops.json) instead of tab HTML, measure bytes per item, then set the daily page budget from $ not from rate.
- First run (20261104T0334Z_df10006) invalid: the babysitter's script called the Playwright page from worker threads, so 639 fetches all
  errored locally (0 PH loads, 0 MB). Data Feeder caught it and reran.
- **Reused-browser JSON method, feeder-phpeople-2, port 10003 (2026-11-04 05:35–05:57 UTC):** cold open failed once (05:38), second
  open cleared (05:41); 8 people completed in ~14 min, then a block on person 9 (05:56:46) → stopped_on_block. Cost 0.92 MB avg /
  0.72 MB median per person vs 11.3 MB with a fresh browser per person (~12× cheaper). Items vs header (8 people): upvotes, followers,
  following, hunted, reviews 100%; stacks 50% (11/22, method gap). **Mid-session block after ~8 people / ~14 min**, so established
  sessions are not block-free on this port: the edge may be requests per session. Next: half pace, log requests-per-session at block.
- **Test 2a, reused browser at half pace, feeder-phpeople-2, port 10003 (2026-11-04 06:58–08:02 UTC):** one Cloudflare clear (07:01),
  then **20/20 people, 0 blocks, 307 requests in one session over ~60 min**, 0.56 MB per person. Completeness vs header: upvotes 155/155,
  following 68/68, hunted 4/4, stacks 4/4 (stacks fix holds) = 100%; followers 154/196 = 78.6% and collections 2/3 = 66.7% (paging gaps).
  Compared with the full-pace run (block after ~8 people / ~14 min), **the mid-session edge on this port is rate-related**, between
  ~1 person per 1.5 min (blocked) and ~1 person per 3 min (clean for 60 min). **Operating point per sticky port: ≤1 person / 3 min
  (~5 requests/min), one long-lived browser** until a faster step is measured.
- **Released VMs at half pace (2026-11-04 09:40–11:11 UTC), per-session ceiling:** VM-1 (10002) one session, 28 people, 537 requests,
  87.7 min, 58.5 MB, then **stopped_on_block 11:07:03Z** (mid-session). VM-3 (10004) one session, 28 people, 507 requests, 84.4 min,
  ended by stop_flag 11:04, then a **cold restart failed Cloudflare 11:10:43Z**. VM-2 (10003) 29+ people, no block at 11:24Z.
  ~~Reading: a fixed per-session ceiling of ~500 requests / ~85 min.~~ **Corrected 12:40 UTC: the mid-session block is not a fixed
  count; it is a distribution that differs by port:**

  | Port (VM) | Session | People | Requests | Req/person | Result |
  |---|---|---|---|---|---|
  | 10003 (VM-2), test 1, full pace | 05:41–05:56 | 8 | n/a | n/a | block after ~14 min |
  | 10002 (VM-1), half pace | 09:40–11:07 | 29 | 494 | 17.0 | block at 87 min |
  | 10003 (VM-2), half pace | 09:39– (still open 12:23) | 36+ | 1,786+ | 49.6 | clean ≥2.7 h |
  | 10004 (VM-3), half pace | 09:41–11:04 | 28 | ~507 | ~18 | ended by Data Feeder's stop_flag, no block; cold reopen 11:10 failed |

  Person mix does not explain it: VM-2 makes ~3× more requests per person (5 heavy upvoters with >200 upvotes) and has run 3.6× more
  requests than VM-1 without a block. The likely difference is the exit IP behind each sticky port (10002 also stopped on a block at
  03:45 UTC). Exit IPs are not logged in the status rows; every session should log its exit IP and AS at open so this can be tested.
  A cold open right after a long session failed (VM-3, 11:10). First 20 per VM: 0 blocks; MB 0.59 / 2.12 / 0.67;
  upvotes capped at ~197–199 for heavy upvoters (paging stops ~10 pages), stacks 73–100%, followers 89–99%.
- **Upvotes list cap (signed out), confirmed 2026-11-04:** a profile's upvotes stop at ~195–199 items however far paging goes. VM-2 made
  ~330–340 GraphQL calls on two heavy upvoters (19–20 min, 11.7 / 12.8 MB) and got 195/2,526 and 197/3,142; other capped people
  stopped at 197–199; the box browser pull stopped at 197/3,142. Stop upvote paging at ~200 (or at the first page that adds nothing)
  and mark upvotes_capped; further calls only spend bytes. Signed-in visibility past 200 not tested.
- 2026-11-04 14:02–14:04 UTC, VM-2 (10003): one person ran 2,015 s / 51.3 MB with rc 1 (the ≤20 min / ≤15 MB per-person cap from
  13:30 did not stop it), then the cold browser reopen failed (14:03:29) → stopped_on_block. Second time today a cold reopen right after a
  long session failed (VM-3 11:10). At 14:25 UTC only VM-3 (10004) is pulling; VM-1 (10002) off for the day.
- 2026-11-04 15:44 UTC, VM-3 (10004): **stopped_on_block mid-session after 46 people / 914 requests / 151 min** (session opened ~13:13).
  All three ports have now blocked mid-session at least once: 10002 at 494 requests / 87 min, 10004 at 914 / 151 min, 10003 at 8 people
  at full pace (and 1,786+ requests clean at half pace). Sessions last a few hundred to ~2,000 requests before a block, varying by exit IP.

## Lab run 2026-11-04 19:28–19:47 UTC (babysitter-lab-1, e2-standard-4, port 10006, exit AS5650 Verizon, signed out)
Script: tools/babysitter_cf_lab.py. Raw: raw/_babysitter/lab/{live,live2}.out. VM deleted after the run.

| Step | Result |
|---|---|
| P1 cold open, persistent profile | 403 challenge, cleared in 15.5 s |
| P3 bytes | HTML upvotes tab 480–492 KB; GraphQL upvotes page 17.4–18.0 KB (~27× less) |
| P2 close + reopen same profile | challenged again, cleared in 15.3 s: **persistent profile does not keep clearance** |
| P4 one page, 1 / 2 / 4 / 8 parallel GraphQL (3 min each) | 180/180 (60/min), 360/360 (120/min), 720/720 (240/min), **1,416/1,416 (472/min)**; 0 blocks; 10.5 KB/request; load ≤0.3 on 4 vCPU |
| P5 fingerprint_preset=True, new process, same IP | cleared, but 34.9 s (vs ~15 s) |
| P6 2 browsers at once (separate processes) | **both failed to clear** (70 s, 403) → stop rule, no retry |

Reading: the per-IP request rate is not the edge (≥472/min for 3 min, edge not reached; CPU idle). What failed was **fresh browser
opens**: the 6th and 7th opens on this IP in ~18 min (two at once, right after the preset open) did not clear. Confounded: "too many
opens per IP" vs "two simultaneous opens" can't be separated from this run. Long-run session limits from the people VMs still apply
(blocks after ~500–2,000 requests per session, varying by IP).

### Recommended configuration (most data per $ and per block, best uptime)
1. **One warm browser per sticky IP, opened once.** Never reopen to retry; never add a second browser on the same IP.
2. **Throughput through in-page parallel GraphQL** (persisted queries), not more browsers or tabs: concurrency 4 (240/min) as the
   working point; c8 (472/min) proven only for 3 min.
3. **GraphQL only, no HTML tabs:** ~10.5 KB/request → ~1 GB per 100k requests (~$1 at DataImpulse $1/GB). Stop upvotes at the ~200 cap.
4. **Small VM is enough:** CPU/RAM are not binding at 1 browser (load 0.3 at 472/min); e2-small/medium per IP.
5. **Scale by IP (more sticky ports), not by browsers per VM.** Needs the orchestrator's OK (new ports/IPs rule).
6. Persistent profiles give nothing (clearance not kept). fingerprint_preset clears but is slower; no benefit shown; optional.
7. Uptime: stop at the first block; cool-down before a reopen on the same IP is still unmeasured.
