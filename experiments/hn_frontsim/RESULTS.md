# HN front-page dynamics simulator: Caught at 15 min (Nov 2)

Shreyas approved this on exp-2. Every run is CPU-only and takes about 15 minutes locally; exp-2 was started for setup and then stopped.

## Setup

Code: `frontsim.py`. Numbers: `frontsim_results.json`.

- **Test set:** posts Oct 2-14, 12,788 posts and 388 winners. This is the same as the HN agent's caught.Q.
- **Winner:** the post appears in any daily top 30.
- **Flags:** as many as there are winners.
- **Intervals:** 95%, resampling posting days.
- **Reference:** the HN agent's wb15 "+ votes + who + exposure (direction A)" scores (forward daily retrain, train <= d - 2). They reproduce exactly: 29.6% [25.6, 33.7].

## What the simulator does

- **Quality.** q is upvotes per unit of Quality News exposure.
  - The prior is q = exp(b z) * u. Here z is an at-posting LightGBM score with 127 inputs: POST text_score and b_*, kNN, embedding, crowd, crowd v2 and hist_prior. Training posts get out-of-fold scores.
  - u is a nonparametric (NPMLE) grid fitted on 79,762 training stories, Jul 14 - Sep 30. The fitted b is 1.0.
- **Early votes.** The likelihood is (score - 1) ~ Poisson(kappa q E0)^tau.
  - E0 is position-weighted /newest page-1 minutes, from Wayback captures up to the snapshot age, times the hour's /newest traffic.
  - tau and kappa are fitted forward each day by the predictive likelihood of later votes. The fitting set is training posts plus test days <= d - 2.
- **Exposure.** Every 10 minutes, by front-page rank x hour, or off the front page by age x hour. The source is Quality News qn_exp_10m.
- **Rank.** HN's score, (P - 1)^0.8 / (age_h + 2)^1.8, times a penalty drawn per run. It is compared with the effective scores by rank of a random earlier day's front page at the same clock time.
  - The earlier day is a weekday or a weekend day to match the post, and is at least 3 days before the test day.
  - Only days whose front page Quality News reconstructs (90%+ of slots) are used: 58 weekday days and 14 weekend days.
- **Output.** 24 hours of Poisson votes per draw, 200 draws. The score is P(daily top 30 | 24 h points), isotonic on training posts.
- **Real-front-page variant.** It uses the real front page at t + 15: the posts on it then, their effective scores projected with a growth table learned in training, plus arrivals replayed from an earlier day.
- **No leakage.** A test post's own Quality News series is never read.

## Results

| scorer (Caught at 15 min, Oct 2-14) | Caught | vs wb15 |
|---|---|---|
| wb15 (+ votes + who + exposure) | 29.6% [25.6, 33.7] | |
| at-posting score z alone | 21.6% [17.8, 25.7] | |
| 15-min /newest score alone | 11.6% [8.1, 15.0] | |
| simulator, flat prior | 11.6% [8.0, 15.7] | |
| **simulator, at-posting prior** | **22.7% [17.3, 29.1]** | -7.0 [-10.8, -3.0] |
| wb15 + simulator, equal logit blend (fixed in advance) | 27.3% [22.4, 33.3] | -2.3 [-5.2, +0.5] |
| wb15 + simulator, forward logistic blend (days <= d-2) | 28.1% [22.6, 33.6] | -1.6 [-6.2, +1.6] |

- Simulator vs at-posting z alone: +1.0 [-1.6, +4.3].
- On the 10 days with 90%+ /newest coverage (287 winners), wb15 scores 30.0% and the simulator 24.4%. The equal blend is -2.4 [-5.9, +0.3] and the forward blend -2.4 [-8.2, +1.7].
- **Real vs replayed front page.** This is testable only on the 7 October days that Quality News reconstructs (215 winners): 21.4% vs 22.3%, -0.9 [-6.6, +7.4].
  - From Oct 11 the bucket's series cover only 7-10 of the top 30 ranks per slot.
  - Even on covered days, the reconstructed real front page is too empty: 55% of simulated posts reach the top 30, against 6% that really do.
  - So this variant is not a valid test yet. It needs the full front page, which live hn_minute provides from Nov 2.

## Findings

1. **Early votes.** Without a /newest denominator, the fitted early-vote weight was 0.
   - With position-weighted /newest exposure it is small but positive: tau 0.05-0.1, with kappa at the low edge of the grid.
   - The predictive log-likelihood gain over no early votes is +4 (train only) to +56 (with Oct 2-10 added). The untempered update is 450+ worse.
   - At 15 min, winners have a median of 2 points.
2. **Where the signal is.** The simulator keeps the at-posting ranking and adds about +1, which is not significant.
   - Every gain over wb15 would have to come from who commented and the exposure features, which the simulator does not see.
   - No version beats wb15, and no blend has an interval above 0.
3. **Realism gaps.** Calibration is off: the sum of P(top 30) is 1,177 against 388 winners.
   - The replayed front page lets 14% of posts reach the top 30. Quality News shows 6%, which is itself an undercount.
   - The real-front-page variant has no usable October data.

## Next

- Run the real-front-page variant on live hn_minute, which has the full front page every minute, for Nov 2 onward once the lists settle.
- Calibrate the reach of the top 30, for example with a per-day threshold for the list.
- Add the wb15 inputs (who commented, exposure) as quality-prior conditioning.
