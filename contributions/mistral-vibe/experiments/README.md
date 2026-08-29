# OM2W harness experiments — shared context

Read this before starting any arm. Each `arm*.md` is self-contained after this file.

## Goal

Improve the **harness**, not the model and not the judge. We are trying to raise
`success_rate_scored` for `mistral-small-2603` on the Online-Mind2Web (OM2W) task set
by fixing how the agent interacts with the page.

Out of scope for these arms: swapping the model, rewriting the judge, buying proxies.

## Where we are

Last full run (`results/capability/full100_mistral_mistral-small-2603_m33_stage1_fleet.json`,
88 of 100 tasks — 12 lost to Spot preemption):

| Metric | Value |
|---|---|
| `success_rate_scored` | **12.0%** (6/50) |
| Raw | 6.8% (6/88) |
| `BLOCKED` | 36 (41%) |
| `FAILURE` | 44 |
| `JUDGE_ERROR` | 2 |
| Cost | $5.57 ($5.06 Mistral API + $0.51 GCP) |

Reference point: the official OM2W leaderboard entry for `browser-use` + GPT-4o scores
**30.0%** at a **25-step** budget — a *smaller* budget than ours. So our deficit is not
the budget. Budget is *masking* our other problems, not causing the gap.
Leaderboard: https://huggingface.co/spaces/osunlp/Online_Mind2Web_Leaderboard

## The three findings these arms are built on

1. **The step budget is binding.** `MAX_ACTIONS = MAX_HUMAN_STEPS + ACTION_BUFFER` = 22 + 11
   = 33 (`src/capability/__init__.py`). 41 of 44 failures (93%) hit that cap, and 3 of 6
   successes finished *at* it (step counts were `[8, 16, 25, 33, 34, 34]`). Until this moves,
   every other change is measured through a ceiling and no A/B is interpretable.
   **Every arm therefore runs at `MAX_ACTIONS=60`.**

2. **Widget interaction is the largest genuine failure class.** Published component-level
   taxonomy over 8,864 failed traces: continuous calibration (sliders/ranges) 20.2%,
   transient state loss (popover closes before commit) 19.9%, missing commit 11.6%,
   target acquisition 11.2%, repetition loop 11.2%, missing widget procedure 9.6%.
   Our traces match: one run clicked element index 6580 six times; another issued
   `InputTextAction(index=6022, text='', clear=True)` then retyped, i.e. the agent is
   hand-rolling a clear-before-type workaround and paying two steps per field.

3. **We are already on the right substrate.** ComponentBench measured `browser-use`'s
   DOM mode as the *best* available observation mode for exactly our worst components —
   Date & Time 83.4% vs 59.4% for pixels, dropdowns 97.2% vs 79.0%. Do **not** switch to
   screenshots/set-of-marks. The substrate is fine; the action primitives are not.

## Measurement protocol — do not deviate

- **Never A/B on `full10`.** At n=8 the standard error is ±17 points. It cannot resolve
  any of these changes and it is what made two previous sessions look like progress.
- Run `--stage full100`. Compare `success_rate_scored` from
  `src/capability/metrics.py::summarize`, which already excludes `BLOCKED` and `JUDGE_ERROR`.
- Report alongside it: `by_failure_category`, the fraction of runs where
  `num_actions >= max_actions_budget`, and median `num_actions` split by outcome.
  A change that lowers budget-exhaustion but not success is still progress worth keeping.
- `BLOCKED` is environmental (datacenter IP), not your arm's fault. If your arm's blocked
  count moves a lot versus `arm-0`, that is noise, so say so rather than claiming a win.
- Quote `n_scored`, not just the percentage. 6/50 and 12/100 are not the same evidence.

## Fleet sizing — give every worker one vCPU

A bakeoff shard is **CPU-bound**, not network-bound. Measured on the arm-0 run:
4 workers on a 2-vCPU `e2-standard-2` produced **load average 6.25** (3× oversubscribed),
which stretched a step from ~10s to ~27s and a task from ~10 min to ~25 min. Memory was
never the constraint — 0.94 GB per worker, 3.9 GB of 7.9 GB used.

So the way to go faster is **fewer, bigger VMs with more workers each**, not more VMs.
Keep roughly 1 vCPU per worker:

| Machine | vCPU | Workers | VMs for 100 | vCPU/worker | Compute @0.4h |
|---|---|---|---|---|---|
| `e2-standard-2` | 2 | 4 | 25 | 0.50 | $0.21 |
| `e2-standard-4` | 4 | 4 | 25 | 1.00 | $0.43 |
| **`e2-standard-8`** | **8** | **8** | **13** | **1.00** | **$0.44** |

**Use `e2-standard-8` × 8 workers × 13 VMs.** Same compute cost as the oversubscribed
layout, half the VM count, and each Chromium gets a full vCPU. Compute is ~8% of run cost
either way — the Mistral API is the other 92%, and it is identical regardless of layout.
Do not trade CPU headroom to save cents on VMs.

## How to run an arm

```bash
# from repo root; needs secrets/env and secrets/vertex_adc.json
STAGE=full100 \
FLEET_TAG=<arm-tag> \
FLEET_PREFIX=usersim-bu-<arm> \
GCP_MACHINE=e2-standard-8 NUM_SHARDS=13 WORKERS=8 \
MAX_ACTIONS=60 \
EXTRA_ENV='<KEY=VAL KEY=VAL>' \
  ./scripts/vm/fleet_bakeoff.sh
```

13 Spot VMs × 8 workers, one task-shard each, ~10–15 min wall, ~$11 per arm at budget 60.
Each VM rejudges itself, uploads to
`gs://usersim-bakeoff-347838016394/<stage>/<tag>/`, then **deletes itself**. Do not leave
VMs running; a previous session burned 24 idle VMs.

```bash
STAGE=full100 FLEET_TAG=<arm-tag> ./scripts/vm/fleet_bakeoff.sh --status    # GCS markers, no SSH
STAGE=full100 FLEET_TAG=<arm-tag> ./scripts/vm/fleet_bakeoff.sh --pull      # GCS -> local + merge
STAGE=full100 FLEET_TAG=<arm-tag> ./scripts/vm/fleet_bakeoff.sh --relaunch  # restart preempted shards
STAGE=full100 FLEET_PREFIX=usersim-bu-<arm> ./scripts/vm/fleet_bakeoff.sh --down
```

Spot preemption is frequent — the arm-0 run lost 5 shards to it. `--relaunch` compares the
GCS `_done/` markers against live VMs and redeploys anything missing, so run it whenever
`--status` shows TERMINATED instances. Shards resume from their existing manifest.

## Per-step CPU knobs

`mistral_browser_use_runner.py` now applies lean Chromium flags on the local/fleet path
(`_lean_browser_args`) plus `enable_default_extensions=False` and
`cross_origin_iframes=False` — the Browserbase profile already had these, the fleet path
did not. Two further knobs, both off by default because they change what the agent sees:

- `BROWSER_USE_NO_IMAGES=1` — blocks image loading. Large CPU and bandwidth win.
- `BROWSER_USE_DOM_ONLY=1` — disables vision, so no per-step screenshot capture, PIL
  resize (`1280x800 → 960x600` every step) or PNG encode. This is the single biggest
  per-step CPU item at high worker counts. Note ComponentBench rates DOM mode *above*
  pixels for our worst components, so this may be a win on both axes — but it is an
  observation-mode change, so treat it as its own arm rather than folding it into another.

Never poll shards over SSH in a loop. The serial IAP loops that used to live in this
script took 4–8 minutes for 25 shards and reliably timed out. `--status` reads GCS.

`MAX_ACTIONS` and `EXTRA_ENV` are the two knobs that let an arm change behaviour without
editing the fleet scripts. `EXTRA_ENV` is a space-separated list of `KEY=VALUE` pairs
exported on the VM before the bakeoff starts.

## Guardrails

- **Gate every behaviour change behind an env var, defaulting to off.** Arms run
  concurrently off the same tree; an ungated change silently contaminates every other arm.
- Keep `BROWSER_USE_FAST=0`. Flash mode strips `evaluation_previous_goal`, `next_goal`,
  and thinking from the agent schema. It was measured to cost 3 tasks on full10.
- Record your flag in `stage1_config_snapshot()` (`src/capability/browser_use_harness.py`)
  so the manifest states which arm produced it. A result whose config you cannot
  reconstruct is worthless.
- `browser-use` is pinned to `0.13.8`. Verify API names against the installed package
  rather than assuming; several classes were renamed in the 0.13 line.
- Don't touch `src/capability/judge.py` or `metrics.py`. Changing the scorer mid-experiment
  invalidates comparison against `arm-0`.

## Arms

| Arm | File | Change | Effort |
|---|---|---|---|
| 0 | `arm0_baseline_budget.md` | Budget 60 only. **The baseline everything else is measured against — run first.** | trivial |
| 1 | `arm1_widget_primitives.md` | Direct `<option>` select, clear-before-type, programmatic dates, post-filter assert, loop breaker, filter-UI prompt | small |
| 2 | `arm2_self_verification.md` | Re-verify constraints before `done` is accepted | medium |
| 3 | `arm3_code_action_space.md` | Let the agent write Playwright code instead of click primitives | large |

Arm 0 must land before arms 1–3 are interpretable. Arms 1–3 are independent of each other
and parallelize cleanly.

## Known gaps you may hit

- Only `final.png` is saved per trace (110 PNGs across 339 trace dirs). There are no
  per-step screenshots, so no screenshot-based analysis is possible on existing data.
- Final-state capture launches a **fresh browser** and re-navigates to the end URL
  (`mistral_browser_use_runner.py`, the `async_playwright` block near the end of
  `_run_async`). URL and query string survive (verified: 0/85 mismatch), but cookies,
  login, cart contents, JS-applied filters, and form entries do not. Seven runs worked
  25+ actions and then hit `Access Denied`/`Human Verification` on that cold re-visit.
  Fixing this is tracked in `arm2` since self-verification needs the live session anyway.
- ~45% of the task set is unreachable from GCP datacenter IPs. Browserbase support already
  exists (`BROWSERBASE_PROXIES=1`), but proxies are a separate spend decision, not part of
  these arms.
