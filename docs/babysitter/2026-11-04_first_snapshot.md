# Nov 4 first snapshot (00:0x PT), verdict per tier (babysitter, 09:20 UTC)

Checked against docs/babysitter/forward_capture_spec.md in raw/ph_at_launch/2026-11-04/ (live/, api_*/) and
raw/ph_at_launch/live/boxbrowser_first_snapshot_20261104/. Counts only; usernames stay in GCS.

| Tier | What | Verdict | Evidence |
|---|---|---|---|
| P0 | Launch series via API, every 15 min | **PASS** | 00:01 PT: 35/35 launches, fetched 08:01:11Z (12 s late); 00:15 PT 35/35 (5 s late); fetched_at + snapshot_ts on every posts_ts row; heartbeat rewritten each snapshot |
| P0 | Comments via API | **PASS** | first window 38 comments, 37 commenter ids, 33 launches, every createdAt present (authors as numeric ids; usernames redacted by the API) |
| P1 | Board order (page view) | **PASS** (box browser) | board_ts 76 page-view rows: homepage 39 + leaderboard_daily 37, all fetched_at set, view_logged_out true; leaderboard time approximate |
| P1 | First-snapshot page content | **PARTIAL** | 16 box posts_ts rows (15 read, stopped at #16 on a second CF challenge); content_ts 13 rows with description and media null; tagline/topics/website from api_detail (35) |
| P1 | Makers + hunter at featured + 20 min | **FAIL** | no people_ts; route 4 (10001) on hold to Nov 5 07:25Z; 31 makers/hunters queued first on phpeople-2 instead (later than +20 min, so they fail the strict pre-launch rule) |
| P1 | Comments with usernames from the page | not needed | comments come from the API with exact times and commenter ids |
| P3 | Commenters on first sight | **NOT RUN** | tier scheduler not built; route 4 hold |
| P6a | Likely-voter first-seen reads | **NOT RUN** | same |
| P2-lite | Makers at +4 h / +24 h, follower diff | **NOT RUN** | same |
| P4 | Competitors (top-5 similar products) | **NOT RUN** | same |
| P5 / P6 | Commenters d2–7, rest of pool | **NOT RUN** | same |

Late rows: the PH agent's 14 start-up rows more than 5 min late are the 14 box-browser posts_ts rows of snapshot 20261104T0001PT
(read 08:05–08:13Z against snapshot_ts 08:00Z, up to 770 s). No API row and no coverage_ts slot is more than 5 min late.

Route-4 budget today: 2,500 pages, 0 used (gate not running). API key (box) at 12% at 08:15Z; light loop has priority, heavy backfills
now gated at ≥50% remaining.
