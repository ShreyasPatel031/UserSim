# AGENTS.md — rules for any agent working in this repo

## Definition of done (FM baselines / beat_behavior_fms)

`docs/plans/gates.yaml` is the definition of done. If it and the prose in
`docs/plans/beat_behavior_fms.md` disagree, **the YAML wins**.

A gate is met **only** when this exits 0:

```bash
python scripts/gates/verify.py --gate N
```

Your claim that a gate passed **must include that command's output**. Never assert
a gate from reading logs, `STATUS.md`, chat summaries, or a hand-written note.

Unknown / undefined gates (`status: pending_definition` in the contract) are
**FAIL**, never pass. Do not invent numeric criteria to "close" them.

## Generated files — do not edit by hand

These are overwritten by the verifier. Hand edits are forbidden and will be lost:

- `results/fm_baselines/STATUS.md`
- `results/fm_baselines/SUMMARY.md`
- `results/gates/gate*.json`

If status looks wrong, fix artifacts or the contract, then re-run `verify.py`.

## Smoke / partial runs

A smoke or subset run is a **labeled precursor**. It never closes a Gate 0
checklist item.

- Subsetting requires `ALLOW_PARTIAL=1` (enforced by eval scripts).
- Partial runs write `PARTIAL.<reason>.json`, never `SUMMARY.json`.
- The verifier only accepts `SUMMARY.json` with `coverage.complete: true`.

If you subset, say so in the **same sentence** you report the number
(e.g. "smoke: 2/40 studies, W=0.184 — not Gate 0").

## Commit before you leave

Uncommitted work under `scripts/` has already been lost to branch checkouts.
Before ending a turn that creates or modifies scripts, commit them (or at
minimum leave them staged and tell the user). Prefer committing gate/contract
changes with the verifier in the same commit.

## Phase 0 scope (current)

- Required: Minitaur Psych-101-test NLL (6561 items), Socrates-14B SocSci210
  Wasserstein (40 unseen studies), Be.FM-1.5-4B **full** BehaviorBench
  (all `DEFAULT_DATA_PATHS` tasks — currently 39).
- Skipped by contract: Centaur-70B.
- Be.FM "8-task subset" is **not** Gate 0. Do not call it done.

## Quick verify

```bash
python scripts/gates/verify.py --gate 0
# expect exit 1 until full reproductions exist; that is correct
```
