# Phase 0 / Socrates pivot status — 2026-09-08

## Live jobs

| Job | VM | Status |
|---|---|---|
| Qwen3-8B-Base Socrates floor | `fm-floor-qwen-l4` (L4 Spot) | **RUNNING** — resumed from 40192 preds; ~1.2k/min toward 482642 |
| Minitaur / Centaur Psych-101 | `fm-gate0-minitaur` (T4) | **STOPPED** — SUMMARY complete (6561/6561); watch label removed |
| Spot watchdog | `fm-gate0-spot-watchdog` | Running (will revive labeled Spot VMs only) |

## Baselines

- **Socrates-14B-SFT** (paper repro): W≈**0.150** on 40 unseen studies (`results/fm_baselines/socrates/SUMMARY.json`). STATUS previously said smoke-only — that was stale.
- **Minitaur**: complete (`results/fm_baselines/minitaur/SUMMARY.json`).
- **Qwen3-8B-Base Socrates floor**: in progress; local checkpoint 40k+ preds under `results/fm_baselines/qwen3_8b_floor_socrates/`.
- **Psych-101 Qwen floor**: invalid (null NLLs) — parked.
- **Be.FM train clone**: deprioritized (train mix not public).

## Next

See `docs/plans/socrates_finetune.md` — finish floor → seen-study corpus → QLoRA SFT kill-test → full SFT vs W=0.151.
