# Staged-context pilot: which customer-context data helps?

_Auto-generated tables; interpretation is in the Findings section. All scores are machine-extracted and machine-judged (provisional) unless the audit file says otherwise._

## Results (macro-average over 3 products; mean over replicates)

| Condition | Task recall ↑ | Ease MAE ↓ | Ease RPS ↓ | Benefit/friction recall ↑ | Reference disagreement ↓ | Cost |
| --- | --- | --- | --- | --- | --- | --- |
| S0 (M) | 0.334 | 0.830 | 0.124 | 0.166 | 0.033 | $0.1515 |
| S1 (M+D) | 0.340 | 0.921 | 0.140 | 0.137 | 0.017 | $0.1603 |
| S2 (M+D+O) | 0.239 | 0.918 | 0.140 | 0.118 | 0.028 | $0.1590 |
| S3 (M+D+O+C) | 0.366 | 0.835 | 0.124 | 0.155 | 0.054 | $0.1823 |
| S4 (M+D+O+C+T) | 0.340 | 0.630 | 0.103 | 0.202 | 0.021 | $0.1777 |
| A1 (M+D+C) | 0.247 | 0.756 | 0.112 | 0.158 | 0.042 | $0.1726 |
| A2 (M+D+C+T) | 0.360 | 0.630 | 0.103 | 0.255 | 0.019 | $0.1838 |
| A3 (M+D+T) | 0.396 | 0.630 | 0.103 | 0.305 | 0.014 | $0.1895 |

Task recall = strict (score-2) one-to-one recall per task-bearing review. Reference disagreement = share of (predicted claim × claim-bearing review) pairs judged an explicit contradiction. Cost = prediction + judging for that condition's 3 product calls (extraction shared, reported below).

### Secondary metrics

| Condition | Partial task recall | Sample-confirmed task fraction | Benefit recall | Friction recall | Unconfirmed claim rate | Audience top-3 coverage |
| --- | --- | --- | --- | --- | --- | --- |
| S0 | 0.560 | 0.90 | 0.182 | 0.175 | 0.139 | 0.155 |
| S1 | 0.495 | 0.63 | 0.110 | 0.203 | 0.278 | 0.216 |
| S2 | 0.458 | 0.63 | 0.078 | 0.217 | 0.222 | 0.283 |
| S3 | 0.563 | 0.63 | 0.133 | 0.236 | 0.278 | 0.226 |
| S4 | 0.547 | 0.87 | 0.187 | 0.271 | 0.194 | 0.185 |
| A1 | 0.490 | 0.60 | 0.122 | 0.251 | 0.250 | 0.256 |
| A2 | 0.519 | 0.80 | 0.250 | 0.254 | 0.194 | 0.241 |
| A3 | 0.611 | 0.77 | 0.300 | 0.304 | 0.222 | 0.191 |

### Numeric rating baselines (no model)

| Baseline | Ease MAE ↓ | Ease RPS ↓ |
| --- | --- | --- |
| BASE_C_pack_dist | 0.657 | 0.108 |
| BASE_T_full_pool_dist | 0.621 | 0.096 |
| BASE_T_pack_dist | 0.630 | 0.103 |
| BASE_uniform | 1.417 | 0.224 |

## Paired deltas per product (replicate 1; positive = later condition higher)

| Comparison | Product | Δ task recall | Δ ease MAE | Δ ease RPS | Δ B/F recall | 95% review-bootstrap Δ task recall |
| --- | --- | --- | --- | --- | --- | --- |
| S1−S0 | Asana | -0.237 | 0.150 | 0.019 | -0.166 | [-0.386, -0.096] |
| S1−S0 | Trello | 0.186 | -0.026 | -0.006 | -0.166 | [-0.069, 0.441] |
| S1−S0 | ClickUp | 0.071 | 0.080 | 0.024 | 0.057 | [-0.167, 0.306] |
| S2−S1 | Asana | 0.061 | -0.050 | -0.008 | -0.004 | [-0.120, 0.219] |
| S2−S1 | Trello | 0.029 | -0.046 | -0.010 | 0.025 | [-0.042, 0.115] |
| S2−S1 | ClickUp | -0.226 | -0.100 | -0.029 | -0.049 | [-0.474, 0.000] |
| S3−S2 | Asana | 0.140 | 0.000 | 0.000 | 0.017 | [0.020, 0.281] |
| S3−S2 | Trello | -0.029 | 0.062 | 0.013 | 0.096 | [-0.219, 0.156] |
| S3−S2 | ClickUp | 0.405 | 0.000 | 0.000 | -0.002 | [0.214, 0.615] |
| S4−S3 | Asana | -0.167 | -0.330 | -0.049 | 0.027 | [-0.367, 0.009] |
| S4−S3 | Trello | -0.078 | -0.150 | -0.003 | 0.017 | [-0.267, 0.123] |
| S4−S3 | ClickUp | -0.155 | -0.140 | -0.006 | 0.122 | [-0.441, 0.131] |
| S3−A1 | Asana | 0.272 | 0.220 | 0.024 | -0.029 | [0.150, 0.395] |
| S3−A1 | Trello | 0.353 | 0.046 | 0.012 | 0.092 | [0.185, 0.537] |
| S3−A1 | ClickUp | 0.095 | -0.020 | -0.006 | -0.035 | [-0.048, 0.267] |
| S4−A2 | Asana | -0.114 | 0.000 | 0.000 | 0.017 | [-0.206, -0.026] |
| S4−A2 | Trello | -0.196 | 0.000 | 0.000 | -0.291 | [-0.369, -0.033] |
| S4−A2 | ClickUp | 0.048 | 0.000 | 0.000 | 0.009 | [-0.131, 0.256] |
| A2−A3 | Asana | 0.167 | 0.000 | 0.000 | 0.014 | [0.055, 0.298] |
| A2−A3 | Trello | -0.078 | 0.000 | 0.000 | -0.010 | [-0.324, 0.146] |
| A2−A3 | ClickUp | -0.214 | 0.000 | 0.000 | -0.023 | [-0.500, 0.095] |

## Replicate variability (macro task recall / ease MAE per replicate)

- S0: task recall 0.314, 0.355; MAE 0.813, 0.847
- S1: task recall 0.321, 0.359; MAE 0.881, 0.960
- S2: task recall 0.275, 0.202; MAE 0.816, 1.020
- S3: task recall 0.447, 0.284; MAE 0.837, 0.833
- S4: task recall 0.314, 0.365; MAE 0.630, 0.630
- A1: task recall 0.207, 0.287; MAE 0.755, 0.757
- A2: task recall 0.402, 0.318; MAE 0.630, 0.630
- A3: task recall 0.444, 0.349; MAE 0.630, 0.630

## Denominators

- Asana: task-bearing reviews 19/20, rated reviews 20, claim-bearing 20, audience-evaluable titles 17
- Trello: task-bearing reviews 17/20, rated reviews 20, claim-bearing 20, audience-evaluable titles 14
- ClickUp: task-bearing reviews 14/20, rated reviews 20, claim-bearing 20, audience-evaluable titles 17

## Examples (auto-selected; audit before relying on them)

**Improvements** (137 reference tasks changed strict-match status across comparisons)
- Asana, S0 → S1 (pack difference: D): before `no strict match in S0`; after `Manage | workloads and resource allocation | - | for team members to balance capacity`; hidden review span: "managing our project resources"
- Trello, S1 → S2 (pack difference: O): before `no strict match in S1`; after `Organize | daily to-dos | - | for personal or team accountability`; hidden review span: "organize and execute multiple projects and to-do lists while collaborating with other team members"
- ClickUp, S2 → S3 (pack difference: C): before `no strict match in S2`; after `Search and consolidate | information | across connected apps and documents | find relevant data from a single platform`; hidden review span: "manejar todo en un solo lugar"
**Regressions** (123 reference tasks changed strict-match status across comparisons)
- Asana, S0 → S1 (pack difference: D): before `Create and assign | tasks | to team members | to distribute workload and responsibilities`; after `no strict match in S1`; hidden review span: "assign work to colleagues with deadlines to keep a project moving along"
- Trello, S1 → S2 (pack difference: O): before `Track | task progress | by adding due dates and marking cards as 'Done' | to monitor deadlines and completion status`; after `no strict match in S2`; hidden review span: "managing in progress work"
- ClickUp, S2 → S3 (pack difference: C): before `Track work items | project progress | with assignees and due dates | to manage project progress`; after `no strict match in S3`; hidden review span: "track the workflow every day"

## Cost and errors

- Total uncached model spend: $9.3459 (onet_map $0.1263, predict $0.6089, extract $1.4947, judge $6.1428, matched_screen $0.9732)
- Prediction model: gemini-2.5-flash (temperature 0.7); judge/extractor: gemini-2.5-pro
- Valid predictions: 48/48; call errors logged: 26 (by stage: {'judge': np.int64(24), 'predict': np.int64(2)}); judge sets still failed after rerun: 0

## Leakage checks

```
{
  "review_ids_disjoint": true,
  "clusters_disjoint": true,
  "packs_only_from_pool": true,
  "no_target_reviews_or_mentions_in_C": true,
  "no_hidden_8gram_in_packs": true,
  "no_reference_spans_in_packs": true
}
```
