# UserSim MCP — handover

Branch: `claude/clever-goodall-1r9iqq` (based on `main` @ 3d69a76). Plan: `docs/plans/usersim_mcp.md`.

## 1. What exists

A coding agent **is** the simulated user. UserSim does not name a model: if the human asked for one, use that, otherwise use the model already running. UserSim runs the browser on
**our Browserbase account**, executes each action on the real page, records an ordinary Study,
judges the outcome independently, and returns the report over MCP. The user provides only a public URL.

| File | What |
|---|---|
| `mvp/sim_mcp/server.py` | MCP endpoint at `/mcp` (streamable HTTP, stateless, JSON). Tools: `usersim_start_session`, `usersim_observe`, `usersim_act`, `usersim_finish`, `usersim_get_report`. Prompt: `usersim_simulate_user`. Server `instructions` describe the flow (approve persona+task → start → open `watch_url` → run the user as a subagent on whatever model the caller is using → report). |
| `mvp/sim_mcp/sessions.py` | One Browserbase session per simulated user (`capability.browserbase_client.create_session` + Playwright `connect_over_cdp`), 1280×800 viewport. URL guard (public only), same-site `navigate`, vision actions (`click/double_click/right_click/hover/type/key/scroll/back/wait/navigate`), recorder → `StudyState.live_sessions["t1__p1__product"]`, idle/budget reaper. |
| `mvp/sim_mcp/report.py` | Judge (`e2e2_gates.judge_goal_screenshot`, Vertex Gemini); judge error ⇒ `unverified`, never a pass. Proof checks (e2e2 gate functions). Report JSON + markdown. |
| `mvp/version.py` | `engine_version` (git SHA, or `USERSIM_ENGINE_VERSION`) + `config_hash` (MVP_*/model env). On `/health`, every study, every report. |
| `mvp/study.py` | `StudyState` gained `driver`, `engine_version`, `config_hash` (also in `study_to_dict`). |
| `mvp/server.py` | mounts `/mcp` (disable with `MVP_MCP=0`); `/health` returns the version stamp. |
| `mvp/static/app.js` | `/?study=<id>` watches any study on the same live stage a website Run shows. That is the MCP `watch_url`. |
| `mvp/test_sim_mcp.py` | offline unit tests (10). |
| `mvp/e2e_mcp.py` | live e2e: scripted MCP client (no LLM) + Chromium check that `watch_url` mounts the live Browserbase iframe + `proof.pass`. |
| `requirements-vercel.txt` | + `mcp>=1.26.0`, `pillow>=10.0`, `google-genai>=1.0`. |

The MCP path does **not** use the browser-use library. browser-use stays in the repo only for the
website's old fallback agent / GCP fleet path (to be retired in the consolidation phase).

### Proof checks (every MCP run, in the report)

`opened_on_product`, `real_action` (click/type/scroll), `screenshots_real` (PNG, >2 KB, not blank),
`beyond_first_screen`, `live_view_offered`, `judge_ran`, `not_degraded`. Report headline says
"unverified" if any fail.

### Server limits (no auth, same as the website)

| Env | Default |
|---|---|
| `MVP_MCP_MAX_STEPS` | 40 |
| `MVP_MCP_BUDGET_S` | 900 |
| `MVP_MCP_IDLE_S` | 300 (session closed + study marked abandoned) |
| `MVP_MCP_MAX_SESSIONS` | 5 open sessions server-wide |
| `MVP_MCP_MAX_PER_CLIENT` | 2 per client IP (`X-Forwarded-For`) |
| `MVP_PUBLIC_BASE_URL` | base for `watch_url` / report links (default `https://usersim.vercel.app`) |

## 2. What was tested (in a cloud container, real Browserbase + Vertex)

- `PYTHONPATH=src:. pytest mvp` → 338 passed, 3 skipped. One test deselected because it already
  fails on `main`: `test_e2e2_gates.py::PageOpenedTests::test_strength_and_weakness_cite_step_ax_and_the_final_screenshot`.
- `python -m mvp.e2e_mcp --base http://127.0.0.1:8787` → pass: 7/7 proof checks, judge "goal reached",
  `watch_url` mounted the live iframe; localhost URL, off-site navigate and act-after-finish all refused.
- Real Claude Code on Haiku (`claude -p … --model haiku --mcp-config …`) on books.toscrape.com:
  home → Travel → "It's Only the Himalayas" (£45.17), finish → judge "goal reached", proof PASS.
- A deliberately wrong click was judged "goal NOT reached" (judge doesn't follow the driver's claim).

- 2026-10-06, local server on this branch, Composer (`composer-2.5`) as the driver, no model named by the server: books.toscrape.com, persona a retired teacher, task "find a travel book and open its page to see the price." 19 `usersim_act` calls. Book: It's Only the Himalayas, £45.17. Judge `goal_reached: true`, `proof.pass: true`. Session `03054811024148249caae50cd0ca5ee5`, study `9255c41e-ee78-4152-ba27-3907ef1b1360`. Start response had no `driver_model`. An earlier same-day smoke test on example.com finished with 0 actions and correctly failed proof (`real_action`, `beyond_first_screen`).

**Not tested:** `usersim_start_study` with parallel cells (persona × task × site) driven by real subagents; `usersim_finish_study` when some cells are skipped; the deployed VM / `usersim.vercel.app` proxy; a non-toy product.

## 2b. What the next agent should test

Checkout `claude/clever-goodall-1r9iqq` after this push. Do not commit `secrets/` or `MATRIX_RESULTS.md`. Report/insight edits in the same working tree (buyer grouping by pick, tie matchups) are **not** in this push.

1. `PYTHONPATH=src:. .venv/bin/pytest mvp/test_sim_mcp.py -q` — includes `MatrixStudyTests` (cells, favors, one-start, bad input, study report).
2. MCP `initialize` instructions must not name a model. `usersim_start_session` must not return `driver_model`. `mvp/e2e_mcp.py` asserts the second.
3. `PYTHONPATH=src:. .venv/bin/python -m mvp.e2e_mcp --base http://127.0.0.1:8787` — scripted client, real Browserbase. Needs the env in section 3. Expect proof pass and goal reached on the travel-book script.
4. One non-scripted session on a model other than Haiku (Composer already passed once; a second model, or a re-run, is the point). Persona and task must be approved by the human first. The agent must click, not finish on the first screenshot.
5. One small matrix: `usersim_start_study` with 2 personas × 1 task × the product and 1 competitor (4 cells). Drive each cell with `usersim_start_session(study_id, cell_id)` in parallel, up to `max_parallel`. When the last cell finishes, `usersim_get_report` should be the website study report. If you skip a cell, call `usersim_finish_study` and confirm the skipped cell is marked skipped.
6. After deploy only: `python -m mvp.e2e_mcp --base https://usersim.vercel.app`.

## 3. Run it locally

```bash
git checkout claude/clever-goodall-1r9iqq
python -m venv .venv && .venv/bin/pip install -r requirements-vercel.txt "uvicorn[standard]" pytest
# credentials: BROWSERBASE_API_KEY, BROWSERBASE_PROJECT_ID, GOOGLE_APPLICATION_CREDENTIALS (Vertex SA json),
# GCP_PROJECT=project-amer-scs-sandbox, VERTEX_LOCATION=us-central1   (e.g. `set -a; source secrets/env; set +a`)

PYTHONPATH=src:. MVP_WARM_STUDY_LIST=0 MVP_RECOVER_DELAY_S=99999 MVP_BB_OWNER=testfix \
  USE_BROWSERBASE=1 MVP_PUBLIC_BASE_URL=http://127.0.0.1:8787 \
  .venv/bin/uvicorn mvp.server:app --port 8787

curl -s 127.0.0.1:8787/health          # {"ok":true,"engine_version":"…","config_hash":"…"}
```

Watch progress in real time: open the `watch_url` from `usersim_start_session`
(`http://127.0.0.1:8787/?study=<id>`) — same stage as the website, with the Browserbase live browser.
The step screenshots are at `mvp/runs/<study_id>/t1__p1__product/screenshots/step_N.png`.

Tests:

```bash
PYTHONPATH=src:. .venv/bin/pytest mvp/test_sim_mcp.py -q
PYTHONPATH=src:. .venv/bin/python -m mvp.e2e_mcp --base http://127.0.0.1:8787
# if the Playwright pip version has no matching local browser: PLAYWRIGHT_CHROMIUM_PATH=/path/to/chrome
```

Use it from Claude Code:

```bash
claude mcp add --transport http usersim http://127.0.0.1:8787/mcp      # local
# claude mcp add --transport http usersim https://usersim.vercel.app/mcp  # after deploy
```

Then: *"Use UserSim to test https://<public or preview URL> — a new user trying to <goal>."*
The caller drafts persona + task, asks you to approve, starts the session, opens the watch URL, runs the
simulated user as a subagent on whatever model it is already using (or the model you named), and prints the report.

Note: the browser runs in Browserbase's cloud, so the product URL must be public (preview deploys fine;
`localhost` is rejected).

## 4. Deploy (not done — no VM access from the cloud session)

`usersim.vercel.app` is a Vercel proxy (`deploy/vercel-proxy/vercel.json`) to the GCP VM
`usersim-grokbot-web` (35.202.98.224, project `project-amer-scs-sandbox`) running `mvp.server:app`.
Nothing in the repo provisions that VM; its env lives in `/workspace/usersim-env.sh` on the box.

1. On the VM: fetch this branch (or merge into the branch the VM runs), `pip install -r requirements-vercel.txt`, restart uvicorn.
2. `curl -s https://usersim.vercel.app/health` → must show `engine_version` = the deployed SHA.
3. `python -m mvp.e2e_mcp --base https://usersim.vercel.app` → must pass (checks the proxy too: start takes 5–20 s).
4. If uvicorn runs with >1 worker, MCP sessions (in memory) break — run 1 worker or add sticky routing.

## 5. Known issues / gotchas

- Container-only: `GCS_PREFIX` there was not a `gs://` URI, so screenshot uploads to GCS failed (local copies served fine). Check prod's `MVP_GCS_PREFIX` uploads after deploy.
- No auth on `/mcp` (by decision). Limits above are the only abuse guard; each session uses one of our Browserbase seats (shared with website studies, 25 concurrent).
- `navigate` is same-site only, but clicked links may leave the site (intended: real user behaviour, OAuth).
- MCP sessions live in process memory; a server restart orphans them (Browserbase times them out; the study stays "running" until the existing interrupted-study recovery marks it).
- Friction list in the report is a keyword pass over the driver's thoughts — placeholder until the behaviour-science work.
- FastAPI `on_event` deprecation warnings (pre-existing pattern; MCP startup uses it too).

## 6. Next steps (from the plan)

1. Deploy + verify (section 4). Add a checked-in VM deploy script pinned to a tag (version drift).
2. Perception modes `a11y` and `marks` behind the same action schema; tiers low/medium/high.
3. Matrix studies are in the server (`usersim_start_study` / `usersim_finish_study`) but not yet driven end to end by parallel subagents. Product sign-in is still open.
4. Consolidation: website's Gemini a11y agent onto the same core as the MCP path; retire the browser-use GCP fleet path; single engine config; prompts out of inline strings.
5. Behaviour science (`BehaviorPolicy`): persona fidelity, when real users quit — separate track.

## 7. Decisions log (from the planning chat)

- Users bring only their coding agent + a public URL. No tokens, no Browserbase key, no LLM key.
- Browsers: our Browserbase only. Never local Chromium on the user's machine.
- Simulated user = whoever calls the tools. The server names no model and returns no `driver_model`.
- MVP: one simulated user, one product, vision perception (screenshot + pixel coordinates).
- Judge + proof are server-side and never trust the driver's own "done".
- Hosting: same VM as the website, behind the usersim.vercel.app proxy.
