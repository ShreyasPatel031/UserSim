#!/usr/bin/env bash
# Set up the real upstream SeeAct in an isolated venv.
#
# SeeAct pins openai==1.24.0 / litellm==1.35.32, which conflict with browser-use
# in the main venv. Isolating it is the whole point: no shared site-packages,
# so neither harness constrains the other.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
VENDOR="$ROOT/vendor/SeeAct"
VENV="$ROOT/.venv-seeact"

if [ ! -d "$VENDOR" ]; then
  mkdir -p "$ROOT/vendor"
  git clone --depth 1 https://github.com/OSU-NLP-Group/SeeAct.git "$VENDOR"
fi

if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
fi

"$VENV/bin/pip" install --upgrade pip
# Modern litellm: needed for vertex_ai/gemini-3.x. SeeAct's own pin predates it.
"$VENV/bin/pip" install \
  "litellm>=1.60" google-auth "playwright==1.62.0" \
  toml backoff python-dotenv lxml beautifulsoup4 aioconsole jsonlines
# --no-deps so SeeAct's stale pins don't override the versions above.
"$VENV/bin/pip" install --no-deps -e "$VENDOR/seeact_package"

"$VENV/bin/python" -m playwright install chromium || true

echo "SeeAct venv ready: $VENV"
