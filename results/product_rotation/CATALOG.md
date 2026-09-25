# Product rotation (generic e2e)

Standing target: live site runs any product URL immediately.

**Pass bar:** 24 agents. Per-agent creation → first **REAL** (non-placeholder, non-blank) product screenshot ≤ `E2E2_FIRST_SHOT_S` (default **5s**). Placeholders do not count. 8-agent runs are smoke-only.

## Real-shot matrix (2026-09-25, `cursor/e2e-ui-run` tip)

| # | Product | PASS | run→first task | run→all 24 | creation→real shot p50/p95/max | elapsed |
|---|---------|------|----------------|------------|-------------------------------|---------|
| 1 | youtube.com | **PASS** | 25.7s | 31.8s | 0.27 / 0.32 / **0.35s** | 292s |
| 2 | developer.mozilla.org | **PASS** | 17.7s | 22.5s | 0.21 / 0.25 / **0.28s** | 283s |
| 3 | etsy.com | **PASS** | 21.5s | 29.5s | 0.23 / 0.38 / **2.69s** | 287s |
| 4 | linear.app | **PASS** | 16.9s | 28.6s | 0.24 / 1.80 / **3.93s** | 287s |
| 5 | bbc.com/news | **PASS** | 41.2s | 47.7s | 0.26 / 0.29 / **0.92s** | 305s |
| 6 | excalidraw.com | **PASS** | 23.5s | 27.0s | 0.15 / 0.17 / **0.17s** | 282s |

Warm BB create is ~0.3–1.3s; navigate+paint ~8–27s — that work runs during persona/task LLM so creation→real shot stays under 5s.

Prior sub-0.3s “PASSes” that stamped placeholders are **void**.

## Blockers
- **PR #32** is the merge candidate (includes #36 criteria). Prod e2e after merge.

## GCP
- No VMs started.
