# Readable 00:05 model vs clean_nosite (214 days Apr-Oct 2026, 5033 launches; walk-forward by month)

Inputs (10, all in the deployed clean_nosite set, known at 00:05): hunter track record (hist_hunter_rel, hist_hunter_n), Gemini pitch and brand (llm_pitch, llm_brand), topic prior (topic_prior_mean), closest same-day competitor (comp_nn_max), media (ph_n_media, ph_has_video), team size (ph_n_makers), pre-launch promotion (promo_cov).

| line | top 3 | top 5 | top 10 | daily rho | diff vs clean_nosite (t3 / t5 / t10 / rho, 95%) | call (top 3) |
|---|---|---|---|---|---|---|
| clean_nosite (walk-forward retrain, 40 inputs, reference) | 56.9 | 67.6 | 75.0 | 0.613 | - | - |
| (a) readable ridge on within-day z, 10 inputs | 54.0 | 64.3 | 72.9 | 0.587 | -2.8 [-5.9, +0.2] / -3.3 [-5.2, -1.4] / -2.1 [-3.2, -0.9] / -0.027 [-0.045, -0.007] | worse |
| (b) readable additive monotone stumps, 10 inputs | 53.7 | 66.4 | 74.3 | 0.603 | -3.1 [-5.8, -0.5] / -1.1 [-2.7, +0.5] / -0.7 [-1.6, +0.2] / -0.010 [-0.029, +0.010] | worse |
| clean_nosite OOF line (tw_nosite) | 56.4 | 67.8 | 75.0 | 0.614 | -0.5 [-1.9, +0.9] / +0.2 [-0.6, +0.9] / +0.1 [-0.3, +0.5] / +0.000 [-0.006, +0.007] | not worse |

## + th_n_pre (LODO ridge), vs clean_nosite + th_n_pre

| line | top 3 | top 5 | top 10 | daily rho | diff (95%) | call |
|---|---|---|---|---|---|---|
| clean_nosite + th_n_pre (reference) | 60.1 | 68.5 | 75.2 | 0.622 | - | - |
| (a) + th_n_pre | 57.3 | 67.7 | 73.3 | 0.595 | -2.8 [-5.3, -0.5] / -0.8 [-2.7, +0.9] / -1.9 [-3.0, -0.8] / -0.027 [-0.044, -0.009] | worse |
| (b) + th_n_pre | 58.4 | 68.3 | 74.6 | 0.615 | -1.7 [-4.2, +0.6] / -0.2 [-1.7, +1.3] / -0.7 [-1.5, +0.3] / -0.007 [-0.023, +0.011] | worse |

Rule (orchestrator): not worse = interval of the top-3 difference includes 0 and the mean is within 1.5 points.
