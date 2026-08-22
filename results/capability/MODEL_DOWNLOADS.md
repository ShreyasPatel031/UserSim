# Downloaded open CUA weights (local)

**Date:** 2026-08-22  
**Location:** `/workspace/data/models/` (gitignored under `data/`)

| Model | Path | Disk | HF |
|-------|------|------|-----|
| **Fara1.5-4B** | `/workspace/data/models/Fara1.5-4B` | ~8.5 GB | [microsoft/Fara1.5-4B](https://huggingface.co/microsoft/Fara1.5-4B) |
| **OpenWebRL-4B** | `/workspace/data/models/OpenWebRL-4B` | ~8.3 GB | [OpenWebRL/OpenWebRL-4B](https://huggingface.co/OpenWebRL/OpenWebRL-4B) |

## Serve on GPU (T4 / L4)

**Torch pin (T4 VM):** `torch==2.6.0+cu124` — `torch 2.13` breaks vLLM import (`duplicate template name` inductor bug).

```bash
source ~/usersim/.venv/bin/activate
pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124
pip install "vllm>=0.19.1"
```
vllm serve /workspace/data/models/Fara1.5-4B \
  --host 0.0.0.0 --port 8000 \
  --dtype bfloat16 --max-model-len 32768

# OpenWebRL — Qwen3-VL backbone; same vLLM pattern if vision supported
vllm serve /workspace/data/models/OpenWebRL-4B \
  --host 0.0.0.0 --port 8001 \
  --dtype bfloat16 --trust-remote-code
```

Copy `data/models/` to Colab or T4 VM (`~/usersim/models/`) if this agent disk is ephemeral.

## Not done yet

- No vLLM server running (this pod has no GPU)
- No Mini-2 eval wired to these endpoints
- T4 VM IAP was down last check — copy weights or re-download on GPU box
