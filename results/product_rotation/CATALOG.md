# Product rotation (generic e2e)

Standing target: live site runs any product URL immediately.

**Pass bar (tightened):** 24 agents only. Per-agent creation→first-screenshot ≤ `E2E2_FIRST_SHOT_S` (default **5s**). 8-agent runs are smoke-only and do **not** count as PASS.

| # | Shape | Product | Smoke (8) | 24 + ≤5s/agent | Notes |
|---|-------|---------|-----------|----------------|-------|
| 1 | Video | youtube.com | smoke | **PASS** 321.3s | run→tasks 55/60s; shot p50/p95/max 0.24/0.27/0.29s |
| 2 | Docs | developer.mozilla.org | smoke | **PASS** 278.1s | run→tasks 21/26s; shot max 0.26s |
| 3 | E-commerce | etsy.com | smoke | **PASS** 288.4s | run→tasks 22/29s; shot max 1.99s |
| 4 | SaaS signup | linear.app | smoke | **PASS** 319.7s | 4×3×2; run→tasks 48/53s; shot max 0.26s |
| 5 | News | bbc.com/news | smoke | **PASS** 292.8s | NPR/AP; run→tasks 25/30s; shot max 0.27s |
| 6 | Heavy JS | excalidraw.com | smoke | **PASS** 293.6s | 4×3×2 tldraw; run→tasks 35/38s; shot max 0.15s |

## Blockers
- **PR #32 still OPEN** — prod https://usersim.vercel.app/ on `app.js?v=86`. Merge required for prod e2e.

## GCP
- No VMs started.
