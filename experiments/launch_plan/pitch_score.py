"""Score each pitch variant with the arm-2 llm_pitch prompt (llm.py PROMPT, mode pitch, Gemini 2.5 Flash, temperature 0), listwise inside a real
day's line-up: one call per (sampled day, variant), the day's real products plus ours. 14 days = 2 per weekday of the last 8 weeks.
Output per call: our score, and our percentile among that call's scores for the real products."""
import json, sys, os, re, numpy as np, pandas as pd, concurrent.futures as cf
SP = sys.argv[1]; sys.path.insert(0, f"{SP}/rb/pp"); os.environ.setdefault("H25_DATA", f"{SP}/rb/h25data")
import llm
X = pd.read_parquet(f"{SP}/rb/X_full.parquet"); X["id"] = X.id.astype(str); W = X[X.day >= "2026-09-18"]; C = json.load(open(f"{SP}/selfplan/candidates.json"))
days = sorted(W.day.unique()); wd = pd.to_datetime(pd.Series(days)).dt.weekday.values; pick = [d for w in range(7) for d in [x for x, y in zip(days, wd) if y == w][2:7:4]]
print("days", pick, flush=True)
basis = "the pitch (name, tagline, description, topics)"
def one(a):
    d, cand, vi = a; g = W[W.day == d]; v = C[cand]["variants"][vi]
    items = [f"[{r.id}] {r['name']} — {r.tagline}\n  topics: {', '.join(r.topics)}\n  description: {(r.description or '')[:400]}" for _, r in g.iterrows()]
    ours = f"[usersim] {v['name']} — {v['tagline']}\n  topics: {', '.join(C[cand]['default_topics'])}\n  description: {v['description'][:400]}"
    pos = len(items) // 2; items.insert(pos, ours)
    txt = llm.gemini_call(llm.PROMPT.format(n=len(items), day=d, basis=basis, items="\n".join(items)), 60 * len(items) + 500)
    try: res = json.loads(re.search(r"\{.*\}", txt, re.S).group(0)); s = float(res["usersim"]["score"]); oth = np.array([float(x["score"]) for k, x in res.items() if k != "usersim"])
    except Exception: return None
    return {"day": d, "cand": cand, "variant": vi, "score": s, "pct_in_call": float((oth < s).mean() + 0.5 * (oth == s).mean()), "n": len(oth), "stored_mean": float(g.llm_pitch.mean()), "call_mean_others": float(oth.mean())}
jobs = [(d, c, i) for d in pick for c in C for i in range(3)]
with cf.ThreadPoolExecutor(8) as ex: R = [r for r in ex.map(one, jobs) if r]
T = pd.DataFrame(R); T.to_parquet(f"{SP}/selfplan/pitch_scores.parquet")
print("calls ok", len(T), "of", len(jobs), "usd", round(llm.USAGE["in"] / 1e6 * .3 + llm.USAGE["out"] / 1e6 * 2.5, 3))
print(T.groupby(["cand", "variant"]).agg(score=("score", "mean"), sd=("score", "std"), pct=("pct_in_call", "mean"), pct_sd=("pct_in_call", "std")).round(2).to_string())
print("call vs stored mean for real products:", round(T.call_mean_others.mean(), 1), round(T.stored_mean.mean(), 1))
