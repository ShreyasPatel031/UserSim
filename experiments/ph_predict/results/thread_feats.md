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
| clean LM alone | 57.6 | 68.2 | 74.7 | 72.0 | 40.1 |
| ridge on LM features | 57.6 | 68.2 | 74.7 | 72.0 | 40.1 |
| ridge + thread features | 59.7 | 69.9 | 75.1 | 77.8 | 43.0 |

Thread minus LM-only ridge (paired day bootstrap): top3 +2.1 [-0.3, +4.5], top5 +1.6 [+0.2, +3.1], top10 +0.4 [-0.4, +1.2], p1 +5.8 [+1.0, +11.1], exact +2.9 [-2.9, +8.2]
