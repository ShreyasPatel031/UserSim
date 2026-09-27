# Qwen3-14B DistMatch QLoRA checkpoint-1400: COLLAPSED

**Date**: 2026-09-27  
**Verdict**: Adapter collapsed — outputs constant token regardless of input.

## Evidence

| Test | Model | Result |
|------|-------|--------|
| Base only | Qwen3-14B (no adapter) | 50/50 valid across all question types |
| With adapter | + checkpoint-1400 LoRA | 0/60 valid — always emits "times" (token 15136) or "a" |

## Conclusion

The distribution-matching LoRA adapter has mode-collapsed. The 0% parse rate in the 5-study eval (W=0.304, acc=53.5%) is caused by broken adapter weights, not a format mismatch.

## Next Steps

1. Inspect training logs for divergence signs
2. Test earlier checkpoints (700, 350)
3. Pin PEFT version to 0.20.0 used during training
