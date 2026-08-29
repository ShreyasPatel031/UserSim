"""Optional study presets for competitive / Bland-style simulations."""

from __future__ import annotations

PERSONA_PRESETS = [
    {
        "id": "p1_ops",
        "name": "Maya Chen",
        "role": "Contact Center Ops Manager",
        "label": "Maya — Ops (call logs, QA, analytics)",
    },
    {
        "id": "p2_fde",
        "name": "Jordan Blake",
        "role": "Solutions Engineer",
        "label": "Jordan — FDE (agents, tools, test loops)",
    },
    {
        "id": "p3_outbound",
        "name": "Priya Nair",
        "role": "Outbound Campaign Lead",
        "label": "Priya — Outbound (numbers, batch, metrics)",
    },
    {
        "id": "p4_eng",
        "name": "Alex Rivera",
        "role": "Platform Engineer",
        "label": "Alex — Eng (API keys, webhooks, config)",
    },
    {
        "id": "p5_compliance",
        "name": "Sam Okonkwo",
        "role": "Compliance & Risk",
        "label": "Sam — Compliance (recordings, privacy, export)",
    },
    {
        "id": "p6_founder",
        "name": "Elena Park",
        "role": "Founder / Head of Product",
        "label": "Elena — Founder (first agent, pricing, onboarding)",
    },
]

COMPETITOR_PRESETS = [
    {"id": "retell", "label": "Retell AI", "url": "https://dashboard.retellai.com/"},
    {"id": "vapi", "label": "Vapi", "url": "https://dashboard.vapi.ai/"},
    {"id": "bland", "label": "Bland AI", "url": "https://app.bland.ai/dashboard"},
]

JOURNEY_PRESETS = [
    {"id": "J1", "label": "J1 — Create agent / rapid setup"},
    {"id": "J2", "label": "J2 — Knowledge / escalation"},
    {"id": "J3", "label": "J3 — Routing / call ops"},
    {"id": "J4", "label": "J4 — Integration / tools"},
    {"id": "J5", "label": "J5 — Testing / simulation / analytics"},
]

# Map journeys → example task themes used to steer generation.
JOURNEY_TASK_HINTS = {
    "J1": "create agent / first pathway, pricing clarity, buy or import a phone number",
    "J2": "knowledge upload, help/docs, QA/triage, team access, privacy settings",
    "J3": "call logs, call detail/transcripts, filters, phone numbers, outbound/batch cues",
    "J4": "API keys, org settings, tools/functions, webhooks, developer-oriented config",
    "J5": "test/simulate call, analytics overview, campaign metrics, voice/persona controls, export",
}
