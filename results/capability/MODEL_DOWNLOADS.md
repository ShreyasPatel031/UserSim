# Downloaded open CUA weights (local)

**Date:** 2026-08-22  
**Location:** `/workspace/data/models/` (gitignored under `data/`)

| Model | Path | Disk | HF |
|-------|------|------|-----|
| **Fara1.5-4B** | `/workspace/data/models/Fara1.5-4B` | ~8.5 GB | [microsoft/Fara1.5-4B](https://huggingface.co/microsoft/Fara1.5-4B) |
| **OpenWebRL-4B** | `/workspace/data/models/OpenWebRL-4B` | ~8.3 GB | [OpenWebRL/OpenWebRL-4B](https://huggingface.co/OpenWebRL/OpenWebRL-4B) |

## On T4 VM (`~/usersim/models/`)

Copied from GCS 2026-08-22:

```bash
gsutil -m cp -r gs://ai-studio-bucket-347838016394-us-east1/usersim-models/Fara1.5-4B ~/usersim/models/
gsutil -m cp -r gs://ai-studio-bucket-347838016394-us-east1/usersim-models/OpenWebRL-4B ~/usersim/models/
```

## Serve on GPU (T4 / L4)

### Verified: transformers smoke (T4)

```bash
source ~/usersim/.venv/bin/activate
pip install torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 \
  --index-url https://download.pytorch.org/whl/cu124
pip install "transformers>=5.2" accelerate pillow
python ~/usersim/scripts/vm/smoke_transformers.py
# → replies "OK"
```

### vLLM (blocked on this VM for now)

- `vllm==0.19.1` imports but does **not** register Fara1.5-4B as multimodal.
- `vllm>=0.22` + `torch 2.13` hits torch inductor `duplicate template name` at import.
- Use **transformers** for T4 inference smoke; revisit vLLM when stack is pinned.

```bash
# Target (once vLLM supports Fara on T4):
vllm serve ~/usersim/models/Fara1.5-4B \
  --host 0.0.0.0 --port 8000 \
  --dtype bfloat16 --max-model-len 16384 \
  --limit-mm-per-prompt image=5 --trust-remote-code --enforce-eager
```

Colab: `notebooks/colab_cua_models.ipynb`

## Not done yet

- Wire Browser Use / Mini-2 to local model endpoint
- OpenWebRL smoke on GPU
- Stable vLLM serve on T4
