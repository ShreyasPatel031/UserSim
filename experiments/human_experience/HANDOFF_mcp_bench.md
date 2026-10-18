# Handoff: signed-in production-MCP runs on the handoff's held-out benchmark

Branch `claude/ecstatic-einstein-3e3aq5`. Question from the user: does running the reviewer's real task in persona,
signed in, on the **production MCP** (`https://35-202-98-224.sslip.io/mcp`), add to or remove from prediction quality
when combined with the review context from `experiments/staged_context/HANDOFF_review_context.md`
(branch `claude/modest-euler-6111ae`, checked out at `/home/user/UserSim-ctx`; `git worktree add` it if missing)?
Directional answer wanted; calibration comes later. **No O*NET, no rerunning the context-only test, keep spend low.**

## How it works
- `mcp_bench.py dump --product P` writes reviewer cards (role, industry, size, tenure, task; no review text) to
  `results/mcp_bench/cases/<rid>.json`. Cases are the handoff's held-out TEST products (`e2e_bench.cases(5)`).
- One subagent per case follows `v2/MCP_BENCH_RUNNER.md` (uses `mcp_client.py`, fresh sign-up each time) and writes
  `results/mcp_bench/runs/<rid>.json` (signed_in, reached_product, outcome, observations split into product_friction /
  product_benefit / agent_failure / signup_friction).
- `EXP_SPEND_CAP_USD=35 python experiments/human_experience/mcp_bench.py score --product P [--product Q]`, run from
  `/home/user/UserSim-ctx`, scores C1-C6 into `results/mcp_bench/per_case.csv` / `summary.csv`. The handoff ledger was
  already at $28.9 so the default $10 cap must be raised. C5/C6 feed only product observations from runs that were
  signed in and reached the product; agent failures are dropped.
- Server allows 10 concurrent sessions; start retries when full.

## Results so far
- **Basecamp 5/5 signed in** (scored): C2 reviews-only is best on ease 0.20 / functionality 0.20 / overall 0.80 MAE.
  Signed-in run alone (C5) 1.0 / 1.0 / 1.2; run + reviews (C6) 0.60 / 0.80 / 1.20. Logged-out runs (C3/C4) were worse
  still (1.5-1.75). The run pulls ratings down ~1 star because the predictor treats listed frictions as lost stars;
  reviewers actually rated 3-5. C6 alone matched any cons (0.12). 5 people, directional only.
- **Smartsheet 0/5**: all blocked at sign-up (error page / verification mail never arrived). Dropped.
- Case cards also dumped for Freshdesk, Klaviyo, Freshsales.

## In flight / next
1. Freshdesk (5) and Klaviyo (4 launched; 3268470 may be one) subagents were launched; check `results/mcp_bench/runs/`
   for missing rids (Freshdesk 4807753, 6505501, 4986750, 5016866, 6602735; Klaviyo 2733249, 3090142, 3268470,
   6746071). Re-launch any that are missing. Then run `score` on Basecamp + Freshdesk + Klaviyo.
2. Freshsales (2868417, 1298771, 3875603, 1379542, 1283516) not launched yet. Optionally Zoho CRM / Looker for the
   5-product spread; skip products where sign-up blocks (retry once, then drop and say so).
3. Fix to test next (calibration): keep the context-only rating, use the run only to adjust it or for pros/cons,
   instead of letting observations replace it. Do not feed pass/fail or agent failures into predictions.
4. Report to the user briefly: table per condition across products, how many runs signed in, and spend.
5. Commit and push everything (a stop hook requires a clean tree). Do not open a PR unless asked.
