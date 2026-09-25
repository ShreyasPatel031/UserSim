"""Bland-style analytics + trace drill-down for the recurse.run competitive study.

Mirrors /blandai and /video-platforms: preference wins across product + 2 rivals,
sliced by persona and task, with side-by-side step screenshots.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

STUDY_ID = "e5daac85-b0f8-4425-a991-834d071ee823"
DATA = Path(__file__).resolve().parent / "recurse_data" / "study.json"

PLATFORMS = ("recurse", "langchain", "llamaindex")
LABELS = {
    "recurse": "Recurse",
    "langchain": "LangChain",
    "llamaindex": "LlamaIndex",
}
SITE_TO_PLATFORM = {
    "product": "recurse",
    "competitor_1": "langchain",
    "competitor_2": "llamaindex",
}
CONVERT_SCORE = {"yes": 3, "likely": 3, "true": 3, "maybe": 1, "no": 0, "false": 0}


def _load() -> dict[str, Any]:
    if not DATA.is_file():
        raise FileNotFoundError(f"Missing packaged study at {DATA}")
    return json.loads(DATA.read_text())


def _platform(row: dict[str, Any]) -> str | None:
    sk = str(row.get("site_key") or "")
    if sk in SITE_TO_PLATFORM:
        return SITE_TO_PLATFORM[sk]
    label = str(row.get("site_label") or row.get("site_url") or "").lower()
    if "recurse" in label:
        return "recurse"
    if "langchain" in label:
        return "langchain"
    if "llamaindex" in label or "llama" in label:
        return "llamaindex"
    return None


def _base_title(title: str) -> str:
    t = (title or "").strip()
    t = re.sub(r"\s*\(vs\s+https?://[^)]+\)\s*$", "", t, flags=re.I)
    return t or "Task"


def _goal_key(persona_id: str, title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", _base_title(title).lower()).strip("_")[:48]
    return f"{persona_id}__{slug}"


def _convert_score(row: dict[str, Any]) -> int:
    return CONVERT_SCORE.get(str(row.get("would_convert") or "").lower(), 0)


def _success(row: dict[str, Any]) -> bool:
    """Treat a session as completed enough if we got a convert judgment or steps."""
    if row.get("would_convert") in {"yes", "maybe", "no"}:
        return True
    return int(row.get("num_steps") or len(row.get("trace") or []) or 0) > 0


def _rows() -> list[dict[str, Any]]:
    data = _load()
    out: list[dict[str, Any]] = []
    for r in data.get("agent_results") or []:
        if not isinstance(r, dict):
            continue
        plat = _platform(r)
        if not plat:
            continue
        persona_id = str(r.get("persona_id") or "p?")
        title = _base_title(str(r.get("task_title") or r.get("task_prompt") or "Task"))
        out.append(
            {
                **r,
                "platform": plat,
                "persona_id": persona_id,
                "goal_title": title,
                "goal_key": _goal_key(persona_id, title),
            }
        )
    return out


def _groups(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        grouped[r["goal_key"]].append(r)
    return grouped


def _winner(group: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick preferred platform for one persona×task from would_convert + friction."""
    by_plat: dict[str, dict[str, Any]] = {}
    for r in group:
        p = r["platform"]
        # Keep the best row if duplicates
        prev = by_plat.get(p)
        if prev is None or _convert_score(r) > _convert_score(prev):
            by_plat[p] = r
    if not by_plat:
        return None

    def key(r: dict[str, Any]) -> tuple:
        fric = len(r.get("friction_points") or [])
        steps = int(r.get("num_steps") or len(r.get("trace") or []) or 0)
        # Higher convert wins; fewer frictions; more evidence steps as soft signal
        return (_convert_score(r), -fric, steps)

    return max(by_plat.values(), key=key)


def _shot_url(study_id: str, agent_id: str, filename: str) -> str:
    return f"/api/studies/{study_id}/agents/{agent_id}/screenshots/{filename}"


def _normalize_trace(row: dict[str, Any], study_id: str) -> list[dict[str, Any]]:
    agent_id = str(row.get("agent_id") or "")
    steps: list[dict[str, Any]] = []
    for i, s in enumerate(row.get("trace") or []):
        if not isinstance(s, dict):
            continue
        shot = s.get("screenshot_url") or ""
        if not shot and agent_id:
            # Prefer bbox_N then step_N
            n = s.get("step")
            if n is None:
                n = i
            shot = _shot_url(study_id, agent_id, f"bbox_{n}.png")
        elif shot.startswith("/api/") is False and agent_id:
            # local path → API
            name = Path(str(shot)).name
            if re.fullmatch(r"(?:bbox|step)_\d+\.png", name):
                shot = _shot_url(study_id, agent_id, name)
        steps.append(
            {
                "step": s.get("step", i),
                "action": s.get("action") or s.get("thought") or f"Step {i}",
                "target": (s.get("thought_detail") or {}).get("target")
                if isinstance(s.get("thought_detail"), dict)
                else "",
                "observation": s.get("observation") or "",
                "url": s.get("url") or "",
                "thought_detail": s.get("thought_detail") or {},
                "outcome": s.get("outcome") or "neutral",
                "screenshot_url": shot,
            }
        )
    if not steps and agent_id:
        # At least landing frame
        steps = [
            {
                "step": 0,
                "action": "Opened page",
                "target": "",
                "observation": "",
                "url": row.get("site_url") or "",
                "thought_detail": {},
                "outcome": "neutral",
                "screenshot_url": _shot_url(study_id, agent_id, "bbox_0.png"),
            }
        ]
    return steps


def analytics() -> dict[str, Any]:
    rows = _rows()
    groups = _groups(rows)
    winners = {k: _winner(g) for k, g in groups.items()}
    winners = {k: v for k, v in winners.items() if v}

    pref = Counter(w["platform"] for w in winners.values())
    n_goals = max(1, len(winners))

    success_by_platform: dict[str, dict[str, Any]] = {}
    avg_actions: dict[str, float | None] = {}
    for p in PLATFORMS:
        pr = [r for r in rows if r["platform"] == p]
        ok = sum(1 for r in pr if _success(r))
        n = len(pr)
        success_by_platform[p] = {
            "ok": ok,
            "n": n,
            "rate": round(100.0 * ok / n, 1) if n else 0.0,
        }
        steps = [
            int(r.get("num_steps") or len(r.get("trace") or []) or 0)
            for r in pr
            if _success(r)
        ]
        avg_actions[p] = round(sum(steps) / len(steps), 1) if steps else None

    # Journeys = unique base task titles across personas
    title_to_jid: dict[str, str] = {}
    journeys_meta: list[tuple[str, str]] = []
    for title in sorted({r["goal_title"] for r in rows}):
        jid = f"T{len(journeys_meta) + 1}"
        title_to_jid[title] = jid
        journeys_meta.append((jid, title))

    by_journey = []
    for jid, label in journeys_meta:
        jrows = [r for r in rows if title_to_jid[r["goal_title"]] == jid]
        jwins = [w for w in winners.values() if title_to_jid[w["goal_title"]] == jid]
        by_journey.append(
            {
                "id": jid,
                "label": label,
                "success": {
                    p: {
                        "ok": sum(1 for r in jrows if r["platform"] == p and _success(r)),
                        "n": sum(1 for r in jrows if r["platform"] == p),
                    }
                    for p in PLATFORMS
                },
                "preferences": {
                    p: sum(1 for w in jwins if w["platform"] == p) for p in PLATFORMS
                },
            }
        )

    by_persona = []
    for pid in sorted({r["persona_id"] for r in rows}):
        pruns = [r for r in rows if r["persona_id"] == pid]
        name = next((r.get("persona_name") for r in pruns if r.get("persona_name")), pid)
        bio = next((r.get("persona_bio") for r in pruns if r.get("persona_bio")), "")
        pgoals = []
        for key, group in groups.items():
            if group[0]["persona_id"] != pid:
                continue
            win = winners.get(key)
            if not win:
                continue
            pgoals.append(
                {
                    "goal_key": key,
                    "title": group[0]["goal_title"],
                    "journey": title_to_jid[group[0]["goal_title"]],
                    "journey_label": group[0]["goal_title"],
                    "success": {
                        p: _success(next((r for r in group if r["platform"] == p), {}))
                        for p in PLATFORMS
                    },
                    "winner": win["platform"],
                    "runner_up": None,
                    "why": (
                        f"Highest convert signal ({win.get('would_convert')}) "
                        f"with {len(win.get('friction_points') or [])} friction notes."
                    ),
                }
            )
        pc = Counter(g["winner"] for g in pgoals)
        by_persona.append(
            {
                "persona_id": pid,
                "persona_name": name,
                "bio": bio or "",
                "success": {
                    p: {
                        "ok": sum(1 for r in pruns if r["platform"] == p and _success(r)),
                        "n": sum(1 for r in pruns if r["platform"] == p),
                    }
                    for p in PLATFORMS
                },
                "preferences": {p: pc[p] for p in PLATFORMS},
                "top_preference": (pc.most_common(1)[0][0] if pc else None),
                "goals": pgoals,
            }
        )

    return {
        "platforms": list(PLATFORMS),
        "platform_labels": LABELS,
        "n_runs": len(rows),
        "n_goals": len(winners),
        "study_id": STUDY_ID,
        "product_url": "https://recurse.run/",
        "metric_note": (
            "Preference wins compare Recurse vs LangChain vs LlamaIndex for the same "
            "persona×task using would-convert (yes > maybe > no), then fewer friction "
            "notes. 66/75 sessions finished; 9 hung agents were excluded."
        ),
        "success_by_platform": success_by_platform,
        "preference_counts": {p: pref[p] for p in PLATFORMS},
        "preference_share": {
            p: round(100.0 * pref[p] / n_goals, 1) for p in PLATFORMS
        },
        "avg_actions": avg_actions,
        "by_journey": by_journey,
        "by_persona": by_persona,
        "matrix": {
            "journeys": [j for j, _ in journeys_meta],
            "journey_labels": {j: lab for j, lab in journeys_meta},
            "cells": {
                x["persona_id"]: {g["journey"]: g["winner"] for g in x["goals"]}
                for x in by_persona
            },
        },
    }


def studies() -> list[dict[str, Any]]:
    rows = _rows()
    out = []
    for pid in sorted({r["persona_id"] for r in rows}):
        rr = [r for r in rows if r["persona_id"] == pid]
        out.append(
            {
                "id": pid,
                "persona_id": pid,
                "persona_name": rr[0].get("persona_name") or pid,
                "n_runs": len(rr),
                "successes": sum(1 for r in rr if _success(r)),
                "stage": "complete",
            }
        )
    return out


def study(pid: str) -> dict[str, Any]:
    rows = [r for r in _rows() if r["persona_id"] == pid]
    if not rows:
        raise FileNotFoundError(pid)
    data = _load()
    study_id = str(data.get("id") or STUDY_ID)
    grouped = _groups(rows)
    reviews: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    for key, group in grouped.items():
        win = _winner(group)
        if win:
            reviews.append(
                {
                    "goal_key": key,
                    "most_likely_to_use": win["platform"],
                    "runner_up": None,
                    "why_winner": (
                        f"Convert={win.get('would_convert')}; "
                        f"{len(win.get('friction_points') or [])} friction notes."
                    ),
                }
            )
        for r in group:
            results.append(
                {
                    "agent_id": r.get("agent_id"),
                    "task_id": key,
                    "persona_id": pid,
                    "persona_name": r.get("persona_name"),
                    "task_title": f"{r['goal_title']} — {LABELS[r['platform']]}",
                    "task_prompt": r.get("task_prompt") or r["goal_title"],
                    "platform": r["platform"],
                    "goal_key": key,
                    "status": "complete",
                    "success": _success(r),
                    "judge_status": "complete" if _success(r) else "friction",
                    "final_url": r.get("final_url") or r.get("site_url"),
                    "num_actions": int(
                        r.get("num_steps") or len(r.get("trace") or []) or 0
                    ),
                    "difficulty": r.get("difficulty") or "medium",
                    "would_convert": r.get("would_convert"),
                    "product_feedback": r.get("product_feedback"),
                    "likes": r.get("what_was_easy") or [],
                    "dislikes": r.get("friction_points") or [],
                    "quote": r.get("quote"),
                    "comparative_winner": win["platform"] if win else None,
                    "comparative_why": (
                        reviews[-1]["why_winner"] if win and reviews else None
                    ),
                    "trace": _normalize_trace(r, study_id),
                }
            )
    name = rows[0].get("persona_name") or pid
    bio = rows[0].get("persona_bio") or ""
    return {
        "study_id": pid,
        "status": "complete",
        "phase": "Complete",
        "personas": [{"id": pid, "name": name, "bio": bio}],
        "tasks": [],
        "agent_results": results,
        "comparative": {"reviews": reviews},
        "summary": {},
    }
