# Arm 1 — uncapped text history

## Hypothesis

We pinned `max_history_items=6` to avoid Mistral's 8-image limit. That limit does not apply:
browser-use's `agent_history_description` is text-only and each request carries one screenshot.
At step 30 the agent only sees step 1, `[... 24 omitted ...]`, and steps 26–30 — so it retries
failed approaches and burns the step budget.

Arm 1 removes the cap (`max_history_items=None`). Everything else matches arm-0.

## Config

```bash
export BROWSER_USE_ARM=1          # sets max_history_items=None
export BROWSER_USE_FAST=0
export CAPABILITY_MAX_ACTIONS=60  # default since parallel-arm protocol
```

Arm-0 control (for comparison):

```bash
export BROWSER_USE_ARM=0          # max_history_items=6 (12% baseline)
export BROWSER_USE_FAST=0
export CAPABILITY_MAX_ACTIONS=60
```

## Smoke (1 task, ~$0.05)

```bash
set -a && source secrets/env && set +a
export BROWSER_USE_ARM=1 BROWSER_USE_FAST=0

PYTHONPATH=src .venv/bin/python -m capability.run_mistral_bakeoff \
  --stage one --eval-index 0 --model mistral-small-2603 \
  --max-actions 60 --workers 1 --no-preflight \
  --tag arm1_smoke
```

Check manifest `harness_config.max_history_items` is `null` and no image-limit errors in trace.

## Full100 fleet (~$10–12)

```bash
STAGE=full100 \
MAX_ACTIONS=60 \
EXTRA_ENV='BROWSER_USE_ARM=1 BROWSER_USE_FAST=0' \
FLEET_TAG=mistral-small-2603_arm1_m60 \
./scripts/vm/fleet_bakeoff.sh
```

Pull + merge when done:

```bash
STAGE=full100 FLEET_TAG=mistral-small-2603_arm1_m60 \
./scripts/vm/fleet_bakeoff.sh --pull
```

## Success criteria

Compare against arm-0 at the same budget (60):

- `success_rate_scored` up on the same 100-task set
- fewer runs with `num_actions >= max_actions_budget` (was 93% of failures at budget 33)
- fewer exact-repeat action loops (was 32% of runs)

Report: `success_rate_scored`, `n_scored`, `by_status`, fraction at budget cap, `$` cost.
