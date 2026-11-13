# Late climbers (REPLAY; 13 days, 350 launches; climbers 9, faders 6)

Days: {"2026-10-25": "no early read", "2026-10-26": "no early read", "2026-10-27": {"early_source": "posts_ts", "early_read_PT": "12:06", "launches": 20, "comments": true}, "2026-10-28": {"early_source": "posts_ts", "early_read_PT": "12:06", "launches": 31, "comments": true}, "2026-10-29": {"early_source": "posts_ts", "early_read_PT": "12:06", "launches": 30, "comments": true}, "2026-10-30": {"early_source": "posts_ts", "early_read_PT": "12:06", "launches": 20, "comments": true}, "2026-10-31": {"early_source": "posts_ts", "early_read_PT": "12:06", "launches": 22, "comments": true}, "2026-11-01": {"early_source": "posts_ts", "early_read_PT": "12:06", "launches": 19, "comments": true}, "2026-11-02": {"early_source": "posts_ts", "early_read_PT": "11:50", "launches": 18, "comments": true}, "2026-11-03": {"early_source": "posts_ts", "early_read_PT": "11:50", "launches": 38, "comments": true}, "2026-11-04": {"early_source": "posts_ts", "early_read_PT": "04:00", "launches": 34, "comments": true}, "2026-11-08": {"early_source": "posts_ts", "early_read_PT": "04:00", "launches": 17, "comments": true}, "2026-11-09": {"early_source": "posts_ts", "early_read_PT": "04:00", "launches": 25, "comments": false}, "2026-11-10": {"early_source": "posts_ts", "early_read_PT": "04:00", "launches": 50, "comments": true}, "2026-11-11": {"early_source": "posts_ts", "early_read_PT": "04:00", "launches": 26, "comments": true}}

## Climbers vs non-climbers with early rank 4-15 (standardized difference, day bootstrap 95%)

| feature | diff (climber - other) |
|---|---|
| clean | +0.48 [-0.16, +0.79] |
| npre | +0.77 [+0.02, +1.88] |
| team | +0.19 [-0.45, +0.56] |
| ntopics | +0.33 [-0.05, +0.56] |

## Leave-one-day-out, early read + features (top 3 / 5 / 10, paired vs early rank as is)

| variant | top 3 | top 5 | top 10 |
|---|---|---|---|
| early rank as is | 89.7 | 90.8 | 93.8 |
| early only (ridge) | 89.7 | 90.8 (+0.0 [+0.0, +0.0]) | 93.8 (+0.0 [+0.0, +0.0]) |
| early + clean | 89.7 | 90.8 (+0.0 [+0.0, +0.0]) | 94.6 (+0.8 [+0.0, +2.3]) |
| early + all four | 89.7 | 89.2 (-1.5 [-4.6, +0.0]) | 94.6 (+0.8 [+0.0, +2.3]) |
