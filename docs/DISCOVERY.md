# Discovery (study part 1)

Product URL in; competitors, real users and comparison tasks out. No browsers or simulated users run here.
Code: [`mvp/discovery.py`](../mvp/discovery.py). Test page: **`/discovery`** on the MVP server (`mvp/server.py`).

## What it does

1. **Reads the product's site** — homepage plus up to two about/pricing/features pages — and web-searches `what is <host>`.
2. **Profiles the product** (LLM): name, one-liner, category, target users, features, search terms, Product Hunt topics.
3. **Gathers competitor candidates**
   - Web search: `<name> alternatives`, `<name> competitors`, `best <search term>` — Google via Apify
     (`apify~google-search-scraper`) when `APIFY_TOKEN` is set, else DuckDuckGo HTML (often bot-checked from cloud IPs).
   - Product Hunt API v2: the product's own post, its topics (or topics matching the profile), top posts in those topics.
4. **Picks competitors** (LLM), probes their homepages, drops dead ones. Unpicked live candidates are "similar products".
5. **Collects real users**
   - Product Hunt commenters (headline + comment) on the product's and competitors' posts. PH redacts most user names.
   - G2 / Capterra (+ TrustRadius, Gartner) reviewers via Apify `zen-studio~software-review-scraper`
     (reuses `mvp/review_context.py`, cached in `cache/apify/`). Under 30 reviews → the next two similar products are scraped too.
6. **Writes segments and tasks** (LLM): 3–6 segments citing real users by id, and N tasks that work on every site.

Every step is in the run's `steps` trace: input, duration, summary and the raw data retrieved.

## API

| Route | |
|---|---|
| `POST /api/discovery` | `{"url", "max_competitors": 2, "task_count": 6, "scrape_reviews": true}` → `{"id"}` |
| `GET /api/discovery/{id}` | `{status, steps[], result}`; poll while `status == "running"` |
| `GET /api/discovery` | recent runs (saved under `mvp/runs/discovery/`) |

`result`: `product`, `competitors[]`, `similar_products[]`, `users[]`, `segments[]`, `tasks[]`, `counts`.

## Secrets

`APIFY_TOKEN` (already used for reviews) and **`PRODUCT_HUNT_TOKEN`** — a Product Hunt API v2 developer token, loaded
like the others from Secret Manager as `usersim-PRODUCT_HUNT_TOKEN` (see `mvp/secrets_store.py`). A missing token skips
that source; the trace says so. LLM calls use Gemini on Vertex (`capability.gemini_config`).
`MVP_DISCOVERY_REVIEW_WAIT_S` (default 240) caps how long one review scrape is awaited; it keeps running and caches.
