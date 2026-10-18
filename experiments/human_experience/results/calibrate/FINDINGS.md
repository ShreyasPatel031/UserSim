# Calibration on top of the plain context agent (agent_full = C2)

`python calibrate.py` (no model calls). 420 Capterra reviewers; fit on 25 DEV products → scored on 10 TEST products,
and leave-one-product-out over all 35. Errors are normalized (recommend 0-10 counted on a 1-5 scale).

| What is added on top of agent_full | TEST MAE | TEST RMSE | LOPO MAE | LOPO RMSE |
| --- | --- | --- | --- | --- |
| nothing (agent_full) | 0.669 | 0.899 | 0.690 | 0.926 |
| bias shift to the dev median residual | 0.598 | 0.901 | 0.614 | 0.924 |
| **constant = everyone's median (5/5, 9/10)** | **0.570** | 0.930 | **0.534** | 0.935 |
| **constant = everyone's mean** | 0.621 | **0.761** | 0.635 | **0.789** |
| linear / stack with averages / factor weights / corpus GBM (L1 or L2) | = the constants ± 0.005 | | | |

- **The whole gain is level calibration.** Every learned calibrator collapsed to (or tied with) a constant. The L1 fits
  put weight 0 on agent_full, the averages, and each factor (role, size, tenure, industry, category, within-category
  deviations, previous product).
- **Individual differences are not predicted by anything here.** Within-product Spearman ≤ 0.08 for every method;
  unhappy-user AUC 0.50–0.63.
- So report ratings as the population median (for MAE) or mean (for RMSE / expected value), and use per-person data
  for words (pros/cons), not stars. Next lever to test: **product-level evidence** (the product's own reviews on another
  platform / earlier reviews), which moves the level per product rather than per person.
