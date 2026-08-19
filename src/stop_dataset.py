"""Teacher-forced STOP/CONTINUE labels on full Mind2Web trajectories.

The v0 next-action eval truncated at 8 steps. That would mislabel STOP for
any longer demonstration, so v0.5 uses every action of the same 40 tasks.
"""

from __future__ import annotations

import json
import random
import re

from config import MAX_TRAJECTORIES, N_CANDIDATES, SLIM_JSON
from elements import element_repr
from eval_offline import sample_candidates

AGENT_SYSTEM = """You are a web agent. Your goal is to successfully complete the user's task.
After the most recent action, decide whether you still need to interact with the website to finish the task, or whether the task is already finished.
Reply STOP only if the task is complete. If more interaction could help complete the task, reply CONTINUE.
Return JSON only."""

HUMAN_SYSTEM = """You simulate a normal human using a public website.
Predict whether that person would continue interacting or stop after the most recent action.
Do not optimize for task completion. Humans often stop as soon as they believe they have done enough, even if a more thorough agent would keep going.
Return JSON only."""

USER_TAIL = (
    "After taking the most recent action, should the interaction CONTINUE or STOP?\n"
    'Respond as JSON: {"decision": "STOP"|"CONTINUE", "p_stop": <number from 0 to 1>}\n'
    "p_stop is your probability that the correct decision is STOP. "
    "If decision is CONTINUE, p_stop must be < 0.5. If STOP, p_stop must be >= 0.5."
)

LEAK_PATTERNS = [
    re.compile(r"\bfinal\b", re.I),
    re.compile(r"\bterminal\b", re.I),
    re.compile(r"\blast (step|action|logged)\b", re.I),
    re.compile(r"\bis_last\b", re.I),
    re.compile(r"\bstop label\b", re.I),
    re.compile(r"\b\d+\s*/\s*\d+\b"),
    re.compile(r"\bstep \d+ of \d+\b", re.I),
]


def load_tasks() -> list[dict]:
    return json.loads(SLIM_JSON.read_text())[:MAX_TRAJECTORIES]


def _candidates_for(action: dict, seed: str) -> list[str]:
    rng = random.Random(seed)
    pos = list(action.get("pos_candidates") or [])
    neg = list(action.get("neg_candidates") or [])
    if pos:
        mixed = sample_candidates(
            {"pos_candidates": pos, "neg_candidates": neg}, rng
        )
        return [element_repr(c) for c in mixed]
    if not neg:
        return []
    take = min(N_CANDIDATES, len(neg))
    picked = rng.sample(neg, take) if len(neg) > take else neg
    return [element_repr(c) for c in picked]


def load_stop_steps() -> list[dict]:
    steps = []
    for task in load_tasks():
        actions = task.get("actions") or []
        reprs = task.get("action_reprs") or []
        n = len(actions)
        hist: list[str] = []
        for i, action in enumerate(actions):
            gold_repr = reprs[i] if i < len(reprs) else None
            if gold_repr:
                hist.append(gold_repr)
            elif (action.get("operation") or {}).get("op"):
                op = action["operation"]
                hist.append(f"{op.get('op')} {op.get('value') or ''}".strip())
            steps.append(
                {
                    "annotation_id": task["annotation_id"],
                    "website": task["website"],
                    "domain": task.get("domain"),
                    "task": task["confirmed_task"],
                    "step_index": i,
                    "n_steps": n,
                    "is_terminal": i == n - 1,
                    "label": "STOP" if i == n - 1 else "CONTINUE",
                    "history": list(hist),
                    "gold_op": (action.get("operation") or {}).get("op") or "CLICK",
                    "gold_repr": hist[-1] if hist else "",
                    "candidate_reprs": _candidates_for(
                        action, f"stop:{task['annotation_id']}:{i}"
                    ),
                }
            )
    return steps


def build_user_prompt(step: dict) -> str:
    lines = [
        f"TASK\n{step['task']}",
        "",
        f"WEBSITE\n{step['website']}",
        "",
        "CURRENT PAGE CONTEXT",
    ]
    if step["candidate_reprs"]:
        for i, cand in enumerate(step["candidate_reprs"], start=1):
            lines.append(f"{i}. {cand}")
    else:
        lines.append("No interactive elements extracted for this page.")
    lines.append("")
    lines.append("HUMAN ACTION HISTORY")
    if step["history"]:
        for i, h in enumerate(step["history"], start=1):
            lines.append(f"{i}. {h}")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("QUESTION")
    lines.append(USER_TAIL)
    return "\n".join(lines)


def leakage_hits(prompt: str) -> list[str]:
    return [pat.pattern for pat in LEAK_PATTERNS if pat.search(prompt)]


def sanity_check(steps: list[dict]) -> list[str]:
    """Fail only on label bugs or metadata we injected. Page text may contain
    'terminal' or '3 / 5' as real UI copy; that is not leakage."""
    errors: list[str] = []
    by_traj: dict[str, list[dict]] = {}
    for s in steps:
        by_traj.setdefault(s["annotation_id"], []).append(s)

    if len(by_traj) != MAX_TRAJECTORIES:
        errors.append(f"expected {MAX_TRAJECTORIES} trajectories, got {len(by_traj)}")

    for tid, rows in by_traj.items():
        rows = sorted(rows, key=lambda r: r["step_index"])
        labels = [r["label"] for r in rows]
        if labels.count("STOP") != 1:
            errors.append(f"{tid}: STOP count={labels.count('STOP')}")
        if any(r["label"] != "CONTINUE" for r in rows[:-1]):
            errors.append(f"{tid}: non-final CONTINUE violation")
        if rows[-1]["label"] != "STOP" or not rows[-1]["is_terminal"]:
            errors.append(f"{tid}: last label is not STOP")
        if rows[-1]["n_steps"] != len(rows):
            errors.append(f"{tid}: n_steps mismatch")
        if any(r["is_terminal"] for r in rows[:-1]):
            errors.append(f"{tid}: is_terminal on a non-final step")
        for r in rows:
            if r["gold_repr"] and (not r["history"] or r["history"][-1] != r["gold_repr"]):
                errors.append(f"{tid} step {r['step_index']}: history missing current action")

    sample = build_user_prompt(steps[0])
    if "successfully complete" in sample.lower() or "normal human" in sample.lower():
        errors.append("framing leaked into user prompt")
    injected = [
        "is_terminal",
        '"final": true',
        "final: true",
        "stop label",
        "this is the last",
        "last logged",
    ]
    for s in steps:
        prompt = build_user_prompt(s)
        low = prompt.lower()
        for needle in injected:
            if needle in low:
                errors.append(f"injected leak '{needle}'")
        if re.search(rf"\b{s['step_index'] + 1}\s*/\s*{s['n_steps']}\b", prompt):
            errors.append("explicit k/n progress leaked")
        if f"step {s['step_index'] + 1} of {s['n_steps']}" in low:
            errors.append("step i of n leaked")

    agent_tail = USER_TAIL
    if "successfully complete" in agent_tail.lower():
        errors.append("agent framing in shared question")
    return errors
