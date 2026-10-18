# Staged-context pilot

Which customer-context evidence improves product-level predictions of held-out Capterra reviews
(Asana, Trello, ClickUp; 20 hidden test reviews each)? This implements the handoff spec in
`Coding_Agent_Staged_Context_Experiment.md`: 8 input conditions × 3 products = 24 prediction calls per repetition.

## Run

From the repo root:

```bash
python experiments/staged_context/experiment.py prepare --seed 42   # no model: download, split, packs M/D/C/T, leakage checks
python experiments/staged_context/experiment.py baselines           # no model: numeric rating baselines
python experiments/staged_context/experiment.py estimate            # no model: projected spend
python experiments/staged_context/experiment.py onet                # model: occupation mapping -> pack O
python experiments/staged_context/experiment.py smoke               # model: Asana S0+S4 vs dev rows (schema + cost check)
python experiments/staged_context/experiment.py predict --conditions all --repetitions 1
python experiments/staged_context/experiment.py score               # model: test extraction + blind judging + metrics
python experiments/staged_context/experiment.py report              # writes out/report_tables.md
```

Model steps reuse the repo's Vertex client (`src/model.py::_client`, same credentials as the rest of
UserSim). Defaults: predictor `gemini-2.5-flash` (temperature 0.7, seed 1000×rep), extractor/judge
`gemini-2.5-pro` (temperature 0). Override with `EXP_PREDICT_MODEL` / `EXP_JUDGE_MODEL`; a `claude-*` model
name routes to the Anthropic SDK via `ANTHROPIC_API_KEY`. Spend cap: `EXP_SPEND_CAP_USD` (default 10). Every
model call is cached by request hash in `out/calls/` and logged (tokens, cost, elapsed, error) in
`out/call_log.jsonl`, so reruns are free and resumable.

## Design notes

- **Split** (`out/splits.json`): FreshCrawl revision `fc7c316c…`, CSV sha256 `867bea84…`. Prose = NFKC/lowercase/
  whitespace-collapsed pros, cons, comments and choose/switch reasons. Exact and 5-gram-Jaccard ≥ 0.85 duplicates are
  clustered (blank prose never clusters), one representative kept. The snapshot has none. Per product, rows are sorted by
  `sha256("42|product|review_id|text")`: 5 dev, 20 test, 975 pool.
- **Isolation**: prediction reads only `out/packs/`. Hidden dev/test rows are in `out/hidden/` and are read only by
  extraction and scoring. `out/leakage_checks.json` verifies:
  - disjoint IDs and clusters
  - C/T packs drawn only from the pool
  - no target-product mentions in C
  - no 8-gram from any hidden review in any pack
  - no extracted reference span in any pack (after scoring)
- **Packs**:
  - **M**: one neutral sentence.
  - **D**: target landing page plus a feature page (≤1,500 tokens) and one overview page per peer (≤500 tokens).
    Sentences with testimonials, statistics, customer counts, ratings or CTAs are removed by regex.
  - **O**: ≤3 O*NET 31.0 occupations, model-mapped from D only, and ≤4 real task statements each. Core tasks are
    chosen first, ranked by lexical overlap with the D text.
  - **C/T**: 10 pool reviews per source product, ordered by `sha256(seed|kind|product|id)` and requiring nonempty
    prose. Fixed field order, 250-token cap. In C, sentences and alternative-product fields mentioning the target
    are masked.
  - Token counts in the manifest are approximate (chars/4); actual API usage is logged per call.
- **References**: machine-extracted with a frozen rubric (`RUBRIC_VERSION`). Spans must be verbatim substrings of the
  review, and items with invalid spans are dropped and counted. Four test reviews per product are flagged
  `pending_human_review` in `out/reference_audit.jsonl`. Scores are provisional until a person audits them.
- **Judging**: one call per prediction set under an anonymous set ID. The judge never sees the condition, basis IDs or
  evidence, and items are shuffled. The judge returns pairwise 0/1/2 scores. One-to-one matching per review is computed
  in code.
- **Audience**: a regex role-family codebook (`ROLE_FAMILIES`) built from dev and pool titles only. It maps both
  hidden titles and predicted segments. Unmatched titles become `unknown` and are excluded from the denominator.
- **Uncertainty**: within-product paired review bootstrap (`out/bootstrap.json`). This is conditional on the 20 sampled
  reviews and says nothing about other products.

## Product-experience MCP (`ux_mcp_server.py`)

One tool, `predict_experience(product_url, job_title, industry, company_size, time_used, task, previous_product)`.
It classifies the product page into a Capterra category, then returns, for each output, whatever tested best on
held-out products (`router_eval.py`, choices in `out/router/router.json`):

- a ready estimate (people-like-them averages) for overall, value-for-money, support and recommend;
- averages as context for ease, functionality and overall experience in words;
- the full package (averages + competitor complaint rates + similar people's competitor reviews) for cons and unhappy risk;
- nothing for pros (no data beat the agent on dev).

```bash
python experiments/staged_context/router_eval.py      # re-pick strategies on dev products, report on test products
claude mcp add ux-experience -- python experiments/staged_context/ux_mcp_server.py
```

## In UserSim studies (`mvp/review_context.py`)

Production uses **only live Capterra + G2 scrapes of the competitors the study plan names** (Apify:
`trakk/capterra-reviews-scraper`, `automation-lab/g2-scraper`; needs `APIFY_TOKEN`). The FreshCrawl snapshots
here cover arbitrary products and are research data only, never used in studies. Scrapes start in the background
when a study starts and are cached per rival in `cache/apify/`. From them the feedback step gets people-like-this-
persona rating averages, complaint-topic rates and the most similar people's reviews, plus a
`likely_frictions_from_similar_users` field. Observed `friction_points` stay grounded in the recorded steps.
If no scrape is usable, the feedback carries no review evidence and the log says why; nothing is substituted.
Failed scrapes (no credit, network) are not cached, so the next study retries them. Disable with `MVP_REVIEW_CONTEXT=0`.

Known limits (Oct 2026): Capterra lists few AI coding tools (search returns other products, which are dropped);
the G2 scraper returns no job titles and numeric ids for industry and company segment, so role-matching uses
Capterra reviews only.
