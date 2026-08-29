"""Persona schema — deep sociopsychological seed, not just demographics.

Inspired by SCOPE facets (personality, values, identity, professional context).
Demographics alone explain ~1.5% of behavioral variance; keep them optional.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PersonaFacets:
    """Structured behavioral facets used to condition the simulator."""

    # Big-Five style shorthand (free text or Likert notes are fine)
    personality: str = ""
    # What they optimize for / won't compromise on
    values: str = ""
    # Daily habits, channel preferences, risk / patience
    lifestyle: str = ""
    # Who they are outside the task
    identity: str = ""
    # Role, seniority, constraints at work
    professional: str = ""
    # Explicit goals for *this* simulation episode (optional override)
    episode_goals: str = ""
    # Hard constraints (budget, time, compliance, tech comfort)
    constraints: str = ""


@dataclass
class Persona:
    """One simulated human. Seed from real interviews / SCOPE / CRM; expand at runtime."""

    id: str
    name: str
    # One-line role for prompts
    summary: str
    facets: PersonaFacets = field(default_factory=PersonaFacets)
    # Optional coarse demographics — never the sole conditioner
    demographics: dict[str, Any] = field(default_factory=dict)
    # Provenance: "hand", "scope", "interview", "nemotron+augment", "runtime"
    source: str = "hand"
    # Free-form notes from a real intake / interview
    seed_notes: str = ""

    def to_prompt_block(self) -> str:
        lines = [
            f"PERSONA: {self.name} ({self.id})",
            f"Summary: {self.summary}",
        ]
        if self.demographics:
            demo = ", ".join(f"{k}={v}" for k, v in self.demographics.items())
            lines.append(f"Demographics (weak signal): {demo}")
        f = self.facets
        for label, val in (
            ("Personality", f.personality),
            ("Values", f.values),
            ("Lifestyle / habits", f.lifestyle),
            ("Identity", f.identity),
            ("Professional context", f.professional),
            ("Episode goals", f.episode_goals),
            ("Hard constraints", f.constraints),
        ):
            if val.strip():
                lines.append(f"{label}: {val.strip()}")
        if self.seed_notes.strip():
            lines.append(f"Seed notes: {self.seed_notes.strip()}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Persona:
        facets_raw = data.get("facets") or {}
        facets = PersonaFacets(**{k: facets_raw.get(k, "") for k in PersonaFacets.__dataclass_fields__})
        return cls(
            id=str(data["id"]),
            name=str(data.get("name") or data["id"]),
            summary=str(data.get("summary") or ""),
            facets=facets,
            demographics=dict(data.get("demographics") or {}),
            source=str(data.get("source") or "hand"),
            seed_notes=str(data.get("seed_notes") or ""),
        )
