# Run locally — copy/paste runbook

Everything from the cloud agent is on GitHub. **You** open it on your machine; the cloud VM cannot do that for you.

## 1. Clone + branch (fast — ~3 MB)

**Cancel a slow full clone** (Ctrl+C) and use shallow clone instead:

```bash
git clone --depth 1 --branch cursor/capability-bakeoff-781d \
  https://github.com/ShreyasPatel031/UserSim.git
cd UserSim
```

Or if you already cloned:

```bash
git fetch origin cursor/capability-bakeoff-781d
git checkout cursor/capability-bakeoff-781d
git pull
```

## 2. Bootstrap (venv, deps, Playwright)

```bash
chmod +x scripts/local/bootstrap.sh
./scripts/local/bootstrap.sh --pull-model   # --pull-model needs gcloud/gsutil + ~7 GiB disk
```

Without `--pull-model` if you already have weights or want to pull later:

```bash
gsutil -m cp -r \
  gs://ai-studio-bucket-347838016394-us-east1/usersim-models/Ministral3-3B-CUA-web \
  ./data/models/
```

## 3. Secrets (required for Gemini judge / Vertex)

```bash
mkdir -p secrets
cp scripts/local/env.example secrets/env
# Edit secrets/env — set HF_TOKEN, etc.
# Copy your Vertex JSON → secrets/vertex_adc.json
```

Load env in every shell:

```bash
set -a && source secrets/env && set +a
```

Verify Vertex:

```bash
PYTHONPATH=src .venv/bin/python -c "from auth import vertex_credentials; print('ok', bool(vertex_credentials().token))"
```

## 4. Cursor: get a **local worktree** (enables Move to Local)

This is the step crowd-sim Mapper had and UserSim did not.

1. **File → Open Folder** → the `UserSim` directory you just cloned
2. Switch to **Agents Window** layout (not Editor-only chat)
3. **Start a new local agent** in that folder — any one-line task is enough
4. In the sidebar, right-click the cloud agent  
   `UserSim v0 experiment design (fork)` → **Move to → Local**

That pulls the branch and **keeps full chat history**. Must be the **same machine** where you opened the repo.

If Move to Local still missing: you’re on a different laptop than your local worktree, or no local agent is running — start step 3 again.

## 5. Run Ministral CUA eval locally (needs NVIDIA GPU)

Image size must be **1008×784** (training resolution). Eval needs **384** `max_new_tokens`.

```bash
set -a && source secrets/env && set +a
PYTHONPATH=src .venv/bin/python scripts/train/eval_ministral3_cua.py \
  --model data/models/Ministral3-3B-CUA-web \
  --n 25 \
  --max-new-tokens 384
```

Expected (from cloud run): ~100% parse, ~48% click within 5% on holdout.

## 6. Other local commands

**Mistral API mini-2 eval** (needs `MISTRAL_API_KEY` in `secrets/env`):

```bash
PYTHONPATH=src .venv/bin/python -m capability.run_mistral_mini2
```

**Browser Use + Gemini judge** (capability harness):

```bash
PYTHONPATH=src .venv/bin/python -m capability.harnesses.run_browser_use_mini2
```

## What’s on this branch

| Path | Purpose |
|---|---|
| `scripts/train/train_ministral3_cua.py` | SFT trainer |
| `scripts/train/eval_ministral3_cua.py` | Proper eval (384 tokens) |
| `src/capability/mistral_*` | Mistral API runners |
| `results/capability/ministral3_cua_results.json` | Summary metrics |
| `results/capability/MISTRAL_CUA_FINETUNE_PLAN.md` | Phase 5 = OM2W coordinate harness |

## Cloud agent URL (if you stay in cloud)

https://cursor.com/agents/bc-dcf38da3-54a3-4872-852e-506b5127fc07

Branch: `cursor/capability-bakeoff-781d`
