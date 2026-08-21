# UI-TARS-2: open code vs open weights (correction)

**Verdict:** UI-TARS *project* code is open. **UI-TARS-2 model weights are not on Hugging Face / ModelScope.** Do not confuse with **UI-TARS-2B** (2B-parameter v1 checkpoint).

## Naming trap

| Name | What it is | Weights? |
|------|------------|----------|
| **UI-TARS-2B** | Original UI-TARS, **2 billion** params | Yes — `ByteDance-Seed/UI-TARS-2B-SFT` |
| **UI-TARS-2** | Sept 2025 paper model (~230B MoE / Seed-thinking-1.6), 88.2% Online-Mind2Web | **No public checkpoint found** |

Hugging Face search for `UI-TARS-2` only returns `UI-TARS-2B-*` repos. Official `ByteDance-Seed` TARS models as of this check:

- https://huggingface.co/ByteDance-Seed/UI-TARS-1.5-7B
- https://huggingface.co/ByteDance-Seed/UI-TARS-2B-SFT
- https://huggingface.co/ByteDance-Seed/UI-TARS-7B-SFT / `-DPO`
- https://huggingface.co/ByteDance-Seed/UI-TARS-72B-SFT / `-DPO`

No `UI-TARS-2` (version 2) repo.

## What *is* open (usable today)

| Artifact | URL | Notes |
|----------|-----|--------|
| Inference / deploy docs + action parser | https://github.com/bytedance/UI-TARS | `pip install ui-tars`; HF endpoint deploy for **released** checkpoints |
| Desktop agent | https://github.com/bytedance/UI-TARS-desktop | Local GUI agent; points at available models / providers |
| Browser automation | https://github.com/web-infra-dev/Midscene | Separate OSS harness that can call UI-TARS-style models |
| Paper + demos | https://arxiv.org/abs/2509.02544 · https://seed-tars.com/showcase/ui-tars-2/ | Report + videos, not weights |
| Community ask for v2 weights | https://github.com/bytedance/UI-TARS/issues/213 | Still open; ByteDance: “we will consider”; commenters still asking for UITARS2 |

## Official wording (README)

- **Open-sourced:** UI-TARS-1.5-**7B** only (explicit HF link).
- **Announced:** UI-TARS-2 via tech report + showcase site — no HF download link.
- **Gated:** full (non-7B) UI-TARS-1.5 = “early research access” → `TARS@bytedance.com`.

## Hostable pick for our bakeoff

For GCP T4/L4 self-host: use **UI-TARS-1.5-7B** (or Fara1.5-4B/9B), not UI-TARS-2. The 88.2% Online-Mind2Web number is the **closed** UI-TARS-2 paper model, not the open 7B (~31% in MolmoWeb’s table).
