# Product rotation (generic e2e)

Standing target: live site runs any product URL immediately.

| # | Shape | Product | 8 | 24 | Notes |
|---|-------|---------|---|-----|-------|
| 1 | Video | youtube.com | — | **PASS** 287.9s | first_shot 23.4s |
| 2 | Docs | developer.mozilla.org | PASS | **PASS** 267.8s | first_shot 12.8s |
| 3 | E-commerce | etsy.com | PASS | **PASS** 280.7s | first_shot 17.0s |
| 4 | SaaS signup | linear.app | PASS | **UNSTABLE** (best 23/24) | 8/8 solid; at 24 some agents stuck on ~33KB logo splash. Auth-judge + longer paint waits shipped; still need stronger same-site backfill. |
| 5 | News | bbc.com/news | PASS | **PASS** 282.8s | NPR/AP competitors; Reuters bot-walled |
| 6 | Heavy JS | excalidraw.com | PASS | **PASS** 289.7s | 4×3×2 with tldraw; diagrams.net dropped |

## Blockers
- **PR #32 still OPEN** — prod https://usersim.vercel.app/ on `app.js?v=86`. Merge required for prod e2e.
- Linear@24: intermittent blank opening shots under full concurrency (generic SPA splash).

## GCP
- No VMs started.
