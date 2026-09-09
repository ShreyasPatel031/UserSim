# E2E handoff — smoke test can only validate the easiest config

## TL;DR

`mvp/e2e_smoke_local.py` passes on YouTube. Full YouTube studies are visibly
broken. Both are true, because the harness **forces smoke mode** and smoke mode
skips the entire code path that breaks.

The test is not lying. It is answering a question nobody asked.

---

## The test gap (this is the work)

`e2e_smoke_local.py` hardcodes `test_mode = ON`:

```python
if await smoke.count() and not await smoke.is_checked():
    await smoke.check()                     # forces test_mode ON
if not await smoke.count() or not await smoke.is_checked():
    report["fails"].append("smoke checkbox not available/checked")
```

Server-side, everything that matters is behind `if not study.test_mode`
(`mvp/study.py:~1288`): task fan-out, competitors, multi-agent contention.

So the harness can **never** exercise:

- the persona/task/site fan-out
- more than one agent
- competitor sites
- browser-slot contention (the semaphore)
- consent walls / signed-in bootstraps under concurrency

### Evidence that this is the gap, not a flake

| run | url | mode | pass |
|---|---|---|---|
| `results/e2e_smoke_youtube/` | youtube.com | smoke (1 agent) | **True** |
| `results/e2e_run1/`, `run2/` | useagency.dev | smoke (1 agent) | **True** |
| `results/e2e_smoke_hard/` | youtube.com | smoke (1 agent) | False |

`e2e_smoke_youtube` passed honestly: steps `[0,1,2]`, typed a search, `done`,
`final_status: complete`, 14 distinct live frames, `live_max_static_gap: 1.7s`.
One agent on YouTube genuinely works. Eighteen do not.

### What to build

A `--full` flag (test-only; no product changes needed):

1. Do not touch the Smoke checkbox — drive it from the flag, and do not fail
   when it is unchecked.
2. Fill `competitors` so `sites > 1`.
3. Assert `task_count == n_persona_tasks × n_sites`. This is the regression
   guard for the cross-product bug (see below) — it would have caught 90.
4. Keep **every** existing assertion: stall guard, `live_max_static_gap`,
   fold detection, terminal status, `min_steps`, pill/step parity.

### Hyperparameters — decide these deliberately

Smoke defaults do not transfer. With N agents against a browser semaphore of
`MVP_BROWSER_CONCURRENCY`, agents legitimately sit idle for whole waves.
Derive, don't guess:

```
waves        = ceil(n_agents / MVP_BROWSER_CONCURRENCY)
stall_s      >= per_step_llm_latency * waves      (smoke default 45s is far too tight)
min_steps    per *started* agent, not globally
timeout      brief(~45s) + waves*~120s + summary(~30s), plus headroom
```

Do **not** loosen an assertion to get green. If a threshold fires on
legitimate queueing, fix how the threshold is derived — do not raise it until
it stops complaining. Several rounds of this session were spent undoing exactly
that pattern.

---

## Already fixed — do not redo

| commit | what |
|---|---|
| `1f7643c` | `study.py` called `expand_full_matrix` (persona × task × site = 75/90 agents). Switched to `expand_tasks_for_sites` → 15. Verified: 75→15 agents, **60 of 75 runs had been assigned the wrong persona** → 0. Even site coverage. |
| `fb7a545` | restored the hardened smoke harness (see `880d5ab` on `cursor/e2e-ui-run`) |

Why the cross product also broke completion: 90 agents against Browserbase
concurrency (**account plan limit is 25** — confirmed via
`GET /v1/projects → {'concurrency': 25}`; local shells were running **2**)
forced many waves whose ETA exceeded `MVP_STUDY_TIMEOUT_S`, so every full study
aborted before finishing.

### Harness hardening already in place

Continuous `LIVE_OBSERVER` latch (mount vs paint vs motion — the stage unmounts
the iframe the moment a session stops browsing, which races short runs); blank
`#0a0a0a` frame detection via grayscale spread; `live_max_static_gap` (longest
static gap, **not** a boolean — a sticky `not live_moved` gate let one early
pixel change disable the freeze check for the whole run); fold-proof stall
accounting (`--max-folds`, `--fold-ratio`) so server-side folding of identical
frames cannot hide a frozen agent from the progress judge; symmetric pill
predicate; site-PNG-only progress judging; resilient polling; 2.0s first-paint
SLA; site-agnostic by contract (every check derives from `--url`, no per-site
presets).

---

## Product bugs found and NOT fixed

### 1. `_ensure_on_host` is dead code — `mvp/browser_agent.py:256`

```python
current = str(browser_session.get_current_page_url() or "")   # coroutine, never awaited
```

Unawaited coroutine → `urlparse` → `host = ""` → `if not host: return`. The
off-host lock **never fires**, and it leaks a `RuntimeWarning` every step. This
is why agents drift off-site (a YouTube task navigated to `gong.io` and stayed).
One-line fix: `await` it.

### 2. Agents emit `'—'` actions — the real "stuck screen" cause

`_action_label(None)` renders `'—'`, meaning `model_output.action` came back
**empty**. Those steps burn a turn and change nothing, producing the identical
consecutive frames users report as frozen.

Live data from an 18-agent YouTube study (`ca0265ef`): all 18 `status=running`,
**49 of 51 trace rows had a screenshot** (so capture is fine, not the problem),
`num_steps` of 1–3, `last_action = "Deciding what to do next (step N)…"`.
The server log shows the agents genuinely working — typing "Advertise",
clicking Dailymotion's "I understand", scrolling, reaching Step 4 — so they are
**stuck thinking, not stuck rendering**. Every card shows its opening frame
because at any moment nearly all 18 are mid-LLM-call.

Worth investigating: whether YouTube's DOM size makes flash-lite return an
empty action slot.

### 3. Fabricated placeholder session — `mvp/static/app.js` `renderStage`

```js
const session = sessions[idx] || {
  status: "starting",
  persona_name: (…personas || [])[0]?.name || "Simulated user",
  task_title: uniqueBriefTasks(…)[0]?.title || "",
  trace: [],
};
```

A study with nothing happening renders as a live-looking card — "Simulated
user", "Task pending…", "0 steps". Makes a stall indistinguishable from a start.

### 4. `"N active"` overcounts

`active = running + summarizing`, where `running` counts status `running` **or**
`starting`. All agents are marked `starting` at launch, so a 90-agent study
reported "90 active" while the semaphore only ran 2. `queued` counts only status
`pending`, which these never receive.

### 5. Frontend ETA hardcodes concurrency

`app.js` `estimateStudySeconds` uses `Math.min(25, n)`. Should read the real
`MVP_BROWSER_CONCURRENCY`, or the ETA is wrong on any non-25 deployment.

### 6. `e2e_five_threads.py` is un-hardened on this branch

Its fixes were lost in a stash and never landed in `880d5ab` (only the smoke
test did). It still has: sticky `saw_live` exemption; "never live" gated on
progress also failing; hash compared only against `sha0` instead of the previous
step; thread count recorded but never asserted; `_select_session` swallowing
select failures (wrong-agent evidence reads as a pass). **It can still
greenwash.** Harden it before trusting any non-smoke verdict from it.

---

## Also known

- `MVP_PREFER_GCP_FLEET` is `"0"` and `_prefer_browserbase_live` returns
  `_browserbase_configured()`, so the fleet branch (`study.py:~1606`,
  `elif _fleet_preferred(...) and not _prefer_browserbase_live(study)`) is
  **unreachable**. Intended — moving off the fleet — but it means Browserbase
  concurrency (25) is now the hard parallelism ceiling. Running the full matrix
  in one wave needs a plan upgrade.
- `/api/studies` dedupes by URL, so `https://youtube.com` and
  `https://www.youtube.com/` collapse to one row and hide each other.
- Local server env matters: a shell running `MVP_BROWSER_CONCURRENCY=2` makes
  any full study look broken regardless of code. Check it before diagnosing.
