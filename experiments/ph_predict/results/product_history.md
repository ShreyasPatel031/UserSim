# Product history at 00:05 (214 days Apr-Oct; 5033 launches; 2025 lists: 190 days)

Coverage: launches with a prior launch of the same product 6.2% (final top 3: 9.7%); name carries a version/year 4.9% (top 3: 9.1%); hunter new 54.6% (top 3: 12.8%); self-hunted (leak-prone makers) 47.7% (top 3: 10.9%); busy days (30+ launches) 50

| model | top 3 | top 5 | top 10 | diff vs base (95%) | new-hunter top-3 launches caught | busy days t3/t5/t10 |
|---|---|---|---|---|---|---|
| pure + th_n_pre | 60.1 | 68.5 | 75.2 | - | 9 of 82 | 56.0 / 58.0 / 68.0 |
| pure + product history | 60.1 | 68.5 | 75.0 | -0.0 [-0.6, +0.6] / +0.0 [-0.4, +0.4] / -0.2 [-0.4, -0.0] | 9 of 82 | 56.0 / 57.6 / 68.0 |
| pure + product history + flags (name_ver, hunter_new) | 59.2 | 68.0 | 75.4 | -0.9 [-1.9, -0.2] / -0.5 [-1.2, +0.2] / +0.1 [-0.2, +0.6] | 8 of 82 | 55.3 / 56.8 / 68.2 |
| pure + flags only | 59.3 | 68.3 | 75.5 | -0.8 [-1.6, -0.0] / -0.2 [-0.9, +0.5] / +0.2 [-0.1, +0.6] | 8 of 82 | 55.3 / 58.0 / 68.2 |
| pure + self-hunted (LEAK-PRONE) | 60.0 | 68.5 | 75.0 | -0.2 [-0.5, +0.0] / +0.0 [-0.4, +0.4] / -0.3 [-0.5, -0.1] | 9 of 82 | 55.3 / 58.4 / 67.6 |
| both + th_n_pre | 60.6 | 70.3 | 75.3 | - | 9 of 82 | 56.7 / 61.2 / 68.8 |
| both + product history | 60.6 | 70.2 | 75.2 | +0.0 [-0.5, +0.5] / -0.1 [-0.3, +0.0] / -0.1 [-0.3, +0.1] | 9 of 82 | 56.7 / 60.8 / 68.8 |
| both + product history + flags (name_ver, hunter_new) | 60.6 | 70.0 | 75.0 | +0.0 [-0.5, +0.5] / -0.3 [-0.7, +0.1] / -0.3 [-0.7, +0.0] | 9 of 82 | 56.7 / 60.4 / 68.2 |
| both + flags only | 60.6 | 70.1 | 75.1 | +0.0 [+0.0, +0.0] / -0.2 [-0.6, +0.2] / -0.2 [-0.6, +0.1] | 9 of 82 | 56.7 / 60.8 / 68.2 |
| both + self-hunted (LEAK-PRONE) | 60.9 | 70.0 | 75.2 | +0.3 [+0.0, +0.8] / -0.3 [-0.7, +0.1] / -0.1 [-0.4, +0.1] | 10 of 82 | 56.7 / 60.8 / 68.4 |
