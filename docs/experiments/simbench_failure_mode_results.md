# SimBench failure mode: Pop vs Grouped, or consensus vs divided? — results

Run of `simbench_failure_mode_spec.md`. Haiku 4.5 only, same setup as `simbench_distribution_injection.md` (eval 981, dev 380, seed 7; consensus < 0.65 ≤ mixed < 0.84 ≤ divided). `*` marks cells with N < 30 (unreliable). CIs are paired bootstrap 95% unless stated.

## Verdict (short)

**Neither H1 nor H2 as stated.** Composition is not the bottleneck: giving it did not lift Pop-divided, and real weights did no better than equal weights. Predictions on divided questions are also not collapsed: their entropy matches reality (gap about 0). The error is **placement**. The model spreads the right amount of mass but puts it on the wrong options, and it makes the same mistake for every subgroup. The "Pop is worse on divided" gap comes almost entirely from Pop-only task datasets (personality scales, gambles, number puzzles), not from population surveys.

## Step 0 — cross-tab from existing full-benchmark runs (no new calls)

Mean S, Haiku, eval (981 questions). Gap = Pop − Grouped within the bin (unpaired bootstrap CI).

| Arm | Bin | Pop N | Pop S | Grouped N | Grouped S | Pop − Grouped | Pop entropy gap (pred − true) | Grouped entropy gap |
|---|---|---|---|---|---|---|---|---|
| base | consensus | 144 | 43.2 | 185 | 48.7 | −5.5 [−17.5, +6.0] | +0.22 | +0.20 |
| base | mixed | 142 | 24.2 | 182 | 35.2 | −11.1 [−22.2, −0.0] | +0.04 | +0.08 |
| base | divided | 195 | 13.2 | 133 | 36.7 | **−23.4 [−33.4, −13.5]** | −0.07 | −0.01 |
| retr6 | consensus | 144 | 50.8 | 185 | 53.3 | −2.5 [−12.2, +7.3] | +0.19 | +0.17 |
| retr6 | mixed | 142 | 46.1 | 182 | 43.5 | +2.6 [−7.3, +12.1] | +0.04 | +0.06 |
| retr6 | divided | 195 | 29.3 | 133 | 40.4 | **−11.1 [−20.5, −1.5]** | −0.05 | −0.02 |
| P_groundall5 | consensus | 144 | 42.7 | 185 | 41.1 | +1.6 [−8.6, +10.3] | +0.26 | +0.23 |
| P_groundall5 | mixed | 142 | 44.2 | 182 | 42.1 | +2.1 [−7.0, +11.4] | +0.08 | +0.09 |
| P_groundall5 | divided | 195 | 36.2 | 133 | 45.9 | **−9.6 [−17.8, −0.8]** | −0.02 | +0.02 |

With real data in the prompt (`retr6`, panel), the Pop–Grouped gap vanishes on consensus and mixed questions but stays on divided ones.

**Confound check: only the 5 datasets present in both splits** (Afrobarometer, ESS, ISSP, LatinoBarometro, OpinionQA):

| Arm | Divided: Pop N / S | Grouped N / S | Gap |
|---|---|---|---|
| base | 42 / 38.1 | 133 / 36.7 | +1.4 [−12.5, +14.7] |
| retr6 | 42 / 40.1 | 133 / 40.4 | −0.3 [−11.4, +10.7] |
| P_groundall5 | 42 / 44.1 | 133 / 45.9 | −1.8 [−12.4, +9.6] |

Inside the same surveys, Pop-divided scores like Grouped-divided. The Pop-divided gap is carried by Pop-only datasets. `retr6` on Pop divided questions scores: OSPsychMACH −1.1 (N 24), Choices13k −1.9 (15), NumberGame 1.5 (13), OSPsychMGKT −7.2 (6), ConspiracyCorr 28.3 (17). Survey datasets in the same bin score 31–67.

## Step 1 — what population information exists

| Dataset | Split | Composition | How |
|---|---|---|---|
| Afrobarometer, ESS, ISSP, LatinoBarometro | Pop | **Derivable (partial)** | Single-attribute Grouped cells for the same country (age, gender, religion, …) with respondent counts. SimBench keeps only some cells per country, so only attributes whose cells cover ≥ 80% of respondents are used |
| OpinionQA | Pop | **Derivable** | Full US cells for 11 attributes (region, age, sex, education, …) |
| Same 5 datasets | Grouped, country-only rows | **Derivable** | Same as above |
| Same 5 datasets | Grouped, subgroup rows (country × attribute) | No | The target is already a cell; no finer cells exist |
| ChaosNLI, Choices13k, ConspiracyCorr, DICES, GlobalOpinionQA, Jester, MoralMachine, MoralMachineClassic, NumberGame, OSPsych (Big5, MACH, MGKT, RWAS), TISP, WisdomOfCrowds | Pop | **No** | Only a country or platform label. `auxiliary` holds task metadata (gamble rates, number sets, correct answers) or attributes of the cell, not shares |

Coverage: **145 / 981 eval questions (15%)**: Pop 119, Grouped 26. **66 / 380 dev**: Pop 48, Grouped 18.

Shares use only `group_size`, take the median over other questions (sizes from the target question are excluded), and cap at 5 groups. The preferred attribute is the one with the most groups, then the best coverage; no answer information is used to choose it. Chosen attributes on eval: gender in LatinoBarometro (30) and Afrobarometer (22), education in OpinionQA (21), age/domicile/gender in ESS, work status in ISSP.

**Leak checks:** 0 demos share the target's original question text (both option orders). No prompt contains any subgroup answer distribution; composition text is built from sizes only.

## Step 2–3 — composition arms (both option orders, `retr6` demos)

- `C0` = `retr6_rev2`
- `C1` = + composition table (up to 3 attributes), direct prediction
- `C2` = one call per group, real shares
- `C3` = C2's group answers, equal weights

### Eval (145 covered questions)

| Cell | N | C0 | C1 | C2 | C3 | C1 vs C0 | C2 vs C0 | C2 vs C3 | Entropy gap C0 / C2 | Top option right C0 / C2 |
|---|---|---|---|---|---|---|---|---|---|---|
| Pop / consensus | 24* | 52.0 | 50.7 | 50.8 | 50.9 | −1.3 [−7.3, +5.3] | −1.1 [−3.0, +0.6] | −0.1 | +0.13 / +0.13 | 0.79 / 0.79 |
| Pop / mixed | 57 | 46.2 | 47.2 | 45.5 | 45.4 | +1.0 [−1.8, +3.8] | −0.8 [−3.1, +1.6] | +0.1 | +0.06 / +0.06 | 0.61 / 0.56 |
| **Pop / divided** | 38 | 47.5 | 44.4 | 49.4 | 49.6 | −3.1 [−8.2, +0.9] | +1.9 [−0.4, +4.4] | −0.2 | −0.01 / −0.00 | 0.53 / 0.58 |
| Pop / all | 119 | 47.8 | 47.0 | 47.8 | 47.8 | −0.8 [−3.3, +1.6] | +0.0 [−1.5, +1.4] | −0.0 | +0.05 / +0.05 | 0.62 / 0.61 |
| Grouped / consensus | 6* | 51.4 | 64.0 | 66.3 | 65.7 | +12.7 | +14.9 | +0.6 | +0.26 / +0.16 | 0.83 / 0.83 |
| Grouped / mixed | 7* | 52.5 | 52.6 | 54.5 | 56.9 | +0.1 | +2.0 | −2.3 | +0.04 / +0.05 | 0.71 / 0.71 |
| Grouped / divided | 13* | 32.1 | 29.6 | 36.7 | 36.1 | −2.5 | +4.6 | +0.6 | −0.00 / +0.00 | 0.69 / 0.69 |
| Grouped / all | 26* | 42.1 | 43.8 | 48.3 | 48.5 | +1.7 [−2.9, +6.2] | +6.3 [+0.7, +11.8] | −0.2 | +0.07 / +0.05 | 0.73 / 0.73 |
| **All / all** | 145 | 46.8 | 46.5 | 47.9 | 48.0 | −0.3 [−2.6, +1.8] | +1.1 [−0.3, +2.7] | −0.1 [−0.4, +0.2] | +0.06 / +0.05 | 0.64 / 0.63 |

### Dev (66 covered questions)

| Cell | N | C0 | C1 | C2 | C3 | C2 vs C0 | C2 vs C3 |
|---|---|---|---|---|---|---|---|
| Pop / divided | 13* | 42.4 | 36.4 | 39.3 | 40.3 | −3.1 [−11.4, +4.0] | −1.1 [−2.2, −0.1] |
| Pop / all | 48 | 48.7 | 46.7 | 48.0 | 48.2 | −0.7 [−3.4, +1.7] | −0.3 |
| All / all | 66 | 43.6 | 42.1 | 43.3 | 43.5 | −0.2 [−2.5, +2.0] | −0.2 [−0.6, +0.4] |

### Diagnostics

1. **Composition does not lift Pop-divided.**
   - C1 hurts slightly on eval (−3.1) and on dev (−6.0).
   - C2 is +1.9 on eval [−0.4, +4.4] and −3.1 on dev. Neither is significant, and they point in opposite directions.
2. **Entropy gap on divided questions is about 0** (−0.02 to +0.00) for every arm. Predictions are not collapsed toward one answer. Consensus questions remain too flat (+0.13 to +0.30), as before.
3. **Top-option agreement on Pop-divided is low** (0.53–0.58 eval, 0.31 dev) and barely moves with composition.
4. **Weights test.** Real shares vs equal shares: −0.1 [−0.4, +0.2] on eval overall, and −0.1 [−0.7, +0.4] on the 76 questions where shares differ by ≥ 10 points. Real weights carry no signal here.
5. **Oracle ceiling (diagnostic only).** Mixing the true same-question subgroup answers with true shares reproduces the target almost exactly: S 97.6 (eval, N 27) and 96.9 (dev, N 18). On the same questions C2 scores 49.5 and C0 43.8. The information that matters is the **subgroup answers**, not the shares.
6. **Group spread on oracle questions.**
   - Real subgroups differ from each other by TVD 0.089 (eval) and 0.094 (dev).
   - Haiku's group answers differ by 0.054 and 0.059, about 40% too similar.
   - Each group's answer is 0.18–0.22 TVD from that group's real answer.
   - The shared error is 2–4× larger than the real differences between groups. Composition cannot fix an error that every group shares.

## Which row of §7 the evidence supports

The closest row is **"C1/C2 do not lift Pop-divided"**, so composition is not the bottleneck and H1 is not supported on the 15% of the benchmark where composition exists. The second half of that row does not hold, though: the entropy gap is not negative. The model is not failing to spread. It spreads about the right amount and puts the mass on the wrong options. The same misplacement appears in every subgroup's answer (point 6), so it acts like a shared prior. The remaining Pop-divided weakness sits in Pop-only task datasets (personality scales, gambles, number puzzles), where neither real demos nor composition give the model the right direction.

**Strongest counter-reading:**
- **Coverage.** Composition was only testable on the survey datasets, where Pop already scores like Grouped. H1 could still matter for the Pop-only datasets, which carry the gap but have no composition data.
- **Coarse composition.** It is one attribute, often a 50/50 gender split, and some shares come from a different survey wave. That makes the weights test weak.
- **Small cells.** The divided cells are small (38 Pop-divided on eval).

## Implications for next steps

1. **Work on placement, not spread.** Entropy is already right on divided questions. The missing piece is which options carry the mass.
2. **The Pop-only task datasets are the real hole.** MACH, Choices13k, NumberGame and MGKT score near or below 0. These need task-specific handling, for example a better demo match within the same scale or game, rather than population modelling.
3. **Subgroup answers are the high-value signal.** The oracle shows that true subgroup answers explain Pop almost perfectly. Predicting subgroup answers better, for example with retrieved demos from the same subgroup cell, is where composition could still pay off.

## Cost and files

- About $2 of Haiku: C1 $0.50, C2 $1.46 across dev and eval.
- Code:
  - `src/human_sim/simbench_ablate.py`: `_composition_index`, `_composition`, `C1_comp_direct`, `C2_comp_personas`
  - `src/human_sim/simbench_failure_mode.py`: diagnostics
- Results:
  - `results/simbench_ablate/failure_mode_step0_crosstab.json` (Step 0)
  - `results/simbench_ablate/failure_mode_report.json` (Steps 2–3, oracle, group spread)
  - `results/simbench_ablate/C1_comp_direct_*` and `C2_comp_personas_*` (per question; C2 logs groups, real shares, group answers and both option orders)
