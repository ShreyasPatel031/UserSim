"""Comparative public-site insights from the audited voice-public bakeoff."""

from __future__ import annotations


def _item(text: str, run_id: str) -> dict:
    return {
        "text": text,
        "run_id": run_id,
        "screenshot_url": f"/bakeoff-traces/{run_id}/final.png",
    }


# Counts after offline re-judge of the three JUDGE_ERROR traces in
# results/capability/voice-public-d28b7070.json (no new browser runs).
# Success is tied on 4 of 5 tasks; differences are steps and where the agent landed.

RETELL_STRENGTHS = [
    _item(
        "API docs is a 3/3 tie, but Retell reached the API overview in 5 steps on every persona "
        "(median 5) versus Bland median 10 (8–13) and Vapi median 15 (8–16). "
        "Engineer run ended on docs.retellai.com/api-references/overview.",
        "bu_26441_ddfb10d7",
    ),
    _item(
        "Getting started is a 3/3 tie. Retell median was 6 steps (6, 6, 7) to the quick-start doc, "
        "versus Bland median 9 (8–16) and Vapi median 24 (15–26). "
        "PM run finished on docs.retellai.com/get-started/quick-start.",
        "bu_85658_6c744f9e",
    ),
    _item(
        "Voice-agent capabilities: Retell and Vapi both 3/3; Bland is 2/3 because one Bland run "
        "hit the 25-step cap and stopped on bland.ai/pricing (bu_13188_b7eae5ef). "
        "Retell's engineer run reached retellai.com/use-cases in 20 steps; Bland's successes took 25.",
        "bu_64422_a0a5804a",
    ),
]

RETELL_WEAKNESSES = [
    _item(
        "Capabilities is a 3/3 tie with Vapi, but Retell's median was 22 steps (20, 22, 26) "
        "versus Vapi's fastest path at 15 steps to docs.vapi.ai/quickstart. "
        "The founder run spent 22 steps and finished on docs.retellai.com/general/introduction, "
        "not a marketing use-cases page.",
        "bu_91461_ae8058b7",
    ),
    _item(
        "Integrations is a 3/3 tie, but Retell's median was 24 steps (9, 24, 26) versus Bland median 8 "
        "(all three Bland runs on docs.bland.ai/tutorials/webhooks or the calls API) and Vapi median 12 "
        "(server-url docs). The founder Retell run took 26 steps and stopped on the API overview, "
        "not the integrations page.",
        "bu_12391_1efe3405",
    ),
    _item(
        "Pricing is a 3/3 tie. Vapi was slightly faster (median 5 steps, range 5–7) than Retell "
        "(median 6, range 5–7) and Bland (median 6, range 4–9). Retell's founder still needed an extra "
        "click from the pricing page into #pricing_breakdown (5 steps, bu_34211_3a337d3c).",
        "bu_45796_33f1c470",
    ),
]


def attach_public_insights(page: dict, runs: list[dict] | None = None) -> dict:
    summary = page.setdefault("summary", {})
    summary["headline"] = (
        "On public-site tasks, success rates are a tie: Retell 15/15, Vapi 15/15, Bland 14/15 "
        "(one Bland capabilities run ended on pricing after the step cap). "
        "Retell is faster to API docs and getting started, and slower to a capabilities page and to webhook docs."
    )
    summary["metric_note"] = (
        "Audited harness run voice-public-d28b7070. Zero harness timeouts. "
        "Three former judge-JSON errors were re-scored from saved traces as successes "
        "(Retell capabilities, Retell webhooks, Vapi webhooks). "
        "The only product failure is Bland capabilities (planning: final page was pricing)."
    )
    summary["retell_strengths"] = RETELL_STRENGTHS
    summary["retell_weaknesses"] = RETELL_WEAKNESSES
    summary["insights_synthesized"] = True
    summary["source_manifest"] = "results/capability/voice-public-d28b7070.json"
    return page
