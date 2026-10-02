# SimBench divided questions: where is the error, and what are the biggest levers? — exploratory analysis

Run of the exploratory-analysis spec. **No new model calls**: logged runs only. Haiku 4.5 unless stated. Eval 981 / dev 380 (seed 7). Divided = normalized entropy ≥ 0.84. Scores are SimBench S. Paired bootstrap 95% CIs. `*` = N < 30. Pop-only task datasets (OSPsychMACH, Choices13k, NumberGame, OSPsychMGKT) are reported separately throughout.

## The 3 biggest levers

| Rank | Lever | Ceiling on divided shared-survey questions (eval, baseline 43.0) | Signal available before the answer? |
|---|---|---|---|
| 1 | **Fix the placement for the whole population** (the question-level error) | **+21.8** if only the placement is fixed (64.8). **+39.3** if the error shared across subgroups is removed (Step C cell set). Dev: +28.0 | **No.** The direction of the error is not predictable from question features (AUC 0.52–0.57). Needs new information, e.g. a question-level anchor; the earlier diagnostic arm got +30.7 from one |
| 2 | **Route each question to the best existing harness** | **+24.6** oracle (67.6). This is inflated by picking the best of 7 noisy predictions | **Weak.** A router fitted on dev realises **+3.2** on divided shared questions but **−1.6** overall. Bad questions are detectable only weakly (AUC 0.61 divided, 0.67 overall) |
| 3 | **Larger model for `retr6`** | Realised, not an oracle: **+11.9 [+3.3, +20.3]** with Sonnet 4.6 and **+11.2 [+2.8, +20.1]** with Sonnet 5.5 (dev divided shared, N 69). Best-of oracle +24.5 | **Yes**, just use it. Caveat: dev only, and the best divided Haiku harness scores the same as Sonnet's (43.8 vs 43.7), so the gain is for the simple harness |

**Separately, Pop-only task datasets:** the segments harness alone realises **+25.4 [+11.7, +39.1]** over `retr6` both orders (24.3 vs −1.2, N 58). Fixing only the over-confidence (oracle entropy) would give +37.9.

![Headroom per lever](img/eda_headroom.png)

## What the analysis says, in one paragraph

On divided survey questions, no question feature explains much of the error. The best single dimension (topic) explains 6.8% of the variance, and **country explains none** once corrected for its 55 levels. No subgroup stands out after removing the error shared across groups (permutation p = 0.48). Different models share their hard questions only partly (per-question error correlation 0.60–0.74). The error is mostly a question-level misplacement that is invisible to every feature we can compute before the answer. The levers that work at prediction time are a bigger model for the simple harness, the segments harness on task datasets, and modest routing. The big remaining gain (+22 to +39) needs real information about the question itself.

## Step 1 — analysis table

`results/simbench_ablate/divided_eda_table.csv` (and `.pkl` with full distributions). 12,406 rows = 1,361 questions × logged arms.

| Set | Haiku arms | Other models |
|---|---|---|
| Eval | base, retr6, retr6_rev2, panel, P_adapt, B_n3_soft, B_n3_soft_rev2 | Gemini Flash retr6 |
| Dev | same 7 Haiku arms, plus panel reversed and grounded segments (both orders) | Sonnet 4.6, Sonnet 5.5, Gemini Flash (retr6) |

Questions: eval 329 consensus / 324 mixed / 328 divided; dev 114 / 139 / 127.

Columns:
- **Outcomes:** S, TVD, top option right, polarity flip (ordinal only), true and predicted entropy, residual on the textbook option.
- **Population:** country, region, survey year, subgroup attribute and value.
- **Question features:** number of options, scale type, has "don't know", question length, topic cluster, value-laden flag and textbook option.
- **Demo features:** recomputed `retr6` demos, deterministic and with no calls. Includes mean TF-IDF similarity, mean demo entropy, and option-aligned demos. The aligned-average TVD to truth is a truth-using diagnostic.
- **Model behaviour:** order sensitivity (TVD between the two option orders), harness disagreement (`retr6` vs panel), model disagreement (Haiku vs Gemini).

**Topic clusters:** k-means on question-stem embeddings, using cached vectors only (no calls) where available. TF-IDF k-means otherwise; the method per dataset is recorded in the report.

**Value-laden rule:** a documented keyword list on the question stem and option texts only (full rule in `divided_eda_report.json` and the code). Checked against the 50 hand-coded questions from Appendix B:
- Flag: 21 true positives, **0 false positives**, 2 false negatives.
- Same textbook option set where both flag: 15 / 21.
- Coverage: 15% of divided eval questions are value-laden.

**Not logged, so skipped on eval:** panel in both orders and the best divided mix (dev only); Sonnet models (dev only). Gemini is the only second model on eval.

## Step 2 — where the error concentrates

### Variance decomposition (per-question TVD, divided)

Each dimension alone: R² and **adjusted R²** (penalised for the number of levels). Joint: OLS with all dimensions as dummies; unique share = joint adjusted R² minus joint-without-this-dimension.

**Shared surveys, eval, `retr6_rev2`, N 175** (joint R² 0.72, adjusted 0.30):

| Dimension | Levels | Alone R² | **Alone adjusted R²** | Unique adjusted R² |
|---|---|---|---|---|
| topic | 16 | 0.148 | **+0.068** | +0.042 |
| n_options | 9 | 0.098 | +0.054 | +0.150 |
| sub_attribute | 21 | 0.147 | +0.036 | +0.078 |
| scale_type | 3 | 0.037 | +0.026 | +0.093 |
| value_laden | 2 | 0.018 | +0.012 | −0.006 |
| dataset | 5 | 0.034 | +0.011 | 0.000 |
| split | 2 | 0.001 | −0.005 | +0.007 |
| year | 11 | 0.052 | −0.006 | +0.021 |
| region | 5 | 0.011 | −0.013 | 0.000 |
| **country** | 55 | 0.288 | **−0.032** | +0.175 |

The panel (eval, N 175) ranks the dimensions similarly: n_options +0.118, scale_type +0.084, dataset +0.035, topic +0.026; country again −0.019. Dev (`retr6_rev2`, N 69): n_options +0.192, scale_type +0.160, topic +0.096, country +0.017.

**Pop-only tasks** (eval, N 58): topic +0.314, country +0.181, dataset +0.151. Here the error is strongly task-driven.

**Reading:**
- **Format matters a little:** ordinal scales and particular option counts are harder.
- **Topic matters a little.**
- **Country explains nothing on its own.** Its large raw R² is overfitting from 55 levels on 175 questions. Its "unique" share in the joint model is unstable for the same reason and should not be read as an effect.
- **Most of the variance is question-specific.**

### Slices (worst levels, eval, divided shared surveys, `retr6_rev2`)

| Dimension | Worst levels (S, N, flip rate) |
|---|---|
| dataset | LatinoBarometro 32.3 (64, 0.21); ISSP 45.6 (46, 0.13); ESS 49.0 (56, 0.06) |
| scale type | ordinal 38.2 (101, 0.16); categorical 48.3 (23*); binary 50.2 (51) |
| n options | 3: 8.5 (8*); 4: 33.0 (40); 5: 44.6 (50) |
| value-laden | yes 35.5 (49, 0.17); no 45.9 (126, 0.16) |
| country | Venezuela −18.5 (6*, 0.67); Guatemala 4.7 (3*); Peru 8.9 (3*). All N < 10 |
| survey year | 2023 (mostly LatinoBarometro) 33.8 (67, 0.23); 2017–2020 48.3 (36) |

Pop-only tasks: OSPsychMGKT −20.2 (6*), NumberGame −10.0 (13*), OSPsychMACH 2.4 (24*, flip 0.33), Choices13k 8.6 (15*). Full lists: `divided_eda_report.json` → `slices`.

![Worst levels per dimension](img/eda_slices.png)

### Group-level view (subgroups, shared vs group-specific error)

Source: the Step C cell run (430 subgroup cells, 52 questions with ≥ 2 cells scored).

- **Mean shared error:** TVD 0.177. **Mean group-specific error:** 0.065.
- **Worst group by group-specific error:** ESS Germany age 65+, 0.128 (N 3*). The 95th percentile of the maximum under within-question label shuffling is 0.145, giving **permutation p = 0.48**. **No group stands out**: the remaining error is flat across groups.
- **By attribute** (N ≥ 10): religion 0.122 (12*), marital status 0.079 (30), age 0.067 (127), education 0.060 (56), domicile 0.046 (121).

![Shared vs group-specific error](img/eda_group_scatter.png)

### Cross-model overlap

| Set | N | Per-question TVD correlation | Worst 20% shared by all models |
|---|---|---|---|
| Dev divided (Haiku, Sonnet 4.6, Sonnet 5.5, Gemini) | 127 | Pearson 0.61–0.74; Spearman 0.52–0.69 | 7 / 25 (28%) |
| Eval divided (Haiku, Gemini) | 328 | 0.60 | 33 / 65 (51%) |

Hard questions are partly shared across models. The overlap is moderate, so model choice or combination can help on some questions.

## Step 3 — headroom per lever (divided, eval; ceilings are labelled)

| Lever | Shared surveys (N 175) | Pop-only tasks (N 58*) | Other Pop-only (N 95) | Available at prediction time? |
|---|---|---|---|---|
| Baseline `retr6` both orders | 43.0 | −1.2 | 43.7 | yes |
| Best single Haiku harness | 46.4 (segments both orders; +3.4 [−1.3, +8.1]) | **24.3** (segments; **+25.4 [+11.7, +39.1]**) | 46.6 (panel) | yes |
| A. Router fitted on dev | 46.2 (+3.2) | – | – | yes (but −1.6 on all questions) |
| A. Best harness per question | 67.6 | 51.0 | 64.9 | ceiling |
| B. Average of the model's own aligned demos, used as the prediction | 27.7 vs model 46.2 (N 114) | 23.3 vs −1.2 | 32.8 vs 46.5 | yes |
| B. Best average of ≤ 6 aligned pool demos | 80.2 vs model 46.5 (N 121) | 90.8 | 73.4 | ceiling (selection uses the answer) |
| C. Fix placement only | 64.8 | 39.5 | 65.1 | ceiling |
| D. Fix top option only | 55.8 | 31.9 | 54.8 | ceiling |
| E. Fix order bias (best of the two orders and their average) | 50.1 | 13.5 | 49.8 | ceiling |
| F. Remove the shared error (Step C cell set, 430 cells) | 41.0 → **80.3** | – | – | ceiling |
| G. Gemini Flash `retr6` (eval) | 44.8 (+1.8 [−2.7, +6.5]) | −1.5 | 40.5 | yes |
| G. Best of Haiku and Gemini | 55.4 | 15.9 | 55.6 | ceiling |
| H. Fix entropy only (match the true entropy) | 51.6 | 36.7 | 56.6 | ceiling |

**Dev repeats** (divided shared surveys, N 69, baseline 37.8):

| Lever | Score |
|---|---|
| Fix placement | 65.8 |
| Fix top option | 56.8 |
| Fix entropy | 47.9 |
| Best Haiku harness per question (oracle) | 62.4 |
| Sonnet 4.6 `retr6` | **49.7** |
| Sonnet 5.5 `retr6` | **49.0** |
| Best of Haiku, Sonnet 4.6 and Sonnet 5.5 | 62.3 (oracle) |
| Best divided mix (§4.10) | 46.1 |

**B in detail:**
- 69% of divided shared questions have option-aligned demos in the pool.
- Haiku moves away from the plain demo average in 91% of cases, and the move helps 65% of the time.
- For Pop-only tasks the move helps only 36% of the time, so averaging the aligned demos there (23.3) beats the model (−1.2).

## Step 4 — can the error be predicted before seeing the answer?

Models are trained on dev (all question types) using only prediction-time features, then applied unchanged to eval. Features: number of options, question length, demo similarity and entropy, aligned demos, order sensitivity, harness and model disagreement, predicted entropy and top mass, dataset, split, scale type, "don't know", value-laden, region.

| Target | Eval set | N | Positive rate | AUC logistic | AUC GBM |
|---|---|---|---|---|---|
| Polarity flip (ordinal) | divided | 167 | 0.19 | 0.61 [0.48, 0.74] | 0.59 [0.47, 0.70] |
| Polarity flip (ordinal) | all | 393 | 0.16 | 0.62 [0.55, 0.69] | 0.64 [0.56, 0.72] |
| Bad question (TVD > 0.30) | divided | 328 | 0.13 | 0.61 [0.52, 0.69] | 0.59 [0.49, 0.67] |
| Bad question (TVD > 0.30) | all | 981 | 0.17 | 0.63 [0.59, 0.68] | **0.67 [0.63, 0.71]** |
| Error toward the textbook option | divided value-laden | 50 | 0.54 | 0.57 [0.39, 0.75] | 0.52 [0.36, 0.68] |
| Error toward the textbook option | all value-laden | 108 | 0.58 | 0.55 [0.46, 0.67] | 0.50 [0.38, 0.60] |

**Top features:**
- For bad questions: predicted top-option mass (over-confidence), model disagreement, harness disagreement, entropy of the aligned demos.
- For flips: predicted entropy, demo entropy, question length.

**Reading:**
- **Bad questions are weakly detectable,** mostly from the model's own confidence and from disagreement between harnesses or models.
- **Flips on divided questions are barely detectable** (the CI includes 0.5).
- **The direction of the error is not predictable at all.**

So the misplacement itself cannot be fixed from question features. The route is new information (a question-level anchor), plus using disagreement as a flag.

## Strongest counter-reading

- **Some ceilings are optimistic by construction.** The best harness per question picks the best of 7 noisy predictions. The best demo average selects demos using the answer. Fixing only the shared error uses the true mean. They rank levers; they are not results.
- **The larger-model gain is dev-only and small-N** (69 questions, CI +3 to +20). It applies to the simple `retr6` harness, not to the best divided harness.
- **The variance decomposition is underpowered for many-level dimensions** (55 countries, 21 attributes on 175 questions). Adjusted R² protects against over-reading. "Country explains nothing" means "no detectable country effect at this N", not "zero".
- **The Step C cell set is ESS-heavy,** and its results (group view, ceiling F) come from a different sample than eval.
- **Value-laden coding is keyword-based.** It is precise against the hand codes but misses some items.

## Cost and files

- **Cost:** no model calls; $0.
- **Code:** `src/human_sim/simbench_divided_eda.py`.
- **Results:**
  - `results/simbench_ablate/divided_eda_table.csv` and `.pkl`
  - `divided_eda_report.json`: variance decomposition, slices, group view, cross-model overlap, headroom, predictability, CIs, value-laden rule
- **Plots:** `docs/experiments/img/eda_headroom.png`, `eda_slices.png`, `eda_group_scatter.png`.
