# Deployed vs honest 00:05 configuration on the live days (14 days, 00:05 rows, 5 seeds)

Params identical in all configs (LIVE_PARAMS = ctrl.fit settings); configs differ in feature set and refit cadence.

| config | top 3 | top 5 | top 10 | minus live_daily: top 3 | top 5 | top 10 |
|---|---|---|---|---|---|---|
| live_daily | 57.1 | 64.3 | 76.9 | - | - | - |
| honest_daily | 57.1 | 64.3 | 76.9 | +0.0 [+0.0, +0.0] | +0.0 [+0.0, +0.0] | +0.0 [+0.0, +0.0] |
| honest_month | 52.4 | 61.4 | 77.7 | -4.8 [-11.9, +0.0] | -2.9 [-7.1, +0.0] | +0.8 [+0.0, +2.3] |
| live_month | 52.4 | 61.4 | 77.7 | -4.8 [-11.9, +0.0] | -2.9 [-7.1, +0.0] | +0.8 [+0.0, +2.3] |
| honest_nopage_daily | 57.1 | 64.3 | 76.9 | +0.0 [+0.0, +0.0] | +0.0 [+0.0, +0.0] | +0.0 [+0.0, +0.0] |
