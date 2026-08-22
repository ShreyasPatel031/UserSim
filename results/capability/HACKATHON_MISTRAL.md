# Mysterious hackathon — Mistral web agent

The point is the hack, not reproducing OpenWebRL’s 300 GPU-hour RL loop. Ship a demo where **Mistral browses the live web** on OM2W Mini-2, with a believable “we built this overnight” story.

> **Actually fine-tuning Mistral for computer use:** see **`MISTRAL_CUA_FINETUNE_PLAN.md`** — Ministral-3-3B (Apache 2.0, vision) + LoRA on the web subset of Aguvis Stage 2, ~$30–60 total. The API tracks below are the fallback / baseline.

## Three viable hacks (pick 1–2)

### 1. Pixtral sees, Browser Use acts (fastest demo)
- **Model:** `pixtral-large-2411` (vision) or `mistral-medium-2508` (agentic multimodal)
- **Harness:** Browser Use OSS — same stack that beat SeeAct/WebVoyager on Mini-2 with Gemini
- **Judge:** keep `gemini-2.5-flash` (cheap, already wired)
- **Benchmark:** Mini-2 only — Eventbrite + IGN (reachable from cloud IP)

```bash
# secrets/env
MISTRAL_API_KEY=...
MISTRAL_MODEL=pixtral-large-2411   # optional override

pip install browser-use==0.13.8
PYTHONPATH=src python -m capability.run_mistral_mini2
```

### 2. Overnight distillation (the mystery)
You already have **100+ Gemini Browser Use traces** under `results/capability/traces/bu_*`.

```bash
python scripts/hackathon/traces_to_mistral_sft.py
# → data/hackathon/mistral_sft.jsonl
```

Upload JSONL to Mistral fine-tuning (or Colab LoRA on **Mistral Large 3** open weights). Pitch: *“We taught Mistral to browse from teacher trajectories — no Orchard, no MM-GRPO.”*

### 3. Teacher ensemble (spicy slide)
- **Teacher:** Fara1.5-4B or OpenWebRL-4B on T4/Colab (vLLM)
- **Student:** Mistral API plans + Pixtral verifies screenshots
- Compare action traces on the same Mini-2 task — “open model vs Mistral hack”

## What NOT to do in 24h
- Full OpenWebRL online RL on live web
- Full FaraGen synthetic pipeline
- OM2W full100 on Akamai-blocked sites (tag BLOCKED, don’t burn API $)

## Models cheat sheet

| API id | Role | Notes |
|--------|------|-------|
| `pixtral-large-2411` | Vision + text | Default for Browser Use `use_vision=True` |
| `mistral-medium-2508` | Agentic multimodal | Docs: “optimized for agentic use cases” |
| `pixtral-12b-2409` | Cheaper vision | Good for iteration |
| Mistral Large 3 (HF) | Open weights | Self-host / LoRA on Colab if API budget tight |

## Colab + GCS
- Notebook: `notebooks/colab_cua_models.ipynb` — pull Fara/OpenWebRL from GCS, vLLM smoke
- Mistral eval can run from laptop/cloud agent with API key (no GPU needed for Track 1)

## Demo script (5 min)
1. Show Mini-2 task on Eventbrite
2. Run `run_mistral_mini2 --task-index 0`
3. Show trace + Gemini judge SUCCESS
4. Optional: reveal SFT JSONL line count from teacher traces
