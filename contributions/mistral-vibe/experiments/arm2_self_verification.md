# Arm 2 — self-verification gate before `done`

Read `README.md` first. Runs at `MAX_ACTIONS=60`, same as arm 0.

## Hypothesis

The agent declares `done` while constraints are unsatisfied. Forcing it to re-check every
constraint against the live page before `done` is accepted converts near-misses into
successes, and converts confident wrong answers into further attempts.

## Evidence

- Both systems that beat this benchmark treat this as load-bearing. Webwright names
  premature `done` one of its two core problems and gates it: the agent must produce a
  self-reflection config, re-run a verification script in a fresh folder with logs and
  screenshots, and pass its own judgement, or the `done` flag is dropped and it retries.
  The OM2W paper independently lists self-verification as one of Operator's three
  distinguishing advantages, with an appendix example of Operator picking BLUE instead of
  BLACK, detecting it, and self-correcting.
- Our failures read exactly like ungated `done`. Verbatim from exhausted runs:
  "Despite filtering…", "Task partially completed with critical limitations",
  "Summary of Attempts and Findings". The agent knows it failed and stops anyway.
- "Missing commit or confirmation" is 11.6% of the published failure taxonomy — filled the
  form, never hit Submit; chose the filter, never confirmed.
- Our current prompt already says "Do not call done until every task constraint is
  satisfied on the page" (`stage1_agent_kwargs`). It is ignored. **A stronger prompt is not
  this arm** — the point is a mechanical gate that can reject `done`, not more instruction.

## Changes

Gate behind `BROWSER_USE_VERIFY_DONE=1`, default off.

**Implemented (2026-08-22):** `src/capability/verify_done.py` — constraint extraction,
live-session page check via `on_step_end`, rejects `done` by clearing `is_done` and calling
`add_new_task` with unmet items. Wired in `mistral_browser_use_runner.py`. Stats land in
`run.json` as `verify_rejections`, `verify_cap_hit`, `verify_last_failed`.

1. **Extract constraints once, up front.** From the task text, produce an explicit checklist.
   Mirror the official rubric's stance: only constraints *stated* in the task, never
   inferred ones, and turn any superlative ("cheapest", "closest", "latest") into an
   explicit sort/filter requirement. Cache it on the run; do not recompute per step.

2. **Intercept `done`.** When the agent emits `done`, do not accept it. Re-read the live
   page and check each constraint. On pass, allow `done`. On fail, drop the flag and return
   the specific unmet constraints to the agent so it can continue.

3. **Cap retries** at 2 rejections, then accept `done` regardless. Without a cap this will
   burn the entire 60-step budget arguing with itself and you will have built a slower way
   to fail. Record the rejection count in the manifest.

4. **Verify against the agent's live session** — its own page, its own cookies. Do **not**
   use the existing final-screenshot path as your verifier: that block launches a fresh
   browser and re-navigates to the end URL. URL and query string survive (verified: 0/85
   mismatch) but cookies, login, cart contents, JS-applied filters, and form entries do
   not, so a cold re-visit cannot see most of what you need to check. Fixing that capture
   to reuse the agent session belongs to this arm, since verification needs it anyway.

5. Use the cheap extraction model (`ministral-8b-latest`, already wired as
   `page_extraction_llm`) for the check, not the agent model. This runs up to 3× per task.

Record `verify_done`, rejection count, and which constraints failed in the manifest and in
`stage1_config_snapshot()`.

## Run

```bash
STAGE=full100 \
FLEET_TAG=mistral-small-2603_arm2_verify \
FLEET_PREFIX=usersim-bu-arm2 \
MAX_ACTIONS=60 \
EXTRA_ENV='BROWSER_USE_VERIFY_DONE=1' \
  ./scripts/vm/fleet_bakeoff.sh
```

Smoke-test locally first; a verifier that never passes will fail all 100 tasks identically.

## Report

- `success_rate_scored` and `n_scored` vs arm 0, against arm 0's seed spread.
- **Gate statistics — the mechanism check for this arm:** how often `done` was rejected,
  how often a rejection was followed by an eventual success, and how often the retry cap
  was hit. If rejections almost never convert to successes, the gate is detecting real
  failure it cannot fix, which is a genuine finding and means the ceiling is elsewhere.
- `PREMATURE_STOP` count vs arm 0 (currently only 3, so there is little room here — see
  below).
- Budget exhaustion. Expect this to *rise*; verification consumes steps.
- Cost, including the extra verifier calls.

## Success criteria

- `success_rate_scored` beats arm 0 by more than arm 0's seed spread.
- Rejected-then-succeeded is non-trivial. That is the causal chain this arm is testing.

## Watch out

- **Read this before committing effort.** Our current `PREMATURE_STOP` count is only 3 of
  88, because 93% of failures die at the *budget*, not at an early `done`. So on our
  current data the population this arm targets looks small, and it may show little on its
  own. It becomes far more relevant once arm 0 and arm 1 stop the bleeding at the cap — at
  which point ungated `done` should become the binding failure. Sequence it after arm 0
  reports, and read arm 0's exhaustion number before sizing this work.
- Verification competes with the task for the same step budget. If exhaustion rises sharply
  and success is flat, retry the arm at `MAX_ACTIONS=80` before concluding it failed.
- Don't let the verifier read the agent's own `done` narration — it will happily confirm
  the agent's own summary. Check the page, not the story. This is the documented primary
  source of false positives in this benchmark family.
