# Data request for the HN daily-list forecast (from the hn_sim agent)

Goal: predict news.ycombinator.com/front?day=D (top 30), forecast at times T during the UTC day D.
Metric: share of the real top 30 found in our top 30. Now (46 test days): 12:00 UTC 35%, 18:00 60%, 21:00 74%,
end of day 80%.

## What we learned (2026-10-31)
- Every story is on exactly one day's list (20,159 stories, all 120 ranks).
- That day is the UTC day of HN's *displayed* time, which HN resets when it re-ups a story from the second-chance
  pool. 15-20% of a day's top 30 are stories posted 2+ days earlier and re-upped.
- Order within a day follows points.
- The rest of what we miss before ~20:00 UTC is stories not posted yet.

## Wanted, in order
1. **Re-up events with times** (the biggest gap). From now on, every 1-2 min: news.ycombinator.com/ (and ?p=2,3),
   /newest, /pool, /front; for each item: id, rank, points, displayed age text ("3 hours ago"), comment count,
   fetched_at. A displayed age younger than the item's real age = re-upped; its new time = fetched_at - age.
   Historical: any archive of HN front pages with displayed ages (archive.org snapshots of news.ycombinator.com,
   2026-07-01..2026-10-16) would let us backtest this directly.
2. **Outside feeds with first-seen times**, to anticipate stories before they reach HN: Techmeme, lobste.rs,
   Reddit r/programming + r/technology (new + top), GitHub trending (daily), arXiv cs new listings, company engineering
   blogs/press RSS, X posts from high-reach tech accounts. Fields: source, url, title, published_at (source time,
   UTC), fetched_at, engagement counts at fetch time. Backfill 2026-07-01..2026-10-16 where the source has dated
   history, then live.
3. **HN rank + score every minute** (Firebase topstories/newstories/beststories + item score), from now on.
4. Linked page metadata (domain, publish time, paywall) - low.
5. Per-person data (GitHub/X/sites) - lowest; person-level data goes to the private bucket only.

## Format and place
JSONL, one row per item per read, gs://usersim-bakeoff-347838016394/usersim_sim/hn_jobs/cache/feeder/<source>/<YYYY-MM-DD>.jsonl
Each row: source, id/url, title, published_at (source time, UTC), fetched_at (UTC), counts.
Cutoff rule: a forecast at T uses only rows with published_at < T (and fetched_at < T for live use). Counts read today
(karma, followers, likes) are usable only for live forecasts, never for past days.
Never post, vote or comment on HN. Log every dollar to the warehouse spend table.
