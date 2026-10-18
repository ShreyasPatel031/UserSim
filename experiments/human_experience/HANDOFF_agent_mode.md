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
earlier reviews to the context package: a rating line plus 8 earlier reviewers, either the most similar (`own_similar`)
or the most recent (`own_recent`). Paired differences vs agent_full, with product-cluster bootstrap 95% intervals:

| | Capterra own_similar | Capterra own_recent | Capterra own_only (no rivals) | G2 own_similar |
| --- | --- | --- | --- | --- |
| overall experience (same sentiment + main point) | **+0.081 [+0.041, +0.119]** (0.19 → 0.27) | +0.067 [+0.024, +0.107] | +0.057 | +0.035 [−0.035, +0.120] |
| cons matched | +0.022 [−0.017, +0.064] | +0.019 | −0.013 | +0.027 [−0.027, +0.090] |
| pros matched | +0.009 | +0.013 | +0.017 | −0.018 |

- **Words: own similar reviews plus the rival package is best.**
  - Overall experience improves significantly on Capterra and in the same direction on G2.
  - Cons improve slightly on both.
  - Removing the rival sections hurts cons.
- **Ratings: the model does not use the own-rating line well.** Its stated ratings didn't improve, so agent mode
  computes ratings from the data (result 2) instead of asking the model.
- Spend: about $8 for both benches. The ledger now stands at $36.

### 4. Per-person factors done right (`personalize.py`)

Data and method:
- The people-like-them averages compare segments *across* products. `personalize.py` instead learns each factor's offset
  *within* products: the rating minus that product's mean, learned on other products and shrunk with k = 50.
- The offsets are added to the own-review level, with the weight chosen on DEV products.

Findings on TEST:
- RMSE improved on 6 of 7 sets (by 0.3–1.4%); customer support was unchanged.
- Within-product Spearman rose: recommend 0.00 → 0.13, ease 0.02 → 0.10, overall 0.04 → 0.09.
- Time using the product dominates: a free-trial user recommends 0.53 lower, a 2+ year user 0.28 higher.
- Exported to `mvp/agent_mode_offsets.json`; agent mode reports the result as `for_this_persona`.

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
