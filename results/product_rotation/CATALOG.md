# Product rotation (generic e2e)

Standing target: live site runs any product URL immediately.

**Pass bar (tightened):** 24 agents only. Per-agent creation→first-screenshot ≤ `E2E2_FIRST_SHOT_S` (default **5s**). 8-agent runs are smoke-only and do **not** count as PASS.

| # | Shape | Product | Smoke (8) | 24 + ≤5s/agent | Notes |
|---|-------|---------|-----------|----------------|-------|
| 1 | Video | youtube.com | smoke | **PASS** 321.3s | run→tasks 55/60s; shot p50/p95/max 0.24/0.27/0.29s |
| 2 | Docs | developer.mozilla.org | smoke | pending | |
| 3 | E-commerce | etsy.com | smoke | pending | |
| 4 | SaaS signup | linear.app | smoke | pending | |
| 5 | News | bbc.com/news | smoke | pending | |
| 6 | Heavy JS | excalidraw.com | smoke | pending | |

## Blockers
- **PR #32 still OPEN** — prod https://usersim.vercel.app/ on `app.js?v=86`. Merge required for prod e2e.

## GCP
- No VMs started.
