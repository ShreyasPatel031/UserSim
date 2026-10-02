# SimBench: where is the divided-question error, and is it within or across demographics? — results

Run of the follow-up spec to `simbench_failure_mode_spec.md`. Haiku 4.5 only, same setup as `simbench_distribution_injection.md` (eval 981, dev 380, seed 7; consensus < 0.65 ≤ mixed < 0.84 ≤ divided; both option orders; demos never share the target's question; paired bootstrap 95% CIs). Shared surveys = Afrobarometer, ESS, ISSP, LatinoBarometro, OpinionQA. Pop-only task datasets (OSPsychMACH, Choices13k, NumberGame, OSPsychMGKT) are reported separately.

## Verdict (short)

1. **Divided-ness is within groups, not across them.** About 1.4% of the real disagreement on divided questions is between demographic subgroups; about 98.6% is inside each subgroup.
2. **The model's error is mostly common to all groups.** Errors of different groups on the same question correlate at +0.66, and 72–80% of the error is shared. The model gets the direction of group differences right (sign 74–77%) but understates their size (about two thirds).
3. **What goes wrong is placement, not spread.**
   - The spread is right (SD 0.309 vs 0.311 real; entropy gap ≈ 0).
   - Errors go both ways along the scale, with no overall shift toward the middle or "don't know".
   - About 1 in 6 predictions puts the top answer on the wrong side of the scale.
   - The worst cases are complete flips toward a "textbook" answer: the factually correct, rational, liberal or civic one.
4. **The missing information is a question-specific anchor.** Changing where the demos come from (same topic, same group) does not help divided questions. Showing other groups' real answers to the same question (diagnostic only) adds about +30.

## Step A — within vs between groups (no model calls)

Source: every question × country × attribute in the Grouped split with ≥ 2 single-attribute cells of ≥ 100 respondents (1,996 groups). Cells are large: 5th percentile 321 respondents, median 536, so no cell was excluded. H(pop) = mean within-group entropy + between-group Jensen–Shannon divergence. Noise floor: each cell redrawn 200× from the pooled distribution at its own size.

| Question type | N groups | Between-group share of entropy | Net of sampling noise | 90th percentile |
|---|---|---|---|---|
| **Divided** | 596 | **1.4%** | 1.3% | 2.8% |
| Mixed | 716 | 2.3% | 2.1% | 4.3% |

| Divided, by dataset | N | Between share |
|---|---|---|
| ESS | 241 | 2.0% |
| LatinoBarometro | 211 | 0.4% |
| ISSP | 129 | 1.8% |
| OpinionQA | 11 | 3.8% |
| Afrobarometer | 4* | 0.4% |

Most divisive attributes (divided, N ≥ 15): religion 5.2% (33), main activity 4.7% (36), age 2.3% (81), marital status 1.8% (40).

**Reading:** "within-group share is large". Within one demographic split, each group is itself divided. Caveat: only single attributes are available (no intersections), and the country is fixed. Differences between countries are not part of this measure.

## Step B — error anatomy (logged eval runs, no new calls)

Divided eval questions: shared surveys 175 (101 ordinal), Pop-only tasks 58, other Pop-only 95. Positions run from the first-listed option (0) to the last (1). A positive shift means toward the later-listed end; polarity flips do not depend on direction.

| Shared surveys, divided (N 175) | `retr6` | `retr6_rev2` | Panel |
|---|---|---|---|
| S | 40.3 | 43.0 | 45.4 |
| Top option right | 0.57 | 0.54 | 0.51 |
| Entropy gap (pred − true) | −0.02 | −0.01 | +0.02 |
| Mean signed scale shift | +0.02 | +0.01 | +0.02 |
| Mean absolute scale shift | 0.11 | 0.10 | 0.09 |
| SD pred / true | 0.303 / 0.311 | 0.309 / 0.311 | 0.329 / 0.311 |
| **Polarity flip rate** | 0.21 | **0.16** | 0.24 |
| "Don't know" mass pred / true | 0.031 / 0.030 | 0.035 / 0.030 | 0.028 / 0.030 |
| Middle-option mass pred / true (N 45) | 0.20 / 0.21 | 0.20 / 0.21 | 0.19 / 0.21 |
| Categorical (N 74): residual on true top | −0.04 | −0.05 | −0.07 |

- **Signed residual by scale position** (`retr6_rev2`, ordinal, 5 bins from first- to last-listed): −0.000, −0.004, −0.013, −0.009, +0.031; "don't know" −0.005. All small, so there is no systematic piling onto the middle or onto "don't know".
- **Top-option confusion:** mostly adjacent misses (e.g. true bin 3 → predicted 4, 10 cases; true 1 → predicted 0, 5 cases), plus a minority of full flips (0 → 4, 4 → 1).
- **By dataset** (`retr6_rev2`): ESS S 49.0, flip 6%; ISSP 45.6, flip 13%; LatinoBarometro 32.3, flip 21%.

| Pop-only tasks, divided (N 58) | `retr6_rev2` | Panel |
|---|---|---|
| S | −1.2 | 13.6 |
| Entropy gap | **−0.09** (MGKT −0.37, NumberGame −0.16) | −0.07 |
| Top option right | 0.50 | 0.47 |
| Polarity flip (ordinal MACH, N 24) | 0.33 | 0.33 |

Collapse (over-confidence) shows up here and only here.

**Normative lean (hand-coded sample of 50 divided shared-survey questions):**
- **Coding rule:** coded by Claude from question and options only, before seeing predictions or truth. A question is value-laden if one answer matches the textbook liberal-democratic / civic norm: pro-democracy, tolerance of minorities and immigrants, gender egalitarianism, civic participation, secular morality, pro-environment. Perception, frequency, belief and self-description questions were coded "none". 23 of 50 were value-laden.
- **Result:** mean extra mass on the desirable answers is +3.8 points for `retr6_rev2` [−2.8, +11.0] and +3.6 for the panel [−2.4, +10.0]. Only about half lean that way. With real demos in context, the average lean is small and not significant.
- **But the lean drives the worst cases** (below): rare, and very large when it happens.

**20 worst divided questions (`retr6_rev2`, TVD 0.39–0.59).** Patterns, with examples (true → predicted):
- **Knowledge items answered as an expert would** (OSPsychMGKT): "Is a caliper a craftsman's tool?" true Yes 34% → predicted 88%. Same for "bevel" and "trichomoniasis".
- **Rational / pattern answers** (NumberGame, Choices13k): true "Yes" 71% → predicted 12%. In the gamble choice, true machine A 59% → predicted 20%.
- **Opinion of a foreign country:** true very favorable 48% → predicted very unfavorable 48% (two LatinoBarometro cases).
- **Liberal answer projected onto conservative publics:**
  - ESS "would feel ashamed if a close family member were gay": true agree 24% → predicted 5%, with strongly disagree at 74% vs 21%.
  - ESS gay adoption: true disagree 57% → predicted agree 69%.
  - LatinoBarometro military government: true support 67% → predicted 28%.
- **Civic behaviour:** ISSP environmental petition, true 30% yes → predicted 70%.
- **Belief items:** ISSP belief in God: true "I don't believe" 10% → predicted 38%.

Full list with options, truth and prediction: `results/simbench_ablate/divided_stepB_anatomy.json` (`worst20_retr6_rev2`).

## Step C — common-mode vs group-specific error

Sources:
1. **New subgroup-cell run (small, labelled):** `retr6_rev2` on every cell of 150 randomly chosen divided question × country × attribute groups with ≥ 3 cells. That is 430 cells, of which 129 questions have ≥ 2 scored cells (ESS 98, ISSP 19, OpinionQA 10, LatinoBarometro 2). Cost $0.80. No demo shows any group's answer to the same question (verified: 0).
2. **Logged per-group answers from the composition arm (C2)** on the 45 questions with same-question subgroup truth.

| Metric | Subgroup-cell run (129 q, 526 pairs) | C2 groups (45 q, 115 pairs) |
|---|---|---|
| **Error correlation across groups** | **+0.66** | **+0.66** |
| Real groups' deviation correlation (reference) | −0.31 | −0.44 |
| **Group-specific share of error** | **0.28** | **0.20** |
| Between-group TVD, predicted / real | 0.094 / 0.139 | 0.057 / 0.086 |
| Each group's TVD to its own truth | 0.19 | 0.19 |
| Direction test: pairs with real gap ≥ 0.10 | 266 | 39 |
| Sign agreement on the largest real gap | **0.77** | 0.74 |
| Correlation of predicted vs real gap | **0.64** | 0.62 |

By dataset (subgroup-cell run): ESS 0.69 / 0.27 / 0.74 (error correlation / group-specific share / sign agreement); ISSP 0.74 / 0.22 / 0.74; OpinionQA 0.48 / 0.51 / 0.87.

**Reading:** two rows apply at once.
- "Errors highly correlated across groups, group-specific share small": one shared wrong belief about the question.
- "Direction test good, level wrong": the model knows who is more X than whom, but not the level of the whole population.

OpinionQA (US) is the exception, with a larger group-specific part (0.51).

## Step D — demo-source test (new Haiku calls; dev first, then eval unchanged)

Scope: all questions of the five shared surveys (eval 625 = Pop 125 / Grouped 500; dev 250 = 50 / 200). Every arm runs in both option orders. All arms draw from the same demo pool: spare rows of the same split and dataset (Pop uses all spare rows). No demo may share the target's question stem (verified: 0 leaks).

| Arm | Demos shown |
|---|---|
| D0 | 6 most similar other questions (TF-IDF), same group first |
| D1 | 6 other questions from the same topic: k-means clusters of question-stem embeddings per dataset, no wording ranking |
| D2 | Other questions from the same subgroup cell, matched by country + attribute + value across waves |
| D3 | Same cell and same topic, filled with same cell |
| D4 | **Diagnostic only, never a candidate:** up to 6 other groups' real answers to this same question in the same country. Never the target's own subgroup (any wave), never the country total, never for Pop targets |

Grouped targets have few same-cell questions: D2 and D3 average 3.7 demos on dev and are mostly identical.

### Eval (paired vs D0 on the same questions)

| Cell | N | D0 S | D1 Δ | D2 Δ | D3 Δ | D4 Δ (N) |
|---|---|---|---|---|---|---|
| Pop / consensus | 26* | 49.0 | +2.4 [−8.2, +14.4] | −7.9 [−14.2, −1.8] | −7.8 [−14.2, −1.8] | – |
| Pop / mixed | 57 | 46.0 | −0.5 [−7.0, +5.3] | −11.4 [−19.0, −4.4] | −5.0 [−11.4, +0.8] | – |
| **Pop / divided** | 42 | 55.1 | **−14.0 [−26.7, −2.2]** | −6.1 [−12.7, −0.0] | +0.1 [−4.9, +5.2] | – |
| Grouped / consensus | 185 | 50.1 | −2.9 [−7.0, +0.8] | +1.4 [−1.6, +4.3] | +1.4 [−1.8, +4.5] | +31.9 [+26.3, +37.3] (177) |
| Grouped / mixed | 182 | 44.3 | −2.8 [−7.0, +1.5] | +2.9 [−0.3, +6.6] | +2.5 [−0.9, +5.7] | +30.8 [+24.1, +37.8] (173) |
| **Grouped / divided** | 133 | 40.3 | +1.7 [−4.1, +8.1] | +4.0 [−0.9, +10.0] | +4.7 [−0.6, +9.8] | **+30.7 [+22.7, +39.2]** (119) |
| Grouped / all | 500 | 45.4 | −1.6 [−4.3, +0.9] | **+2.6 [+0.5, +4.5]** | **+2.7 [+0.5, +4.9]** | +31.2 [+27.4, +35.1] (469) |
| All / all | 625 | 46.2 | −2.2 [−4.5, +0.1] | +0.3 [−1.8, +2.2] | +1.4 [−0.5, +3.4] | – |

### Dev

| Cell | N | D0 S | D1 Δ | D2 Δ | D3 Δ | D4 Δ (N) |
|---|---|---|---|---|---|---|
| Pop / divided | 14* | 51.0 | −17.5 [−38.4, −1.4] | −10.9 [−23.0, −0.9] | −4.4 [−17.8, +6.1] | – |
| Grouped / divided | 55 | 36.3 | −0.1 [−9.3, +9.3] | −0.9 [−10.9, +9.1] | +1.1 [−9.1, +11.4] | +28.5 [+14.9, +43.1] (49) |
| Grouped / all | 200 | 39.8 | −0.8 [−4.6, +3.0] | +5.0 [+1.1, +9.1] | +5.7 [+1.8, +9.5] | +34.6 [+28.3, +41.4] (181) |

**Residuals on Grouped divided** (eval, D0 → D4): top option right 0.55 → 0.78; polarity flip 0.21 → 0.11; absolute scale shift 0.105 → 0.057; entropy gap −0.006 → −0.019. D1–D3 leave these about unchanged.

**Reading:** "D4 helps a lot and D1/D2 do not" on divided questions. The model lacks a question-specific anchor; real answers on the question itself are the signal. Same-group demos add a small, real gain across all Grouped questions (+2.6, mostly mixed and consensus). Same-topic demos and same-country Pop demos hurt.

## Which rows of the interpretation tables the evidence supports

- **Step A:** "Within-group share is large". Demographic framing cannot create the spread. It is already inside every group, and the model reproduces its amount correctly.
- **Step C:** "Errors highly correlated across groups, group-specific share small" together with "Direction test good, level wrong". One shared misjudgement of where this question's answers sit, while relative group differences are roughly right.
- **Step D:** "D4 helps a lot and D1/D2 do not". The signal that fixes divided questions is the actual answer distribution of this question in this population, which every subgroup shares, given Step A.

These fit together. Divided-ness is a property of the question, shared by every group. The model gets the amount of spread right but places it wrong for the whole population. Only information about this question moves the placement.

**Strongest counter-reading:**
- **D4 is close to a proxy leak.** Because subgroups differ so little (Step A), other groups' answers to the same question are nearly the target's own answer. So +30 shows that question-level information is what is missing; it does not show that a usable method exists.
- **The Step C cell run is ESS-heavy** (98 of 129 questions), and OpinionQA behaves differently (group-specific share 0.51).
- **Step A covers single attributes only.** Intersectional groups could differ more.
- **D2 is weakened by thin data:** Grouped targets average 3.7 same-cell demos instead of 6.

## Implications

1. **Stop spending on demo-source variants and demographic decompositions for divided questions.** Within-group spread and a common-mode error mean neither can move the placement.
2. **Look for question-level anchors that are legitimately available**, e.g. the same question in an earlier wave, in a neighbouring country, or from a related segment. Test them with the same leak rules. This is the one lever with a large measured effect, though so far only as a diagnostic.
3. **Pop-only task datasets remain a separate problem.** There the model is over-confident (entropy gap −0.09 to −0.37) and answers like an expert or a rational agent.
4. **For UserSim:** when any real answer distribution exists for the actual question being asked, from any segment, anchor the panel on it. Persona and segment structure should then shape differences around that anchor, which the model does get directionally right.

## Cost and files

- About $7.80 of Haiku: Step C cell run $0.80, Step D dev $2.00 and eval $5.00.
- Code:
  - `src/human_sim/simbench_divided_anatomy.py`: Steps A–D analysis
  - `src/human_sim/simbench_ablate.py`: `--set stepc`, `D0`–`D4` arms, `_dpool`, `_topics`, `_cell_key`
- Results:
  - `results/simbench_ablate/divided_stepA_summary.json`, `divided_stepA_per_question.json`
  - `divided_stepB_anatomy.json` (incl. 20 worst), `divided_stepB_normative50.json` (codes and rule)
  - `divided_stepC_common_mode.json`
  - `divided_stepD_demo_sources.json`
  - per-question logs `D*_claude-haiku-4-5_*.json`, `retr6_rev2_claude-haiku-4-5_p25g100s7stepc.json` (both option orders logged)
