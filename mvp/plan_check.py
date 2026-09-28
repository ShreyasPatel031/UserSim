"""Planner-only dry run: the plan POST /api/studies would write, checked, with no browsers.

Used by ``dry_run: true`` on POST /api/studies and by ``scripts/preflight.py --url``.
Runs the full plan and the early-start starter concurrently and splices them the
way mvp/server.py does, probes the rivals over plain HTTP, and validates the result.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any
from urllib.parse import urlsplit

PLAN_BUDGET_S = float(os.environ.get("MVP_DRY_RUN_BUDGET_S", "25") or "25")
MIN_RIVALS = 2
MIN_TASKS_PER_SITE = 2


def _host(url: str) -> str:
    raw = str(url or "").strip()
    if "://" not in raw:
        raw = "https://" + raw
    return (urlsplit(raw).hostname or "").lower().removeprefix("www.")


async def live_rivals(competitors: list[str], *, fetch: Any = None) -> list[dict[str, Any]]:
    """One row per planned rival: {url, live, reason}. Rivals are probed at once."""
    from mvp.competitor_urls import probe_competitor_url

    async def one(url: str) -> dict[str, Any]:
        try:
            probe = await probe_competitor_url(url, fetch=fetch)
        except Exception as exc:  # noqa: BLE001
            return {"url": url, "live": False, "reason": f"probe_error:{type(exc).__name__}"}
        return {"url": url, "live": bool(probe.ok), "reason": probe.reason}

    return list(await asyncio.gather(*(one(c) for c in competitors or [])))


def validate_plan(
    plan: dict[str, Any] | None,
    *,
    product_url: str,
    rivals: list[dict[str, Any]],
    elapsed_s: float,
    budget_s: float = PLAN_BUDGET_S,
) -> list[dict[str, Any]]:
    """Checks a finished plan must pass: [{name, ok, detail}]."""
    from mvp.fast_plan import is_chatbot_rival, product_is_general_assistant

    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    if not plan:
        add("plan", False, "planner returned no plan")
    else:
        rejected = {_host(u) for u in ((plan.get("verified") or {}).get("rejected") or []) if u}
        kept = [c for c in plan.get("competitors") or [] if _host(c) in rejected]
        if plan.get("mode") != "compare":
            add("plan", False, "planner fell back to the classic plan (no comparison)")
        elif kept:
            add("plan", False, f"plan keeps rivals its own check rejected: {kept}")
        else:
            add("plan", True, f"compare plan for {plan.get('product') or _host(product_url)}")

    live = [r["url"] for r in rivals if r.get("live")]
    dead = [f"{r['url']} ({r.get('reason')})" for r in rivals if not r.get("live")]
    add(
        "live_rivals",
        len(live) >= MIN_RIVALS,
        f"{len(live)} live of {len(rivals)}" + (f"; dead: {', '.join(dead)}" if dead else ""),
    )

    competitors = list((plan or {}).get("competitors") or [])
    own = _host(product_url)
    names = dict((plan or {}).get("competitor_names") or {})
    bots = [c for c in competitors if is_chatbot_rival(c)]
    if bots and product_is_general_assistant(own):
        add("no_chatbot_rival", True, f"product is a general assistant; chatbot rivals allowed: {bots}")
    else:
        add("no_chatbot_rival", not bots, f"chatbot rivals: {bots}" if bots else "none")

    people = [str(p.get("name") or "").strip() for p in (plan or {}).get("personas") or [] if isinstance(p, dict)]
    lowered = [p.lower() for p in people]
    dupes = sorted({p for p in people if lowered.count(p.lower()) > 1})
    add(
        "unique_personas",
        bool(people) and not dupes,
        f"{len(people)} personas" + (f"; repeated: {dupes}" if dupes else ""),
    )

    specs = [t for t in (plan or {}).get("task_specs") or [] if isinstance(t, dict)]
    sites = ["product"] + competitors
    counts = {s: sum(1 for t in specs if t.get("favors") == s) for s in sites}
    short = {("product" if s == "product" else names.get(s) or s): n for s, n in counts.items() if n < MIN_TASKS_PER_SITE}
    add(
        "tasks_per_site",
        bool(plan) and not short,
        ", ".join(f"{'product' if s == 'product' else names.get(s) or _host(s)}={n}" for s, n in counts.items())
        + (f"; short: {short}" if short else ""),
    )

    add("plan_time", elapsed_s < budget_s, f"{elapsed_s:.1f}s (budget {budget_s:.0f}s)")
    return checks


async def dry_run_plan(url: str, *, fetch: Any = None) -> dict[str, Any]:
    """Plan ``url`` like POST /api/studies, probe the rivals, and validate. No browsers, no study."""
    from capability.gemini_config import estimate_cost_usd, track_usage
    from mvp import early_start
    from mvp.fast_plan import compare_mode, competitor_cells, plan_from_url

    with track_usage() as usage:
        t0 = time.monotonic()
        plan_task = asyncio.create_task(plan_from_url(url))
        starter = None
        if compare_mode() and early_start.enabled():
            starter = await early_start.starter_plan(url)
        plan = await plan_task
        if plan and starter and plan.get("mode") == "compare":
            plan = early_start.splice_plan(plan, starter)
            plan["competitor_cells"] = competitor_cells(
                list(plan.get("personas") or []), list(plan.get("task_specs") or []), list(plan.get("competitors") or [])
            )
        elapsed = time.monotonic() - t0
    rivals = await live_rivals(list((plan or {}).get("competitors") or []), fetch=fetch)
    checks = validate_plan(plan, product_url=url, rivals=rivals, elapsed_s=elapsed)
    names = dict((plan or {}).get("competitor_names") or {})
    tokens_in = sum(r["input_tokens"] for r in usage)
    tokens_out = sum(r["output_tokens"] for r in usage)
    return {
        "dry_run": True,
        "url": url,
        "ok": all(c["ok"] for c in checks),
        "plan_s": round(elapsed, 2),
        "product": (plan or {}).get("product"),
        "segment": (plan or {}).get("segment"),
        "mode": (plan or {}).get("mode"),
        "personas": list((plan or {}).get("personas") or []),
        "tasks": list((plan or {}).get("task_specs") or [{"prompt": t} for t in (plan or {}).get("tasks") or []]),
        "rivals": [dict(r, name=names.get(r["url"]) or "") for r in rivals],
        "competitor_cells": (plan or {}).get("competitor_cells"),
        "validation": checks,
        "usage": {
            "gemini_calls": len(usage),
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "est_cost_usd": estimate_cost_usd(usage),
            "calls": usage,
        },
    }
