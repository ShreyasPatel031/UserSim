"""G2 version of own_reviews_bench: 200 G2 reviewers (g2_merge's 20 products), same predictor and judge.

agent_full = g2_merge's G2-source package (cache hit). own_similar adds the product's own earlier G2 reviews (rating
line over the last 100, shrunk to same-category rivals with k=10, plus 8 most similar earlier reviewers).

    EXP_SPEND_CAP_USD=80 python own_reviews_bench_g2.py
"""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

CTX = Path(os.environ.get("CTX_ROOT", "/home/user/UserSim-ctx"))
sys.path.insert(0, str(CTX / "experiments/staged_context"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import corpus as C  # noqa: E402
import experiment as E  # noqa: E402
import g2_merge as G  # noqa: E402
import heldout_bench as HB  # noqa: E402
import matched as MT  # noqa: E402
import router_eval as RE  # noqa: E402
import ux_mcp as U  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "results/own_reviews_bench_g2"
FLASH = RE.FLASH
CONDS = ["agent_full", "own_similar"]
K, LAST = 10, 100


def own_section(r: dict, d: pd.DataFrame) -> str:
    g2 = d[d.source == "g2"]
    own = g2[(g2["product"] == r["product"]) & (g2.date < r["date"]) & (g2.rid != r["rid"])].sort_values("date")
    cat = g2[(g2.category == r["category"]) & (g2["product"] != r["product"])]
    v = own.overall_rating.dropna().to_numpy()[-LAST:]
    prior = cat.overall_rating.mean()
    est = (v.sum() + K * prior) / (len(v) + K)
    line = (f"- overall_rating: last {len(v)} reviews of this product average {v.mean() if len(v) else float('nan'):.2f}; "
            f"same-category rivals {prior:.2f}; combined estimate {est:.2f}")
    pool = own.tail(200)
    s = 3 * (pool.role_family == r["role_family"]) + 2 * (pool.size3 == r["size3"]) + (pool.industry == r["industry"])
    pool = pool.assign(_s=s).sort_values(["_s", "date"], ascending=[False, False]).head(8)
    revs = [f"role: {E.clean(x['title']) or '-'}; size: {x['size3'] or '-'}; rating: {x['overall_rating']}\n"
            f"Liked: {E.clean(x['pros'])[:400]}\nDisliked: {E.clean(x['cons'])[:400]}" for x in pool.to_dict("records")]
    return (f"## This product's own earlier reviews (other people; {len(own)} available)\nRatings:\n{line}\n\n"
            "Most similar earlier reviewers:\n" + "\n\n".join(revs))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pool = ThreadPoolExecutor(96)
    d = C.corpus().copy()
    d["date"] = HB.frame().date.values  # same rows, same order; keep corpus's own product names and categories
    dates = d.set_index("rid").date
    gp, g_dev, _ = G.g2_people()
    for r in gp:
        r["date"] = dates.get(r["rid"])

    def g2_extract(r):  # identical to g2_merge -> cache hit
        text = f"Liked: {r['pros']}\nDisliked: {r['cons']}\nProblems solved: {r.get('problems_solved') or ''}"
        rec = E.call_model("g2_extract", FLASH, "You extract claims from reviews. Return JSON only.",
                           RE.EXTRACT.format(product=r["product"], text=text), temperature=0.0, seed=42, max_tokens=4096,
                           thinking_budget=512)
        j = rec.get("json") if isinstance(rec.get("json"), dict) else {}
        task = j.get("task") if isinstance(j.get("task"), str) and not MT.LEAK.search(j.get("task") or "") else None
        return r["rid"], {"task": task, "benefits": [str(x) for x in (j.get("benefits") or [])][:4],
                          "frictions": [str(x) for x in (j.get("frictions") or [])][:4]}

    refs = dict(pool.map(g2_extract, gp))
    cards = {r["rid"]: {"product": r["product"], "url": "no URL given", "role_title": E.clean(r["title"]),
                        "role_family": r["role_family"], "industry": r["industry"] or "not stated",
                        "company_size": r["size3"], "time_used": "not recorded", "task": refs[r["rid"]]["task"] or "not stated",
                        "previous": "not stated"} for r in gp}
    rows = {r["rid"]: r for r in gp}
    pkgs = dict(pool.map(lambda r: (r["rid"], C.sections({"role_family": r["role_family"], "size3": r["size3"], "industry": r["industry"]},
                                                         r["category"], G.SRC["g2"], r["product"], U.mask_for(r["product"]))), gp))

    def predict(job):
        rid, mode = job
        ev = "\nData:\n" + "\n\n".join(pkgs[rid]["sections"].values())
        if mode == "own_similar":
            ev += "\n\n" + own_section(rows[rid], d)
        key = f"{rid}|g2|agent_full" if mode == "agent_full" else f"{rid}|g2|{mode}"
        rec = E.call_model("g2_predict" if mode == "agent_full" else "own_predict_g2", FLASH, MT.PRED_SYSTEM,
                           RE.PRED.format(**cards[rid], evidence=ev), temperature=E.PREDICT_TEMPERATURE, seed=1000,
                           max_tokens=8192, thinking_budget=1024, key_extra=key)
        return job, rec.get("json") if isinstance(rec.get("json"), dict) else {}

    preds = dict(pool.map(predict, [(r["rid"], m) for r in gp for m in CONDS]))

    def judge(job):
        rid, _ = job
        j, ref, r = preds[job], refs[rid], rows[rid]
        lst = lambda x: [str(v) for v in x][:3] if isinstance(x, list) else []  # noqa: E731
        fmt = lambda xs, p: "\n".join(f"{p}{i + 1}: {x}" for i, x in enumerate(xs)) or "(none)"  # noqa: E731
        rec = E.call_model("g2_judge", FLASH, "You are a strict evaluator. Return JSON only.",
                           RE.JUDGE.format(pp=fmt(lst(j.get("pros")), "P"), ap=fmt(ref["benefits"], "A"),
                                           pc=fmt(lst(j.get("cons")), "P"), ac=fmt(ref["frictions"], "A"),
                                           po=str(j.get("overall_experience") or ""),
                                           at=str(r.get("review_text") or f"Liked: {r['pros']} Disliked: {r['cons']}")),
                           temperature=0.0, seed=42, max_tokens=4096, thinking_budget=512)
        g = rec.get("json") if isinstance(rec.get("json"), dict) else {}

        def recall(key, n):
            best = {}
            for m in g.get(key) or []:
                if isinstance(m, dict) and m.get("score") in (1, 2):
                    best[m.get("act")] = max(best.get(m.get("act"), 0), m["score"])
            return (sum(v == 2 for v in best.values()) / n) if n else None
        ov = g.get("overall")
        return job, {"pros": recall("pros", len(ref["benefits"])), "cons": recall("cons", len(ref["frictions"])),
                     "overall_experience": float(ov == 2) if ov in (0, 1, 2) else None}

    judged = dict(pool.map(judge, list(preds)))
    out = []
    for (rid, m), j in preds.items():
        r = rows[rid]
        v = RE.U_num(j.get("overall_rating"), 1, 5)
        out.append({"rid": rid, "product": r["product"], "split": "dev" if r["product"] in g_dev else "test", "cond": m,
                    "overall_rating_pred": v, "overall_rating_y": r["overall_rating"],
                    "overall_rating_abs_err": abs(v - r["overall_rating"]) if v is not None else None, **judged[(rid, m)]})
    M = pd.DataFrame(out)
    M.to_csv(OUT / "per_person.csv", index=False)
    cols = ["overall_rating_abs_err", "pros", "cons", "overall_experience"]
    S = M.groupby("cond")[cols].mean().loc[CONDS]
    S.to_csv(OUT / "summary.csv")
    print(S.round(3).T.to_string())
    print(f"spend so far ${E.spent_usd():.2f}")


if __name__ == "__main__":
    main()
