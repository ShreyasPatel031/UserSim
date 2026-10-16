# UserSim MCP — plan

Status: MVP built (`mvp/sim_mcp/`), e2e green locally against real Browserbase, incl. a real
Claude Code (Haiku) run. Not yet deployed to the VM. MVP scope = **one simulated user on one product**.

## 1. What we are building

An MCP server that any coding agent (Claude Code first) can add. The coding agent
**is** the simulated user: it reads the persona and task, looks at the product page,
and decides each action. UserSim provides everything else:

- the browser — **always our Browserbase account**, never a browser on the user's laptop,
  and never the user's own Browserbase key;
- action execution, trace + screenshot recording;
- the live window (the same study page and Browserbase live iframe as usersim.vercel.app);
- independent judging, the proof checks, and the report that goes back to the agent.

Users bring nothing but their coding agent. They never open the website.

```
User's Claude Code (the brain)
  └─ MCP tools ──bearer token──▶ UserSim API (ours, holds Browserbase + Gemini keys)
                                   ├─ Browserbase session  ──▶ product URL (public)
                                   ├─ executor: runs each action on the real page
                                   ├─ recorder: trace, screenshots → same Study store
                                   ├─ live window: /live study page + BB live iframe
                                   └─ judge + proof checks + report  ──▶ back to Claude
```

## 2. Decisions

| Topic | Decision |
|---|---|
| Brain | User's Claude Code. Driver is a field (`driver: "claude_code"`) so other models (Codex, our Gemini a11y agent) can plug in later. Not built now. |
| Browser | Browserbase only, our key, server-side. No local Chromium, no user key. |
| Keys on the client | None, and no token either: the user only provides a public URL, same as the website. Abuse is bounded server-side (see Server rules). |
| Transport | Remote MCP (streamable HTTP) at `/mcp` on the same server as the website (the GCP VM behind the usersim.vercel.app proxy): `claude mcp add --transport http usersim https://usersim.vercel.app/mcp`. Tool list is served by the server, so there is no client package to drift. |
| Simulated-user model | Model-agnostic. The caller is the simulated user. Server instructions name no model and the start response has no `driver_model`. If the human asked for a model, the caller uses that; otherwise it uses the model it is already running as. |
| Product reachability | Public URLs only (Browserbase can't reach `localhost`). Preview deploys work. Tunnels later. |
| Perception | Pluggable. Final product offers three tiers (low / medium / high) that bundle perception mode, screenshot resolution, step cap, number of users. **MVP ships `vision` only.** |
| Persona fidelity / stopping science | Out of scope. Keep a clean seam (`BehaviorPolicy`), ship a minimal placeholder. Server-side safety caps are infra, not science, and stay. |
| Judging | Server-side with our model (existing vision judge in `e2e2_gates.judge_goal_screenshot`). Never trust the driver's own "done". |

### Perception modes (seam built in MVP, only `vision` implemented)

| Mode | Observation the driver gets | Action targets | Notes |
|---|---|---|---|
| `a11y` | numbered accessibility tree text (today's `mvp/a11y_agent.py`) | element ref `#12` | cheapest; blind to canvas / icon-only UI |
| `marks` | screenshot with numbered boxes + element list (browser-use style "set of marks"; we implement it ourselves, browser-use's agent loop can't be used because it owns the LLM call) | element ref | middle |
| `vision` | screenshot only (+ URL, title) | pixel coordinates | closest to what a person sees; Claude is trained for this action space; most tokens |

One action schema covers all modes: `target` is either `{ref}` or `{x, y}`.

Tiers (later, placeholder field `tier` accepted and ignored in MVP):
`low` ≈ a11y, small screenshots, short step cap, 1 user · `medium` ≈ marks · `high` ≈ vision,
full-res, more users. Token cost on the user's Claude plan is driven by these.

## 3. No-version-drift rules

1. **One server, one engine.** The MCP tools, persona/task prompts, action executor,
   judge, proof checks and report all live on our server. The client receives them at
   runtime, so a stale client can't exist.
2. **An MCP run is a normal `Study`.** It is written to the same store (`STUDIES`,
   `persist_study`, GCS) with `driver="claude_code"` and one `live_sessions` row.
   So the existing study page, `/api/studies/{id}`, `/live`, `/report` and the
   `e2e2_gates` functions work on it unchanged. No second report or viewer.
3. **Version stamp from day 1.** `engine_version` (git SHA at deploy) + `config_hash`
   are returned by `/health`, by `usersim_start_session`, and stored on every study and report.
4. **Shared core module.** Browserbase session lifecycle, executor, recorder, screenshots,
   judge, proof checks go in one core package (`mvp/core/`). The MCP path uses it from
   day 1; the website's Gemini a11y path migrates onto it in Phase 3, which also retires
   the browser-use GCP fleet path and consolidates config/prompts.

## 4. MVP scope: one user, one product

### Spec (what the human approves)

```json
{
  "product_url": "https://app.example.com/signup",   // required, human-provided
  "task": "Create a project and invite a teammate",   // drafted by Claude from the codebase, human approves
  "persona": "Ops manager at a 200-person logistics co, not technical, evaluating tools",  // drafted, approved
  "perception": "vision",        // MVP: only value
  "tier": null,                  // reserved
  "driver": "claude_code"        // reserved
}
```

Human input required: `product_url`. Task and persona are drafted by Claude Code
(it can read the repo / diff) and shown to the human before `usersim_start_session`.
The MCP prompt tells the agent to ask for that approval.

### MCP tools

| Tool | Input | Output |
|---|---|---|
| `usersim_start_session` | spec | `study_id`, `session_id`, `watch_url`, `engine_version`, persona/task brief, rules (`max_steps`, `budget_s`, viewport), first observation |
| `usersim_observe` | `session_id` | screenshot (MCP image content, 1280×800 viewport), `url`, `title`, `step` |
| `usersim_act` | `session_id`, `action`, `thought` | result + next observation (saves a round trip) |
| `usersim_finish` | `session_id`, `outcome` (`completed` / `gave_up` / `blocked`), `notes` | ack; triggers judging |
| `usersim_get_report` | `study_id` | markdown report + structured JSON (see below) |

Plus one MCP **prompt** `simulate_user` (served by the server) that tells the driver how
to run the loop: stay in persona, one action per call, record a `thought` each step,
call `usersim_finish` when done or stuck, open `watch_url` for the human
(`open <url>` / `xdg-open`).

Vision actions: `click{x,y}`, `double_click{x,y}`, `type{text}`, `key{keys}`,
`scroll{x,y,dy}`, `back`, `wait{ms}`, `navigate{url}` (same-site only).

### Server rules (infra, not behavior science)

- `max_steps` 40, `budget_s` 15 min, idle timeout 5 min → session closed and the study marked abandoned.
- `navigate` limited to the product's registrable domain + common auth providers
  (stops our Browserbase account being used as a general browsing proxy).
- No auth (matches the website). Caps instead: `MVP_MCP_MAX_SESSIONS` (5) open sessions server-wide,
  `MVP_MCP_MAX_PER_CLIENT` (2) per client IP.
- Every `act` is executed on the real Browserbase page via Playwright `connect_over_cdp`;
  screenshot after each action is stored like `step_shots.py` does today.

### Report returned to Claude

- Outcome: **judge verdict** (goal reached yes/no + reason), the driver's own claim shown separately.
- Step list: action, `thought`, URL, screenshot link.
- Friction points: from the driver's `thought` / `notes`, each tied to a step + screenshot.
- Proof block: `{pass, checks[]}` (below). If proof fails, the report says so at the top.
- Links: `watch_url` (replay), `/report?study=…`, `engine_version`.

### Proof contract (MVP subset of today's website gates, run server-side on every MCP study)

From `mvp/e2e2_gates.py` / `mvp/e2e_smoke_local.py`, parameterised for 1 agent:

1. Browser opened on the assigned host (`opened_on_assigned_site`).
2. ≥1 real action (click / type / scroll) executed by the executor.
3. Every step has a real screenshot (image magic bytes, >2 KB, not blank by `_looks_blank`).
4. Went beyond the first screen (`beyond_first_screen`).
5. Live view URL was offered for the session.
6. Judge ran. Judge error = `unverified`, never a silent pass (fixes the
   `page_verdict.py:89-91` fallback for this path).
7. Not snapshot / test mode.

### Tests

- Unit (offline): action schema validation, domain guard, executor with a fake page,
  proof checks on fixture studies, report renderer.
- E2E `mvp/e2e_mcp.py`: a scripted MCP client (fixed actions, no LLM) runs one session
  against a stable public site. Then Playwright opens `watch_url` and asserts the same
  live-view checks as `e2e_smoke_local.py` (iframe mounted, painted, changing). Then it
  asserts `proof.pass` and the report shape.
- Manual acceptance: real Claude Code, one persona, one task, on a real product.

### Build steps

1. `mvp/core/`: Browserbase session open/close + live URL, vision executor, recorder → Study.
2. Proof checks module + judge wiring (reusing `e2e2_gates`).
3. MCP endpoint mounted in `mvp/server.py` (`/mcp`), token auth, tools + `simulate_user` prompt.
4. Report renderer (markdown + JSON) from the Study.
5. `engine_version` / `config_hash` stamping, `/health`.
6. Tests above; deploy; manual Claude Code acceptance run.

## 5. Later phases (designed for, not built)

- **P2 — breadth:** `a11y` and `marks` perception, tiers low/medium/high, multiple users
  (Claude Code subagents, one per persona × task, in parallel), competitors, product auth
  (test accounts / sign-up).
- **P3 — consolidation:** website's Gemini a11y agent becomes a second driver on
  `mvp/core/`; retire the browser-use GCP fleet path; single engine config; prompts out
  of inline strings; VM deploy script pinned to a tag. Offer `driver: "hosted"` for big runs.
- **P4 — behavior science:** `BehaviorPolicy` (persona fidelity, when real users quit,
  calibration against human data). Other model drivers (Codex etc.).

## 6. Open questions

Resolved: endpoint on the existing VM via the usersim.vercel.app proxy; no tokens; Haiku default;
E2E uses books.toscrape.com (a public scraping sandbox).

Still open:
1. Deploy: the VM is set up by hand (no script in the repo). Someone with VM access pulls this
   branch, runs `pip install -r requirements-vercel.txt` (adds `mcp`, `pillow`) and restarts uvicorn.
2. Vercel proxy timeouts on long tool calls (start ≈ 5–20 s) — verify after deploy with
   `python -m mvp.e2e_mcp --base https://usersim.vercel.app`.

## 7. What was built (MVP)

| File | What |
|---|---|
| `mvp/sim_mcp/sessions.py` | Browserbase session per simulated user, URL guard, vision action executor, recorder into a normal `StudyState`, idle/budget reaper |
| `mvp/sim_mcp/report.py` | independent judge (`e2e2_gates.judge_goal_screenshot`), proof checks (e2e2 gate functions), report JSON + markdown |
| `mvp/sim_mcp/server.py` | MCP tools + `usersim_simulate_user` prompt, mounted at `/mcp` in `mvp/server.py` |
| `mvp/version.py` | `engine_version` + `config_hash`, on `/health`, every study, every report |
| `mvp/static/app.js` | `/?study=<id>` opens any study on the same live stage a Run shows (the MCP `watch_url`) |
| `mvp/test_sim_mcp.py` | offline unit tests |
| `mvp/e2e_mcp.py` | live e2e: scripted MCP client + Chromium check that watch_url mounts the live iframe + proof.pass |

Add to Claude Code:

```
claude mcp add --transport http usersim https://usersim.vercel.app/mcp
```

Then ask: "Run a UserSim test of https://my-preview.vercel.app — new user trying to create a project."
