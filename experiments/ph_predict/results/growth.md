# Expected day-end votes: growth multipliers from a read at T

m = day-end votes / votes at T (from the reveal) or / est_votes at T (before it). Median with p10-p90; n launches (days).
Sources: hourly 5 days (2026-10-31..2026-11-07), 980 rows; live 4 days (2026-11-04..2026-11-10), 2177 rows; wayback 27 days (2026-07-01..2026-10-17), 659 rows.

## Multipliers by T and leader position (all days; weekday / weekend split in growth.json)

| kind | T (h after 00:00 PT) | top 3 | 4-10 | rest | all |
|---|---|---|---|---|---|
| est | 0.75 | 2.89 [1.77-6.84] n 9 (3) | 3.70 [2.00-8.62] n 21 (3) | 2.23 [1.72-3.86] n 71 (3) | 2.35 [1.75-6.52] n 101 (3) |
| est | 1 | 2.89 [1.77-6.84] n 9 (3) | 3.70 [2.00-8.62] n 21 (3) | 2.23 [1.72-3.86] n 71 (3) | 2.35 [1.75-6.52] n 101 (3) |
| est | 1.5 | 2.41 [1.84-4.18] n 9 (3) | 1.83 [1.07-6.26] n 21 (3) | 2.29 [1.72-3.86] n 71 (3) | 2.23 [1.61-4.58] n 101 (3) |
| est | 2 | 2.41 [1.84-4.18] n 9 (3) | 2.00 [1.58-6.56] n 21 (3) | 2.23 [1.72-3.78] n 71 (3) | 2.23 [1.66-4.58] n 101 (3) |
| est | 2.5 | 3.02 [1.85-3.77] n 9 (3) | 1.80 [1.40-2.49] n 21 (3) | 2.10 [1.61-3.38] n 71 (3) | 2.07 [1.50-3.33] n 101 (3) |
| est | 3 | 3.02 [1.85-3.77] n 9 (3) | 1.80 [1.40-2.49] n 21 (3) | 2.10 [1.61-3.38] n 71 (3) | 2.07 [1.50-3.33] n 101 (3) |
| est | 3.5 | 2.93 [1.68-3.46] n 9 (3) | 1.80 [1.37-2.81] n 21 (3) | 1.97 [1.19-2.96] n 71 (3) | 1.97 [1.26-2.96] n 101 (3) |
| est | 3.75 | 2.64 [1.68-3.23] n 9 (3) | 1.47 [1.25-2.81] n 21 (3) | 1.92 [1.19-2.39] n 71 (3) | 1.89 [1.25-2.86] n 101 (3) |
| votes | 4 | 2.47 [1.72-2.84] n 18 (6) | 1.57 [1.17-2.59] n 42 (6) | 1.14 [1.06-1.36] n 121 (6) | 1.23 [1.06-2.44] n 181 (6) |
| votes | 4.25 | 2.32 [1.73-2.98] n 24 (8) | 1.58 [1.22-2.29] n 48 (8) | 1.13 [1.06-1.34] n 121 (6) | 1.23 [1.06-2.27] n 193 (8) |
| votes | 4.5 | 2.20 [1.70-3.01] n 27 (9) | 1.51 [1.22-2.33] n 50 (9) | 1.12 [1.05-1.34] n 121 (6) | 1.23 [1.06-2.24] n 198 (9) |
| votes | 5 | 2.03 [1.64-2.61] n 45 (15) | 1.54 [1.19-2.36] n 68 (15) | 1.11 [1.03-1.28] n 121 (6) | 1.26 [1.06-2.14] n 234 (15) |
| votes | 6 | 1.83 [1.57-2.13] n 54 (18) | 1.49 [1.20-2.06] n 80 (18) | 1.10 [1.03-1.25] n 121 (6) | 1.27 [1.05-1.97] n 255 (18) |
| votes | 7 | 1.66 [1.40-2.14] n 42 (14) | 1.36 [1.13-1.75] n 75 (14) | 1.07 [1.02-1.20] n 147 (8) | 1.16 [1.03-1.72] n 264 (14) |
| votes | 8 | 1.57 [1.38-1.91] n 54 (18) | 1.33 [1.12-1.68] n 91 (18) | 1.07 [1.02-1.17] n 156 (9) | 1.16 [1.03-1.64] n 301 (18) |
| votes | 9 | 1.48 [1.31-1.74] n 51 (17) | 1.29 [1.10-1.60] n 87 (17) | 1.06 [1.01-1.16] n 157 (9) | 1.13 [1.03-1.56] n 295 (17) |
| votes | 10 | 1.39 [1.26-1.60] n 60 (20) | 1.26 [1.08-1.50] n 97 (20) | 1.05 [1.01-1.13] n 157 (9) | 1.11 [1.02-1.48] n 314 (20) |
| votes | 11 | 1.32 [1.21-1.49] n 60 (20) | 1.20 [1.07-1.47] n 97 (20) | 1.05 [1.01-1.11] n 157 (9) | 1.11 [1.02-1.41] n 314 (20) |
| votes | 12 | 1.29 [1.17-1.44] n 57 (19) | 1.19 [1.06-1.43] n 89 (19) | 1.04 [1.00-1.09] n 150 (8) | 1.09 [1.01-1.36] n 296 (19) |

## Weekday vs weekend (votes, all positions)

| T | weekday | weekend |
|---|---|---|
| 4 | 1.20 n 164 (5) | 1.30 n 17 (1) |
| 4.25 | 1.21 n 170 (6) | 1.41 n 23 (2) |
| 4.5 | 1.22 n 175 (7) | 1.41 n 23 (2) |
| 5 | 1.23 n 205 (12) | 1.60 n 29 (3) |
| 6 | 1.24 n 220 (14) | 1.60 n 35 (4) |
| 7 | 1.13 n 189 (9) | 1.18 n 75 (5) |
| 8 | 1.12 n 195 (10) | 1.21 n 106 (8) |
| 9 | 1.09 n 183 (8) | 1.23 n 112 (9) |
| 10 | 1.11 n 208 (12) | 1.16 n 106 (8) |
| 11 | 1.11 n 220 (14) | 1.10 n 94 (6) |
| 12 | 1.09 n 219 (14) | 1.09 n 77 (5) |

## Leave-one-day-out error of predicted day-end votes (median abs % error; launches with day-end >= 10)

none = the read alone; T-only = one multiplier per T; fitted = per T x position x weekday/weekend.

| kind | T | source | n (days) | none | T-only | fitted | fitted, top-10 positions |
|---|---|---|---|---|---|---|---|
| est | 0.75 | live | 101 (3) | 57.5 | 43.9 | 28.6 | 56.4 |
| est | 1 | live | 101 (3) | 57.5 | 43.9 | 28.6 | 56.4 |
| est | 1.5 | live | 101 (3) | 55.1 | 29.8 | 29.5 | 43.7 |
| est | 2 | live | 101 (3) | 55.1 | 27.8 | 27.3 | 36.4 |
| est | 2.5 | live | 101 (3) | 51.7 | 20.5 | 20.8 | 30.3 |
| est | 3 | live | 101 (3) | 51.7 | 20.5 | 20.8 | 30.3 |
| est | 3.5 | live | 101 (3) | 49.2 | 17.4 | 20.2 | 30.5 |
| est | 3.75 | live | 101 (3) | 47.0 | 19.2 | 20.5 | 33.8 |
| votes | 4 | hourly | 55 (2) | 24.7 | 12.2 | 8.9 | 15.4 |
| votes | 4 | live | 126 (4) | 14.9 | 14.4 | 9.5 | 33.9 |
| votes | 4.25 | hourly | 55 (2) | 24.7 | 12.9 | 9.4 | 11.5 |
| votes | 4.25 | live | 126 (4) | 13.8 | 15.4 | 7.6 | 24.9 |
| votes | 4.25 | wayback | 12 (2) | 47.7 | 36.3 | 17.2 | 17.2 |
| votes | 4.5 | hourly | 55 (2) | 24.7 | 12.4 | 9.1 | 11.9 |
| votes | 4.5 | live | 126 (4) | 12.2 | 15.2 | 6.5 | 21.4 |
| votes | 4.5 | wayback | 17 (3) | 48.9 | 37.5 | 13.9 | 13.9 |
| votes | 5 | hourly | 55 (2) | 21.1 | 14.9 | 8.0 | 10.6 |
| votes | 5 | live | 126 (4) | 11.6 | 21.9 | 6.6 | 23.8 |
| votes | 5 | wayback | 53 (9) | 49.2 | 36.1 | 16.1 | 16.1 |
| votes | 6 | hourly | 55 (2) | 18.2 | 14.7 | 7.6 | 8.8 |
| votes | 6 | live | 126 (4) | 11.0 | 21.6 | 6.1 | 17.4 |
| votes | 6 | wayback | 74 (12) | 43.8 | 28.8 | 10.4 | 10.4 |
| votes | 7 | hourly | 101 (4) | 14.3 | 9.9 | 6.3 | 11.3 |
| votes | 7 | live | 126 (4) | 9.5 | 12.3 | 4.6 | 15.0 |
| votes | 7 | wayback | 37 (6) | 37.6 | 28.2 | 8.1 | 8.1 |
| votes | 8 | hourly | 120 (5) | 13.7 | 9.4 | 5.4 | 8.5 |
| votes | 8 | live | 126 (4) | 8.1 | 11.8 | 5.0 | 15.0 |
| votes | 8 | wayback | 55 (9) | 35.9 | 26.3 | 9.1 | 9.1 |
| votes | 9 | hourly | 121 (5) | 12.2 | 8.5 | 5.0 | 8.2 |
| votes | 9 | live | 126 (4) | 6.9 | 10.3 | 4.0 | 13.6 |
| votes | 9 | wayback | 48 (8) | 32.2 | 23.5 | 8.0 | 8.0 |
| votes | 10 | hourly | 121 (5) | 9.0 | 7.8 | 4.5 | 7.0 |
| votes | 10 | live | 126 (4) | 6.4 | 9.4 | 3.7 | 13.0 |
| votes | 10 | wayback | 67 (11) | 25.6 | 17.4 | 6.2 | 6.2 |
| votes | 11 | hourly | 121 (5) | 8.0 | 7.2 | 3.9 | 6.4 |
| votes | 11 | live | 126 (4) | 6.0 | 8.4 | 3.4 | 12.4 |
| votes | 11 | wayback | 67 (11) | 22.7 | 14.6 | 7.4 | 7.4 |
| votes | 12 | hourly | 121 (5) | 7.2 | 6.7 | 3.4 | 6.3 |
| votes | 12 | live | 109 (3) | 4.2 | 8.4 | 2.9 | 10.3 |
| votes | 12 | wayback | 66 (11) | 21.8 | 15.0 | 6.0 | 6.0 |

## Weekly call: hand factors vs fitted (multipliers fitted without the scored day)

Truth = the week-so-far order by day-end votes at the end of the scored day; earlier days by their day-end votes. Nov 8 unusable (no Nov 5-7 day-end votes); Nov 9 is a Monday (no est_votes).

| day | R4 x 1.069 (hand) | R4 x fitted m | 03:45 est x 2 (hand) | 03:45 est x fitted m |
|---|---|---|---|---|
| 2026-11-04 | 67 / 80 / 80 | 100 / 100 / 90 | 67 / 60 / 80 | 67 / 60 / 80 |
| 2026-11-09 | 100 / 100 / 90 | 100 / 100 / 90 | - | - |
| 2026-11-10 | 67 / 80 / 80 | 67 / 100 / 90 | 67 / 80 / 90 | 67 / 80 / 90 |
| mean | 77.8 / 86.7 / 83.3 (3 d) | 88.9 / 100.0 / 90.0 (3 d) | 66.7 / 70.0 / 85.0 (2 d) | 66.7 / 70.0 / 85.0 (2 d) |

Live from Nov 12: weekly_live r4 uses the fitted factor (old ratio kept as old_ratio); new point weekly_live est (03:45 PT, not Mondays);
P files (comment_forecast) carry exp_final_votes = est_votes x m(est, T); R files (early_forecast) exp_final_votes = votes x m(votes, T).
Caveats: est multipliers rest on 3 days (Nov 4, 8, 10); the weekend split mostly falls back to the weekday+weekend cell (n < 20); Wayback covers only top-of-homepage launches and post-reveal T.
