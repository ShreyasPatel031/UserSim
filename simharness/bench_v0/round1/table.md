| Model | HARD AUC (all 50,100 rows) | HARD-LLM AUC (960 rows) | vs logistic on HARD-LLM (paired) | EASY AUC | FULL recall@N | FULL AUC | $ / 1k | s / call |
|---|---|---|---|---|---|---|---|---|
| most-active | 0.499 [0.494, 0.502] | 0.461 [0.424, 0.492] | -0.047 [-0.070, -0.027] | 0.897 [0.871, 0.923] | 32.0 [30.4, 33.9] | 0.918 [0.910, 0.925] | 0.00 |  |
| logistic | 0.518 [0.515, 0.520] | 0.507 [0.482, 0.533] |  | 0.923 [0.895, 0.948] | 38.5 [36.6, 40.5] | 0.938 [0.932, 0.944] | 0.00 |  |
| taste-v1 | 0.529 [0.521, 0.537] | 0.579 [0.538, 0.620] | +0.072 [+0.013, +0.132] | 0.604 [0.523, 0.679] | 15.9 [14.5, 17.3] | 0.615 [0.562, 0.686] | 0.00 |  |
| taste-v1 hard-only (ablation) | 0.522 [0.515, 0.530] | 0.580 [0.541, 0.622] | +0.072 [+0.014, +0.133] | 0.365 [0.301, 0.430] | 10.3 [9.1, 11.6] | 0.383 [0.339, 0.441] | 0.00 |  |
| gemini-2.5-flash |  | 0.528 [0.511, 0.549] | +0.021 [-0.007, +0.050] |  |  |  | 0.52 | 0.98 |
| gpt-oss-120b |  | 0.517 [0.488, 0.549] | +0.010 [-0.019, +0.040] |  |  |  | 0.27 | 0.72 |
| llama-4-maverick |  | 0.522 [0.505, 0.541] | +0.015 [-0.009, +0.042] |  |  |  | 0.49 | 0.72 |
| claude-haiku-4-5 (scored before the restart; day-bootstrap interval) | | 0.517 [0.497, 0.537] | not available (per-row scores lost) | | | | 1.64 | 1.0 |
| claude-sonnet-4-6 (scored before the restart; day-bootstrap interval) | | 0.530 [0.515, 0.543] | not available (per-row scores lost) | | | | 4.91 | 1.83 |
| gemini-2.5-flash-lite tuned (yes/no, 4,000 train rows, 1 epoch) (scored before the restart; day-bootstrap interval) | | 0.517 [0.494, 0.543] | not available (per-row scores lost) | | | | 0.14 | 0.8 |

| Stack (weights fit on validation only) | HARD AUC | HARD-LLM AUC | vs logistic (paired) | vs its non-LLM member | FULL recall@N |
|---|---|---|---|---|---|
| logistic + taste-v1 (stack), FULL |  |  | -0.017 [-0.027, -0.006] (recall@N) |  | 36.8 [35.6, 38.2] |
| logistic + taste-v1 (stack) | 0.526 [0.519, 0.534] | 0.576 [0.537, 0.616] | +0.009 [+0.001, +0.018] |  |  |
| logistic + gemini-2.5-flash (stack) |  | 0.516 [0.495, 0.536] | +0.009 [-0.035, +0.054] | +0.009 [-0.035, +0.054] |  |
| taste-v1 + gemini-2.5-flash (stack) |  | 0.578 [0.539, 0.618] | +0.071 [+0.013, +0.129] | -0.001 [-0.004, +0.002] |  |
| logistic + gpt-oss-120b (stack) |  | 0.520 [0.488, 0.553] | +0.013 [-0.025, +0.050] | +0.013 [-0.025, +0.050] |  |
| taste-v1 + gpt-oss-120b (stack) |  | 0.587 [0.553, 0.620] | +0.079 [+0.030, +0.128] | +0.008 [-0.016, +0.033] |  |
