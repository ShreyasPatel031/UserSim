# Phase 0 / Socrates pivot status — 2026-09-08

## Live jobs

| Job | VM | Status |
|---|---|---|
| Qwen3-8B-Base Socrates floor | `fm-floor-qwen-l4` (L4 Spot) | **RUNNING** — resumed from 40192 preds; ~1.2k/min toward 482642 |
| Socrates QLoRA SFT (Qwen3-8B-Base) | `fm-sft-socrates-l4` (L4 Spot) | **RUNNING** — 1 epoch over 165624 rows, 2588 steps @ ~54 s/step |
| Minitaur / Centaur Psych-101 | `fm-gate0-minitaur` (T4) | **STOPPED** — SUMMARY complete (6561/6561); watch label removed |
| Spot watchdog | `fm-gate0-spot-watchdog` | Running (revives both L4s; polls ~70 s) |

### Socrates SFT smoke gates (all passed before the full run)

| Gate | Result |
|---|---|
| Format parity (train text == eval prompt) | pass — `SYSTEM` parsed out of the eval runner, prompt tokens fully masked, 16 supervised tokens in an 8-row batch |
| Corpus, 3 studies | 440 rows, zero unseen study ids |
| Train, 20 steps | loss 1.468, no divergence, 14.1/23 GB GPU |
| Eval, 1 unseen study through vLLM + LoRA | W = 0.670 on 16060 preds (pipeline sanity, not quality — adapter had 20 steps) |
| Corpus, full | 165624 rows / 170 studies, 32 participants per (study, condition, task) |

## Baselines

- **Socrates-14B-SFT** (paper repro): W≈**0.150** on 40 unseen studies (`results/fm_baselines/socrates/SUMMARY.json`). STATUS previously said smoke-only — that was stale.
- **Minitaur**: complete (`results/fm_baselines/minitaur/SUMMARY.json`).
- **Qwen3-8B-Base Socrates floor**: in progress; local checkpoint 40k+ preds under `results/fm_baselines/qwen3_8b_floor_socrates/`.
- **Psych-101 Qwen floor**: invalid (null NLLs) — parked.
- **Be.FM train clone**: deprioritized (train mix not public).

## Next

See `docs/plans/socrates_finetune.md` — finish floor → seen-study corpus → QLoRA SFT kill-test → full SFT vs W=0.151.
