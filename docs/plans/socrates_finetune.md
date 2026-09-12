# Socrates / SocSci210 finetune plan

Status: draft 2026-09-08. Pivot off Be.FM train cloning. Centaur/Minitaur parked (baseline complete). Target: beat Socrates home metric on the public split with open data.

## Goal (fail-able)

On SocSci210 **unseen-study** split (`participant_mapping.json`: 170 seen train / 40 unseen eval), with the same eval harness we already use (`colab_qwen3_8b_floor_socrates_vllm.py` / `colab_socrates_wass.py`):

All W values are on the paper's [0,1] standardization, computed by the one
shared scorer `scripts/fm_baselines/socrates_metric.py`. Any W quoted without
that standardization is not comparable to 0.151 — see the metric post-mortem
below.

| Checkpoint | Metric | Target |
|---|---|---|
| Qwen3-8B-Base floor | mean Wasserstein W | **0.2186 — measured, and worse than the 0.1973 uniform-guessing control** |
| Paper Socrates-14B-SFT (reproduced) | W | **0.1499** (paper 0.151) ✓ |
| Our SFT on Qwen3-8B-Base | W | **&lt; 0.151** (beat paper) |
| Stretch | W | approach empirical bound **0.125** |

The base floor came in *worse than random guessing*, so "clear lift vs our own
floor" is not a meaningful bar and has been dropped. Qwen3-8B-Base emits a bare
number on only 47.8% of items and nothing parseable on 20.7%: it is a raw
pretrained LM, whereas the paper's base was **instruction-tuned**, which is why
theirs obeyed "a single number only". The bars that matter are the uniform
control (0.1973) and the paper (0.151).

Secondary: individual accuracy (paper DPO path). Do not optimize accuracy if it worsens W.

## What we already have

- Eval: resume-capable vLLM runner, temp=0.6, top_p=0.9, chat template, predictions.jsonl → SUMMARY.
- Paper repro: `results/fm_baselines/socrates/SUMMARY.json` → W≈0.150, 40 studies, 482642 preds.
- Floor: `fm-floor-qwen-l4` running Qwen3-8B-Base from 40k → ~482k preds (~1.2k/min on L4).
- Leakage registry scaffolding under `scripts/fm_train/build_leakage_registry.py` (extend for SocSci210 unseen prompts).
- Data: HF `socratesft/SocSci210` (~2.9M rows); local metadata under `data/fm_baselines/SocSci210_meta/metadata/`.

## Paper recipe (reproduce, then ablate)

From Socrates EMNLP 2025 / site:

- Base: **Instruct** (Llama3-8B-Instruct / Qwen2.5-14B-Instruct). We deliberately start from **Qwen3-8B-Base** for entropy / distributional metrics (documented alignment-simulation tradeoff).
- Split: `participant_mapping` unseen studies.
- SFT: 1 epoch, global batch 256, lr **1e-5**, cosine + warmup 0.05, wd **0.1**, 8×A100-80G, ~4–24h.
- DPO: same shape, lr **1e-6** (helps accuracy, hurts W in paper — run only after SFT W is good).
- Inference: T=0.6, top_p=0.9, max_len 4096.

## Stages

### S0 — Floor: DONE

1. Generation complete at 482642/482642; re-scored on CPU with the shared metric.
2. W = **0.2186** vs uniform control 0.1973 → below chance, invalid as a baseline.
   Recorded in `results/fm_baselines/socrates_floor_qwen3_8b_base.json`.
3. Floor VM stopped once generation was confirmed complete, then reused as a
   parallel eval box. Minitaur **deleted** (disk snapshotted) after being revived
   five times; a deleted instance cannot be revived.

### S1 — Train corpus (SocSci210 only)

1. Filter HF train split to `study_id ∈ seen` (170 studies). Never train on unseen 40.
2. Hash every unseen eval prompt into leakage registry; assert zero train overlap.
3. Format: same chat as eval (`system` + user survey prompt → assistant response number/text). Loss on assistant tokens only.
4. Optional pilot: subsample **N participants per (study, condition, task)** (e.g. 8 / 32 / all) to cut wall-clock while keeping cell coverage.
5. Deliverable: `data/fm_train/socrates_seen_corpus.jsonl` + card + filter log.

### S2 — Kill-test SFT (fast iteration)

Hardware: 1× L4 or A100; QLoRA (reuse `scripts/fm_train/sft_qwen3_8b_base_pilot.py` pattern).

| Knob | Pilot | Full SFT |
|---|---|---|
| Method | QLoRA r=16–64 | QLoRA or full FT if budget |
| Epochs | 0.1–0.25 on participant subsample | 1 |
| LR | 1e-5 (paper) and 5e-5 (Centaur-ish) | winner of pilot |
| Batch | effective 64–256 | 256 if memory allows |
| Seq | 2048–4096 | match data |

Eval during pilot: **smoke W on 5 unseen studies** (or MAX_PER_CELL=50) every N steps — full 482k only for gate.

**Kill gate:** adapter must beat floor W by ≥5% relative on the smoke set, else stop and change format/LR before full epoch.

### S3 — Full SFT + gate

1. Train 1 epoch on full seen corpus with winning recipe.
2. Full unseen W eval (same runner, swap model path / LoRA merge).
3. Gate: W &lt; 0.151 **and** W &lt; floor W. If only floor-beating but not paper, ship as “base+data win” and decide whether to scale to 14B or add objective.

### S4 — Objectives (only if S3 clears or stalls near paper)

In order of expected W gain:

1. Soft-label CE / KL to empirical cell distribution (study×condition×task) — paper metric is distributional; individual CE is misaligned.
2. Light DPO only if we care about accuracy; expect W regression (paper: SFT W=0.151, DPO W=0.181).
3. Do **not** chase Be.FM or Psych-101 in this branch.

## Compute routing

| Job | VM | Notes |
|---|---|---|
| Floor eval | `fm-floor-qwen-l4` (Spot L4) | Running; keep |
| Minitaur / Centaur | `fm-gate0-minitaur` | **STOPPED**; watch label cleared |
| SFT pilot | Prefer A100-40/80 when free; else L4 QLoRA after floor frees | |
| Watchdog | `fm-gate0-spot-watchdog` | Restarts labeled Spot VMs only |

## Explicit non-goals (this plan)

- Cloning Be.FM’s closed ~826k mix.
- Retraining Psych-101 / Centaur until Socrates S3 gate.
- BehaviorBench as a train target (optional later eval only).

## Immediate next actions

1. Monitor floor preds → SUMMARY.
2. Gate the SFT adapter's full-unseen W against the floor and against 0.151.
3. If the gate clears, decide 14B scale-up vs. soft-label objective (S4).

## Run log — full QLoRA on L4 (started 2026-09-08)

Live on `fm-sft-socrates-l4` (L4 24 GB Spot, same region as the floor VM), driven by
`scripts/fm_train/boot_socrates_sft.py` under `usersim-sft-socrates.service`.

| Setting | Value | Why |
|---|---|---|
| Corpus | 165624 rows, 170 seen studies, 32 per cell | A true all-rows epoch (2.3M rows) is ~5–15 days on one L4; capping participants per cell keeps every study/condition/task while fitting the box |
| Adapter | QLoRA r=16, alpha 32, all attn+MLP projections, 43.6M trainable (0.53%) | Fits nf4 8B in 14 GB with room for 1536-token batches |
| Batch | micro 4 x accum 16 = 64 | Paper used 256 on 8xA100; 64 is what one L4 sustains |
| LR / schedule | 1e-4, cosine, warmup 0.05, wd 0.1 | LoRA wants ~10x the paper's full-FT 1e-5 |
| Steps | 2588 (1 epoch) at ~54 s/step | ~39 h of GPU time, longer in wall clock with preemptions |
| Checkpoints | every 50 steps, keep 2 | Caps preemption loss near 45 min |

Resilience: the spot watchdog VM restarts a preempted instance, the boot
script's startup metadata re-enables the training unit, stage stamps skip
completed work, and the Trainer resumes from the newest checkpoint.
`sft_watchdog.py` polls every 5 min and writes `WATCHDOG.json` / `ALERT.json`
for divergence, OOM, repeated restarts and stalled stages.

Known non-blocking observation: the CUDA allocator logged one soft OOM retry
at step 1 and recovered. If hard OOMs appear, drop micro batch to 2 and raise
accumulation to 32 for the same effective batch.

### Metric post-mortem (2026-09-08) — why the floor read 5.7e27

Two bugs, either of which alone would have invalidated the number:

1. The floor runner scored Wasserstein on the **raw response scale** and printed
   it beside the paper's 0.151, which is defined on the paper's [0,1]
   standardization. The two were never comparable. And with no clipping into the
   human range, one out-of-range generation (a base model answering "1997" on a
   1-7 scale) moves the cell mean without bound — hence 1e27 rather than a
   number in [0,1].
2. The eval smoke gate was `0 < W < 1`. After standardization W is *always* in
   [0,1], so the predicate is vacuous: it passed a smoke W of 0.670 against a
   target of 0.151.

Three copies of the scorer existed and had drifted: the floor runner's
raw-scale one, a correct standardized one in `colab_socrates_wass.py` that
nothing called, and a third Wasserstein using 256-point quantile matching. All
callers now import `socrates_metric.py`, covered by 12 unit tests including
scale invariance and boundedness under absurd predictions.

The gate now checks parse rate, bare-numeric adherence, and W against a
`uniform_control` — the same metric scored with uniform draws. The control is
the load-bearing check: an absolute W threshold cannot separate a working model
from a broken one, because W's scale depends on the response distribution.

Cost of the bugs: the floor's 482,642 generations were *not* wasted (they
re-scored on CPU for free, and the run had in fact completed), but a day of L4
time went to a baseline that turned out to be below chance, and the signal that
would have revealed it was visible in the smoke result hours earlier.

Rule going forward: **no full eval sweep without a gated smoke on the same
scorer**, and no new copy of a metric.

### Environment traps hit on the way (all fixed in-repo)

- Building the corpus with `Dataset.to_list()` on 2.3M long prompts took 16 GB
  and was OOM-killed; the builder now streams Arrow batches.
- vLLM upgrades transformers to 5.x, which current peft cannot import, so
  training runs from `venvs/train` (transformers 4.x) while eval keeps the
  vLLM interpreter.
- That same upgrade moves torch ahead of the image's torchaudio, whose CUDA
  version guard blocks every vLLM import — torchaudio is removed instead.
- flashinfer JIT-builds sampling kernels at engine start, so `ninja` must be
  installed or the adapter eval dies in engine init.
- The plain Ubuntu image failed to build the NVIDIA kernel module; use the
  same `pytorch-2-9-cu129-ubuntu-2204-nvidia-580` DLVM image as the floor VM.
- Colab is not usable from the cloud agent: the service-account entitlement
  grants T4 only, and L4/A100/G4 are rejected outright.
