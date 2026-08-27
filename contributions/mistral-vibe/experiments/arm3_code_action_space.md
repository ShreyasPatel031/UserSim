# Arm 3 — code as the action space

Read `README.md` first. Runs at `MAX_ACTIONS=60`, same as arm 0.

**Highest ceiling, largest build.** This is a separate track, not a same-day arm. Start it
in parallel with arms 0–2 but expect it to land later.

## Hypothesis

Predicting one click at a time accumulates error across long chains. Letting the agent
write a short program instead — for a date range, a filter set, a whole form — collapses a
15-step chain into one action with one failure point, and matches what LLMs are actually
good at.

## Evidence

- Microsoft's **Webwright** scores **86.7%**, the highest open harness recipe on the OM2W
  leaderboard, by giving the model a terminal and having it drive the browser with
  Playwright code. They ran the controlled comparison: the *same* GPT-5.4 in a conventional
  screenshot-plus-coordinate loop scored materially lower across all three difficulty
  tiers. Their stated rationale is exactly our failure profile — "selecting a date or
  filling out an entire form" is expressible as a compact program.
  https://www.microsoft.com/en-us/research/articles/webwright-a-terminal-is-all-you-need-for-web-agents/
- **`browser-use` reached the same conclusion independently.** Their OM2W writeup has a
  section titled "The biggest improvement" describing this exact switch: "Instead of only
  tools like click and type, it added Python to parse HTML and extract data. This aligns
  much better with the LLM's training distribution and makes edge cases and data extraction
  dramatically easier." Since we *are* a `browser-use` shop, this is the upstream author's
  own highest-value change.
  https://browser-use.com/posts/online-mind2web-benchmark
- Corroborating our own data: 27% of our actions are DOM-groping (`Evaluate` 11.0% +
  `FindElements` 8.6% + `SearchPage` 7.8%) — the agent burning steps on inspection that a
  single query would answer.

## Scope this narrowly

Do **not** rewrite the harness into a terminal agent. Add a code-execution action alongside
the existing primitives and let the model choose. Gate behind
`BROWSER_USE_CODE_ACTIONS=1`, default off.

**Implemented (2026-08-22):**

| Piece | Location |
|---|---|
| `run_page_code` action | `src/capability/code_actions.py` |
| `page` helper (`fill`, `click`, `select_option`, `set_date`, `eval_js`) | `src/capability/page_helper.py` |
| Shared registry injection | `src/capability/widget_tools.py` → wired in `mistral_browser_use_runner.py` |
| Prompt steer | `stage1_agent_kwargs` when flag on |
| Manifest flags | `harness_config.code_actions` via `stage1_config_snapshot()` |

Sandbox: no imports, 15s wall timeout (`BROWSER_USE_CODE_TIMEOUT_S`), 8k result cap
(`BROWSER_USE_CODE_RESULT_MAX`), post-run `allowed_domains` check on current URL.

1. **`run_page_code(code)`** — execute a short async Python snippet against the current
   page, returning stdout plus a serialized result. Bound it hard: a wall-clock timeout
   (start at 15s), a result-size cap, and no navigation away from `allowed_domains`
   (`stage1_profile_kwargs` already computes the allowlist — reuse it, don't reimplement).
2. **Prompt for the right use cases** — multi-field forms, date ranges, filter sets,
   extracting a structured list. Steer away from single clicks, where the existing
   primitive is cheaper and safer.
3. **Return errors verbatim** so the model can iterate. A truncated traceback is useless
   and it will retry blind.
4. **Keep a step ceiling per snippet** so one runaway snippet cannot consume the run.

Reuse arm 1's `widget_tools.py` registry rather than building a second injection point.

## Local smoke (required before fleet)

Pick 5 tasks where the baseline trace shows DOM-groping or calendar/filter pain
(`Evaluate`/`FindElements`/`SearchPage` heavy, or judge reason mentions dates/filters):

```bash
export BROWSER_USE_CODE_ACTIONS=1
export BROWSER_USE_FAST=0
PYTHONPATH=src .venv/bin/python -m capability.run_mistral_bakeoff \
  --stage full10 --model mistral-small-2603 --workers 2 --max-actions 60 \
  --tag arm3_code_smoke --no-preflight
```

**Pass criteria for smoke:** at least one task calls `run_page_code` without exception;
exception rate on code calls < 50%; no silent harness crash. If the model never reaches
for `run_page_code`, tighten the prompt or rename the action description before buying
a fleet run.

## Run

```bash
STAGE=full100 \
FLEET_TAG=mistral-small-2603_arm3_code \
FLEET_PREFIX=usersim-bu-arm3 \
MAX_ACTIONS=60 \
EXTRA_ENV='BROWSER_USE_CODE_ACTIONS=1 BROWSER_USE_FAST=0' \
  ./scripts/vm/fleet_bakeoff.sh
```

Compare against **arm 0** (`mistral-small-2603_arm0_b60`), not the old m33 fleet.

```bash
STAGE=full100 FLEET_TAG=mistral-small-2603_arm3_code ./scripts/vm/fleet_bakeoff.sh --status
STAGE=full100 FLEET_TAG=mistral-small-2603_arm3_code ./scripts/vm/fleet_bakeoff.sh --pull
```

~$11 Mistral API + ~$0.50 GCP. Do not run until arm 0 baseline has at least one seed.

## Report

- `success_rate_scored` and `n_scored` vs arm 0, against arm 0's seed spread.
- How often `run_page_code` was chosen, and its success/exception rate. **If the model
  rarely reaches for it, that is the finding** — the prompt or the signature is wrong, and
  the arm is untested rather than falsified.
- Steps per success vs arm 0. The mechanism here is step compression; this is where it
  should show.
- DOM-groping action share vs arm 0.

## Success criteria

- `success_rate_scored` beats arm 0 by more than arm 0's seed spread.
- Meaningful adoption of the code action, with a low exception rate.
- Fewer steps per success.

## Watch out

- **Security.** This executes model-authored code. It runs on ephemeral Spot VMs that
  delete themselves, which is the right blast radius, but never run this arm on a
  workstation or anything with live credentials. `secrets/env` and `secrets/vertex_adc.json`
  are on those VMs — keep the timeout and domain allowlist tight, and treat exfiltration as
  the threat model, not just crashes.
- Mistral Small may not write reliable Playwright. If the exception rate is high, the arm is
  bounded by the model, not the idea — report that plainly rather than iterating forever.
  Note that both published successes here used frontier models (GPT-5.4).
- A code action that can navigate anywhere silently voids the `allowed_domains` control that
  the rest of the harness depends on. Enforce the allowlist inside the action.
- If this arm wins big, it likely subsumes much of arm 1. Land arm 1 first anyway — it is
  cheap, it is independently valuable, and it gives this arm a fair comparison point.
