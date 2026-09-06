# Online web CUA models — complete assessment (verified)

Re-checked every row in the bakeoff table against Hugging Face APIs (disk sizes), official READMEs/papers, and GitHub. **Numbers below are author-reported** unless noted; protocols differ (step budget, judge, pass@k).

## Corrected leaderboard (what we care about)

| Model | Open weights? | Disk (HF bf16) | Realistic host | Online-Mind2Web | WebVoyager | Source of scores | Code / weights |
|-------|---------------|----------------|----------------|-----------------|------------|------------------|----------------|
| **Fara1.5-27B** | **Yes** (MIT) | **54.7 GB** | multi-GPU / A100-80 | **72.3%** | **89.3%** | MS HF card / fara README | [HF](https://huggingface.co/microsoft/Fara1.5-27B) · [github.com/microsoft/fara](https://github.com/microsoft/fara) |
| **UI-TARS-2** | **No** | — | N/A (paper/demo only) | **88.2%** | — | [arxiv 2509.02544](https://arxiv.org/abs/2509.02544) | Code/desktop open; **no** `UI-TARS-2` HF repo (≠ **UI-TARS-2B**) — see `UI_TARS_2_WEIGHTS.md` |
| **UI-TARS-1.5** (full) | **No** (email access) | — | ByteDance gated | **75.8%*** | **84.8%*** | [UI-TARS README](https://github.com/bytedance/UI-TARS) | Contact `TARS@bytedance.com` |
| **OpenWebRL-4B** | **Yes** | **8.9 GB** | **1×T4 / L4** | **67.0%** † | **74.1%** † | [openwebrl.github.io](https://openwebrl.github.io/) / paper | [HF](https://huggingface.co/OpenWebRL/OpenWebRL-4B) · [github.com/OpenWebRL/OpenWebRL](https://github.com/OpenWebRL/OpenWebRL) |
| **Fara1.5-9B** | **Yes** (MIT) | **18.8 GB** | **1×L4** (bf16) | **63.4%** | **86.6%** | MS HF / fara README | [HF](https://huggingface.co/microsoft/Fara1.5-9B) · [fara](https://github.com/microsoft/fara) |
| **Fara1.5-4B** | **Yes** (MIT) | **9.1 GB** | **1×T4–L4** | **57.3%** | **80.8%** | MS HF / fara README | [HF](https://huggingface.co/microsoft/Fara1.5-4B) · [fara](https://github.com/microsoft/fara) |
| **MolmoWeb-8B** | **Yes** (Apache-2.0) | **34.7 GB** | A100 / multi-GPU (or quant) | **35.3%** (pass@4 **60.5%**) | **78.2%** (pass@4 94.7%) | [allenai/MolmoWeb-8B](https://huggingface.co/allenai/MolmoWeb-8B) | [HF](https://huggingface.co/allenai/MolmoWeb-8B) · [github.com/allenai/MolmoWeb](https://github.com/allenai/MolmoWeb) |
| **Fara-7B** | **Yes** (MIT) | **16.6 GB** | 1×L4 / T4+quant | **34.1%** | **73.5%** | OpenWebRL / MolmoWeb comparison tables | [HF](https://huggingface.co/microsoft/Fara-7B) · [fara](https://github.com/microsoft/fara) |
| **UI-TARS-1.5-7B** | **Yes** (Apache-2.0) | **33.2 GB** | A100 / quant on 24GB | **31.3%** | **66.4%** | OpenWebRL / MolmoWeb tables (not ByteDance’s full-1.5 row) | [HF](https://huggingface.co/ByteDance-Seed/UI-TARS-1.5-7B) · [UI-TARS](https://github.com/bytedance/UI-TARS) |
| **MolmoWeb-4B** | **Yes** (Apache-2.0) | **19.4 GB** | 1×L4 | **31.3%** | **75.2%** | MolmoWeb / OpenWebRL tables | [HF](https://huggingface.co/allenai/MolmoWeb-4B) · [MolmoWeb](https://github.com/allenai/MolmoWeb) |
| **Gemini 3.6 Flash + Browser Use** (ours) | API | $ | Vertex | ~**34%** raw / ~**48%** audited | — | our full100 | this repo |

\* Closed full **UI-TARS-1.5** scores from ByteDance README — **not** the open 7B.  
† OpenWebRL’s main table uses a **30-step** cap; several baselines they cite use **100 steps**. Treat 67% as strong but **not apples-to-apples**.

Also on HF (same family, useful): `OpenWebRL/OpenWebRL-4B-SFT`, `OpenWebRL/OpenWebRL-8B`, `OpenWebRL/OpenWebRL-Judge-8B`, `osunlp/WebJudge-7B`.

---

## Per-model verification

### Fara1.5-4B / 9B / 27B — **confirmed open, usable**
- **Weights:** `microsoft/Fara1.5-{4,9,27}B`, ungated, MIT.
- **Code / harness:** https://github.com/microsoft/fara (vLLM serve path documented; Foundry hosting optional).
- **Scores:** OM2W 57.3 / 63.4 / 72.3; WV 80.8 / 86.6 / 89.3 — match HF cards + fara README (blog once lists 27B WV as 88.6; use **89.3** from HF/README table).
- **Host notes:** 4B card: bf16 needs “enough memory”; tested A6000/A100/H100/B200. Disk ~9 GB → **T4 16GB is plausible** with tight KV / lower concurrency. 9B ~19 GB disk → **L4**. 27B ~55 GB disk → multi-GPU, not one T4.
- **Ignore:** Foundry Labs marketing “27B clears 90% OM2W” — contradicts the published **72.3%**.

### OpenWebRL-4B — **confirmed open, usable** (best small OM2W claim)
- **Weights:** https://huggingface.co/OpenWebRL/OpenWebRL-4B (~8.9 GB, Qwen3-VL tags). No README on the model card yet; weights present and ungated.
- **Code:** https://github.com/OpenWebRL/OpenWebRL (Apache-2.0).
- **Scores:** OM2W **67.0%**, WV **74.1%**, DeepShop 64.0% (project site / arxiv 2606.02031).
- **Caveat:** reported at **max 30 steps** vs 100 for Fara-7B / MolmoWeb / UI-TARS-1.5-7B in their comparison table. Still the strongest *open ≤4B* OM2W claim; validate on Mini-2 ourselves.
- **Prior table error:** WV was “—” — corrected to **74.1%**.

### UI-TARS-2 — **code open, weights NOT public**
- Announcement + paper + demos only. HF has **UI-TARS-2B** (2B params), not version 2.
- Community still asking for weights: https://github.com/bytedance/UI-TARS/issues/213
- Details: `results/capability/UI_TARS_2_WEIGHTS.md`

### UI-TARS-1.5 (full) vs UI-TARS-1.5-7B
| | Full 1.5 | Open 1.5-7B |
|--|----------|-------------|
| OM2W | **75.8%** (README) | **~31.3%** (third-party tables) |
| WV | **84.8%** | **~66.4%** |
| Weights | gated email | https://huggingface.co/ByteDance-Seed/UI-TARS-1.5-7B (~33 GB) |
| Code | same OSS repos | same |

Do **not** put “UI-TARS-1.5 open” and the 75.8% number on the same row.

### MolmoWeb-4B / 8B — **confirmed open**
- HF + https://github.com/allenai/MolmoWeb + Native variants.
- OM2W pass@1 **31.3 / 35.3**; pass@4 **60.5%** (8B) is test-time compute, not single-rollout.
- **Prior table error:** “~12GB / ~24GB” understated; measured **19.4 / 34.7 GB** on HF.

### Fara-7B — **confirmed open** (predecessor)
- https://huggingface.co/microsoft/Fara-7B (~16.6 GB). OM2W ~34% — superseded by Fara1.5 for accuracy.

### Our Gemini 3.6 Flash + Browser Use
- Not an open CUA weight; harness baseline. full100 ≈34% raw / ≈48% audited. Mini-2 harness bakeoff: Browser Use beat SeeAct/WebVoyager on same model.

---

## Errors in the previous research table

1. **UI-TARS-2 listed as usable OSS model** — only code/demos; no downloadable version-2 checkpoint.
2. **OpenWebRL WV = —** — should be **74.1%**.
3. **Disk / GPU footprints** were rough; use measured HF sizes above (esp. MolmoWeb, Fara1.5-27B ~55GB not ~80GB weights).
4. **Comparing pass@1 vs pass@4 / 30-step vs 100-step** without footnotes inflated or muddied rankings.

---

## What to run on our T4 (16GB) first

| Priority | Model | Why |
|----------|-------|-----|
| **1** | **OpenWebRL-4B** | Highest open OM2W claim that fits T4; code+weights real |
| **2** | **Fara1.5-4B** | Clean MS stack (fara + vLLM); solid 57% OM2W; MIT |
| **3** | Fara1.5-9B | Needs L4 (or heavy quant on T4) |
| Skip for accuracy | MolmoWeb-*, UI-TARS-1.5-7B, Fara-7B | ~31–35% OM2W pass@1 |
| Unavailable | UI-TARS-2, full UI-TARS-1.5 | No public weights |

Judge cost option: `osunlp/WebJudge-7B` or `OpenWebRL/OpenWebRL-Judge-8B` instead of Gemini judge where possible.

---

## Quick link index

| Org | Models hub | Agent code |
|-----|------------|------------|
| Microsoft | https://huggingface.co/microsoft?search_models=Fara | https://github.com/microsoft/fara |
| OpenWebRL | https://huggingface.co/OpenWebRL | https://github.com/OpenWebRL/OpenWebRL |
| Ai2 | https://huggingface.co/allenai?search_models=MolmoWeb | https://github.com/allenai/MolmoWeb |
| ByteDance-Seed | https://huggingface.co/ByteDance-Seed?search_models=UI-TARS | https://github.com/bytedance/UI-TARS · desktop · Midscene |
