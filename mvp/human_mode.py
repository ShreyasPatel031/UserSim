"""Human mode: a simulated user works in the real product (the browser tools), and what it saw is added to the
agent-mode prediction in the amount that held up on real reviewers.

    plan(...)    -> the task to give the simulated user and what to observe (usersim_plan_human_run)
    combine(...) -> agent-mode prediction + the run's observations, bounded (usersim_combine_human_run)

What the held-out tests found (experiments/staged_context/human_mode.py, HUMAN_MODE.md; real reviewers, product
excluded from the context so it is treated as new):
- Context-only predictions already hit pricing, onboarding and learning-curve points; they miss product-specific UI /
  navigation and core-feature depth. So the run is asked to do the core job for real (3+ items), then two
  second-level features (views, custom fields, reports, automations...), then edit / reorganise, and to report
  product facts, not onboarding.
- On top of the shipped agent mode (product's own reviews + rivals), adding the run's product observations to the
  evidence the words are written from raised cons recall 0.269 -> 0.315 (+0.046, 95% CI +0.007..+0.085; 173 held-out
  reviewers, 5 products, better on 4); pros unchanged (+0.004). Changing at most one item instead was slightly worse
  there (hm_agent_eval.py, out/human_mode/agent_mode_plus_run.csv).
- With NO own reviews (a new product; context = competitors only), free-form notes hurt (pros 0.42 -> 0.36, cons
  0.28 -> 0.21, product-level, 3 products) and only a bounded edit helped (at most one pro and one con changed, after
  dropping free-plan / setup / onboarding / pricing / billing / support notes: cons 0.28 -> 0.31).
- Ratings stay agent mode's: a first session's impressions ran about a star below real reviewers.
No silent fallbacks: if agent mode has no result, or there are no usable observations, the result says so.
"""

from __future__ import annotations

import json
from typing import Any

from mvp import agent_mode as AM

MAX_EDITS = 1  # per side (pros / cons); tested 1 and 2, 1 was best on cons
FIRST_SESSION = {"free_plan_or_tier_limits", "setup_configuration", "onboarding_learning_curve", "pricing_cost",
                 "billing_contract", "customer_support"}
THEMES = ["ui_ease_navigation", "onboarding_learning_curve", "setup_configuration", "core_feature_depth_or_missing",
          "reporting_analytics", "integrations", "customization_flexibility", "automation_workflows",
          "collaboration_sharing_permissions", "notifications", "templates", "data_import_export", "search",
          "performance_speed", "bugs_reliability", "mobile_app", "pricing_cost", "free_plan_or_tier_limits",
          "customer_support", "billing_contract", "scaling_large_data_or_teams", "other"]

TASK_PROMPT = """You are writing the task for a simulated user who will sign up for {product} ({url}) and use it for one
session of about 35 browser actions, with made-up demo data, on the free plan or a free trial.

Goal of the session: find what real long-term users of {product} will like and complain about. Data on real reviews
shows that general complaints (price, learning curve, support) are already predictable from competitor reviews, so
the session must NOT spend effort on onboarding, pricing pages or support. What only hands-on use reveals is how the
CORE workflow feels when done for real (navigation, number of clicks, missing or shallow features, clumsy editing),
and the second-level features people rely on after a few weeks (views, custom fields, filters, reports, automations,
templates, bulk edits, permissions), where competitors' users complain like this:
{rival}

Write the task in the simulated user's own words as {persona}. It must:
1. do {product}'s main job end to end with at least 3 realistic items (not one),
2. then use two second-level features that this kind of product's users depend on (pick the two most relevant),
3. then change or reorganise what was created (edit, move, filter or report on it).
Return {{"task": "<one paragraph, under 90 words>", "core_job": "<5-10 words>", "features": ["...", "..."]}}"""

RELEVANCE_PROMPT = """{product} ({url}). A planner named "{rival}" as a direct competitor. Review sites returned these
reviews for "{rival}":
{sample}
Return {{"reviews_are_of_named_product": true/false, "direct_competitor": "yes" | "partly" | "no", "why": "<one sentence>"}}.
"yes" = a buyer of {product} would compare them for the same job; "partly" = overlapping job or different buyer;
"no" = different job. (YC test: 19 of 40 planner-named rivals of new startups were "no".)"""

OBSERVE = """Report 6-12 observations as {"kind": "product_friction" | "product_benefit" | "signup_friction" | "agent_failure",
"feature": "...", "what": "one specific sentence"}. Product observations are about using the product for the work:
clicks the core job took, controls that were hard to find, clumsy editing, views / filters / reports / automations /
custom fields that were missing, shallow, paywalled or unusually good. Include what worked well. Onboarding tours,
empty states, sign-up and pricing pages are signup_friction, not product facts. Your own misclicks are agent_failure.
No ratings."""

THEME_PROMPT = """Give each observation's theme, one of {themes}.
{obs}
Return {{"themes": ["<theme of line 1>", ...]}} in order."""

EDIT_PROMPT = """Here are predicted pros and cons of {product} for this kind of user, written from review data:
{lists}

A simulated user then used {product} itself (signed in, demo data) and noted:
{obs}

Revise the prediction using the notes, changing AT MOST {k} pro(s) and AT MOST {k} con(s):
- replace an item only when a note directly contradicts it or shows a clearly more {product}-specific version of it,
- write replacements the way long-term reviewers write (themes such as "easy to use", "reporting is basic"), not UI
  steps; first-session friction (setup, empty states, free-plan limits) fades for long-term users,
- keep every other item exactly as it is, in the same order.
Return {{"pros": [...same number of items...], "cons": [...same number of items...],
 "changed": ["what you changed and which note justified it", ...]}}"""


async def _default_llm(prompt: str, system: str, temperature: float = 0.0) -> dict:
    from capability.gemini_config import extract_json, gemini_chat

    raw = await gemini_chat([{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                            temperature=temperature, json_mode=True, thinking_budget=1024)
    j = extract_json(raw)
    return j if isinstance(j, dict) else {}


def rival_complaints(reviews: list[dict], k: int = 25) -> str:
    rows = [r for r in reviews if len(str(r.get("cons") or "")) > 40]
    rows.sort(key=lambda r: (str(r.get("product")), str(r.get("cons"))))
    step = max(1, len(rows) // k) if rows else 1
    return "\n".join(f"- [{r.get('product')}] {str(r.get('cons')).strip()[:200]}" for r in rows[::step][:k])


async def plan(*, product: str, url: str, persona: str, competitors: list[str] | None = None, wait_s: float = 45.0,
               llm=None, discover=None) -> dict[str, Any]:
    """The task and observation guide for one human-mode run. status: ok | pending | no_data."""
    product, url = (product or "").strip(), (url or "").strip()
    if not product or not url:
        return {"mode": "human", "status": "no_data", "reason": "product and product_url are both required"}
    rivals = [c.strip() for c in (competitors or []) if c and c.strip()]
    if not rivals:
        try:
            rivals = await (discover or AM.discover_rivals)(url)
        except Exception as exc:  # noqa: BLE001
            return {"mode": "human", "status": "no_data", "reason": f"rival discovery failed ({type(exc).__name__}); pass competitors"}
    if not rivals:
        return {"mode": "human", "status": "no_data", "reason": "no competitors found; pass 1-3 competitor names"}
    import asyncio

    got = await asyncio.to_thread(AM.gather, rivals[0], rivals[1:], wait_s)
    pending = [n for n, v in got.items() if v is None]
    if pending and not any(v and v.get("reviews") for v in got.values()):
        return {"mode": "human", "status": "pending", "pending": pending,
                "reason": "rival review scrapes take 1-2 minutes; call usersim_plan_human_run again"}
    checked, riv = [], []
    for n, v in got.items():
        revs = (v or {}).get("reviews") or []
        if not revs:
            checked.append({"rival": n, "used": False, "why": "still scraping" if v is None else "no reviews found"})
            continue
        sample = "\n".join(f"- liked: {str(r.get('pros') or '')[:200]} | disliked: {str(r.get('cons') or '')[:200]} | "
                           f"{str(r.get('text') or '')[:200]}" for r in revs[:6])
        rel = await (llm or _default_llm)(RELEVANCE_PROMPT.format(product=product, url=url, rival=n, sample=sample),
                                          "You know the B2B software market. Return JSON only.")
        ok = rel.get("reviews_are_of_named_product") is True and rel.get("direct_competitor") in ("yes", "partly")
        checked.append({"rival": n, "used": ok, "direct": rel.get("direct_competitor"), "why": rel.get("why")})
        if ok:
            riv += revs
    if not riv:
        return {"mode": "human", "status": "no_data", "rivals_checked": checked,
                "reason": "none of the rivals is a real competitor with reviews of the named product; pass competitors"}
    j = await (llm or _default_llm)(TASK_PROMPT.format(product=product, url=url, persona=persona or "a typical user",
                                                       rival=rival_complaints(riv)[:3500]),
                                    "You design realistic product-usage sessions. Return JSON only.")
    if not j.get("task"):
        return {"mode": "human", "status": "no_data", "reason": "task generation returned nothing"}
    return {"mode": "human", "status": "ok", "product": product, "rivals": rivals, "rivals_checked": checked,
            "core_job": j.get("core_job"),
            "features": j.get("features") or [],
            "start_session": {"product_url": url, "persona": persona, "task": j["task"]},
            "observe": OBSERVE,
            "next": ("Run usersim_start_session with start_session, sign up, do the task, usersim_finish, then pass your "
                     "observations to usersim_combine_human_run.")}


async def filter_observations(observations: list[dict], llm=None) -> tuple[list[str], list[str]]:
    """(kept, dropped) product observations as '- [friction|benefit] what' lines."""
    lines = [f"- [{str(o.get('kind', '')).replace('product_', '')}] {str(o.get('what', '')).strip()}"
             for o in observations if str(o.get("kind", "")) in ("product_friction", "product_benefit") and o.get("what")]
    if not lines:
        return [], []
    j = await (llm or _default_llm)(THEME_PROMPT.format(themes=THEMES, obs="\n".join(lines)),
                                    "You classify product observations. Return JSON only.")
    th = j.get("themes")
    if not isinstance(th, list) or len(th) != len(lines):
        raise RuntimeError("observation themes missing")
    kept = [ln for ln, t in zip(lines, th) if t not in FIRST_SESSION]
    return kept, [ln for ln in lines if ln not in kept]


RUN_SECTION = """## What a simulated new user saw when using {product} itself today (signed in, demo data)
{obs}"""


def product_lines(observations: list[dict]) -> list[str]:
    return [f"- [{str(o.get('kind', '')).replace('product_', '')}] {str(o.get('what', '')).strip()}"
            for o in observations if str(o.get("kind", "")) in ("product_friction", "product_benefit") and o.get("what")]


async def _words_llm(prompt: str) -> dict:
    """agent_mode's default words call (same system prompt, temperature and thinking)."""
    from capability.gemini_config import extract_json, gemini_chat

    raw = await gemini_chat([{"role": "system", "content": AM.WORDS_SYSTEM}, {"role": "user", "content": prompt}],
                            temperature=0.7, json_mode=True, thinking_budget=AM.WORDS_THINKING)
    j = extract_json(raw)
    return j if isinstance(j, dict) else {}


async def combine(*, product: str, url: str, persona: dict[str, Any], observations: list[dict], task: str = "",
                  competitors: list[str] | None = None, wait_s: float = 45.0, llm=None, agent=None,
                  words_llm=None) -> dict[str, Any]:
    """Agent-mode prediction plus the run's product observations, in the amount that held up on real reviewers.

    Product with its own reviews: the words are rewritten from agent mode's evidence plus the observations.
    No own reviews: at most MAX_EDITS pro and con of agent mode's words change (first-session notes dropped).
    Ratings are agent mode's in both cases."""
    base = await (agent or AM.predict_experience)(product=product, url=url, persona=persona, task=task,
                                                  competitors=competitors, wait_s=wait_s)
    if base.get("status") != "ok":
        return {**base, "mode": "human", "reason": "agent-mode prediction not ready: " + str(base.get("reason") or base.get("status"))}
    lines = product_lines(observations or [])
    if (base.get("evidence") or {}).get("own_reviews"):
        out = {**base, "mode": "human", "agent_mode": {"pros": base.get("pros"), "cons": base.get("cons"),
                                                       "overall_experience": base.get("overall_experience")},
               "observations_used": lines, "rule": "own reviews present: words rewritten with the run's observations added"}
        if not lines:
            out["human_note"] = "no product observations in the run: the prediction is agent mode's, unchanged"
            return out
        section = "\n\n" + RUN_SECTION.format(product=product, obs="\n".join(lines))
        inner = words_llm or _words_llm

        async def with_run(prompt: str) -> dict:
            return await inner(prompt + section)
        again = await (agent or AM.predict_experience)(product=product, url=url, persona=persona, task=task,
                                                       competitors=competitors, wait_s=wait_s, llm=with_run)
        if again.get("status") != "ok" or again.get("words_error"):
            out["human_note"] = f"rewriting with the observations failed ({again.get('words_error') or again.get('status')}): agent mode's words kept"
            return out
        out.update(pros=again.get("pros") or [], cons=again.get("cons") or [],
                   overall_experience=again.get("overall_experience") or "")
        out["how_to_read"] = (base.get("how_to_read", "") + " Human mode: ratings are agent mode's (a first session's "
                              "impressions ran about a star low against real reviewers); pros, cons and overall experience "
                              "were rewritten with what the simulated user saw added to the review evidence.")
        return out
    kept, dropped = await filter_observations(observations or [], llm)
    out = {**base, "mode": "human", "agent_mode": {"pros": base.get("pros"), "cons": base.get("cons")},
           "observations_used": kept, "observations_dropped_first_session": dropped, "changed": [],
           "rule": "no own reviews: at most one pro and one con changed by the run's observations"}
    if not kept:
        out["human_note"] = ("no usable product observations (none, or only setup / free-plan / pricing / support notes): "
                             "the prediction is agent mode's, unchanged")
        return out
    lists = "Pros:\n" + "\n".join(f"- {x}" for x in base.get("pros") or []) + "\nCons:\n" + "\n".join(
        f"- {x}" for x in base.get("cons") or [])
    j = await (llm or _default_llm)(EDIT_PROMPT.format(product=product, lists=lists, obs="\n".join(kept), k=MAX_EDITS),
                                    "You revise product predictions conservatively. Return JSON only.")
    pros, cons = _bounded(base.get("pros") or [], j.get("pros")), _bounded(base.get("cons") or [], j.get("cons"))
    out.update(pros=pros, cons=cons, changed=[str(c) for c in (j.get("changed") or [])][:2 * MAX_EDITS])
    out["how_to_read"] = (base.get("how_to_read", "") + " Human mode: ratings are agent mode's (a first session's "
                          f"impressions ran about a star low against real reviewers); at most {MAX_EDITS} pro and "
                          f"{MAX_EDITS} con were changed by what the simulated user saw (see changed).")
    return out


def _bounded(before: list, after: Any) -> list:
    """Accept the model's revision only if it changed at most MAX_EDITS items of the same-length list."""
    if not isinstance(after, list) or len(after) != len(before):
        return list(before)
    after = [str(x) for x in after]
    if sum(a != b for a, b in zip(before, after)) > MAX_EDITS:
        return list(before)
    return after


def parse_observations(value: Any) -> list[dict]:
    """Accept a list of {kind, what} dicts or a JSON string of one."""
    if isinstance(value, str):
        value = json.loads(value)
    return [dict(o) for o in (value or []) if isinstance(o, dict)]
