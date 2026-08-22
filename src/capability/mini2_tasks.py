"""Mini-2 capability probe: OM2W tasks validated on strong HAL agents.

Selection rules:
1. Succeed on ≥2 of {SeeAct+GPT-5, SeeAct+Gemini-2.0-Flash, Browser-Use+Gemini-2.0-Flash}.
2. Start URL must load from our cloud IP (no Akamai/CAPTCHA wall on first paint).

Dropped (HAL-valid but blocked here): apartments.com, uniqlo.com — both return
Akamai Access Denied from this environment (Mini-2 attempt 1, both harnesses BLOCKED).

Keep small — harness comparison with gemini-2.5-flash, not another Hard-20.
"""

from __future__ import annotations

MINI2_TASKS = [
    {
        "task_id": "c698ff3fc0f6cbce39947c597ab5749b",
        "website": "eventbrite",
        "start_url": "https://www.eventbrite.com/",
        "task": "Browse the page with event planning tips on Eventbrite.",
        "level": "easy",
        "reference_length": None,
        "hal_validated": {
            "seeact_gpt5": True,
            "seeact_gemini20flash": True,
            "browseruse_gemini20flash": True,
        },
        "why": (
            "Cross-model success (3/3). Easy nav task; Eventbrite loads from cloud IP "
            "(also SUCCESS in our full100 Flash live set)."
        ),
    },
    {
        "task_id": "b320c68bffc1f3c7f2a8dc9d5478fb27",
        "website": "ign",
        "start_url": "https://www.ign.com/",
        "task": 'Find a walkthrough for the game "The Legend of Zelda: Breath of the Wild" on ign.',
        "level": "medium",
        "reference_length": None,
        "hal_validated": {
            "seeact_gpt5": True,
            "seeact_gemini20flash": False,
            "browseruse_gemini20flash": True,
        },
        "why": (
            "Passes SeeAct+GPT-5 and Browser-Use+Gemini (2/3). Medium search→content task; "
            "IGN loads from cloud IP (SUCCESS site in full100 Flash)."
        ),
    },
]

MINI2_BY_ID = {t["task_id"]: t for t in MINI2_TASKS}
