"""Human mode, offline part: where can a browser run add signal on top of the context-only agent, and what task should
the simulated user be given to find it?

For the router_eval people (Capterra, 35 products x 12, each product's own reviews excluded from its context):
  1. each real benefit / friction the person wrote (router_eval extraction, cached),
  2. whether the context-only agent (agent_full) already predicted it (router_eval judge pairs, score 2, cached),
  3. a theme, and whether a new user could observe it in ONE signed-in session with demo data (one model call/person),
     plus the task that would expose it.
Headroom per theme = share of all points x (1 - context hit rate) x observable share.

    python experiments/staged_context/human_mode.py observability
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import experiment as E  # noqa: E402
import g2_merge as G  # noqa: E402
import matched as MT  # noqa: E402
import router_eval as RE  # noqa: E402
import ux_mcp as U  # noqa: E402

HOUT = E.OUT / "human_mode"
FLASH = "gemini-2.5-flash"
THEMES = ["ui_ease_navigation", "onboarding_learning_curve", "setup_configuration", "core_feature_depth_or_missing",
          "reporting_analytics", "integrations", "customization_flexibility", "automation_workflows",
          "collaboration_sharing_permissions", "notifications", "templates", "data_import_export", "search",
          "performance_speed", "bugs_reliability", "mobile_app", "pricing_cost", "free_plan_or_tier_limits",
          "customer_support", "billing_contract", "scaling_large_data_or_teams", "other"]

CLASSIFY = """A reviewer of {product} wrote these points. For each, give:
- theme: one of {themes}
- observable: could a NEW user notice this point themselves in ONE signed-in session (about 30 minutes, free plan or
  trial, synthetic demo data, no real team, no support ticket, no billing)? "yes", "partly" or "no".
- task: if yes/partly, the one concrete task (imperative, under 15 words) that would expose it; else null.
Points:
{points}
Return {{"points": [{{"id": "B1", "theme": "...", "observable": "yes", "task": "..."}}, ...]}} covering every id."""


def people_and_judgements() -> tuple[list[dict], dict, dict]:
    """router_eval people with extraction refs and agent_full judge pairs (all calls normally cached)."""
    df = U.data()
    people = RE.sample(df)
    pool = ThreadPoolExecutor(64)
    refs = dict(pool.map(lambda r: (r["review_id"], G.RE_extract(r)), people))
    cards = {r["review_id"]: RE.card(r, refs[r["review_id"]]["task"]) for r in people}

    def pkg(r):
        return r["review_id"], U.build_package(RE.URLS[r["product_name"]], {
            "role_family": cards[r["review_id"]]["role_family"], "company_size": r["reviewer_company_size"],
            "time_used": r["reviewer_time_used_product"], "industry": r["reviewer_industry"]},
            exclude_product=r["product_name"], mask=U.mask_for(r["product_name"]))
    pkgs = dict(pool.map(pkg, people))

    def predict_judge(r):
        rid = r["review_id"]
        ev = "\nData:\n" + "\n\n".join(pkgs[rid]["sections"].values())
        rec = E.call_model("router_predict", FLASH, MT.PRED_SYSTEM, RE.PRED.format(**cards[rid], evidence=ev),
                           temperature=E.PREDICT_TEMPERATURE, seed=1000, max_tokens=8192, thinking_budget=1024,
                           key_extra=f"{rid}|agent_full")
        j = rec.get("json") if isinstance(rec.get("json"), dict) else {}
        ref = refs[rid]
        lst = lambda x: [str(v) for v in x][:3] if isinstance(x, list) else []  # noqa: E731
        fmt = lambda xs, p: "\n".join(f"{p}{i + 1}: {x}" for i, x in enumerate(xs)) or "(none)"  # noqa: E731
        g = E.call_model("router_judge", FLASH, "You are a strict evaluator. Return JSON only.", RE.JUDGE.format(
            pp=fmt(lst(j.get("pros")), "P"), ap=fmt(ref["benefits"], "A"), pc=fmt(lst(j.get("cons")), "P"),
            ac=fmt(ref["frictions"], "A"), po=str(j.get("overall_experience") or ""), at=E.review_for_extraction(r)),
            temperature=0.0, seed=42, max_tokens=4096, thinking_budget=512)
        g = g.get("json") if isinstance(g.get("json"), dict) else {}
        hit = {"pros": set(), "cons": set()}
        for k in hit:
            for m in g.get(k) or []:
                if isinstance(m, dict) and m.get("score") == 2:
                    hit[k].add(m.get("act"))
        return rid, {"pred": j, "hit": hit}
    judged = dict(pool.map(predict_judge, people))
    return people, refs, judged


def observability() -> None:
    people, refs, judged = people_and_judgements()
    pool = ThreadPoolExecutor(64)

    def classify(r):
        rid, ref = r["review_id"], refs[r["review_id"]]
        pts = [(f"B{i + 1}", "benefit", x) for i, x in enumerate(ref["benefits"])] + \
              [(f"F{i + 1}", "friction", x) for i, x in enumerate(ref["frictions"])]
        if not pts:
            return rid, {}
        rec = E.call_model("hm_observable", FLASH, "You analyse software reviews. Return JSON only.", CLASSIFY.format(
            product=r["product_name"], themes=THEMES, points="\n".join(f"{i} ({k}): {x}" for i, k, x in pts)),
            temperature=0.0, seed=42, max_tokens=4096, thinking_budget=512)
        j = rec.get("json") if isinstance(rec.get("json"), dict) else {}
        return rid, {p.get("id"): p for p in (j.get("points") or []) if isinstance(p, dict)}
    cls = dict(pool.map(classify, people))

    rows = []
    for r in people:
        rid, ref = r["review_id"], refs[r["review_id"]]
        for kind, key, pref, hk in (("benefit", "benefits", "B", "pros"), ("friction", "frictions", "F", "cons")):
            for i, text in enumerate(ref[key]):
                c = cls[rid].get(f"{pref}{i + 1}", {})
                rows.append({"rid": rid, "product": r["product_name"], "split": "dev" if r["product_name"] in RE.DEV else "test",
                             "kind": kind, "text": text, "theme": c.get("theme") if c.get("theme") in THEMES else "other",
                             "observable": c.get("observable") if c.get("observable") in ("yes", "partly", "no") else "no",
                             "task": c.get("task"), "context_hit": f"A{i + 1}" in judged[rid]["hit"][hk]})
    P = pd.DataFrame(rows)
    HOUT.mkdir(parents=True, exist_ok=True)
    P.to_csv(HOUT / "points.csv", index=False)
    P["obs"] = P.observable.map({"yes": 1.0, "partly": 0.5, "no": 0.0})
    out = []
    for (kind, theme), g in P.groupby(["kind", "theme"]):
        n_kind = (P.kind == kind).sum()
        share, hit, obs = len(g) / n_kind, g.context_hit.mean(), g.obs.mean()
        out.append({"kind": kind, "theme": theme, "n": len(g), "share": share, "context_hit": hit, "observable": obs,
                    "missed_and_observable": float(((~g.context_hit) * g.obs).sum() / n_kind)})
    T = pd.DataFrame(out).sort_values(["kind", "missed_and_observable"], ascending=[True, False])
    T.to_csv(HOUT / "themes.csv", index=False)
    summ = {k: {"points": int((P.kind == k).sum()), "context_hit": float(P[P.kind == k].context_hit.mean()),
                "observable_yes": float((P[P.kind == k].observable == "yes").mean()),
                "observable_any": float((P[P.kind == k].observable != "no").mean()),
                "missed_but_observable": float(((~P[P.kind == k].context_hit) & (P[P.kind == k].observable != "no")).mean())}
            for k in ("benefit", "friction")}
    E.write_json(HOUT / "observability.json", summ)
    pd.set_option("display.width", 200)
    print(json.dumps(summ, indent=1))
    print(T.round(3).to_string(index=False))
    print(f"spend ${E.spent_usd():.3f}")


# ----------------------------------------------------------------------------- run signal on top of context

RUN_RAW = """## What a simulated new user saw when using {product} itself today (signed in, demo data)
{obs}"""
RUN_GUIDED = """## Hands-on notes: a simulated new user used {product} itself today (signed in, free plan or trial, demo data)
These are facts about THIS product, unlike the data above, which is about other products.
{obs}
How to use them: they make pros/cons specific to {product}. Use an observation for this person only when it touches
the work they do. They come from a first session, while this person has used the product for a while: setup and
first-use friction fades with time, missing features and clumsy core workflows do not. Keep the ratings anchored
on the data above and move a rating by at most half a point because of these notes."""


def run_obs(runs: list[dict], max_n: int = 14) -> list[str]:
    seen, out = set(), []
    for r in runs:
        if not (r.get("signed_in") and r.get("reached_product")):
            continue
        for o in r.get("observations") or []:
            if o.get("kind") in ("product_friction", "product_benefit") and o["what"] not in seen:
                seen.add(o["what"])
                out.append(f"- [{o['kind'].replace('product_', '')}] {o['what']}")
    return out[:max_n]


def product_people(product: str, n: int) -> list[dict]:
    df = U.data()
    g = df[(df.product_name == product) & df.pros.notna() & df.overall_rating.notna()].copy()
    g = g[g.apply(lambda r: MT.context_ok({**r.to_dict(), "ease_of_use_rating": r.ease_of_use_rating}), axis=1)]
    g = g.assign(_h=g.review_id.map(lambda i: E.sha(f"42|hm|{product}|{i}"))).sort_values("_h").head(n)
    import numpy as np
    return [{k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in r.items()} for r in g.to_dict("records")]


def judge_one(pred: dict, ref: dict, review_text: str) -> dict:
    lst = lambda x: [str(v) for v in x][:3] if isinstance(x, list) else []  # noqa: E731
    fmt = lambda xs, p: "\n".join(f"{p}{i + 1}: {x}" for i, x in enumerate(xs)) or "(none)"  # noqa: E731
    g = E.call_model("router_judge", FLASH, "You are a strict evaluator. Return JSON only.", RE.JUDGE.format(
        pp=fmt(lst(pred.get("pros")), "P"), ap=fmt(ref["benefits"], "A"), pc=fmt(lst(pred.get("cons")), "P"),
        ac=fmt(ref["frictions"], "A"), po=str(pred.get("overall_experience") or ""), at=review_text),
        temperature=0.0, seed=42, max_tokens=4096, thinking_budget=512)
    g = g.get("json") if isinstance(g.get("json"), dict) else {}
    out = {}
    for key, n in (("pros", len(ref["benefits"])), ("cons", len(ref["frictions"]))):
        best = {}
        for m in g.get(key) or []:
            if isinstance(m, dict) and m.get("score") in (1, 2):
                best[m.get("act")] = max(best.get(m.get("act"), 0), m["score"])
        out[key] = sum(v == 2 for v in best.values()) / n if n else None
    ov = g.get("overall")
    out["overall_experience"] = float(ov == 2) if ov in (0, 1, 2) else None
    return out


def score_runs(product: str, runs: list[dict], n_people: int = 40, tag: str = "") -> pd.DataFrame:
    """Per held-out person of `product`: context only vs context + run notes (raw / guided)."""
    obs = run_obs(runs)
    if not obs:
        raise RuntimeError(f"{product}: no signed-in product observations in {len(runs)} runs")
    people = product_people(product, n_people)
    pool = ThreadPoolExecutor(64)
    refs = dict(pool.map(lambda r: (r["review_id"], G.RE_extract(r)), people))
    cards = {r["review_id"]: RE.card(r, refs[r["review_id"]]["task"]) for r in people}
    pkgs = dict(pool.map(lambda r: (r["review_id"], U.build_package(RE.URLS[product], {
        "role_family": cards[r["review_id"]]["role_family"], "company_size": r["reviewer_company_size"],
        "time_used": r["reviewer_time_used_product"], "industry": r["reviewer_industry"]},
        exclude_product=product, mask=U.mask_for(product))), people))
    obs_txt = "\n".join(obs)

    def one(job):
        r, cond = job
        rid = r["review_id"]
        ev = "\nData:\n" + "\n\n".join(pkgs[rid]["sections"].values())
        key = f"{rid}|agent_full"
        if cond == "run_raw":
            ev += "\n\n" + RUN_RAW.format(product=product, obs=obs_txt)
            key = f"{rid}|hm_raw|{E.sha(obs_txt)[:10]}"
        elif cond == "run_guided":
            ev += "\n\n" + RUN_GUIDED.format(product=product, obs=obs_txt)
            key = f"{rid}|hm_guided|{E.sha(obs_txt)[:10]}"
        rec = E.call_model("router_predict" if cond == "context" else "hm_predict", FLASH, MT.PRED_SYSTEM,
                           RE.PRED.format(**cards[rid], evidence=ev), temperature=E.PREDICT_TEMPERATURE, seed=1000,
                           max_tokens=8192, thinking_budget=1024, key_extra=key)
        j = rec.get("json") if isinstance(rec.get("json"), dict) else {}
        row = {"product": product, "rid": rid, "cond": cond, **judge_one(j, refs[rid], E.review_for_extraction(r))}
        for out_, (lo, hi) in U.RATINGS.items():
            v = RE.U_num(j.get(out_), lo, hi)
            if v is not None and r.get(out_) is not None:
                row[f"err_{out_}"] = abs(v - r[out_])
        return row
    rows = list(pool.map(one, [(r, c) for r in people for c in ("context", "run_raw", "run_guided")]))
    D = pd.DataFrame(rows)
    HOUT.mkdir(parents=True, exist_ok=True)
    D.to_csv(HOUT / f"run_signal_{L_slug(product)}{tag}.csv", index=False)
    return D


def L_slug(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def summarize(D: pd.DataFrame) -> pd.DataFrame:
    cols = ["pros", "cons", "overall_experience"] + [c for c in D.columns if c.startswith("err_")]
    return D.groupby("cond")[cols].mean().round(3)


def basecamp() -> None:
    runs = [json.loads(p.read_text()) for p in sorted((HOUT / "runs").glob("*.json"))]
    D = score_runs("Basecamp", runs, tag="_bench5")
    pd.set_option("display.width", 220)
    print(summarize(D).T)
    print(f"spend ${E.spent_usd():.3f}")


if __name__ == "__main__":
    {"observability": observability, "basecamp": basecamp}[sys.argv[1]]()
