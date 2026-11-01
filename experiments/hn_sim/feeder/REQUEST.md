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

## URGENT (2026-10-31 17:10 UTC): HN favorites for 4,786 people - please fetch fast, then verify

Why: favorites are the closest public thing to a person's upvotes; they train each simulated user's taste. Our one VM
gets throttled by HN (about 30 people per hour). You have a residential proxy and your own machine.

- People: gs://usersim-bakeoff-347838016394/usersim_sim/hn_jobs/cache/feeder/requests/favs_people.csv (person, rank;
  most active commenters first). Do them in rank order.
- Pages: https://news.ycombinator.com/favorites?id=<person>&p=<n>, n = 1..10 (30 stories a page; stop at the first
  page with no stories). Read-only. Never log in, vote, favorite or post. Spread requests over several proxy IPs,
  about 1 request per second per IP; back off on 503 / "Sorry".
- Output, one row per page, appended as you go:
  gs://usersim-bakeoff-347838016394/usersim_sim/hn_jobs/cache/feeder/favs/favs_<part>.jsonl
  {"person": str, "page": int, "story_ids": [int, ...], "fetched_at": "<UTC ISO>", "status": int}
  ("story_ids" from the <tr class="athing" id="..."> rows, in page order). Person-level data: this private bucket only.
- Verify before saying done, and put the numbers in feeder/favs/VERIFY.md:
  1. people done / 4,786; pages done; share of pages that came back blocked or empty-by-error (should be < 1%);
  2. re-fetch 50 random (person, page) pairs from a different IP and report how many match exactly;
  3. 20 random people: count of favorites vs the "favorites" link on their profile page (if shown) or page count;
  4. no duplicate (person, page) rows; every story_id is an integer that exists on HN (spot-check 50 via
     https://hacker-news.firebaseio.com/v0/item/<id>.json).
- Spend: log any proxy cost to the spend table. Tell us when the first 1,000 people are in.

## Favorites: pagination bug (found 2026-11-01 by the hn_sim agent) - please re-fetch pages 2-10

In feeder/favs/*.jsonl, for all 795 people with 3+ pages, every page holds the same story ids as page 1 (e.g.
lcnPylGDnU4H9OF pages 1-4 all start 46816357, 46345549, 45937302). So the 251,999 ids are 40,446 unique; only the
first 30 favorites per person were collected. Likely cause: the page parameter was dropped. HN's own "More" link on
https://news.ycombinator.com/favorites?id=<person> is the reliable way to the next page - follow it rather than
building the URL. Check before re-running: page 2 differs from page 1 for a person with 60+ favorites.
Verification to add: for 20 people, page n's first id must not appear on page n-1.
Please re-fetch pages 2..10 for those 795 people into feeder/favs/favs_p2_<part>.jsonl, same row format.
