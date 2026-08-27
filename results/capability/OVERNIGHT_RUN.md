# Overnight SFT run — Ministral-3-3B → web CUA

**Status: COMPLETE.** Ran 11:03 → 15:40 UTC. A100 deleted; billing stopped.

## Result

| Metric | Value |
|---|---|
| Training loss | 1.51 → **0.66** |
| Steps | 1,369 (1 epoch, 21,891 samples) |
| Throughput | 1.34 samples/s · 4.52 h |
| **Action parse rate** | **100%** (25/25) |
| **Click within 5% of canvas** | **48%** (12/25) |

The model reliably emits the trained `Thought / Action / pyautogui.click(x, y)` format and lands
roughly half its clicks within 5% of the gold target. Sample output:

```
PRED: Thought: To achieve the goal of searching for thriller movies directed by Wilcox from 2016,
      I need to enter 'thriller' in the genre field...
      pyautogui.click(x=0.6323, y=0.6881)
GOLD: pyautogui.click(x=0.6625, y=0.6405)     -> hit
```

**These are single-step grounding numbers, not OM2W task success.** Real OM2W requires the
coordinate harness (`MISTRAL_CUA_FINETUNE_PLAN.md` Phase 5).

> **`eval_summary.json` in the bucket reports `parsed: 0` — ignore it.** The in-training eval
> capped generation at 128 tokens, which truncates before the `pyautogui` line whenever the
> Thought block runs long. `eval_full.json` has the correct numbers at 384 tokens.

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

## Cost (final)

| Item | Cost |
|---|---|
| A100 `a2-highgpu-1g`, ~5.2 h @ $3.67/h | $19.10 |
| T4 VM (shared with the parallel agent's Fara proxy) | ~$4.50 |
| Boot disk, egress, GCS storage | ~$0.80 |
| **Total** | **~$24** |

A100 instance and its 300 GB disk are **deleted** — no further charge. The T4
(`oprior-1787208583-uscentral1a`) is still up and is not ours to stop; another agent is serving
Fara on it at ~$0.73/h.

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
