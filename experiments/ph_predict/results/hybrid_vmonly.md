# VM-only before-reveal hybrid (recorder rank + recorder comment count + 00:05 forecast), 11 days Nov 2-12

Recorder reads only (E5's rule: latest rank_now <= T, within 65 min, after 23:55 PT); 03:45 = the 03:00 read (no 03:45 read existed). Label = official dailyRank, all featured launches. Weights leave-one-day-out. Clean prior per day: 11-02 month-fold clean_nosite stand-in; 11-03 forecast parquet pred; 11-04 forecast parquet pred; 11-05 month-fold clean_nosite stand-in; 11-06 month-fold clean_nosite stand-in; 11-07 month-fold clean_nosite stand-in; 11-08 forecast parquet pred; 11-09 forecast parquet pred; 11-10 forecast parquet pred; 11-11 forecast parquet pred; 11-12 forecast parquet pred

| point | line | top 3 | top 5 | top 10 | minus plain hidden rank (t3 / t5 / t10) |
|---|---|---|---|---|---|
| 03:00 | plain hidden rank | 72.7 | 74.5 | 72.7 | - |
| 03:00 | VM-only hybrid (hidden top 5 + ridge 6+) | 72.7 | 74.5 | 77.3 | +0.0 [+0.0, +0.0] / +0.0 [+0.0, +0.0] / +4.5 [+0.0, +9.1] |
| 03:00 | 00:05 clean prior alone (reference) | 51.5 | 52.7 | 70.9 | -21.2 [-39.4, +0.0] / -21.8 [-34.5, -9.1] / -1.8 [-8.2, +4.5] |
| 03:45 | plain hidden rank | 72.7 | 74.5 | 72.7 | - |
| 03:45 | VM-only hybrid (hidden top 5 + ridge 6+) | 72.7 | 74.5 | 77.3 | +0.0 [+0.0, +0.0] / +0.0 [+0.0, +0.0] / +4.5 [+0.0, +9.1] |
| 03:45 | 00:05 clean prior alone (reference) | 51.5 | 52.7 | 70.9 | -21.2 [-39.4, +0.0] / -21.8 [-34.5, -9.1] / -1.8 [-7.3, +4.5] |

Published 03:45 hybrid (feed comments + distinct commenters, frozen P345 weights), recorder-only reads, 11 days: 72.7 / 74.5 / 77.3 (prereveal_12day_recorder_only.md).
