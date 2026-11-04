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

## Re-paired against the corrected wb15 (Nov 2, later)

The HN agent confirmed the pandas-3 timestamp bug in wb15's exposure features, which had all been NaN. The earlier 29.6% "exposure" column was in effect votes + who commented + posting volume + hour. After the fix, the clean reference is "+ votes + who": 28.4% [23.8, 33.0]. The simulator scores below are the same saved scores as above; this is `frontsim_vs_wb15_fixed.json`.

| vs "+ votes + who" (28.4%) | all days | 90%+ coverage days |
|---|---|---|
| simulator alone | -5.7 [-9.3, -1.5] | -4.9 [-9.7, -0.3] |
| equal logit blend | -1.3 [-3.5, +1.2] | -1.7 [-5.1, +1.8] |
| forward blend | **+0.3 [-1.9, +2.4]** | -0.7 [-3.0, +1.3] |

Against the fixed "+ votes + who + exposure" column (28.1%), the forward blend is -0.8 [-2.8, +1.1] and the equal blend -1.6 [-3.9, +0.8]. No interval is above 0, so the simulator adds nothing measurable yet.

Next: the v2 fit on Quality News per-minute series (raw/hn_qn_series/, being pulled by Data Feeder). They give /new rank per minute, which is the missing /newest exposure denominator. Arrival rates will be fitted on the covered set (3+ points); coverage is outcome-correlated, so it must not be used as an input when scoring.

## Live-page simulator on hn_minute (Nov 2 onward): calibration first

`live_frontsim.py` judges every post at 15 min using the real pages, read live:
- latest points by t + 15;
- /newest p1-2 position-weighted minutes;
- /news p1-3 at t + 15, with effective scores by rank interpolated over all 90 positions;
- birth times from the HN API.
Arrivals come from replayed Jul-Sep days. Labels are settled listwatch lists, as in live_caught.py. Nov 2 is the first full feed day (877 posts so far), and its lists settle around Nov 6. There is no live at-posting score yet, so the prior is flat (requested from the HN agent).

### Calibration, step by step

1. **As built** (October model, QN-likelihood tempering). Sum of P on Nov 2 was 102 to 141 against ~25-30 winners a day. On posts with 12 h+, simulated top-30 reach was 22-27% against 5.2% real, and simulated 24 h points averaged ~245 against 11.
   - First bug: unread front ranks counted as empty, so a 1-point post started near rank 1. Fixed by interpolating all 90 ranks, with a replay fallback when fewer than 60 are read.
   - The overshoot stayed after the fix. Its cause is the flat quality prior: median q is 0.7 because the low tail is barely identified.
2. **Training check** (Sep, prior only; `calib_reach.py`). Simulated reach is 11.6% against 6.4% real. A global q scale of c ≈ 0.6 matches both reach and 24 h points.
3. **Early votes on outcome data** (Oct 2-9 weekdays, dense snapshots). Real reach by 15-min score:

   | 15-min score | none | 1 | 2 | 3 | 4+ |
   |---|---|---|---|---|---|
   | real reach | 7.2% | 4.0% | 11.5% | 15.1% | 35.5% |
   | simulated, QN-likelihood tempering (tau ≈ 0.1) | 13-15% | 13-15% | 13-15% | 13-15% | 13-15% |
   | simulated, outcome calibration | 2.4% | 0.9% | 10.3% | 30.5% | 60.7% |

   The tempering fitted by QN predictive likelihood, which only sees posts ending with 5+ points, leaves early votes almost inert. The outcome data say they matter a lot. This is the selection effect the orchestrator suspected.
4. **Outcome calibration** (`calib_fit.py`): tau, kappa and c chosen by the per-post binomial log-likelihood of real reach on Oct 2-9. Best fit: tau 0.3, kappa 0.2, c 0.25. Overall reach is 5.5% against 7.0% real, but the response to early votes is now too steep (see the last row above). Real outcomes are noisier than the simulated rank feedback allows.
5. **Live Nov 2 with the outcome calibration.** Sum of P is 28.5 (isotonic) and 26.8 (day threshold), against an expected ~25-30 winners: right in aggregate. On the 194 posts with 12 h+:
   - Simulated reach is 15.1% against 5.2% real (10 posts). Posts with 1 point are matched (2.3% against 2.1%); posts with 2 points or more are overshot.
   - On reaching the top 30, the simulator ranks worse than the raw 15-min score: AUC 0.64 against 0.72.

Next:
- Add per-post dispersion (overdispersed votes, or late quality only partly tied to early quality) to fix the steep response.
- Use the live at-posting prior.
- Report Caught once the Nov 2 lists settle.

## Selection finding: QN-based fits under-weight early votes (applies to everything built on QN)

Quality News series exist only for posts that ended with 5+ points. Fitting how much early votes say about later votes by predictive likelihood on that set gives a small weight:
- tau = 0 without a /newest denominator;
- tau 0.05-0.2 with one.

On outcome data the picture is different. Oct 2-9 weekdays, 4,474 posts, all with an outcome-independent Wayback /newest snapshot by 15 min:
- Real top-30 reach rises from 4.0% (1 point) to 35.5% (4+ points).
- With the QN-fitted weight, the simulator's reach is flat across those bins at 13-15%.
- Fitting the same likelihood by the per-post binomial likelihood of real reach instead gives tau ≈ 0.3, with a steep response.

So "early votes carry little per vote" was largely an artifact of the QN selection, which compresses the variance of q. The direct check on unselected data (Wayback /newest 2025, raw/hn_early_votes_2025/) will be run when it lands.

## Decision-rule runs (orchestrator): Oct 2-9 top-30 reach AUC, simulator vs raw 15-min score

Rule: if, after per-post dispersion and the at-posting prior, the simulator still does not rank top-30 reach above the raw 15-min score, stop the standalone simulator. Instead hand the HN agent the outcome-calibrated reach table and the vote-arrival model. Results: `calib_auc_*_results.json`. The interval resamples days.

| step | params | simulated reach | AUC simulator | AUC 15-min score | difference |
|---|---|---|---|---|---|
| outcome calibration, no dispersion | tau 0.3, kappa 0.2, c 0.25 | 5.6% | 0.656 [0.612, 0.687] | 0.648 [0.617, 0.683] | +0.008 [-0.045, +0.070] |
| step 1: + per-post dispersion (sigma 1.0) | tau 0.3, kappa 0.2, c 0.25 | 7.4% | 0.656 [0.620, 0.692] | 0.648 | +0.008 [-0.032, +0.044] |
| step 2: + at-posting prior (out of sample) | b 0.25, tau 0.3, kappa 0.2, c 0.25, sigma 1.0 | 8.3% | 0.712 [0.683, 0.732] | 0.648 | +0.064 [+0.002, +0.106] |

Real reach on these days is 7.0%. Dispersion improves the reach log-likelihood (-1140.5 against -1150.7) and the overall level, but not the ranking. The 0.64 against 0.72 quoted earlier came from 194 live Nov 2 posts with only 10 reachers, and was noisy.

### Step 2 and the decision (Nov 3, 05:20 UTC)

The at-posting prior is the HN agent's odds-tool P(top 30) at posting (`atposting_hist.parquet`, Sep 1 - Oct 14). It is **out of sample** (the tool was fit Jul 1 - Aug 15 and calibrated Aug 16-31; the HN agent corrected its earlier in-sample caveat), so step 2 is an honest test. The prior was refit on Sep 1-30 (b = 0.25). File names carry "insample" from before the correction.

The literal rule passes: the simulator scores 0.712 against 0.648 for the 15-min score, +0.064 [+0.002, +0.106]. But that comes from the at-posting score. The simulator adds nothing over its own two inputs:
- At-posting score alone: AUC 0.705 [0.695, 0.715]. The simulator minus it: +0.006 [-0.024, +0.029].
- Unfitted rank-average of the at-posting score and the 15-min score: AUC 0.727. The simulator minus it: -0.016 [-0.071, +0.012].

**Decision: the standalone simulator stops.** Handed to the HN agent (`hn_handoff_e5.json`, also at `hn_jobs/cache/e5_handoff/`):
1. The outcome-calibrated reach table by 15-min score.
2. The vote-arrival model: exposure by rank x hour and off-front by age x hour, plus the outcome-fitted early-vote likelihood.

The live simulator (live_frontsim.py) keeps running only as a shadow; its Nov 8 Caught for Nov 2 posts is reported as a shadow number, not a bet.

### Handoff refit on September only (Nov 3, for the Oct 2-14 backtest)

The Oct 2-9 fit overlaps the HN agent's Oct 2-14 backtest, so the reach table and early-vote likelihood were refit on September alone: 20 weekdays whose front page reconstructs, and 1,325 posts with a Wayback /newest snapshot by 15 min. Of those, 87 reached the top 30 (6.6%). Results are in `calib_fit_sep_results.json` and in `hn_handoff_e5.json` under `*_sep`.

| 15-min score | 1 | 2 | 3 | 4+ |
|---|---|---|---|---|
| real reach, Sep | 3.9% | 10.7% | 19.6% | 35.5% |
| real reach, Oct 2-9 | 4.0% | 11.5% | 15.1% | 35.5% |
| simulated, Sep fit | 1.1% | 13.7% | 35.4% | 58.8% |

Best Sep fit: tau 0.3, kappa 0.05, c 0.25, sigma 0. A runner-up within 0.1 log-likelihood is tau 0.6, kappa 1.0, c 0.15. The Oct fit was tau 0.3, kappa 0.2, c 0.25, sigma 1.0.

The real reach table is stable between months. The simulated table is still too steep, as it was in October.

The HN agent tested the September reach table as a 15-min input to wb15's "+ votes + who" on Oct 2-14 (forward daily retrain, paired): 28.4% became 27.6%, a change of -0.8 [-3.1, +1.5]. There is no gain, because wb15 already sees the raw 15-min score. The handoff is closed (HN agent's reach15.py). The vote-arrival fit is kept for its live per-minute model.

### Live shadow: full 24 h calibration for Nov 2 (run Nov 4, 00:45 UTC)

913 Nov 2 posts have a full 24 h of feed. The prior is flat (the live at-posting score is loaded but not used). The early-vote likelihood uses the October outcome fit. File: `live_frontsim_nov02_24h.json`.

| | real | simulated |
|---|---|---|
| top-30 reach within 24 h | 8.0% (73 posts) | 15.0% (136.6) |
| reach, 1 point at 15 min (624 posts) | 2.6% | 3.5% |
| reach, 2 points (189) | 12.2% | 28.3% |
| reach, 3 points (62) | 22.6% | 53.7% |
| reach, 4+ points (38) | 52.6% | 73.6% |
| median 24 h points | 1 | 1 |
| mean log1p 24 h points | 1.26 (feed max; undercounts slightly) | 1.40 |
| sum of P(top 30), whole day | about 25-30 winners | 47.1 (isotonic), 45.3 (day threshold) |

Points are calibrated, and posts with 1 point at 15 min are too. The simulator overshoots reach for 2+ point posts, the same too-steep response to early votes found in October.

An earlier report of the simulated "median 24 h points 58.8" was a metric error: a per-post mean over draws, inflated by rare front-page runs. It is now the median over draws.

The simulator stays a shadow (decision rule above). Caught for Nov 2 posts is due when lists Nov 2-5 settle (~Nov 8).
