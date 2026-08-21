"""Mini-2 capability probe: OM2W tasks validated on strong HAL agents.

Selection rule: must succeed on ≥2 of {SeeAct+GPT-5, SeeAct+Gemini-2.0-Flash, Browser-Use+Gemini-2.0-Flash}.
Keep small — harness comparison with gemini-3.6-flash, not another Hard-20.
"""

from __future__ import annotations

MINI2_TASKS = [
    {
        "task_id": "c0fa2c0e622971955cabf5bcf7b777e8",
        "website": "apartments",
        "start_url": "https://www.apartments.com/",
        "task": "Search for rentals in Corning, CA with a maximum price of $1500.",
        "level": "medium",
        "reference_length": None,
        "hal_validated": {
            "seeact_gpt5": True,
            "seeact_gemini20flash": True,
            "browseruse_gemini20flash": True,
            "seeact_gpt5_steps": 6,
        },
        "why": "Cross-model success (3/3). Location+price filter; medium difficulty.",
    },
    {
        "task_id": "b7a9a6b5d451164c09bbd27b670bc2ae",
        "website": "uniqlo",
        "start_url": "https://www.uniqlo.com/",
        "task": "Show me the list of Men's Blazers, Black, Size M on Uniqlo.",
        "level": "hard",
        "reference_length": 11,
        "hal_validated": {
            "seeact_gpt5": True,
            "seeact_gemini20flash": False,
            "browseruse_gemini20flash": True,
            "seeact_gpt5_steps": 12,
        },
        "why": (
            "Passes SeeAct+GPT-5 and Browser-Use+Gemini. Matches our residual "
            "multi-filter / grounding failure mode on Uniqlo."
        ),
    },
]

MINI2_BY_ID = {t["task_id"]: t for t in MINI2_TASKS}
