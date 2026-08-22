# Overnight SFT run — Ministral-3-3B → web CUA

**Launched:** 2026-08-22 11:03 UTC · **ETA:** ~15:50 UTC (~4.5 h train + merge/eval/upload)

**Early health check:** loss 1.51 → 1.01 over the first 20 steps, GPU pinned at 100%. Learning.

## What is running

| | |
|---|---|
| VM | `usersim-a100-sft` · **us-central1-b** · `a2-highgpu-1g` |
| GPU | A100-SXM4-**40GB** (bf16 native) |
| Base | `mistralai/Ministral-3-3B-Base-2512` (Apache 2.0) |
| Data | 22,091 samples: mind2web 7,591 + guiact-web-single 12,000 + miniwob 2,500 |
| Method | LoRA r=64 on 182 LM modules + trainable projector, ViT frozen (115.6M trainable, 2.93%) |
| Schedule | 1 epoch, 1,369 optimizer steps, effective batch 16, cosine LR 1e-4 |
| Observed | ~12 s/step ≈ 1.33 samples/s, initial loss 1.50 |

**Not Colab** — Colab needs a human to keep the session alive. This is a dedicated VM
running detached under `nohup`, so it survives disconnection.

## When it finishes, automatically

1. Merges LoRA into the base weights → single servable bf16 checkpoint
2. Scores 50 held-out samples (parse rate + click within 5% of normalized canvas)
3. Uploads to `gs://ai-studio-bucket-347838016394-us-east1/usersim-models/Ministral3-3B-CUA-web`
4. **Powers the VM off** so billing stops

Shutdown only happens on the success path. If it crashes, the VM stays up with logs intact.

## Check it in the morning

```bash
export CLOUDSDK_CORE_PROJECT=project-amer-scs-sandbox

# Fastest signal: did the weights land?
gsutil ls gs://ai-studio-bucket-347838016394-us-east1/usersim-models/Ministral3-3B-CUA-web

# Loss curve (written every 10 steps, independent of transformers' logger)
gcloud compute ssh usersim-a100-sft --zone=us-central1-b --tunnel-through-iap \
  --command='tail -20 ~/usersim/logs/loss.jsonl'

# Held-out grounding score
gsutil cat gs://.../Ministral3-3B-CUA-web/eval_summary.json

# Full training log (uploaded alongside the weights)
gsutil cat gs://.../Ministral3-3B-CUA-web/train.log | tail -40
```

`STATUS: TERMINATED` on the VM means it finished cleanly and shut itself off.

```bash
gcloud compute instances describe usersim-a100-sft --zone=us-central1-b --format='value(status)'
```

If it's still `RUNNING` past ~16:00 UTC, something stalled:

```bash
gcloud compute ssh usersim-a100-sft --zone=us-central1-b --tunnel-through-iap \
  --command='tail -40 ~/usersim/logs/train.log'
```

## Reading the result

`eval_summary.json` reports `parsed` and `click_within_5pct`. This is a **grounding proxy**,
not an OM2W score.

- `parsed` near 50/50 means the model reliably emits `pyautogui.click(x=…, y=…)` — the format was learned
- `accuracy` is single-step click precision on held-out data

A healthy run lands parse rate near 100% and click accuracy well above zero. Real OM2W numbers
need the coordinate harness (not yet built — see `MISTRAL_CUA_FINETUNE_PLAN.md` Phase 5).

## Cost

A100 on-demand ≈ $3.67/h × ~5 h ≈ **$18**, then auto-off. The old T4
(`oprior-1787208583-uscentral1a`) is untouched and still running its own workload.

## Serve it

```bash
gsutil -m cp -r gs://.../Ministral3-3B-CUA-web ./
vllm serve ./Ministral3-3B-CUA-web --dtype bfloat16 --max-model-len 16384 \
  --limit-mm-per-prompt image=5 --trust-remote-code
```

**Inference must resize screenshots to exactly 1008×784**, matching training. Coordinates are
normalized `[0,1]`, so multiply by the real viewport to get pixels.

## Fixed during bring-up

- No `default` VPC in this project — VM created on `main-vpc` / `primary-subnet`
- A100 stockout in `us-central1-a` → placed in `us-central1-b`
- DLVM image shipped `torchaudio 2.11` against `torch 2.9`; transformers 5 imports torchaudio
  unconditionally, so it was pinned back to 2.9.1
- Fixed-size 200-sample holdout consumed the entire smoke set → holdout is now proportional
- `TrainingArguments.warmup_ratio` was removed in transformers 5 → `warmup_steps`
- transformers 5's progress callback drops metrics when stdout is not a TTY, so nothing was
  logged overnight → added a `LossLog` callback writing `loss.jsonl` plus `disable_tqdm=True`
