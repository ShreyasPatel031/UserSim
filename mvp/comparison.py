"""Head-to-head scoring: where the product is better or worse than each rival.

Task completion only tells us whether our agents worked. A buyer wants to
know which product serves which kind of customer on which job, and that
still holds when the rivals are demo-only. After every agent finishes, the
Gemini judge scores each (persona, task, site) run from its real trace
(the step list with URLs, the final URL and page text, and the final
screenshot):

  in_product       the persona did the job inside the product       7-10
  clear_evidence   the website clearly shows how it does the job    4-7
  vague_marketing  only claims, no proof or detail                  2-4
  wall_or_nothing  a demo/signup wall or nothing relevant           0-2

It also scores friction (0 none to 3 severe) and gives a one-sentence
reason tied to a step. ``build_comparison`` turns the scores into per-task
winners (with the product's rank), per-persona picks, and the product's
strengths and weaknesses against each rival, each citing runs, steps and
screenshots. Nothing here reads the agent's own "done" claim.
"""

from __future__ import annotations

import asyncio
import os
import re
import statistics
import time
from typing import Any

LEVELS = ("in_product", "clear_evidence", "vague_marketing", "wall_or_nothing")
_LEVEL_BANDS = {
    "in_product": (7.0, 10.0),
    "clear_evidence": (4.0, 7.0),
    "vague_marketing": (2.0, 4.0),
    "wall_or_nothing": (0.0, 2.0),
}
# A task-level gap this large (0-10 scale) counts as a strength or weakness.
EDGE = float(os.environ.get("MVP_COMPARE_EDGE", "1.5"))


def _base_task(run: dict[str, Any]) -> str:
    """The task as the planner wrote it, without the rival-site wrapper."""
    title = str(run.get("task_title") or run.get("task_prompt") or "")
    return re.sub(r"\s*\(vs https?://\S+\)\s*$", "", title).strip()


def _trace_lines(run: dict[str, Any], limit: int = 30) -> list[str]:
    lines: list[str] = []
    for step in run.get("trace") or []:
        if not isinstance(step, dict):
            continue
        action = " ".join(str(step.get("action") or "").split())[:140]
        if not action:
            continue
        lines.append(f"step {step.get('step')}: {action} @ {str(step.get('url') or '')[:120]}")
    if len(lines) > limit:
        lines = lines[:5] + ["..."] + lines[-(limit - 6):]
    return lines


def site_name(site_url: str, names: dict[str, str] | None = None) -> str:
    for raw, name in (names or {}).items():
        if name and _host(raw) == _host(site_url):
            return name
    host = _host(site_url)
    return host.split(".")[0].capitalize() if host else site_url


def _host(url: str) -> str:
    m = re.match(r"(?:https?://)?([^/]+)", str(url or "").strip())
    return (m.group(1).lower().removeprefix("www.") if m else "")


def score_prompt(run: dict[str, Any], persona: dict[str, Any], *, site_label: str, is_product: bool) -> str:
    signup = run.get("signup") if isinstance(run.get("signup"), dict) else {}
    if signup.get("ok"):
        access = "The agent created a trial account and worked inside the product."
    elif run.get("website_eval"):
        access = (
            "The site had no self-serve account (demo or sales wall at "
            f"{(run.get('website_eval') or {}).get('wall_url') or 'the signup step'}), so the agent judged it from the website."
        )
    else:
        access = "The agent used the public website (no account)."
    dom = " ".join(str(run.get("final_dom") or run.get("observation") or "").split())[:2200]
    steps = "\n".join(_trace_lines(run)) or "(no steps recorded)"
    return f"""You score one run of a product comparison study. Judge only the evidence below (the trace, the final URL, the final page text and the screenshot). Do not trust the agent's own claims.

Buyer persona: {persona.get('name') or ''}, {persona.get('occupation') or ''}. {persona.get('bio') or ''}
Job to be done: {_base_task(run)}
Site: {site_label} ({run.get('site_url') or ''}){' - the product under study' if is_product else ' - a competitor'}
Access: {access}
Step trace:
{steps}
Final URL: {run.get('final_url') or ''}
Final page text (truncated): {dom or '(none)'}

How well did this persona get what they needed for this job on this site?
level:
- in_product: the persona actually did the job (or saw the real result) inside the product. Score 7-10.
- clear_evidence: the website clearly shows how the product does this job (feature detail, screenshots, docs, transparent pricing, customer proof), fast. Score 4-7.
- vague_marketing: only generic claims; the persona still cannot tell if or how it does the job. Score 2-4.
- wall_or_nothing: blocked by a demo, signup or error wall, or nothing relevant was found. Score 0-2.
Doing the job in the product always beats reading about it. Within a band, score higher for less friction and a faster, clearer answer for this persona.
friction: 0 none, 1 minor, 2 major, 3 severe (walls, dead ends, loops, confusing UI).

Return JSON only:
{{"level": "in_product|clear_evidence|vague_marketing|wall_or_nothing",
  "score": 0-10,
  "friction": 0-3,
  "reason": "one sentence naming what the page or trace shows",
  "evidence_step": step number that best shows it,
  "friction_note": "at most 12 words, or empty"}}"""


def coerce_score(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    level = str(raw.get("level") or "").strip().lower()
    if level not in _LEVEL_BANDS:
        return None
    lo, hi = _LEVEL_BANDS[level]
    try:
        score = float(raw.get("score"))
    except (TypeError, ValueError):
        score = (lo + hi) / 2
    score = max(lo, min(hi, score))
    try:
        friction = int(raw.get("friction") or 0)
    except (TypeError, ValueError):
        friction = 0
    try:
        step = int(raw.get("evidence_step")) if raw.get("evidence_step") is not None else None
    except (TypeError, ValueError):
        step = None
    return {
        "level": level,
        "score": round(score, 1),
        "friction": max(0, min(3, friction)),
        "reason": " ".join(str(raw.get("reason") or "").split())[:300],
        "evidence_step": step,
        "friction_note": " ".join(str(raw.get("friction_note") or "").split())[:120],
    }


def _merged_runs(study: Any) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """agent_results rows with live-session fields (trace, final shot) filled in."""
    live = getattr(study, "live_sessions", None)
    if live is None and isinstance(study, dict):
        live = study.get("live_sessions")
    rows = {}
    for row in (list(live.values()) if isinstance(live, dict) else list(live or [])):
        if isinstance(row, dict) and row.get("agent_id"):
            rows[str(row["agent_id"])] = row
    results = getattr(study, "agent_results", None)
    if results is None and isinstance(study, dict):
        results = study.get("agent_results")
    return [r for r in (results or []) if isinstance(r, dict)], rows


async def apply_comparison_scores(study: Any, *, timeout_s: float | None = None) -> int:
    """Score every run once (stored as run['comparison_score']); returns how many were scored."""
    if os.environ.get("MVP_COMPARE_SCORE", "1") == "0":
        return 0
    from mvp.e2e_ui_run import gemini_vision_json
    from mvp.paths import MVP_RUNS_DIR

    results, live = _merged_runs(study)
    personas = {str(p.get("id")): p for p in (getattr(study, "personas", None) or []) if isinstance(p, dict)}
    names = dict(getattr(study, "competitor_names", None) or {})
    product_label = str(getattr(study, "product_name", "") or "") or site_name(str(getattr(study, "url", "")))
    sem = asyncio.Semaphore(int(os.environ.get("MVP_COMPARE_SCORE_CONCURRENCY", "16")))
    budget = float(timeout_s or os.environ.get("MVP_COMPARE_SCORE_TIMEOUT_S", "45"))
    model = os.environ.get("MVP_COMPARE_JUDGE_MODEL", "gemini-2.5-flash")
    written = 0

    async def one(result: dict[str, Any]) -> None:
        nonlocal written
        aid = str(result.get("agent_id") or "")
        run = {**live.get(aid, {}), **result}
        is_product = str(run.get("site_key") or "") == "product"
        label = product_label if is_product else site_name(str(run.get("site_url") or ""), names)
        path = MVP_RUNS_DIR / str(getattr(study, "id", "")) / aid / "screenshots" / "final.png"
        if not path.is_file() or path.stat().st_size < 2000:
            # No final page to look at (lost browser): leave it out of the comparison.
            result["comparison_score"] = {"level": None, "score": None, "reason": "no final screenshot", "excluded": True}
            return
        prompt = score_prompt(run, personas.get(str(run.get("persona_id")), {}), site_label=label, is_product=is_product)
        async with sem:
            try:
                raw = await asyncio.wait_for(
                    asyncio.to_thread(gemini_vision_json, prompt, path.read_bytes(), model=model), timeout=budget
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[comparison] {aid} score failed: {exc!r}"[:200], flush=True)
                return
        score = coerce_score(raw)
        if score is None:
            return
        score["scored_at_ts"] = time.time()
        score["model"] = model
        result["comparison_score"] = score
        written += 1

    await asyncio.gather(*(one(r) for r in results))
    print(f"[comparison] {written}/{len(results)} runs scored", flush=True)
    return written


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 1) if values else None


def _cite(run: dict[str, Any]) -> dict[str, Any]:
    sc = run.get("comparison_score") or {}
    return {
        "agent_id": run.get("agent_id"),
        "persona_id": run.get("persona_id"),
        "site_key": run.get("site_key"),
        "score": sc.get("score"),
        "level": sc.get("level"),
        "reason": sc.get("reason"),
        "step": sc.get("evidence_step"),
        "final_url": run.get("final_url"),
        "screenshot": run.get("final_screenshot_url") or run.get("final_screenshot"),
    }


def build_comparison(study: dict[str, Any]) -> dict[str, Any] | None:
    """Per-task winners, per-persona picks, strengths and weaknesses vs each rival. None without scores."""
    runs = [
        r for r in (study.get("agent_results") or [])
        if isinstance(r, dict) and isinstance((r.get("comparison_score") or {}).get("score"), (int, float))
    ]
    if not runs:
        return None
    names = dict(study.get("competitor_names") or {})
    product_label = str(study.get("product_name") or "") or site_name(str(study.get("url") or ""))
    site_urls: dict[str, str] = {}
    for r in study.get("agent_results") or []:
        if isinstance(r, dict) and r.get("site_key"):
            site_urls.setdefault(str(r["site_key"]), str(r.get("site_url") or ""))
    sites = sorted(site_urls, key=lambda k: (k != "product", k))
    labels = {k: (product_label if k == "product" else site_name(site_urls[k], names)) for k in sites}
    url_to_key = {_host(u): k for k, u in site_urls.items()}
    personas = {str(p.get("id")): p for p in (study.get("personas") or []) if isinstance(p, dict)}
    specs = {str(t.get("prompt") or ""): t for t in (study.get("task_specs") or []) if isinstance(t, dict)}

    def favored_key(value: str) -> str:
        if not value:
            return ""
        return "product" if value == "product" else url_to_key.get(_host(value), "")

    tasks: list[str] = []
    for r in runs:
        t = _base_task(r)
        if t not in tasks:
            tasks.append(t)

    def cell(task: str | None, pid: str | None, site: str) -> list[dict[str, Any]]:
        return [
            r for r in runs
            if r.get("site_key") == site
            and (task is None or _base_task(r) == task)
            and (pid is None or str(r.get("persona_id")) == pid)
        ]

    def score_of(rows: list[dict[str, Any]]) -> float | None:
        return _mean([float(r["comparison_score"]["score"]) for r in rows])

    def best(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        return max(rows, key=lambda r: float(r["comparison_score"]["score"]), default=None)

    def ranked(scores: dict[str, float | None]) -> list[str]:
        return sorted([k for k, v in scores.items() if v is not None], key=lambda k: -float(scores[k]))

    by_task = []
    for t in tasks:
        scores = {s: score_of(cell(t, None, s)) for s in sites}
        order = ranked(scores)
        winner = order[0] if order else ""
        levels = {
            s: statistics.mode([r["comparison_score"]["level"] for r in cell(t, None, s)]) if cell(t, None, s) else None
            for s in sites
        }
        spec = specs.get(t, {})
        win_run = best(cell(t, None, winner)) if winner else None
        prod_run = best(cell(t, None, "product"))
        by_task.append(
            {
                "task": t,
                "expected_favorite": favored_key(str(spec.get("favors") or "")),
                "expected_why": spec.get("favors_why") or "",
                "scores": scores,
                "levels": levels,
                "winner": winner,
                "winner_label": labels.get(winner, winner),
                "product_rank": (order.index("product") + 1) if "product" in order else None,
                "n_sites": len(order),
                "why": (win_run or {}).get("comparison_score", {}).get("reason", ""),
                "winner_evidence": _cite(win_run) if win_run else None,
                "product_evidence": _cite(prod_run) if prod_run else None,
            }
        )

    by_persona = []
    for pid, p in personas.items():
        scores = {s: score_of(cell(None, pid, s)) for s in sites}
        order = ranked(scores)
        if not order:
            continue
        pick = order[0]
        by_persona.append(
            {
                "persona_id": pid,
                "name": p.get("name"),
                "role": p.get("occupation") or "",
                "expected_favorite": favored_key(str(p.get("favors") or "")),
                "expected_why": p.get("favors_why") or "",
                "scores": scores,
                "pick": pick,
                "pick_label": labels.get(pick, pick),
                "product_wins": pick == "product",
                "product_rank": (order.index("product") + 1) if "product" in order else None,
            }
        )

    versus = []
    for comp in [s for s in sites if s != "product"]:
        strengths, weaknesses = [], []
        for row in by_task:
            ps, cs = row["scores"].get("product"), row["scores"].get(comp)
            if ps is None or cs is None:
                continue
            gap = round(ps - cs, 1)
            if abs(gap) < EDGE:
                continue
            pr, cr = best(cell(row["task"], None, "product")), best(cell(row["task"], None, comp))
            item = {
                "task": row["task"],
                "product_score": ps,
                "competitor_score": cs,
                "gap": gap,
                "product_level": row["levels"].get("product"),
                "competitor_level": row["levels"].get(comp),
                "product_evidence": _cite(pr) if pr else None,
                "competitor_evidence": _cite(cr) if cr else None,
            }
            (strengths if gap > 0 else weaknesses).append(item)
        strengths.sort(key=lambda i: -i["gap"])
        weaknesses.sort(key=lambda i: i["gap"])
        overall_p = score_of(cell(None, None, "product"))
        overall_c = score_of(cell(None, None, comp))
        versus.append(
            {
                "competitor": comp,
                "label": labels[comp],
                "url": site_urls.get(comp),
                "product_overall": overall_p,
                "competitor_overall": overall_c,
                "strengths": strengths,
                "weaknesses": weaknesses,
            }
        )

    wins = [r for r in by_task if r["winner"] == "product"]
    losses = [r for r in by_task if r["winner"] and r["winner"] != "product"]
    return {
        "product_label": product_label,
        "sites": [{"key": s, "label": labels[s], "url": site_urls[s]} for s in sites],
        "n_scored": len(runs),
        "overall": {s: score_of(cell(None, None, s)) for s in sites},
        "by_task": by_task,
        "by_persona": by_persona,
        "versus": versus,
        "wins": [{"task": r["task"], "why": r["why"], "runner_up": _runner_up(r, labels)} for r in wins],
        "losses": [
            {"task": r["task"], "winner": r["winner_label"], "product_rank": r["product_rank"], "why": r["why"]}
            for r in losses
        ],
        "personas_won": [p["name"] for p in by_persona if p["product_wins"]],
        "personas_lost": [{"name": p["name"], "pick": p["pick_label"]} for p in by_persona if not p["product_wins"]],
    }


def _runner_up(row: dict[str, Any], labels: dict[str, str]) -> str:
    order = sorted(
        [k for k, v in row["scores"].items() if v is not None and k != row["winner"]],
        key=lambda k: -float(row["scores"][k]),
    )
    return labels.get(order[0], order[0]) if order else ""
