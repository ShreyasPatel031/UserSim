# Leak check: honest month-forward backtest without the llm / promo sources (5 seeds)

## all scored days (Mar - Nov 10): 214 days (days with all of the final top 10 ranked)

| variant | top 3 | top 5 | top 10 | #1 in top 3 | #2 in top 3 | #3 in top 3 | exact winner | #1-#2 margin (median, z) | minus ref top 3 [95% CI] | minus ref #1 in top 3 |
|---|---|---|---|---|---|---|---|---|---|---|
| ref | 58.4 | 65.0 | 75.3 | 88.3 | 54.7 | 32.2 | 75.7 | 0.395 (1.03) | - | - |
| clean_v2 | 54.7 | 64.5 | 75.6 | 72.0 | 52.3 | 39.7 | 39.3 | 0.142 (0.36) | -3.7 [-6.1, -1.4] | -16.4 [-22.0, -10.7] |
| clean_v3 | 53.7 | 64.6 | 75.4 | 68.7 | 54.7 | 37.9 | 31.8 | 0.135 (0.36) | -4.7 [-7.0, -2.3] | -19.6 [-25.7, -14.0] |

## Sep - Oct: 58 days (days with all of the final top 10 ranked)

| variant | top 3 | top 5 | top 10 | #1 in top 3 | #2 in top 3 | #3 in top 3 | exact winner | #1-#2 margin (median, z) | minus ref top 3 [95% CI] | minus ref #1 in top 3 |
|---|---|---|---|---|---|---|---|---|---|---|
| ref | 60.3 | 66.9 | 75.3 | 89.7 | 55.2 | 36.2 | 81.0 | 0.413 (1.09) | - | - |
| clean_v2 | 54.0 | 66.9 | 75.2 | 65.5 | 60.3 | 36.2 | 32.8 | 0.141 (0.36) | -6.3 [-10.3, -2.9] | -24.1 [-36.2, -13.8] |
| clean_v3 | 52.9 | 66.9 | 75.5 | 65.5 | 58.6 | 34.5 | 31.0 | 0.129 (0.34) | -7.5 [-10.9, -4.0] | -24.1 [-36.2, -13.8] |

