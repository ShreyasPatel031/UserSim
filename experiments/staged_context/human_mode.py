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


DEEP_TASK = """You are writing the task for a simulated user who will sign up for {product} ({url}) and use it for one
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


def deep_task(product: str, url: str, persona: str, rival_text: str) -> dict:
    rec = E.call_model("hm_task", FLASH, "You design realistic product-usage sessions. Return JSON only.",
                       DEEP_TASK.format(product=product, url=url, persona=persona, rival=rival_text[:3500]),
                       temperature=0.0, seed=42, max_tokens=2048, thinking_budget=512)
    return rec.get("json") if isinstance(rec.get("json"), dict) else {}


def rival_complaints(category: str | None, exclude: str, live_names: list[str] | None = None, k: int = 25) -> str:
    """Cons written by competitors' users: live scrapes of named rivals when given, else the category's snapshot."""
    import live as L  # noqa: PLC0415
    if live_names:
        f = pd.concat([L.frame(n) for n in live_names if (L.LIVE / f"{L.slug(n)}.json").is_file()], ignore_index=True)
    else:
        f = U.competitors(category, exclude).rename(columns={"product_name": "product"})
    f = f[f.cons.notna() & (f.cons.astype(str).str.len() > 40)]
    f = f.assign(_h=f["product"].astype(str) + f.cons.astype(str)).assign(_h=lambda d: d._h.map(lambda x: E.sha(x)))
    return "\n".join(f"- [{r['product']}] {E.clean(r['cons'])[:200]}" for r in f.sort_values("_h").head(k).to_dict("records"))


def basecamp() -> None:
    runs = [json.loads(p.read_text()) for p in sorted((HOUT / "runs").glob("*.json"))]
    D = score_runs("Basecamp", runs, tag="_bench5")
    pd.set_option("display.width", 220)
    print(summarize(D).T)
    print(f"spend ${E.spent_usd():.3f}")


# ----------------------------------------------------------------------------- oracle notes: how to inject product facts

NOTES_RAW = """## Notes on {product} itself (facts about THIS product)
{obs}"""
NOTES_CAND = """## Candidate pros and cons of {product} itself (facts about THIS product, not about the other products above)
{obs}
Choose this person's pros and cons mainly from these candidates, keeping only those that fit their role, task and
company size, and phrase them specifically. Keep ratings anchored on the data above (these notes do not change the
typical level)."""


def oracle(n_notes: tuple[int, ...] = (4, 12)) -> None:
    """Upper bound for human mode: inject product facts taken from OTHER real reviewers of the same product (never the
    held-out person) in different formats and amounts; see which format turns product facts into better predictions.
    Held-out people = router_eval TEST people (their context-only predictions are cached)."""
    df = U.data()
    people = [r for r in RE.sample(df) if r["product_name"] in RE.TEST]
    held = {r["review_id"] for r in RE.sample(df)}
    pool = ThreadPoolExecutor(64)
    refs = dict(pool.map(lambda r: (r["review_id"], G.RE_extract(r)), people))
    cards = {r["review_id"]: RE.card(r, refs[r["review_id"]]["task"]) for r in people}
    pkgs = dict(pool.map(lambda r: (r["review_id"], U.build_package(RE.URLS[r["product_name"]], {
        "role_family": cards[r["review_id"]]["role_family"], "company_size": r["reviewer_company_size"],
        "time_used": r["reviewer_time_used_product"], "industry": r["reviewer_industry"]},
        exclude_product=r["product_name"], mask=U.mask_for(r["product_name"]))), people))
    notes = {}
    for prod in RE.TEST:
        others = [r for r in product_people(prod, 60) if r["review_id"] not in held][:12]
        ex = list(pool.map(G.RE_extract, others))
        pts = []
        for e in ex:  # interleave: one friction and one benefit per reviewer
            pts += [f"- [friction] {x}" for x in e["frictions"][:1]] + [f"- [benefit] {x}" for x in e["benefits"][:1]]
        notes[prod] = pts
    E.write_json(HOUT / "oracle_notes.json", notes)

    def one(job):
        r, cond = job
        rid, prod = r["review_id"], r["product_name"]
        ev = "\nData:\n" + "\n\n".join(pkgs[rid]["sections"].values())
        key, stage = f"{rid}|agent_full", "router_predict"
        if cond != "context":
            fmt, k = cond.split("_")
            obs = "\n".join(notes[prod][:int(k)])
            ev += "\n\n" + {"raw": NOTES_RAW, "guided": RUN_GUIDED, "cand": NOTES_CAND}[fmt].format(product=prod, obs=obs)
            key, stage = f"{rid}|oracle|{cond}|{E.sha(obs)[:10]}", "hm_oracle"
        rec = E.call_model(stage, FLASH, MT.PRED_SYSTEM, RE.PRED.format(**cards[rid], evidence=ev),
                           temperature=E.PREDICT_TEMPERATURE, seed=1000, max_tokens=8192, thinking_budget=1024, key_extra=key)
        j = rec.get("json") if isinstance(rec.get("json"), dict) else {}
        row = {"product": prod, "rid": rid, "cond": cond, **judge_one(j, refs[rid], E.review_for_extraction(r))}
        for out_, (lo, hi) in U.RATINGS.items():
            v = RE.U_num(j.get(out_), lo, hi)
            if v is not None and r.get(out_) is not None:
                row[f"err_{out_}"] = abs(v - r[out_])
        return row
    conds = ["context"] + [f"{f}_{k}" for f in ("raw", "guided", "cand") for k in n_notes]
    D = pd.DataFrame(list(pool.map(one, [(r, c) for r in people for c in conds])))
    D.to_csv(HOUT / "oracle.csv", index=False)
    pd.set_option("display.width", 220)
    print(summarize(D).T)
    print(f"spend ${E.spent_usd():.3f}")


# ----------------------------------------------------------------------------- product-level: what will users praise / complain about

PLIST = """Predict what real, long-term users of {product} ({url}) most often praise and complain about in reviews.
{evidence}
Return {{"pros": [6 short, specific points, most common first], "cons": [6 short, specific points, most common first],
 "overall_rating": typical 1-5 star rating}}"""
CTX_HEAD = """## Data on competitors' users (other products in the same category; not {product} itself)
{ctx}"""
RUN_HEAD = """## Hands-on notes: simulated new users used {product} itself today (signed in, free plan or trial, demo data)
{obs}"""
BOTH_GUIDE = """How to combine: the competitor data says which themes users of this kind of product praise and complain about.
The hands-on notes are facts about {product} itself: use them to decide which of those themes apply to {product},
which do not, and which {product}-specific themes to add. Write every point the way long-term reviewers write them
(e.g. "easy to use", "reporting is basic", "free plan too limited"), not as UI steps or click-level details.
Setup and first-use friction fades for long-term users; missing features and clumsy core workflows do not.
Base the typical rating on the competitor data; the notes move it by at most a quarter star."""
JUDGE_SIDE = """A product team predicted the most common {side} of a product. Compare them with one real reviewer's {side}.
Score each (predicted, actual) pair 2 = same specific point, 1 = same general area but vaguer, 0 = different.
Predicted {side}:
{pp}
This reviewer's actual {side}:
{ap}
Return {{"pairs": [{{"pred": "P1", "act": "A1", "score": 2}}]}} listing only pairs scoring 1 or 2."""


def judge_list(pl: dict, ref: dict) -> dict:
    """Pros and cons judged in separate calls, so a side's score depends only on that side's list."""
    fmt = lambda xs, p: "\n".join(f"{p}{i + 1}: {x}" for i, x in enumerate(xs)) or "(none)"  # noqa: E731
    lst = lambda x: [str(v) for v in x][:6] if isinstance(x, list) else []  # noqa: E731
    out = {}
    for key, side, acts_src in (("pros", "pros (things they liked)", "benefits"), ("cons", "cons (things that frustrated them)", "frictions")):
        n = len(ref[acts_src])
        if not n:
            out[f"{key}_recall"] = out[f"{key}_covered"] = None
            continue
        g = E.call_model("hm_side_judge", FLASH, "You are a strict evaluator. Return JSON only.", JUDGE_SIDE.format(
            side=side, pp=fmt(lst(pl.get(key)), "P"), ap=fmt(ref[acts_src], "A")), temperature=0.0, seed=42,
            max_tokens=2048, thinking_budget=512)
        g = g.get("json") if isinstance(g.get("json"), dict) else {}
        acts = {m.get("act") for m in g.get("pairs") or [] if isinstance(m, dict) and m.get("score") == 2}
        out[f"{key}_recall"] = len(acts) / n
        out[f"{key}_covered"] = float(bool(acts))
    return out


N_SEEDS = 3
FIRST_SESSION = {"free_plan_or_tier_limits", "setup_configuration", "onboarding_learning_curve", "pricing_cost",
                 "billing_contract", "customer_support"}
OBS_THEME = """Give each observation's theme, one of {themes}.
{obs}
Return {{"themes": ["<theme of line 1>", ...]}} in order."""


def filter_first_session(product: str, obs: list[str]) -> list[str]:
    """Drop notes about free-plan limits, setup, onboarding, pricing, billing, support: long-term reviewers rarely
    mention them, and context already predicts those themes (out/human_mode/themes.csv)."""
    if not obs:
        return obs
    rec = E.call_model("hm_obs_theme", FLASH, "You classify product observations. Return JSON only.",
                       OBS_THEME.format(themes=THEMES, obs="\n".join(obs)), temperature=0.0, seed=42, max_tokens=2048,
                       thinking_budget=256)
    th = (rec.get("json") or {}).get("themes") if isinstance(rec.get("json"), dict) else None
    if not isinstance(th, list) or len(th) != len(obs):
        raise RuntimeError(f"{product}: observation themes missing")
    return [o for o, t in zip(obs, th) if t not in FIRST_SESSION]


EDIT = """Here are predicted pros and cons of {product} written from data on competitors' users:
{lists}

A simulated new user then used {product} itself (signed in, demo data) and noted:
{obs}

Revise the prediction using the notes, changing AT MOST {k} pro(s) and AT MOST {k} con(s):
- replace an item only when a note directly contradicts it or shows a clearly more {product}-specific version of it,
- write replacements the way long-term reviewers write (themes such as "easy to use", "reporting is basic"), not UI
  steps; first-session friction (setup, empty states, free-plan limits) fades for long-term users,
- keep every other item exactly as it is, in the same order.
Return {{"pros": [6 items], "cons": [6 items], "changed": ["what you changed and which note justified it", ...]}}"""


def edit_list(product: str, base: dict, obs: list[str], k: int, seed: int) -> dict:
    lists = "Pros:\n" + "\n".join(f"- {x}" for x in base.get("pros") or []) + "\nCons:\n" + "\n".join(
        f"- {x}" for x in base.get("cons") or [])
    rec = E.call_model("hm_edit", FLASH, "You revise product predictions conservatively. Return JSON only.",
                       EDIT.format(product=product, lists=lists, obs="\n".join(obs), k=k), temperature=0.0 if seed == 0 else 0.7,
                       seed=42 + seed, max_tokens=4096, thinking_budget=1024)
    j = rec.get("json") if isinstance(rec.get("json"), dict) else {}
    out = {"pros": j.get("pros") or base.get("pros"), "cons": j.get("cons") or base.get("cons"),
           "overall_rating": base.get("overall_rating"), "changed": j.get("changed")}
    return out


def product_list(product: str, url: str, cond: str, ctx: str, obs: list[str], seed: int = 0) -> dict:
    parts = []
    if "ctx" in cond:
        parts.append(CTX_HEAD.format(product=product, ctx=ctx))
    if "run" in cond:
        parts.append(RUN_HEAD.format(product=product, obs="\n".join(obs)))
    if cond == "ctx+run":
        parts.append(BOTH_GUIDE.format(product=product))
    ev = ("\n\n".join(parts)) if parts else "(no data: use what you know)"
    rec = E.call_model("hm_plist", FLASH, "You predict product reviews. Return JSON only.",
                       PLIST.format(product=product, url=url, evidence=ev), temperature=0.0 if seed == 0 else 0.7,
                       seed=42 + seed, max_tokens=4096, thinking_budget=1024, key_extra=cond)
    return rec.get("json") if isinstance(rec.get("json"), dict) else {}


def truth_people(product: str, n: int = 40) -> tuple[list[dict], dict]:
    """Real reviewers of the product with extracted benefits / frictions: Capterra snapshot, else the live scrape."""
    if product in set(U.data().product_name):
        ppl = product_people(product, n)
        refs = dict(ThreadPoolExecutor(32).map(lambda r: (r["review_id"], G.RE_extract(r)), ppl))
        return [{"rid": r["review_id"], "overall_rating": r["overall_rating"]} for r in ppl], refs
    import live as L  # noqa: PLC0415
    f = L.frame(product)
    f = f[f.pros.notna() & f.cons.notna()]
    f = f.assign(_h=f.rid.map(lambda i: E.sha(f"42|hmlive|{product}|{i}"))).sort_values("_h").head(n)

    def ex(r):
        text = f"Liked: {r['pros']}\nDisliked: {r['cons']}\n{E.clean(r.get('review_text'))}"
        rec = E.call_model("hm_live_extract", FLASH, "You extract claims from reviews. Return JSON only.",
                           RE.EXTRACT.format(product=product, text=text), temperature=0.0, seed=42, max_tokens=4096,
                           thinking_budget=512)
        j = rec.get("json") if isinstance(rec.get("json"), dict) else {}
        return r["rid"], {"task": j.get("task"), "benefits": [str(x) for x in (j.get("benefits") or [])][:4],
                          "frictions": [str(x) for x in (j.get("frictions") or [])][:4]}
    rows = f.to_dict("records")
    return [{"rid": r["rid"], "overall_rating": r["overall_rating"]} for r in rows], dict(ThreadPoolExecutor(32).map(ex, rows))


def agent_context(product: str, url: str, category: str | None, live_rivals: list[str] | None) -> str:
    """Agent-mode stand-in: competitor ratings / complaint topics + a sample of competitor reviews (product excluded)."""
    if live_rivals:
        import live as L  # noqa: PLC0415
        comp = pd.concat([L.frame(n) for n in live_rivals if (L.LIVE / f"{L.slug(n)}.json").is_file()], ignore_index=True)
        cons = comp.cons.fillna("").astype(str).str.lower()
        import predictability as PR  # noqa: PLC0415
        head = (f"Competitors (live reviews from G2 / Capterra / TrustRadius / Gartner): {', '.join(sorted(comp['product'].unique()))}"
                f" ({len(comp)} reviews).\nAverage overall rating: {comp.overall_rating.mean():.2f}\nComplaint topics in their cons:\n"
                + "\n".join(f"- {k.replace('complaint_', '')}: {cons.str.contains(p_, regex=True).mean():.1%} mention it"
                            for k, p_ in PR.TOPICS.items()))
    else:
        head = U.competitor_section(U.competitors(category, product))
    return head + "\n\nSample of competitor users' cons:\n" + rival_complaints(category, product, live_rivals)


def product_eval(product: str, runs: list[dict], tag: str, live_rivals: list[str] | None = None) -> pd.DataFrame:
    t = E.read_json(HOUT / "run_tasks.json")[product]
    url, cat = t["url"], t["category"]
    if live_rivals is None and product not in set(U.data().product_name):  # not in the snapshot: live named rivals
        live_rivals = E.read_json(E.OUT / "mixture" / "competitors.json")[product][:3]
    obs = run_obs(runs)
    ctx = agent_context(product, url, cat, live_rivals)
    ppl, refs = truth_people(product)
    conds = ["none", "ctx"] + (["run", "ctx+run", "ctx+runF", "prosRunF_consCtx", "edit1", "edit2", "edit1F"] if obs else [])
    obs_f = filter_first_session(product, obs)
    lists = {}
    for seed in range(N_SEEDS):
        L_ = {c: product_list(product, url, c, ctx, obs, seed) for c in conds if c in ("none", "ctx", "run", "ctx+run")}
        if obs:
            L_["ctx+runF"] = product_list(product, url, "ctx+run", ctx, obs_f, seed) if obs_f else L_["ctx"]
            L_["prosRunF_consCtx"] = {"pros": L_["ctx+runF"].get("pros"), "cons": L_["ctx"].get("cons"),
                                      "overall_rating": L_["ctx"].get("overall_rating")}
            L_["edit1"] = edit_list(product, L_["ctx"], obs, 1, seed)
            L_["edit2"] = edit_list(product, L_["ctx"], obs, 2, seed)
            L_["edit1F"] = edit_list(product, L_["ctx"], obs_f, 1, seed) if obs_f else L_["ctx"]
        lists[seed] = L_
    pool = ThreadPoolExecutor(64)
    rows = list(pool.map(lambda job: {"product": product, "tag": tag, "rid": job[0]["rid"], "cond": job[1], "seed": job[2],
                                      **judge_list(lists[job[2]][job[1]], refs[job[0]["rid"]])},
                         [(p, c, sd) for p in ppl for c in conds for sd in range(N_SEEDS)]))
    D = pd.DataFrame(rows)
    true_mean = float(pd.Series([p["overall_rating"] for p in ppl]).mean())
    E.write_json(HOUT / f"plist_{L_slug(product)}_{tag}.json", {"lists": lists, "obs": obs, "obs_filtered": obs_f,
                                                                "true_mean_overall": true_mean})
    D.to_csv(HOUT / f"plist_{L_slug(product)}_{tag}.csv", index=False)
    return D


def product_summary(D: pd.DataFrame) -> pd.DataFrame:
    return D.groupby(["product", "tag", "cond"])[["pros_recall", "pros_covered", "cons_recall", "cons_covered"]].mean().round(3)


RUN_PRODUCTS = {  # product -> (url, persona for the run, source of rival complaints)
    "Basecamp": ("https://basecamp.com/", "a project manager at a 30-person agency", None),
    "Zoho Desk": ("https://www.zoho.com/desk/", "a support team lead at a 40-person software company", None),
    "Klaviyo": ("https://www.klaviyo.com/", "an e-commerce marketing manager at a small online store", None),
    "Freshdesk": ("https://www.freshworks.com/freshdesk/", "a customer support manager at a 60-person company", None),
    "Teamwork.com": ("https://www.teamwork.com/", "an account manager at a 25-person creative agency", "live"),
    "Bitwarden": ("https://bitwarden.com/", "an IT admin at a 50-person company", None),
}


def make_tasks() -> None:
    comps = E.read_json(E.OUT / "mixture" / "competitors.json")
    out = {}
    for p, (url, persona, src) in RUN_PRODUCTS.items():
        cat = U.recorded_category(url) or U.classify(url)["category"]
        rival = rival_complaints(cat, p, comps[p][:3] if src == "live" else None)
        t = deep_task(p, url, persona, rival)
        out[p] = {"url": url, "persona": persona, "category": cat, **t}
        print(p, "|", t.get("task"))
    E.write_json(HOUT / "run_tasks.json", out)


if __name__ == "__main__":
    {"observability": observability, "basecamp": basecamp, "tasks": make_tasks, "oracle": oracle, "plist_basecamp_old": lambda: print(product_summary(product_eval(
    "Basecamp", [json.loads(p.read_text()) for p in sorted((HOUT / "runs").glob("*.json"))], "bench5")))}[sys.argv[1]]()
