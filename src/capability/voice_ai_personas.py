"""Persona-driven comparative UX tasks across Bland, Vapi, and Retell.

Primary research target: Bland customers and buyers evaluating Bland vs peers.
Each persona has FIVE unique goals (not shared across personas). Every goal is
run on all three product consoles for comparative analysis.
"""

from __future__ import annotations

from dataclasses import dataclass

PLATFORMS: tuple[str, ...] = ("bland", "vapi", "retell")

PLATFORM_HOME: dict[str, str] = {
    "bland": "https://app.bland.ai/dashboard",
    "vapi": "https://dashboard.vapi.ai/",
    "retell": "https://dashboard.retellai.com/",
}

# Soft nav hints — agents should still explore; hints reduce thrash on unfamiliar UIs.
PLATFORM_HINTS: dict[str, dict[str, str]] = {
    "call_logs": {
        "bland": "Sidebar: Call logs (or Calls).",
        "vapi": "Sidebar: Calls / Call Logs.",
        "retell": "Sidebar: Call History / Calls.",
    },
    "agents": {
        "bland": "Sidebar: Pathways / Agents / Pathways library.",
        "vapi": "Sidebar: Assistants.",
        "retell": "Sidebar: Agents.",
    },
    "create_agent": {
        "bland": "Pathways → Create / New pathway, or Norm builder entry.",
        "vapi": "Assistants → Create Assistant.",
        "retell": "Agents → Create Agent / New Agent.",
    },
    "phone_numbers": {
        "bland": "Sidebar: Phone Numbers / Numbers / Send Call.",
        "vapi": "Sidebar: Phone Numbers.",
        "retell": "Sidebar: Phone Numbers.",
    },
    "analytics": {
        "bland": "Sidebar: Analytics / Insights / Monitor.",
        "vapi": "Sidebar: Analytics / Overview metrics.",
        "retell": "Sidebar: Analytics / Insights.",
    },
    "api_keys": {
        "bland": "Settings / API Keys / Developer.",
        "vapi": "Sidebar: API Keys / Organization settings.",
        "retell": "Sidebar: API Keys / Settings.",
    },
    "billing": {
        "bland": "Settings / Billing / Usage / Plans.",
        "vapi": "Settings / Billing / Usage.",
        "retell": "Settings / Billing / Usage.",
    },
    "tools": {
        "bland": "Tools / Custom tools / Webhooks inside pathway or Tools page.",
        "vapi": "Tools / Functions on an assistant, or Tools library.",
        "retell": "Functions / Custom functions on an agent, or Tools.",
    },
    "settings": {
        "bland": "Account / Settings / Organization.",
        "vapi": "Organization / Settings.",
        "retell": "Settings / Account.",
    },
    "batch": {
        "bland": "Batch / Send Call / Campaign / Outbound.",
        "vapi": "Outbound / Campaign / Batch calls if present.",
        "retell": "Batch Call / Outbound campaign.",
    },
    "knowledge": {
        "bland": "Knowledge / Memory / Documents if present.",
        "vapi": "Knowledge Base / Files on assistant.",
        "retell": "Knowledge Base / Documents.",
    },
    "triage": {
        "bland": "Monitor / Triage / Alerts / Issues.",
        "vapi": "Call detail issues / evaluation / scoring if present.",
        "retell": "Post-call analysis / QA / evaluation if present.",
    },
    "voices": {
        "bland": "Voice settings on pathway / Voices library.",
        "vapi": "Voice / TTS on assistant config.",
        "retell": "Voice / LLM settings on agent.",
    },
    "team": {
        "bland": "Team / Members / Organization settings.",
        "vapi": "Organization / Members / Team.",
        "retell": "Team / Workspace members.",
    },
}


@dataclass(frozen=True)
class Persona:
    id: str
    name: str
    role: str
    company: str
    goal: str
    cares_about: tuple[str, ...]


PERSONAS: tuple[Persona, ...] = (
    Persona(
        id="p1_ops",
        name="Maya Chen",
        role="Contact Center Operations Manager",
        company="Regional multi-clinic healthcare group",
        goal="Keep inbound voice agents reliable; QA every bad call quickly",
        cares_about=("call quality", "transcripts", "filters", "issue triage", "time-to-insight"),
    ),
    Persona(
        id="p2_fde",
        name="Jordan Blake",
        role="Forward-Deployed / Solutions Engineer",
        company="Voice AI vendor partner (implements for enterprise)",
        goal="Stand up production conversational pathways and tool wiring fast",
        cares_about=("builder UX", "branching logic", "tools/webhooks", "test loops", "versioning"),
    ),
    Persona(
        id="p3_outbound",
        name="Priya Nair",
        role="Outbound Campaign Lead",
        company="Fintech collections + appointment reminder ops",
        goal="Launch high-volume outbound with good answer rates and clear reporting",
        cares_about=("phone numbers", "batch dialing", "campaign metrics", "voices", "spam risk"),
    ),
    Persona(
        id="p4_eng",
        name="Alex Rivera",
        role="Platform / Full-stack Engineer",
        company="Series B marketplace building voice into product",
        goal="Ship programmatic agents via API with clean keys, tools, and webhooks",
        cares_about=("API keys", "developer ergonomics", "tools", "webhooks", "org settings"),
    ),
    Persona(
        id="p5_compliance",
        name="Sam Okonkwo",
        role="Compliance & Risk Lead",
        company="Consumer lending / regulated fintech",
        goal="Prove recording access, retention, access controls, and spend visibility",
        cares_about=("recordings", "auditability", "team access", "billing transparency", "privacy"),
    ),
    Persona(
        id="p6_founder",
        name="Elena Park",
        role="Founder / Head of Product",
        company="Early-stage consumer startup evaluating vendors this week",
        goal="Pick a platform she can demo to investors in 48 hours",
        cares_about=("time-to-first-agent", "pricing clarity", "onboarding", "knowledge upload", "numbers"),
    ),
)

PERSONA_BY_ID = {p.id: p for p in PERSONAS}


def _goal(
    *,
    task_key: str,
    title: str,
    user_goal: str,
    success_criteria: str,
    hint_key: str,
    max_actions: int = 18,
) -> dict:
    return {
        "task_key": task_key,
        "title": title,
        "user_goal": user_goal,
        "success_criteria": success_criteria,
        "hint_key": hint_key,
        "max_actions": max_actions,
    }


# Five UNIQUE goals per persona (30 total). None are reused across personas.
PERSONA_GOALS: dict[str, tuple[dict, ...]] = {
    "p1_ops": (
        _goal(
            task_key="p1_t1_call_logs_overview",
            title="Find the call-log / call-history surface",
            user_goal=(
                "As ops, open the main call logs or call history view so I can scan recent "
                "inbound/outbound activity for my agents."
            ),
            success_criteria=(
                "Final URL/page is a call list or history (not login). Visible columns or rows "
                "for calls, or an empty-state that still confirms this is the call-log surface."
            ),
            hint_key="call_logs",
        ),
        _goal(
            task_key="p1_t2_open_call_detail",
            title="Open one call detail with transcript cues",
            user_goal=(
                "Open call logs, then open ANY single call detail (or the empty-state help) and "
                "confirm whether transcript/recording/status fields are visible."
            ),
            success_criteria=(
                "SUCCESS if you open a call detail page with transcript/recording/status, OR if the "
                "account has zero calls and you reach the call-list empty state and clearly report that "
                "no detail rows exist. Not stuck on login."
            ),
            hint_key="call_logs",
            max_actions=22,
        ),
        _goal(
            task_key="p1_t3_filter_or_search_calls",
            title="Find filters/search on call logs",
            user_goal=(
                "On call logs, locate filtering or search (status, date, agent/pathway, direction). "
                "Describe what filter controls exist even if you do not apply them permanently."
            ),
            success_criteria=(
                "You identified filter/search UI on the call-log surface and reported the controls."
            ),
            hint_key="call_logs",
        ),
        _goal(
            task_key="p1_t4_triage_or_qa",
            title="Find QA / triage / evaluation surface",
            user_goal=(
                "Find any triage, monitoring, alerts, evaluation, or QA surface used to flag bad calls."
            ),
            success_criteria=(
                "SUCCESS if final URL/page is any of: triage, monitor, alerts, evals, evaluation, "
                "quality-assurance, QA, scoring — OR call-detail issue/flag UI — OR you clearly "
                "document after searching sidebar that no dedicated QA surface exists. "
                "Do not fail merely because a nested tab did not open."
            ),
            hint_key="triage",
            max_actions=22,
        ),
        _goal(
            task_key="p1_t5_analytics_glance",
            title="Open analytics / insights overview",
            user_goal=(
                "Open an analytics or insights overview useful for weekly ops review "
                "(volume, outcomes, or performance charts)."
            ),
            success_criteria="You are on an analytics/insights page (or empty dashboard) not login.",
            hint_key="analytics",
        ),
    ),
    "p2_fde": (
        _goal(
            task_key="p2_t1_agents_list",
            title="Open agents / assistants / pathways list",
            user_goal="Open the primary list of agents, assistants, or pathways I would edit for a customer.",
            success_criteria="Agents/assistants/pathways list (or empty create CTA) visible; not login.",
            hint_key="agents",
        ),
        _goal(
            task_key="p2_t2_create_agent_entry",
            title="Reach create-agent / create-pathway entry",
            user_goal=(
                "Reach the create flow entry for a new agent/assistant/pathway (do NOT finish "
                "publishing a production agent; stop once the create form/builder is open)."
            ),
            success_criteria="Create/new agent or pathway builder/form is open.",
            hint_key="create_agent",
            max_actions=22,
        ),
        _goal(
            task_key="p2_t3_open_existing_config",
            title="Open an existing agent config if any",
            user_goal=(
                "From the agents list, open an existing agent/assistant/pathway config if one exists; "
                "otherwise stop on the empty list and note the create CTA."
            ),
            success_criteria="Config/editor open OR empty-list create CTA clearly reached.",
            hint_key="agents",
            max_actions=22,
        ),
        _goal(
            task_key="p2_t4_tools_webhooks",
            title="Find tools / functions / webhooks wiring",
            user_goal=(
                "Locate where custom tools, functions, or webhooks are configured for voice agents."
            ),
            success_criteria="Tools/functions/webhooks UI found (global or inside agent) OR documented absent.",
            hint_key="tools",
            max_actions=22,
        ),
        _goal(
            task_key="p2_t5_test_or_simulate",
            title="Find test call / simulation affordance",
            user_goal=(
                "Find a test call, web call, simulation, or playground control used before go-live."
            ),
            success_criteria="Test/simulate UI located on agent or global surface.",
            hint_key="agents",
            max_actions=22,
        ),
    ),
    "p3_outbound": (
        _goal(
            task_key="p3_t1_phone_numbers",
            title="Open phone numbers inventory",
            user_goal="Open the phone numbers page to see owned/imported numbers for outbound.",
            success_criteria="Phone numbers list/buy UI visible; not login.",
            hint_key="phone_numbers",
        ),
        _goal(
            task_key="p3_t2_batch_or_outbound",
            title="Find batch / outbound campaign entry",
            user_goal="Find batch calling, outbound campaign, or send-call campaign entry points.",
            success_criteria=(
                "SUCCESS if batch/outbound/campaign UI is found, OR after searching you clearly document "
                "it is absent (landing on analytics alone is not enough unless you searched for batch)."
            ),
            hint_key="batch",
            max_actions=22,
        ),
        _goal(
            task_key="p3_t3_outbound_in_logs",
            title="See direction/outbound cues in call history",
            user_goal=(
                "Open call history and check whether direction (inbound/outbound) or campaign/batch "
                "metadata is visible or filterable."
            ),
            success_criteria="Reported direction/campaign cues on call history (or absence).",
            hint_key="call_logs",
        ),
        _goal(
            task_key="p3_t4_voice_persona",
            title="Inspect voice / persona controls",
            user_goal="Find voice/TTS/persona controls you would tune for outbound brand voice.",
            success_criteria="Voice settings UI reached (agent-level or library).",
            hint_key="voices",
            max_actions=22,
        ),
        _goal(
            task_key="p3_t5_campaign_metrics",
            title="Find outbound-relevant metrics",
            user_goal=(
                "Find analytics or overview metrics useful for outbound (answer rate, volume, outcomes)."
            ),
            success_criteria=(
                "SUCCESS if analytics/metrics/overview page is reached — empty charts still count. "
                "Do not fail solely because the account has no call volume yet."
            ),
            hint_key="analytics",
        ),
    ),
    "p4_eng": (
        _goal(
            task_key="p4_t1_api_keys",
            title="Locate API keys",
            user_goal="Find the API keys page so I can wire a backend integration.",
            success_criteria="API keys page/list/create UI visible (do not create/delete keys).",
            hint_key="api_keys",
        ),
        _goal(
            task_key="p4_t2_org_settings",
            title="Open organization / account settings",
            user_goal="Open organization or account settings relevant to multi-env setup.",
            success_criteria="Settings/org page reached.",
            hint_key="settings",
        ),
        _goal(
            task_key="p4_t3_tools_for_functions",
            title="Find function/tool registration for code",
            user_goal="Find where assistants register custom functions/tools for live API calls.",
            success_criteria="Tools/functions config found.",
            hint_key="tools",
            max_actions=22,
        ),
        _goal(
            task_key="p4_t4_webhook_or_events",
            title="Find webhooks / event delivery settings",
            user_goal="Find webhook, event, or post-call callback configuration if exposed in UI.",
            success_criteria="Webhook/events UI found OR documented missing after search.",
            hint_key="tools",
            max_actions=22,
        ),
        _goal(
            task_key="p4_t5_assistant_jsonish",
            title="Open assistant config that looks API-editable",
            user_goal=(
                "Open an assistant/agent config and note whether advanced/JSON/model/provider "
                "controls look developer-oriented."
            ),
            success_criteria=(
                "SUCCESS if agent/assistant config is open and you note model/provider/advanced cues, "
                "OR if you opened a closely related developer config surface and reported what you saw. "
                "Do not fail only because the final prose omitted the ease rating."
            ),
            hint_key="agents",
            max_actions=22,
        ),
    ),
    "p5_compliance": (
        _goal(
            task_key="p5_t1_recording_access",
            title="Confirm recording access path from calls",
            user_goal=(
                "From call history/detail, confirm how recordings or transcripts are accessed for audit."
            ),
            success_criteria=(
                "SUCCESS if recording/transcript access path is identified on a call detail, OR if "
                "call history is empty and you clearly report that no recordings exist to open. Not login."
            ),
            hint_key="call_logs",
            max_actions=22,
        ),
        _goal(
            task_key="p5_t2_billing_usage",
            title="Open billing / usage",
            user_goal="Open billing or usage so finance can see spend controls.",
            success_criteria="Billing/usage page reached; not login.",
            hint_key="billing",
        ),
        _goal(
            task_key="p5_t3_team_access",
            title="Find team / members access controls",
            user_goal="Find team members, invites, or role/access controls.",
            success_criteria="Team/members UI found OR documented absent.",
            hint_key="team",
            max_actions=22,
        ),
        _goal(
            task_key="p5_t4_privacy_settings",
            title="Hunt privacy / retention / compliance settings",
            user_goal=(
                "Search settings for privacy, retention, HIPAA/compliance, or data controls. "
                "Report what exists."
            ),
            success_criteria="Compliance/privacy settings found OR thorough absence report.",
            hint_key="settings",
            max_actions=24,
        ),
        _goal(
            task_key="p5_t5_export_or_download",
            title="Find export/download of call data",
            user_goal="On call logs, find export/download of call data if available.",
            success_criteria="Export control found OR clearly absent on call-log surface.",
            hint_key="call_logs",
        ),
    ),
    "p6_founder": (
        _goal(
            task_key="p6_t1_first_agent",
            title="Start first-agent creation",
            user_goal=(
                "As a first-time evaluator, reach the create-agent flow and stop once the form/builder "
                "loads (do not publish)."
            ),
            success_criteria="Create agent/assistant/pathway form or builder open.",
            hint_key="create_agent",
            max_actions=22,
        ),
        _goal(
            task_key="p6_t2_pricing_billing",
            title="Find pricing / plan / billing clarity",
            user_goal="Find billing, plans, or usage that clarifies cost before committing.",
            success_criteria="Billing/plans/usage page reached.",
            hint_key="billing",
        ),
        _goal(
            task_key="p6_t3_buy_or_import_number",
            title="Reach phone number buy/import UI",
            user_goal="Open phone numbers and locate buy/import/connect number actions.",
            success_criteria="Buy/import/connect number affordance visible.",
            hint_key="phone_numbers",
            max_actions=22,
        ),
        _goal(
            task_key="p6_t4_knowledge_upload",
            title="Find knowledge base / docs upload",
            user_goal="Find knowledge base, documents, or FAQ upload for grounding the agent.",
            success_criteria="Knowledge/docs UI found OR documented absent.",
            hint_key="knowledge",
            max_actions=22,
        ),
        _goal(
            task_key="p6_t5_help_onboarding",
            title="Find help / docs / onboarding from console",
            user_goal=(
                "From inside the product console, find Help, Docs, Getting Started, or onboarding tips."
            ),
            success_criteria=(
                "SUCCESS if in-product help/docs/onboarding entry is found, OR after searching sidebar "
                "and settings you clearly document that none exists. Empty search is allowed."
            ),
            hint_key="settings",
            max_actions=22,
        ),
    ),
}


def _eval_index(persona_ord: int, task_ord: int, platform: str) -> int:
    """9100 + persona*100 + task*10 + platform offset → unique, stable."""
    plat_off = {"bland": 1, "vapi": 2, "retell": 3}[platform]
    return 9100 + persona_ord * 100 + task_ord * 10 + plat_off


def build_platform_task(persona: Persona, goal: dict, platform: str, *, persona_ord: int, task_ord: int) -> dict:
    home = PLATFORM_HOME[platform]
    hint = PLATFORM_HINTS.get(goal["hint_key"], {}).get(platform, "")
    platform_name = {"bland": "Bland AI", "vapi": "Vapi", "retell": "Retell AI"}[platform]
    task_text = (
        f"PERSONA: {persona.name} — {persona.role} at {persona.company}.\n"
        f"Context: {persona.goal}. You care about: {', '.join(persona.cares_about)}.\n"
        f"PLATFORM: {platform_name} product console (you are already signed in).\n"
        f"USER GOAL: {goal['user_goal']}\n"
        f"SUCCESS: {goal['success_criteria']}\n"
        f"Nav hint (optional): {hint}\n"
        f"Rules: Do not create/delete API keys, do not place live phone calls, do not change billing. "
        f"Explore read-only. When done, in your final answer include: (1) what you accomplished, "
        f"(2) 2–4 things you LIKED about {platform_name}'s UX for this goal, "
        f"(3) 2–4 things you DISLIKED or found confusing, "
        f"(4) how hard this felt (easy/medium/hard)."
    )
    return {
        "task_id": f"{goal['task_key']}_{platform}",
        "eval_index": _eval_index(persona_ord, task_ord, platform),
        "website": platform,
        "domain": "voice_ai_persona",
        "persona_id": persona.id,
        "persona_name": persona.name,
        "goal_key": goal["task_key"],
        "goal_title": goal["title"],
        "comparative_group": goal["task_key"],
        "task": task_text,
        "start_url": home,
        "human_n_steps": goal.get("max_actions", 18),
        "human_actions": [],
        "max_actions_hint": goal.get("max_actions", 18),
    }


def all_persona_tasks(
    *,
    persona_ids: list[str] | None = None,
    goal_keys: list[str] | None = None,
    platforms: list[str] | None = None,
) -> list[dict]:
    platforms = platforms or list(PLATFORMS)
    out: list[dict] = []
    for p_ord, persona in enumerate(PERSONAS):
        if persona_ids and persona.id not in persona_ids:
            continue
        goals = PERSONA_GOALS[persona.id]
        for t_ord, goal in enumerate(goals, start=1):
            if goal_keys and goal["task_key"] not in goal_keys:
                continue
            for platform in platforms:
                out.append(
                    build_platform_task(persona, goal, platform, persona_ord=p_ord + 1, task_ord=t_ord)
                )
    return out


def load_persona_stage(stage: str) -> list[dict]:
    """stage examples: product_persona | product_persona_p1 | product_persona_p1_t1"""
    if stage == "product_persona":
        return all_persona_tasks()
    if stage.startswith("product_persona_"):
        rest = stage.removeprefix("product_persona_")
        # p1 or p1_t1 or p1_ops_t1 style
        persona_ids = None
        goal_keys = None
        if "_t" in rest:
            left, tpart = rest.rsplit("_t", 1)
            # left may be p1 or p1_ops
            persona = _resolve_persona_token(left)
            task_n = int(tpart)
            goals = PERSONA_GOALS[persona.id]
            if not 1 <= task_n <= len(goals):
                raise ValueError(f"task index out of range: {task_n}")
            persona_ids = [persona.id]
            goal_keys = [goals[task_n - 1]["task_key"]]
        else:
            persona = _resolve_persona_token(rest)
            persona_ids = [persona.id]
        return all_persona_tasks(persona_ids=persona_ids, goal_keys=goal_keys)
    raise ValueError(f"Unknown persona stage: {stage}")


def _resolve_persona_token(token: str) -> Persona:
    token = token.strip()
    if token in PERSONA_BY_ID:
        return PERSONA_BY_ID[token]
    # p1 → first persona
    if token.startswith("p") and token[1:].isdigit():
        idx = int(token[1:]) - 1
        if 0 <= idx < len(PERSONAS):
            return PERSONAS[idx]
    raise ValueError(f"Unknown persona token: {token}")


COMPARATIVE_SYNTHESIS_PROMPT = """You are synthesizing a buyer's comparative UX review.

Persona: {persona_name} ({persona_role})
Goal: {goal_title}
User goal: {user_goal}

You are given three platform run summaries (Bland, Vapi, Retell) with final URLs, success, and the agent's like/dislike notes.

Produce JSON only:
{{
  "goal": "...",
  "per_platform": {{
    "bland": {{"liked": [...], "disliked": [...], "ease": "easy|medium|hard", "would_complete_again": true}},
    "vapi": {{...}},
    "retell": {{...}}
  }},
  "most_likely_to_use": "bland"|"vapi"|"retell",
  "runner_up": "bland"|"vapi"|"retell",
  "why_winner": "2-4 sentences from this persona's priorities",
  "bland_gaps_vs_winner": "what Bland should improve if it did not win (or reinforce if it won)",
  "confidence": "low|medium|high"
}}
"""
