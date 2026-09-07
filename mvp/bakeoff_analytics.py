"""Aggregate persona bakeoff stats for the analytics dashboard (all platforms)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from mvp.bakeoff_view import CAPABILITY_DIR, PERSONA_BIOS, PLATFORM_LABEL

PLATFORMS = ("bland", "vapi", "retell")

# J1–J5 task-type buckets (matches bakeoff analytics write-up).
JOURNEY_LABELS = {
    "J1": "Create agent / rapid setup",
    "J2": "Knowledge / escalation",
    "J3": "Routing / call ops",
    "J4": "Integration / tools",
    "J5": "Testing / simulation / analytics",
}

_GOAL_JOURNEY: dict[str, str] = {
    "p1_t1_call_logs_overview": "J3",
    "p1_t2_open_call_detail": "J3",
    "p1_t3_filter_or_search_calls": "J3",
    "p1_t4_triage_or_qa": "J2",
    "p1_t5_analytics_glance": "J5",
    "p2_t1_agents_list": "J1",
    "p2_t2_create_agent_entry": "J1",
    "p2_t3_open_existing_config": "J1",
    "p2_t4_tools_webhooks": "J4",
    "p2_t5_test_or_simulate": "J5",
    "p3_t1_phone_numbers": "J3",
    "p3_t2_batch_or_outbound": "J3",
    "p3_t3_outbound_in_logs": "J3",
    "p3_t4_voice_persona": "J5",
    "p3_t5_campaign_metrics": "J5",
    "p4_t1_api_keys": "J4",
    "p4_t2_org_settings": "J4",
    "p4_t3_tools_for_functions": "J4",
    "p4_t4_webhook_or_events": "J4",
    "p4_t5_assistant_jsonish": "J4",
    "p5_t1_recording_access": "J3",
    "p5_t2_billing_usage": "J5",
    "p5_t3_team_access": "J2",
    "p5_t4_privacy_settings": "J2",
    "p5_t5_export_or_download": "J5",
    "p6_t1_first_agent": "J1",
    "p6_t2_pricing_billing": "J1",
    "p6_t3_buy_or_import_number": "J1",
    "p6_t4_knowledge_upload": "J2",
    "p6_t5_help_onboarding": "J2",
}


def journey_for_goal(goal_key: str) -> str:
    if goal_key in _GOAL_JOURNEY:
        return _GOAL_JOURNEY[goal_key]
    # Fallback heuristics
    g = goal_key.lower()
    if any(x in g for x in ("test", "simulat", "analytics", "metrics", "voice")):
        return "J5"
    if any(x in g for x in ("tool", "webhook", "api_key", "org_setting", "jsonish", "function")):
        return "J4"
    if any(x in g for x in ("knowledge", "triage", "qa", "help", "privacy", "team")):
        return "J2"
    if any(x in g for x in ("create", "first_agent", "agents_list", "pricing", "buy_or")):
        return "J1"
    return "J3"


def build_analytics() -> dict:
    runs = _load_all_runs()
    reviews = _load_all_reviews()

    by_platform = {p: {"ok": 0, "n": 0} for p in PLATFORMS}
    actions: dict[str, list[int]] = {p: [] for p in PLATFORMS}
    for r in runs:
        plat = r.get("website")
        if plat not in by_platform:
            continue
        by_platform[plat]["n"] += 1
        if r.get("success"):
            by_platform[plat]["ok"] += 1
        if r.get("success") and isinstance(r.get("num_actions"), int):
            actions[plat].append(r["num_actions"])

    preference_counts = {p: 0 for p in PLATFORMS}
    for rev in reviews:
        w = rev.get("most_likely_to_use")
        if w in preference_counts:
            preference_counts[w] += 1
    n_goals = max(1, sum(preference_counts.values()))
    preference_share = {
        p: round(100.0 * preference_counts[p] / n_goals, 1) for p in PLATFORMS
    }
    avg_actions = {
        p: (round(sum(actions[p]) / len(actions[p]), 1) if actions[p] else None)
        for p in PLATFORMS
    }

    by_journey: dict[str, dict] = {
        jid: {
            "id": jid,
            "label": JOURNEY_LABELS[jid],
            "success": {p: {"ok": 0, "n": 0} for p in PLATFORMS},
            "preferences": {p: 0 for p in PLATFORMS},
        }
        for jid in JOURNEY_LABELS
    }
    for r in runs:
        plat = r.get("website")
        gk = r.get("goal_key") or ""
        jid = journey_for_goal(gk)
        if plat not in PLATFORMS or jid not in by_journey:
            continue
        by_journey[jid]["success"][plat]["n"] += 1
        if r.get("success"):
            by_journey[jid]["success"][plat]["ok"] += 1
    for rev in reviews:
        jid = journey_for_goal(rev.get("goal_key") or "")
        w = rev.get("most_likely_to_use")
        if jid in by_journey and w in by_journey[jid]["preferences"]:
            by_journey[jid]["preferences"][w] += 1

    by_persona: list[dict] = []
    persona_ids = sorted({r.get("persona_id") for r in runs if r.get("persona_id")})
    for pid in persona_ids:
        pruns = [r for r in runs if r.get("persona_id") == pid]
        name = next((r.get("persona_name") for r in pruns if r.get("persona_name")), pid)
        success = {p: {"ok": 0, "n": 0} for p in PLATFORMS}
        for r in pruns:
            plat = r.get("website")
            if plat not in success:
                continue
            success[plat]["n"] += 1
            if r.get("success"):
                success[plat]["ok"] += 1
        prefs = {p: 0 for p in PLATFORMS}
        for rev in reviews:
            if rev.get("persona_id") != pid:
                continue
            w = rev.get("most_likely_to_use")
            if w in prefs:
                prefs[w] += 1
        top = max(prefs, key=prefs.get) if any(prefs.values()) else None
        by_persona.append(
            {
                "persona_id": pid,
                "persona_name": name,
                "bio": PERSONA_BIOS.get(pid, ""),
                "success": success,
                "preferences": prefs,
                "top_preference": top,
                "goals": _persona_goal_rows(pid, runs, reviews),
            }
        )

    return {
        "platforms": list(PLATFORMS),
        "platform_labels": {p: PLATFORM_LABEL.get(p, p) for p in PLATFORMS},
        "n_runs": len(runs),
        "n_goals": len(reviews),
        "metric_note": (
            "Task completion is near-ceiling (agents found most pages). "
            "The discriminator is persona preference wins and steps-to-done."
        ),
        "success_by_platform": {
            p: {
                "ok": by_platform[p]["ok"],
                "n": by_platform[p]["n"],
                "rate": _rate(by_platform[p]["ok"], by_platform[p]["n"]),
            }
            for p in PLATFORMS
        },
        "preference_counts": preference_counts,
        "preference_share": preference_share,
        "avg_actions": avg_actions,
        "by_journey": [by_journey[j] for j in JOURNEY_LABELS],
        "by_persona": by_persona,
        "matrix": _persona_journey_matrix(reviews),
    }


def _rate(ok: int, n: int) -> float | None:
    if not n:
        return None
    return round(100.0 * ok / n, 1)


def _load_all_runs() -> list[dict]:
    out: list[dict] = []
    if not CAPABILITY_DIR.is_dir():
        return out
    for path in sorted(CAPABILITY_DIR.glob("product_persona_p*_browser_use_*_all_v1.json")):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        out.extend(data.get("runs") or [])
    return out


def _load_all_reviews() -> list[dict]:
    out: list[dict] = []
    if not CAPABILITY_DIR.is_dir():
        return out
    for path in sorted(CAPABILITY_DIR.glob("persona_p*_comparative.json")):
        if "rollup" in path.name:
            continue
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        out.extend(data.get("reviews") or [])
    return out


def _persona_goal_rows(pid: str, runs: list[dict], reviews: list[dict]) -> list[dict]:
    goals = sorted({r.get("goal_key") for r in runs if r.get("persona_id") == pid and r.get("goal_key")})
    rows = []
    for gk in goals:
        title = next(
            (r.get("goal_title") for r in runs if r.get("goal_key") == gk and r.get("goal_title")),
            gk,
        )
        success = {}
        for p in PLATFORMS:
            pr = next(
                (
                    r
                    for r in runs
                    if r.get("persona_id") == pid and r.get("goal_key") == gk and r.get("website") == p
                ),
                None,
            )
            success[p] = bool(pr.get("success")) if pr else None
        rev = next(
            (r for r in reviews if r.get("persona_id") == pid and r.get("goal_key") == gk),
            {},
        )
        rows.append(
            {
                "goal_key": gk,
                "title": title,
                "journey": journey_for_goal(gk),
                "journey_label": JOURNEY_LABELS.get(journey_for_goal(gk), ""),
                "success": success,
                "winner": rev.get("most_likely_to_use"),
                "runner_up": rev.get("runner_up"),
                "why": rev.get("why_winner"),
            }
        )
    return rows


def _persona_journey_matrix(reviews: list[dict]) -> dict:
    """Persona × journey preferred platform (from comparative winners)."""
    cells: dict[str, dict[str, str | None]] = {}
    for rev in reviews:
        pid = rev.get("persona_id") or ""
        jid = journey_for_goal(rev.get("goal_key") or "")
        cells.setdefault(pid, {})
        # If multiple goals in same journey, keep majority / first non-null
        prev = cells[pid].get(jid)
        w = rev.get("most_likely_to_use")
        if not prev:
            cells[pid][jid] = w
        elif prev != w and w:
            # mark conflict as tie-ish — keep first, UI can show mixed
            cells[pid][jid] = prev if prev == w else "mixed"
    return {
        "journeys": list(JOURNEY_LABELS.keys()),
        "journey_labels": JOURNEY_LABELS,
        "cells": cells,
    }
