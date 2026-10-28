"""simcore: domain-agnostic user simulation. A domain adapter supplies Contexts (who may show up, what they can see,
how likely each person is to pick each option); the core simulates exposure, choice and herding, and reports per-item
exposure and expected outcomes. Product Hunt is the first adapter (adapters/producthunt.py)."""
from .core import Context, simulate, exposure, CHANNELS_DATED
