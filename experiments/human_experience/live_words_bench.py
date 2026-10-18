"""Words (pros, cons, overall experience) on the live held-out set (G2 / Capterra / TrustRadius / Gartner), through the
SHIPPED agent-mode prompt and evidence builder. Same extractor and judge as router_eval.

People: up to PER_PRODUCT reviewers with pros and cons per live target product (live_bench.py's 14), spread over sites.
  rivals_only  agent mode as for a brand-new product: the named rivals' live reviews only
  agent_mode   agent mode as shipped: + the product's own reviews dated before this person (all sites, most recent 100)

    EXP_SPEND_CAP_USD=80 python live_words_bench.py [--data DIR]
"""

from __future__ import annotations

import argparse
import json
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

import experiment as E  # noqa: E402
import router_eval as RE  # noqa: E402
from live_bench import live_shape  # noqa: E402

from mvp import agent_mode as A  # noqa: E402

OUT = HERE / "results/live_words_bench"
PER_PRODUCT = 12
CONDS = ["rivals_only", "agent_mode"]
FLASH = RE.FLASH


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="/home/user/live")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    d = pd.read_csv(Path(a.data) / "live_reviews.csv.gz")
    comps = json.loads((Path(a.data) / "competitors.json").read_text())
    d["date"] = pd.to_datetime(d.date, errors="coerce")
    people = []
    for target, rivals in comps.items():
        own = d[d["query"] == target]
        if len(own) < 20 or not d["query"].isin(rivals).any():
            continue
        cand = own[own.pros.notna() & own.cons.notna() & own.date.notna() & own.overall_rating.notna()]
        cand = cand.assign(_h=cand.rid.map(lambda i: E.sha(f"42|live|{i}"))).sort_values("_h")
        # round-robin over sites so TrustRadius / Gartner are represented
        picks, groups = [], [g for _, g in cand.groupby("site")]
        while len(picks) < PER_PRODUCT and any(len(g) for g in groups):
            for i, g in enumerate(groups):
                if len(g) and len(picks) < PER_PRODUCT:
                    picks.append(g.iloc[0].to_dict())
                    groups[i] = g.iloc[1:]
        people += [{**p, "rivals": rivals} for p in picks]
    pool = ThreadPoolExecutor(64)

    def extract(p):
        text = f"Liked: {p['pros']}\nDisliked: {p['cons']}\n{p.get('review_text') or ''}"
        rec = E.call_model("live_extract", FLASH, "You extract claims from reviews. Return JSON only.",
                           RE.EXTRACT.format(product=p["query"], text=text[:6000]), temperature=0.0, seed=42, max_tokens=4096,
                           thinking_budget=512)
        j = rec.get("json") if isinstance(rec.get("json"), dict) else {}
        return p["rid"], {"task": j.get("task") if isinstance(j.get("task"), str) else None,
                          "benefits": [str(x) for x in (j.get("benefits") or [])][:4],
                          "frictions": [str(x) for x in (j.get("frictions") or [])][:4], "text": text[:6000]}

    refs = dict(pool.map(extract, people))

    def run(job):
        p, cond = job
        rv = [live_shape(x) for x in d[d["query"].isin(p["rivals"])].to_dict("records")]
        own = d[(d["query"] == p["query"]) & (d.date < p["date"]) & (d.rid != p["rid"])].sort_values("date", ascending=False)
        own = [live_shape(x) for x in own.head(A.LAST).to_dict("records")] if cond == "agent_mode" else []
        g = lambda k: p[k] if isinstance(p.get(k), str) else None  # noqa: E731
        per = {"role": g("title") or "", "company_size": g("size3"), "industry": g("industry"), "time_used": g("time_used")}
        rat = A.rating_estimates(own, rv)
        A.personalize(rat, per)
        prompt = A.words_prompt(p["query"], "", per, refs[p["rid"]]["task"], A.evidence_text(p["query"], own, rv, per, rat)[:14000])
        rec = E.call_model("live_words_v2", FLASH, A.WORDS_SYSTEM, prompt, temperature=0.7, seed=1000, max_tokens=8192,
                           thinking_budget=A.WORDS_THINKING, key_extra=f"{p['rid']}|{cond}")
        j = rec.get("json") if isinstance(rec.get("json"), dict) else {}
        j["_shown"] = rat["overall_rating"].get("for_this_persona")
        return (p["rid"], cond), j

    preds = dict(pool.map(run, [(p, c) for p in people for c in CONDS]))

    def judge(key):
        w, ref = preds[key], refs[key[0]]
        lst = lambda x: [str(v) for v in x][:3] if isinstance(x, list) else []  # noqa: E731
        fmt = lambda xs, q: "\n".join(f"{q}{i + 1}: {x}" for i, x in enumerate(xs)) or "(none)"  # noqa: E731
        rec = E.call_model("live_judge", FLASH, "You are a strict evaluator. Return JSON only.",
                           RE.JUDGE.format(pp=fmt(lst(w.get("pros")), "P"), ap=fmt(ref["benefits"], "A"), pc=fmt(lst(w.get("cons")), "P"),
                                           ac=fmt(ref["frictions"], "A"), po=str(w.get("overall_experience") or ""), at=ref["text"]),
                           temperature=0.0, seed=42, max_tokens=4096, thinking_budget=512)
        g = rec.get("json") if isinstance(rec.get("json"), dict) else {}

        def recall(k, n):
            best = {}
            for m in g.get(k) or []:
                if isinstance(m, dict) and m.get("score") in (1, 2):
                    best[m.get("act")] = max(best.get(m.get("act"), 0), m["score"])
            return (sum(v == 2 for v in best.values()) / n) if n else None
        ov = g.get("overall")
        return key, {"pros": recall("pros", len(ref["benefits"])), "cons": recall("cons", len(ref["frictions"])),
                     "overall_experience": float(ov == 2) if ov in (0, 1, 2) else None}

    judged = dict(pool.map(judge, list(preds)))
    site = {p["rid"]: p["site"] for p in people}
    prod = {p["rid"]: p["query"] for p in people}
    y = {p["rid"]: p["overall_rating"] for p in people}
    M = pd.DataFrame([{"rid": k[0], "cond": k[1], "site": site[k[0]], "product": prod[k[0]], **v, "y": y[k[0]],
                       "shown": preds[k].get("_shown"), "model": RE.U_num(preds[k].get("overall_rating"), 1, 5)}
                      for k, v in judged.items()])
    M.to_csv(OUT / "per_person.csv", index=False)
    cols = ["pros", "cons", "overall_experience"]
    print(M.groupby("cond")[cols].mean().loc[CONDS].round(3).to_string())
    print("\nby site:\n", M.groupby(["site", "cond"])[cols].mean().round(3).unstack("cond").to_string())
    for c in cols:
        P = M.pivot_table(index=["rid", "product"], columns="cond", values=c).dropna()
        dd = (P.agent_mode - P.rivals_only).groupby(level="product").agg(["sum", "count"])
        rng = np.random.default_rng(0)
        bs = [(s := dd.iloc[rng.integers(0, len(dd), len(dd))])["sum"].sum() / s["count"].sum() for _ in range(2000)]
        print(f"{c}: agent_mode - rivals_only = {dd['sum'].sum() / dd['count'].sum():+.3f} "
              f"[{np.percentile(bs, 2.5):+.3f}, {np.percentile(bs, 97.5):+.3f}] n={int(dd['count'].sum())}")
    print(f"spend so far ${E.spent_usd():.2f}")


if __name__ == "__main__":
    main()
