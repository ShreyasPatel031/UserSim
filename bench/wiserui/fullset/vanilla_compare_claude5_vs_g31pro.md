n = 252 pairs

| system | CA [95% CI] | OI | FA / SA | unparsed (of 2n) | $/pair | total $ | wall | dCA vs ours [95% CI] | McNemar p (ours-wrong-model-right / reverse) | ours significantly better? |
|---|---|---|---|---|---|---|---|---|---|---|
| gemini-3.1-pro | 57.9 [52.0, 63.9] | 71.0 | 61.1 / 80.6 | 1 | 0.0192 | 4.84 | 118 s | (reference) | |  |
| claude-opus-5-5 | 66.7 [60.7, 72.6] | 75.4 | 67.9 / 82.9 | 0 | 0.0562 | 14.16 | 571 s | +8.7 [+2.0, +15.1] | 0.014 (48/26) | no |
| claude-sonnet-5 | 37.3 [31.3, 43.3] | 58.1 | 40.1 / 76.2 | 0 | 0.0258 | 6.50 | 702 s | -20.6 [-27.4, -14.3] | 5.3e-09 (15/67) | yes |
