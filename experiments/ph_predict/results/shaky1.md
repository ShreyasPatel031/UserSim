# Why arm 2's #1 pick misses the top 3 (pre-registered, shaky1.py @ 20284dd7)

Miss days vs hit days (means, miss / hit), pre-launch fields of pick #1:

| field | 2026 (184 days, #1 hits 70.7%) | 2025 (204 days, #1 hits 60.3%) |
|---|---|---|
| margin #1 - #2 (score) | 0.152 / 0.188 | 0.168 / 0.189 |
| margin / day sd | 0.43 / 0.53 | 0.48 / 0.54 |
| log line-up size | 3.12 / 3.16 | 2.85 / 2.83 |
| hunter earlier launches (log1p) | 4.79 / 4.97 | 2.73 / 3.36 |
| hunter earlier top-5 share | 0.61 / 0.64 | 0.57 / 0.60 |
| #1 maker has no earlier launch | 0.11 / 0.33 | 0.01 / 0.39 |
| same-topic launches that day (#1) | 12.6 / 15.0 | 9.5 / 8.6 |
| weekend | 0.20 / 0.18 | 0.07 / 0.11 |

Misses come with a smaller #1-#2 margin and a weaker hunter record; "first-time maker" is strongly tied to hits
(likely a data property of hist_maker_n == 0, not causal; worth a check before using it).

Flag (logistic on 2025 discordant days, flag = P(#2 beats #1) > 0.5, no tuning). Swap #1 <-> #2 on flagged days:

| | days | flagged | #1 top 3, arm 2 | #1 top 3, swap | swap - arm 2 |
|---|---|---|---|---|---|
| 2025 (fit, in-sample) | 204 | 73 | 60.3 | 63.2 | +2.9 [-3.4, +9.3] |
| **2026 test** | 184 | 58 | 70.7 [64.1, 77.2] | 72.3 [65.8, 78.8] | **+1.6 [-4.3, +7.6]** |

On flagged 2026 days #1 hit 56.9% and #2 hit 62.1%. A 1 <-> 2 swap leaves top-3 hits unchanged (58.0) by construction.
Secondary (demote #1 to 4th on flagged days): top-3 hits 55.4 vs 58.0, -2.5 [-4.3, -0.5] (worse).

Verdict: no swap. The flag does not clear 0 on 2026; demoting #1 hurts. Use the flag only as a label ("close call") if at all.
