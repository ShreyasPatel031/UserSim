# Simulation competitor data (orchestrator 2026-11-25T00:22Z)

Adds to (does not replace) upvote refresh + need-list work.

## 1) Full PH category directory

- **Source:** https://producthunt.com/categories (Apollo SSR, same class as Similar Products on `/posts/<slug>`).
- **Canonical GCS:**
  - `raw/ph_categories/directory/categories_full.jsonl` — current snapshot (one JSON object per category).
  - `raw/ph_categories/directory/history/categories_full_{YYYYMMDD}PT.jsonl` — weekly archive after first delivery.
- **Row shape (per category):** `category_slug`, `category_name`, `group` (PH group), `description`, `products` (ordered list: `slug`, `name`, `tagline`, `url`, `rating`, `reviews_count`, `review_texts[]`), `fetched_at`, `source`.
- **SLA:** first complete directory by **2026-11-28 00:00 PT**; weekly refresh **Sundays 00:30 PT** thereafter.
- **Runner:** dedicated Camoufox/residential job (pattern: `raw/ph_alternatives/work/`), **not** pdeep fleet — avoids stacks blocker.

## 2) Featured launch categories + Similar Products

- **Schema:** same `similar_products[]` as `raw/ph_alternatives/similar_products_all.jsonl`, plus `launch_categories[]` on the launch row.
- **Canonical GCS:**
  - Nightly: `raw/ph_at_launch/{YYYY-MM-DD}/launch_competitor_context.jsonl` (featured launches that PT day).
  - Backfill Nov 1–25: `raw/ph_at_launch/competitor_backfill/2026-11-01_2026-11-25.jsonl` by **2026-11-28**.
  - Rolling merge: `raw/ph_alternatives/similar_products_by_launch.jsonl` (append/upsert by `launch_slug`).
- **SLA:** nightly by **01:00 PT** starting **2026-11-26** launches; backfill **Nov 1–25** complete by **Nov 28**.
- **Method:** reuse `ph_alternatives` parser (`ProductAlternativeEdge` + launch category fields from post page SSR).

## Dependencies / risk

- Route-4 residential Camoufox (documented in `ph_alternatives/README.md`); volume ~featured count/day + one-time category crawl (larger than 300-launch batch).
- Fleet pdeep remains on need-list/upvote; **LIVE_PRIORITY_HOLD** — no historical fleet scale-up for these feeds.

## 3) Reviews for competitor-set products (orchestrator 00:48Z)

- **Scope:** every `product_slug` in `similar_products[]` from each day's `launch_competitor_context.jsonl` (and Nov 1–25 backfill sets).
- **Schema:** same as `raw/ph_reviews/*.jsonl.gz` — `rating`, `text`, `date` per review (plus product identifiers).
- **GCS:**
  - Nightly **02:00 PT** from Nov 26: `raw/ph_reviews/competitor_sets/{YYYY-MM-DD}/reviews.jsonl.gz`
  - Backfill: `raw/ph_reviews/competitor_sets/backfill_2026-11-01_2026-11-25.jsonl.gz` by **Nov 28**
  - Coverage index: `raw/ph_reviews/competitor_sets/coverage_manifest.json`
- **Gap today:** Nov 24 top-15 competitor set — only **2/29** competitor products have held reviews.

## Status

Recorded in `mailbox/from_cursor/status.json` under `standing_information_needs.simulation_competitor_feeds`.