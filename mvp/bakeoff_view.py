"""Convert capability persona bakeoff manifests into MVP dashboard study payloads."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAPABILITY_DIR = ROOT / "results" / "capability"

PERSONA_BIOS = {
    "p1_ops": "Contact Center Operations Manager — keeps inbound voice agents reliable; QA every bad call quickly.",
    "p2_fde": "Forward-deployed Solutions Engineer — stands up pathways, tools, and test loops for enterprise customers.",
    "p3_outbound": "Outbound Campaign Lead — high-volume dialing, answer rates, campaign reporting.",
    "p4_eng": "Platform Engineer — API keys, webhooks, org settings, developer-oriented configs.",
    "p5_compliance": "Compliance & Risk Lead — recordings, billing visibility, access controls, export.",
    "p6_founder": "Founder / Head of Product — picks a vendor in 48 hours for an investor demo.",
    # full270 personas
    "p1_owner": "Nontechnical business owner — needs time-to-first-agent, templates, pricing clarity.",
    "p2_cx_ops": "CX operations manager — call quality, transcripts, escalation, filters.",
    "p3_revops": "Revenue ops — outbound routing, handoffs, campaigns, reporting.",
    "p4_designer": "Conversation designer — builder UX, intents, knowledge, simulation.",
    "p5_integrator": "Integration developer — APIs, webhooks, variables, tools.",
    "p6_admin": "Enterprise admin — access controls, analytics, recordings, compliance.",
}

JOURNEY_META = {
    "j1_rapid_setup": {"ord": 1, "short": "J1 Rapid setup", "category": "Create agent"},
    "j2_knowledge_support": {"ord": 2, "short": "J2 Knowledge", "category": "Knowledge & escalation"},
    "j3_logic_routing": {"ord": 3, "short": "J3 Routing", "category": "Logic & routing"},
    "j4_integration": {"ord": 4, "short": "J4 Integration", "category": "Webhooks & tools"},
    "j5_testing_debug": {"ord": 5, "short": "J5 Testing", "category": "Simulate & analytics"},
}

PLATFORM_LABEL = {"bland": "Bland AI", "vapi": "Vapi", "retell": "Retell AI"}
PLATFORMS = ("bland", "vapi", "retell")


def list_studies() -> list[dict]:
    out: list[dict] = []
    if not CAPABILITY_DIR.is_dir():
        return out
    seen: set[str] = set()

    def _append(path: Path, *, label_suffix: str = "") -> None:
        if path.stem in seen:
            return
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        seen.add(path.stem)
        runs = data.get("runs") or []
        pid = _persona_id_from_runs(runs)
        pname = _persona_name(runs)
        if _is_full270_manifest(data, path.stem):
            pname = f"Full270 · {data.get('model', 'model')} · {data.get('tag', path.stem)}"
            pid = "full270"
        out.append(
            {
                "id": path.stem,
                "path": str(path),
                "persona_id": pid,
                "persona_name": pname + label_suffix,
                "n_runs": data.get("n") or len(runs),
                "successes": data.get("successes"),
                "stage": data.get("stage"),
                "model": data.get("model"),
                "tag": data.get("tag"),
                "is_full270": _is_full270_manifest(data, path.stem),
            }
        )

    for path in sorted(CAPABILITY_DIR.glob("product_full270_browser_use_*.json")):
        if "_shard" in path.stem:
            continue
        _append(path)
    for path in sorted(CAPABILITY_DIR.glob("product_persona_p*_browser_use_*_all_v1.json")):
        _append(path)
    full = CAPABILITY_DIR / "product_persona_browser_use_all.json"
    if full.is_file():
        _append(full)
    out.sort(key=lambda s: (0 if s.get("is_full270") else 1, s.get("id", "")))
    return out


def _is_full270_manifest(data: dict, study_id: str) -> bool:
    if (data.get("stage") or "").startswith("product_full270"):
        return True
    if "full270" in study_id:
        return True
    runs = data.get("runs") or []
    return any((r.get("goal_key") or "").startswith("j") for r in runs[:20])


def load_study(study_id: str) -> dict:
    path = CAPABILITY_DIR / f"{study_id}.json"
    if not path.is_file():
        raise FileNotFoundError(study_id)
    manifest = json.loads(path.read_text())
    runs = manifest.get("runs") or []
    is_full270 = _is_full270_manifest(manifest, study_id)
    persona_ids = sorted({r.get("persona_id") for r in runs if r.get("persona_id")})
    personas = [
        {
            "id": pid,
            "name": _persona_name([r for r in runs if r.get("persona_id") == pid]),
            "bio": PERSONA_BIOS.get(pid, ""),
        }
        for pid in persona_ids
    ]

    comp_path = path.with_name(path.stem + "_comparative.json")
    if not comp_path.is_file() and persona_ids:
        m = re.search(r"p(\d+)_", persona_ids[0])
        if m:
            alt = CAPABILITY_DIR / f"persona_p{m.group(1)}_comparative.json"
            comp_path = alt if alt.is_file() else comp_path
    comparative = {}
    if comp_path.is_file():
        comparative = json.loads(comp_path.read_text())

    tasks = []
    agent_results = []
    matched_blocks: list[dict] = []

    if is_full270:
        block_ids = sorted({r.get("comparative_group") for r in runs if r.get("comparative_group")})
        for block_id in block_ids:
            block_runs = [r for r in runs if r.get("comparative_group") == block_id]
            if not block_runs:
                continue
            sample = block_runs[0]
            persona_id = sample.get("persona_id")
            goal_key = sample.get("goal_key") or ""
            seed = _seed_from_block(block_id)
            jmeta = JOURNEY_META.get(goal_key, {})
            task_id = block_id
            tasks.append(
                {
                    "id": task_id,
                    "comparative_group": block_id,
                    "persona_id": persona_id,
                    "goal_key": goal_key,
                    "journey_ord": jmeta.get("ord"),
                    "journey_category": jmeta.get("category", goal_key),
                    "seed": seed,
                    "title": sample.get("goal_title") or goal_key,
                    "prompt": _goal_prompt(sample.get("task") or ""),
                }
            )
            comp_review = _comparative_for_goal(comparative, persona_id, goal_key)
            platform_runs = {r.get("website"): r for r in block_runs}
            matched_blocks.append(
                {
                    "id": block_id,
                    "persona_id": persona_id,
                    "persona_name": sample.get("persona_name"),
                    "goal_key": goal_key,
                    "goal_title": sample.get("goal_title"),
                    "journey_ord": jmeta.get("ord"),
                    "journey_category": jmeta.get("category"),
                    "seed": seed,
                    "platforms": {
                        p: {
                            "success": bool(platform_runs.get(p, {}).get("success")),
                            "status": platform_runs.get(p, {}).get("status"),
                        }
                        for p in PLATFORMS
                        if p in platform_runs
                    },
                }
            )
            for r in block_runs:
                agent_results.append(_enrich_run(r, task_id, sample, comp_review))
    else:
        goals = sorted({r.get("goal_key") for r in runs if r.get("goal_key")})
        for goal_key in goals:
            goal_runs = [r for r in runs if r.get("goal_key") == goal_key]
            if not goal_runs:
                continue
            sample = goal_runs[0]
            task_id = goal_key
            tasks.append(
                {
                    "id": task_id,
                    "persona_id": sample.get("persona_id"),
                    "goal_key": goal_key,
                    "title": sample.get("goal_title") or goal_key,
                    "prompt": _goal_prompt(sample.get("task") or ""),
                }
            )
            comp_review = _comparative_for_goal(comparative, sample.get("persona_id"), goal_key)
            for r in goal_runs:
                agent_results.append(_enrich_run(r, task_id, sample, comp_review))

    analytics = _build_analytics(manifest, runs, agent_results, comparative, is_full270)

    headline = f"Persona bakeoff — {manifest.get('successes', 0)}/{manifest.get('n', 0)} tasks succeeded"
    if is_full270:
        rate = analytics.get("success_rate_scored")
        headline = (
            f"Full270 — {manifest.get('successes', 0)}/{manifest.get('n', 0)} succeeded"
            f" ({round((rate or 0) * 100)}% scored)"
        )

    return {
        "study_id": study_id,
        "status": "complete",
        "phase": "Complete",
        "headline": headline,
        "is_full270": is_full270,
        "model": manifest.get("model"),
        "tag": manifest.get("tag"),
        "personas": personas,
        "tasks": tasks,
        "matched_blocks": matched_blocks,
        "journey_types": _journey_types_from_tasks(tasks),
        "agent_results": agent_results,
        "comparative": comparative,
        "summary": _build_summary(comparative, agent_results),
        "analytics": analytics,
    }


def _seed_from_block(block_id: str) -> int | None:
    m = re.search(r"__s(\d+)$", block_id or "")
    return int(m.group(1)) if m else None


def _enrich_run(r: dict, task_id: str, sample: dict, comp_review: dict) -> dict:
    trace_dir = Path(r.get("trace_dir") or "")
    trace = parse_trace_steps(trace_dir)
    feedback = _extract_feedback(r, trace)
    block_id = r.get("comparative_group") or task_id
    return {
        "agent_id": f"{r.get('eval_index')}_{r.get('website')}",
        "task_id": task_id,
        "comparative_group": block_id,
        "persona_id": r.get("persona_id"),
        "persona_name": r.get("persona_name"),
        "task_title": f"{sample.get('goal_title')} — {PLATFORM_LABEL.get(r.get('website',''), r.get('website'))}",
        "task_prompt": _goal_prompt(r.get("task") or ""),
        "platform": r.get("website"),
        "goal_key": r.get("goal_key"),
        "seed": _seed_from_block(block_id),
        "journey_ord": JOURNEY_META.get(r.get("goal_key") or "", {}).get("ord"),
        "journey_category": JOURNEY_META.get(r.get("goal_key") or "", {}).get("category"),
        "status": "complete",
        "success": bool(r.get("success")),
        "judge_status": r.get("status"),
        "failure_category": r.get("failure_category"),
        "final_url": r.get("final_url"),
        "num_actions": r.get("num_actions"),
        "difficulty": feedback.get("difficulty"),
        "would_convert": comp_review.get("most_likely_to_use") if comp_review else None,
        "product_feedback": feedback.get("summary"),
        "likes": feedback.get("likes"),
        "dislikes": feedback.get("dislikes"),
        "quote": feedback.get("quote"),
        "judge_reason": r.get("judge_reason"),
        "comparative_winner": comp_review.get("most_likely_to_use") if comp_review else None,
        "comparative_why": comp_review.get("why_winner") if comp_review else None,
        "trace": trace,
        "trace_name": trace_dir.name,
        "screenshot_url": _step_screenshot_url(trace_dir, 1, trace_dir.name)
        or (
            f"/api/bakeoff/traces/{trace_dir.name}/final.png"
            if (trace_dir / "final.png").is_file()
            else None
        ),
    }


def _journey_types_from_tasks(tasks: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for t in tasks:
        gk = t.get("goal_key")
        if not gk or gk in seen:
            continue
        seen[gk] = {
            "key": gk,
            "title": t.get("title") or gk,
            "ord": t.get("journey_ord") or JOURNEY_META.get(gk, {}).get("ord", 99),
            "category": t.get("journey_category") or JOURNEY_META.get(gk, {}).get("category", gk),
        }
    return sorted(seen.values(), key=lambda x: x["ord"])


def parse_trace_steps(trace_dir: Path) -> list[dict]:
    conv = trace_dir / "conversation"
    click_targets = _click_targets_from_history(trace_dir / "history.txt")
    if conv.is_dir():
        steps = _parse_conversation_dir(conv, click_targets, trace_dir)
        if steps:
            return _append_extra_screenshots(steps, trace_dir)
    hist = trace_dir / "history.txt"
    if hist.is_file():
        steps = _parse_history_txt(hist.read_text(), click_targets, trace_dir)
        return _append_extra_screenshots(steps, trace_dir)
    return []


def _append_extra_screenshots(steps: list[dict], trace_dir: Path) -> list[dict]:
    """Attach replay screenshots beyond conversation file count (e.g. post-click final)."""
    n = len(steps)
    while _step_screenshot_url(trace_dir, n + 1, trace_dir.name):
        n += 1
        steps.append(
            {
                "step": n,
                "action": "done — final state",
                "target": "",
                "observation": "",
                "url": "",
                "thought_detail": {},
                "outcome": "easy",
                "screenshot_url": _step_screenshot_url(trace_dir, n, trace_dir.name),
            }
        )
    return steps


def _click_targets_from_history(hist_path: Path) -> list[str]:
    if not hist_path.is_file():
        return []
    text = hist_path.read_text(errors="replace")
    return re.findall(r"ax_name='([^']+)'", text)


def _step_screenshot_url(trace_dir: Path, step_num: int, trace_name: str) -> str | None:
    shots = trace_dir / "screenshots"
    if (shots / f"bbox_{step_num}.png").is_file():
        return f"/api/bakeoff/traces/{trace_name}/screenshots/bbox_{step_num}.png"
    if (shots / f"step_{step_num}.png").is_file():
        return f"/api/bakeoff/traces/{trace_name}/screenshots/step_{step_num}.png"
    return None


def _parse_conversation_dir(conv: Path, click_targets: list[str], trace_dir: Path) -> list[dict]:
    steps: list[dict] = []
    files = list(conv.glob("conversation_*.txt"))

    def step_num(p: Path) -> int:
        m = re.search(r"_(\d+)\.txt$", p.name)
        return int(m.group(1)) if m else 0

    for fp in sorted(files, key=step_num):
        text = fp.read_text(errors="replace")
        data = _extract_trailing_json(text)
        if not data:
            continue
        url = _extract_current_url(text)
        action = _format_actions(data.get("action"))
        eval_prev = data.get("evaluation_previous_goal") or ""
        outcome = "easy" if "success" in eval_prev.lower() else "neutral"
        if "failure" in eval_prev.lower():
            outcome = "friction"
        target = ""
        if "click" in action.lower() and click_targets:
            target = click_targets.pop(0)
        steps.append(
            {
                "step": len(steps) + 1,
                "action": action,
                "target": target,
                "observation": _browser_observation(text),
                "url": url,
                "thought": data.get("next_goal") or data.get("thinking") or "",
                "thought_detail": {
                    k: data.get(k)
                    for k in ("next_goal", "evaluation_previous_goal", "thinking", "memory")
                    if data.get(k)
                },
                "outcome": outcome,
                "screenshot_url": _step_screenshot_url(trace_dir, len(steps) + 1, trace_dir.name),
            }
        )
    return steps


def _parse_history_txt(text: str, click_targets: list[str], trace_dir: Path) -> list[dict]:
    contents = re.findall(
        r"extracted_content=(?:'((?:\\'|[^'])*)'|\"((?:\\\"|[^\"])*)\")",
        text,
    )
    action_names = re.findall(
        r"\{'(navigate|click|wait|done|input|scroll|select|send_keys)':",
        text,
    )
    steps: list[dict] = []
    for i, (c1, c2) in enumerate(contents):
        content = (c1 or c2 or "").replace("\\n", "\n").replace("\\'", "'")
        if not content.strip():
            continue
        act = action_names[i] if i < len(action_names) else "action"
        steps.append(
            {
                "step": len(steps) + 1,
                "action": f"{act} — {content[:200]}",
                "observation": content,
                "url": "",
                "thought_detail": {},
                "outcome": "easy" if i == len(contents) - 1 and "Task completed" in text else "neutral",
                "screenshot_url": _step_screenshot_url(trace_dir, len(steps) + 1, trace_dir.name),
            }
        )
    return steps


def _extract_trailing_json(text: str) -> dict | None:
    start = text.rfind("\n{")
    if start < 0:
        return None
    chunk = text[start + 1 :].strip()
    try:
        return json.loads(chunk)
    except json.JSONDecodeError:
        return None


def _extract_current_url(text: str) -> str:
    for m in re.finditer(r"Current URL:\s*(\S+)", text):
        url = m.group(1).strip()
        if url.startswith("http"):
            return url
    return ""


def _browser_observation(text: str) -> str:
    if not _extract_current_url(text):
        return ""
    m = re.search(r"<browser_state>([\s\S]*?)</browser_state>", text)
    if not m:
        return ""
    body = m.group(1).strip()
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    # first few meaningful lines
    preview = lines[:8]
    return "\n".join(preview)[:1200]


def _format_actions(action: object) -> str:
    if not action:
        return "Action"
    if isinstance(action, list):
        parts = []
        for item in action:
            if isinstance(item, dict):
                for k, v in item.items():
                    if k == "done" and isinstance(v, dict):
                        parts.append("done — task complete")
                    elif isinstance(v, dict):
                        detail = ", ".join(f"{a}={b}" for a, b in v.items() if a != "text")
                        parts.append(f"{k}({detail})" if detail else k)
                    else:
                        parts.append(f"{k}={v}")
        return " · ".join(parts) if parts else "Action"
    return str(action)[:300]


def _extract_feedback(run: dict, trace: list[dict]) -> dict:
    text = ""
    for step in reversed(trace):
        td = step.get("thought_detail") or {}
        if td.get("thinking"):
            text = td["thinking"]
            break
    # Prefer done text from history / last conversation file
    trace_dir = Path(run.get("trace_dir") or "")
    hist = trace_dir / "history.txt"
    if hist.is_file():
        ht = hist.read_text(errors="replace")
        m = re.search(r"'done':\s*\{'text':\s*\"((?:\\\"|[^\"])*)\"", ht)
        if not m:
            m = re.search(r"'done':\s*\{'text':\s*'((?:\\'|[^'])*)'", ht)
        if m:
            text = m.group(1).replace("\\n", "\n").replace('\\"', '"').replace("\\'", "'")

    likes: list[str] = []
    dislikes: list[str] = []
    difficulty = ""
    if "LIKED" in text or "DISLIKED" in text:
        liked_m = re.search(
            r"Things I LIKED[^\n]*:\s*([\s\S]*?)(?:Things I DISLIKED|How hard this felt:|$)",
            text,
            re.I,
        )
        dis_m = re.search(
            r"Things I DISLIKED[^\n]*:\s*([\s\S]*?)(?:How hard this felt:|$)",
            text,
            re.I,
        )
        hard_m = re.search(r"How hard this felt:\s*(\w+)", text, re.I)
        if liked_m:
            likes = _bullet_lines(liked_m.group(1))
        if dis_m:
            dislikes = _bullet_lines(dis_m.group(1))
        if hard_m:
            difficulty = hard_m.group(1).lower()
    quote = ""
    if likes:
        quote = likes[0][:220]
    summary_parts = []
    if likes:
        summary_parts.append("Liked: " + "; ".join(likes[:3]))
    if dislikes:
        summary_parts.append("Disliked: " + "; ".join(dislikes[:3]))
    if difficulty:
        summary_parts.append(f"Difficulty: {difficulty}")
    return {
        "likes": likes,
        "dislikes": dislikes,
        "difficulty": difficulty or ("easy" if run.get("success") else "hard"),
        "quote": quote,
        "summary": " · ".join(summary_parts),
    }


def _bullet_lines(block: str) -> list[str]:
    lines = []
    for ln in block.strip().splitlines():
        ln = re.sub(r"^\d+\.\s*", "", ln.strip())
        if ln:
            lines.append(ln)
    return lines


def _goal_prompt(task: str) -> str:
    if "USER GOAL:" in task:
        m = re.search(r"USER GOAL:\s*(.+?)\nSUCCESS:", task, re.S)
        if m:
            return m.group(1).strip()
    return task[:400]


def _persona_id_from_runs(runs: list[dict]) -> str:
    for r in runs:
        if r.get("persona_id"):
            return r["persona_id"]
    return "unknown"


def _persona_name(runs: list[dict]) -> str:
    for r in runs:
        if r.get("persona_name"):
            return r["persona_name"]
    return "Persona"


def _comparative_for_goal(comparative: dict, persona_id: str | None, goal_key: str) -> dict:
    for rev in comparative.get("reviews") or []:
        if rev.get("persona_id") == persona_id and rev.get("goal_key") == goal_key:
            return rev
    return {}


def _derive_preference(block_runs: list[dict], comp_review: dict | None = None) -> str | None:
    """Pick preferred platform for a matched triplet (explicit review or heuristic)."""
    if comp_review and comp_review.get("most_likely_to_use"):
        return comp_review["most_likely_to_use"]
    by_plat = {r.get("website"): r for r in block_runs if r.get("website")}
    successes = [p for p in PLATFORMS if by_plat.get(p, {}).get("success")]
    if len(successes) == 1:
        return successes[0]
    if len(successes) > 1:
        return min(successes, key=lambda p: by_plat[p].get("num_actions") or 9999)
    # No success: prefer non-BLOCKED with most progress
    candidates = []
    for p in PLATFORMS:
        r = by_plat.get(p)
        if not r:
            continue
        if r.get("status") == "BLOCKED":
            continue
        candidates.append((p, r.get("num_actions") or 0))
    if candidates:
        return max(candidates, key=lambda x: x[1])[0]
    # likes heuristic from enriched results would need feedback — skip
    return None


def _build_analytics(
    manifest: dict,
    runs: list[dict],
    agent_results: list[dict],
    comparative: dict,
    is_full270: bool,
) -> dict:
    eligible = [r for r in runs if r.get("status") != "BLOCKED"]
    successes = sum(1 for r in eligible if r.get("success"))
    n_eligible = len(eligible)

    def plat_stats(subset: list[dict]) -> dict:
        out: dict[str, dict] = {}
        for p in PLATFORMS:
            pr = [r for r in subset if r.get("website") == p]
            if not pr:
                continue
            el = [r for r in pr if r.get("status") != "BLOCKED"]
            ok = sum(1 for r in el if r.get("success"))
            out[p] = {
                "total": len(pr),
                "eligible": len(el),
                "success": ok,
                "rate": round(ok / max(1, len(el)), 4),
                "blocked": sum(1 for r in pr if r.get("status") == "BLOCKED"),
            }
        return out

    success_by_platform = plat_stats(runs)

    # Group runs by comparative block
    blocks: dict[str, list[dict]] = {}
    for r in runs:
        bid = r.get("comparative_group") or r.get("goal_key") or "unknown"
        blocks.setdefault(bid, []).append(r)

    preference_by_platform: dict[str, int] = {p: 0 for p in PLATFORMS}
    success_wins_by_platform: dict[str, int] = {p: 0 for p in PLATFORMS}
    block_preferences: list[dict] = []

    for block_id, block_runs in blocks.items():
        sample = block_runs[0]
        comp = _comparative_for_goal(
            comparative, sample.get("persona_id"), sample.get("goal_key")
        )
        pref = _derive_preference(block_runs, comp)
        if pref:
            preference_by_platform[pref] = preference_by_platform.get(pref, 0) + 1
        succ_plat = [r.get("website") for r in block_runs if r.get("success")]
        if len(succ_plat) == 1:
            success_wins_by_platform[succ_plat[0]] = success_wins_by_platform.get(succ_plat[0], 0) + 1
        block_preferences.append(
            {
                "block_id": block_id,
                "persona_id": sample.get("persona_id"),
                "goal_key": sample.get("goal_key"),
                "seed": _seed_from_block(block_id),
                "preferred": pref,
                "success_platforms": succ_plat,
            }
        )

    # Persona × platform matrices
    persona_ids = sorted({r.get("persona_id") for r in runs if r.get("persona_id")})
    persona_success_matrix: dict[str, dict] = {}
    persona_preference_matrix: dict[str, dict] = {}
    for pid in persona_ids:
        persona_success_matrix[pid] = plat_stats([r for r in runs if r.get("persona_id") == pid])
        prefs = [b for b in block_preferences if b.get("persona_id") == pid and b.get("preferred")]
        persona_preference_matrix[pid] = {p: 0 for p in PLATFORMS}
        for b in prefs:
            persona_preference_matrix[pid][b["preferred"]] += 1

    # Journey (task type) breakdown
    journey_keys = sorted(
        {r.get("goal_key") for r in runs if r.get("goal_key")},
        key=lambda k: JOURNEY_META.get(k, {}).get("ord", 99),
    )
    by_journey: list[dict] = []
    journey_preference: dict[str, dict[str, int]] = {}
    for gk in journey_keys:
        jr = [r for r in runs if r.get("goal_key") == gk]
        jmeta = JOURNEY_META.get(gk, {})
        jprefs = {p: 0 for p in PLATFORMS}
        for bid, br in blocks.items():
            if br[0].get("goal_key") != gk:
                continue
            comp = _comparative_for_goal(comparative, br[0].get("persona_id"), gk)
            pref = _derive_preference(br, comp)
            if pref:
                jprefs[pref] += 1
        journey_preference[gk] = jprefs
        by_journey.append(
            {
                "goal_key": gk,
                "title": jr[0].get("goal_title") if jr else gk,
                "category": jmeta.get("category", gk),
                "ord": jmeta.get("ord", 99),
                "platforms": plat_stats(jr),
                "preference_counts": jprefs,
                "success_total": sum(1 for r in jr if r.get("success")),
                "total": len(jr),
            }
        )

    by_persona: list[dict] = []
    for pid in persona_ids:
        pr = [r for r in runs if r.get("persona_id") == pid]
        pname = next((r.get("persona_name") for r in pr if r.get("persona_name")), pid)
        pref_counts = persona_preference_matrix.get(pid, {})
        top_pref = max(PLATFORMS, key=lambda p: pref_counts.get(p, 0)) if pref_counts else None
        by_persona.append(
            {
                "persona_id": pid,
                "persona_name": pname,
                "platforms": persona_success_matrix.get(pid, {}),
                "preference_counts": pref_counts,
                "top_preference": top_pref if pref_counts.get(top_pref or "", 0) else None,
                "success_total": sum(1 for r in pr if r.get("success")),
                "total": len(pr),
            }
        )

    total_pref = sum(preference_by_platform.values()) or 1
    avg_preference_share = {
        p: round(preference_by_platform.get(p, 0) / total_pref, 4) for p in PLATFORMS
    }

    return {
        "n": manifest.get("n") or len(runs),
        "successes": manifest.get("successes") or sum(1 for r in runs if r.get("success")),
        "success_rate_raw": round((manifest.get("successes") or 0) / max(1, len(runs)), 4),
        "success_rate_scored": round(successes / max(1, n_eligible), 4),
        "n_eligible": n_eligible,
        "by_status": manifest.get("by_status") or {},
        "total_cost_usd": manifest.get("total_cost_usd"),
        "success_by_platform": success_by_platform,
        "preference_by_platform": preference_by_platform,
        "preference_share": avg_preference_share,
        "success_wins_by_platform": success_wins_by_platform,
        "persona_success_matrix": persona_success_matrix,
        "persona_preference_matrix": persona_preference_matrix,
        "by_journey": by_journey,
        "journey_preference": journey_preference,
        "by_persona": by_persona,
        "block_preferences": block_preferences,
        "is_full270": is_full270,
        "has_comparative_reviews": bool(comparative.get("reviews")),
    }


def _build_summary(comparative: dict, agent_results: list[dict]) -> dict:
    reviews = comparative.get("reviews") or []
    winners: dict[str, int] = {}
    for rev in reviews:
        w = rev.get("most_likely_to_use")
        if w:
            winners[w] = winners.get(w, 0) + 1
    top_friction = []
    top_strengths = []
    for r in agent_results:
        for d in r.get("dislikes") or []:
            top_friction.append(f"{PLATFORM_LABEL.get(r.get('platform',''), r.get('platform'))}: {d}")
        for lk in r.get("likes") or []:
            top_strengths.append(f"{PLATFORM_LABEL.get(r.get('platform',''), r.get('platform'))}: {lk}")
    return {
        "winner_counts": winners,
        "top_friction": top_friction[:8],
        "top_strengths": top_strengths[:8],
        "fit_score": "—",
        "fit_rationale": "Synthetic persona comparative bakeoff (Bland vs Vapi vs Retell).",
        "conversion_outlook": "",
        "recommendations": [
            {
                "title": rev.get("goal_key", "Goal"),
                "body": rev.get("why_winner", ""),
                "priority": rev.get("most_likely_to_use", ""),
            }
            for rev in reviews[:5]
        ],
    }
