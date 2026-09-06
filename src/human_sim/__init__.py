"""Classical human behavior simulator (persona → context → decision).

This is the *policy* head: what a person would do / prefer / say next.
Website navigation, cookies, grounding live in `capability/` — a separate head.
"""

from human_sim.engine import HumanSimulator, SimulateResult
from human_sim.persona import Persona, PersonaFacets
from human_sim.situation import ChoiceOption, Situation

__all__ = [
    "ChoiceOption",
    "HumanSimulator",
    "Persona",
    "PersonaFacets",
    "SimulateResult",
    "Situation",
]
