# E1 v2: the vote model contains the launch model (Nov 2, 2026; Shreyas approved the run)

> **Correction (Nov 2, 11:30 UTC, follow-up below):** the audience inputs of "off" included the makers' Product Hunt
> follower count, which is not a live launch-model input (fetched after launch: leaky). Without it, with live inputs
> only, daily top 3 is +1.3 [−0.4, +3.0] (4 of 6 months better, 2 tied), not +1.7 [+0.2, +3.2]; the weekly gains hold.

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

## Follow-up (Shreyas approved): frozen confirmation and the shadow package
`simlab/vote_model2_confirm.py` (`reports/vote_model2_confirm.json`): every variant frozen, 5 LightGBM seeds fitted
separately and averaged, same launches (May–Oct, 176 days, 25 weeks). Paired against the launch model alone.

| Variant | Daily top 3 / 5 / 10 | Daily top 3 vs LM | Months better (top 3) | Seed spread, top 3 | Weekly top 3 / 5 / 10 vs LM | Log-lik vs LM |
|---|---|---|---|---|---|---|
| Launch model alone | 66.7 / 73.5 / 81.0 | | | | | |
| off, `psa_` (as reported; leaky input) | 68.4 / 72.8 / 81.5 | +1.7 [+0.2, +3.2] | 5 of 6 | 68.0–68.8 (sd 0.28) | +2.7 / **+4.0** / −0.9 | +0.15 [−0.21, +0.52] |
| off, `pna_` (leaky input) | 68.4 / 73.5 / 81.3 | +1.7 [+0.4, +3.2] | 5 of 6, 1 tied | 67.8–68.2 | +4.0 / **+4.8** / +0.0 | +0.26 [−0.07, +0.61] |
| **offlive, `pna_` (live inputs only: packaged)** | **68.0 / 73.2 / 81.3** | +1.3 [−0.4, +3.0] | 4 of 6, 2 tied | 67.6–68.2 (sd 0.20) | **+5.3 [+1.3, +10.7]** / **+3.2 [+0.8, +6.4]** / +0.0 | +0.18 [−0.14, +0.52] |
| offlive, `psa_` | 68.2 / 72.8 / 81.2 | +1.5 [+0.0, +3.0] | 4 of 6, 2 tied | 68.0–68.4 | +5.3 / +4.0 / −1.3 | +0.04 [−0.33, +0.43] |
| offset + pool + day only, `pna_` | 66.5 / 73.2 / 81.6 | −0.2 [−1.3, +0.9] | 1 of 6, 4 tied | 66.1–66.7 | **+8.0 [+2.7, +13.3]** / +3.2 / +0.4 | +0.24 [−0.08, +0.58] |

- The result is stable across seeds (spread under 1 point) and month by month: the live-only variant is better or tied
  in every month on daily top 3.
- With live inputs only, daily top 3 is a likely gain but its interval spans 0; weekly top 3 and top 5 gains exclude 0.
- The page-free pool `pna_` loses nothing against `psa_` here.
- A fresh out-of-sample tail (Nov 1–2) is not possible on these inputs: the launch model's backtest predictions and the
  pool features end on Oct 24. The live shadow forecast is that test.

**Shadow package** (`simlab/e1v2_package.py`, in `gs://usersim-bakeoff-347838016394/usersim_sim/tmp/e5/e1v2/`): the
live-only variant with `pna_`, trained on Apr 1–Oct 24 (4,876 launches), 5 boosters + `meta.json` + `predict.py` for the
pipeline's shadow slot (`python3 predict.py <day>` from `ph_predict/data/shadow/e1v2/`, JSON lines
`{"launch_id", "score"}`, score = log expected votes). Inputs: `results/forecast_<day>.parquet` (offset), `data/sim_live/
pnx_<day>.json` (pool), and the five audience columns, read from the forecast file if present, otherwise rebuilt with
`features.build(include_today=True)`. Self-test (`simlab/e1v2_pkg_test.py`, Oct 20 staged in the live layout): 33 of 33
launches scored, identical to the in-code prediction (max difference 0.0) both with the columns in the forecast file
and through the fallback; about 2 s without the fallback.
