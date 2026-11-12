# Leak check: honest month-forward backtest without the llm / promo sources (5 seeds)

## all scored days (Mar - Nov 10): 214 days (days with all of the final top 10 ranked)

| variant | top 3 | top 5 | top 10 | #1 in top 3 | #2 in top 3 | #3 in top 3 | exact winner | #1-#2 margin (median, z) | minus ref top 3 [95% CI] | minus ref #1 in top 3 |
|---|---|---|---|---|---|---|---|---|---|---|
| ref | 58.4 | 65.0 | 75.3 | 88.3 | 54.7 | 32.2 | 75.7 | 0.395 (1.03) | - | - |
| no_maker_age | 59.5 | 64.9 | 75.0 | 87.9 | 51.9 | 38.8 | 74.8 | 0.329 (0.91) | +1.1 [-0.3, +2.5] | -0.5 [-2.3, +1.4] |
| no_maker_prof | 54.7 | 64.5 | 75.6 | 72.0 | 52.3 | 39.7 | 39.3 | 0.142 (0.36) | -3.7 [-6.1, -1.4] | -16.4 [-22.4, -10.7] |

## Sep - Oct: 58 days (days with all of the final top 10 ranked)

| variant | top 3 | top 5 | top 10 | #1 in top 3 | #2 in top 3 | #3 in top 3 | exact winner | #1-#2 margin (median, z) | minus ref top 3 [95% CI] | minus ref #1 in top 3 |
|---|---|---|---|---|---|---|---|---|---|---|
| ref | 60.3 | 66.9 | 75.3 | 89.7 | 55.2 | 36.2 | 81.0 | 0.413 (1.09) | - | - |
| no_maker_age | 61.5 | 66.6 | 75.3 | 86.2 | 56.9 | 41.4 | 79.3 | 0.318 (0.88) | +1.1 [-1.7, +4.6] | -3.4 [-8.6, +0.0] |
| no_maker_prof | 54.0 | 66.9 | 75.2 | 65.5 | 60.3 | 36.2 | 32.8 | 0.141 (0.36) | -6.3 [-9.8, -2.9] | -24.1 [-36.2, -13.8] |

