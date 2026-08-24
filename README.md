# UserSim — internal QA testing tool

Give it a target URL + a user profile, and it spins up parallel QA agents (Gemini 2.5 Flash,
driving real local Chromium browsers via [browser-use](https://github.com/browser-use/browser-use))
that run realistic test cases against the live site, then reports back issues found, what works,
and prioritized fixes. Two ways to run it: a web UI, or a terminal CLI.

**Full usage docs: [mvp/README.md](mvp/README.md).** This file is the from-scratch setup path.

## Branch

This tool lives on `cursor/cloud-agent-1787439924695-hwaz6`, not `main`. `main` only has the
older Mind2Web offline-eval scaffolding (see `CLOUD.md`) — it does not have `mvp/`.

```bash
git clone https://github.com/ShreyasPatel031/UserSim.git
cd UserSim
git checkout cursor/cloud-agent-1787439924695-hwaz6
```

## Setup (fresh clone → running server)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -r mvp/requirements.txt
.venv/bin/playwright install chromium
```

Auth is Vertex AI via `gcloud` — no API keys anywhere in this tool.

```bash
gcloud auth login                              # if not already logged in
gcloud config set project project-amer-scs-sandbox
```

Verify Vertex AI access before running anything real:

```bash
PYTHONPATH=src .venv/bin/python -c "from auth import vertex_credentials; c=vertex_credentials(); print('ok', bool(c.token))"
```
Expect `ok True`. Model/project/location are fixed in `src/config.py`
(`gemini-2.5-flash`, `project-amer-scs-sandbox`, `us-central1`) — change them there, not via env
vars, if you need a different target.

## Run it

**Web UI:**
```bash
PYTHONPATH=src .venv/bin/uvicorn mvp.server:app --port 8787
```
Open http://127.0.0.1:8787.

**CLI** (no server needed, streams progress + opens screenshots as they land):
```bash
PYTHONPATH=src .venv/bin/python mvp/cli.py \
  --url "https://www.cloud.com/" \
  --segment "Compliance officer at a global bank evaluating secure access and integration platforms"
```
Cheap smoke test: add `--agents 1 --max-steps 5`.

## Verify it's actually working

```bash
curl -s http://127.0.0.1:8787/health   # -> {"ok":true}
```
A real run writes to `mvp/runs/<study_id>/<agent_id>/screenshots/bbox_N.png` — numbered
clickable elements boxed on a real page. If a run silently falls back to `"mode":
"fallback_snapshot"` in `mvp/runs/<study_id>/<agent_id>/run.json` instead of `"mode": "browser"`,
the live browser-use agent crashed and hid the error — check the terminal/server log for a
traceback, don't trust the study looking "complete" as proof the browser actually ran.

## Repo layout

- `mvp/` — the QA tool (web UI + CLI). Start here.
- `src/` — Gemini/Vertex auth (`auth.py`, `config.py`) shared by everything, plus the older
  Mind2Web offline-eval code (`eval_*.py`, `live_predict.py`) and the `capability/` bakeoff
  harnesses (browser-use vs. native computer-use vs. SeeAct/WebVoyager) — unrelated to the QA
  tool, safe to ignore unless you're working on that eval.
- `CLOUD.md` — handoff notes for the eval work, not the QA tool.
