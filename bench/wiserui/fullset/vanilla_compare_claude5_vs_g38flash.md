n = 252 pairs

| system | CA [95% CI] | OI | FA / SA | unparsed (of 2n) | $/pair | total $ | wall | dCA vs ours [95% CI] | McNemar p (ours-wrong-model-right / reverse) | ours significantly better? |
|---|---|---|---|---|---|---|---|---|---|---|
| gemini-3.8-flash | 54.4 [48.0, 60.7] | 65.9 | 56.7 / 75.0 | 0 | 0.0072 | 1.80 | 83 s | (reference) | |  |
| claude-opus-5-5 | 66.7 [60.7, 72.6] | 75.4 | 67.9 / 82.9 | 0 | 0.0562 | 14.16 | 571 s | +12.3 [+6.0, +18.7] | 0.00024 (50/19) | no |
| claude-sonnet-5 | 37.3 [31.3, 43.3] | 58.1 | 40.1 / 76.2 | 0 | 0.0258 | 6.50 | 702 s | -17.1 [-23.4, -10.7] | 6.1e-07 (16/59) | yes |
