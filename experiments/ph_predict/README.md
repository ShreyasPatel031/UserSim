# Predicting Product Hunt's Top Products lists

**Goal:** predict which launches appear on PH's homepage lists — Yesterday's, Last Week's and Last Month's Top
Products, overall and per topic — without using the launch's own votes, comments or ranks.

**Results:** [`FINDINGS.md`](FINDINGS.md) (summary) and [`out/report.md`](out/report.md) (recall@3/5/10 per list, sources, factors, product types, topic lists).

## Pipeline

| Step | Script | Source | Route / cost |
|---|---|---|---|
| Launches + labels | `collect_ph.py` | PH GraphQL API: every featured launch per PT day, with `dailyRank` / `weeklyRank` / `monthlyRank` | free; 6,250 points per 15 min, ~250 per day of launches |
| Websites | `crawl_sites.py` | PH's `/r/` redirect → real homepage text | Apify Website Content Crawler, US residential, cheerio: ~$0.0003 per site |
| LLM read | `llm_scores.py` | Gemini 2.5 Flash-Lite on listing + homepage (PH badges removed) | Vertex AI, cents per thousand |
| Outside signals | `external.py` | HN stories linking the domain before launch day (Algolia), domain age (RDAP), GitHub stars before launch day | free |
| Features | `features.py` | groups: launch, people, followers, history, site, llm, hn, domain, github | — |
| Backtest | `evaluate.py` → `report.py` | expanding window by month, LightGBM on log votes, recall@k per list | — |
| Residual | `residual.py` | does judging the product predict votes the team/hunter model misses? | — |
| Live | `predict_live.py <day>` | today's launches, model trained on all earlier days | — |

`run_all.sh` runs the enrichment steps (GitHub links: `crawl_sites.py 2025-01-01 Github`) and the backtest; each step skips work already on disk (`cache/`, gitignored).

Credentials (env): `PH_TOKEN` (or `PH_CLIENT_ID` + `PH_CLIENT_SECRET`), `APIFY_TOKEN`,
`GOOGLE_APPLICATION_CREDENTIALS` (Vertex), optional `GH_TOKEN`.

## Leakage rules

- Labels never enter features. Track-record features (maker / hunter / topic / look-alike launches) only read
  launches from earlier days.
- Rows are shuffled before ranking: the API returns each day in rank order, and ties broken by row order leaked the
  answer (a constant feature scored 0.99 before the fix).
- Follower counts are today's counts, so they include followers won by the launch itself. They are a separate
  group, left out of the headline model and reported alongside it.
- Homepages are crawled today, not on launch day; sentences mentioning Product Hunt / "Product of the Day" are
  stripped before any feature or LLM sees them.
- Live days (fetched before the PT day closed) are excluded from the backtest.
