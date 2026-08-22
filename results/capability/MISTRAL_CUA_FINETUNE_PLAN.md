# Plan: fine-tune Mistral into a web computer-use agent

**Goal:** take an open Mistral vision model to Fara1.5-4B-class performance (~57% OM2W) using only open-source data, on a subset, for tens of dollars.

---

## First, the cost correction

The 300 GPU-hour figure quoted earlier was **OpenWebRL's online RL loop** (live browsers, rollouts, VLM reward judging). That is the expensive part and we are not doing it.

What we are doing is **SFT / LoRA on pre-collected trajectories**. Different order of magnitude:

| Stage | Compute | Cost |
|-------|---------|------|
| OpenWebRL online MM-GRPO | ~300 B200-hrs | thousands |
| Fara FaraGen synth generation | GPT-5.4 solver over ~145K trajs | thousands |
| **Our LoRA SFT on web subset** | **~12–35 GPU-hrs** | **~$25–60** |

Also worth separating: the ~100 traces in `results/capability/traces/` are **eval runs**, not training data. They are far too few to train on (and they are Gemini-flavored DOM actions, not vision-grounded). Training data comes from open datasets below — for free.

---

## Base model: Ministral 3 3B

Mistral 3 (Dec 2025) shipped small **multimodal** models under Apache 2.0. Verified on HF, all ungated:

| Repo | Size on disk | Precision | Use |
|------|--------------|-----------|-----|
| `mistralai/Ministral-3-3B-Base-2512` | 7.7 GB | BF16 | **train from this** |
| `mistralai/Ministral-3-3B-Instruct-2512` | 4.67 GB | FP8 | zero-shot baseline |
| `mistralai/Ministral-3-8B-Instruct-2512` | ~9 GB | FP8 | stretch goal |

Architecture: 3.4B language model + **0.4B Pixtral-style ViT** (frozen vision encoder, newly trained projection). This is almost exactly the Fara1.5-4B recipe shape (4B, vision-only perception), which makes the comparison fair and the target credible.

Train from the **BF16 Base** checkpoint — FP8 Instruct weights are awkward to LoRA against.

---

## Data: web-only subset of Aguvis Stage 2

`xlangai/aguvis-stage2` is 168 GB total, but it's split by source and **the web portion is small**. Verified sample counts:

| Subset | Samples | Images | Relevance |
|--------|---------|--------|-----------|
| `mind2web-l2` | **7,591** | 1.2 GB | Same distribution as OM2W — highest value |
| `guiact-web-single` | 67,396 | 1.25 GB | Single-step web grounding, cheap |
| `guiact-web-multi-l2` | 16,704 | 10.2 GB | Multi-step web |
| `miniwob-l2` | 9,826 | 0.06 GB | Synthetic, tiny, good for warmup |

**Download ≈ 2.5 GB** if we take `mind2web` + `guiact-web-single` + `miniwob`. Not 168 GB.

The format is already what we need — screenshot, thought, grounded action:

```
system: You are a GUI agent... you have access to browser.select_option, pyautogui...
human:  <image> Instruction: Book a first class vacation... Previous actions: None
gpt:    Thought: To book a vacation package, I need to switch to 'Vacation packages'...
        Action: Click on the 'Vacation packages' tab...
gpt:    pyautogui.click(x=0.2315, y=0.7736)
```

Normalized coordinates, explicit reasoning, action history in the prompt. No relabeling needed.

**Optional grounding warmup:** `xlangai/aguvis-stage1` has `webui350k.zip` (34 GB) and `seeclick` (128 GB) — skip both. If click accuracy is the bottleneck, add `ui_refexp.zip` (0.42 GB) only.

Licensing: Aguvis, AgentNet (MIT), OS-Atlas, Mind2Web are all open. Ministral 3 is Apache 2.0. Nothing here is gated.

---

## Proposed training mix

Target **~25K samples**, weighted toward our benchmark:

| Source | Take | Why |
|--------|------|-----|
| `mind2web-l2` | all 7,591 | Directly on-distribution for OM2W |
| `guiact-web-single` | 12,000 sampled | Click grounding volume |
| `guiact-web-multi-l2` | 4,000 sampled | Multi-step planning |
| `miniwob-l2` | 2,000 sampled | Cheap regularizer |

LoRA config: rank 32–64 on attention + MLP projections, **vision encoder frozen**, train the multimodal projection layer. Images capped at 1024px long edge to control vision token count. 2 epochs.

---

## Hardware

**Important:** the T4 in `oprior-1787208583-uscentral1a` is Turing (SM75) — **no bf16, no FP8, no flash-attention**. It also currently has a broken vLLM install (CUDA 13 wheels vs driver mismatch).

| Option | VRAM | Feasibility |
|--------|------|-------------|
| T4 16GB (current) | 16 | QLoRA 4-bit + fp16 + 512px images only. Slow; use for a 3–5K smoke subset |
| **L4 24GB** (GCP `g2-standard-8`) | 24 | **Recommended.** Ada, bf16 native, ~$0.7/hr |
| A100 40GB | 40 | Fastest, ~$2–3/hr |
| Colab Pro A100/L4 | — | Fine if session limits are tolerable |

Recommend requesting an **L4 quota in us-central1** rather than fighting the T4.

### Budget

| Phase | GPU-hrs | Cost |
|-------|---------|------|
| Data prep + tokenization | CPU only | ~$0 |
| Smoke run (500 samples, 1 epoch) | 1–2 | ~$2 |
| Full LoRA (25K × 2 epochs, L4) | 25–35 | ~$20–25 |
| Same on A100 | 10–14 | ~$30–40 |
| Eval (Mini-2 + OM2W subset, judge) | Gemini 2.5 Flash | ~$5 |
| **Total** | | **~$30–60** |

---

## The harness problem (most important design decision)

Aguvis actions are **normalized pixel coordinates** (`pyautogui.click(x=0.23, y=0.77)`). Browser Use expects **DOM element indices**. These are incompatible action spaces.

**Decision: build a small coordinate-based harness**, not adapt Browser Use.

- Playwright, screenshot → model → `mouse.click(x * W, y * H)`
- ~150–200 lines: screenshot loop, action parser, history buffer, done detection
- This is exactly the protocol Fara1.5 and OpenWebRL use, so **our number is directly comparable to Fara's 57.3%**
- Reuse existing `capability.judge` (WebJudge on gemini-2.5-flash) unchanged

Adapting Browser Use instead would require regenerating all training data in DOM-index space — far more work and no longer comparable to published numbers.

Serving: vLLM with the LoRA adapter, OpenAI-compatible endpoint. The existing `mistral_browser_use_runner.py` already accepts a `base_url`, so it can point at localhost for API-shaped comparisons.

---

## Phases

**Phase 1 — Baseline (no training).** Download Ministral-3-3B-Instruct, serve on vLLM, build the coordinate harness, run Mini-2 (Eventbrite + IGN). Expect near-zero success — a general VLM has no grounded click prior. *This zero is the demo's before-picture.*

**Phase 2 — Data.** Pull the 2.5 GB web subset, convert Aguvis conversations to Ministral chat format, hold out 200 samples. Verify coordinate convention end-to-end by replaying a known action.

**Phase 3 — Smoke train.** 500 samples, 1 epoch, confirm loss decreases and the model emits parseable `pyautogui.click(x=..., y=...)`. Measure seconds/sample here and extrapolate the real budget before committing spend.

**Phase 4 — Full LoRA.** 25K samples, 2 epochs on L4/A100. Checkpoint each epoch.

**Phase 5 — Eval.** Mini-2 first, then a 20–30 task OM2W subset on non-blocked sites. Compare against Fara1.5-4B and OpenWebRL-4B (weights already on GCS and the VM) under the identical harness and judge.

Gate between phases: if Phase 3 doesn't produce parseable grounded actions, the format conversion is wrong — fix that before spending on Phase 4.

---

## Honest expectations

Fara1.5-4B's 57.3% came from ~145K verified synthetic trajectories built by a GPT-5.4 solver. We are using ~25K public trajectories on a 3B model. **Realistic landing zone: 20–35% OM2W** — well short of Fara, but a large jump from an untrained baseline near 0%.

That is still a strong result to show: *an Apache-2.0 3B Mistral, fine-tuned on open data for ~$40, browsing the live web.* The credible claim is the delta and the cost, not beating Microsoft.

**Main risks**

1. **vLLM support for Ministral 3 vision.** Verify multimodal inference works *before* training. If unsupported, fall back to a HuggingFace `transformers` serving loop (slower, acceptable at this scale).
2. **Coordinate convention mismatch.** Aguvis normalizes to [0,1]; OS-Atlas scales by 1000. Getting this wrong silently destroys click accuracy — validate in Phase 2.
3. **Frozen ViT ceiling.** Ministral 3's vision encoder is inherited frozen from Mistral Small 3.1 and was not trained for dense UI grounding. If click accuracy plateaus, unfreezing the projection plus the last few ViT blocks is the lever.
4. **T4 dead end.** Don't sink time into the current VM; get L4 quota.

---

## Not doing

- Online RL / MM-GRPO (this is the expensive part)
- FaraGen-style synthetic generation with a frontier solver
- Full 168 GB Aguvis or 128 GB SeeClick pretraining
- Full OM2W on Akamai-blocked sites — tag `BLOCKED`, don't burn budget
