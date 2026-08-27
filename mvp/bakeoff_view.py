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
}

PLATFORM_LABEL = {"bland": "Bland AI", "vapi": "Vapi", "retell": "Retell AI"}


def list_studies() -> list[dict]:
    out: list[dict] = []
    if not CAPABILITY_DIR.is_dir():
        return out
    for path in sorted(CAPABILITY_DIR.glob("product_persona_p*_browser_use_*_all_v1.json")):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        pid = _persona_id_from_runs(data.get("runs") or [])
        out.append(
            {
                "id": path.stem,
                "path": str(path),
                "persona_id": pid,
                "persona_name": _persona_name(data.get("runs") or []),
                "n_runs": data.get("n") or len(data.get("runs") or []),
                "successes": data.get("successes"),
                "stage": data.get("stage"),
            }
        )
    # Full rollup manifest if present
    full = CAPABILITY_DIR / "product_persona_browser_use_all.json"
    if full.is_file():
        try:
            data = json.loads(full.read_text())
            out.insert(
                0,
                {
                    "id": full.stem,
                    "path": str(full),
                    "persona_id": "all",
                    "persona_name": "All personas",
                    "n_runs": data.get("n"),
                    "successes": data.get("successes"),
                    "stage": data.get("stage"),
                },
            )
        except (json.JSONDecodeError, OSError):
            pass
    return out


def load_study(study_id: str) -> dict:
    path = CAPABILITY_DIR / f"{study_id}.json"
    if not path.is_file():
        raise FileNotFoundError(study_id)
    manifest = json.loads(path.read_text())
    runs = manifest.get("runs") or []
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
    if not comp_path.is_file():
        alt = CAPABILITY_DIR / f"persona_{persona_ids[0].replace('_ops','').replace('_fde','').replace('_outbound','').replace('_eng','').replace('_compliance','').replace('_founder','')}_comparative.json"
        # e.g. persona_p1_comparative.json
        m = re.search(r"p(\d+)_", persona_ids[0] if persona_ids else "")
        if m:
            alt = CAPABILITY_DIR / f"persona_p{m.group(1)}_comparative.json"
        comp_path = alt if alt.is_file() else comp_path
    comparative = {}
    if comp_path.is_file():
        comparative = json.loads(comp_path.read_text())

    goals = sorted({r.get("goal_key") for r in runs if r.get("goal_key")})
    tasks = []
    agent_results = []

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
                "title": sample.get("goal_title") or goal_key,
                "prompt": _goal_prompt(sample.get("task") or ""),
            }
        )
        comp_review = _comparative_for_goal(comparative, sample.get("persona_id"), goal_key)

        for r in goal_runs:
            trace_dir = Path(r.get("trace_dir") or "")
            trace = parse_trace_steps(trace_dir)
            feedback = _extract_feedback(r, trace)
            agent_results.append(
                {
                    "agent_id": f"{r.get('eval_index')}_{r.get('website')}",
                    "task_id": task_id,
                    "persona_id": r.get("persona_id"),
                    "persona_name": r.get("persona_name"),
                    "task_title": f"{sample.get('goal_title')} — {PLATFORM_LABEL.get(r.get('website',''), r.get('website'))}",
                    "task_prompt": _goal_prompt(r.get("task") or ""),
                    "platform": r.get("website"),
                    "goal_key": goal_key,
                    "status": "complete",
                    "success": bool(r.get("success")),
                    "judge_status": r.get("status"),
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
            )

    return {
        "study_id": study_id,
        "status": "complete",
        "phase": "Complete",
        "headline": f"Persona bakeoff — {manifest.get('successes', 0)}/{manifest.get('n', 0)} tasks succeeded",
        "personas": personas,
        "tasks": tasks,
        "agent_results": agent_results,
        "comparative": comparative,
        "summary": _build_summary(comparative, agent_results),
    }


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
