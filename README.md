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

**CLI** — streams progress in the terminal and opens a browser **viewer** showing the exact
same UI as the web app (`http://<host>/?study=<id>`: live personas, trace, bbox screenshots, QA
report). If a UserSim server is already running on `--port` (default 8787), the CLI talks to it
directly and the viewer is that same running server. Otherwise it starts one itself, in-process:
```bash
.venv/bin/python mvp/cli.py \
  --url "https://www.cloud.com/" \
  --segment "Compliance officer at a global bank evaluating secure access and integration platforms"
```
Cheap smoke test: add `--agents 1 --max-steps 5`. No display to open a browser on (a sandbox,
CI, a coding agent)? Add `--no-viewer` — the viewer URL still prints, just isn't auto-opened.

## Running this for a user, as a coding agent

If you're an agent (not a human at a terminal) running this on someone's behalf — you have no
display, so `--no-viewer`'s auto-open is a no-op anyway, but the CLI still gives you everything
you need to show the user real progress via your own browser/screenshot tool:

1. Run the CLI with `--no-viewer` so it doesn't try (and fail silently) to pop a native browser:
   ```bash
   .venv/bin/python mvp/cli.py --url "<url>" --segment "<segment>" --no-viewer
   ```
   For a first smoke test before spending a full run, add `--agents 1 --max-steps 5`.
2. The first thing it prints is a `viewer: http://127.0.0.1:8787/?study=<id>` line — grab that
   URL immediately, before the study finishes.
3. Open that URL with your own browser tool and take a screenshot to show the user real
   progress (personas being generated, agents browsing live, bbox screenshots landing). The
   page polls itself, so re-navigating and re-screenshotting later shows fresh state — you don't
   need to resubmit anything.
4. The CLI process blocks until the study is done, then prints the QA report and the same
   viewer URL again. Take one final screenshot of the viewer at that point — it now shows the
   complete report — and paste it into the conversation as the result.
5. If the terminal output shows an agent "using snapshot fallback", the live browser-use run
   crashed (see "Verify it's actually working" below) — say so; don't present a fallback run as
   a real browser test.

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
