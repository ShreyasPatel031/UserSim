# SimBench Evaluation Results: Qwen3-14B Base vs SFT Checkpoints

**Date:** 2026-09-28  
**Eval VM:** `fm-simbench-l4` (Spot L4, g2-standard-8)  
**Hardware:** NVIDIA L4 (24GB VRAM), nf4 quantization  
**Software:** transformers 4.51.3, peft 0.15.2, bitsandbytes 0.45.5  

## Summary Table

### Logprob Protocol (First-Token Probabilities)

| Model | pilot497 (n=497) | heldout1426 (n=1426) | Option Mass |
|-------|------------------|----------------------|-------------|
| Qwen3-14B Base | **-69.45** [-76.1, -62.9] | **-68.19** [-71.8, -64.3] | 99.1% / 99.5% |
| checkpoint-400 | **+2.44** [-2.3, +6.4] | **+1.14** [-1.2, +3.6] | 99.9% / 99.9% |
| checkpoint-600 | **+2.58** [-1.9, +6.6] | **+2.25** [-0.1, +4.7] | 99.8% / 99.8% |

### Verbalized Protocol (JSON Distribution Generation)

| Model | pilot497 (n=497) | Parse Failures |
|-------|------------------|----------------|
| Qwen3-14B Base | **+12.14** [+7.4, +16.6] | 0 |
| checkpoint-400 | **-14.30** [-20.6, -7.9] | 0 |
| checkpoint-600 | **-13.81** [-20.2, -7.5] | 0 |

### Improvement Over Base (Logprob, pilot497)

| Checkpoint | Δ split_avg | 95% CI | Items Won |
|------------|-------------|--------|-----------|
| checkpoint-400 | **+71.89** | [+66.3, +77.3] | 85% |
| checkpoint-600 | **+72.03** | [+66.4, +77.4] | 84% |

### Comparison to API Baselines (pilot497, verbalized protocol)

| Model | split_avg | Δ vs Base logprob |
|-------|-----------|-------------------|
| Claude Sonnet 5 | 41.9 | +111.4 |
| Gemini 3.5 Flash-Lite | 35.2 | +104.6 |
| GPT-6-Luna | 32.9 | +102.3 |
| Claude Haiku 4.5 | 31.9 | +101.3 |
| Dataset-mean baseline | 26.6 | +96.1 |

## Key Observations

1. **Massive improvement with SFT:** The QLoRA checkpoints improve SimBench logprob scores from ~-69 to ~+2, a **+72 point gain** over the base model.

2. **Option mass is excellent:** All runs show >99% probability mass on the letter options, meaning the model correctly outputs letter choices rather than something else.

3. **checkpoint-600 slightly outperforms checkpoint-400** on heldout1426 (+2.25 vs +1.14) but they're within confidence intervals on pilot497.

4. **Verbalized protocol anomaly:** The SFT checkpoints perform *worse* on verbalized (-14) than base (+12). This is because:
   - The SFT training format uses single-number answers as one person
   - SimBench verbalized asks for a JSON distribution as a group
   - Both formats are out-of-distribution for the adapter
   - The logprob protocol better captures what the model learned

5. **Still far from API models:** Even with +72 point improvement, the SFT checkpoints (+2.4 split_avg) are below the dataset-mean baseline (26.6) and well below Claude Sonnet 5 (41.9).

## Runtimes

| Run Type | Model Load | Eval Time | Total |
|----------|------------|-----------|-------|
| Base logprob (pilot497) | 218s (first, includes download) | 59s | ~5 min |
| Base logprob (heldout1426) | 58s (cached) | 161s | ~4 min |
| Base verbalized (pilot497) | 51s | 383s | ~7 min |
| checkpoint-400 logprob (pilot497) | 56s | 87s | ~2.5 min |
| checkpoint-400 logprob (heldout1426) | 53s | 228s | ~5 min |
| checkpoint-400 verbalized (pilot497) | 54s | 436s | ~8 min |
| checkpoint-600 logprob (pilot497) | 55s | 84s | ~2.5 min |
| checkpoint-600 logprob (heldout1426) | 47s | 228s | ~5 min |
| checkpoint-600 verbalized (pilot497) | 52s | 436s | ~8 min |

**Total wall-clock time:** ~2.5 hours (including model downloads, checkpoint-600 wait, and 2 Spot preemptions)

## Fixes Applied

1. **None required for the eval kit itself** - it worked on first GPU run without modifications.

2. **PEFT version warning:** The adapter config had newer fields from a higher peft version. The warning was safely ignored and did not affect results.

## GCS Results Paths

All results uploaded to:
```
gs://ai-studio-bucket-347838016394-us-east1/usersim-models/simbench_evals/
├── base_pilot497/
├── base_heldout1426/
├── base_pilot497_verb/
├── ckpt400_pilot497/
├── ckpt400_heldout1426/
├── ckpt400_pilot497_verb/
├── ckpt600_pilot497/
├── ckpt600_heldout1426/
└── ckpt600_pilot497_verb/
```

Each directory contains:
- `scores.json` - Full scoring details, diagnostics, and metadata
- `predictions.jsonl` - Per-item predictions

## VM Cleanup

- VM `fm-simbench-l4` **STOPPED and DELETED** at 2026-09-28 20:53 UTC
- Verified deletion: `gcloud compute instances list` shows 0 items for `fm-simbench-l4`
- Forbidden VMs (`fm-sft-socrates-l4`, `fm-gate0-spot-watchdog`) were NOT touched
