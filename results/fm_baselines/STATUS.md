# Phase 0 / Socrates pivot status — 2026-09-08

## Live jobs

| Job | VM | Status |
|---|---|---|
| Qwen3-8B-Base Socrates floor | `fm-floor-qwen-l4` (L4 Spot) | **COMPLETE** (482642/482642) — re-scored to W=**0.2186**; invalid as a baseline, see below |
| Socrates QLoRA SFT (Qwen3-8B-Base) | `fm-sft-socrates-l4` (L4 Spot) | **RUNNING** — 1 epoch over 165624 rows, 2588 steps @ ~54 s/step |
| Minitaur / Centaur Psych-101 | `fm-gate0-minitaur` (T4) | **STOPPED** — SUMMARY complete (6561/6561); watch label removed |
| Spot watchdog | `fm-gate0-spot-watchdog` | Running (revives both L4s; polls ~70 s) |

### Log

- **2026-09-08 10:15Z** — The floor had been dead for 3 h: a preemption at 07:01
  left a NUL-padded line in `predictions.jsonl`, the resume reader raised
  `JSONDecodeError`, and systemd restarted into the same file 63 times. The
  runner now skips unreadable lines; floor is back at ~1000 preds/min from
  67072/482642. The adapter eval shares that runner and would have hit the same
  trap. Separately, the SFT VM was preempted at 10:02 and auto-recovered, but
  restarted from step 0 because no checkpoint existed yet — checkpoints
  tightened from every 100 steps to every 25 (~20 min of exposure).

- **2026-09-08 12:00Z** — Checkpoint resume validated under real preemption: the
  SFT VM was preempted twice more and restarted from `checkpoint-50` and then
  `checkpoint-75`, losing under 25 steps each time. Effective throughput is
  ~75% of ideal (72 steps per 80 min against 96 ideal), so the 2588-step epoch
  lands nearer 46 h than 36 h. Floor at 184832/482642, ~850 preds/min, no
  restarts.

- **2026-09-08 17:30Z** — **The eval metric was wrong, and the eval smoke gate
  could not have caught it.** The floor runner scored Wasserstein on the raw
  response scale and printed it next to the paper's 0.151, which is defined on
  the paper's [0,1] standardization. Those numbers were never comparable, and
  with no clipping to the human range a single out-of-range generation (a base
  model answering "1997" on a 1-7 scale) moved the mean without bound — hence
  the 5.7e27 "floor". Three divergent copies of the scorer existed; the correct
  standardized one in `colab_socrates_wass.py` was the copy nothing called.
  All callers now import `scripts/fm_baselines/socrates_metric.py`.

  The smoke gate was `0 < W < 1`. After standardization W is *always* in [0,1],
  so that predicate can never fail: it waved through a smoke W of 0.670 against
  a target of 0.151. The gate now checks parse rate, bare-numeric adherence, and
  W against a `uniform_control` (the same metric scored with uniform draws),
  because an absolute W threshold cannot distinguish a working model from a
  broken one when W's scale depends on the response distribution. Fed the real
  completed floor run, the new gate fails it on all three checks.

### Socrates SFT smoke gates

| Gate | Result |
|---|---|
| Format parity (train text == eval prompt) | pass — `SYSTEM` parsed out of the eval runner, prompt tokens fully masked, 16 supervised tokens in an 8-row batch |
| Corpus, 3 studies | 440 rows, zero unseen study ids |
| Train, 20 steps | loss 1.468, no divergence, 14.1/23 GB GPU |
| Eval, 1 unseen study through vLLM + LoRA | **inadequate at the time** — recorded W = 0.670 and passed it on `0 < W < 1`. That W was 4.4x the paper target and should have stopped the run. Re-gated: fails. |
| Metric unit tests | 12/12 — scale invariance, bounded output under absurd predictions, unweighted study averaging, parse diagnostics |
| Corpus, full | 165624 rows / 170 studies, 32 participants per (study, condition, task) |

## Baselines

All Socrates numbers below are on the paper's [0,1] standardized scale, over the
same 40 unseen studies / 801 cells / 482642 rows, and are therefore comparable.

| Model | W | vs paper 0.151 |
|---|---|---|
| Socrates-14B-SFT (paper repro) | **0.1499** | matches |
| *Uniform-guessing control* | *0.1973* | — |
| Qwen3-8B-Base (our floor) | **0.2186** | worse than guessing |

- **Socrates-14B-SFT** (paper repro): W=**0.1499** (`results/fm_baselines/socrates/SUMMARY.json`).
  Its runner was never committed, so provenance was checked via cell accounting:
  it reports 801 cells and 2 degenerate-range skips, which is exactly what the
  standardized scorer produces on this data, whereas the raw-scale scorer gives
  803 cells and 0 skips. The repro therefore did standardize, and 0.1499 is a
  valid reference. Its predictions are gone with its VM, so it cannot be
  re-scored directly.
- **Qwen3-8B-Base Socrates floor**: complete, W=**0.2186** vs a uniform-guessing
  control of 0.1973 — i.e. *worse than random*
  (`results/fm_baselines/socrates_floor_qwen3_8b_base.json`). It emits a bare
  number on 47.8% of items and nothing parseable on 20.7%, because it is a raw
  pretrained LM with no instruction tuning. This answers the standing question
  about the paper's base: theirs was instruction-tuned, which is why it obeyed
  "a single number only" and ours does not. **Not a usable baseline**; the
  informative floor is the uniform control, and the number to beat is 0.151.
- **Minitaur**: complete (`results/fm_baselines/minitaur/SUMMARY.json`).
- **Psych-101 Qwen floor**: invalid (null NLLs) — parked.
- **Be.FM train clone**: deprioritized (train mix not public).

## Next

See `docs/plans/socrates_finetune.md` — finish floor → seen-study corpus → QLoRA SFT kill-test → full SFT vs W=0.151.
