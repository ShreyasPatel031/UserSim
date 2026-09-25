# Product rotation (generic e2e)

Standing target: live site runs any product URL immediately.

| # | Shape | Product URL | Competitors | Agents | Status | Result dir | Notes |
|---|-------|-------------|-------------|--------|--------|------------|-------|
| 1 | Video / media | https://www.youtube.com/ | vimeo, dailymotion | 24 | PASS | `results/e2e2_youtube/` | 24/24 in 287.9s |
| 2 | Docs / search | https://developer.mozilla.org/ | docs.python.org | 8 → raising 24 | PASS 8 | `results/e2e2_mdn/` | 8/8 in 310s |
| 3 | E-commerce | https://www.etsy.com/ | ikea.com | 8 → raising 24 | PASS 8 | `results/e2e2_etsy/` | 8/8 in 378s |
| 4 | SaaS + signup | https://linear.app/ | notion.so | 8 → raising 24 | PASS 8 | `results/e2e2_linear/` | 8/8 in 264.5s |
| 5 | News / media | https://www.bbc.com/news | npr (+ apnews @24) | 8 + 24 | PASS | `results/e2e2_bbc/` `results/e2e2_bbc24/` | 24/24 in 282.8s |
| 6 | Heavy JS | https://excalidraw.com/ | tldraw (4×3×2) | 8 + 24 | PASS | `results/e2e2_excalidraw/` `results/e2e2_excalidraw24/` | 24/24 in 289.7s. diagrams.net produced no shots — dropped. |

## Blockers
- Prod https://usersim.vercel.app/ awaits PR #32 merge (still app.js?v=86).
