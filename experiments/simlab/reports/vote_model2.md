# E1 v2: the vote model contains the launch model (Nov 2, 2026; Shreyas approved the run)

Code: `simlab/vote_model2.py`. Pre-launch only. Poisson LightGBM on final votes, rolling monthly (train on every earlier
month, test the next; May–Oct, 3,977 launches, 176 days for daily top 3/5, 144 for top 10, 25 weeks), 3 seeds.
- **Launch model alone:** ctrl.py `all` (out of sample), as a Poisson mean `expm1(all)` rescaled on the training months.
- **off:** starts from the launch model (its log mean as the offset) and learns multiplicative corrections from the pool
  (`psa_` expected picks), audience sizes (makers' / hunter's PH followers, X followers, promotion) and a day-level term
  (line-up size, weekday, the day's pool reach and summed picks, the day's summed launch-model votes). Non-decreasing in
  the pool and in every audience size.
- **off+maker:** + per-maker / per-hunter conversion from their earlier launches (days strictly before): shrunk mean
  residual vs the launch model, last residual, count, shrunk pool shock; first-timers get the prior 0.
- **full+maker:** no offset; the launch model's 207 inputs + everything above, learned jointly.
All scores are paired against the launch model alone (bootstrap over days / weeks, 10,000).

## Results (pool `psa_`)
| Model | Daily top 3 | Top 5 | Top 10 | Weekly top 3 | Top 5 | Top 10 | Log-lik / launch |
|---|---|---|---|---|---|---|---|
| Launch model alone | 66.7 | **73.5** | 81.0 | 49.3 | 56.0 | 58.3 | −12.128 |
| **E1 v2 off** | **68.4** | 72.6 | **81.5** | 53.3 | 60.0 | 57.8 | **−11.967** |
| E1 v2 off+maker | 66.3 | 72.6 | 81.0 | 48.0 | 56.8 | 56.5 | −12.217 |
| E1 v2 full+maker | 65.5 | **73.6** | 78.9 | 52.0 | **61.6** | **60.0** | −12.823 |

Paired against the launch model alone:
| Model | Daily top 3 | Top 5 | Top 10 | Weekly top 3 | Top 5 | Top 10 | Log-lik |
|---|---|---|---|---|---|---|---|
| off | **+1.7 [+0.2, +3.2]** | −0.9 [−2.2, +0.3] | +0.5 [−0.3, +1.2] | +4.0 [−2.7, +10.7] | **+4.0 [+0.8, +7.2]** | −0.4 [−3.0, +2.2] | +0.13 [−0.22, +0.50] |
| off+maker | −0.4 [−2.5, +1.9] | −0.9 [−2.3, +0.5] | +0.0 [−0.8, +0.8] | −1.3 [−6.7, +4.0] | +0.8 [−1.6, +4.0] | −1.7 [−4.8, +1.3] | −0.14 [−0.55, +0.29] |
| full+maker | −1.1 [−3.8, +1.5] | +0.1 [−1.5, +1.7] | −2.1 [−3.1, −1.0] | +2.7 [−4.0, +9.3] | **+5.6 [+2.4, +8.8]** | +1.7 [−1.7, +5.2] | −0.66 [−1.26, −0.10] |

With `psx_` as the pool, off gives the same 68.4 / 72.8 / 81.3 (+1.7 [+0.2, +3.4] daily top 3). `psa_` − `psx_` within off:
daily top 3/5/10 +0.0 [−0.8, +0.8] / −0.2 [−0.8, +0.3] / +0.2 [−0.1, +0.6], log-likelihood +0.06 [−0.04, +0.15].

## What carries the gain (ablations of off, paired against off)
| Removed | Daily top 3 | Log-lik |
|---|---|---|
| the pool | −0.4 [−1.1, +0.4] | −0.01 [−0.04, +0.03] |
| the day-level term | **−1.5 [−2.8, −0.4]** | **−0.30 [−0.51, −0.09]** |
| the audiences | −0.6 [−2.1, +0.9] | +0.01 [−0.16, +0.19] |
| all but the day term | −1.7 [−3.2, −0.2] | +0.10 [−0.16, +0.35] |
| all but the pool | −2.3 [−4.0, −0.6] | −0.18 [−0.44, +0.08] |

A day-level term alone multiplies every launch of a day by the same factor, so it cannot change a daily ranking; with it,
the corrections from the pool and the audiences differ by day context (line-up size, the day's pool activity). That
interaction is where the gain sits; the pool on its own adds nothing measurable once the launch model is the offset.

## Reading
- **E1 now matches the launch model and beats it on daily top 3:** 68.4 vs 66.7, +1.7 [+0.2, +3.2], and weekly top 5,
  +4.0 [+0.8, +7.2]. Top 5 / top 10 daily and log-likelihood are ties. Caveat: eight variants were compared with the
  launch model in this run; the lower bound of +0.2 is close to 0, so this is a first positive, to confirm on the live
  days from Nov 3.
- **Per-maker conversion from earlier launches did not help** (−2.1 daily top 3 against off). Most launches have few or no
  earlier launches by the same makers with a launch-model residual (it exists only from March), and the launch model
  already carries the track record (`hist_`). The E0 persistence (0.25–0.44) is real but too thin per maker here.
- **The pool component adds nothing beyond the launch model** in this form (−0.4 [−1.1, +0.4] without it); `psa_` and
  `psx_` are equal.
- **Learning everything jointly without the offset** (full+maker) is worse on daily top 10 and log-likelihood, and better
  on weekly top 5 (+5.6 [+2.4, +8.8]): weekly benefits from a model of total votes; daily from starting at the launch model.

## Next
1. Score off live from Nov 3 (pre-launch, daily and weekly), next to the launch model.
2. Per-maker conversion with more history: the full upvote histories of past launches, and a prior from similar makers
   (topic, follower size), rather than residuals that exist only from March.
3. X engagers as their own audience as coverage grows; launch-day shock terms only in the launch-day forecast.
