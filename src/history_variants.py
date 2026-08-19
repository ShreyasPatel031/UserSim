"""History ablations for UserSim v0.1. Same step, different information in the history slot."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

from model import DEFAULT_HISTORY_HEADING

ACTION_RE = re.compile(
    r"\[(?P<tag>[^\]]*)\]\s*(?P<name>.*?)\s*->\s*(?P<op>CLICK|TYPE|SELECT)(?::\s*(?P<value>.*))?$",
    re.I,
)

OTHER_HEADING = DEFAULT_HISTORY_HEADING  # do not leak that this is a different task
LAST_HEADING = DEFAULT_HISTORY_HEADING
SHUFFLED_HEADING = DEFAULT_HISTORY_HEADING
BEHAVIORAL_HEADING = (
    "This person's previous action types on this task "
    "(element names and typed/selected values omitted):"
)
SUMMARY_HEADING = (
    "Reconstructed task progress so far. This is a state summary, "
    "not the click-by-click UI trace:"
)


@dataclass(frozen=True)
class HistorySpec:
    items: list[str]
    heading: str
    number: bool = True


def parse_repr(raw: str) -> dict:
    match = ACTION_RE.search((raw or "").strip())
    if not match:
        return {"tag": "", "name": "", "op": "", "value": "", "raw": raw}
    return {
        "tag": (match.group("tag") or "").strip(),
        "name": (match.group("name") or "").strip(),
        "op": (match.group("op") or "").strip().upper(),
        "value": (match.group("value") or "").strip(),
        "raw": raw,
    }


def correct(history: list[str]) -> HistorySpec:
    return HistorySpec(list(history), DEFAULT_HISTORY_HEADING)


def last_only(history: list[str]) -> HistorySpec:
    return HistorySpec(history[-1:] if history else [], LAST_HEADING)


def shuffled(history: list[str], seed: str) -> HistorySpec:
    items = list(history)
    random.Random(f"shuffle:{seed}").shuffle(items)
    return HistorySpec(items, SHUFFLED_HEADING)


def behavioral_only(history: list[str]) -> HistorySpec:
    items = []
    for raw in history:
        parsed = parse_repr(raw)
        op = parsed["op"] or "UNKNOWN"
        items.append(op)
    return HistorySpec(items, BEHAVIORAL_HEADING)


def progress_summary(history: list[str], step_index: int, n_steps: int) -> HistorySpec:
    if not history:
        return HistorySpec([], SUMMARY_HEADING, number=False)
    filled: list[str] = []
    clicked: list[str] = []
    for raw in history:
        parsed = parse_repr(raw)
        label = parsed["name"] or parsed["tag"] or "a control"
        if parsed["op"] in {"TYPE", "SELECT"} and parsed["value"]:
            filled.append(f"{label} = {parsed['value']}")
        elif parsed["op"] == "CLICK":
            clicked.append(label)
        elif parsed["op"]:
            clicked.append(f"{parsed['op']} {label}".strip())
    lines = [
        f"The user is partway through the task (about {step_index + 1} of {n_steps} actions).",
        "What has already been accomplished:",
    ]
    if filled:
        lines.append("- Constraints / fields already set: " + "; ".join(filled))
    if clicked:
        shown = clicked[:10]
        extra = f" (+{len(clicked) - 10} more)" if len(clicked) > 10 else ""
        lines.append("- Other UI targets already used: " + "; ".join(shown) + extra)
    if not filled and not clicked:
        lines.append("- Prior actions were taken, but they could not be parsed into slots.")
    lines.append("Do not treat this as an ordered click trace.")
    return HistorySpec(["\n".join(lines)], SUMMARY_HEADING, number=False)


def other_trajectory(
    history_len: int,
    annotation_id: str,
    website: str,
    step_index: int,
    catalog: list[dict],
) -> HistorySpec:
    """Same length as true history, drawn from a different trajectory (prefer other site)."""
    others = [t for t in catalog if t["annotation_id"] != annotation_id]
    rng = random.Random(f"other:{annotation_id}:{step_index}")
    diff_site = [t for t in others if t["website"] != website]
    pool = diff_site or others
    src = rng.choice(pool)
    if history_len <= 0:
        return HistorySpec([], OTHER_HEADING)
    reprs = list(src["action_reprs"] or [])
    items = reprs[:history_len] if reprs else []
    return HistorySpec(items, OTHER_HEADING)
