"""YC test: do the production tools return real, reliable competitors, customers and tasks for brand-new startups?

20 B2B companies from YC Spring/Summer 2026 (out/yc/yc20.json, picked by hash). Per company:
  plan    competitors from the study planner (mvp.fast_plan, the path agent / human mode use), URL-verified by it
  scrape  live reviews (G2/Capterra/TrustRadius/Gartner) of the startup and each competitor (cache/live)
  report  competitors found / live / with reviews / judged real direct competitors; customer mix from competitor
          reviewers; tasks (usersim_plan_human_run's task + competitor users' top use cases); flags for poor matches

    python experiments/staged_context/yc_test.py plan
    (scrape the names in out/yc/scrape_names.txt)
    python experiments/staged_context/yc_test.py report
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
import experiment as E  # noqa: E402
import live as L  # noqa: E402
import router_eval as RE  # noqa: E402

from mvp import human_mode as HM  # noqa: E402
from mvp import review_context as RC  # noqa: E402

YOUT = E.OUT / "yc"
FLASH = "gemini-2.5-flash"


def plan() -> None:
    from mvp.fast_plan import compare_plan_from_url

    cos = E.read_json(YOUT / "yc20.json")

    async def one(c):
        try:
            p = await compare_plan_from_url(c["website"], timeout=90) or {}
        except Exception as exc:  # noqa: BLE001
            p = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
        return c["slug"], {k: p.get(k) for k in ("product", "segment", "competitors", "competitor_names", "personas",
                                                   "tasks", "verified", "positioning", "error")}

    async def main():
        sem = asyncio.Semaphore(5)

        async def lim(c):
            async with sem:
                return await one(c)
        return dict(await asyncio.gather(*(lim(c) for c in cos)))
    plans = asyncio.run(main())
    E.write_json(YOUT / "plans.json", plans)
    names = []
    for c in cos:
        p = plans[c["slug"]]
        names.append(c["name"])
        names += [n for n in (p.get("competitor_names") or {}).values() if n]
    (YOUT / "scrape_names.txt").write_text("\n".join(dict.fromkeys(names)) + "\n")
    for c in cos:
        p = plans[c["slug"]]
        print(f"{c['name']:16} rivals={list((p.get('competitor_names') or {}).values())} err={p.get('error')}")


RELEVANCE = """A startup: {name} ({url}) — {one_liner}. {desc}

A planner named "{rival}" as a direct competitor. Review sites returned these reviews for "{rival}" (product as listed: {found_as}):
{sample}

Return {{"reviews_are_of_named_product": true/false, "direct_competitor": "yes" | "partly" | "no",
 "why": "<one sentence>"}}. "yes" = a buyer of {name} would seriously compare the two for the same job;
"partly" = adjacent / overlapping job or different buyer; "no" = different job."""

USE_CASES = """Reviews by users of {rivals} (competitors of {name}: {one_liner}):
{sample}

List the 5 most common concrete things these users use the products for, as tasks a new user of {name} could try
(imperative, under 12 words each), most common first. Only include tasks that also fit {name}.
Return {{"tasks": ["...", ...]}}"""


def _sample(revs: list[dict], k: int = 6) -> str:
    rows = [r for r in revs if r.get("pros") or r.get("text")][:k]
    return "\n".join(f"- [{r.get('source')}; {r.get('role') or 'role n/a'}] liked: {RE_clip(r.get('pros'))} | disliked: "
                     f"{RE_clip(r.get('cons'))} | {RE_clip(r.get('text'))}" for r in rows) or "(no reviews)"


def RE_clip(v, n: int = 220) -> str:
    return E.clean(v)[:n] if v else "-"


def report() -> None:
    cos = E.read_json(YOUT / "yc20.json")
    plans = E.read_json(YOUT / "plans.json")
    pool = ThreadPoolExecutor(16)
    rows = []

    def revs_of(name):
        f = L.LIVE / f"{L.slug(name)}.json"
        return [RC._all_in_one_item(x) for x in L.scrape(name)] if f.is_file() else None

    for c in cos:
        p = plans[c["slug"]]
        names = [n for n in (p.get("competitor_names") or {}).values() if n]
        urls = list(p.get("competitor_names") or {})
        own = revs_of(c["name"])
        own_same = [r for r in (own or []) if RC._same_product(r.get("product"), c["name"])]
        comp = []

        def judge(n, u):
            rv = revs_of(n)
            found_as = sorted({str(r.get("product")) for r in (rv or []) if r.get("product")})[:3]
            rec = E.call_model("yc_relevance", FLASH, "You know the B2B software market. Return JSON only.", RELEVANCE.format(
                name=c["name"], url=c["website"], one_liner=c["one_liner"], desc=(c.get("long_description") or "")[:600],
                rival=n, found_as=found_as or "nothing found", sample=_sample(rv or [])),
                temperature=0.0, seed=42, max_tokens=2048, thinking_budget=512)
            j = rec.get("json") if isinstance(rec.get("json"), dict) else {}
            return {"name": n, "url": u, "verified_live": bool(u), "reviews": len(rv) if rv is not None else None,
                    "by_site": dict(Counter(r.get("source") for r in rv or [])), "found_as": found_as,
                    "reviews_match": j.get("reviews_are_of_named_product"), "direct": j.get("direct_competitor"),
                    "why": j.get("why")}
        comp = list(pool.map(lambda nu: judge(*nu), zip(names, urls)))
        good = [x for x in comp if x["direct"] in ("yes", "partly") and x["reviews_match"] and (x["reviews"] or 0) >= 20]
        riv = [r for x in good for r in (revs_of(x["name"]) or [])]
        fam = Counter(RE_role(r.get("role")) for r in riv if r.get("role"))
        size = Counter(r.get("size") for r in riv if r.get("size"))
        ind = Counter(L.industry(r.get("industry")) for r in riv if r.get("industry"))
        tot = lambda cnt: sum(cnt.values()) or 1  # noqa: E731
        customers = {"n_reviewers": len(riv),
                     "roles": {k: round(v / tot(fam), 2) for k, v in fam.most_common(5)},
                     "company_size": {str(k): round(v / tot(size), 2) for k, v in size.most_common(4)},
                     "industries": {str(k): round(v / tot(ind), 2) for k, v in ind.most_common(4)}}
        uc = []
        if riv:
            rec = E.call_model("yc_use_cases", FLASH, "You analyse software reviews. Return JSON only.", USE_CASES.format(
                rivals=", ".join(x["name"] for x in good), name=c["name"], one_liner=c["one_liner"], sample=_sample(riv, 30)),
                temperature=0.0, seed=42, max_tokens=2048, thinking_budget=512)
            uc = (rec.get("json") or {}).get("tasks") or [] if isinstance(rec.get("json"), dict) else []
        run_task = None
        if riv:
            rec = E.call_model("yc_run_task", FLASH, "You design realistic product-usage sessions. Return JSON only.",
                               HM.TASK_PROMPT.format(product=c["name"], url=c["website"], persona=(p.get("personas") or [{}])[0].get("description", "a typical buyer") if isinstance((p.get("personas") or [{}])[0], dict) else str((p.get("personas") or ["a typical buyer"])[0]),
                                                     rival=HM.rival_complaints(riv)[:3500]),
                               temperature=0.0, seed=42, max_tokens=2048, thinking_budget=512)
            run_task = (rec.get("json") or {}).get("task") if isinstance(rec.get("json"), dict) else None
        flags = []
        if not names:
            flags.append("planner found no competitors")
        if names and not good:
            flags.append("no competitor is both a real direct competitor and has 20+ reviews of the right product")
        flags += [f"{x['name']}: reviews are of another product ({x['found_as']})" for x in comp if x["reviews"] and x["reviews_match"] is False]
        flags += [f"{x['name']}: judged not a direct competitor ({x['why']})" for x in comp if x["direct"] == "no"]
        flags += [f"{x['name']}: no reviews found" for x in comp if not x["reviews"]]
        rows.append({"name": c["name"], "website": c["website"], "one_liner": c["one_liner"], "batch": c["batch"],
                     "own_reviews": len(own_same), "competitors": comp, "usable_competitors": [x["name"] for x in good],
                     "customers": customers, "planner_tasks": p.get("tasks"), "competitor_use_cases": uc,
                     "human_run_task": run_task, "flags": flags})
        print(f"{c['name']:16} own={len(own_same):3} rivals={len(comp)} usable={len(good)} reviewers={len(riv):4} flags={len(flags)}", flush=True)
    E.write_json(YOUT / "yc_report.json", rows)


def RE_role(t):
    return E.role_family(t or "")


if __name__ == "__main__":
    {"plan": plan, "report": report}[sys.argv[1]]()
