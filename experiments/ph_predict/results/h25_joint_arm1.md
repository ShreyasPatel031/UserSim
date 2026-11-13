# Joint fit, th_n_pre inside the model (arm1; 214 days 2026 Apr-Oct; 5033 launches; 5 seeds)

| line | top 3 | top 5 | top 10 | diff vs clean_nosite + th_n_pre (t3 / t5 / t10, 95%) |
|---|---|---|---|---|
| clean_nosite + th_n_pre (LODO ridge, reference) | 60.1 | 68.7 | 75.3 | - |
| pure_th (joint, no 2025) | 60.6 | 68.4 | 75.0 | +0.5 [-1.6, +2.5] / -0.3 [-1.6, +1.0] / -0.3 [-0.8, +0.2] |
| both_th (joint, 2025 rows, th missing on them) | 59.3 | 68.1 | 74.9 | -0.8 [-3.3, +1.7] / -0.6 [-2.2, +1.0] / -0.4 [-1.2, +0.4] |
| pure + th_n_pre (stacked) | 60.1 | 68.5 | 75.2 | -0.0 [-1.2, +1.2] / -0.2 [-0.9, +0.6] / -0.0 [-0.4, +0.3] |
| both + th_n_pre (stacked) | 60.3 | 69.1 | 75.2 | +0.2 [-2.0, +2.3] / +0.4 [-1.0, +1.9] / -0.0 [-0.8, +0.7] |
| pure alone | 56.9 | 67.6 | 75.0 | -3.3 [-5.5, -0.9] / -1.1 [-2.6, +0.3] / -0.3 [-1.0, +0.3] |
| both alone | 58.7 | 67.9 | 75.1 | -1.4 [-4.2, +1.2] / -0.8 [-2.5, +0.8] / -0.2 [-1.0, +0.7] |

both_th (joint) minus both + th_n_pre (stacked): -0.9 [-3.0, +0.9] / -0.9 [-2.2, +0.4] / -0.3 [-0.8, +0.1]
