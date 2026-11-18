# Readable 00:05 model vs clean_nosite (214 days Apr-Oct 2026, 5033 launches; walk-forward by month)

Inputs (10, all in the deployed clean_nosite set, known at 00:05): hunter track record (hist_hunter_rel, hist_hunter_n), Gemini pitch and brand (llm_pitch, llm_brand), topic prior (topic_prior_mean), closest same-day competitor (comp_nn_max), media (ph_n_media, ph_has_video), team size (ph_n_makers), pre-launch promotion (promo_cov).

| line | top 3 | top 5 | top 10 | daily rho | diff vs clean_nosite (t3 / t5 / t10 / rho, 95%) | call (top 3) |
|---|---|---|---|---|---|---|
| clean_nosite (walk-forward retrain, 40 inputs, reference) | 56.9 | 67.6 | 75.0 | 0.613 | - | - |
| (a) readable ridge on within-day z, 10 inputs | 54.7 | 65.0 | 74.0 | 0.592 | -2.2 [-5.1, +0.8] / -2.5 [-4.5, -0.6] / -1.0 [-2.0, +0.0] / -0.022 [-0.038, -0.005] | worse |
| (b) readable additive monotone stumps, 10 inputs | 54.4 | 66.8 | 74.5 | 0.602 | -2.5 [-5.0, +0.0] / -0.7 [-2.2, +0.7] / -0.4 [-1.2, +0.4] / -0.011 [-0.026, +0.005] | worse |
| clean_nosite OOF line (tw_nosite) | 56.4 | 67.8 | 75.0 | 0.614 | -0.5 [-1.9, +0.9] / +0.2 [-0.6, +0.9] / +0.1 [-0.3, +0.5] / +0.000 [-0.006, +0.007] | not worse |

## + th_n_pre (LODO ridge), vs clean_nosite + th_n_pre

| line | top 3 | top 5 | top 10 | daily rho | diff (95%) | call |
|---|---|---|---|---|---|---|
| clean_nosite + th_n_pre (reference) | 60.1 | 68.5 | 75.2 | 0.622 | - | - |
| (a) + th_n_pre | 57.3 | 68.0 | 74.1 | 0.602 | -2.8 [-5.5, -0.3] / -0.5 [-2.1, +1.3] / -1.1 [-2.0, -0.2] / -0.020 [-0.036, -0.002] | worse |
| (b) + th_n_pre | 58.9 | 69.2 | 74.5 | 0.616 | -1.2 [-3.4, +0.9] / +0.7 [-0.8, +2.1] / -0.7 [-1.5, +0.1] / -0.006 [-0.020, +0.009] | not worse |

## Split (input set chosen on the first 107 days only; days 2026-04-01..2026-07-16 | 2026-07-17..2026-10-31)

| line | days | diff t3 / t5 / t10 / rho vs reference (95%) | call |
|---|---|---|---|
| (b) alone vs clean_nosite | first half | -2.2 [-5.6, +1.2] / -0.4 [-2.6, +1.7] / -0.1 [-1.3, +1.1] / -0.000 [-0.023, +0.023] | worse |
| (b) alone vs clean_nosite | last half | -2.8 [-6.5, +1.2] / -1.1 [-3.2, +0.9] / -0.7 [-1.8, +0.3] / -0.022 [-0.043, -0.002] | worse |
| (b) alone vs clean_nosite | all | -2.5 [-5.1, +0.0] / -0.7 [-2.2, +0.7] / -0.4 [-1.2, +0.4] / -0.011 [-0.026, +0.004] | worse |
| (b) + th_n_pre vs clean_nosite + th_n_pre | first half | -1.2 [-4.4, +1.9] / +0.2 [-1.9, +2.4] / -0.5 [-1.7, +0.7] / +0.003 [-0.018, +0.025] | not worse |
| (b) + th_n_pre vs clean_nosite + th_n_pre | last half | -1.2 [-4.4, +1.6] / +1.1 [-0.9, +3.0] / -0.9 [-2.1, +0.2] / -0.015 [-0.034, +0.003] | not worse |
| (b) + th_n_pre vs clean_nosite + th_n_pre | all | -1.2 [-3.4, +0.9] / +0.7 [-0.8, +2.1] / -0.7 [-1.5, +0.1] / -0.006 [-0.020, +0.009] | not worse |

Top-3 agreement, (b) + th_n_pre vs clean_nosite + th_n_pre, per day: all 3 same 58.4%, >= 2 same 97.7%, mean overlap 2.56 of 3 (214 days).

Rule (orchestrator): not worse = interval of the top-3 difference includes 0 and the mean is within 1.5 points.
