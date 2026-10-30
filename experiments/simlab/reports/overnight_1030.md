# Overnight Oct 29–30: does the page change who votes, and does that raise the launch score?

All tests are out of sample (train on earlier months, test on the next). No Claude calls. Gemini spend tonight: about $0 (all local models).

## Results

| Direction | Test | Result | Verdict |
|---|---|---|---|
| Page-aware person model (psp) | Person picks in line-up, 6 months | AUC 0.668 → 0.681, top-3 hit 46.7 → 47.0 | small gain |
| Page-aware person model → launch score | daily top 3/5/10, Apr–Oct, live config | 64.5/70.8/79.1 → 63.8/70.3/79.2 (+psp); simulation only 38.5 → 37.1 | **no gain** |
| Person taste for page traits (page_taste.py) | Same within-person test | AUC 0.681 → 0.692, top-3 hit 47.0 → 48.8, better in 6/6 months | **best person-level gain** |
| + Gemini persona ratings (Sep–Oct only) | Same test, 2 months | person 46.7 → all 50.9 top-3 hit (AUC 0.691 → 0.720); persona alone helps in 1/2 months | gain, only 2 months of data |
| Upworthy click-rate scorer (copytest/) | Held-out real headline A/B tests | 73.9% (34,210 pairs; Gemini zero-shot 57.0%) | replicates |
| Upworthy scorer → Product Hunt taglines | Corr. with over-performance at fixed reach | 0.016 (95% −0.017 to 0.047); matched pairs 50.4% | **does not transfer** |
| Appeal model (Hogg & Lerman: votes = reach × appeal), page-only | Corr. with real appeal within day | 0.138 (0.103–0.174) vs page lift 0.235; matched pairs 58.6% vs 55.9% | mixed: better on matched pairs, worse on correlation |
| Attribute-aware factorization (page_mf.py) | — | not run (VM stopped at 04:36 UTC) | dropped |

## Why person gains did not raise the launch score
The launch score sums each person's pick probability. The page inputs shift those probabilities about equally for everyone, so the sum ranks launches the same as reach does. Taste differs by person, so it is the one direction that can change the sum. That is the single direction being finished now: taste-aware population simulation (`TASTE=1 python -m simlab.popscore`) → launch test (`robust_src.py +pst =pst`).

## Taste-aware population simulation → launch score (Apr–Oct, live config)

| Daily top 3 / 5 / 10 | Full model | Simulation only |
|---|---|---|
| current (no person sim with page) | 64.5 / 70.8 / 79.1 | — |
| + person sim, no page (psn) | — | 38.5 / 51.8 / 64.3 |
| + person sim with page (psp) | 63.8 / 70.3 / 79.2 | 37.1 / 50.6 / 64.4 |
| + person sim with page + taste (pst) | 63.6 / 70.6 / 79.1 | **39.6** / 51.3 / 64.0 |

Taste helps the simulation alone (+1.1 top-3 over no page, +2.5 over page only) but adds nothing to the full model.
Next: choice-style aggregation (each person splits expected picks over the line-up; counts of people ranking it top 1 / top 3), so relative taste counts instead of raw activity.

## Choice-style aggregation (robust_pst2.csv)
Simulation only daily top 3: 39.6 → 39.8. Full model 63.9 (current 64.5). No real change.

## Does the simulated lift predict over-performance at fixed reach? (simlift.py, ctrl.py residual)
| Input | Corr. with over-performance (95%) | Matched-reach pairs |
|---|---|---|
| page lift in the sim (psp − psn) | 0.042 (0.009–0.077) | 51.8% |
| taste lift (pst − psp) | −0.044 (−0.074 to −0.014) | 49.2% |
| pst_top1 (people ranking it first) | 0.038 (0.002–0.075) | 56.2% |
| for comparison: page lift in the launch model (ctrl.py) | 0.233 (0.199–0.264) | 56.0% |
The person-level simulation does not carry the page's effect to the launch; the launch-level page model does.

## Ceiling (cover.py, Apr–Oct, 5,082 launches)
- Pool people cast 28% of real votes (39% for top-3 launches, 15% for rank 11+).
- Real pool votes track real total votes: within-day rank correlation 0.92.
- If each pool person's votes were known exactly, daily top-3 recall = 88.8%. The pool is big enough; the per-person prediction is the gap (simulation now 39.8).

## Where the simulation loses accuracy (oracle_split.py, taste model, Aug 1–Oct 24, 85 days)
| Launches ranked by | Daily top 3 | Top 5 |
|---|---|---|
| simulation (30-day population × model pick probability) | 41.6 | 54.8 |
| model pick probability over the people who really voted that day (who shows up known) | 43.1 | 55.3 |
| real picks of the 30-day population (what they pick known) | 91.4 | 92.9 |
| real votes of all pool people | 91.4 | 95.5 |
Knowing who shows up adds 1.5 points; knowing what they pick adds 50. The per-person pick model is the whole gap.
Next: stronger pick models (pick_boost.py: more training people, bigger trees, LambdaRank).

## Stronger pick models (pick_boost.py, 6 months, person + page + taste inputs)
| Learner | Top-3 hit | AUC |
|---|---|---|
| base (300 people/day) | 49.1 | 0.695 |
| 1,000 people/day | 49.2 | 0.697 |
| bigger trees | 49.3 | 0.696 |
| LambdaRank | 49.1 | 0.698 |
| LambdaRank, bigger | 48.1 | 0.693 |
Learner and data size are saturated; the inputs are the limit.
Next: herding (Salganik; Hogg & Lerman). Each simulated person also sees how popular the simulation's first pass made each launch (never real votes): `HERD=1 popscore` → robust_src +psh =psh.

## Herding (robust_psh.csv)
| | Full model day top 3 / 5 / 10 | Simulation only |
|---|---|---|
| taste (pst) | 63.9 / 70.7 / 79.1 | 39.8 / 51.0 / 64.6 |
| taste + simulated popularity (psh) | 63.6 / 70.3 / 79.2 | 36.1 / 51.6 / 64.4 |
Worse on the daily top 3; weekly/monthly lists improve (week top 3 21.7 → 30.0, month 10.5 → 14.3) but those have 21 weeks / 7 months. Not adopted.
Next: Gemini persona ratings (largest person-level gain) tested at launch level over the rated people (persona_launch.py).

## Persona ratings at launch level (persona_launch.py; train Sep, test Oct 1–24, rated people only, 6,876 person-days)
| Simulation over rated people | Day top 3 | Top 5 |
|---|---|---|
| person + page + taste | 43.1 | 50.8 |
| + Gemini persona ratings | 43.1 | 54.2 |
| real picks of these people (ceiling) | 84.7 | 86.7 |
Top 5 +3.4 on 24 days (small). ~290 rated people a day already give an 85% ceiling: more people is not the gap, predicting each one's picks is.
Next: listwise Gemini picker (llm_pick.py: past upvotes + full line-up → 3 picks). Pilot 20 person-days, $0.007.

## Listwise Gemini picker (llm_pick.py; Oct 1–24, 1,500 real person-days, $0.52)
| Top-3 hit (person's real pick among the 3) | |
|---|---|
| random 3 | 20.4 |
| Gemini 2.5 Flash, past upvotes + line-up | 28.0 |
| taste person model (train Sep) | 50.1 |
| Gemini picks the model also ranks top 6, then model | 50.5 |
Content taste alone explains little of who picks what. Next: ablation of the person model's input groups (pick_boost.py ABLATE=1).

## Which person data carries the signal (pick_ablate.json, 6 months, 300 people/day)
| Inputs | Top-3 hit | AUC |
|---|---|---|
| all | 49.1 | 0.695 |
| without team ties (backed, similar people backed the team, recent team) | 44.0 | 0.664 |
| team ties only | 49.4 | 0.644 |
| without sequence | 48.5 | 0.692 |
| sequence only | 36.6 | 0.578 |
| without category | 49.1 | 0.692 |
| category only | 32.3 | 0.564 |
| without content (topic, meaning, page, taste) | 45.9 | 0.667 |
| content only | 42.9 | 0.657 |
Ties to the launch team decide the top 3; content improves the rest of the ranking. Relationship data is the source to extend.
Next: reciprocity (the team engaged with this person's own launches before; RECIP=1).

## Reciprocity (RECIP=1, pick_ablate_recip.json)
Top-3 hit 49.1 → 49.3, AUC 0.695 → 0.696. Covers ~1% of person-launch pairs; not worth it alone.
