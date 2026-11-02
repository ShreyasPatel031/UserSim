# Does the concentration of simulated pool support add daily top 3 over the day-calibrated control? (Nov 2, 2026)

Code: `simlab/pool_conc.py`; data `reports/pool_conc.json`. Requested by Grok Bot: find person-model features that add
*daily* top-3 lift over the day-calibrated control (`shadow_daycal`: the launch-model offset + day terms).

**Hypothesis.** The summed expected pool picks mostly track reach. How *concentrated* the support is should carry
within-day signal the total does not: picks from people already tied to the team, the 100 most likely people, people
ranking the launch first or in their top 3 that day, the best single person, the choice-style share, each also as its
standing within the day. **Decision rule fixed before the run:** the hypothesis holds if daily top 3 against the
control has a 95% interval above 0.

**Setup.** Poisson LightGBM offset by the launch model, rolling monthly (May–Oct, 3,977 launches, 176 days for daily
top 3/5, 144 for top 10, 25 weeks), 5 seeds averaged; pool sources `pna_` (page-free, deployable) and `psa_` (page-aware).
Paired by day / week, 10,000 resamples.

| Model | Daily top 3 / 5 / 10 | Weekly top 3 / 5 / 10 | Log-lik / launch |
|---|---|---|---|
| Launch model alone | 66.7 / 73.5 / 81.0 | 49.3 / 56.0 / 58.3 | −12.128 |
| Control (day-calibrated) | 66.7 / 73.5 / 81.0 | 54.7 / 56.0 / 57.4 | **−12.009** |
| + `pna_` total | 67.6 / 73.8 / 81.2 | 54.7 / 60.8 / 56.5 | −12.092 |
| + `pna_` concentration | 66.9 / 73.2 / 81.4 | 49.3 / 56.8 / 56.1 | −12.144 |
| + `psa_` total | 67.4 / 72.6 / 81.0 | 57.3 / 58.4 / 57.4 | −12.082 |
| + `psa_` concentration | 67.0 / 73.2 / 81.0 | 54.7 / 56.0 / 57.8 | −12.127 |

| Paired against the control | Daily top 3 | Top 5 | Top 10 | Weekly top 3 | Weekly top 5 | Log-lik | Months better / tied / worse (daily top 3) |
|---|---|---|---|---|---|---|---|
| + `pna_` concentration | +0.2 [−1.7, +2.1] | −0.3 [−1.6, +0.9] | +0.4 [−0.3, +1.2] | −5.3 [−12.0, +0.0] | +0.8 [−1.6, +3.2] | **−0.32 [−0.58, −0.05]** | 3 / 1 / 2 |
| + `psa_` concentration | +0.4 [−1.3, +2.1] | −0.3 [−1.7, +1.0] | +0.1 [−0.6, +0.8] | +0.0 [−6.7, +8.0] | +0.0 [−2.4, +2.4] | **−0.29 [−0.56, −0.01]** | 3 / 1 / 2 |
| + `pna_` total | +0.9 [−1.1, +3.0] | +0.2 [−0.9, +1.4] | +0.3 [−0.4, +1.0] | +0.0 [−5.3, +5.3] | **+4.8 [+1.6, +8.0]** | −0.17 [−0.45, +0.11] | 3 / 2 / 1 |
| + `psa_` total | +0.8 [−0.8, +2.3] | −0.9 [−1.9, +0.0] | +0.1 [−0.4, +0.6] | +2.7 [−2.7, +8.0] | +2.4 [+0.0, +5.6] | −0.12 [−0.34, +0.10] | 3 / 3 / 0 |

**Verdict: rejected.** No variant meets the rule. Concentration features add +0.2 to +0.4 daily top 3 (intervals span 0),
do worse than the plain total, and make the total-vote likelihood worse (−0.29 to −0.32, intervals below 0): they
overfit. The plain pool total again gives a small, non-significant daily edge (+0.8 to +0.9) and the weekly top-5 gain
seen in E1 v2 (+4.8 [+1.6, +8.0] with `pna_`).

**Reading.** Every way of summing the person model over the pool tried so far (total, ties, fans, first choices,
within-day standing, page-aware or not) lands inside ±1 point of the day-calibrated launch model on daily top 3. This
fits E0: about 90% of the pool's error is a per-launch shock on launch day that no pre-launch person input sees. The
next daily test with a chance should bring new information about that shock (pre-launch X engagers as coverage grows;
the makers' own outreach), not another aggregate of the same person scores.
