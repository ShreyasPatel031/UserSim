# Coding-agent handoff: which customer-context data helps?

## Objective and scope

Implement and run a small staged-input experiment. Report which evidence improves predictions against the SAME held-out Capterra reviews.

Do not assume O*NET helps. Do not remove the competitor-review or target-review stages. Do not build a website, browser runner, CRM connector, or general simulation framework. Use the existing model client if available.

**Size:** 3 products, 60 hidden reviews, 8 input conditions, **24 product-level prediction calls** for the first pass, plus extraction/judging. Optional second repetition: 48 prediction calls total. This is a diagnostic pilot, not proof of generalization.

Return a report and reproducible artifacts to the user so they can bring them back for analysis. Report actual failures and missing data; never invent results.

## 1. Data and actual columns

Use [FreshCrawl Capterra](https://huggingface.co/datasets/FreshCrawl/capterra-b2b-software-reviews). Resolve the CSV from the repository file listing; record its filename/revision/SHA256. This chat inspected a 56,606-row, 66-product snapshot with 1,000 rows each for **Asana, Trello and ClickUp**. Verify your downloaded snapshot.

If sharing this workspace, the inspected CSV is at:
`/workspace/scratch/e13a08970915/research/capterra.csv`.
That local file is not guaranteed to exist in another agent environment.

Actual relevant columns:
`review_id, product_name, review_date, overall_rating, ease_of_use_rating, pros, cons, general_comments, reviewer_job_title, reviewer_company_size, reviewer_industry, reviewer_time_used_product, alternatives_considered, switched_from, reasons_for_choosing, reasons_for_switching, review_url`.

Public product pages:
- https://asana.com/
- https://trello.com/
- https://clickup.com/

Occupation source:
- https://www.onetcenter.org/database.html
- Task Statements, occupation titles/alternate titles; Task Ratings optional for this pilot.

If credentials, network, or a dataset are unavailable, complete the runnable parts, identify exactly what is blocked, and supply the command needed to resume. Never quietly substitute generated reviews or invented occupational rows.

## 2. Freeze split before retrieval or prompt tuning

Use seed 42 and deterministic hashing, not Python's process-dependent hash.

1. Normalize review prose: Unicode normalization, lowercase, whitespace collapse across pros/cons/general comments/choice/switch reasons.
2. Remove exact duplicate nonempty prose. Detect near duplicates (e.g. word 5-gram Jaccard >= 0.85); keep duplicate clusters in a single partition or retain one representative. Do not cluster blank reviews as identical evidence.
3. Within each product, sort by SHA256 of `42|product_name|review_id|normalized_text`.
4. First 5 rows = development; next 20 = test; all remaining rows = evidence pool.
5. Freeze IDs/checksums in `splits.json`. Do not select test reviews because they make the model look good or contain convenient task labels.
6. Exclude ALL development/test rows globally from retrieval, including when a product becomes a competitor.
7. Use the three products as mutual peers; for each target, the other two are competitors.

This is a random retrospective test. Do not call it a historical forecast; today's docs may differ from review-time behavior. Public-model memorization remains unresolved.

**Prediction unit:** one product-level forecast for a new reviewer from this dataset's sampling frame. Do not make 20 identical calls pretending to know 20 different people. Do not give predictors hidden reviewer roles, industries, tasks, ratings, or text.

## 3. Build fixed evidence packs

Prepare/cache these ONCE per target before test scoring:

**M — minimal seed:** product name + one neutral sentence describing category/basic function. No ratings, customer quotes or audience statistics.

**D — public pages:** target landing + one relevant feature/docs page; one overview page per competitor. Keep target/peer identity, URL, capture date and passages. Exclude testimonials, embedded review scores, and customer-count claims. Cap about 1,500 tokens for target + 500 per peer.

**O — occupational evidence:** derive at most 3 plausible occupations from D, without inspecting test reviews. Retrieve at most 4 real O*NET task statements per occupation. Store occupation/task IDs, original text and mapping rationale. Cap 1,000 tokens. Mapping is inferred; source tasks are observed occupational data.

**C — competitor reviews:** 10 evidence-pool rows from each of the two peers, chosen deterministically, independent of hidden outcomes. Use role/industry/size when populated, pros/cons/comments, reasons and ratings. Preserve product identity. Remove/mask passages explicitly discussing the target product for a strict no-target-review condition. Do not use the target test review as a retrieval query.

**T — target reviews:** 10 evidence-pool target rows, deterministic. Same fields/format as C.

For C/T, cap each review at 250 tokens using the same field ordering/truncation rule. Record truncation. Use identical selected rows/text in every condition containing that pack. Increase model context if needed; do not silently truncate older packs when new ones are added.

Record actual tokens and total pipeline costs. This first run measures the practical value of adding data, not a perfectly token-matched causal effect. Do not claim length-independent gains without a later control.

## 4. Required input conditions

All conditions include M.

| ID | Inputs beyond M | Comparison answered |
| --- | --- | --- |
| S0 | None | Plain-model baseline |
| S1 | D | Do public product/competitor pages help? |
| S2 | D + O | Does occupational context add value before reviews? |
| S3 | D + O + C | Do competitor experiences add value? |
| S4 | D + O + C + T | Do some target-product reviews add value? |
| A1 | D + C | Is O*NET useful once competitor reviews exist? Compare S3 vs A1 |
| A2 | D + C + T | Is O*NET useful with both review sources? Compare S4 vs A2 |
| A3 | D + T | Can target reviews alone replace the other enrichments? Compare A2 vs A3 for competitor addition |

This preserves the staged experiment AND tests missing-data combinations. Known-person history is out of scope because we do not have it. Do not synthesize that stage.

Use the same model/version, instructions, decoding policy, output schema and limits. Start with one repetition; add a second for all conditions if affordable. Log supported provider seeds/settings. No prompt tuning after seeing test scores.

## 5. Prediction output

One JSON per product × condition × repetition:

```json
{
  "product": "Asana",
  "condition": "S0",
  "replicate": 1,
  "segments": [
    {"role_family": "string", "motivation": "string", "basis_ids": []}
  ],
  "tasks": [
    {"action": "string", "object": "string", "context": "string or null", "purpose": "string or null", "basis_ids": []}
  ],
  "benefits": [
    {"aspect": "string", "claim": "string", "basis_ids": []}
  ],
  "frictions": [
    {"aspect": "string", "claim": "string", "basis_ids": []}
  ],
  "ease_of_use_probabilities_1_to_5": [0.1, 0.1, 0.2, 0.3, 0.3],
  "unknowns": []
}
```

The numbers above illustrate the schema only. Require up to 3 segments, exactly 5 distinct task hypotheses, up to 3 benefits and 3 frictions; allow explicit null/abstention rather than forced invented claims. Null tasks count as missed coverage. Validate probabilities sum to 1 and lie in [0,1].

Prompt: predict what this product's reviewers are likely to report using it for and experiencing, based only on the attached evidence and general model knowledge. Product-level segments are hypotheses. Do not pretend to know a specific test person or an actual market distribution. Never produce a fake first-person testimonial.

## 6. Hidden reference extraction

A separate evaluator can access test reviews. Prediction calls cannot.

From each test review, extract:
- At most 3 explicit tasks, each with action/object/context/purpose and a verbatim evidence span.
- At most 3 explicit benefits and 3 explicit friction claims with spans.
- Ease-of-use rating if present and valid.
- Reviewer role/industry/size as recorded, preserving missing values.

Do not infer a task from a bare job title. Do not label “great software” a specific task. “No cons” is not proof all possible friction is absent. Record taskless reviews and exclude them only from task-recall denominators, not the whole test.

Draft the extraction rubric using development rows and freeze it. Automated extraction is acceptable for a pilot, but label references machine-extracted unless human audited. Prepare a small audit file for 12 test reviews, four per product. Human verification should check source spans and missed/unsupported claims. If no human audit is available, report automated/provisional scores, not human-validated scores. Never ask the coding agent to impersonate a human annotator.

## 7. Scoring

Keep metrics separate; no combined alignment score.

### Primary A: task coverage

Against each task-bearing test review, match the product's five predictions to reference tasks one-to-one:
- 2 = same action/object and compatible material context/purpose.
- 1 = correct broad task but misses distinguishing context.
- 0 = unrelated/generic/incompatible.

“Manage projects” does not receive full credit for “collect client approval before publishing.”

Strict recall for a review = number of score-2 reference matches / reference task count. Average over eligible reviews within product, then equally over products. Also report partial-match recall separately, task-bearing n, and null/abstention count.

Secondary: fraction of five predicted tasks receiving any strict match in that product's test set. Call this **sample-confirmed task fraction**, not universal precision. Unconfirmed tasks may still occur outside the sample.

### Primary B: ratings

Expected ease score = sum(k × p[k]) for k=1..5. Compare to each held-out ease score:
- MAE.
- Ranked probability score: sum over k=1..4 of (predicted cumulative probability through k − indicator[observed rating <= k]) squared, divided by 4.

Macro-average by product. Report rating denominators. Same product forecast is scored against all its test reviews; there is no person-specific prediction claim.

Add simple numeric baselines: competitor-evidence mean/distribution for C conditions and target-evidence mean/distribution for T conditions. A model that only reproduces a review average may not add value beyond aggregation.

### Secondary: qualitative experience and audience

Use the same 0/1/2 matching rubric for benefits/friction. Report strict reference recall, explicit contradiction rate and unconfirmed rate per comparison. Unmentioned is not false; opposing experiences across different reviewers are heterogeneity, not necessarily a globally false claim. Report contradictions as disagreement with individual reference reports.

For audience, define a small role-family codebook on development/evidence data only. Map hidden job titles separately with unknown/ambiguous labels. Report top-3 role-family coverage among evaluable test titles; no demographics or population-size claim. Keep this secondary because role normalization and small samples are noisy.

### Judge controls and uncertainty

A judge gets randomized anonymous prediction sets and the same reference claims, never stage names or evidence volume. Use fixed rubric/schema; cache judgments. Prefer a separate judge model if already available, but that alone does not validate it.

Audit all apparent biggest wins and contradictions; prepare side-by-side excerpts for human inspection. Do not use embedding similarity or ROUGE as the sole semantic score.

Report paired deltas per product. Optional within-product review bootstrap gives conditional sampling intervals; it does NOT turn three products into broad product-generalization evidence. Show replication variability when available. Call mixed results inconclusive. No calibrated reliability percentages from this pilot.

## 8. Minimal implementation

Prefer a small Python script/module with commands equivalent to:
```bash
python experiment.py prepare --seed 42
python experiment.py predict --conditions all --repetitions 1
python experiment.py score
python experiment.py report
```

Use existing model configuration/environment variables; never expose keys in logs. Save request hashes, model/settings, tokens, elapsed time and stage errors. Keep prediction execution isolated from test label files. Add concrete leakage checks: no overlapping review/duplicate-cluster IDs; no target reviews in competitor packs; no reference spans in prediction packs.

Before the full run, run one development product through S0 and S4 to validate schema and estimate cost. Default proposed spend cap: $10; configurable lower. If projected cost exceeds the cap, use an available cheaper model or pause the model calls with an estimate. Keep all 8 conditions and 3 products when reducing repetitions; do not drop review stages to save effort. Include judges/extraction in the estimate.

## 9. Report back — required deliverables

Create:
- `report.md` — short findings, table, examples, limitations.
- `metrics.csv` — product/condition/replicate metrics, denominators, cost/time.
- `predictions.jsonl` — actual structured outputs.
- `splits.json` — IDs, seed, duplicate handling, source checksum.
- `evidence_manifest.json` — source URLs/IDs, pack hashes, truncation/missingness.
- `reference_audit.jsonl` — extracted spans and audit status.
- Minimal runnable code and README.

The report's first table:
| Condition | Task recall ↑ | Ease MAE ↓ | Ease RPS ↓ | Benefit/friction recall ↑ | Reference disagreement ↓ | Cost |
| --- | --- | --- | --- | --- | --- | --- |

Then explicitly answer:
1. Did public pages help? S1−S0.
2. Did O*NET help before reviews? S2−S1.
3. Did competitor reviews help? S3−S2.
4. Did target reviews help? S4−S3.
5. Did O*NET still help with reviews? S3 vs A1 and S4 vs A2.
6. Did competitors add value once target reviews existed? A2 vs A3.
7. Which smallest evidence bundle performed best for EACH output?
8. Were gains consistent across the three products or driven by one?
9. What was blocked, machine-judged, unconfirmed, or inconclusive?

Include 3 concrete improvements and up to 3 regressions if present: predicted claim before/after, source pack that changed, and matching hidden review excerpt. Do not invent examples when no improvements/regressions exist.

Finish with a compact recommendation: **keep / drop / collect more evidence** for each data source, separately for tasks, audience, and experience. Report observed differences; do not assume richer data wins.

No browser run or UI work until this report exists. Afterward, export the best-supported task output as an Atelier task brief; integration is a separate next step.

