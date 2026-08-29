"""Prompt templates for classical human simulation (not task-completion agents)."""

from __future__ import annotations

from human_sim.persona import Persona
from human_sim.situation import Situation

SYSTEM = """You are a classical human behavior simulator.
You answer as ONE specific person described in the persona block.
You are not a helpful assistant and not a task-completion agent.
Optimize for what THIS person would actually do, prefer, or say — including impatience, satisficing, risk aversion, and incomplete information.
When uncertain, pick the most likely human response for this persona, not the objectively best answer.
Return JSON only."""


def build_user_prompt(persona: Persona, situation: Situation) -> str:
    hist = situation.history
    hist_block = "\n".join(f"{i+1}. {h}" for i, h in enumerate(hist)) if hist else "(none)"

    parts = [
        persona.to_prompt_block(),
        "",
        f"DOMAIN: {situation.domain}",
        f"DECISION KIND: {situation.kind}",
        "",
        "SITUATION:",
        situation.prompt.strip(),
        "",
        "HISTORY (earlier actions / answers):",
        hist_block,
    ]

    if situation.kind == "choose":
        parts += [
            "",
            "OPTIONS:",
            situation.options_block(),
            "",
            'Respond JSON: {"choice_id": "<id from options>", "confidence": <0-1>, "rationale": "<one short sentence in first person>"}',
        ]
    elif situation.kind == "stop":
        parts += [
            "",
            "OPTIONS:",
            situation.options_block()
            or "- [CONTINUE] keep going\n- [STOP] stop now",
            "",
            'Respond JSON: {"choice_id": "STOP"|"CONTINUE", "confidence": <0-1>, "rationale": "<one short sentence in first person>"}',
        ]
    elif situation.kind == "rate":
        parts += [
            "",
            f"Scale: integer from {situation.scale_min} to {situation.scale_max} inclusive.",
            "",
            f'Respond JSON: {{"rating": <int>, "confidence": <0-1>, "rationale": "<one short sentence in first person>"}}',
        ]
    else:  # free_response
        parts += [
            "",
            'Respond JSON: {"text": "<what this person would say>", "confidence": <0-1>, "rationale": "<one short sentence why>"}',
        ]

    if situation.meta:
        parts += ["", f"META: {situation.meta}"]

    return "\n".join(parts)
