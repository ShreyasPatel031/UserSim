# Hacker News simulation: project history (Oct 29 - Nov 1, 2026)

All numbers are from `experiments/hn_sim/RESULTS.md`; held-out test periods only. Code in `experiments/hn_sim/`,
branch `claude/hn-showhn-sim`.

## 1. Where it started

- **Brief:** a Show HN simulation pilot (twins / generic / page-only / shuffled arms). It was parked before Gate 1
  when the goal moved to predicting HN's top stories; no pilot scores were recorded.
- **First target:** each UTC day's top 100 / 30 / 10 stories by final points (test May-Sep 2026, 153 days).
  - **Baseline, post only** (title, domain/author record, timing): top 100 30.8%, top 30 20.8%, top 10 16.5%.
  - **Random picks:** 10.6% / 3.2% / 1.1%.

## 2. Major changes and what they did

| Step | Change | Effect (held out) |
|---|---|---|
| 1 | Comments in the first 30 / 60 min | top 30: 20.8% -> 34.0% -> 48.2% |
| 2 | Who commented early, submitter, favorites taste, account age, Tranco, Lobsters, crowd tally | each within +-0.5 points (no gain) |
| 3 | Forecast later in the story's life (8 h, per-day ranker) | top 30 75.4%, top 10 67.1% |
| 4 | Prior work reproduced | Taylor persona votes: AUC 0.57 vs ours 0.76 (adding them lowered ours to 0.72). Dubach RoBERTa: 0.67 vs ours 0.755 (+0.03 combined). Szabo-Huberman early votes: best single signal |
| 5 | Switched the target to HN's real daily list (front?day=) | A perfect points list matches only 47% of the real top 30. Training on the real list at 60 min: 25.2% -> 38.1% |
| 6 | Daily list v2 (comments by forecast time, previous day's list) | real top 30 found: 12:00 32.1%, 18:00 54.6%, end of day 65.8% |
| 7 | Votes and rank over the day (Quality News hourly), 3 months fetched | end of day 82%, 18:00 62% (18 test days) |
| 8 | Reverse-engineered the list rule | Each story is on exactly 1 day's list, filed by the day it first hit the front page (93.6%). 15-20% of the top 30 are re-ups posted 2+ days earlier. Ordering ceiling with known members: ~90% |
| 9 | v4: whole-life rank series, 7-day candidates (re-ups visible) | 46 test days, top 30 found: 18:00 59.9% -> 64.1%; 21:00 73.5% -> 78.5%; end of day 80.1% -> 86.0% |
| 10 | Hybrid: top-30 classifier picks, ranker orders | 18:00 63.6% -> 65.8% (+2.2 [+1.3, +3.3]); 21:00 78.4% -> 80.2% |
| 11 | 18:00 ablations | +-1 point each, not significant: submitter/domain/title history, outside feeds (Reddit, lobste.rs, Techmeme, arXiv), title similarity, re-weighting, lambdarank cutoffs, blends, predicted final points |
| 12 | Reframed per post ("I post now: what are my chances?") | Calibrated P(top 30) AUC: at posting 0.796, 15 min 0.824, 30 min 0.898, 1 h 0.956, 2 h 0.969. Calibration at posting: says 5.3% -> happens 5.3% |
| 13 | User simulation, individual twins (3,000 most active people) | Per-person median AUC: vector twin 0.583, LLM twin 0.540 ($0.058), popularity 0.808. Shared model v2: 0.632; + favorites 0.640 (0.653 for people with 10+) |
| 14 | Crowd simulation at posting (44k simulated readers; crowd v2 with 6k-person panel; /new competition) | at-posting AUC 0.782 -> 0.799 -> 0.803; none significant on winners caught |

## 3. What helped and what didn't

**Helped:**
- Early votes and comments (the dominant signal).
- Training on the real list instead of points.
- Understanding the list rule and making re-ups visible (the biggest jump: +6 points at end of day).
- The hybrid classifier and ranker.
- Calibration.

**Didn't help:**
- Every audience/taste signal at posting time: crowd tallies, LLM personas, individual twins, favorites taste.
- Outside feeds.
- /new competition.
- More list history (2023-24).
- Most model-architecture changes after v4.

**Why:** the same link posted twice gets nearly unrelated results. The first posting's points predict the repost
with AUC 0.567, and a repost of a flop wins 4.0% of the time, the base rate. Early exposure and luck dominate content.

## 4. Where we are against the north stars

- **Recall >= 80% on the daily top 30:**
  - **Met** at 21:00 UTC (80.2%) and later: 22:00 81.5%, 23:00 84.9%, end of day 86.0%.
  - **Not met** at 18:00 (65.8%). The ceiling there is ~81%, because ~19% of the eventual top 30 aren't posted
    yet; we find 81.9% of those that exist.
  - **Not met** at posting time (per post: 22% of winners in our daily top 30).
- **Competitor / persona grounding increasing predictive value:** not shown. Persona votes (Taylor reproduction),
  LLM twins, vector twins and crowd tallies each added nothing measurable over the post-only + early-signal models,
  and persona votes lowered AUC (0.76 -> 0.72). Competitor-grounded arms from the original Show HN brief were not run.

## 5. Biggest blockers

1. **Unposted and luck-driven stories.** At 18:00, about 5.6 of each day's top 30 don't exist yet. At posting,
   content barely predicts outcome (repost AUC 0.567).
2. **HN's hidden ordering** (moderation, flamewar penalties) caps end-of-day accuracy at ~90%.
3. **Data plumbing.**
   - Quality News is the only source of historical rank/vote series (slow, volunteer-run).
   - The favorites fetch collected only page 1 per person (pagination bug, re-fetch requested).
   - Live-only signals (second-chance pool, /new snapshots, GitHub stars) have about 1 day of history.

## 6. Next 3 steps

1. **Odds tool for one new post:** title + URL + time (+ votes later) gives a calibrated P(top 30 / top 10). The
   models are built (`odds.py`); this wires single-post inputs.
2. **Live validation:** score the hourly daily-list forecasts and per-post odds against settled lists from Nov 3
   (`score_live.py`). After ~2 weeks, test the pool, /new and star signals at 18:00.
3. **Full favorites:** re-run the individual and crowd models when pages 2-10 arrive. Expected gain is small; it's
   the last open test of the user-simulation approach on past data.

## Spend (measured, logged)

- Gemini: ~$6 (persona votes, title test, judges), LLM twin pilot $0.058, title embeddings $1.371.
- VMs: small e2-standard-2 now.
- Everything is within the approved budgets.

## Cross-domain: content taste vs ties (person level)

Metric, same as Product Hunt: per person-day in the held-out period, the model ranks the day's candidates for the
person; a hit if one of its top 3 picks is one the person engaged with (HN: commented on; PH: picked). The random
baseline is 1 - C(n - k, 3) / C(n, 3) per person-day, averaged. 95% intervals bootstrap over person-days.

| | Hacker News (this work; 60,451 person-days, Sep 1 - Oct 14) | Product Hunt (orchestrator, as reported) |
|---|---|---|
| content taste | 29.7% [29.3, 30.1] (vector taste + domain history + favorites) | vector twins 48.6 vs 49.7 without (no help) |
| ties | 17.2% [16.9, 17.5] (to the submitter: comments on their stories, replies, reciprocity, recency, share, rank that day) | 54.2 vs 50.4 without (better in all 6 months) |
| both | 30.2% [29.8, 30.6] | |
| random | 14.1% | |
| popularity (final size; not known at posting) | 49.8% [49.3, 50.1]; all three 55.5% [55.1, 55.9] | |

**Finding:** the person model has to learn the mix per domain. On HN, content taste carries the signal and ties add
only +0.5 points. On Product Hunt, ties beat taste.
