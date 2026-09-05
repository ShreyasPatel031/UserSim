# Phase 0 baseline status — 2026-09-05

Centaur-70B: SKIPPED (user request).

## Be.FM-1.5-4B — PARTIAL COMPLETE
8/8 tasked subset finished (`DONE.json`). Not full BehaviorBench board.
Highlights:
- strategic_gameplay_guessing win_rate: **0.485** (paper ~48% for 4B)
- pers_score_pred MAE_averaged: 7.69
- demo_pred_age MAE: 9.49
- game_behavior_dictator W: 3.56
Sessions: orphaned overnight but results still on disk when reattached.

## Socrates-Qwen-14B-SFT — SMOKE ONLY
2/40 unseen studies done.
- W = **0.184** (paper target **0.151**, empirical best 0.125)
- n_preds=1800, n_cells=90
Full unseen (~482k rows) NOT started.

## Minitaur Psych-101-test — FAILED
CUDA OOM on T4 at max_seq=8192 during NLL. No SUMMARY.

## Sessions
All three GPUs still assigned but kernels were orphaned; reattached for readout.
