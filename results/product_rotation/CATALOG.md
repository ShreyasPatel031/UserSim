# Product rotation (generic e2e)

Standing target: live site runs any product URL immediately. After YouTube 24-agent, rotate public products one at a time. Fix only generic issues.

| # | Shape | Product URL | Competitors | Agents | Status | Result dir | Notes |
|---|-------|-------------|-------------|--------|--------|------------|-------|
| 1 | Video / media | https://www.youtube.com/ | vimeo.com, dailymotion.com | 24 (4×2×3) | PASS local | `results/e2e2_youtube/` | 24/24 YESes in 187.5s; prod deploy pending PR #32 merge |
| 1b | Video ownership smoke | https://www.youtube.com/ | vimeo.com | 4 (2×2×2) | PASS local | `results/e2e2_ownership_smoke/` | Tagged BB owner=e2e; selective kill verified |
| 2 | Docs / search | https://developer.mozilla.org/ | docs.python.org/3/ | 8 (2×2×2) | PASS local | `results/e2e2_mdn/` | 8/8 YESes in 310s; first_shot 15.5s |
| 3 | E-commerce | https://www.etsy.com/ | https://www.ikea.com/ | 8 (2×2×2) | RUNNING | `results/e2e2_etsy/` | Capped to 8 while BB has 13 untagged foreign sessions |
| 4 | SaaS landing + signup | https://linear.app/ | https://notion.so/ | 24 | pending | `results/e2e2_linear/` | |
| 5 | News / media | https://www.bbc.com/news | https://www.reuters.com/ | 24 | pending | `results/e2e2_bbc/` | |
| 6 | Heavy JS web app | https://excalidraw.com/ | https://tldraw.com/ | 24 | pending | `results/e2e2_excalidraw/` | |

## Blockers
- Shared Browserbase: 13 untagged keep_alive sessions (~17+ min) left alone per ownership policy (likely Sign Up pre-tag). Leaves ~12 free of 25 — full 24-agent runs blocked until those release.
- Production https://usersim.vercel.app/ still on `app.js?v=86`; PR #32 MERGEABLE, needs merge → deploy.
