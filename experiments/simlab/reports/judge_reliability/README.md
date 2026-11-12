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
