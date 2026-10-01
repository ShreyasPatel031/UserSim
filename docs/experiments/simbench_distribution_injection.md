# SimBench: injecting human answer distributions — progress log

Status as of 2026-10-01. Branch `claude/blissful-pascal-0ldgye`. All numbers are SimBench scores (higher is better) unless stated.

## 1. The problem

UserSim panels agreed too much, and Pop-split questions scored badly. Adding real answers from other users helped. The question for this work: what is the right way to give the model human answer distributions, both for questions where people agree and for questions where they disagree?

## 2. Setup (fixed for every run)

| Item | Value |
|---|---|
| Score | Official SimBench: `S = 100 × (1 − TVD(pred, human) / mean TVD(human, uniform))`, denominator per dataset |
| Eval sample ("full benchmark") | 981 questions: 25 per Pop dataset, 100 per Grouped dataset, seed 7. Pop 481 / Grouped 500 |
| Dev (tuning) set | 380 questions, disjoint from eval, same per-dataset ratio (10 / 40). Mean entropy 0.72 vs 0.70 eval. Missing 2 small Pop datasets (MoralMachineClassic, OSPsychRWAS: no spare rows, ~3% of eval) |
| Demo pool | Rows outside eval and dev reserve. A demo is never the same question text as the target (also enforced for rewritten questions, see §9) |
| Question types | By normalized entropy of the real answers: **consensus** < 0.65 (top option ~77%), **mixed** 0.65–0.84 (~52%), **divided** ≥ 0.84 (~43%). About one third each, in eval and in the whole benchmark (34 / 33 / 33%). Pop leans divided (37%), Grouped leans consensus (38%) |
| Models | Vertex: Haiku 4.5, Sonnet 4.6, Sonnet 5.5 (global endpoint, no `temperature`, thinking `between_tools`), Gemini 2.5 Flash / Flash-Lite |
| Protocol | Tune on dev, then apply unchanged to eval. Paired bootstrap 95% CIs on per-question differences |

## 3. Glossary of harnesses

| Name | What it does | Calls / question |
|---|---|---|
| `base` | Persona prompt + official instruction | 1 |
| `fewshot` | 3 fixed real distributions from the same dataset | 1 |
| `fs_k6`, `fs_k12` | 6 / 12 fixed demos | 1 |
| **`retr6`** | 6 real distributions for the most similar questions (TF-IDF), same group first, max 2 per question text | 1 |
| `retr6_vs3` | `retr6` demos; model gives 3 candidate distributions with confidences, mixed | 1 |
| `retr6_rev2` | `retr6` asked in original and reversed option order, averaged | 2 |
| `B_n3_soft` | "Split your group into 3 segments; give share + distribution for each", share-weighted. No data | 1 |
| `B_n3_soft_rev2` | Same, both option orders | 2 |
| `B_ground3(_rev2)` | Segments with the 6 retrieved distributions shown first | 1 (2) |
| `B_agents` | 5 archetypes per group (cached), one call each, equal weights | 5 |
| **`P_groundall5`** ("panel") | Planner writes 5 question-specific types + shares, sees 6 real distributions; each type answers in its own call, also sees them; share-weighted | 6 |
| `P_groundall5_R` | The panel run on reversed options, mapped back | 6 |
| `P_adapt` | Panel where the planner estimates agreement first and uses 1–5 types | 2–6 |

## 4. Timeline and results

### 4.1 Starting point (already in the repo, Gemini 2.5 Flash, full benchmark)
| Arm | S | Pop | Grouped |
|---|---|---|---|
| base | 28.6 | 18.0 | 38.8 |
| plural ("report the spread") | 35.7 | 26.6 | 44.5 |
| **fewshot (3 real distributions)** | **41.6** | 35.7 | 47.2 |
| ensemble (5 samples, T=1) | 30.7 | 22.3 | 38.8 |
| no / swapped persona | 10.6 / 13.7 | | |

Isotonic calibration lifted weak arms (+6 to +11) but did almost nothing for fewshot (+0.5).

**Key diagnosis:** predictions are miscalibrated in opposite directions. Too flat on consensus questions, too peaked on divided ones. One global sharpen/flatten cannot fix both: flattening gains +9 on divided and loses 17 on consensus.

### 4.2 Better demos (Flash-Lite full; Haiku 300-question slice)
| Arm | Flash-Lite (981) | Haiku (300) |
|---|---|---|
| base | 16.2 | 36.3 |
| fewshot | 27.1 | 40.3 |
| fs_k6 | 29.6 | 42.9 |
| **retr6** | **32.5** | 45.7 |
| retr6 + entropy labels | 32.4 | 46.0 |

Picking demos by similarity is the main lever. Labelling demos with their spread adds nothing.

### 4.3 Three different mechanisms (Haiku, full)
| Arm | S | Divided |
|---|---|---|
| base | 33.2 | 22.8 |
| retr6 | 43.6 | 33.7 |
| A: shape statistics instead of examples | 33.1 – 34.3 | ~27 |
| B: segment decomposition (`B_n3_soft`) | 31.5 | **37.7** |
| C: calibration keyed on neighbour entropy | no change (43.5 → 43.6) | |

Examples beat summaries of examples. Segments help divided questions and badly hurt consensus ones (28 vs 52).

### 4.4 Retrieval tuning and more segment designs (Haiku dev)
- Retrieval variants vs `retr6` (39.2): reversed demo order 38.7, embeddings 37.7, shape-conditioned 35.7. None helps; TF-IDF is fine.
- Segment designs vs `B_n3_soft` (29.9): adaptive count 28.6, persona agents 29.4, fixed archetype dictionary 24.8 (worse), response-style segments 22.0 (worse).
- Full benchmark: `B_adaptive` 32.5, `B_agents` 31.8, `B_n3_soft` 31.3, `retr6` 43.4. All segment designs sit on the same trade-off curve.
- Share-weighted hybrids (segments invented per question, one call each, weighted by shares): 24.3 – 27.0 on dev, worse than equal weights.

### 4.5 Why segment mixtures fail (logged every segment, dev)
1. **The model's shares carry no information.** Distance to the best possible weights: model shares 0.47, equal weights 0.48.
2. **The prompt forces disagreement.** On consensus questions the mix puts 54% on the top answer vs 78% for real people. The largest segment alone scores better than the mix.
3. **All segments share the model's bias on contested questions.** Mix gets the real top answer only 33–35% of the time (example: 60% of young Guatemalans would accept a military government; every design leaned "no").
4. Archetypes describe survey-taking styles ("Careful Optimizer"), not views, so their answers are near-identical. This reproduces the "panel agrees too much" problem.
5. Headroom from better weights is real only on consensus/mixed questions (after a null control: +31 / +14 / +10 for `B_n3_soft`).

### 4.6 Observable persona panel (Haiku)
| Arm (dev) | S | Consensus | Mixed | Divided |
|---|---|---|---|---|
| Panel, no data | 24.8 | 40.5 | 16.6 | 19.7 |
| Panel, planner sees data | 31.4 | 43.8 | 24.3 | 27.8 |
| **Panel, planner + types see data (`P_groundall5`)** | **39.4** | 46.8 | 37.4 | 34.9 |

Full benchmark: panel **41.6** (consensus 41.8, mixed 43.0, **divided 40.1**). It beats `retr6` on divided (+6.3, CI +3.2 to +9.5) and trails it overall (−1.8). Trace viewer: https://claude.ai/artifact/JXA52y9pfsisQrgpKcrC74 (dev examples).

Consensus gap: the largest type is usually right (74% on the real top answer), but minority types get about half the weight. Fixes on the full benchmark:

| Fix | All | Consensus | Divided |
|---|---|---|---|
| `P_adapt` (planner estimates agreement, 1–5 types) | 40.2 | 47.1 | 34.2 |
| Route between panels by neighbour agreement | 41.9 | 44.1 | 39.7 |
| **Blend: panel + `retr6` as one visible component** | **44.7** | 48.4 | 39.9 |

### 4.7 Divided questions: where we stood after the panel
On divided questions (full, 328 questions): panel 40.1; panel + 30% `B_n3_soft` **44.3** (+4.2 over panel, significant). The panel wins on opinion surveys, segments win on choice/game tasks (NumberGame 59 vs 11, Choices13k 46 vs 25).

**Routing is the bottleneck.** The neighbour-agreement router sends 90% of truly divided questions to the divided harness, but it sends 61% of all questions there. The routed system lands at 43.2, level with `retr6` alone. A perfect router would give about 47. The router signal correlates only 0.58 with true entropy.

### 4.8 Option reversal, multi-candidate, cross-model (then dropped)
- **Leak caught:** the first reversed-options run scored 66.5 because the reworded question no longer matched its own text, so the original question (with its answer) came back as a demo. Fixed (`_orig_template`), verified 0 leaks, re-run: 40.8.
- Full benchmark: `retr6_rev2` 43.6 (no overall gain, divided 33.8 → 35.4); Gemini Flash `retr6` alone **46.3** (consensus 57.5).
- Cross-model mixes reached 48.7 overall, but **we decided to keep models separate** to avoid complexity. Not pursued further.

### 4.9 Same harnesses on each model (dev, no mixing)
| Harness | Haiku | Sonnet 4.6 | Sonnet 5.5 | Gemini Flash |
|---|---|---|---|---|
| **Divided**: persona only | 15.3 | 29.5 | 30.4 | 12.8 |
| **Divided**: `retr6` | 27.2 | 40.6 | 39.0 | 27.7 |
| **Divided**: panel 0.4 + `B_n3_soft_rev2` 0.6 | **43.8** | **43.7** | – | **40.7** |
| **Consensus**: `retr6` | 56.6 | 61.6 | 66.2 | 60.1 |
| **Consensus**: `retr6_vs3` | 54.0 | 59.4 | **67.7** | **60.8** |
| **Overall**: `retr6` | 39.5 | 48.5 | **50.2** | 40.7 |

- Bigger models help consensus questions a lot and divided questions little: the divided harness scores the same on Haiku and Sonnet 4.6.
- **Sonnet 5.5** is available on Vertex, beats Sonnet 4.6 (+4.6 consensus, +1.7 overall) at about two thirds of the price.
- Opus 5.5 estimate for both harnesses on the full benchmark: ~$43, up to ~$95 (thinking can't be turned off). Not run; Sonnet 5.5 chosen instead.

### 4.10 Latest divided-question round (Haiku dev, 126 divided questions)
| Harness | Divided | Overall |
|---|---|---|
| Panel (before) | 34.9 | 39.4 |
| **Panel asked in both option orders, averaged** | **41.0** (+6.1, significant) | **41.1** |
| Segments in both orders | 37.2 | 31.1 |
| Grounded segments, both orders | 38.6 | 37.4 |
| Segments sampled 3× at T=1 | 36.0 | 31.2 |

Cross-validated mixes on divided questions:
| Mix | Divided |
|---|---|
| Panel 0.4 + reversed segments 0.6 (previous best) | 43.7 |
| Panel both orders 0.6 + reversed segments 0.4 | 44.4 |
| **Panel both orders 0.75 + grounded segments 0.25, pulled 29% toward even split** | **45.9** |

## 5. Current best picks

| Question type | Model | Harness | Evidence |
|---|---|---|---|
| Consensus | **Sonnet 5.5** | `retr6` (or `retr6_vs3`, tied) | 66.2 / 67.7 on dev consensus |
| Divided | **Haiku** | Panel in both option orders + grounded segments, pulled toward even split | 45.9 dev (CV); previous version 44.9 on full |
| Which to use | – | Router on neighbour agreement | **Weak link** |

Everything stays observable: personas, shares, each type's answer, both option orders and segments are logged per question.

## 6. What we learned (short version)

1. **Real data in context is the biggest lever**, and which examples matter more than how many. Summaries, labels and calibration add little.
2. **No single prompt is calibrated at both ends.** Consensus questions need concentration; divided questions need spread with the right centre.
3. **The model cannot judge how contested a question is by itself.** Every "let the model decide" design (adaptive segments, agreement estimates) traded one end for the other.
4. **Segments add spread but not direction.** On contested questions all segments share the model's normative bias; only real data moves the centre.
5. **Option order bias is real for the panel** (+6 on divided from averaging both orders), much less for single-call `retr6`.
6. **Larger models fix consensus, not disagreement.**
7. **Routing now decides the total score.**

## 7. Open problems and next-step options (for discussion)

1. **Router.** Better contestedness signal: combine neighbour entropy, the planner's agreement estimate (corr 0.54), dataset priors, the spread between the two option orders, or disagreement between harnesses. Target: get close to the ~47 a perfect router would give.
2. **Confirm the picks on the full benchmark.** Sonnet 5.5 `retr6` ~$3; new Haiku divided harness ~$13 (weights fitted on dev).
3. **More divided-question ideas.** Panel types that carry views on the topic; more types for contested questions; reversal + more orders (cyclic) for the panel; dataset-aware choice between panel and segments (they win on different datasets).
4. **Fit weights instead of asking for shares** (mixture-of-personas style), now that we know model shares are uninformative.
5. **Bring it back to UserSim.** The panel design maps directly onto the Vercel persona-agent flow: question-specific types, grounded on real answers, asked in both option orders, weighted.

## 8. Cost

Roughly **$100 of Vertex usage** over the whole session (list prices; estimated from token counts). Largest items: Sonnet 4.6 dev harnesses ~$23, full-benchmark Haiku panel runs ~$14, cross-model / reversal round ~$10. Typical full-benchmark runs: Haiku `retr6` ~$1, Haiku panel ~$8, Sonnet 5.5 `retr6` ~$3.

## 9. Caveats

- Dev results rest on 380 questions (~126 per type). Differences under ~5 points per type are within noise.
- Mix weights tuned on dev are cross-validated there, then applied once to eval; dev-only mixes in §4.10 are not yet confirmed on eval.
- The divided-first harness is weak on consensus questions by design; it only pays off with a good router.
- One leak was found and fixed (§4.8); demo exclusion now always uses the original question text.

## 10. Where things are

| Path | What |
|---|---|
| `src/human_sim/simbench_ablate.py` | All harnesses (arms), runner, Claude/Gemini backends, dev/eval setup (`build_env`) |
| `src/human_sim/simbench_segment_diag.py` | Segment diagnosis (oracle / equal / model weights, null oracle) |
| `src/human_sim/simbench_panel_blend.py` | Route and blend evaluation (dev-fitted, eval-scored) |
| `src/human_sim/simbench_mix.py` | Mixes of logged arms, dev-fitted, eval-scored |
| `src/human_sim/simbench_harness_eval.py` | Per-model harness comparison on dev |
| `src/human_sim/simbench_nbr_calibrate.py` | Calibration keyed on neighbour entropy |
| `results/simbench_ablate/*.json` | Every run (per question, with segment traces) and reports: `mix_report.json`, `panel_blend_report.json`, `segment_diagnosis.json`, `harness_eval_dev.json` |

Run any arm: `PYTHONPATH=src python -m human_sim.simbench_ablate --model claude-haiku-4-5 --set dev --arms retr6,P_groundall5`
