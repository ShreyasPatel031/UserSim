# Arm 0 — step budget 60, no other changes

Read `README.md` first. **This arm must complete before arms 1–3 mean anything**, because
it is the baseline they are compared against.

## Hypothesis

Raising the step budget from 33 to 60 converts runs that were cut off mid-task into real
attempts, recovering successes that were sitting just past the ceiling.

Expected: a modest gain, not a large one. The official `browser-use` reference scores 30%
at only 25 steps, so budget is not our deficit — it is the ceiling that hides everything
else. Treat a small gain plus a large drop in budget-exhaustion as success for this arm.

## Evidence

- 41 of 44 failures (93%) reached `num_actions >= 33`. Median failure: 34 steps.
- 3 of 6 successes finished at 33–34 steps: `[8, 16, 25, 33, 34, 34]`. Half the successes
  were pressed against the cap, so tasks are very likely succeeding just past it.
- `BLOCKED` runs die at median 12 steps, so they are unaffected by this change. If blocked
  counts move much, that is environmental noise.
- Webwright published the step curve: the first 50 steps deliver 82% of final accuracy and
  the next 50 add only 3–4 points. 60 sits just past the knee. Don't go to 100; you would
  roughly double cost for a few points and add loop time.

## Changes

No code change. `--max-actions` already exists on `run_mistral_bakeoff.py` and is now
plumbed through `fleet_bakeoff.sh` → `shard_runner.sh` via `MAX_ACTIONS`.

Do **not** edit `MAX_ACTIONS` in `src/capability/__init__.py`. Leave the default at 33 so
other arms and historical runs stay reproducible; override per-run instead.

## Run

```bash
STAGE=full100 \
FLEET_TAG=mistral-small-2603_arm0_b60 \
FLEET_PREFIX=usersim-bu-arm0 \
MAX_ACTIONS=60 \
  ./scripts/vm/fleet_bakeoff.sh
```

Then a **second seed at the same config** under tag `..._arm0_b60_seed2`. You need an
error bar on the baseline; without it you cannot tell a 3-point arm gain from noise. This
is the single most valuable extra run in the whole matrix.

## Report

- `success_rate_scored` and `n_scored` for both seeds, and the spread between them.
- Budget-exhaustion rate: fraction with `num_actions >= 60`. **This is the key number.**
  If it is still high, 60 is also too low and the ceiling is still binding — say so
  explicitly, because it changes how arms 1–3 get read.
- Median `num_actions` split by SUCCESS / FAILURE / BLOCKED.
- Cost. Expect roughly $11 (budget doubles token spend; history resend makes it slightly
  superlinear, though Stage 1 history caps hold it near linear).

## Success criteria

- Budget-exhaustion drops well below the current 93% of failures. This is the real test.
- `success_rate_scored` ≥ 12% (should not regress; more steps cannot hurt correctness).
- Seed-to-seed spread quantified, so arms 1–3 have a noise floor to beat.

## Watch out

- If exhaustion stays high *and* success is flat, the agent is looping rather than
  progressing — that is arm 1's territory, and it means the budget lever is spent.
- Wall time rises with budget. Keep `--workers 4`; the concurrency probe found 3–4 to be
  the stable maximum per `e2-standard-2` before CDP/screenshot timeouts appear.
- Confirm the manifest records `max_actions_budget: 60`. If it says 33, the flag did not
  reach the shard and the run is void.
