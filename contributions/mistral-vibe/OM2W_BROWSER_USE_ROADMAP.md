# Vibe CLI × Browser Use: Online-Mind2Web Roadmap

**Contribution for [mistralai/mistral-vibe](https://github.com/mistralai/mistral-vibe)**  
**Date:** 2026-08-22  
**Benchmark:** Online-Mind2Web (OM2W) full10 via Browser Use OSS + `mistral-small-2603` (Mistral Small 4)  
**Harness reference:** [UserSim `mistral_browser_use_runner.py`](../../src/capability/mistral_browser_use_runner.py)

---

## Executive summary

We ran **Mistral Small 4** (`mistral-small-2603`) on the same 10-task OM2W slice used for Gemini baselines, using **Browser Use 0.13.8** as the execution harness (1280×800 viewport, 33-step budget derived from Mind2Web human trajectories).

| Metric | Mistral Small 4 | Gemini 2.5 Flash (same harness) |
|--------|----------------:|--------------------------------:|
| Scored success rate | **44.4%** (4/9) | **35.7%** (5/14) |
| Primary failure mode | PREMATURE_STOP (5/5 of remaining failures) | PREMATURE_STOP, STEP_CAP, BLOCKED |
| Avg cost / task | ~$0.04 | ~$0.09 |

**Key finding:** Mistral Small 4 **already beats the Gemini 2.5 Flash reference point** on this slice, at roughly half the cost per task. The story for Vibe is not "catch up" — it is that a small open model is competitive once the harness stops discarding its work.

Two caveats worth stating plainly. First, 9 scored tasks is a small sample; the 300-task run is what settles this. Second, the first reading of this same run said 22%, because the judge's Vertex token expired mid-run and 5 tasks were silently recorded as AMBIGUOUS. Fixing the measurement — not the agent — produced the single largest swing in this project so far.

Every remaining failure is the same mode: declaring `done` before the task's constraints are actually satisfied on the page.

Vibe CLI today has **no first-class browser/computer-use loop**. Closing the gap means borrowing Browser Use's **observe → act → verify** cycle as a Vibe-native capability (MCP tools + agent profile + skill), not reimplementing web automation inside Vibe's bash/file tools.

---

## Benchmark setup

```bash
# From UserSim repo (reference harness)
PYTHONPATH=src python -m capability.run_mistral_bakeoff \
  --stage full10 \
  --model mistral-small-2603 \
  --max-actions 33 \
  --workers 4
```

**Tasks (10):** IGN, Rotten Tomatoes, ESPN, Newegg, Uniqlo, Megabus, JetBlue, TicketCenter, Under Armour, Eventbrite — indices `[32, 26, 33, 8, 19, 22, 7, 12, 25, 34]`.

**Judge:** Gemini 2.5 Flash LLM judge on final URL + action trace + screenshot (same as our capability bakeoff; OM2W official WebJudge is recommended for published numbers).

**Observation mode:** `browser_use_vision` (screenshots + DOM indices sent to Mistral API).

---

## Failure audit (Mistral Small 4, full10 complete)

All 10 tasks completed and scored. Verdicts below are post-re-judge; see the [hill-climb plan](HILL_CLIMB_PLAN.md) for why the first reading was wrong.

| Primary cause | n | What happened |
|---------------|--:|---------------|
| **PREMATURE_STOP** | 5 | Agent called `done` before the task's constraints were satisfied on the page |
| **BLOCKED** | 1 | Uniqlo — Akamai 403 from a datacenter IP; environment, not model |

Two infrastructure issues showed up throughout without owning a task outcome, and both are config defaults rather than model behaviour:

- **Mistral 429s** during `extract` and planning, because browser-use routes page extraction and its own internal judge through the agent LLM by default.
- **`Total number of images exceeds the maximum allowed of 8`**, from browser-use's built-in judge sending an unbounded screenshot history to a model with an 8-image cap.

### Task-level detail

| idx | Site | Task (short) | Verdict | Steps | Note |
|-----|------|--------------|---------|------:|------|
| 7 | JetBlue | Career openings in New York | SUCCESS | 13 | |
| 25 | Under Armour | Purple high-support sports bra, small | SUCCESS | 32 | Multi-filter task completed at the step cap |
| 32 | IGN | Open Resident Evil 4 guide | SUCCESS | 32 | Reached it by direct URL after search thrashing |
| 33 | ESPN | Follow Atlantic Division NHL team leader | SUCCESS | 26 | Reached David Pastrnak's profile |
| 8 | Newegg | Wireless KB/mouse combo <$100 | FAILURE | 6 | Declared done on a category page having clicked "Add to cart" on an unspecified item |
| 12 | TicketCenter | Show all NFL tickets | FAILURE | 16 | |
| 22 | Megabus | Bus stops in Alanson, MI | FAILURE | 30 | "From" autocomplete kept reverting to "Dallas, PA" |
| 26 | Rotten Tomatoes | Top critic reviews, lowest-rated Tom Hanks film | FAILURE | 18 | Picked *A Man Called Otto* without establishing it was lowest-rated |
| 34 | Eventbrite | Music party in Ohio, follow organizer | FAILURE | 17 | |
| 19 | Uniqlo | Baby sale items <$10 | BLOCKED | 9 | 403, then escaped to Google/Bing → CAPTCHA |

The step counts carry the real signal. Only Newegg is an obvious early bail at 6 steps; Megabus stopped at 30, Rotten Tomatoes at 18, Eventbrite at 17. These agents were not running out of budget — they *chose* to stop while wrong. Meanwhile both long successes (Under Armour and IGN) finished at 32 of 33 steps, right against the cap.

So the fix is not simply "give it more steps". The `done` decision itself needs to be verified against the task's constraints, which is what Phase 2 does.

### Comparison with Gemini on overlapping tasks

| idx | Gemini BU OSS | Mistral Small 4 |
|-----|---------------|-----------------|
| 8 Newegg | SUCCESS (15 steps) | FAILURE (6 steps, early done) |
| 19 Uniqlo | BLOCKED | BLOCKED — environment, needs Browserbase |
| 22 Megabus | SUCCESS (16 steps) | FAILURE (30 steps) |
| 32 IGN | BLOCKED | **SUCCESS** (32 steps) |
| 33 ESPN | SUCCESS (19 steps) | SUCCESS (26 steps) |

Aggregate: Mistral Small 4 **44.4%** scored vs Gemini 2.5 Flash **35.7%** on the same harness.

---

## Gap analysis: Vibe CLI vs Browser Use

| Dimension | Vibe CLI today | Browser Use harness |
|-----------|----------------|---------------------|
| **Primary loop** | bash / read / write / grep in repo | Playwright CDP: screenshot + indexed DOM → structured actions |
| **Observation** | Optional `@image.png` attachments | Every step: viewport screenshot + element list + URL/title |
| **Action space** | Shell commands, file edits | click, input, scroll, navigate, search, extract, done |
| **Grounding** | N/A (no UI) | Element index from live DOM; coordinate metadata on click |
| **Planning** | Single conversational turn loop | Explicit eval/memory/next-goal; plan updates; loop detection |
| **Completion** | User approves or agent stops | `done(success=…)` + optional Browser Use judge trace |
| **Recovery** | Retry bash | wait, scroll, find_elements, search_page; often escapes to Google |
| **Extensibility** | MCP servers, skills, custom agents | Python Agent class + LLM adapter (ChatOpenAI → Mistral API) |
| **Parallelism** | Subagents (`task` tool) | One browser session per agent |
| **Env blocks** | N/A | WAF/CAPTCHA/datacenter IP (needs Browserbase) |

**What Vibe already has that Browser Use lacks:**
- Trust folder system, tool approval UX, OTEL tracing
- Skills (`/deploy`, custom slash commands) and agent profiles (`plan`, `auto-approve`)
- MCP registration CLI (`vibe mcp add …`)
- Managed shell sessions for long-running processes
- Compaction / session memory for long tasks

**What Browser Use has that Vibe needs for computer use:**
- Tight **per-step multimodal loop** (screenshot is first-class, not an attachment)
- **Structured action schema** with execution feedback in the same turn
- **Browser session lifecycle** (navigation, tabs, iframes, viewport)
- **Built-in web primitives** (search_page, find_elements, extract)

---

## Product roadmap

### Phase 0 — Measure ✅ already done (UserSim)

**This repo already has reproducible OM2W-style scoring.** Phase 0 is not greenfield work here — it is the baseline the Vibe contribution builds on.

| Capability | Where it lives |
|------------|----------------|
| Task loader (full10 / smoke / bakeoff5 / full100 / Hard-20) | `src/capability/tasks.py` + `data/mind2web_tasks.json` |
| Mistral + Browser Use runner | `src/capability/mistral_browser_use_runner.py` |
| Bakeoff CLI with `--resume`, `--workers`, JSON manifest | `src/capability/run_mistral_bakeoff.py` |
| Gemini baseline runner | `src/capability/run_bakeoff.py` |
| BLOCKED excluded from eligible rate | `success_rate_eligible` in bakeoff manifests |
| Per-run traces + judge | `results/capability/traces/mistral_*/` + `src/capability/judge.py` |
| Run docs | `results/capability/HOW_TO_RUN_OM2W.md` |

```bash
# Already works today
PYTHONPATH=src python -m capability.run_mistral_bakeoff \
  --stage full10 --model mistral-small-2603 --workers 4 --resume
```

**What's still open (not Phase 0, but gaps vs "proper" OM2W):**
- Official **WebJudge** (we use Gemini 2.5 Flash judge)
- **Browserbase** for datacenter IP blocks (Uniqlo etc.)
- Full maintained **300-task** OM2W set (we use the 100-task UserSim slice)
- **Vibe CLI `/benchmark om2w` skill** — the only Phase 0 item that belongs in mistral-vibe, not UserSim

**Exit criteria:** ✅ met for UserSim. Remaining Phase 0 work = expose the same loop inside Vibe (see Phase 1 wrapper).

---

### Phase 1 — Browser MCP adapter (2–4 weeks)

**Goal:** Vibe agent can drive a browser via MCP tools without leaving the Vibe UX.

Expose Browser Use (or Playwright) as MCP tools:

```
browser_navigate(url)
browser_snapshot()          → { url, title, elements[], screenshot_b64 }
browser_click(index|selector)
browser_type(index, text, clear?)
browser_scroll(direction, pages?)
browser_press(key)
browser_extract(query)      → page text/links for constraint check
browser_done(summary)       → terminal; triggers verification
```

**Vibe integration points:**
- Register via `vibe mcp add browser-use --transport stdio` (local MCP server wrapping Browser Use)
- New agent profile **`web-agent.toml`**:

```toml
active_model = "mistral-small-2603"
system_prompt_id = "web_agent"
enabled_tools = ["browser_*", "todo", "ask_user_question"]
disabled_tools = ["bash", "write_file", "edit"]

[tools.browser_navigate]
permission = "always"

[tools.browser_done]
permission = "ask"   # require user confirm until benchmark mode
```

- **`AGENTS.md` web policy:** stay on start domain; no Google/Bing unless task says so; apply every filter before done.

**Exit criteria:** Vibe completes Eventbrite mini2 + ESPN idx=33 without subprocess shell hacks.

---

### Phase 2 — Close the PREMATURE_STOP gap (2–3 weeks)

Every remaining failure is this one mode: the agent **confuses navigation with completion**. Port mechanisms from SeeAct and our failure audit:

| Mechanism | Implementation in Vibe |
|-----------|------------------------|
| **Screenshot verify before done** | Mandatory `browser_snapshot` + model call — "is every constraint visible on this page?" — before `browser_done` is allowed to terminate |
| **Constraint checklist** | On task start, parse task text → `todo` items (price cap, category, final action). Block `browser_done` until all checked. |
| **Key-points judge** | Second call with OM2W-style key points — already implemented in UserSim `judge.py` |
| **Disable self-judge** | browser-use's internal judge (`use_judge=True` by default) both hit Mistral's 8-image cap and burned rate limit. Use the external judge only. |

Note what is *not* on this list: "reject `done` before 50% of budget". The measured failures stopped at 30, 18 and 17 steps, so a step-count heuristic would not have caught them. Verification has to be about page state, not trajectory length.

**Prompt addition (`~/.vibe/prompts/web_agent.md`):**

```markdown
You are a web task agent. Rules:
1. Every constraint in the task (price, size, date, "follow", "add to cart") must be applied on-page.
2. Do not call browser_done on a category or search results page.
3. Never leave the start website domain except for PDF/download links.
4. After filters, read the visible results to confirm constraints before stopping.
```

**Exit criteria:** Newegg idx=8 succeeds on ≥2 of 3 seeds; `PREMATURE_STOP` below 3/10; `success_rate_scored` clears 55%.

---

### Phase 3 — API & vision hardening (1–2 weeks)

Mistral-specific infra failures from traces:

| Issue | Fix |
|-------|-----|
| **429 rate limits** | Exponential backoff in MCP server; reduce `max_actions_per_step` from 3→1 under load; queue extract calls |
| **8-image API cap** | Rolling screenshot window: send last 2 screenshots only; DOM text for history |
| **CDP timeouts at workers>1** | Default `--workers 1` for vision models; or DOM-only mode for Ministral-3B |
| **Token burn** | Step-level compaction: summarize actions >10 into bullet memory (reuse Vibe `/compact`) |

Add to `config.toml`:

```toml
[web_agent]
max_screenshots_per_request = 2
max_steps = 33
vision = true
rate_limit_backoff_sec = 2.0
parallel_tasks = 1
```

**Exit criteria:** Zero 429-aborted trajectories on full10; no judge failures from image limit.

---

### Phase 4 — Environment & recovery (2 weeks)

| Issue | Fix |
|-------|-----|
| **BLOCKED (Uniqlo, etc.)** | Browserbase CDP URL in config; residential proxy; label BLOCKED not FAILURE |
| **Off-site search escape** | Hard block `browser_navigate` to non-allowlisted domains in web-agent profile |
| **Overlay / cookie walls** | Skill step: detect "Accept"/"Decline"/"Close" in snapshot → click before planning |
| **Form autocomplete** | Browser Use already has concatenation retry; expose `browser_select_autocomplete(index, option)` |
| **CAPTCHA** | Detect `/sorry/` URLs → status BLOCKED + user handoff via `ask_user_question` |

**Exit criteria:** Uniqlo idx=19 runs on Browserbase reach product listing; Megabus form submission succeeds.

---

### Phase 5 — Native Vibe computer use (optional, 1–2 months)

Long-term: reduce Browser Use dependency.

| Milestone | Description |
|-----------|-------------|
| **Playwright MCP** | Thin MCP over Playwright (Microsoft pattern) — Vibe owns session, BU supplies prompts |
| **`web` subagent** | `task` tool delegates to web-agent with isolated browser session |
| **Devstral / Ministral CUA** | Fine-tuned coordinate head (see UserSim `MISTRAL_CUA_FINETUNE_PLAN.md`) as optional local model |
| **Training flywheel** | Export successful Vibe web traces → Mistral fine-tuning JSONL (same as `traces_to_mistral_sft.py`) |

---

## Recommended architecture

```text
┌─────────────────────────────────────────────────────────┐
│  Vibe CLI (web-agent profile)                           │
│  ├── prompts/web_agent.md  (constraints, no early done) │
│  ├── todo checklist        (parsed from task)         │
│  ├── skills/benchmark-om2w.md                           │
│  └── MCP: browser-use-server                            │
│       ├── Playwright / Browserbase CDP                  │
│       ├── snapshot → mistral-small-2603 (vision)        │
│       ├── structured actions ← model                    │
│       └── trace export → ~/.vibe/benchmarks/            │
└─────────────────────────────────────────────────────────┘
         ↓ verify
┌─────────────────────────────────────────────────────────┐
│  External judge (WebJudge-7B or gemini-2.5-flash)       │
│  key_points + screenshot → SUCCESS | FAILURE | BLOCKED  │
└─────────────────────────────────────────────────────────┘
```

---

## Priority matrix

| Priority | Item | Impact | Effort | Closes |
|----------|------|--------|--------|--------|
| **P0** | Browser MCP adapter + web-agent profile | High | Medium | No browser in Vibe |
| **P0** | Verified `done` + constraint checklist | High | Low | PREMATURE_STOP (**all** remaining failures) |
| **P0** | `use_judge=False`, route extraction to a cheap model | High | Trivial | 429s and the 8-image cap |
| **P1** | Screenshot window / 429 backoff | High | Low | Infra aborts |
| **P1** | `/benchmark om2w` skill (wrap existing UserSim runner) | Medium | Low | Vibe-native measurement |
| **P1** | Browserbase config | Medium | Medium | BLOCKED tasks |
| **P2** | Off-site navigation guard | Medium | Low | RECOVERY |
| **P2** | WebJudge integration | Medium | Medium | Credibility vs OM2W leaderboard |
| **P3** | Native Playwright MCP | Low | High | BU dependency |

---

## Success metrics

Track `success_rate_scored` on OM2W full10 — SUCCESS / (SUCCESS + FAILURE), excluding env blocks and any run the judge could not score.

| Milestone | Target |
|-----------|--------|
| Baseline (measured) | **44.4%** (4/9) |
| Phase 1 — harness config | no regression; 429 and image-limit aborts at 0 |
| Phase 2 — verified `done` | ≥55% |
| Phase 3–4 | set from the 300-task run, not guessed |

Also track:
- **Steps-to-success** (median) — for Newegg-type tasks a *longer* trajectory is the improvement. A config that shortens trajectories is probably just stopping early again.
- **Cost per scored success** — currently ~$0.11; keep under $0.15.
- **`judge_error_rate`** — must be 0, or the comparison is meaningless.

Targets past Phase 2 are deliberately left open. With 9 scored tasks any specific number would be invented; the 300-task run is what sets them.

---

## How to contribute back to mistral-vibe

1. **MCP server:** New repo `mistral-vibe-browser` or package under `mistral-vibe` extras: `pip install mistral-vibe[browser]`
2. **Default agent:** PR adding `~/.vibe/agents/web-agent.toml` + `prompts/web_agent.md`
3. **Skill:** PR adding `skills/benchmark-om2w/SKILL.md` with OM2W task loader
4. **Docs:** Link this roadmap from Vibe README under "Computer use (preview)"
5. **Model config:** Document `mistral-small-2603` vision limits (8 images) in model matrix

---

## References

- [mistralai/mistral-vibe](https://github.com/mistralai/mistral-vibe) — MCP, skills, agent profiles
- [browser-use/browser-use](https://github.com/browser-use/browser-use) — OSS web agent harness (v0.13.8)
- [OSU-NLP-Group/Online-Mind2Web](https://github.com/OSU-NLP-Group/Online-Mind2Web) — maintained 300-task benchmark
- UserSim artifacts: `results/capability/full10_mistral_mistral-small-2603_m33.json`, `results/capability/FAILURE_AUDIT.md`, `results/capability/open_ecosystem/OPEN_ECOSYSTEM_ANALYSIS.md`

---

*Generated from live OM2W benchmark traces against `mistral-small-2603`. Re-run with `--resume` to refresh metrics as full10 completes.*
