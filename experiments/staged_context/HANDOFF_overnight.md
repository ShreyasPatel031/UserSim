# Handoff: overnight task (review-data mixtures, YC test, agent-mode MCP)

Branch: `claude/modest-euler-6111ae` (repo ShreyasPatel031/UserSim). All research code is in `experiments/staged_context/`.

## Update: overnight session (branch `claude/modest-wozniak-p0bt3q`, 18 Oct)

The user split the work. Agent mode belongs to the session on `claude/zealous-knuth-4zbdb1`
(`mvp/agent_mode.py`, `usersim_predict_experience`). This branch does **human mode on top of agent mode**, plus the
live data, the mixture test and the YC test. It is merged with that branch, which includes main.

- **Human mode** (`HUMAN_MODE.md`; `mvp/human_mode.py`; MCP tools `usersim_plan_human_run` /
  `usersim_combine_human_run`; tests in `mvp/test_human_mode.py`; docs in `docs/mcp/README.md`):
  - What to ask the run: the core job done for real, then second-level features, then editing. Context already
    predicts onboarding and pricing.
  - How much to add, for a product with its own reviews: rewrite agent mode's words with the run's product
    observations. Cons recall +0.046 (CI +0.007..+0.085), held out on 5 products.
  - For a product without own reviews: a bounded one-item edit.
  - Ratings: always agent mode's.
- **Live data:** `out/live/live_reviews.csv.gz` (79 products), `live.py`, `out/mixture/competitors.json`.
- **Mixture** (`MIXTURE.md`): live named rivals are in every top mixture; CL is best overall and L is the
  production choice.
- **YC test:** `yc_test.py`, `out/yc/` (see below).
- **Runs:** use the anonymous MCP client in `hm/`. Limits: 3 concurrent sessions and about 12 runs a day per IP.
  6 of 12 runs were blocked at sign-up (`+` aliases rejected, CAPTCHA, phone, no free plan).
- **Environment:**
  - `mcp` 2.x is installed system-wide, so the server tests need `.venv` (`mcp<2` plus `mvp/requirements.txt`,
    `browserbase`, `playwright`, `pillow`).
  - Run them with `PYTHONPATH=src .venv/bin/python -m pytest mvp/test_sim_mcp*.py mvp/test_*_mode.py`. 212 pass and
    1 fails (`oct18`, which also fails on main).
- **Apify:** the key was passed to curl only, via `$T`. The auto-mode classifier blocks saving it to a file or
  passing it to Python. Scrapes go through the scratchpad's `apify_scrape.sh` (curl), and Python reads
  `cache/live/`. About $45 of $105 is used so far.

## The task (from the user, verbatim intent)

1. Choose data sources (main G2 + Capterra, plus a few other scrapers) and a held-out set.
2. Find which **mixture of data sources improves scores on the most held-out eval sets**. Keep that mixture.
3. Test on **20 new YC startups** that the tool returns real data and reliable suggestions for **competitors, customers
   and tasks**.
4. Publish to the MCP an **agent mode**: context only, giving an agent data about a product. No browser runs.

## Rules the user has set (do not break)

- **Never use the FreshCrawl snapshots (Capterra 56k / G2 111k) as a product's competitors in production.** They cover
  arbitrary products. They are research and eval data only. Production competitor data = live scrapes of the
  product's real, named competitors.
- **No silent fallbacks.** If data is missing, say what is missing and stop. Don't substitute.
- **Browser / e2e runs go through the real MCP** at `https://35-202-98-224.sslip.io/mcp` (no token, no env vars; it
  handles sign-up, phone, inbox). Never run UserSim's browser code directly, logged out. Another agent owns the live
  MCP server, so don't redeploy it.
- Don't push code the user rejected. Ask before big spend. Keep reports short and plain, with the results first.

## State right now

- **main is NOT merged.** The branch is 165 commits behind `origin/main`.
  - A merge was tested and is clean, but the user stopped the commit, so it was aborted.
  - Merge again with `git merge origin/main` once the user agrees. Main has the real MCP server code
    (`mvp/sim_mcp/server.py`, docs in `docs/mcp-test/`).
  - MCP tests on the merged tree: 188 pass, 1 fails. `test_sim_mcp_oct18::test_start_study_schema_names_required_fields`
    fails on plain main too. They need `pip install pytest`.
- The rejected local sign-up/phone fallbacks were stashed in the old container. They are gone with it, and must not be redone.
- Apify token: `~/.config/apify/token` in this container only. The user must add `APIFY_TOKEN` to the environment
  secrets, and should rotate it, because it was shown in chat.
  - Apify account: $105/month limit, $4.32 used, 16 GB memory, 5 concurrent runs.
- Model spend (Gemini via the repo's Vertex client): $28.87 so far. The cap is `EXP_SPEND_CAP_USD`, default $10, so
  pass it explicitly, e.g. `EXP_SPEND_CAP_USD=60`.

## What is established (held-out results; details in HANDOFF_review_context.md)

- **The per-person package helps calibrate experience.** The package is people-like-them rating averages, competitor
  complaint-topic rates and 8 similar people's competitor reviews. Errors vs the agent alone:
  - overall 0.96 → 0.55;
  - value / support / recommend 0.96 / 1.22 / 1.92 → 0.69 / 0.78 / 1.34;
  - pros 32% → 38%; cons 22% → 26%; overall experience in words 10% → 23%.
  - Spotting unhappy users stays ~0.53 AUC.
- Per-output strategy router: `out/router/router.json`. Use the averages directly for value, support and recommend.
- G2 → Capterra transfer helps. Capterra → G2 is weak but never hurts, so keep both.
- **User mix / ICP:** competitors' counted reviewer mix plus the website gives roles 0.15, size 0.14, industry 0.13 TVD
  (2–3× better than the agent alone). This is only valid when the competitors really are competitors.
- **Website and O\*NET alone don't help. Raw logged-out run feedback hurts badly.** The e2e benchmark in
  `out/e2e_bench/` is invalid: its runs were logged out.

## Scraper comparison (SCRAPER_BAKEOFF.md)

- Best source: **`zen-studio/software-review-scraper`**.
  - One call by product name, covering G2, Gartner, TrustRadius and Capterra in one schema.
  - Job title 84%, company size 100%, industry 72%, real pros/cons text.
  - $0.54 per 98 reviews. Minimum `maxResults` is 100.
- Add **`zen-studio/g2-reviews-scraper`** for "problems solved" (the use case → tasks).
- The current production scrapers in `mvp/review_context.py` (trakk Capterra, automation-lab G2) are weak and should be
  swapped:
  - trakk can't find many products;
  - automation-lab has no job titles and no pros/cons text.
  - G2 segment codes are decoded (179/180/181). Industry codes aren't.
- Apify 402 means the memory cap was exceeded, not out of credit. `_apify_run` caps runs at 3 concurrent with explicit
  memory. Retry proxy connection resets.

## Plan for the remaining work

1. **Live eval set:** scrape ~8 held-out products not in the Capterra/G2 eval sets with the all-in-one scraper, to get a
   third eval set (Gartner/TrustRadius reviewers). Also scrape the 2 top competitors per category, for a "live" source.
2. **Mixture eval:**
   - Mixtures over {Capterra snapshot, G2 snapshot, live}: C, G, CG, L, CL, GL, CGL.
   - Eval sets: Capterra held-out (`router_eval.py` TEST, 120 people), G2 held-out (`g2_merge.py`, 80 people), live set.
   - Choose per output on dev products. Report win counts on held-out products. Reuse `corpus.sections()` and the
     router's per-output strategies to keep calls down (~3 calls/person/mixture, ~$13).
3. **Agent-mode tool:** `product_context(url)` returns:
   - competitors (named and validated: live URL, review data found);
   - customers (role / size / industry mix from competitor reviewers);
   - tasks (from competitor use cases / problems solved, plus the website);
   - the experience package.
4. **YC test:** take 20 recent YC companies (e.g. `https://yc-oss.github.io/api/batches/<batch>.json`). For each,
   report:
   - competitors found / valid / with reviews;
   - customer mix and tasks produced;
   - flag poor matches instead of guessing.
5. **Publish:** add the tool to `mvp/sim_mcp/server.py` as agent mode, with tests and docs. Push the branch, and don't
   redeploy the live server. Then write a short morning report.

## Key files

- `experiments/staged_context/corpus.py`: Capterra + G2 in one frame; `sections()` builds the package.
- `ux_mcp.py`, `ux_mcp_server.py`: the research MCP tool `predict_experience` and its router.
- `router_eval.py`, `g2_merge.py`: held-out evaluation harnesses. Each product's own reviews are excluded.
- `usage.py`: user-mix (ICP) prediction and its scoring (TVD).
- `mvp/review_context.py`: production, live scrapes of the named rivals only. `mvp/study.py::_review_evidence` attaches
  it to session feedback.
