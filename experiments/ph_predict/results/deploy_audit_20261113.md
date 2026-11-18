# Deploy audit, every published point (AGENTS.md rule 5: better on the leak-free paired backtest, interval excluding 0 on the north-star cut => deploy). Nov 13, 19:25Z

| point | published line (backtest t3/t5/t10) | best shadow on the same days | paired diff top 3 (95%) | days | call |
|---|---|---|---|---|---|
| 00:05 | arm 2 (2025-trained clean_nosite), deployed 19:08Z: 60.7 / 68.4 / 75.7 | (was clean_nosite 56.9 / 67.6 / 75.0) | +3.9 [+1.4, +6.5] | 214 | DEPLOYED (forecast.py 61538501; clean kept as shadow + prior) |
| 00:05 | arm 2 | readable v2 stumps 54.4 / 66.8 / 74.5 | -6.3 vs arm 2 (alone, -2.5 [-5.0, 0.0] vs clean) | 214 | no (worse) |
| 00:05 | arm 2 | joint th inside model / h25 arm 1 / target dailyRank | all <= arm 2 (h25_joint, h25_stack, target_test) | 214 | no |
| 00:30 | mrep (clean base): 63.1 / 69.3 / 76.0 | mrep inputs on the arm-2 base: 63.9 / 70.1 / 76.5; with total comments only 64.2 / 69.9 / 76.5 | +0.8 [-1.1, +2.8] (total only +1.1 [-0.8, +3.0]); last half -0.3 [-3.1, +2.5] | 214 | not yet: interval includes 0 (would need ~3x the days at this effect size) |
| 00:30 | mrep | h25_th (arm 2 + th_n_pre) 61.4 / 69.4 / 75.7 | about -1.7 | 214 | no (worse) |
| 00:30 | mrep | readable v2 + mrep inputs 61.1 / 70.2 / 75.1 | -2.0 [-3.7, -0.3] | 214 | no (worse) |
| 00:30 | mrep | eh (early hidden) 61.9 / 65.7 / 81.4 | top 10 +10.0 [+2.9, +18.6]; top 3 n/a | 7 | not yet: 7 replay days, north-star cut is top 3 |
| 01:00 | hr_clean 71.4 / 65.7 / 84.3 | mrep on arm-2 base (214 d) 62.8 / 70.8 / 76.7 vs mrep clean 62.8 / 71.0 / 76.5 | -0.0 [-1.9, +1.9] | 214 / 7 | not yet: hr_clean is a 7-day replay; no shadow beats it on the same days |
| 02:00 | hr_clean 66.7 / 74.3 / 84.3 | hidden rank / hybrid 71.4 / 65.7 | +4.8 top 3, 7 days, interval wide | 7 | not yet: needs ~30 replay days (vote_snapshots rank_now from Oct 31: 12 days held) |
| 03:00 | hybrid 76.2 / 71.4 / 85.7 | hr_clean (tie) | 0 | 7 | not yet |
| 03:45 | hybrid 76.2 / 80.0 / 88.6 | hr_clean 71.4 / 77.1 / 88.6 | -4.8 for the shadow | 7 | no |
| 04:00 | raw votes 66.7 / 72.0 / 84.0 | velocity / GBM same | 0 | 5 | no |
| 05:00 | raw votes 86.7 / 88.0 / 78.0 | velocity V05 93.3 / 88.0 / 78.0 | +6.7 [0, +20] | 5 | not yet: shadow V05 running; ~30 days needed (about Dec 13) |
| 08:00 | raw votes 85.2 / 88.9 / 86.7 | velocity V08 (same) | 0 | 9 | not yet |
| 10:00 | raw votes 88.9 / 88.9 / 87.8 | velocity V10 96.3 / 91.1 / 87.8 | +7.4 [0, +18.5] | 9 | not yet: shadow V10 running |
| 12:00 | raw votes 88.9 / 88.9 / 92.2 | velocity V12 88.9 / 91.1 / 91.1 | 0 top 3 | 9 | no |
| week | running vote order | none | - | 2 weeks | not yet (first score Mon Nov 16; frozen-at-close test needs a Sunday 23:45 read) |
| month | running vote order | none | - | 4 months | not yet |

Only 00:05 met the rule (deployed). Every other candidate either trails, or has an interval that includes 0, or rests on 5-9 replay days.
