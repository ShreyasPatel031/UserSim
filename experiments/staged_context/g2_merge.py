"""Replicate the router on G2, then test whether merging Capterra + G2 data improves predictions on both.

G2 people: 10 per product, structured likes/dislikes, job title, company size and a star rating present.
  G2 dev products choose G2's per-output strategy (G2-only data); G2 test products are held out.
Merge test (strategy per output fixed by each dataset's own router; only the data source changes):
  Capterra test people (the router_eval TEST set) with data from: Capterra / G2 / both
  G2 test people with data from: G2 / Capterra / both
G2 outputs: overall rating, pros (likes), cons (dislikes), overall experience in words, unhappy risk (rating <= 3).

    python experiments/staged_context/g2_merge.py
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus as C  # noqa: E402
import experiment as E  # noqa: E402
import matched as MT  # noqa: E402
import per_person as PP  # noqa: E402
import router_eval as RE  # noqa: E402
import ux_mcp as U  # noqa: E402

GOUT = E.OUT / "g2_merge"
PER_PRODUCT = 10
N_DEV, N_TEST = 12, 8
FLASH = "gemini-2.5-flash"
G2_OUTPUTS = ["overall_rating", "pros", "cons", "overall_experience"]
SRC = {"capterra": {"capterra"}, "g2": {"g2"}, "both": {"capterra", "g2"}}


def g2_people() -> tuple[list[dict], list[str], list[str]]:
    df = C.corpus()
    g = df[(df.source == "g2") & (df.structured == 1) & df.pros.notna() & df.cons.notna() & df.overall_rating.notna()
           & df.size3.notna() & (df.role_family != "unknown") & (df.category != "Other")]
    counts = g.groupby("product").size()
    prods = sorted(counts[counts >= 60].index, key=lambda p: E.sha(f"42|g2prod|{p}"))
    dev, test = prods[:N_DEV], prods[N_DEV:N_DEV + N_TEST]
    people = []
    for p in dev + test:
        gp = g[g["product"] == p]
        gp = gp.assign(_h=gp.rid.map(lambda i: E.sha(f"42|g2|{p}|{i}"))).sort_values("_h").head(PER_PRODUCT)
        people += [{k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in r.items()} for r in gp.to_dict("records")]
    return people, dev, test


def main() -> None:
    pool = ThreadPoolExecutor(128)
    df = C.corpus()
    gp, g_dev, g_test = g2_people()

    # ---------- G2 people: references, cards, packages
    def g2_extract(r):
        text = f"Liked: {r['pros']}\nDisliked: {r['cons']}\nProblems solved: {r.get('problems_solved') or ''}"
        rec = E.call_model("g2_extract", FLASH, "You extract claims from reviews. Return JSON only.",
                           RE.EXTRACT.format(product=r["product"], text=text), temperature=0.0, seed=42, max_tokens=4096,
                           thinking_budget=512)
        j = rec.get("json") if isinstance(rec.get("json"), dict) else {}
        task = j.get("task") if isinstance(j.get("task"), str) and not MT.LEAK.search(j.get("task") or "") else None
        return r["rid"], {"task": task, "benefits": [str(x) for x in (j.get("benefits") or [])][:4],
                          "frictions": [str(x) for x in (j.get("frictions") or [])][:4]}

    g_refs = dict(pool.map(g2_extract, gp))
    g_cards = {r["rid"]: {"product": r["product"], "url": "no URL given", "role_title": E.clean(r["title"]),
                          "role_family": r["role_family"], "industry": r["industry"] or "not stated",
                          "company_size": r["size3"], "time_used": "not recorded", "task": g_refs[r["rid"]]["task"] or "not stated",
                          "previous": "not stated"} for r in gp}
    g_person = {r["rid"]: {"role_family": r["role_family"], "size3": r["size3"], "industry": r["industry"]} for r in gp}
    g_split = {r["rid"]: ("dev" if r["product"] in g_dev else "test") for r in gp}

    # ---------- Capterra test people (identical to router_eval so its cached calls are reused)
    cdf = U.data()
    cp = [r for r in RE.sample(cdf) if r["product_name"] in RE.TEST]
    c_refs = dict(pool.map(lambda r: (r["review_id"], RE_extract(r)), cp))
    c_cards = {r["review_id"]: RE.card(r, c_refs[r["review_id"]]["task"]) for r in cp}
    c_person = {r["review_id"]: {"role_family": c_cards[r["review_id"]]["role_family"], "company_size": r["reviewer_company_size"],
                                 "size_fine": r["reviewer_company_size"], "size3": C.SIZE3.get(r["reviewer_company_size"]),
                                 "time_used": r["reviewer_time_used_product"], "industry": r["reviewer_industry"]} for r in cp}

    # ---------- packages per (person, source)
    def pkg(job):
        who, pid, src = job
        if who == "c":
            r = next(x for x in cp if x["review_id"] == pid)
            prod = r["product_name"]
            if src == "capterra":  # exactly router_eval's package -> cached predictions
                p = U.build_package(RE.URLS[prod], {k: c_person[pid][k] for k in ("role_family", "time_used", "industry")} |
                                    {"company_size": c_person[pid]["company_size"]}, exclude_product=prod, mask=U.mask_for(prod))
                return (who, pid, src), p
            cat = U.classify(RE.URLS[prod])["category"]
            return (who, pid, src), C.sections(c_person[pid], cat, SRC[src], prod, U.mask_for(prod))
        r = next(x for x in gp if x["rid"] == pid)
        return (who, pid, src), C.sections(g_person[pid], r["category"], SRC[src], r["product"], U.mask_for(r["product"]))

    jobs = [("g", r["rid"], "g2") for r in gp] + [("g", r["rid"], s) for r in gp if g_split[r["rid"]] == "test" for s in ("capterra", "both")]
    jobs += [("c", r["review_id"], s) for r in cp for s in ("capterra", "g2", "both")]
    pkgs = dict(pool.map(pkg, jobs))

    def predict(job):
        who, pid, src, mode = job
        card = (c_cards if who == "c" else g_cards)[pid]
        if mode == "agent_alone":
            ev = ""
        else:
            sec = pkgs[(who, pid, src)]["sections"]
            ev = "\nData:\n" + ("\n\n".join(sec.values()) if mode == "agent_full" else sec["averages"])
        key = f"{pid}|{mode}" if (who == "c" and src in ("capterra", None)) else f"{pid}|{src}|{mode}"
        rec = E.call_model("router_predict" if who == "c" else "g2_predict", FLASH, MT.PRED_SYSTEM,
                           RE.PRED.format(**card, evidence=ev), temperature=E.PREDICT_TEMPERATURE, seed=1000,
                           max_tokens=8192, thinking_budget=1024, key_extra=key)
        return (who, pid, src, mode), rec.get("json") if isinstance(rec.get("json"), dict) else {}

    pjobs = [("c", r["review_id"], None, "agent_alone") for r in cp] + [("g", r["rid"], None, "agent_alone") for r in gp]
    pjobs += [(w, pid, s, m) for (w, pid, s) in pkgs for m in ("agent_full", "agent_averages")]
    # router_eval keyed agent_alone with key_extra f"{rid}|agent_alone"
    preds = dict(pool.map(predict, [(w, p, ("capterra" if (w == "c" and m == "agent_alone") else s), m) for w, p, s, m in pjobs]))
    preds = {(w, p, (None if m == "agent_alone" else s), m): v for (w, p, s, m), v in preds.items()}

    def actual_text(who, pid):
        if who == "c":
            return E.review_for_extraction(next(x for x in cp if x["review_id"] == pid))
        r = next(x for x in gp if x["rid"] == pid)
        return str(r.get("review_text") or f"Liked: {r['pros']} Disliked: {r['cons']}")

    def judge(job):
        who, pid, src, mode = job
        j, ref = preds[job], (c_refs if who == "c" else g_refs)[pid]
        lst = lambda x: [str(v) for v in x][:3] if isinstance(x, list) else []  # noqa: E731
        fmt = lambda xs, p: "\n".join(f"{p}{i + 1}: {x}" for i, x in enumerate(xs)) or "(none)"  # noqa: E731
        rec = E.call_model("router_judge" if who == "c" else "g2_judge", FLASH, "You are a strict evaluator. Return JSON only.",
                           RE.JUDGE.format(pp=fmt(lst(j.get("pros")), "P"), ap=fmt(ref["benefits"], "A"),
                                           pc=fmt(lst(j.get("cons")), "P"), ac=fmt(ref["frictions"], "A"),
                                           po=str(j.get("overall_experience") or ""), at=actual_text(who, pid)),
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
                     "overall_experience": (float(ov == 2) if ov in (0, 1, 2) else None)}

    judged = dict(pool.map(judge, list(preds)))

    # ---------- values per strategy
    def value(who, pid, src, out, strategy):
        lo, hi = U.RATINGS.get(out, (1, 5))
        if out in U.RATINGS:
            num = lambda m: RE.U_num(preds[(who, pid, None if m == "agent_alone" else src, m)].get(out), lo, hi)  # noqa: E731
            est = pkgs[(who, pid, src)]["estimates"].get(out) if src else None
            if strategy == "agent_alone":
                return num("agent_alone")
            if strategy == "averages":
                return est if est is not None else num("agent_averages")
            if strategy == "blend":
                f = num("agent_full")
                return (est + f) / 2 if est is not None and f is not None else f
            return num(strategy)
        d = judged[(who, pid, None if strategy == "agent_alone" else src, strategy)]
        return d.get(out)

    strategies = ["agent_alone", "averages", "blend", "agent_full", "agent_averages"]
    text_strats = ["agent_alone", "agent_full", "agent_averages"]

    # G2 router: choose on G2 dev with G2 data
    g_truth = {r["rid"]: r["overall_rating"] for r in gp}
    g_router = {}
    dev_ids = [r["rid"] for r in gp if g_split[r["rid"]] == "dev"]
    for out in G2_OUTPUTS:
        cands = strategies if out in U.RATINGS else text_strats
        sc = {}
        for s in cands:
            vals = [value("g", pid, "g2", out, s) for pid in dev_ids]
            if out in U.RATINGS:
                errs = [abs(v - g_truth[pid]) for v, pid in zip(vals, dev_ids) if v is not None]
                sc[s] = -float(np.mean(errs))
            else:
                v = [x for x in vals if x is not None]
                sc[s] = float(np.mean(v)) if v else -1
        g_router[out] = max(sc, key=sc.get)
    risk_sc = {}
    for s in strategies:
        v = [(value("g", pid, "g2", "overall_rating", s), int(g_truth[pid] <= 3)) for pid in dev_ids]
        v = [(-a, y) for a, y in v if a is not None]
        risk_sc[s] = PP.auc([a for a, _ in v], [y for _, y in v]) or 0
    g_router["unhappy_risk"] = max(risk_sc, key=risk_sc.get)
    c_router = {**E.read_json(U.ROUTER_PATH)["strategy"], "unhappy_risk": E.read_json(U.ROUTER_PATH)["risk"]["unhappy_risk"]}
    E.write_json(GOUT / "g2_router.json", {"strategy": g_router, "chosen_on": g_dev})

    # ---------- test report: each dataset's router, data source varies
    rows = []
    c_truth = {r["review_id"]: r for r in cp}
    for who, ids, router, outs, own, other in (
            ("c", [r["review_id"] for r in cp], c_router, list(U.RATINGS) + ["pros", "cons", "overall_experience"], "capterra", "g2"),
            ("g", [r["rid"] for r in gp if g_split[r["rid"]] == "test"], g_router, G2_OUTPUTS, "g2", "capterra")):
        for out in outs + ["unhappy_risk"]:
            line = {"people": "Capterra" if who == "c" else "G2", "output": out, "strategy": router[out]}
            for label, src, strat in (("agent_alone", None, "agent_alone"), (own, own, router[out]),
                                      (other, other, router[out]), ("both", "both", router[out])):
                if out == "unhappy_risk":
                    sc, ys = [], []
                    for pid in ids:
                        if who == "c":
                            r = c_truth[pid]
                            y = int(r["overall_rating"] <= 3 or (r.get("recommendation_score") is not None and r["recommendation_score"] <= 6))
                            o = value(who, pid, src, "overall_rating", strat)
                            rc = value(who, pid, src, "recommendation_score", strat)
                            if o is None or rc is None:
                                continue
                            sc.append((5 - o) + (10 - rc) / 2)
                        else:
                            y = int(g_truth[pid] <= 3)
                            o = value(who, pid, src, "overall_rating", strat)
                            if o is None:
                                continue
                            sc.append(5 - o)
                        ys.append(y)
                    line[label] = PP.auc(sc, ys)
                elif out in U.RATINGS:
                    errs = []
                    for pid in ids:
                        y = c_truth[pid].get(out) if who == "c" else g_truth[pid]
                        v = value(who, pid, src, out, strat)
                        if y is not None and v is not None:
                            errs.append(abs(v - y))
                    line[label] = float(np.mean(errs)) if errs else None
                else:
                    v = [value(who, pid, src, out, strat) for pid in ids]
                    v = [x for x in v if x is not None]
                    line[label] = float(np.mean(v)) if v else None
            line["n"] = len(ids)
            rows.append(line)
    rep = pd.DataFrame(rows)
    GOUT.mkdir(parents=True, exist_ok=True)
    rep.to_csv(GOUT / "merge_report.csv", index=False)
    E.write_json(GOUT / "products.json", {"g2_dev": g_dev, "g2_test": g_test, "capterra_test": RE.TEST})
    pd.set_option("display.width", 220)
    print("G2 router:", g_router)
    print("G2 dev:", g_dev, "\nG2 test:", g_test)
    print(rep.round(3).to_string(index=False))
    print(f"spend ${E.spent_usd():.3f}")


def RE_extract(r):
    """router_eval's extraction call, verbatim, so it is served from cache."""
    text = E.review_for_extraction(r)
    rec = E.call_model("router_extract", FLASH, "You extract claims from reviews. Return JSON only.",
                       RE.EXTRACT.format(product=r["product_name"], text=text), temperature=0.0, seed=42,
                       max_tokens=4096, thinking_budget=512)
    j = rec.get("json") if isinstance(rec.get("json"), dict) else {}
    task = j.get("task") if isinstance(j.get("task"), str) and not MT.LEAK.search(j.get("task") or "") else None
    return {"task": task, "benefits": [str(x) for x in (j.get("benefits") or [])][:4],
            "frictions": [str(x) for x in (j.get("frictions") or [])][:4]}


if __name__ == "__main__":
    main()
