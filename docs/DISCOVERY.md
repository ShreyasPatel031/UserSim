# Discovery (study part 1)

Product URL in; competitors, real users and comparison tasks out. No browsers or simulated users run here.
Code: [`mvp/discovery.py`](../mvp/discovery.py). Test page: **`/discovery`** on the MVP server (`mvp/server.py`).

## What it does

Every page it uses is one Google returned (Gemini's Google Search grounding on Vertex, all queries in parallel;
DuckDuckGo only if a Google call fails). Apify is used only to scrape review pages. Nothing is reached by guessing a
URL or a slug.

1. **Reads the product's site** — homepage plus up to two about/pricing/features pages.
2. **Profiles the product** (LLM): name, one-liner, category, target users, features, search terms, Product Hunt topics.
3. **Gathers competitor candidates:** Google `<name> alternatives`, `<name> competitors`, `best <search term>`, plus
   similar Product Hunt launches (API: top posts in the topics matching the product).
4. **Picks competitors** (LLM). Each homepage must appear in Google results for `<name> <category>`, then is probed live.
5. **Collects real users.** For the product and each competitor, Google `site:g2.com|capterra.com|producthunt.com
   <name> reviews` finds its exact page; the name must match (`jira`, `atlassian-jira`, `linear-2` yes;
   `jira-service-management` no). Each page is scraped by URL:

   | Site | Apify actor | Who you get |
   |---|---|---|
   | G2 | `zen-studio~software-review-scraper` (URL input; its other-platform rows dropped) | job title, size, industry, rating, review |
   | Capterra | `trakk~capterra-reviews-scraper` (`productUrls: [{url}]`) | job title, size, industry, rating, pros/cons |
   | Product Hunt | `eiv~producthunt-reviews-scraper` (`/products/<slug>/reviews`) | name, headline, rating, review |

   Under 30 users → the next two similar products are scraped too. Scrapes are cached per URL in `cache/apify/`.
6. **Writes segments and tasks** (LLM). Segments come only from the real users retrieved: each must cite users by id,
   and any segment citing no retrieved user is dropped. With 0 users there are no segments, only tasks from the
   product's features, and the result's `source_gaps` (shown as "Missing data") says which source gave nothing and why.

Every step is in the run's `steps` trace: input, duration, summary and the raw data retrieved.

Check the sources with real credentials, without the LLM:
`python scripts/discovery_sources_check.py --product Linear --competitors Jira Shortcut`

## API

| Route | |
|---|---|
| `POST /api/discovery` | `{"url", "max_competitors": 2, "task_count": 6, "scrape_reviews": true}` → `{"id"}` |
| `GET /api/discovery/{id}` | `{status, steps[], result}`; poll while `status == "running"` |
| `GET /api/discovery` | recent runs (saved under `mvp/runs/discovery/`) |

`result`: `product`, `competitors[]`, `similar_products[]`, `users[]`, `segments[]`, `tasks[]`, `source_gaps[]`, `counts`.

## Secrets

| Variable | Used for |
|---|---|
| `APIFY_TOKEN` | Google search and G2/Capterra review scrapes (also read from `~/.config/apify/token`) |
| `PH_TOKEN`, or `PH_CLIENT_ID` + `PH_CLIENT_SECRET` | Product Hunt API v2. Same names as `scripts/ph_crawl.py` ([docs/producthunt/README.md](producthunt/README.md)); the client pair mints a public-scope token |

Where to set them depends on what runs discovery:

- **Production server** (`/discovery` on the VM): Secret Manager, as `usersim-<NAME>` in `project-amer-scs-sandbox`
  (loaded by `mvp/secrets_store.py` within ~5 min, no redeploy). Cloud-session environment settings do not reach the VM.
- **Claude cloud sessions**: the environment's settings (session title bar → cloud environment → Edit → secrets /
  environment variables). Never commit them or paste them into chat.

A missing credential skips that source and shows under "Missing data". LLM calls use Gemini on Vertex
(`capability.gemini_config`). `MVP_DISCOVERY_REVIEW_WAIT_S` (default 240) caps how long one review scrape is awaited;
it keeps running and caches.
