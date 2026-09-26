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
  "quote": "up to 20 words copied exactly from the final page text that back the reason, or empty",
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
        "quote": " ".join(str(raw.get("quote") or "").split())[:200],
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


LEVEL_RANK = {"in_product": 3, "clear_evidence": 2, "vague_marketing": 1, "wall_or_nothing": 0}
LEVEL_LABEL = {
    "in_product": "done in product",
    "clear_evidence": "clear on website",
    "vague_marketing": "vague marketing",
    "wall_or_nothing": "wall",
}


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 1) if values else None


def _sc(run: dict[str, Any]) -> dict[str, Any]:
    return run.get("comparison_score") or {}


def _quote(run: dict[str, Any]) -> str:
    q = str(_sc(run).get("quote") or "").strip()
    if q:
        return q
    dom = " ".join(str(run.get("final_dom") or "").split())
    return (dom[:160] + "…") if len(dom) > 160 else dom


def _cite(run: dict[str, Any]) -> dict[str, Any]:
    sc = _sc(run)
    return {
        "agent_id": run.get("agent_id"),
        "persona_id": run.get("persona_id"),
        "site_key": run.get("site_key"),
        "task": _base_task(run),
        "score": sc.get("score"),
        "level": sc.get("level"),
        "friction": sc.get("friction"),
        "reason": sc.get("reason"),
        "step": sc.get("evidence_step"),
        "quote": _quote(run),
        "final_url": run.get("final_url"),
        "screenshot": run.get("final_screenshot_url") or run.get("final_screenshot"),
    }


def rank_sites(rows_by_site: dict[str, list[dict[str, Any]]]) -> list[list[str]]:
    """Sites best first as tiers. Mean score, then best level, then lower mean friction; equal = tie."""

    def key(site: str) -> tuple[float, int, float]:
        rows = rows_by_site[site]
        mean = statistics.fmean(float(_sc(r)["score"]) for r in rows)
        best_level = max(LEVEL_RANK.get(str(_sc(r).get("level")), 0) for r in rows)
        friction = statistics.fmean(float(_sc(r).get("friction") or 0) for r in rows)
        return (round(mean, 1), best_level, -round(friction, 2))

    present = [s for s, rows in rows_by_site.items() if rows]
    tiers: list[list[str]] = []
    for site in sorted(present, key=key, reverse=True):
        if tiers and key(tiers[-1][0]) == key(site):
            tiers[-1].append(site)
        else:
            tiers.append([site])
    return tiers


def _rank_of(tiers: list[list[str]], site: str) -> int | None:
    pos = 1
    for tier in tiers:
        if site in tier:
            return pos
        pos += len(tier)
    return None


def build_comparison(study: dict[str, Any]) -> dict[str, Any] | None:
    """Per-task winners, per-persona picks, wins/losses and strengths vs each rival. None without scores."""
    runs = [
        r for r in (study.get("agent_results") or [])
        if isinstance(r, dict) and isinstance(_sc(r).get("score"), (int, float))
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
    llm = dict((study.get("summary") or {}).get("comparison_llm") or {})

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
        return _mean([float(_sc(r)["score"]) for r in rows])

    def best(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        return max(
            rows,
            key=lambda r: (float(_sc(r)["score"]), LEVEL_RANK.get(str(_sc(r).get("level")), 0), -float(_sc(r).get("friction") or 0)),
            default=None,
        )

    def level_of(rows: list[dict[str, Any]]) -> str | None:
        if not rows:
            return None
        # The level most runs reached; ties go to the higher level.
        counts: dict[str, int] = {}
        for r in rows:
            counts[str(_sc(r).get("level"))] = counts.get(str(_sc(r).get("level")), 0) + 1
        return max(counts, key=lambda lv: (counts[lv], LEVEL_RANK.get(lv, 0)))

    by_task = []
    for t in tasks:
        tiers = rank_sites({s: cell(t, None, s) for s in sites})
        top = tiers[0] if tiers else []
        winner = top[0] if len(top) == 1 else ""
        spec = specs.get(t, {})
        win_run = best(cell(t, None, winner)) if winner else None
        prod_run = best(cell(t, None, "product"))
        by_task.append(
            {
                "task": t,
                "expected_favorite": favored_key(str(spec.get("favors") or "")),
                "expected_why": spec.get("favors_why") or "",
                "scores": {s: score_of(cell(t, None, s)) for s in sites},
                "levels": {s: level_of(cell(t, None, s)) for s in sites},
                "winner": winner,
                "tied": top if len(top) > 1 else [],
                "winner_label": labels.get(winner, "") if winner else "Tie: " + " = ".join(labels[k] for k in top),
                "product_rank": _rank_of(tiers, "product"),
                "n_sites": sum(len(x) for x in tiers),
                "why": _sc(win_run or {}).get("reason", "") if win_run else "",
                "winner_evidence": _cite(win_run) if win_run else None,
                "product_evidence": _cite(prod_run) if prod_run else None,
            }
        )

    picks_llm = {str(p.get("persona_id")): p for p in (llm.get("picks") or []) if isinstance(p, dict)}
    by_persona = []
    for pid, p in personas.items():
        tiers = rank_sites({s: cell(None, pid, s) for s in sites})
        if not tiers:
            continue
        score_pick = tiers[0][0] if len(tiers[0]) == 1 else ""
        chosen = picks_llm.get(pid) or {}
        pick = chosen.get("pick") if chosen.get("pick") in sites else score_pick
        by_persona.append(
            {
                "persona_id": pid,
                "name": p.get("name"),
                "role": p.get("occupation") or "",
                "bio": p.get("bio") or "",
                "expected_favorite": favored_key(str(p.get("favors") or "")),
                "expected_why": p.get("favors_why") or "",
                "scores": {s: score_of(cell(None, pid, s)) for s in sites},
                "score_pick": score_pick,
                "score_tied": tiers[0] if len(tiers[0]) > 1 else [],
                "pick": pick or "",
                "pick_label": labels.get(pick, "") if pick else "Tie: " + " = ".join(labels[k] for k in tiers[0]),
                "pick_source": "persona" if chosen.get("pick") in sites else "scores",
                "pick_why": chosen.get("why") or "",
                "pick_cites": [c for c in (chosen.get("cites") or []) if isinstance(c, str)],
                "product_wins": pick == "product",
                "product_rank": _rank_of(tiers, "product"),
            }
        )
    pick_counts = {s: sum(1 for p in by_persona if p["pick"] == s) for s in sites}
    ties = sum(1 for p in by_persona if not p["pick"])

    # Wins and losses: product vs one rival for one persona on one task.
    pairs = []
    for comp in [s for s in sites if s != "product"]:
        for t in tasks:
            for pid in personas:
                pr, cr = best(cell(t, pid, "product")), best(cell(t, pid, comp))
                if not pr or not cr:
                    continue
                gap = round(float(_sc(pr)["score"]) - float(_sc(cr)["score"]), 1)
                if gap == 0:
                    lv = LEVEL_RANK.get(str(_sc(pr).get("level")), 0) - LEVEL_RANK.get(str(_sc(cr).get("level")), 0)
                    if lv == 0:
                        continue
                pairs.append(
                    {
                        "competitor": comp,
                        "competitor_label": labels[comp],
                        "persona_id": pid,
                        "persona": (personas.get(pid) or {}).get("name") or pid,
                        "task": t,
                        "product_score": _sc(pr)["score"],
                        "competitor_score": _sc(cr)["score"],
                        "gap": gap,
                        "reason": _sc(pr if gap > 0 else cr).get("reason") or "",
                        "product_evidence": _cite(pr),
                        "competitor_evidence": _cite(cr),
                    }
                )

    def top_pairs(items: list[dict[str, Any]], n: int = 5) -> list[dict[str, Any]]:
        # Largest gaps first, one row per (rival, task) so the list is not one task repeated.
        out, seen = [], set()
        for item in items:
            key = (item["competitor"], item["task"])
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
            if len(out) == n:
                break
        return out

    wins = top_pairs(sorted([x for x in pairs if x["gap"] > 0], key=lambda x: -x["gap"]))
    losses = top_pairs(sorted([x for x in pairs if x["gap"] < 0], key=lambda x: x["gap"]))

    versus = []
    for comp in [s for s in sites if s != "product"]:
        strengths, weaknesses = [], []
        for row in by_task:
            ps, cs = row["scores"].get("product"), row["scores"].get(comp)
            if ps is None or cs is None or abs(ps - cs) < EDGE:
                continue
            pr, cr = best(cell(row["task"], None, "product")), best(cell(row["task"], None, comp))
            item = {
                "task": row["task"],
                "product_score": ps,
                "competitor_score": cs,
                "gap": round(ps - cs, 1),
                "product_level": row["levels"].get("product"),
                "competitor_level": row["levels"].get(comp),
                "product_evidence": _cite(pr) if pr else None,
                "competitor_evidence": _cite(cr) if cr else None,
            }
            (strengths if item["gap"] > 0 else weaknesses).append(item)
        strengths.sort(key=lambda i: -i["gap"])
        weaknesses.sort(key=lambda i: i["gap"])
        versus.append(
            {
                "competitor": comp,
                "label": labels[comp],
                "url": site_urls.get(comp),
                "product_overall": score_of(cell(None, None, "product")),
                "competitor_overall": score_of(cell(None, None, comp)),
                "strengths": strengths,
                "weaknesses": weaknesses,
            }
        )

    fixes = sorted(
        [f for f in (llm.get("fixes") or []) if isinstance(f, dict)],
        key=lambda f: (-len(f.get("personas") or []), -len(f.get("moments") or [])),
    )
    headline_counts = ", ".join(
        f"{labels[s]}: {pick_counts[s]}" for s in sorted(sites, key=lambda k: (-pick_counts[k], k != "product", k))
    ) + (f", tie: {ties}" if ties else "")
    return {
        "product_label": product_label,
        "sites": [{"key": s, "label": labels[s], "url": site_urls[s]} for s in sites],
        "n_scored": len(runs),
        "n_personas": len(by_persona),
        "pick_counts": pick_counts,
        "pick_ties": ties,
        "headline_metric": f"{labels['product']}: {pick_counts.get('product', 0)} of {len(by_persona)} buyers"
        + "".join(f", {labels[s]}: {pick_counts[s]}" for s in sites if s != "product")
        + (f", tie: {ties}" if ties else ""),
        "headline_counts": headline_counts,
        "headline": llm.get("headline") or [],
        "overall": {s: score_of(cell(None, None, s)) for s in sites},
        "by_task": by_task,
        "by_persona": by_persona,
        "wins": wins,
        "losses": losses,
        "versus": versus,
        "first_impressions": llm.get("first_impressions") or [],
        "fixes": fixes,
        "level_labels": LEVEL_LABEL,
    }


# ---------------------------------------------------------------- model passes


async def _json_call(prompt: str, *, timeout: float = 40.0) -> Any:
    from capability.gemini_config import extract_json, gemini_chat

    raw = await asyncio.wait_for(
        gemini_chat(
            [{"role": "user", "content": prompt}],
            model=os.environ.get("MVP_COMPARE_JUDGE_MODEL", "gemini-2.5-flash"),
            temperature=0.2,
            json_mode=True,
            max_retries=2,
        ),
        timeout=timeout,
    )
    return extract_json(raw)


def _refs(rows: list[dict[str, Any]]) -> dict[str, str]:
    """Short run refs (R1, R2 ...) for prompts; models mangle ids like t1__p1__product."""
    return {f"R{i + 1}": str(r.get("agent_id")) for i, r in enumerate(rows)}


def _resolve(value: Any, refs: dict[str, str]) -> str:
    text = str(value or "").strip().strip("[]() ").upper()
    if text in refs:
        return refs[text]
    raw = str(value or "").strip().strip("[]() ")
    return raw if raw in refs.values() else ""


def _run_line(r: dict[str, Any], labels: dict[str, str], ref: str = "") -> str:
    sc = _sc(r)
    return (
        f"- [{ref or r.get('agent_id')}] {labels.get(str(r.get('site_key')), r.get('site_key'))} | {_base_task(r)} | "
        f"{sc.get('level')} {sc.get('score')}/10, friction {sc.get('friction')} | {sc.get('reason')}"
        + (f' | page says: "{_quote(r)[:140]}"' if _quote(r) else "")
    )


async def persona_pick(persona: dict[str, Any], rows: list[dict[str, Any]], labels: dict[str, str]) -> dict[str, Any] | None:
    keys = list(labels)
    refs = _refs(rows)
    prompt = f"""You are this buyer. You just tried the same jobs on {len(keys)} products. Pick the ONE product you would buy, from your own results below.

You: {persona.get('name')}, {persona.get('occupation') or ''}. {persona.get('bio') or ''}
Products (key: name): {", ".join(f"{k}: {v}" for k, v in labels.items())}
Your runs (agent id, product, job, how far you got, score, friction, reason, what the page said):
{chr(10).join(_run_line(r, labels, ref) for ref, r in zip(refs, rows))}

Doing a job inside the product beats reading about it on a website. Weigh the jobs that matter most to you.
Return JSON only: {{"pick": "one product key from the list", "runner_up": "product key", "why": "two short sentences in first person citing specific results", "cites": ["run refs (like R3) of the 1-3 runs that decided it"]}}"""
    data = await _json_call(prompt)

    def key_of(value: Any) -> str:
        text = str(value or "").strip()
        if text in keys:
            return text
        for k, name in labels.items():
            if name and name.lower() == text.lower():
                return k
        return ""

    if not isinstance(data, dict) or not key_of(data.get("pick")):
        print(f"[comparison] pick not a product: {str(data)[:160]}", flush=True)
        return None
    return {
        "pick": key_of(data["pick"]),
        "runner_up": key_of(data.get("runner_up")),
        "why": " ".join(str(data.get("why") or "").split())[:400],
        "cites": [a for a in (_resolve(c, refs) for c in (data.get("cites") or [])) if a][:3],
    }


def _opening_text(study: Any, site: str) -> str:
    """The site's step-0 page text (the shared opening read)."""
    results = study.get("agent_results") if isinstance(study, dict) else getattr(study, "agent_results", None)
    for r in results or []:
        if isinstance(r, dict) and r.get("site_key") == site:
            for step in r.get("trace") or []:
                if isinstance(step, dict) and int(step.get("step") or 0) == 0 and step.get("observation"):
                    return " ".join(str(step.get("observation")).split())[:1800]
    return ""


async def first_impression(study: Any, site: str, label: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    web = [r for r in rows if r.get("website_eval") or not (r.get("signup") or {}).get("ok")][:8] or rows[:4]
    refs = _refs(web)
    lines = [_run_line(r, {site: label}, ref) for ref, r in zip(refs, web)]
    signed = sum(1 for r in rows if (r.get("signup") or {}).get("ok"))
    prompt = f"""A buyer lands on {label}'s website and has about 30 seconds. From the opening page text and what our website visits found, write what they come away with.

Opening page text: {_opening_text(study, site) or '(not recorded)'}
Website visits (agent id, job, result, page quote):
{chr(10).join(lines) or '(none)'}
Self-serve signups that worked: {signed} of {len(rows)} runs.

Return JSON only:
{{"what_it_is": "at most 15 words", "who_for": "at most 12 words", "price": "what the site says about price, or 'not shown'",
  "proof": "customer logos, numbers or case studies shown, or 'none shown'", "fastest_path": "fastest way to try it, e.g. free signup, free trial, book a demo only",
  "clarity": 0-10, "cites": ["run refs (like R2) backing this"]}}"""
    data = await _json_call(prompt)
    if not isinstance(data, dict):
        return None
    return {
        "site": site,
        "label": label,
        **{k: " ".join(str(data.get(k) or "").split())[:200] for k in ("what_it_is", "who_for", "price", "proof", "fastest_path")},
        "clarity": data.get("clarity") if isinstance(data.get("clarity"), (int, float)) else None,
        "signups_ok": signed,
        "runs": len(rows),
        "cites": [a for a in (_resolve(c, refs) for c in (data.get("cites") or [])) if a][:4],
    }


async def product_fixes(rows: list[dict[str, Any]], personas: dict[str, dict[str, Any]], label: str) -> list[dict[str, Any]]:
    weak = [r for r in rows if float(_sc(r).get("score") or 0) < 7 or int(_sc(r).get("friction") or 0) >= 2]
    if not weak:
        return []
    refs = _refs(weak)
    back = {v: k for k, v in refs.items()}
    lines = [
        f"- [{back[str(r.get('agent_id'))]}] persona {r.get('persona_id')} ({(personas.get(str(r.get('persona_id'))) or {}).get('name', '')}) | "
        f"{_base_task(r)} | {_sc(r).get('level')} {_sc(r).get('score')} friction {_sc(r).get('friction')} | "
        f"step {_sc(r).get('evidence_step')}: {_sc(r).get('reason')} | {_sc(r).get('friction_note') or ''}"
        for r in weak
    ]
    prompt = f"""These are the weak runs on {label}, the product under study. Group them into distinct product problems a product team can fix (not problems with our test agents).

{chr(10).join(lines)}

Return JSON only: {{"fixes": [{{"issue": "at most 14 words", "fix": "at most 16 words", "personas": ["persona ids hurt"],
  "moments": [{{"run": "run ref like R4", "step": step number, "what": "at most 12 words"}}]}}]}}
At most 6 fixes, each with 1-3 moments. Use only run refs listed above."""
    data = await _json_call(prompt)
    out = []
    for f in (data or {}).get("fixes") or [] if isinstance(data, dict) else []:
        if not isinstance(f, dict) or not f.get("issue"):
            continue
        moments = [
            {"agent_id": _resolve(m.get("run") or m.get("agent_id"), refs), "step": m.get("step"), "what": " ".join(str(m.get("what") or "").split())[:120]}
            for m in (f.get("moments") or []) if isinstance(m, dict) and _resolve(m.get("run") or m.get("agent_id"), refs)
        ][:3]
        out.append(
            {
                "issue": " ".join(str(f["issue"]).split())[:160],
                "fix": " ".join(str(f.get("fix") or "").split())[:180],
                "personas": sorted({str(p) for p in (f.get("personas") or []) if str(p) in personas}),
                "moments": moments,
            }
        )
    return out


async def headline_sentences(comp: dict[str, Any]) -> list[dict[str, Any]]:
    label = comp["product_label"]
    cited: list[str] = []

    def ref(agent_id: str) -> str:
        if not agent_id:
            return ""
        if agent_id not in cited:
            cited.append(agent_id)
        return f"R{cited.index(agent_id) + 1}"

    def row(x: dict[str, Any]) -> str:
        return (
            f"- {x['task']} | {x['persona']} | {label} {x['product_score']} vs {x['competitor_label']} {x['competitor_score']} | "
            f"{x['reason']} | cite {ref(x['product_evidence']['agent_id'] if x['gap'] > 0 else x['competitor_evidence']['agent_id'])}"
        )

    tasks = "\n".join(
        f"- {t['task']}: winner {t['winner_label']}, {label} rank {t['product_rank']} of {t['n_sites']} | "
        f"cite {ref((t.get('winner_evidence') or {}).get('agent_id', ''))}"
        for t in comp["by_task"]
    )
    prompt = f"""Write the headline of a competitive study for {label}'s team: 3 or 4 plain sentences saying where {label} wins and where it loses against the competitors. Use only the facts below. Each sentence cites one run ref (like R2) from the facts.

Buyer picks: {comp['headline_metric']}
Per task:
{tasks}
Biggest wins:
{chr(10).join(row(x) for x in comp['wins']) or '(none)'}
Biggest losses:
{chr(10).join(row(x) for x in comp['losses']) or '(none)'}

Return JSON only: {{"sentences": [{{"text": "sentence", "cite": "run ref"}}]}}"""
    data = await _json_call(prompt)
    out = []
    for srow in (data or {}).get("sentences") or [] if isinstance(data, dict) else []:
        if isinstance(srow, dict) and srow.get("text"):
            refs = {f"R{i + 1}": a for i, a in enumerate(cited)}
            out.append({"text": " ".join(str(srow["text"]).split())[:300], "cite": _resolve(srow.get("cite"), refs)})
    return out[:4]


async def apply_comparison_llm(study: Any) -> dict[str, Any]:
    """Persona picks, first impressions, fixes, then the headline; stored in summary['comparison_llm']."""
    from mvp.study import study_to_dict

    data = study_to_dict(study) if not isinstance(study, dict) else study
    comp = build_comparison(data)
    if not comp:
        return {}
    labels = {s["key"]: s["label"] for s in comp["sites"]}
    runs = [r for r in data.get("agent_results") or [] if isinstance(_sc(r).get("score"), (int, float))]
    personas = {str(p.get("id")): p for p in (data.get("personas") or []) if isinstance(p, dict)}

    async def pick(pid: str) -> dict[str, Any] | None:
        rows = [r for r in runs if str(r.get("persona_id")) == pid]
        if not rows:
            return None
        try:
            got = await persona_pick(personas[pid], rows, labels)
        except Exception as exc:  # noqa: BLE001
            print(f"[comparison] pick {pid} failed: {exc!r}"[:200], flush=True)
            return None
        return {"persona_id": pid, **got} if got else None

    async def impression(site: str) -> dict[str, Any] | None:
        try:
            return await first_impression(data, site, labels[site], [r for r in runs if r.get("site_key") == site])
        except Exception as exc:  # noqa: BLE001
            print(f"[comparison] first impression {site} failed: {exc!r}"[:200], flush=True)
            return None

    async def fixes() -> list[dict[str, Any]]:
        try:
            return await product_fixes([r for r in runs if r.get("site_key") == "product"], personas, labels["product"])
        except Exception as exc:  # noqa: BLE001
            print(f"[comparison] fixes failed: {exc!r}"[:200], flush=True)
            return []

    results = await asyncio.gather(
        asyncio.gather(*(pick(pid) for pid in personas)),
        asyncio.gather(*(impression(s) for s in labels)),
        fixes(),
    )
    llm = {
        "picks": [p for p in results[0] if p],
        "first_impressions": [f for f in results[1] if f],
        "fixes": results[2],
    }
    summary = dict(getattr(study, "summary", None) or data.get("summary") or {})
    summary["comparison_llm"] = llm
    data = {**data, "summary": summary}
    try:
        llm["headline"] = await headline_sentences(build_comparison(data))
    except Exception as exc:  # noqa: BLE001
        print(f"[comparison] headline failed: {exc!r}"[:200], flush=True)
    summary["comparison_llm"] = llm
    if isinstance(study, dict):
        study["summary"] = summary
    else:
        study.summary = summary
    print(f"[comparison] picks={len(llm['picks'])} impressions={len(llm['first_impressions'])} fixes={len(llm['fixes'])} headline={len(llm.get('headline') or [])}", flush=True)
    return llm
