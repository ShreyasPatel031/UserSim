# Early-day line-ups in held data (orchestrator 15:08Z Nov 14; no new fetches)

Sources checked: Wayback homepage captures (raw/ph_homepage_archive/parsed.jsonl, 467 captures Jul 1 - Oct 28, today's posts = rows whose
featured PT day equals the capture's PT day), warehouse hourly vote_snapshots (first read 00:06 PT; Oct 31 on, adds Nov 5-7 which have no
00:05 forecast line-up), data/today/<d>.json (= the 16 live days already used), ph_at_launch live capture (Oct 25 on, same days), raw
producthunt_api (Nov 2 on, same days), leaderboard reads (10:50 PT or later). Raw API day files: featuredAt/createdAt are back-dated to
00:00-00:01 PT, so they cannot date a launch's first appearance.

Earliest held read per day: 12 Wayback days <= 01:00 PT and 17 <= 03:00 PT (+ Nov 5, 6, 7 at 00:06 from vote_snapshots) = 15 / 20 days.
Wayback first-capture hour is spread over the day (00h 12 days, 01h 4, 02h 1, 03h 3, ... 17h 10), 71 days with any homepage capture.

| day | source | PT | line-up | ranked | missing | missing in top 10 |
|---|---|---|---|---|---|---|
| 2026-07-01 | wayback home | 00:07 | 30 | 29 | 0 | 0 |
| 2026-08-31 | wayback home | 00:30 | 10 | 12 | 2 | 2 |
| 2026-09-10 | wayback home | 02:39 | 20 | 20 | 0 | 0 |
| 2026-09-11 | wayback home | 01:22 | 21 | 21 | 0 | 0 |
| 2026-10-03 | wayback home | 01:39 | 25 | 26 | 1 | 0 |
| 2026-10-04 | wayback home | 00:34 | 37 | 37 | 0 | 0 |
| 2026-10-05 | wayback home | 00:18 | 26 | 25 | 0 | 0 |
| 2026-10-06 | wayback home | 00:14 | 40 | 40 | 0 | 0 |
| 2026-10-07 | wayback home | 00:45 | 44 | 44 | 1 | 0 |
| 2026-10-08 | wayback home | 00:41 | 47 | 45 | 0 | 0 |
| 2026-10-09 | wayback home | 00:29 | 35 | 36 | 1 | 0 |
| 2026-10-10 | wayback home | 00:38 | 38 | 37 | 0 | 0 |
| 2026-10-13 | wayback home | 01:40 | 29 | 29 | 1 | 0 |
| 2026-10-15 | wayback home | 00:10 | 35 | 34 | 0 | 0 |
| 2026-10-16 | wayback home | 00:16 | 9 | 39 | 30 | 2 |
| 2026-10-17 | wayback home | 00:07 | 14 | 18 | 4 | 0 |
| 2026-10-18 | wayback home | 01:09 | 17 | 17 | 0 | 0 |
| 2026-11-05 | vote_snapshots first read | 00:06 | 36 | 35 | 0 | 0 |
| 2026-11-06 | vote_snapshots first read | 00:06 | 54 | 55 | 2 | 1 |
| 2026-11-07 | vote_snapshots first read | 00:06 | 18 | 24 | 6 | 5 |

Missing pattern: all 20 days 48 of 623 ranked missing (7.7%), but 30 of them are Oct 16 (a 00:16 capture showing 9 of 39 - a partial
homepage render, not a line-up). Without Oct 16: 18 of 584 (3.1%; <= 01:00 PT: 16 of 471, 3.4%), 8 in a final top 10, 1 in a top 3
(Nov 7). Final-rank percentile bins of the misses (incl. Oct 16): 4 / 11 / 11 / 12 / 10 - flatter than the live pattern's bottom-heavy
0.24 / 0.42 / 0.20 / 1.05 / 2.78; median missing final rank 19.5 (live 20.5). Several Wayback captures also show 1-2 launches that never
made the final featured list (unfeatured later).

Verdict: 19-20 usable early days, below the 40-day bar, so no arm 2 vs arm 3 replay on them (it would add ~19 days to E5's 17 with the
same width problem). The forward read that fixes this: keep the 00:20 PT midnight job's own line-up file every night (data/today/<d>.json
is already written at 00:05 by today.py and uploaded as raw/daily/<d>/today_0005.json since Oct 28; add a 01:00 PT re-read of the same
query into raw/daily/<d>/lineup_0100.json) - 30 nights give a 47-day real-line-up replay with E5's 17.
