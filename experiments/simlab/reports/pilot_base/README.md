# Vertex Gemini baselines for the Decisions API pilot (orchestrator 04:34Z Nov 13)

**Files.**
- Script: pilot_base.py.
- Prompts: pilot/prompts.json, with the Decisions API equivalents noted.
- Samples, for exact reuse: gs://…/usersim_sim/tmp/e5/pilot/pilot_sample.json (hashed person ids, days, line-up order) and pilot_launch_sample.json.

**Cost.** About $1, estimated: flash-lite plus flash, thinking off. The rerun logged only $0.05 because calls were cached. Flash median latency is 0.9 s per call.

## (A) Person level

**Sample.** 1,442 person-days (1,354 with a usable answer). 5 test days: Oct 25, 26, 30, Nov 1, Nov 4. Up to 300 people per day who upvoted ≥ 1 line-up launch.

**Card.** The person's 30 most recent dated upvotes (product and tagline), plus the line-up with a follows-team flag. There are no names, no handles and no headline (the store has no profile text).

**Metrics.** % [95% CI] per person-day; differences are paired bootstraps over person-days.

| | top-3 hit | ranking accuracy |
|---|---|---|
| popularity (clean 00:05) | 49.4 | 76.6 |
| popularity + follows | 49.5 | 77.7 |
| flash-lite | 36.2 | 58.0 |
| flash | 29.6 | 61.3 |
| flash-lite − pop+follows | −13.3 [−15.6, −11.0] | −19.6 [−21.1, −18.3] |
| flash − pop+follows | −19.9 [−22.4, −17.4] | −16.3 [−17.5, −15.1] |
| blend (rank mean) flash-lite − pop+follows | −4.5 [−6.1, −2.9] | −2.8 [−3.3, −2.2] |
| blend flash − pop+follows | −7.1 [−9.2, −4.8] | −3.5 [−4.1, −2.9] |

Popularity levels here (49.4 / 76.6) are higher than person_choice's 30.1 / 66.9 because the sample and days differ. Compare only within this table.

**Launch score** (sum of p over the sampled active people; indicative only, 5 days). Mean within-day Spearman with final rank:

| | Spearman | partial beyond clean |
|---|---|---|
| flash-lite | 0.457 | +0.093 |
| flash | 0.361 | +0.056 |
| clean score | 0.614 | – |

**Verdict.** The LLM-as-person simulation is far below popularity, and blending only hurts. This is the bar the Decisions API must clear.

## (B) Launch level

flash gives P(top 10) and P(top 3) from name, tagline, topics and description. Data: 354 launches, 14 days (Oct 26 – Nov 11, with clean_v3_nosite). Leave-day-out ridge on top of clean_v3_nosite; th_n_pre is not held for these days.

| gain vs clean (64.3 / 70.0 / 76.4) | top 3 | top 5 | top 10 |
|---|---|---|---|
| + P(top 10) | 0.0 [−7.1, +7.1] | −2.9 [−7.1, 0.0] | −0.7 [−2.1, 0.0] |
| + P(top 3) | −4.8 [−14.3, +4.8] | −2.9 [−7.1, 0.0] | −0.7 [−2.1, 0.0] |
| P(top 10) alone | −38.1 | −40.0 | −22.1 |

**Calibration, P(top 10).**

| stated | actual |
|---|---|
| 0.33 | 0.31 |
| 0.43 | 0.37 |
| 0.65 | 0.41 |
| 0.84 (n = 14) | 0.86 |

**Calibration, P(top 3).**

| stated | actual |
|---|---|
| 0.15 | 0.12 |
| 0.33 | 0.16 |
| > 0.5 (n = 10) | 0.0 |

It is overconfident in the middle and upper bins.

**Verdict.** No gain over the clean model, and the probabilities are poorly calibrated.

## (C) Pairwise near-ties (orchestrator 05:34Z Nov 13). Script: pairwise_base.py; prompt in pilot/prompts.json "pairwise"

**Method.**
- Model: gemini-2.5-flash, temperature 0.
- Pairs: all 21 pairs among the clean model's ranks 2–8, asked in both orders, using 00:05 text only.
- Ranks 2–8 are re-ordered by total wins and by Bradley-Terry strength.

**Data.** LIVE = Oct 26 – Nov 11 (clean_v3_nosite). BACK = 40 random honest_preds_v2 days, Apr – Oct, possibly inside the training data (36 days had ≥ 10 launches). Cost $0.34.

| | days | pair accuracy vs final order | clean top 3 / top 5 | wins − clean | Bradley-Terry − clean |
|---|---|---|---|---|---|
| LIVE | 14 | 56.2% | 64.3 / 70.0 | −14.3 [−21.4, −4.8] / −11.4 [−20.0, −2.9] | −14.3 [−23.8, −7.1] / −11.4 [−20.0, −2.9] |
| BACK | 36 | 50.5% | 56.5 / 65.6 | −13.9 [−23.1, −4.6] / −7.2 [−12.8, −1.7] | −13.9 [−23.1, −5.6] / −7.2 [−12.8, −1.7] |

**Verdict.** Within the near-tie band, the LLM's pairwise call is close to a coin flip (50–56%). Re-ordering by it loses 7–14 points of top 3 / top 5. Null, and harmful.

## Decisions API harness (decisions_harness.py): dry run, nothing sent

Every request for the fixed samples is built and validated against the documented schema, with 0 errors:

| use | requests | questions | max questions / request | est. input tokens | est. cost |
|---|---|---|---|---|---|
| person (1,442 person-days) | 1,442 | 31,794 | 34 | 2.26M | $0.23 |
| launch (14 days; top-10, top-3, band + 21 pairs per day) | 14 | 1,348 | 171 | 87k | $0.01 |
| judge (300 pro-labelled items, 144 launches; pro SAME_POINT share 20%) | 144 | 300 | 5 | 111k | $0.01 |

Scaling estimates:
- The 14,000-card summed-simulation test would cost about $2.2.
- 60 backtest launch days would cost about $0.04.

The judge sample (real comment text) lives in the bucket only: tmp/e5/pilot/judge_sample.json, built by decisions_judge_sample.py.
