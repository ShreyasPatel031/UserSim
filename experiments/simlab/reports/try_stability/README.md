# Is /try stable? (orchestrator 09:08Z Nov 12)

Script: try_stability.py.
- Sample: 60 of the fresh 130 page-read launches, 20 per final-rank tertile. Everything runs through the site's own code.
- Control floor: a different product's outputs (fixed derangement).
- Values in brackets are 95% bootstraps. Gemini flash / flash-lite only, about $1.
- A first run was invalid: the local in-memory test caps (150 a day) blocked most runs. The live counter was untouched. Rerun with the caps lifted; 60/60 for every arm except hero text.

## Band (page band percentile; 10 points = one decile)

| comparison | mean abs. percentile diff | pairs > 1 decile apart | Spearman across the 60 |
|---|---|---|---|
| same URL, rerun (3 pairs) | 7.1–8.1 | 16.7–20.0% | 0.92–0.93 [0.86, 0.97] |
| same URL, read at temperature 0 (2 runs) | **0.0** | **0%** | **1.00** |
| linked page vs root domain (22 that differ) | 17.0 | 36.4% | 0.75 [0.45, 0.90] |
| page read vs pasted PH description (different band models) | 28.4 | 65.0% | 0.45 [0.20, 0.64] |
| page read vs pasted 2-sentence / long copy / hero | 19.3 / 21.8 / 23.9 | 43 / 58 / 50% | 0.69 / 0.57 / 0.58 |
| **different product (floor)** | **37.7** | **68.3%** | **−0.08** |

- Rerun sd is 6.2 percentile points (floor 26.7). As median rank in the served band, a rerun moves it by 0 ranks (mean 0.9); a different product by 2 (mean 3.1).
- Rerun noise comes from the read at temperature 0.2. The fetch adds none: at temperature 0, two reruns, each with its own fetch, gave identical bands on all 60.

## Accuracy by input (Spearman of band percentile with −final rank, n = 60)

| input | Spearman |
|---|---|
| **pasted real PH description** (PH band) | **0.535 [0.311, 0.700]** |
| pasted 2-sentence paraphrase | 0.384 [0.134, 0.595] |
| page read, single run (3 runs) | 0.326–0.391 |
| page read, mean of 3 runs | 0.369 [0.133, 0.551] |
| page read, temperature 0 | 0.337 [0.084, 0.536] |
| pasted hero text (34 that pass) | 0.315 [−0.042, 0.596] |
| pasted long marketing copy | 0.294 [0.036, 0.520] |
| root domain (22) | 0.267 [−0.136, 0.609] |

- What to ask visitors to paste: the real launch description is best.
- Hero text is not enough. It fails the 80-character / page-judge checks on 26 of 60, and is weaker when it does pass.
- Long marketing copy hurts (0.29 vs 0.38 for 2 sentences).
- Averaging 3 reads does not raise accuracy (0.37 vs 0.33–0.39); temperature 0 costs nothing (0.34).

## Reactions and ranked lists

| | rerun agreement | different product (floor) |
|---|---|---|
| reactions (judge: B reaction raises the same specific point as some A reaction) | **56.4% [49.7, 63.1]** | 0.8% |
| reactions, page read vs pasted PH description | 30.3% | |
| ranked concerns, overlap@3 (30 launches) | **46.7% [40.0, 54.4]** | 4.4% |
| ranked questions, overlap@3 (30) | **58.9% [50.0, 67.8]** | 5.6% |

Reactions precision against real comment themes (20 launches with at least 5 comments):
- page read: 9.2% [4.2, 14.2]; second run 10.0%.
- pasted PH description: 19.2% [10.0, 29.2]. The PH-description input helps reactions too.

## Verdict (text the site could show)

"Rerunning the same page moves the band by less than one rank on average (about 6 percentile points). Users' reactions agree about
56% between reruns, and the top-3 concerns / questions about 47% / 59%. A different product agrees about 1–6%. Pasting your real launch
description gives the most accurate band."

## Free fixes, measured

- **Temperature 0 for the read** makes the band fully repeatable (sd 6.2 → 0.0) at no accuracy cost (0.337 vs 0.326–0.391).
- **Caching by URL hash** gives the same answer for the same page by construction.
- **Averaging 3 reads** costs 3× the reads for no measured gain. Not recommended.
