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
