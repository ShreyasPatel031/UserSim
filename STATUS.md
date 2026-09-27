# Socrates Training Status - Qwen3-14B SFT

## Task 1: Backups ✅

All checkpoints and predictions backed up to GCS bucket `gs://ai-studio-bucket-347838016394-us-east1/usersim-models/`:

| Path | Description | Count/Size |
|------|-------------|------------|
| `ckpt425/` | SFT adapter checkpoint-425 | 2 files, 166.6 MiB |
| `ckpt425_dpo384/` | DPO checkpoint-384 | 16 files, 351.7 MiB |
| `eval_preds/ckpt425_full40/` | ckpt-425 full-40 predictions | 5 files, 64.1 MiB |
| `eval_preds/qwen3_14b_full40/` | Qwen3-14B full-40 predictions | 80 files, 64.0 MiB |
| `eval_preds/ckpt425_dpo_full40/` | DPO eval results | 7 files, 64.0 MiB |

## Task 2: Re-sort Test ✅

**Concept:** Keep ckpt-425's multiset of predicted values but assign them in Qwen3-14B's rank order.

### Results on 5 Screen Studies

| Model | W | acc_raw | acc_clipped |
|-------|---|---------|-------------|
| ckpt-425 | 0.143 | 55.6% | 63.1% |
| Qwen3-14B | 0.253 | 67.6% | 72.8% |
| **re-sorted** | **0.143** | 57.1% | 64.6% |
| mix (p=0.29) | 0.143 | 55.6% | 63.1% |

### Results on Full 40 Studies

| Model | W | acc_raw | acc_clipped |
|-------|---|---------|-------------|
| ckpt-425 | 0.142 | 60.6% | 67.6% |
| Qwen3-14B | 0.215 | 67.0% | 73.2% |
| **re-sorted** | **0.142** | 60.9% | 67.9% |
| mix (p=0.29) | 0.142 | 60.6% | 67.6% |

### Pass Bar Check (screen)
- ✓ W <= 0.160 (0.143)
- ✗ acc_raw >= 65.0% (57.1%)
- ✗ acc_clipped >= 70.0% (64.6%)
- ~~✓ beats mix on W~~ ⚠️
- ~~✓ beats mix on acc_clipped~~ ⚠️

**Note on "beats mix" claims:** The mix metrics matching ckpt-425 exactly was due to a bug in `build_lookup()` - it keyed on nonexistent fields, so the mix fallback always used ckpt-425 predictions. In other words, mix == ckpt-425, making the "beats mix" comparison meaningless.

**Conclusion:** Re-sorting maintains W quality but doesn't achieve accuracy bar.

## Task 3: Qwen3-14B QLoRA SFT 🚀

### Training Configuration
- **VM:** `fm-sft-socrates-l4` (Spot g2-standard-8 + 1x L4)
- **Region:** US Central
- **Model:** Qwen/Qwen3-14B
- **Trainable params:** 64.2M (0.43% of 14.8B)

### Hyperparameters (updated after OOM restart)
| Parameter | Value |
|-----------|-------|
| r | 16 |
| lr | 1e-4 |
| MAX_SEQ | 768 |
| micro_batch | 2 |
| grad_accum | 16 |
| effective_batch | 32 |
| MAX_STEPS | 600 |
| SAVE_STEPS | 20 |
| bf16 | True |
| enable_thinking | False |
| PYTORCH_CUDA_ALLOC_CONF | expandable_segments:True |

### Training Progress
- **Relaunched:** 00:53 PT (2026-09-27) after CUDA OOM at step ~17
- **Step rate:** ~43.5 s/step
- **ETA:** ~8:15 AM PT

### Watchdog Labels
```
usersim-spot-watch=true
usersim-train-state=running
usersim-failover-to=fm-sft-socrates-l4-od
```

### Checkpoints → GCS
All checkpoints uploaded to `gs://ai-studio-bucket-347838016394-us-east1/usersim-models/qwen3_14b_sft/`

### Screens Scheduled
Screens now pause training, run evaluation, then resume (to avoid GPU OOM):
- Step 200: ~2.5 hours after start (~3:15 AM PT)
- Step 400: ~5 hours after start (~5:45 AM PT)
- Step 600: ~7.5 hours after start (~8:15 AM PT)

Screen pass bar: W <= 0.160, acc_raw >= 66.0%, acc_clipped >= 70.0%

Early stop trigger: W > 0.20 or clipped < 65% at step 200.

### Budget
- Spot L4 rate: $0.512/h
- Expected duration: ~7.5 hours
- Expected cost: ~$4.00 (well under $5.6 budget)

### Monitor Script Fixes (2026-09-27)
- Removed in-VM step-20 sanity check (runs on separate VM)
- Screens now stop training → run eval → resume training (no GPU sharing)
- Added trap to always reset gate-state on exit/failure
- Clear stale train.exit_code at boot
- Skip screens whose SUMMARY.json already exists in GCS
- Stop VM after step-600 screen completes
- Log upload errors to file instead of DEVNULL
- Final upload copies only adapter files (not checkpoint subdirs)
- Fixed left-truncation of prompts in sanity checks
- Allow negative numbers in format check regex
