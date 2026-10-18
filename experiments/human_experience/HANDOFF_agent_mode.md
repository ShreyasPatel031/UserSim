# Handoff: agent mode + what adds accuracy on top of the review-context agent

Branch `claude/zealous-knuth-4zbdb1`, PR https://github.com/ShreyasPatel031/UserSim/pull/86 (to main).
Research code imports the review-context branch from `$CTX_ROOT` (default `/home/user/UserSim-ctx`):
`git worktree add /home/user/UserSim-ctx origin/claude/modest-euler-6111ae`.

**Dependencies.** The analysis scripts need `scikit-learn` and `google-genai`. MCP tests need `pytest`, `mcp<2`,
`browserbase` and `browser-use==0.13.8`. Run tests with `PYTHONPATH=src`.

## Results (all held out; nothing checked by a human)

### 1. Ratings: calibration on top of the plain context agent (`calibrate.py`)

Data and method:
- 420 Capterra reviewers across 35 products.
- Choices made on 25 dev products and scored on 10 test products, plus leave-one-product-out (LOPO) over all 35.
- No model calls.

Findings:
- **Only the rating level matters.**
  - Under MAE, predicting the median for everyone (5/5, 9/10) beats the agent: 0.669 → 0.570 on test, 0.690 → 0.534 LOPO.
  - Under RMSE, predicting the mean beats it: 0.899 → 0.761.
- **Nothing adds per-person signal.** Every learned stack (agent + people-like-them averages + factor weights + corpus
  gradient boosting) tied with the constant. Within-product Spearman stayed ≤ 0.08 and unhappy-user AUC 0.50–0.63.

### 2. Ratings: which data moves the level (`heldout_bench.py`)

Data and method:
- Model-free, about 5,700 reviewers.
- 4 eval sets: Capterra dev/test and G2 dev/test. Products are split by hash.

Findings:
- **The product's own recent reviews**, shrunk to a prior (last 100–200, k = 10), won on all 4 sets:
  - G2 test RMSE 0.726 → 0.648 (−11%);
  - Capterra test 0.822 → 0.803.
- **The product's reviews on the other platform did not transfer** (slightly worse). The same goes for rivals' reviews
  from the other platform.
- **Recency matters**: all of the product's history was worse than its last 50–200 reviews on G2.

### 3. Words (pros, cons, overall experience)

`own_reviews_bench.py` (Capterra, 420 people) and `own_reviews_bench_g2.py` (G2, 200 people) add the product's own
earlier reviews to the context package. Results are in `results/own_reviews_bench*/summary.csv`; see the update below.

## Agent mode (shipped in PR #86)

- **Tool**: `usersim_predict_experience` in `mvp/sim_mcp/server.py`; logic in `mvp/agent_mode.py`.
  - Live scrapes of the product and its rivals use `mvp/review_context.py` (Apify), so `APIFY_TOKEN` must be set on the server.
  - When rivals aren't named, they are discovered from the URL with the study planner.
  - Ratings use result 2; words use the most similar reviewers.
  - Statuses: `ok`, `pending` (call again), `no_data` (with a reason), `disabled`.
- **Human mode** is the existing browser flow. Docs: `docs/mcp/README.md` ("Two modes").
- **Tests**: `mvp/test_agent_mode.py`.

## Open

- A third eval source (TrustRadius / Gartner) and a live YC test need `APIFY_TOKEN` in the environment. The all-in-one
  `zen-studio/software-review-scraper` was best in `SCRAPER_BAKEOFF.md`; agent mode still uses the older trakk /
  automation-lab actors.
- The live MCP server is owned by another agent; it has not been redeployed.
- mcp_bench (signed-in runs): the Freshdesk / Klaviyo runs never reported back, and Freshsales was never launched
  (see `HANDOFF_mcp_bench.md`).
