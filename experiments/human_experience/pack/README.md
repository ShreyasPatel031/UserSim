# UserSim context + execution evaluation pack

## Start here

This is a **prepared evaluation set and coding-agent handoff**, not measured model performance.

- 36 real Capterra review cases: 12 each for Asana, Trello and ClickUp.
- 18 separate development reviews and 90 separate evidence-review IDs.
- Hidden numeric outcomes supplied; raw reference prose materialized separately from the source.
- 12 neutral task reconstructions for execution, including a 6-case starting subset.
- Phase A tests individual data additions and combinations.
- Phase B tests context × execution engine on the SAME reviewer/task cases.
- Rating scorer included. Model calls, source retrieval and browser/UserSim adapters must use the existing project.

Do not build a new UI or browser harness. Integrate this with existing UserSim and an ordinary execution control.

## 1. What “representative” means here

The set covers **three organization-size bands × two overall-rating bands**, two cases per cell per product:
- solo/small: self-employed or 1–10 employees;
- mid: 11–200;
- large: 201+;
- lower reported satisfaction: overall 1–3;
- higher reported satisfaction: overall 4–5.

This is a deliberately stratified diagnostic sample of three project-management products. It is not representative of all software or all customers.

Half the selected reviews have overall scores 1–3, whereas these are uncommon in the source. Report BOTH:
1. unweighted diagnostic results, exposing negative experiences;
2. inverse-selection-weighted phase-A results, approximating the downloaded 1,000-review frame per product.

Weights and strata live only in evaluator_only. Never tell the predictor whether a case was sampled as positive/negative. Weights do not repair reviewer-selection bias, capped product coverage, historical mismatch, or tiny sample uncertainty.

The 12 execution cases are purposefully selected for clear task descriptions. They are NOT population representative and must not use the phase-A population weights. The six core cases include both rating bands and all three products, but do not cover every stratum.

## 2. Actual files

- `inputs/cases.jsonl`: 36 opaque case IDs, target product/URL and recorded role/industry/company size/tenure.
- `inputs/e2e_tasks.jsonl`: 12 task goals, synthetic fixtures, prerequisites, success criteria and limits. Six have `core_smoke_subset: true`.
- `evaluator_only/outcomes.jsonl`: actual numeric ratings and sampling weights.
- `evaluator_only/task_provenance.jsonl`: source IDs/fields and audit requirements for task reconstruction.
- `evaluator_only/sample_summary.json`: coverage and metric denominators.
- `config/splits.json`: frozen source IDs; test/development/evidence separation.
- `config/experiment.json`: exact experiment cells.
- `config/source.json`: source URL/checksum.
- `CASE_PREVIEW.md`: actual role/task examples without exposing ratings.
- `PREDICTION_SCHEMA.md`: required result format.
- `scripts/prepare_reviews.py`: materializes review text into the right partitions.
- `scripts/score_ratings.py`: computes rating metrics from actual forecasts.

The source profile is recorded context, not a verified identity or a complete persona. Nulls stay null. Do not infer income, budget, personality or technical skill from a role. A long-tenure reviewer is not recreated by telling an agent to behave as an expert.

## 3. Prepare the source

```bash
python scripts/prepare_reviews.py --csv /path/to/capterra_software_reviews.csv
# Or download and verify the source snapshot:
python scripts/prepare_reviews.py
```

Expected: 36 hidden test, 18 development, 90 evidence reviews. Snapshot hash mismatch is a hard stop: retrieve the matching snapshot or rebuild/version the split transparently.

The inspected source CSV can be reused at:
`/workspace/scratch/e13a08970915/research/capterra.csv`
if this workspace is shared. Do not assume that path exists elsewhere.

Do not upload/retrieve the whole CSV into prediction prompts. Split first. Isolate predictor/runner access from evaluator_only. Test prose is for reference extraction and evaluation only.

Use fresh stateless prediction and runner sessions. The coding/evaluator agent may inspect gold files, but its conversation history must never be reused as a prediction prompt. Check actual serialized payloads, not just directory names.

Keep multilingual source reviews; preserve originals and use a single documented translation process for evaluator labels. The language of a review is not proof of the user's preferred interface language.

## 4. Evidence packs

**M:** product name + neutral one-sentence description, no reviews or popularity numbers.

**D:** target landing + one useful documentation/feature page, plus one overview for each of the two peers. Up to 2,500 tokens total. Save passages, identity, URL and capture date. Strip testimonials, ratings and review snippets. Current docs make this a retrospective current-version experiment.

**P:** recorded reviewer role, industry, company-size band and tenure from inputs. This is an explicitly known-context benchmark. Do not assume production callers always supply it.

**O:** real O*NET occupation/task statements. Retrieve up to 12 statements from no more than three plausible occupation matches using only permitted M/D/P. Save occupation/task IDs and the inferred mapping. Cap 1,000 tokens. If role mapping fails, return a missing pack rather than invented task statements.
Source: https://www.onetcenter.org/database.html

**C:** first 10 allowed evidence IDs from each other product, 20 total. Include their review context and text/ratings under a fixed serialization, at most 250 tokens per review. Remove passages naming/comparing the target so the competitor-only stage does not secretly access target experience.

**T:** first 10 allowed evidence IDs for the target, same serialization and cap.

**Q:** one fixed neutral task and synthetic fixture from inputs/e2e_tasks.jsonl. Never pass outcomes or source quotations that reveal positive/negative experience.

Use identical evidence rows/text across all cells containing a pack. C/T may be matched to P later, but fixed rows keep this pilot reproducible. Do not retrieve using a hidden review's text/rating.

This first run adds tokens as it adds data: it measures practical value/cost, not a pure length-controlled effect. Log token counts and truncation. Do not claim that an improvement is independent of longer context.

## 5. Phase A — which information helps prediction?

Predict ease of use, functionality, overall/value ratings and up to three benefits/frictions. Task hypotheses are secondary. No execution and no reconstructed target task is given.

| Cell | Evidence | Purpose |
| --- | --- | --- |
| A0 | M | Plain-model baseline |
| A1 | M + D | Public pages |
| A2 | M + D + P | Known reviewer context |
| A3 | M + D + P + O | O*NET alone above the shared base |
| A4 | M + D + P + C | Competitor reviews alone above the base |
| A5 | M + D + P + T | Target reviews alone above the base |
| A6 | M + D + P + O + C | Occupational + competitor context |
| A7 | M + D + P + C + T | Competitor + target reviews |
| A8 | M + D + P + O + C + T | Full evidence |

“Alone” here means a source added to M/D/P, not a model receiving an isolated review with no product identity.

All 36 cases; same prediction model/schema/settings. A0/A1 lack individual input: cache one forecast per product/cell and score it against each corresponding case rather than fabricating unique personas. Maximum naive calls 324; with that caching, 258 unique prediction calls.

Required contrasts:
- A1−A0 public pages; A2−A1 profile;
- A3−A2 O*NET; A4−A2 competitor reviews; A5−A2 target reviews;
- A6−A4 O*NET with competitors;
- A7−A5 competitors with target reviews;
- A8−A7 O*NET with both review sources;
- A8−A6 target reviews with occupational/competitor context.

Use conditional known-profile results to assess conditioning. They cannot certify top-down audience discovery because the profile was provided.

## 6. Phase B — does actual UserSim execution improve predictions?

Start with the six `core_smoke_subset` cases. If feasible, extend to all 12 without changing prompts. All cells use the same M/D/P/Q for each case.

| Cell | Extra context | Execution |
| --- | --- | --- |
| B0 | None | None: model-only forecast |
| B1 | O + C + T | None: context-only forecast |
| B2 | None | Generic agent |
| B3 | O + C + T | Generic agent |
| B4 | None | UserSim agent |
| B5 | O + C + T | UserSim agent |

The final forecast model always sees the permitted base/context plus the actual trace-derived observations when available. Keep that final model fixed.

Both execution engines receive the SAME permitted evidence, goal, fixtures and action limits within each context condition. Generic means ordinary goal-directed execution without UserSim's persona/simulation machinery; UserSim uses the actual existing implementation. Document the exact configuration difference. If engines use different underlying models/tools, the result is a system-level comparison, not an isolated effect of persona prompting.

**Core workload:** 24 browser runs (6 cases × 2 engines × 2 context levels) and 36 final forecasts. Extended workload: 48 browser runs and 72 forecasts. None of these runs has been performed.

Required contrasts:
- B1−B0: context without execution.
- B3−B1: generic execution added to full context.
- B5−B1: UserSim execution added to full context.
- B5−B3: UserSim versus generic execution with matched information.
- B4−B2: UserSim versus generic without enrichment.
- B5−B4: additional context inside UserSim.
- (B5−B4) versus (B1−B0): does context help differently with execution? Descriptive interaction only in this small sample.

Do not choose “best context” on phase-A test results and then present phase B on the same people as an untouched confirmation. Full context is predeclared here. Any adaptive follow-up needs a fresh test slice.

### Execution controls

- Reset the workspace before EVERY run. Same product plan, fixture and account capabilities.
- Same maximum 5 minutes / 40 actions, unless adjusted for all cells before the first test.
- Use only authorized test identities; no real client invites, purchases or external messaging.
- Record actual plan/version/capture date, blockers, steps, success checks, retries, time and trace.
- Mask condition labels from the final judge where possible.
- Do not show the runner any hidden rating, reference complaint or workaround.
- Never manufacture frustration, delays or errors to match the persona.
- If gated features/account restrictions prevent execution, mark the run blocked. Do not score missing observations as a successful run. Report intent-to-run results with a no-observation fallback and matched successful-run results separately.
- A short fresh-account run cannot recreate years of usage, large organizational adoption or delayed support experiences. Preserve mismatch fields.

Tasks were reconstructed from reported activities. They are not original researcher-issued instructions. The fixtures/success criteria are proposed test conditions, not historical facts. Review and freeze the neutral goals before running; log any edits and rationale.

## 7. Outcomes and scoring

### Primary numerical outcomes
- Ease-of-use score.
- Functionality score.

Secondary: overall satisfaction and value for money. Support/recommendation are recorded but not primary execution outcomes: a brief run rarely measures actual support interaction or willingness to recommend.

Use probability vectors over 1–5, expected-score MAE and ordinal ranked probability score (RPS). Do not compare the agent's completion time directly to star ratings.

```bash
python scripts/score_ratings.py predictions.jsonl --output rating_metrics.csv
```

The scorer reports missing-case completeness and both diagnostic/weighted metrics for complete phase-A conditions. Phase-B results are unweighted purposeful-subset results. Report per product and on paired complete cases. Include abstention/blocked/missing rates so dropping difficult cases cannot create a false win.

Add evidence-only mean/distribution baselines from C and T. These measure whether model/simulation work beats simple review aggregation. Mean baselines may be strong because ratings are concentrated near 4–5.

### Primary qualitative outcomes
Specific benefits and specific friction, extracted from hidden pros/cons/comments with source spans.

Use development rows to freeze the codebook/rubric. The supplied pack does NOT yet contain human-verified qualitative labels. Have a separate evaluator extract up to three explicit claims per type. Audit at least 12 test reviews, four per product, with a real human when available. Otherwise label scores automated/provisional.

Match predictions one-to-one to claims:
- 2 specific semantic match (aspect/object/direction and relevant condition).
- 1 broad/partial match.
- 0 unrelated/generic.
- explicit opposite = disagreement with this reviewer.
- not mentioned = unconfirmed, not proven false.

Report strict reference recall, partial matches, explicit disagreement and unconfirmed rate. Max three predictions per type. References may omit real experiences, and conflicting reviewers can both be truthful. Generic “confusing interface” must not fully match a specific missing-task problem.

Separate:
1. matches to **all review claims** — how well we predict overall reported experience;
2. matches to **claims relevant to the supplied task** — independently marked before predictions are seen.
The Capterra ratings remain review-level even when qualitative claims are task-related.

Judges see anonymous predictions and reference claims, not condition names. Include concrete source-grounded before/after examples in the report. Embedding similarity alone is not an adequate judge.

### Agent-observed outcomes
Completion, steps, time and errors are valuable engineering measurements, but this dataset has no matching human action traces. Do not call these human-behavior accuracy scores.

### Confidence
This sample is too small for per-segment reliability guarantees. Predicted probabilities are forecasts to score, not calibrated confidence. Report paired per-case deltas and product breakdowns. Any bootstrap describes this sampled frame, not arbitrary products. Call mixed/unstable results inconclusive.

## 8. Coding-agent execution order and budget

1. Inspect the existing project and reuse its model/runner integrations.
2. Run prepare_reviews and check test/dev/evidence disjointness.
3. Build cached M/D/P/O/C/T packets with source IDs. Enforce input allowlists; never attach a whole raw case row.
4. Audit task goals and develop extraction/scoring on the 18 development rows.
5. Run one development example to estimate end-to-end cost. Proposed total cap $20, configurable; no paid subscriptions. Include browser/model/judge costs. If credentials or budget block a cell, finish feasible work and report what is blocked.
6. Freeze prompts and run phase A.
7. Run all six phase-B cells for the six core cases before extending to 12.
8. Produce paired metrics, traces, qualitative audits and a concise report.

When reducing cost, keep paired conditions; reduce the declared case subset consistently BEFORE inspecting scores. Do not drop unsuccessful UserSim runs or review-context stages.

Only use observed data. If no runnable UserSim adapter exists, report that integration gap; do not substitute imagined execution.

## 9. Required return package

Return:
- report.md (one-page summary plus examples);
- predictions.jsonl;
- rating_metrics.csv and qualitative_metrics.csv;
- paired_deltas.csv, with exact compared case IDs and denominators;
- packet manifests with source IDs/hashes and model/settings/cost;
- execution manifest and trace references;
- qualitative reference labels with source spans and audit status;
- code/commands used.

First report table: condition, n, ease MAE, functionality MAE, qualitative match, disagreement, missing/blocked rate, cost.

Answer:
1. Which source helped on its own above M/D/P?
2. Which source added nothing or hurt?
3. Did reviews outperform occupational context?
4. Did execution improve predictions beyond context-only?
5. Did UserSim outperform generic execution with the same information?
6. Were gains consistent across products and size/rating groups?
7. Which smallest bundle should be used for which output?
8. What cannot be concluded because of incomplete context, old reviews, small n or judge uncertainty?

The goal is to discover whether UserSim improves prediction of reported customer experience, not to assume it does.

## Preparation checks already completed

Source checksum and frozen IDs verified; 36 test, 18 development and 90 evidence records materialized successfully. No word-5-gram Jaccard >=0.8 duplicates were found between selected test cases or between them and the remaining three-product pool. Test and evidence IDs do not overlap.

All 36 cases have overall, ease-of-use and functionality scores. Value-for-money and customer-support scores are present on 27 cases; recommendation scores on 34. Missing scores remain missing.

The numeric scorer was checked with synthetic perfect forecasts (zero MAE/RPS) and duplicate-record rejection. Those synthetic checks are not model evaluation results and are not included as predictions. No model forecasts, live executions, or human-verified qualitative annotations have been produced.

