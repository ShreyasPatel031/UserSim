n = 252 pairs

| system | CA [95% CI] | OI | FA / SA | unparsed (of 2n) | $/pair | total $ | wall | dCA vs ours [95% CI] | McNemar p (ours-wrong-model-right / reverse) | ours significantly better? |
|---|---|---|---|---|---|---|---|---|---|---|
| ours: G-FOCUS single, T0, gemini-2.5-flash | 42.9 [36.5, 48.8] | 59.9 | 51.6 / 68.3 | 1 | 0.0110 | 2.77 | 89 s | (reference) | |  |
| claude-sonnet-4-6 vanilla | 36.5 [30.6, 42.5] | 59.3 | 38.9 / 79.8 | 0 | 0.0234 | 5.90 | 142 s | -6.3 [-13.1, +0.8] | 0.097 (33/49) | no |
| gpt-4o vanilla | 21.8 [16.7, 27.0] | 56.3 | 36.5 / 61.9 | 71 | 0.0127 | 3.21 | 96 s | -21.0 [-27.8, -14.3] | 8.4e-09 (17/70) | yes |
| gpt-4.1-mini vanilla | 31.7 [26.2, 37.3] | 56.7 | 36.9 / 76.6 | 0 | 0.0034 | 0.86 | 110 s | -11.1 [-17.9, -4.0] | 0.0026 (27/55) | yes |
| gpt-5-mini vanilla (minimal) | 35.3 [29.4, 41.3] | 55.0 | 41.3 / 68.7 | 0 | 0.0038 | 0.96 | 117 s | -7.5 [-14.7, -0.4] | 0.053 (34/53) | no |
| gemini-2.5-flash vanilla | 25.8 [20.2, 31.3] | 55.8 | 27.4 / 81.3 | 13 | 0.0030 | 0.77 | 128 s | -17.1 [-23.4, -10.7] | 6.1e-07 (16/59) | yes |
