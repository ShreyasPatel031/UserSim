"""Domain-agnostic situation + choice options for the human simulator.

Websites are one artifact. Same types cover surveys, A/B creatives,
product prefs, interview answers, stop/continue, etc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

DecisionKind = Literal[
    "choose",  # pick among options (A/B, product, next click id, …)
    "rate",  # Likert / score
    "stop",  # STOP vs CONTINUE
    "free_response",  # short natural-language answer
]


@dataclass
class ChoiceOption:
    id: str
    label: str
    description: str = ""


@dataclass
class Situation:
    """What the person is facing right now."""

    kind: DecisionKind
    # Domain tag for routing / eval splits: survey | marketing | web | interview | …
    domain: str
    # Human-readable scenario
    prompt: str
    # Ordered options (required for choose/stop; optional elsewhere)
    options: list[ChoiceOption] = field(default_factory=list)
    # Prior steps as short strings (clicks, answers, messages)
    history: list[str] = field(default_factory=list)
    # Structured extras (page URL, creative urls, scale anchors, …)
    meta: dict[str, Any] = field(default_factory=dict)
    # For rate: inclusive integer bounds
    scale_min: int = 1
    scale_max: int = 5

    def options_block(self) -> str:
        if not self.options:
            return "(no options)"
        lines = []
        for o in self.options:
            extra = f" — {o.description}" if o.description else ""
            lines.append(f"- [{o.id}] {o.label}{extra}")
        return "\n".join(lines)
