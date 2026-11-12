# Weekly running rank vs growth-adjusted running votes (leave-one-week-out)

Weeks with a close read: 2026-10-26, 2026-11-02; growth pairs: 1546 launch-days from 8 consecutive nightly reads.
Truth = weekly_rank at the first full-refresh read after Sunday's close. Hits out of 3 / 5 / 10. reach10 = final top 10 already launched.

      week       asof weekday  days_left     read_pt  running_top3  running_top5  running_top10  running_g_top3  running_g_top5  running_g_top10  running_g_e_top3  running_g_e_top5  running_g_e_top10  entrants_in_top10  reach10
2026-10-26 2026-10-27     Tue          5 10-28 06:44             0             0              0               0               0                0                 0                 0                  0                 10        0
2026-10-26 2026-10-28     Wed          4 10-29 00:25             0             2              3               0               2                3                 0                 1                  2                  7        3
2026-10-26 2026-10-29     Thu          3 10-30 01:31             1             3              5               1               3                5                 1                 2                  4                  5        5
2026-10-26 2026-10-30     Fri          2 10-31 00:13             1             4              8               2               4                8                 1                 3                  7                  3        8
2026-10-26 2026-10-31     Sat          1 11-01 06:13             2             4              9               2               4                9                 2                 4                  9                  1        9
2026-11-02 2026-11-02     Mon          6 11-03 00:18             1             1              3               1               1                3                 0                 1                  1                  9        3
2026-11-02 2026-11-03     Tue          5 11-04 00:21             2             3              5               2               3                5                 1                 2                  3                  7        5
2026-11-02 2026-11-07     Sat          1 11-08 00:17             3             4              9               3               4               10                 3                 4                  8                  2       10

Totals (sum of hits over as-of points): running 10/21/42, running_g 11/21/43, running_g_e 8/17/34

Median daily growth by age (all pairs): 1: x1.016, 2: x1.000, 3: x1.000, 4: x1.000, 5: x1.000, 6: x1.000, 7: x1.000
