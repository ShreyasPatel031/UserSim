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

**Provisional operating point for Nov 4** (until a staged test says otherwise): ≤60 pages/min, one VM, one sticky session, ≤2 browsers;
no burst above 60/min; ≤~2,500 route-4 pages per PT day across all jobs, live capture first; stop the run at the first 403 on a fresh session.
Staged test after the live capture has run 2 h clean: 40 → 60 → 90 pages/min, 30 min per step, stop at >2% 403.

## Log of edge events
- 2026-11-03 19:16 UTC: PH route 4, Cloudflare 403 on all fresh sessions (full rota VM, then the live-capture VM at 19:32). Jobs stopped
  19:52 by Grok Bot/Data Feeder on the orchestrator's decision; one probe every 10 min. Recovery: pending.
- 2026-11-03 20:01 UTC: fresh GCP VM in us-east1 (usersim-babysitter-probe, e2-micro, IP 104.196.53.204): Wayback CDX 3/3 HTTP 200 (0.5–2.7 s), captures 3/3 HTTP 302 to the nearest timestamp (0.2–0.9 s), no timeouts. So the timeouts are per-IP (hn-sim-1, the cloud session's egress), not all of GCP: a second polite worker set on a fresh GCP IP is possible.
- 2026-11-03 ~04:00 UTC: Wayback from hn-sim-1 (GCP) TCP timeouts; moved to the box. Cloud-session egress shows the same signature at 19:52 UTC.
