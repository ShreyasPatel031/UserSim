# How reliable are the "what they will say" numbers? (orchestrator 09:50Z Nov 12)

Script: judge_reliability.py. About $1.6 of Gemini.
- Simulated lists were held fixed:
  - S300: 60 of the reactions_v2 300, using the BEST lists, stratified by comment volume.
  - FRESH: 36 fresh page-read launches, single run.
- Per launch: truth extraction ×3 (reactions_eval TRUTH, flash, temperature 0). Per extraction:
  - JUDGE ×3 (the original judge);
  - JUDGE2 ×1 (reactions_v2's second judge; covered = "same specific point");
  - a generic constant list (6 typical launch comments) ×1.

## Headline with all noise sources

Format: mean over all extractions × judges, [95% total interval: hierarchical bootstrap over launches, extraction and judge].

| set | recall | precision | second judge (recall / precision) | constant list | chance-corrected (minus constant) |
|---|---|---|---|---|---|
| S300 BEST (claimed 50 / 51) | **48.4 [43.1, 53.0]** | **53.0 [46.7, 59.2]** | 25.3 / 33.5 | 14.4 / 18.0 | 34.0 / 35.0 |
| FRESH page reads | **41.6 [33.9, 49.3]** | **41.1 [33.3, 49.1]** | 15.8 / 20.5 | 13.0 / 15.3 | 28.7 / 25.8 |
| all 96 | 45.8 [41.6, 50.1] | 48.5 [43.6, 53.8] | 21.7 / 28.6 | 13.9 / 17.0 | 32.0 / 31.6 |

## Noise components

Variance shares across launch / extraction / judge:

| set | recall | precision |
|---|---|---|
| S300 | 54 / 31 / 15% | 69 / 14 / 17% |
| FRESH | 74 / 13 / 13% | 72 / 10 / 18% |

- Per launch, one re-extraction moves a score by about 8–11 points (sd), and one re-judging by about 8–10.
- Averaged over 36–60 launches this mostly washes out. The total interval is only 1–2 points wider than the launch-only one (S300 recall [41.2, 51.5] → [43.1, 53.0]).
- So the quoted launch-bootstrap intervals are close to honest. The noise that is not averaged away is the choice of judge.

## Judge agreement (item-level Cohen's kappa, all 96)

| | a_covered (recall items) | b_present (precision items) |
|---|---|---|
| same judge, run 1 vs run 2 | 0.87 | 0.86 |
| JUDGE vs JUDGE2 | **0.47** | **0.55** |

- The second judge only counts "the same specific point", so it gives about half the original score: 22 / 29 vs 46 / 49.
- The headline is a judge-definition number. A strict reading halves it.

## By comment volume and theme count (S300, first extraction / judge)

| comments | 5–9 | 10–19 | 20+ |
|---|---|---|---|
| precision (n) | 37.0 (9) | 47.5 (27) | **61.1 (24)** |
| constant-list precision | 9.3 | 16.7 | 22.2 |
| recall (n) | 39.0 | 45.0 | 51.0 |

- Precision is inflated on launches with many comments: more and broader themes to hit, and the constant list rises too, 9 → 22.
- Corrected for the constant, the gain is flatter: 28 → 31 → 39.
- Most launches hit the cap of 8 themes (69 of 96); recall is not higher on the capped ones.

## Scoring rules (total interval; the width per call barely changes)

| rule | recall interval (all 96) | calls per launch |
|---|---|---|
| 1 extraction × 1 judge (current) | [41.6, 50.1] | 2 |
| 1 extraction × majority of 3 judges | [42.4, 50.7] | 4 |
| mean of 3 extractions × 1 judge | [42.1, 49.5] | 6 |

The current rule is the most efficient per dollar. Extra extractions or judges narrow the interval by under 1 point.

## Restated

| | recall | precision | 2nd judge | chance-corrected |
|---|---|---|---|---|
| BEST | 48 [43, 53] | 53 [47, 59] | 25 / 34 | 34 / 35 |
| fresh page reads | 42 [34, 49] | 41 [33, 49] | 16 / 21 | 29 / 26 |

The page-read 48 / 52 from try_e2e was not re-scored (its lists were not in this set); the fresh row is the page-read restatement.

## Honest sentence for the site

"Our simulated reactions match about half of the themes real users raised (about 45–50%, give or take 5 points) by our automated
judge; a stricter second judge that counts only the same specific point puts it at about a quarter; a generic list of typical launch
comments scores about 15% on the first judge. Page reads score lower than a pasted launch description."

# Which judge is right? Adjudication (orchestrator 09:59Z; judge_adjudicate.py, about $1.3)

Setup:
- All items of the 96 launches (extraction 1), not a sample: 576 simulated reactions (precision items) and 717 real themes (recall items).
- Adjudicated by gemini-2.5-pro at temperature 0. It sees the real comments as well as the theme labels.
- Rubric: SAME_POINT / SAME_TOPIC (same area or generic sentiment, different point) / UNRELATED.
- Adjudicator self-agreement (rerun on 48 launches): 92% / 84% exact; kappa(same point) 0.88 / 0.72.

## The disagreement cell

| precision items (simulated reaction vs real comments) | n | SAME_POINT | SAME_TOPIC | UNRELATED |
|---|---|---|---|---|
| both judges yes | 151 | 43.0 | 53.6 | 3.3 |
| **lenient yes, strict no** | **121** | **20.7** | **72.7** | 6.6 |
| strict yes, lenient no | 13 | 7.7 | 69.2 | 23.1 |
| both no | 291 | 3.8 | 49.1 | 47.1 |

| recall items (real theme covered by the list) | n | SAME_POINT | SAME_TOPIC | UNRELATED |
|---|---|---|---|---|
| both yes | 153 | 72.5 | 27.5 | 0 |
| **lenient yes, strict no** | **163** | **47.2** | **44.2** | 8.6 |
| both no | 394 | 17.8 | 33.5 | 48.7 |

## Each judge against the adjudicated standard (precision / recall of the judge's "yes", kappa)

| judge | reactions vs SAME_POINT | reactions vs POINT or TOPIC | themes vs SAME_POINT | themes vs POINT or TOPIC |
|---|---|---|---|---|
| lenient (site's JUDGE) | 33 / 88, κ 0.30 | 95 / 61, κ 0.40 | 60 / 72, κ 0.42 | 96 / 59, κ 0.41 |
| strict (JUDGE2) | 40 / 65, κ 0.36 | 95 / 37, κ 0.21 | 72 / 44, κ 0.37 | 100 / 31, κ 0.21 |

Reading:
- The site's judge is effectively a "same topic" judge. 95% of its yes verdicts are at least the same topic; only 33% are the same point on reactions.
- Neither judge measures "same specific point" well (κ 0.30–0.42).
- On the reactions the judges disagree on, the adjudicator sides with the strict judge 4 to 1 (73% topic-only, 21% same point).

## Headline restated under the adjudicated standards (launch means, 95% bootstrap)

| | standard | recall | precision | constant list recall / precision (24 launches) |
|---|---|---|---|---|
| BEST (S300, PH descriptions) | SAME_POINT | **43.7 [36.8, 50.9]** | **24.2 [18.1, 30.0]** | 7.9 / 10.4 |
| | POINT or TOPIC | 77.7 [72.1, 83.1] | 78.3 [72.2, 84.2] | 20.1 / 33.3 |
| fresh page reads | SAME_POINT | **24.4 [14.0, 35.9]** | **6.9 [3.2, 11.6]** | 11.5 / 17.4 |
| | POINT or TOPIC | 62.5 [51.4, 73.3] | 65.3 [55.6, 75.0] | 25.1 / 44.4 |

- From PH descriptions, about 1 in 4 simulated reactions makes the same specific point as a real comment, and the list covers about 4 in 10 of the real themes. Both are well above the generic list.
- From a page read alone, same-point precision is 7%, BELOW the generic constant list (17%, which earns credit for generic congratulations / pricing questions). Same-point recall is 24% vs 12%.
- 10 anonymised disagreement examples are in the bucket only: gs://…/usersim_sim/tmp/e5/judge/disagreement_examples.json. The adjudicator labelled 7 of them SAME_TOPIC and 3 SAME_POINT.
