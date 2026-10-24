# Product Hunt launch-ranking baseline: handoff

**Goal:** given a new product (its public website and launch info), predict where it
would land among Product Hunt launches in its category, and eventually how likely it is
to succeed. This note covers the data work so far.

## What exists

| Piece | Where |
|---|---|
| Crawler (one topic + month, featured launches, resumable, rate-limit aware) | `scripts/ph_crawl.py` |
| Temporal-holdout baseline | `scripts/ph_baseline_eval.py` |
| Crawled data (7,850 rows, 5,454 unique launches, 43 MB, **gitignored**) | `data/producthunt/<topic>_<YYYY-MM>.jsonl` |

Data covers `artificial-intelligence`, `developer-tools` and `productivity` for
2025-10..2026-09, plus AI for 2025-06. Regenerate with:

```
export PH_CLIENT_ID=... PH_CLIENT_SECRET=...   # or PH_TOKEN
python scripts/ph_crawl.py --topic developer-tools --month 2026-03 --no-resolve
python scripts/ph_baseline_eval.py
```

## Product Hunt API facts (GraphQL, `https://api.producthunt.com/v2/api/graphql`)

- Auth: client-credentials token (`public` scope) or a developer token.
- Rate limit: 6,250 points per 900 s; each request costs 100 points regardless of size, so
  about 62 requests per window. Page size is capped at 20 posts.
- Query complexity cap is 500,000. Nested lists multiply, so `topics(first:10)` and
  `comments(first:5)` per post is about the maximum for a 20-post page.
- Available: votes, comments (body, votes, time), ranks, `featuredAt`, topics, makers (headline,
  followers), gallery media (images/video URLs), description, tagline, `reviewsCount` and
  `reviewsRating`.
- Not available: review text, voter lists or vote timing, Orbit-style categories (only 434
  topics), comment author names (redacted), upvote velocity.
- Product Hunt's `/r/...` website links sit behind a Cloudflare challenge for scripts and
  headless Chromium (verified, 403 `cf-mitigated: challenge`). Real product domains therefore
  do **not** resolve from the cloud container. Only 3 of 269 resolved, from URLs in
  descriptions. A real browser on a user's own machine and IP works.

## Results so far (temporal holdout: train 2025-10..2026-06, test 2026-07..2026-09)

Target is the within-topic-month vote percentile (volume and vote levels drift over time).

| Model | Spearman | Top-quartile hit rate (random 25%) |
|---|---|---|
| GBM, all features | 0.62 | 55% |
| Ridge, all features | 0.57 | 55% |
| GBM without maker follower counts | 0.53 | 51% |
| Max maker followers alone | 0.40 | 42% |

On a smaller 269-launch AI/June-2025 set, a blind LLM judge on tagline + description alone
reached 0.37, and adding it to structured features lifted 0.48 to 0.56.

## Caveats

- Maker follower counts are current, not as of launch, so the follower signal is inflated.
- Only featured launches are in the data. This predicts rank among featured launches, not
  whether a launch is featured.
- The LLM-judge numbers are contaminated by training-data recall of well-known products.
- No copy/embedding features yet and no real product domains.

## Suggested next steps

1. Add copy signal (embeddings or an LLM score on tagline + description) and measure lift over 0.62.
2. Add a nearest-similar-launches feature (median outcome of the 20 closest recent launches in the topic).
3. Estimate follower leakage.
4. Resolve real domains by running a Playwright worker on a user's own machine, or via PHBench
   (arXiv 2605.02974, about 67k featured launches with Crunchbase-linked Series A labels), then
   snapshot product sites.

## Security

A client secret and developer token were pasted into chat during this work. Regenerate them at
https://api.producthunt.com/v2/oauth/applications. None are stored in the repo.
