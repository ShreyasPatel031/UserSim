# Local checkout — current branch

All cloud-agent work is on:

```
branch: cursor/capability-bakeoff-781d
repo:   https://github.com/ShreyasPatel031/UserSim
```

```bash
git clone https://github.com/ShreyasPatel031/UserSim.git
cd UserSim
git fetch origin cursor/capability-bakeoff-781d
git checkout cursor/capability-bakeoff-781d
```

Open this folder in Cursor (`File → Open Folder`) to work locally.

## What’s on this branch

- Capability bakeoff harness (Browser Use + Gemini 2.5 Flash judge)
- Mistral hackathon runners (`src/capability/mistral_*`)
- Ministral-3-3B web CUA SFT scripts (`scripts/train/`)
- Docs: `OVERNIGHT_RUN.md`, `MISTRAL_CUA_FINETUNE_PLAN.md`, `ministral3_cua_results.json`

## Pull the fine-tuned model (not in git)

```bash
gsutil -m cp -r gs://ai-studio-bucket-347838016394-us-east1/usersim-models/Ministral3-3B-CUA-web ./data/models/
```

## Cloud agent chat

This thread does **not** move to local automatically. Use git for code; start a new local agent chat on this branch for local edits.
