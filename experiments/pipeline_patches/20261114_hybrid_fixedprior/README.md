# 20261114_hybrid_fixedprior: 03:45 hybrid slots 6-10 weights refit on the fixed 00:05 prior (UNDEPLOYED; new build, 12a / 12a.1 untouched)

The orchestrator asked for this at 16:38Z Nov 14 (today-rows bug scope). The live z(clean) input of the 03:45 VM-only hybrid is the 00:05 forecast's clean_nosite
score, built with the today-rows bug since Oct 26. The weights in 12a / 12a.1 (hybrid_vmonly_P345_20261114.json, md5 16912cd6) were fit on it.
Here the clean prior is the as-of-night clean_nosite from the today-rows replay (experiments/ph_predict/today_replay.py, fixed builder;
results/today_replay_fixed.parquet). Nov 5-7 have no line-up file, so they keep the month-fold stand-in, as before. Script: ph_predict/hybrid_lodo.py
with CLEAN_PRIOR / TAG.

12 days Nov 2-13, 03:00 recorder read, top 10 (hidden rank alone 73.3 in every row):

| clean prior | slots 6-10 by prior | LODO hybrid | L2O | LODO - hidden | permutation p |
|---|---|---|---|---|---|
| live forecast parquet (what 12a was fit on) | 74.2 | 77.5 | 77.5 | +4.2 [+0.0, +8.3] | 0.055 |
| polluted replay (control: reproduces live) | 74.2 | 77.5 | 78.0 | +4.2 [+0.0, +8.3] | 0.075 |
| fixed replay | 75.8 | 79.2 | 79.1 | +5.8 [+1.7, +10.0] | 0.020 |

The polluted-replay control matches the live parquet, so the change comes from the fix, not from replaying. With the fixed prior,
the LODO edge over hidden order clears 0. It is still 12 days: the label stays "not yet established" until the orchestrator decides otherwise.

Weights (all-day fit Nov 2-12, alpha 3; z within day):

| | z_lpos | z_move | z_nc_rec | z_clean |
|---|---|---|---|---|
| 12a (live prior) | -0.598 | -0.015 | 0.114 | 0.217 |
| fixed prior (this file, md5 b8a59cdd) | -0.583 | -0.011 | 0.102 | 0.248 |

Swap rule: install this file only AFTER the today-rows fix is live, because these weights expect a fixed prior.
1. Back up ~/w/tw12a/hybrid_vmonly_P345_20261114.json (16912cd6).
2. Copy this file's content over it. two_predictions.py reads that path.
3. Update WANT in the deploy script of whichever 12a build carries it.
This needs Shreyas's direct word, like any pipeline change. The before-reveal file label would then read: LODO 79.2 (12 days), edge over hidden +5.8 [+1.7, +10.0].
