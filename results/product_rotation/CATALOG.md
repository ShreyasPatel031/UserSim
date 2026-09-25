# Product rotation (generic e2e)

Standing target: live site runs any product URL immediately. After YouTube 24-agent, rotate public products one at a time. Fix only generic issues.

| # | Shape | Product URL | Competitors | Agents | Status | Result dir | Notes |
|---|-------|-------------|-------------|--------|--------|------------|-------|
| 1 | Video / media | https://www.youtube.com/ | vimeo.com, dailymotion.com | 24 (4×2×3) | PASS local | `results/e2e2_youtube/` | 24/24 YESes in 287.9s; first_shot 23.4s |
| 2 | Docs / search | https://developer.mozilla.org/ | docs.python.org/3/ | 8 (2×2×2) | PASS local | `results/e2e2_mdn/` | 8/8 YESes in 310s; first_shot 15.5s |
| 3 | E-commerce | https://www.etsy.com/ | https://www.ikea.com/ | 8 (2×2×2) | PASS local | `results/e2e2_etsy/` | 8/8 YESes in 378s; first_shot 17.0s |
| 4 | SaaS landing + signup | https://linear.app/ | https://www.notion.so/ | 8 (2×2×2) | PASS local | `results/e2e2_linear/` | 8/8 YESes in 264.5s; first_shot 29.9s |
| 5 | News / media | https://www.bbc.com/news | https://www.npr.org/ | 8 (2×2×2) | PASS local | `results/e2e2_bbc/` | 8/8 YESes in 252.5s; first_shot 20.2s. Reuters competitor failed bot wall (see result_reuters_fail.json); NPR works. Raising to 24. |
| 6 | Heavy JS web app | https://excalidraw.com/ | https://tldraw.com/ | 8–24 | pending | `results/e2e2_excalidraw/` | |

## Blockers
- Production https://usersim.vercel.app/ awaits PR #32 merge (prod still app.js?v=86).
- Ready CTA sometimes still hidden after complete despite studyStillRunning fix — investigating stale live_session statuses.
