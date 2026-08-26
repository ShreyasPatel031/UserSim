#!/usr/bin/env bash
# One-shot local setup for UserSim capability work.
# Usage: ./scripts/local/bootstrap.sh [--pull-model]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PULL_MODEL=0
for arg in "$@"; do
  case "$arg" in
    --pull-model) PULL_MODEL=1 ;;
    -h|--help)
      echo "Usage: $0 [--pull-model]"
      echo "  --pull-model  gsutil copy Ministral3-3B-CUA-web (~7 GiB) into data/models/"
      exit 0
      ;;
  esac
done

echo "==> Python venv"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -U pip wheel

echo "==> Base deps"
pip install -r requirements.txt
pip install -r requirements-local-gpu.txt

echo "==> Playwright Chromium"
pip install playwright
playwright install chromium

echo "==> secrets/env"
mkdir -p secrets
if [[ ! -f secrets/env ]]; then
  cp scripts/local/env.example secrets/env
  echo "    Created secrets/env from template — edit before running Vertex/Gemini/Mistral."
else
  echo "    secrets/env already exists (not overwritten)."
fi

if [[ ! -f secrets/vertex_adc.json ]]; then
  echo "    WARNING: secrets/vertex_adc.json missing — copy your Vertex service-account JSON here."
fi

echo "==> data/models"
mkdir -p data/models

MODEL_DIR="data/models/Ministral3-3B-CUA-web"
GCS_URI="gs://ai-studio-bucket-347838016394-us-east1/usersim-models/Ministral3-3B-CUA-web"

if [[ "$PULL_MODEL" -eq 1 ]]; then
  if [[ -f "$MODEL_DIR/model.safetensors" || -f "$MODEL_DIR/model-00001-of-00002.safetensors" ]]; then
    echo "    Model already present under $MODEL_DIR"
  elif command -v gsutil >/dev/null 2>&1; then
    echo "    Pulling $GCS_URI (~7 GiB)..."
    gsutil -m cp -r "$GCS_URI" "$MODEL_DIR"
  else
    echo "    gsutil not found. Install Google Cloud SDK, then:"
    echo "    gsutil -m cp -r $GCS_URI $MODEL_DIR"
    exit 1
  fi
else
  echo "    Skip model download (pass --pull-model to fetch from GCS)."
fi

echo ""
echo "==> Done. Next:"
echo "  1. Edit secrets/env and add secrets/vertex_adc.json"
echo "  2. Open this folder in Cursor: File → Open Folder → $ROOT"
echo "  3. Agents Window → start a local agent (any prompt)"
echo "  4. Right-click cloud agent → Move to → Local (keeps chat history)"
echo ""
echo "  Quick verify (needs CUDA):"
echo "    set -a && source secrets/env && set +a"
echo "    PYTHONPATH=src .venv/bin/python scripts/train/eval_ministral3_cua.py \\"
echo "      --model data/models/Ministral3-3B-CUA-web --n 5"
