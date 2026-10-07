# Close-out: full SimBench 62.86

Branch `claude/blissful-pascal-0ldgye` at `e2c61d9`. Nothing from the LatinoBarómetro / ESS follow-up was kept, so the full score stays **62.86** on 13,510 questions.

The session that produced this stopped while renaming a scratch script called `dis.py` (that name shadows Python’s `dis` module). The rename never landed, and no visualization script was committed. This note is the record of where that run ended.

## Score path

| Checkpoint | Full score |
| --- | --- |
| Model only (`retr6_rev2`) | 41.46 |
| Pick-one rule | 50.15 |
| Label prior + cognitive models | 57.57 |
| Two-way decomposition extended | 58.29 |
| Scenario model + OpinionQA / shallow prior | 60.01 |
| 3 cross-validated tuning rounds | 62.03 |
| 5 further rounds | 62.86 |

A tuning change is kept only when the 5-fold paired interval sits entirely above zero.

## What added the points

From 41.46 to 60.01, points of the full score (lift on that slice times its share of 13,510):

| Source | Questions | Points on the full score |
| --- | --- | --- |
| Disjoint groups in the same country | 3,362 | +10.02 |
| Cognitive models (Choices13k, NumberGame, MoralMachine) | 1,416 | +3.88 |
| Same question, other countries | 1,452 | +2.55 |
| Country total abroad + country offset | 1,283 | +1.05 |
| Same group abroad + group offset | 1,161 | +0.64 |
| Label prior, no anchor | 1,779 | +0.42 |
| Model left as-is | 3,057 | 0 |

The later +2.85 (60.01 to 62.86) is bracket retunes: decomposition +0.71, surveys with no decomposition +0.69, cognitive models +0.62, Jester / DICES / ChaosNLI and small sets +0.49, other-country anchors +0.34.

## The two brackets that did not move

Together 524 of 13,510 questions (3.9%). Perfect scores on both would add about 2.5 points to the full score. They are the lowest brackets. They are not a third of the benchmark.

**LatinoBarómetro, same group in other countries.** 414 questions, score 36.2. Those 414 rows are 14 distinct questions. El Salvador on “is this country progressing?” is 85% “progressing”; the same groups in other Latin American countries mostly say “in decline”. Country pairs share a median of 4 questions. Similarity weighting moved the source alone from 25.9 to 27.6; blending it cost −1.1, interval (−3.3, +1.1). An oracle that picks the best other country after seeing the answer reaches only 46.6, and −1.9 on El Salvador. The allowed data does not contain that answer. The population that does (other subgroups in El Salvador) overlaps the target, so the overlap rule excludes it. Tried in rounds 3, 5, and 6, and again after round 8. Nothing kept.

**ESS, base rates only.** 110 questions, score 37.2. 42 were never asked in another country; a label prior there scores 26.6, worse than the current prediction. On the other 68, a plain average of foreign answers scores 28.9 against the current 35.7. Matching the target’s attribute scored −0.9, interval (−4.5, +2.6). An oracle that picks the best group abroad after seeing the answer reaches 74.5, which is a peek across dozens of groups. Country pairs share a median of 1 question. Tried in rounds 3, 5, and 8. Nothing kept.

## How to read the next miss

1. How many distinct questions are hiding inside the row count.
2. Oracle ceiling: does any allowed population have the answer at all.
3. Cross-validated interval: can a rule find that population before seeing the answer.
4. Which rule is blocking the population that actually carries the signal.

A worked example of (4) in the other direction — a tool that is allowed and still wrong — is the Botswana internet question in `structure_observability_examples.md`: the clustering tool puts unemployed job-seekers in Botswana into a rural-Benin segment and predicts 79% “never”, against a real 49% “never” / 24% “every day”.

## What would have to change

- Loosen the overlap rule so overlapping groups in the same country can inform the target question. Likely lifts LatinoBarómetro. Bends “no population overlap”.
- Add earlier LatinoBarómetro or ESS waves. Outside SimBench.
- New model calls (for example D3dyn) past the $15 cap. A few points at most. Does not fix an El Salvador-style outlier.
