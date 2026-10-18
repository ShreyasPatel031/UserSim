"""End-to-end held-out eval of the SHIPPED agent mode (mvp/agent_mode.py): its rating math, persona offsets, evidence
builder and words prompt, fed snapshot reviews shaped like live scrapes.

People: router_eval's 420 Capterra reviewers and g2_merge's 200 G2 reviewers. Baseline: the handoff's context agent
(agent_full, cached). For each person, agent mode gets:
  own     the product's own reviews dated before this person's (most recent first, up to 100), from their platform
  rivals  the RIVALS most-reviewed other products in the same category on that platform, 50 recent reviews each
          (production scrapes the named rivals live; the snapshots stand in for them here, research only)
Words go through agent_mode.WORDS_PROMPT with Gemini 2.5 Flash (cached) and the same judge as router_eval.

    EXP_SPEND_CAP_USD=80 python agent_mode_eval.py
"""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

CTX = Path(os.environ.get("CTX_ROOT", "/home/user/UserSim-ctx"))
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(CTX / "experiments/staged_context"))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

import corpus as C  # noqa: E402
import experiment as E  # noqa: E402
import g2_merge as G  # noqa: E402
import heldout_bench as HB  # noqa: E402
import router_eval as RE  # noqa: E402
import ux_mcp as U  # noqa: E402

from mvp import agent_mode as A  # noqa: E402

OUT = HERE / "results/agent_mode_eval"
RIVALS, PER_RIVAL = 3, 50
FLASH = RE.FLASH


def live_shape(r: dict) -> dict:
    """A snapshot review in the live-scrape schema agent_mode reads."""
    g = lambda k: None if (r.get(k) is None or (isinstance(r.get(k), float) and np.isnan(r[k]))) else r[k]  # noqa: E731
    return {"source": r["source"], "product": r["product"], "role": g("title") if r["source"] == "g2" else g("role_title"),
            "size": g("size_fine") or g("size3"), "industry": g("industry"), "time_used": g("time_used"),
            "rating": g("overall_rating"), "ease": g("ease_of_use_rating"), "nps": g("recommendation_score"),
            "pros": g("pros"), "cons": g("cons"),
            # Capterra's summary comment; for G2 the full review text (live scrapes return it as `text`)
            "text": (" ".join(x for x in (g("general_comments"), g("reasons_for_choosing"), g("reasons_for_switching")) if x)
                     if "own_reasons" in VARIANT else g("general_comments")) if r["source"] == "capterra" else g("review_text")}


VARIANT = os.environ.get("AM_VARIANT", "")  # ablations: "rivals_category", "own_reasons", or both joined by "+"


def main() -> None:
    global OUT
    if VARIANT:
        OUT = OUT.parent / f"agent_mode_eval_{VARIANT.replace('+', '_')}"
    OUT.mkdir(parents=True, exist_ok=True)
    d = C.corpus().copy()
    d["date"] = HB.frame().date.values
    cap = U.data().set_index(U.data().review_id.astype(str))
    d["role_title"] = d.rid.str[2:].map(cap.reviewer_job_title).where(d.source == "capterra")
    for col in ("general_comments", "reasons_for_choosing", "reasons_for_switching"):
        d[col] = d.rid.str[2:].map(cap[col]).where(d.source == "capterra")
    pool = ThreadPoolExecutor(96)

    # people: Capterra (router_eval) and G2 (g2_merge), with their cards and extracted references (cache hits)
    people = []
    for r in RE.sample(U.data()):
        people.append({"rid": "C:" + str(r["review_id"]), "orig": r, "source": "capterra", "product": r["product_name"],
                       "category": r["product_category_group"]})
    gp, _, _ = G.g2_people() if (not VARIANT or "no_own" in VARIANT) else ([], [], [])
    for r in gp:
        people.append({"rid": r["rid"], "orig": r, "source": "g2", "product": r["product"], "category": r["category"]})
    by_rid = d.set_index("rid")

    def refs_card(p):
        r = p["orig"]
        if p["source"] == "capterra":
            rec = E.call_model("router_extract", FLASH, "You extract claims from reviews. Return JSON only.",
                               RE.EXTRACT.format(product=r["product_name"], text=E.review_for_extraction(r)), temperature=0.0,
                               seed=42, max_tokens=4096, thinking_budget=512)
            text = E.review_for_extraction(r)
        else:
            t = f"Liked: {r['pros']}\nDisliked: {r['cons']}\nProblems solved: {r.get('problems_solved') or ''}"
            rec = E.call_model("g2_extract", FLASH, "You extract claims from reviews. Return JSON only.",
                               RE.EXTRACT.format(product=r["product"], text=t), temperature=0.0, seed=42, max_tokens=4096,
                               thinking_budget=512)
            text = str(r.get("review_text") or f"Liked: {r['pros']} Disliked: {r['cons']}")
        j = rec.get("json") if isinstance(rec.get("json"), dict) else {}
        return p["rid"], {"task": j.get("task") if isinstance(j.get("task"), str) else None,
                          "benefits": [str(x) for x in (j.get("benefits") or [])][:4],
                          "frictions": [str(x) for x in (j.get("frictions") or [])][:4], "text": text}

    refs = dict(pool.map(refs_card, people))

    def persona(p):
        r = p["orig"]
        if p["source"] == "capterra":
            return {"role": E.clean(r["reviewer_job_title"]), "company_size": r["reviewer_company_size"],
                    "industry": r["reviewer_industry"], "time_used": r["reviewer_time_used_product"],
                    "previous": RE.card(r, None)["previous"]}
        return {"role": E.clean(r["title"]), "company_size": r["size3"], "industry": r["industry"]}

    def evidence(p):
        src, prod, date = p["source"], p["product"], by_rid.loc[p["rid"], "date"]
        own = d[(d.source == src) & (d["product"] == prod) & (d.date < date) & (d.rid != p["rid"])].sort_values("date", ascending=False)
        comp = d[(d.source == src) & (d.category == p["category"]) & (d["product"] != prod)]
        top = comp.groupby("product").size().sort_values(ascending=False).index[:RIVALS]
        riv = pd.concat([comp[comp["product"] == t].sort_values("date", ascending=False).head(PER_RIVAL) for t in top]) if len(top) else comp.head(0)
        if "rivals_category" in VARIANT:  # research layout: similar reviews drawn from the whole category
            riv, top = comp, list(comp["product"].unique())
        if "no_own" in VARIANT:  # a net-new product: no reviews of its own exist
            own = own.head(0)
        return [live_shape(x) for x in own.head(A.LAST).to_dict("records")], [live_shape(x) for x in riv.to_dict("records")], list(top)

    def run(p):
        own, riv, top = evidence(p)
        per = persona(p)
        ratings = A.rating_estimates(own, riv)
        A.personalize(ratings, per)
        url = RE.URLS.get(p["product"], "") if p["source"] == "capterra" else ""
        prompt = A.words_prompt(p["product"], url, per, refs[p["rid"]]["task"], A.evidence_text(p["product"], own, riv, per, ratings)[:14000])
        rec = E.call_model("agent_mode_words_v4" + (f"_{VARIANT}" if VARIANT else ""), FLASH, A.WORDS_SYSTEM, prompt, temperature=0.7, seed=1000, max_tokens=8192,
                           thinking_budget=A.WORDS_THINKING, key_extra=p["rid"] + (f"|{VARIANT}" if VARIANT else ""))
        words = rec.get("json") if isinstance(rec.get("json"), dict) else {}
        return p["rid"], {"ratings": ratings, "words": words, "rivals": top, "n_own": len(own)}

    res = dict(pool.map(run, people))

    def judge(p):
        w, ref = res[p["rid"]]["words"], refs[p["rid"]]
        lst = lambda x: [str(v) for v in x][:3] if isinstance(x, list) else []  # noqa: E731
        fmt = lambda xs, q: "\n".join(f"{q}{i + 1}: {x}" for i, x in enumerate(xs)) or "(none)"  # noqa: E731
        rec = E.call_model("router_judge" if p["source"] == "capterra" else "g2_judge", FLASH,
                           "You are a strict evaluator. Return JSON only.",
                           RE.JUDGE.format(pp=fmt(lst(w.get("pros")), "P"), ap=fmt(ref["benefits"], "A"), pc=fmt(lst(w.get("cons")), "P"),
                                           ac=fmt(ref["frictions"], "A"), po=str(w.get("overall_experience") or ""), at=ref["text"]),
                           temperature=0.0, seed=42, max_tokens=4096, thinking_budget=512)
        g = rec.get("json") if isinstance(rec.get("json"), dict) else {}

        def recall(key, n):
            best = {}
            for m in g.get(key) or []:
                if isinstance(m, dict) and m.get("score") in (1, 2):
                    best[m.get("act")] = max(best.get(m.get("act"), 0), m["score"])
            return (sum(v == 2 for v in best.values()) / n) if n else None
        ov = g.get("overall")
        return p["rid"], {"pros": recall("pros", len(ref["benefits"])), "cons": recall("cons", len(ref["frictions"])),
                          "overall_experience": float(ov == 2) if ov in (0, 1, 2) else None}

    judged = dict(pool.map(judge, people))
    rows = []
    for p in people:
        if p["rid"] not in res:
            continue
        r, out = p["orig"], res[p["rid"]]
        row = {"rid": p["rid"], "source": p["source"], "product": p["product"], "n_own": out["n_own"], **judged[p["rid"]]}
        for o in ("overall_rating", "ease_of_use_rating", "recommendation_score"):
            y = r.get(o)
            rec = out["ratings"].get(o) or {}
            row[f"{o}_y"] = y
            row[f"{o}_shown"] = rec.get("for_this_persona")
            row[f"{o}_model"] = RE.U_num(out["words"].get(o), *A.OUT_SCALE[o])
            for k in ("estimate", "for_this_persona"):
                v = rec.get(k)
                row[f"{o}_{k}_abs_err"] = abs(v - y) if v is not None and y is not None and not (isinstance(y, float) and np.isnan(y)) else None
        rows.append(row)
    M = pd.DataFrame(rows)
    M.to_csv(OUT / "per_person.csv", index=False)
    # baselines from the earlier benches (same people, same judge)
    base_c = pd.read_csv(HERE / "results/own_reviews_bench/per_person.csv")
    base_g = pd.read_csv(HERE / "results/own_reviews_bench_g2/per_person.csv")
    base = pd.concat([base_c.assign(rid="C:" + base_c.rid.astype(str), source="capterra"), base_g.assign(source="g2")])
    pd.set_option("display.width", 250)
    for src in (("capterra",) if (VARIANT and "no_own" not in VARIANT) else ("capterra", "g2")):
        b = base[base.source == src].groupby("cond")[["pros", "cons", "overall_experience"] +
                                                    [c for c in base.columns if c == "overall_rating_abs_err"]].mean()
        m = M[M.source == src]
        print(f"\n== {src} (n={len(m)})\nbaselines:\n{b.round(3).to_string()}")
        print("agent mode:", m[["pros", "cons", "overall_experience"]].mean().round(3).to_dict())
        print("agent mode rating errors:", m[[c for c in m.columns if c.endswith("_abs_err")]].mean().round(3).to_dict())
    print(f"spend so far ${E.spent_usd():.2f}")


if __name__ == "__main__":
    main()
