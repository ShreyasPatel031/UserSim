# ph_n_makers drop test (pre-registered, drop_nmakers.py @ 5de1c2f3)

Arm 2 vs arm 2 with ph_n_makers and ph_dayrank_ph_n_makers dropped. Same rows, months and seeds (5), month-forward.
Paired drop - arm 2, day bootstrap 95%.

| year | days | arm 2 (re-run) | drop | top 3 | top 5 (primary, 2026) | top 10 |
|---|---|---|---|---|---|---|
| 2026 (truth_daily) | 184 | 56.0 / 65.0 / 75.9 | 52.7 / 64.0 / 73.7 | -3.3 [-6.3, -0.4] | -1.0 [-2.8, +0.9] | -2.2 [-3.3, -1.1] |
| 2025 (stored dailyRank) | 204 | 48.5 / 60.7 / 78.9 | 47.2 / 57.7 / 76.2 | -1.3 [-4.1, +1.6] | -2.9 [-4.8, -1.1] | -2.6 [-3.7, -1.7] |

The re-run arm 2 is not bit-identical to the stored published backtest (corr 0.9967, max |diff| 0.22; 56.0/65.0/75.9 vs 58.0/65.2/76.5).
The comparison is paired within the re-run.

Pre-registered rule: 2026 top 5 = -1.0 [-2.8, +0.9] is not worse beyond noise, so by the letter the drop goes into the next bundle.
However, the drop is worse beyond noise on 2026 top 3 and top 10 and on 2025 top 5 and top 10, so it costs real accuracy.
The leak it removes is small (stored rows add +0.14 makers to winners vs +0.05 to others).
