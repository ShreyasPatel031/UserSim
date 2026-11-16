# upvote_refresh.status (fleet-cursor)

**Run:** `20261108t082000z`  
**Started (UTC):** `2026-11-16T00:35:55Z` (first roll); **queue rebuild** `2026-11-16T01:40:56Z`  
**Started:** yes  

## Configuration

| Item | Value |
|------|--------|
| Mode | `repullupvotes` (Upvotes tab only, diff stop at first held upvote) |
| Source queue | `raw/_cursor/refresh_upvotes_20261116T0145Z_fleet.txt` (**82,661** complete people, no cap) |
| Order | Upvotes on launches dated **2026-10-17 … 2026-11-15** (`store_v3/events.parquet`; ties random seed 42) |
| Dedicated slots | **9, 27, 38** (~27,554 / 27,554 / 27,553 handles) |
| GO token | `repullupvotes:fleet-upvote-20261108t082000z-20261116T0140Z` |
| Strategy | `fleet_upvote_refresh.env` — same-IP back-off, no IPRoyal rotate on block |
| Historical fleet | **18 VMs** (`LIVE_PRIORITY_HOLD`, no scale-up) |

## Progress (daily)

| Metric | Value |
|--------|--------|
| People refreshed (2026-11-16 PT day) | ~40+ since 00:35Z roll; **restarted at top of new queue** after 01:40Z rebuild |
| Pages read (mean / p95) | pending hourly scrape from slot `status_*.jsonl` |
| New upvotes appended | pending Population merge tallies |
| Queue prior (deprecated) | `refresh_upvotes_20261112T2300Z.txt` (39,848 only) |

## Fleet context (01:41Z measure)

- Main completion fleet: **10.8 complete_ppm**, **6 active** slots (upvote slots 9/27/38 excluded from utilization recover restarts).
- Builder: `scripts/vm/ph_fleet_build_upvote_refresh_queue.py` (rebuild daily from `have_index.jsonl` + events).

## Not started

- **daily_launch_teams** — no `launch_teams` mode on current `reuse.tgz`.

## References

- `mailbox/to_cursor/20261114T2220Z_upvote_refresh_diff.md`
- `mailbox/to_cursor/20261114T2305Z_upvote_refresh_order.md`