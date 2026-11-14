
## Nightly walk-forward (STEP=1, refit every test day on days <= d-2; Nov 14 ~16:55Z)
Same build, prep, params and 5 seeds as month-forward. Clean backtest (days/ only, no today/ rows).
- >= 10 ranked (183 d): arm 2 59.0 / 65.4 / 77.0, clean 54.5 / 64.6 / 76.5. Nightly - month-forward: arm 2 +0.9 [-0.7, +2.6] / +0.1 / +0.1;
  clean +0.0 [-2.0, +2.0]. Arm 2 - clean: +4.6 [+2.0, +7.1] top 3 (month-forward +3.6 [+0.9, +6.4]).
- all 214: arm 2 61.2 / 68.3 / 75.8; arm 2 - clean +4.5 [+2.2, +7.0].
- last 90: arm 2 - clean +3.7 [-0.0, +7.4]; nightly - month-forward arm 2 top 10 -0.8 [-1.4, -0.2].
Reading: refit cadence doesn't matter (nightly ~ weekly ~ monthly within noise). The arm 2 edge over clean holds under the live cadence.
The published 183-day figures (58.1 / 65.2 / 76.9) are a fair, slightly conservative label for the nightly-refit live model.
