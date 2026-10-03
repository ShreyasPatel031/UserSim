# Persona panel: where we are and why it isn't working

Branch `claude/blissful-pascal-0ldgye`. Model for every run below: Haiku 4.5 unless stated. All scores are SimBench S (higher is better). Eval = the 981-question sample; "covered" = the 411 eval questions from the 5 shared surveys, the only ones where real demographic personas exist.

## 1. The goal

Build a persona panel where:
- each persona is a **real demographic group** (real size, its own average opinion, its own examples);
- it beats the best other method on **consensus** questions and on **divided** questions;
- it is **observable**: you can see who makes up the population, which attribute explains the most variance, and what each group would say.

## 2. Short answer

**Not met.** The panel can be made observable, but it does not make Haiku more accurate than a single retrieval call. The reasons, in order:

1. **The model's estimate of one group is the bottleneck.** Whatever is wrapped around it (personas, weights, post-processing) starts from an answer that is too flat on consensus questions and on the wrong side on divided questions.
2. **Real demographic groups barely differ on these questions.** So splitting into groups has almost nothing to add.
3. **When we let the data choose how many personas to use, it chose one.** Single retrieval, with the demographic breakdown attached for observability.

## 3. Your two questions

**"Why can't you control the number of personas for consensus questions? A few demographics should explain most of the variance, closer to single retrieval."**
We did, in version 5 (`simbench_panel_dynamic_k.py`). Each question gets a "how much did the groups differ on similar questions" score (never the target question). Low score means one persona for the whole population; high score means the demographic split. Tuned on dev, the best cutoff **never splits**: 0% of consensus, mixed and divided questions got the demographic split. Your intuition holds: for most questions the right answer is close to single retrieval. The consequence is that the panel doesn't add accuracy.

**"If retrieval is still shared across all personas, that's the same model N times. Divide retrieval per persona."**
You were right. Before, every persona saw its own group's examples **plus a block of the whole population's examples**, and the shared block dominated (personas were 0.05 TVD apart). In `C7_split_own` each persona sees **only its own group's** examples. Persona diversity rose to 0.095, **exactly the real groups' diversity (0.095)**. So the personas now behave like the real groups, but they got **less accurate** (consensus 45.3, divided 41.6) because each persona works from about 5 examples of one thin group.

## 4. What each attempt scored

Eval, 411 covered questions. The best competitor is 56.2 on consensus (`retr6`) and 46.5 on divided (`D3`, same-group data).

| Version | Consensus | Divided | All | Criteria |
|---|---|---|---|---|
| Plain harness (`retr6_rev2`) | 54.5 | 40.8 | 49.3 | |
| Invented personas (original panel) | 46.2 | 44.0 | 46.1 | no |
| Demographic personas, shared retrieval block (`C5b`) | 50.7 | 44.9 | 50.1 | no |
| v1: sharpen each persona per question | 53.2 | 44.3 | 50.2 | no |
| v2a: "estimate agreement first" prompt (dev only) | dev −6.3 vs plain | dev −3.4 | | no |
| v2b: 20 imagined individuals per persona (dev only) | dev −20.3 | dev −3.4 | | no |
| v4: personas as offsets around a per-question population level | **56.9** | 45.9 | **52.0** | consensus met (+0.8, CI −2.6 to +4.2), divided not |
| v5: demographic split, own retrieval only (`C7`) | 45.3 | 41.6 | 46.1 | no |
| v5: persona count per question (hard or soft) | 54.4 / 54.1 | 44.3 | 50.5 | no |

v4 has the best overall score of any benchmark-valid method here. Its consensus win is within noise, and **its population level comes mostly from other predictors** (in the example I checked: 65% `D3`, 27% `retr6`, 1% the panel). The personas add only their offsets, which are tiny. So v4 is not the persona panel succeeding.

## 5. The full reason it doesn't work

**a. The error is in the level, not in the demographic split.**
I measured how much the real demographic groups differ on each target question (TVD to their size-weighted mean, from the real cell answers):

| | Real difference between groups | Plain harness error |
|---|---|---|
| All questions | 0.095 (median 0.064) | 0.160 |
| Consensus | 0.094 | 0.168 |
| Divided | **0.069** | **0.182** |

People on divided questions are divided **inside** every demographic group, not between groups. Women split the way men split. A panel of demographic groups can only recover the between-group part. This is an inference from these numbers, not a proof: the error mostly sits in the population-level estimate, and no split fixes that.

**b. The model is over-hedged on consensus and on the wrong side on divided.**
On consensus questions the predicted spread is 0.64 (plain) and 0.68 (invented personas) against a real 0.44. On divided questions the spread is right (0.89 to 0.92 vs 0.92) but the top answer is right only about 55% of the time. If each consensus question's spread were matched exactly (not possible at prediction time), consensus error would fall by about a third.

**c. Nothing around the model's answer can fix it.** Tested offline on logged runs:
- Per-question spread control gives +1.4 overall (45.0 vs 43.6).
- Calibrating the top answer's share, gating on source agreement, predicting agreement from evidence, and shape-aware sharpening all **lowered** the score by 0.8 to 1.9. The signals explain only about half the variation in how strongly a group agrees, so correcting with them flattens the questions that were fine.
- Prompt changes inside each persona (agreement-first, imagined individuals) were worse.

**d. Weighting the personas is not the problem.** Equal weights scored 35.9 against 41.6 for the planner's weights.

**e. A model-capability ceiling shows up elsewhere.** Earlier runs: Sonnet 5.5 with the plain harness scored 56.1 on eval vs 43.6 for Haiku, mostly by removing order and shape error. The demographic panel has not been tried with Sonnet.

## 6. What does work

- **Observability layer.** Real demographic groups, real sizes, and each group's own examples and average opinion. Persona diversity (0.095) matches the real groups (0.095). The chosen attribute is the one whose groups differ most on similar questions (political ideology for OpinionQA, age for LatinoBarometro, activity status or age for ESS).
- **No leakage.** Audited on eval and dev: 0 examples with the target question's text, 0 held-out rows used as examples. Evidence labels are normalized so the same population spelled two ways cannot slip in.
- **A fixed benchmark-valid result.** Demographic personas beat invented personas on subgroup questions (+1.2 vs −2.8 against plain).

## 7. Caveats on every number above

- 411 covered eval questions and 166 dev questions. Confidence intervals are about ±4 points, so most gaps between versions are within noise.
- Everything is one run per configuration, Haiku only.
- The "persona count" signal comes from similar-question retrieval by text similarity. A better signal could exist; none we tried predicts where splitting helps.
- The earlier "leak ceiling" scores (68.7, then 57.0 after fixing label matching) use other groups' answers to the *same* question. They show how much similar data is worth. They are **not** benchmark scores.
- Tasks and datasets without demographics (Choices13k, NumberGame, Jester, and others) cannot have a demographic panel at all.

## 8. Corrections to things I said earlier

- Segments were **−12** on the 981 eval, not +2.1; it only helps on divided questions.
- The persona panel is **−1.9** overall; it wins on divided (+4.7) and loses on consensus (−7.9).
- Equal persona weights are worse, not better.
- My first leak ceiling (68.7) included duplicate and aggregate data; the corrected no-overlap figure is 57.0.

## 9. Options from here

| Option | What it tests | Rough cost |
|---|---|---|
| Sonnet 5.5 in the persona seat, per-question persona count | Does a stronger model make personas both accurate and different from each other | ~$10 to $12 for eval + dev (estimate) |
| Keep v4 as the product: best predictor sets the level, demographic personas supply offsets and the explanation | Observability on top of the best accuracy we have (52.0 on covered questions) | Free (offline) |
| Outside representative data as evidence (national toplines, cross-national releases of the same instruments) | How much of the leak ceiling survives with real outside sources | Data work, then ~$5 per eval |
| Demographic intersections (e.g. age x gender) | Whether finer groups differ more than single-attribute groups do | ~$5 to $10 |

## 10. Where the code and results are

- Harnesses: `src/human_sim/simbench_ablate.py` (`C5_demo_mix`, `C5b_demo_mix`, `C6a_demo_agree`, `C6b_demo_individuals`, `C7_split_own`, `P_strict5`, `L_strict`).
- Scoreboard: `src/human_sim/simbench_panel_criteria.py`.
- Versions: `simbench_panel_temper.py` (v1), `simbench_panel_offsets.py` (v4), `simbench_panel_dynamic_k.py` (v5), `simbench_real_group_diff.py` (the real group-difference measurement).
- Results: `results/simbench_ablate/*_report.json`, `panel_offsets_examples.json` (per-persona breakdown example).
