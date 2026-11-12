# Thread-position maker features over the clean LM (207 days, month-forward ridge)

Feature means by final rank group (rank-neutral if flat):

       th_has_first  th_hunter_first  th_n_pre  th_fa_n  th_fa_rel
g                                                                 
#1            0.962            0.269     1.092    0.839      0.563
#2-3          0.947            0.403     0.844    0.945      0.563
#4-10         0.916            0.646     0.366    0.881      0.550
11+           0.879            0.829     0.070    0.284      0.508

| scorer | top 3 | top 5 | top 10 | #1 in top 3 | exact winner |
|---|---|---|---|---|---|
| clean LM alone | 56.2 | 67.6 | 75.0 | 72.5 | 38.2 |
| ridge on LM features | 56.2 | 67.6 | 75.0 | 72.5 | 38.2 |
| ridge + thread features | 58.6 | 68.2 | 75.3 | 77.3 | 39.6 |

Thread minus LM-only ridge (paired day bootstrap): top3 +2.4 [+0.3, +4.5], top5 +0.6 [-0.8, +2.0], top10 +0.3 [-0.5, +1.1], p1 +4.8 [-0.5, +10.1], exact +1.4 [-3.9, +6.8]

## Within-day z, alpha 10 (orchestrator stack method)

| scorer | top 3 | top 5 | top 10 | #1 in top 3 | exact winner |
|---|---|---|---|---|---|
| honest | 56.2 | 67.6 | 75.0 | 72.5 | 38.2 |
| clean_thread_z | 60.9 | 68.5 | 75.2 | 77.3 | 40.1 |
| clean_stack | 60.2 | 68.5 | 75.1 | 76.8 | 39.6 |
clean_thread_z minus clean LM alone (paired day bootstrap): top3 +4.7 [+2.3, +7.2], top5 +0.9 [-0.5, +2.3], top10 +0.2 [-0.4, +0.8], p1 +4.8 [-0.5, +10.1]
clean_stack minus clean LM alone (paired day bootstrap): top3 +4.0 [+1.6, +6.6], top5 +0.9 [-0.6, +2.3], top10 +0.1 [-0.5, +0.7], p1 +4.3 [-1.4, +10.1]
