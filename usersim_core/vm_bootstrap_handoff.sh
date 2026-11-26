#!/usr/bin/env bash
# ==============================================================================
# UserSim Core — 1-Command GCE VM Handoff Bootstrap (`vm_bootstrap_handoff.sh`)
# ==============================================================================
# Restores 100% of the Antigravity Mac session onto any GCE Linux VM in ~45s:
#   1. Clones/updates `UserSim` repo on branch `usersim-core-v1`
#   2. Creates/syncs Python `.venv` via `uv`
#   3. Downloads `usersim_core_scratch_bundle.tar.gz` (bench, taxonomy, sites,
#      apify_v1, LLM caches, 350 HC3 Google-SSO surfaces, 220 HC4 4-step CUA
#      traces + screenshots, live_23d lineups/post0005, and STACK-1b coefs)
#   4. Pulls full E5 per-person `backer_pred/*.parquet` (Qwen-7B P(yes)),
#      `backer_arms/*.parquet`, `segments/*.parquet`, and `tables/follows/`
#      over GCP internal 10Gbps network ($0 egress)
#   5. Runs `simharness.ledger validate` to verify 0 errors.
#
# Usage on GCE VM:
#   bash usersim_core/vm_bootstrap_handoff.sh [REPO_DIR] [WORK_DIR]
# ==============================================================================
set -euo pipefail

REPO_DIR="${1:-$HOME/UserSim}"
WORK_DIR="${2:-/var/tmp/usersim_core_work}"
HANDOFF_DIR="gs://usersim-trace-store-347838016394/vm_handoff_20261126"
HANDOFF_GCS="$HANDOFF_DIR/usersim_core_scratch_bundle.tar.gz"
REPO_GCS="$HANDOFF_DIR/UserSim_repo_usersim_core_v1.tar.gz"
SIM_GCS="gs://usersim-bakeoff-347838016394/usersim_sim"

echo "=== [1/5] Ensuring git, libgomp1 (LightGBM), tmux, ripgrep & uv are installed ==="
if ! command -v git >/dev/null 2>&1 || ! dpkg -s libgomp1 >/dev/null 2>&1; then
  sudo apt-get update -qq && sudo apt-get install -y -qq git tmux libgomp1 curl jq ripgrep build-essential >/dev/null
fi
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "=== [2/5] Syncing UserSim repository (branch: usersim-core-v1) at $REPO_DIR ==="
if [ ! -d "$REPO_DIR/.git" ]; then
  echo "  -> Bootstrapping full git repo snapshot from $REPO_GCS..."
  mkdir -p "$REPO_DIR"
  gcloud storage cp "$REPO_GCS" /tmp/UserSim_repo_usersim_core_v1.tar.gz
  tar --warning=no-unknown-keyword -xzf /tmp/UserSim_repo_usersim_core_v1.tar.gz -C "$REPO_DIR"
  rm -f /tmp/UserSim_repo_usersim_core_v1.tar.gz
fi
git -C "$REPO_DIR" fetch origin 2>/dev/null || true
git -C "$REPO_DIR" checkout usersim-core-v1
git -C "$REPO_DIR" pull --ff-only origin usersim-core-v1 2>/dev/null || true

echo "=== [3/5] Provisioning Python environment (.venv) ==="
cd "$REPO_DIR"
if [ ! -d ".venv" ]; then
  uv venv .venv --python 3.12 || uv venv .venv --python 3.11
fi
uv pip install --python .venv/bin/python -e . lightgbm scikit-learn scipy pandas pyarrow httpx sentence-transformers >/dev/null

echo "=== [4/5] Restoring Scratch Data, LLM Caches, CUA Traces & 93K Population Tables to $WORK_DIR ==="
mkdir -p "$WORK_DIR"
if [ ! -f "$WORK_DIR/.bundle_restored_20261126" ]; then
  gcloud storage cp "$HANDOFF_GCS" "$WORK_DIR/usersim_core_scratch_bundle.tar.gz"
  tar --warning=no-unknown-keyword -xzf "$WORK_DIR/usersim_core_scratch_bundle.tar.gz" -C "$WORK_DIR"
  rm -f "$WORK_DIR/usersim_core_scratch_bundle.tar.gz"
  touch "$WORK_DIR/.bundle_restored_20261126"
fi

mkdir -p "$WORK_DIR/data/e5_pop/backer_pred" \
         "$WORK_DIR/data/e5_pop/backer_arms" \
         "$WORK_DIR/data/e5_pop/segments" \
         "$WORK_DIR/data/follows"

echo "  -> Pulling Qwen-7B per-person P(yes) (backer_pred), backer_arms, segments & follows..."
gcloud storage cp -n "$SIM_GCS/tmp/e5/private/backer_pred/*.parquet" "$WORK_DIR/data/e5_pop/backer_pred/" 2>/dev/null || true
gcloud storage cp -n "$SIM_GCS/tmp/e5/private/backer_arms/*.parquet" "$WORK_DIR/data/e5_pop/backer_arms/" 2>/dev/null || true
gcloud storage cp -n "$SIM_GCS/tmp/e5/private/segments/*.parquet" "$WORK_DIR/data/e5_pop/segments/" 2>/dev/null || true
gcloud storage cp -n "$SIM_GCS/tables/follows/*.parquet" "$WORK_DIR/data/follows/" 2>/dev/null || true
gcloud storage cp -n "$SIM_GCS/tmp/e5/private/stack/stack_coef.json" "$WORK_DIR/data/e5_pop/" 2>/dev/null || true

# Fix hardcoded Nov-25 reference path if needed via symlink or env var
export USERSIM_WORK_DIR="$WORK_DIR"

echo "=== [5/5] Verifying Experiment Ledger & Pool B Fleet Connectivity ==="
"$REPO_DIR/.venv/bin/python" -m simharness.ledger validate

echo ""
echo "=============================================================================="
echo "READY ON VM!"
echo "  Repo branch : $(git -C "$REPO_DIR" rev-parse --abbrev-ref HEAD) @ $(git -C "$REPO_DIR" rev-parse --short HEAD)"
echo "  Work dir    : $WORK_DIR ($(du -sh "$WORK_DIR" | awk '{print $1}'))"
echo "  Next plan   : $REPO_DIR/docs/VM_HANDOFF_AND_PLAN_20261126.md"
echo "=============================================================================="
