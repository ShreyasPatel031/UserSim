# Product rotation (generic e2e)

Standing target: live site runs any product URL immediately.

**Pass bar (tightened):** 24 agents only. Per-agent creation→first-screenshot ≤ `E2E2_FIRST_SHOT_S` (default **5s**). 8-agent runs are smoke-only and do **not** count as PASS.

| # | Shape | Product | Smoke (8) | 24 + ≤5s/agent | Notes |
|---|-------|---------|-----------|----------------|-------|
| 1 | Video | youtube.com | smoke | pending re-run | prior loose PASS voided |
| 2 | Docs | developer.mozilla.org | smoke | pending re-run | prior loose PASS voided |
| 3 | E-commerce | etsy.com | smoke | pending re-run | prior loose PASS voided |
| 4 | SaaS signup | linear.app | smoke | pending re-run | was UNSTABLE @24 under old rule |
| 5 | News | bbc.com/news | smoke | pending re-run | prior loose PASS voided |
| 6 | Heavy JS | excalidraw.com | smoke | pending re-run | prior loose PASS voided |

## Blockers
- **PR #32 still OPEN** — prod https://usersim.vercel.app/ on `app.js?v=86`. Merge required for prod e2e.
- Re-run under tightened criteria in progress on `cursor/e2e2-tight-criteria-12d9`.

## GCP
- No VMs started.
