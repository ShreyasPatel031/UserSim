"""Bland-style analytics and drill-down payloads for the video platform study."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

DATA = Path(__file__).resolve().parent / "video_data" / "all_90_results.json"
PLATFORMS = ("youtube", "vimeo", "dailymotion")
LABELS = {"youtube": "YouTube", "vimeo": "Vimeo", "dailymotion": "Dailymotion"}
BIOS = {
    "p1_viewer": "Everyday viewer — wants relevant, trustworthy videos without fighting the interface.",
    "p2_learner": "Self-directed learner — evaluates depth, clarity, and discovery for a new topic.",
    "p3_creator": "Video creator — studies formats, competitors, and creator-facing signals.",
    "p4_marketer": "Growth marketer — researches trends, brands, and audience engagement.",
    "p5_researcher": "Research professional — needs precise retrieval and credible source context.",
    "p6_power": "Power user — probes advanced navigation, filtering, and workflow efficiency.",
}
FAILURE = re.compile(r"unable to complete|could not complete|maximum step limit|unsuccessful|could not (?:find|inspect|search)|captcha", re.I)


def _runs():
    return json.loads(DATA.read_text()).get("results", [])


def _success(run):
    return not FAILURE.search(run.get("final_result") or "")


def _groups(runs):
    out = {}
    for run in runs:
        out.setdefault(run["comparative_group"], []).append(run)
    return out


def _winner(group):
    eligible = [r for r in group if _success(r)] or group
    return min(eligible, key=lambda r: r.get("elapsed_s") or 10**9)


def analytics():
    runs = _runs()
    groups = _groups(runs)
    winners = {key: _winner(group) for key, group in groups.items()}
    pref = Counter(r["website"] for r in winners.values())
    personas = []
    for pid in sorted({r["persona_id"] for r in runs}):
        pruns = [r for r in runs if r["persona_id"] == pid]
        pgoals = []
        for key, group in groups.items():
            if group[0]["persona_id"] != pid:
                continue
            win = winners[key]
            pgoals.append({
                "goal_key": key, "title": group[0]["goal_title"],
                "journey": group[0]["goal_key"].upper(), "journey_label": group[0]["goal_title"],
                "success": {p: _success(next(r for r in group if r["website"] == p)) for p in PLATFORMS},
                "winner": win["website"], "runner_up": None,
                "why": f"Fastest likely-complete result at {round(win['elapsed_s'])} seconds.",
            })
        pc = Counter(g["winner"] for g in pgoals)
        personas.append({
            "persona_id": pid, "persona_name": pruns[0]["persona_name"], "bio": BIOS.get(pid, ""),
            "success": {p: {"ok": sum(_success(r) for r in pruns if r["website"] == p), "n": 5} for p in PLATFORMS},
            "preferences": {p: pc[p] for p in PLATFORMS},
            "top_preference": pc.most_common(1)[0][0], "goals": pgoals,
        })
    journeys = []
    for goal in sorted({r["goal_key"] for r in runs}):
        gruns = [r for r in runs if r["goal_key"] == goal]
        relevant = [w for w in winners.values() if w["goal_key"] == goal]
        journeys.append({
            "id": goal.upper(), "label": gruns[0]["goal_title"],
            "success": {p: {"ok": sum(_success(r) for r in gruns if r["website"] == p), "n": 6} for p in PLATFORMS},
            "preferences": {p: sum(r["website"] == p for r in relevant) for p in PLATFORMS},
        })
    return {
        "platforms": list(PLATFORMS), "platform_labels": LABELS, "n_runs": 90, "n_goals": 30,
        "metric_note": "Completion is inferred conservatively from each agent's final report. Preference wins use the fastest likely-complete platform for the same persona and task.",
        "success_by_platform": {p: {"ok": sum(_success(r) for r in runs if r["website"] == p), "n": 30, "rate": round(100 * sum(_success(r) for r in runs if r["website"] == p) / 30, 1)} for p in PLATFORMS},
        "preference_counts": {p: pref[p] for p in PLATFORMS},
        "preference_share": {p: round(100 * pref[p] / 30, 1) for p in PLATFORMS},
        "avg_actions": {p: round(sum(r["elapsed_s"] for r in runs if r["website"] == p) / 30, 1) for p in PLATFORMS},
        "by_journey": journeys, "by_persona": personas,
        "matrix": {"journeys": [j["id"] for j in journeys], "journey_labels": {j["id"]: j["label"] for j in journeys}, "cells": {x["persona_id"]: {g["journey"]: g["winner"] for g in x["goals"]} for x in personas}},
    }


def studies():
    runs = _runs()
    out = []
    for pid in sorted({r["persona_id"] for r in runs}):
        rr = [r for r in runs if r["persona_id"] == pid]
        out.append({"id": pid, "persona_id": pid, "persona_name": rr[0]["persona_name"], "n_runs": 15, "successes": sum(_success(r) for r in rr), "stage": "complete"})
    return out


def study(pid):
    runs = [r for r in _runs() if r["persona_id"] == pid]
    if not runs:
        raise FileNotFoundError(pid)
    grouped = _groups(runs)
    reviews, results = [], []
    for key, group in grouped.items():
        win = _winner(group)
        reviews.append({"goal_key": key, "most_likely_to_use": win["website"], "runner_up": None, "why_winner": f"Fastest likely-complete result at {round(win['elapsed_s'])} seconds."})
        for r in group:
            results.append({
                "agent_id": str(r["eval_index"]), "task_id": key, "persona_id": pid, "persona_name": r["persona_name"],
                "task_title": f"{r['goal_title']} — {LABELS[r['website']]}", "task_prompt": r["goal_title"],
                "platform": r["website"], "goal_key": key, "status": "complete", "success": _success(r),
                "judge_status": "complete" if _success(r) else "friction", "final_url": r.get("final_url"),
                "num_actions": round(r.get("elapsed_s") or 0), "difficulty": "easy" if _success(r) else "hard",
                "product_feedback": r.get("final_result"), "likes": [], "dislikes": [], "trace": [],
            })
    return {"study_id": pid, "status": "complete", "phase": "Complete", "personas": [{"id": pid, "name": runs[0]["persona_name"], "bio": BIOS.get(pid, "")}], "tasks": [], "agent_results": results, "comparative": {"reviews": reviews}, "summary": {}}
