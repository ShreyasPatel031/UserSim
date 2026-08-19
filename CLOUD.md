# Cloud handoff — UserSim v0.6

Local gcloud will not exist on the cloud VM. Auth is the Searce user JSON.

```
secrets/vertex_adc.json          # Vertex / Gemini 2.5 Flash
secrets/huggingface_token        # HF downloads
secrets/env                      # GCP_PROJECT, HF_TOKEN, …
data/mind2web_tasks.json         # 100 human traces (no HTML); first 40 = v0 eval
```

Load env, then verify Vertex before spending:

```
set -a && source secrets/env && set +a
PYTHONPATH=src .venv/bin/python -c "from auth import vertex_credentials; c=vertex_credentials(); print('ok', bool(c.token))"
```

Project: `project-amer-scs-sandbox`. Model: `gemini-2.5-flash`. Account: `shreyas.patel@searce.com`.
Keep spend in the same band as v0.5 (~$0.30–$1 unless told otherwise).

## What is already done

- v0: next-action prediction, history helps (32% → 50% element acc), 40 traj / 250 steps.
- v0.1: lift is task-state reconstruction, not personalization.
- v0.5: teacher-forced STOP/CONTINUE. **Judged** complete endpoints only (27 traj):
  agent terminal-continue **11% (3/27)** vs human-sim **0% (0/27)**.
  Naive last-row=STOP was 20% vs 2.5% — Tesla hover-submit was a label error.
  Both still stop early along the human path (0.74× / 0.62×).
  Files: `results/summary_v05_judged.json`, `results/endpoint_audit.json`.

Do not recruit paid testers yet. Do not stay teacher-forced.

## v0.6 — free-run on live public sites

Question: are UserSim traces more human-like than a standard completion agent when both act on the **live** website?

Mind2Web was collected on real public sites. The live site today may differ from 2022–2023 (UI, inventory, login). That drift is expected; Online-Mind2Web / Mind2Web-Live exist for that reason.

### Data

1. **Human path (needed for similarity):** original Mind2Web traces in `data/mind2web_tasks.json` (`action_reprs`). Screen ~50 tasks whose site/task still works without login.
2. **Live task set (needed for success on current web):** HuggingFace `osunlp/Online-Mind2Web` — 300 tasks / 136 sites, `website`, `task_description`, `reference_length`. Rewritten for solvability; **does not include the original click-by-click human demo**. Use it for success + length vs reference_length. Join back to original Mind2Web by website+task text when you want A→B→C→D comparison.

Start small: **8–12 live tasks** that open without login, then scale toward 50 if spend and breakage allow.

### Conditions (same page, different system prompt)

For each task, open the live URL in a real browser (Playwright). Let the site produce the next state after every action. Do not teacher-force the human path.

1. **Agent:** complete the task; keep going if more interaction could help.
2. **UserSim:** behave like a normal person on a public site; stop when a person would stop; do not optimize for completion.

Reuse `src/live_predict.py` as the action head. Add STOP. Cap steps (e.g. 2× human length or 20). Screenshot + numbered DOM elements.

### Metrics (generated traj vs human demo)

- task success (manual or WebJudge-style; say which)
- number of actions
- extra actions beyond human
- retries / repeated actions
- backtracking (URL or host return)
- action-type distribution (CLICK/TYPE/SELECT)
- stopping point vs human / vs success
- semantic similarity to human path (not exact element match)
- unnecessary exploration

Secondary: Online-Mind2Web success vs `reference_length` when there is no original demo.

### Caveats to keep in the writeup

- Live ≠ 2022 DOM. Path mismatch is not automatically a model failure.
- Not abandonment; not paid-user validation.
- Teacher-forced v0.5 numbers are not free-running length.
- No SFT checkpoint in this repo.

### Suggested first cloud commands

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/pip install playwright
.venv/bin/playwright install chromium
set -a && source secrets/env && set +a
```

Then implement a Playwright loop around `live_predict.py`, screen tasks, run agent vs UserSim on the same 8–12 URLs, write `results/summary_v06.json`.
