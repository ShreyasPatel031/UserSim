"""Scoreboard maths shared by the bakeoff runners and the offline re-judge.

Three rates, because one number hides the thing that bit us: a run the judge
could not score is not a run the model failed.

  success_rate_eligible  SUCCESS / (everything except env blocks)   - pessimistic
  success_rate_scored    SUCCESS / (SUCCESS + FAILURE)              - decision metric
  judge_error_rate       unscoreable / n                            - must be 0

Compare configurations on `success_rate_scored`, and only trust the comparison
when `judge_error_rate` is 0.
"""

from __future__ import annotations

from collections import Counter

from capability.judge import JUDGE_ERROR

# Outcomes caused by the environment or the harness, not by model behaviour.
NON_MODEL_STATUSES = frozenset({"BLOCKED", "SITE_CHANGED", JUDGE_ERROR})


def _sort_key(run: dict):
    """Order runs by eval_index, tolerating the string indices used by mini2."""
    idx = run.get("eval_index")
    return (0, idx, "") if isinstance(idx, int) else (1, 0, str(idx))


def summarize(runs: list[dict]) -> dict:
    n = len(runs)
    eligible = [r for r in runs if r.get("status") not in NON_MODEL_STATUSES]
    scoreable = [r for r in runs if r.get("status") in {"SUCCESS", "FAILURE"}]
    judge_errors = [r for r in runs if r.get("status") == JUDGE_ERROR]

    ok_eligible = sum(1 for r in eligible if r.get("success"))
    ok_scored = sum(1 for r in scoreable if r.get("success"))

    return {
        "n": n,
        "n_eligible": len(eligible),
        "n_scored": len(scoreable),
        "successes": sum(1 for r in runs if r.get("success")),
        "successes_eligible": ok_eligible,
        "success_rate_eligible": round(ok_eligible / max(1, len(eligible)), 4),
        "success_rate_scored": round(ok_scored / max(1, len(scoreable)), 4),
        "judge_errors": len(judge_errors),
        "judge_error_rate": round(len(judge_errors) / max(1, n), 4),
        "by_status": dict(Counter(r.get("status") for r in runs)),
        "by_failure_category": dict(
            Counter(r.get("failure_category") for r in runs if not r.get("success"))
        ),
        "total_cost_usd": round(sum(float(r.get("estimated_cost_usd") or 0) for r in runs), 4),
    }


def sort_runs(runs: list[dict]) -> list[dict]:
    return sorted(runs, key=_sort_key)
