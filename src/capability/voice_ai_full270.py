"""Full270 matched-triplet persona × journey × seed × platform study.

Design
------
6 personas × 5 shared journeys × 3 seeds × 3 platforms = 270 sessions.

Fan-out is primarily over tasks (journeys). Personas are fully crossed so we
can estimate platform, task, persona, and interaction effects.

Matched block: (persona, journey, seed) → Bland + Retell + Vapi launched with
identical prompt text (platform name/nav hints differ only).

Journeys 2–5 start from a prepared baseline agent (existing agent in the
console) so Task-1 create failures do not contaminate the rest.

Reserve ~30 sessions outside this set for invalid replacements and predefined
robustness reruns — do not casually add extra cells mid-study.
"""

from __future__ import annotations

from dataclasses import dataclass

from capability.voice_ai_personas import (
    PLATFORM_HINTS,
    PLATFORM_HOME,
    PLATFORMS,
    Persona,
)

# Personas mapped to the six buyer types in the full270 brief.
PERSONAS_270: tuple[Persona, ...] = (
    Persona(
        id="p1_owner",
        name="Elena Park",
        role="Nontechnical business owner",
        company="Early-stage consumer startup evaluating vendors this week",
        goal="Pick a platform she can demo without engineering help",
        cares_about=("time-to-first-agent", "templates", "pricing clarity", "onboarding", "numbers"),
    ),
    Persona(
        id="p2_cx_ops",
        name="Maya Chen",
        role="CX operations manager",
        company="Regional multi-clinic healthcare group",
        goal="Keep inbound voice reliable and QA bad calls quickly",
        cares_about=("call quality", "transcripts", "escalation", "filters", "time-to-insight"),
    ),
    Persona(
        id="p3_revops",
        name="Priya Nair",
        role="Revenue operations manager",
        company="Fintech collections + appointment reminder ops",
        goal="Stand up outbound + routing that sales/CS can operate",
        cares_about=("routing", "handoffs", "campaigns", "reporting", "answer rates"),
    ),
    Persona(
        id="p4_designer",
        name="Jordan Blake",
        role="Conversation designer",
        company="Voice AI vendor partner (implements for enterprise)",
        goal="Design clear intents, knowledge bounds, and testable flows",
        cares_about=("builder UX", "intents", "knowledge", "simulation", "versioning"),
    ),
    Persona(
        id="p5_integrator",
        name="Alex Rivera",
        role="Integration developer",
        company="Series B marketplace building voice into product",
        goal="Wire APIs/webhooks and structured outputs cleanly",
        cares_about=("API keys", "webhooks", "variables", "tools", "org settings"),
    ),
    Persona(
        id="p6_admin",
        name="Sam Okonkwo",
        role="Enterprise administrator",
        company="Consumer lending / regulated fintech",
        goal="Ship a compliant, operable agent with auditability",
        cares_about=("access controls", "analytics", "recordings", "billing", "stability"),
    ),
)

PERSONA_BY_ID_270 = {p.id: p for p in PERSONAS_270}

SEEDS: tuple[int, ...] = (1, 2, 3)

NEUTRAL_BRIEF = (
    "Acme Clinic Reminders: an inbound line that confirms appointments, answers "
    "hours/location FAQs from a knowledge base, escalates billing questions to a human, "
    "and after hours takes a callback message."
)

MOCK_WEBHOOK = "https://httpbin.org/post"


@dataclass(frozen=True)
class Journey:
    key: str
    title: str
    ord: int  # 1..5
    uses_baseline_agent: bool
    user_goal: str
    success_criteria: str
    hint_key: str
    validator_id: str
    max_actions: int = 40


JOURNEYS: tuple[Journey, ...] = (
    Journey(
        key="j1_rapid_setup",
        title="Rapid setup — inbound agent from brief",
        ord=1,
        uses_baseline_agent=False,
        user_goal=(
            f"Create an inbound voice agent/assistant/pathway from this neutral business brief "
            f"(templates and built-in AI assistants ARE allowed — they are part of the product UX):\n"
            f"BRIEF: {NEUTRAL_BRIEF}\n"
            f"Prepare it far enough that it looks deployable (name + prompt/instructions + voice or "
            f"model defaults). Do NOT place a live phone call. Do NOT buy numbers unless required "
            f"to reach the create UI; prefer stopping on the configured agent editor."
        ),
        success_criteria=(
            "SUCCESS if an agent/assistant/pathway editor is open with the brief reflected in "
            "name and/or system prompt/instructions (draft OK). Not stuck on login. "
            "Publishing/go-live is optional."
        ),
        hint_key="create_agent",
        validator_id="rapid_setup",
        max_actions=45,
    ),
    Journey(
        key="j2_knowledge_support",
        title="Knowledge support — KB + boundaries + escalation",
        ord=2,
        uses_baseline_agent=True,
        user_goal=(
            "Start from an EXISTING baseline agent/assistant/pathway (open the first usable one "
            "in the list — do not create a brand-new agent from scratch). "
            "Locate knowledge-base / documents / FAQ grounding. Configure or clearly stage: "
            "(1) answer boundaries / when not to invent answers, "
            "(2) escalation or handoff behavior for out-of-scope questions. "
            "If upload requires a local file you do not have, reach the upload UI and describe "
            "what you would attach. Do not place live calls."
        ),
        success_criteria=(
            "SUCCESS if you are inside an existing agent's config AND you reached knowledge/docs "
            "and/or escalation/handoff settings (or documented which are missing after searching). "
            "Not a fresh create-from-scratch flow."
        ),
        hint_key="knowledge",
        validator_id="knowledge_support",
        max_actions=40,
    ),
    Journey(
        key="j3_logic_routing",
        title="Logic and routing — intents, transfer, after-hours",
        ord=3,
        uses_baseline_agent=True,
        user_goal=(
            "Start from an EXISTING baseline agent (open first usable agent — do not create new). "
            "Build or locate intent-based routing / branching that covers: "
            "(1) route/transfer to a human for billing or escalation intents, "
            "(2) an after-hours / closed fallback (message or voicemail-style path). "
            "Prefer editing pathways/flows/nodes over deleting production config. No live calls."
        ),
        success_criteria=(
            "SUCCESS if inside an existing agent flow/builder AND you opened or edited routing/"
            "intent/transfer/after-hours controls (or clearly documented absence after searching)."
        ),
        hint_key="agents",
        validator_id="logic_routing",
        max_actions=45,
    ),
    Journey(
        key="j4_integration",
        title="Integration — mock webhook + variables + structured output",
        ord=4,
        uses_baseline_agent=True,
        user_goal=(
            "Start from an EXISTING baseline agent. Configure integration pieces: "
            f"(1) a tool/webhook/custom function pointing at mock API {MOCK_WEBHOOK}, "
            "(2) at least one dynamic variable / slot, "
            "(3) structured output / JSON schema / extractable fields if the product supports it. "
            "Do not create new API keys if avoidable; use existing tool UI. No live calls."
        ),
        success_criteria=(
            "SUCCESS if inside an existing agent AND you reached tools/webhooks/functions UI and "
            "attempted or staged mock webhook + variable/structured-output config "
            "(or documented which pieces are missing)."
        ),
        hint_key="tools",
        validator_id="integration",
        max_actions=45,
    ),
    Journey(
        key="j5_testing_debug",
        title="Testing and debugging — simulate, diagnose, analytics",
        ord=5,
        uses_baseline_agent=True,
        user_goal=(
            "Start from an EXISTING baseline agent. Use available text/simulation/test-call/"
            "playground tooling (not a real customer call). "
            "Diagnose a seeded failure scenario: the agent invents clinic hours instead of using KB "
            "or fails to escalate billing — reproduce via simulator if possible, note the fix you "
            "would make, then open analytics/call-logs/insights to inspect how failures would show up. "
            "Do not place live outbound calls to real numbers."
        ),
        success_criteria=(
            "SUCCESS if you opened test/simulate UI on an existing agent AND reached an analytics "
            "or call-log/insights surface (or documented which are missing after searching)."
        ),
        hint_key="analytics",
        validator_id="testing_debug",
        max_actions=40,
    ),
)

JOURNEY_BY_KEY = {j.key: j for j in JOURNEYS}


def _eval_index(persona_ord: int, journey_ord: int, seed: int, platform: str) -> int:
    """20000 + persona*1000 + journey*100 + seed*10 + platform → unique, stable.

    persona_ord 0..5, journey_ord 1..5, seed 1..3, platform bland/vapi/retell.
    """
    plat_off = {"bland": 1, "vapi": 2, "retell": 3}[platform]
    return 20000 + persona_ord * 1000 + journey_ord * 100 + seed * 10 + plat_off


def _block_id(persona_id: str, journey_key: str, seed: int) -> str:
    return f"{persona_id}__{journey_key}__s{seed}"


def build_full270_task(
    persona: Persona,
    journey: Journey,
    platform: str,
    *,
    persona_ord: int,
    seed: int,
) -> dict:
    home = PLATFORM_HOME[platform]
    hint = PLATFORM_HINTS.get(journey.hint_key, {}).get(platform, "")
    platform_name = {"bland": "Bland AI", "vapi": "Vapi", "retell": "Retell AI"}[platform]
    baseline = (
        "BASELINE: Open an EXISTING agent/assistant/pathway first (do not create a new one). "
        "If the account has zero agents, stop on the empty list/create CTA and report that "
        "baseline is missing — do not invent a full create flow for journeys 2–5.\n"
        if journey.uses_baseline_agent
        else "BASELINE: Creating a new agent is expected for this journey.\n"
    )
    task_text = (
        f"PERSONA: {persona.name} — {persona.role} at {persona.company}.\n"
        f"Context: {persona.goal}. You care about: {', '.join(persona.cares_about)}.\n"
        f"PLATFORM: {platform_name} product console (you are already signed in).\n"
        f"MATCHED BLOCK: {_block_id(persona.id, journey.key, seed)} (seed={seed}). "
        f"Same persona/journey/seed runs on Bland, Vapi, and Retell for comparison.\n"
        f"JOURNEY {journey.ord}/5: {journey.title}\n"
        f"{baseline}"
        f"USER GOAL: {journey.user_goal}\n"
        f"SUCCESS: {journey.success_criteria}\n"
        f"Nav hint (optional): {hint}\n"
        f"Rules: Do not delete API keys, do not change billing plans, do not place live phone calls "
        f"to real numbers. Templates and built-in AI assistants are allowed. "
        f"When done, in your final answer include: (1) what you accomplished, "
        f"(2) 2–4 things you LIKED about {platform_name}'s UX for this journey, "
        f"(3) 2–4 things you DISLIKED or found confusing, "
        f"(4) how hard this felt (easy/medium/hard), "
        f"(5) whether you used a template/AI assist (yes/no)."
    )
    return {
        "task_id": f"{journey.key}_{persona.id}_s{seed}_{platform}",
        "eval_index": _eval_index(persona_ord, journey.ord, seed, platform),
        "website": platform,
        "domain": "voice_ai_full270",
        "persona_id": persona.id,
        "persona_name": persona.name,
        "persona_role": persona.role,
        "journey_key": journey.key,
        "journey_title": journey.title,
        "journey_ord": journey.ord,
        "seed": seed,
        "goal_key": journey.key,
        "goal_title": journey.title,
        "comparative_group": _block_id(persona.id, journey.key, seed),
        "matched_block": _block_id(persona.id, journey.key, seed),
        "validator_id": journey.validator_id,
        "uses_baseline_agent": journey.uses_baseline_agent,
        "task": task_text,
        "start_url": home,
        "human_n_steps": journey.max_actions,
        "human_actions": [],
        "max_actions_hint": journey.max_actions,
    }


def all_full270_tasks(
    *,
    platforms: list[str] | None = None,
    persona_ids: list[str] | None = None,
    journey_keys: list[str] | None = None,
    seeds: list[int] | None = None,
) -> list[dict]:
    """Emit tasks in matched-triplet order: for each (persona, journey, seed) → bland,vapi,retell."""
    platforms = platforms or list(PLATFORMS)
    seeds = seeds or list(SEEDS)
    out: list[dict] = []
    for p_ord, persona in enumerate(PERSONAS_270):
        if persona_ids and persona.id not in persona_ids:
            continue
        for journey in JOURNEYS:
            if journey_keys and journey.key not in journey_keys:
                continue
            for seed in seeds:
                for platform in platforms:
                    out.append(
                        build_full270_task(
                            persona,
                            journey,
                            platform,
                            persona_ord=p_ord,
                            seed=seed,
                        )
                    )
    return out


def load_full270_stage(stage: str) -> list[dict]:
    """Stages:
    - product_full270              → all 270
    - product_full270_bland|vapi|retell → 90 for one platform
    - product_full270_j1 .. j5     → one journey × all personas × seeds × platforms
    - product_full270_smoke        → 1 persona × 1 journey × 1 seed × 3 platforms (triad smoke)
    """
    if stage == "product_full270":
        return all_full270_tasks()
    if stage == "product_full270_smoke":
        return all_full270_tasks(
            persona_ids=["p2_cx_ops"],
            journey_keys=["j1_rapid_setup"],
            seeds=[1],
        )
    if stage in {f"product_full270_{p}" for p in PLATFORMS}:
        plat = stage.rsplit("_", 1)[-1]
        return all_full270_tasks(platforms=[plat])
    if stage.startswith("product_full270_j") and stage[-1].isdigit():
        n = int(stage[-1])
        if not 1 <= n <= len(JOURNEYS):
            raise ValueError(stage)
        return all_full270_tasks(journey_keys=[JOURNEYS[n - 1].key])
    raise ValueError(f"Unknown full270 stage: {stage}")


def full270_summary() -> dict:
    tasks = all_full270_tasks()
    by_plat = {p: sum(1 for t in tasks if t["website"] == p) for p in PLATFORMS}
    return {
        "n": len(tasks),
        "personas": len(PERSONAS_270),
        "journeys": len(JOURNEYS),
        "seeds": len(SEEDS),
        "platforms": list(PLATFORMS),
        "per_platform": by_plat,
        "matched_blocks": len(PERSONAS_270) * len(JOURNEYS) * len(SEEDS),
        "reserve_sessions_guidance": 30,
    }
