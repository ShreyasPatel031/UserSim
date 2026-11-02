# Competitors' earlier Product Hunt outcomes as a demand prior (Nov 2, 2026; Grok Bot for the orchestrator and Shreyas)

Code: `simlab/cmp_outcomes.py`; data `reports/cmp_outcomes.json`.

**Hypothesis.** How a launch's real competitors (PH Similar Products) did on Product Hunt before its day predicts its own
launch-day demand. **Rule fixed before the run:** daily top 3 against the honest day-calibrated control, 95% interval above 0.

**Inputs** (dated outcomes only): for each launch, the earlier launches (before its day) of its similar products, matched
by product slug: best final daily rank; max and median final votes (only launches at least 7 days earlier, so the vote
counts have settled); days since the most recent one; their number; one in the last 30 days (crowding). The products'
ratings and review counts were read now and are not used.

**Setup.** Exactly `simlab/e1_honest.py`'s: the honest launch model as the offset (PH ops' `honest_preds`), the control is
offset + day terms, Poisson LightGBM, rolling monthly, May–Oct (3,977 launches, 176 days for daily top 3/5, 144 for top
10, 25 weeks), 5 seeds averaged, paired by day / week (10,000 resamples).

**Coverage.** 99.6% of launches have a similar-products list; 68.8% have at least one earlier-launched competitor in our
data (May 56.7% rising to October 77.9%).

| Model | Daily top 3 / 5 / 10 | Weekly top 3 / 5 / 10 | Log-lik / launch |
|---|---|---|---|
| Honest launch model alone | 64.4 / 70.5 / 76.9 | 45.3 / 54.4 / 55.7 | −14.132 |
| Control (day-calibrated) | 64.4 / 70.5 / 76.9 | 50.7 / 56.0 / 54.8 | −13.900 |
| + competitor outcomes | 63.3 / 70.1 / 76.8 | 48.0 / 56.8 / 55.2 | −14.182 |

| + competitor outcomes − control | Daily top 3 | Top 5 | Top 10 | Weekly top 3 | Weekly top 5 | Weekly top 10 | Log-lik |
|---|---|---|---|---|---|---|---|
| Difference | −1.1 [−3.0, +0.8] | −0.3 [−1.5, +0.8] | −0.1 [−0.9, +0.8] | −2.7 [−9.3, +4.0] | +0.8 [+0.0, +2.4] | +0.4 [−0.9, +2.2] | **−0.43 [−0.67, −0.20]** |
| Months better / tied / worse | 2 / 1 / 3 | 1 / 1 / 4 | 2 / 3 / 1 | | | | |

Daily top 3 by month (with competitors vs control): May 58.1 vs 61.3, Jun 66.7 vs 66.7, Jul 68.8 vs 67.7, Aug 66.7 vs
65.6, Sep 60.0 vs 63.3, Oct 58.3 vs 61.1.

**Verdict: fails.** Competitor outcomes do not add daily value (−1.1, interval spans 0, worse in 3 of 6 months) and make the
total-vote likelihood worse (−0.43, interval below 0): the model fits noise in them. This agrees with the PH agent's test of
competitor page gaps against the day-calibrated control (daily top 5 −1.2 [−2.0, −0.6]). Competitor grounding, as outcomes
or as page gaps, does not help the pre-launch daily ranking.
