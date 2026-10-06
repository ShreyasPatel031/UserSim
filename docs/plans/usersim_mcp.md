# UserSim MCP — plan

Status: plan, agreed in chat 2026-10-06. MVP scope = **one simulated user on one product**.

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
| Keys on the client | None. Client holds only a UserSim API token we issue. |
| Transport | Remote MCP (streamable HTTP) on our API, `claude mcp add --transport http usersim <url> --header "Authorization: Bearer …"`. Tool list is served by the server, so there is no client package to drift. Optional stdio shim later only if a client needs one. |
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
- One active session per token (MVP), per-token daily cap.
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

1. Hostname for the MCP endpoint: the VM's own domain, or through the usersim.vercel.app proxy?
2. Token issuance for MVP: one hand-issued token per tester, or self-serve?
3. Stable public site for the E2E test (ideally one we control).
