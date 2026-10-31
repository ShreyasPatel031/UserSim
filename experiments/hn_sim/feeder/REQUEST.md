# Data request for the HN daily-list forecast (from the hn_sim agent)

Goal: predict news.ycombinator.com/front?day=D (top 30), forecast at times T during the UTC day D.
Metric: share of the real top 30 found in our top 30. Now (46 test days): 12:00 UTC 35%, 18:00 60%, 21:00 74%,
end of day 80%.

## What we learned (2026-10-31)
- Every story is on exactly one day's list (20,159 stories, all 120 ranks).
- That day is the UTC day the story first reached the front page, or its posting day if it got there within 30 min
  (93.6% of list entries). 15-20% of a day's top 30 are stories posted 2+ days earlier that came back to the front
  page (second-chance re-ups). HN's displayed time is not reset, so re-ups are seen only through rank history.
- Order within a day follows points.
- Before ~20:00 UTC most misses are stories not posted yet.

## Wanted, in order
1. **Outside feeds with first-seen times** (in progress by the feeder), to anticipate stories before they reach HN:
   Techmeme, lobste.rs, Reddit r/programming + r/technology, GitHub trending, arXiv cs, company blogs/press RSS,
   X posts from high-reach tech accounts. Fields: source, url, title, published_at (source time, UTC), fetched_at,
   engagement counts at fetch time. 2026-07-01..2026-10-16, then live.
2. **HN ranks every minute, from now on**: news.ycombinator.com/ pages 1-3, /newest, /pool (id, rank, points,
   comments, fetched_at). This is what tells us re-ups and momentum live.
3. Linked page metadata (domain, publish time, paywall) - low.
4. Per-person data (GitHub/X/sites) - lowest; person-level data goes to the private bucket only.

## Format and place
JSONL, one row per item per read, gs://usersim-bakeoff-347838016394/usersim_sim/hn_jobs/cache/feeder/<source>/<YYYY-MM-DD>.jsonl
Each row: source, id/url, title, published_at (source time, UTC), fetched_at (UTC), counts.
Cutoff rule: a forecast at T uses only rows with published_at < T (and fetched_at < T for live use). Counts read today
(karma, followers, likes) are usable only for live forecasts, never for past days.
Never post, vote or comment on HN. Log every dollar to the warehouse spend table.
