"""Stage B agents' comments vs real launch-day comment themes (forward_says judge, frozen consensus truth). v1 = rerank_b agents
(<D>.parquet); v2pick = each person's one comment attributed to their first pick (<D>_v2pick.parquet). Aggregates only.
    python agents_what.py D SP OUT.json      (run from experiments/simlab)"""
import io, json, os, re, subprocess, sys
import numpy as np, pandas as pd
D, SP, OUT = sys.argv[1:4]
src = open("forward_says.py").read(); src = src[:src.index("def one(lid):")]
G = {"__name__": "fs", "__file__": os.path.abspath("forward_says.py")}; sys.argv = ["forward_says.py", D, SP]; exec(compile(src, "fs", "exec"), G)
rd = lambda p: (lambda r: pd.read_parquet(io.BytesIO(r)) if r else None)(subprocess.run(["gsutil", "cat", f"gs://usersim-bakeoff-347838016394/usersim_sim/tmp/e5/private/agents/{p}"], capture_output=True).stdout)
truth = {}
def score(X):
    rows = []
    for lid, g in X.groupby("launch_id"):
        lid = str(lid); cm = G["NT"][G["NT"].post == lid].sort_values("created").text.tolist()
        if len(cm) < 5: continue
        if lid not in truth: truth[lid] = G["truth_for"](lid, "\n".join(f"- {t[:400]}" for t in cm[:40]))
        th, ct = (truth[lid] or {}).get("themes") or [], (truth[lid] or {}).get("complaints") or []
        seen, c = set(), []
        for t in g.sort_values("p", ascending=False).comment.dropna():
            k = re.sub(r"\W+", " ", t.lower()).strip()[:80]
            if k and k not in seen: seen.add(k); c.append(t)
        if c[:14] and th: rows.append({"launch_id": lid, "n_cand": len(c[:14]), **G["judge"](th, ct, c[:14])})
    return pd.DataFrame(rows)
def summ(R):
    rng = np.random.default_rng(0); out = {"launches": len(R)}
    for m in ("recall", "precision", "complaint_recall"):
        v = R[m].dropna().to_numpy() if m in R else np.array([])
        if len(v): bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]; out[m] = [round(100 * v.mean(), 1), round(100 * np.percentile(bs, 2.5), 1), round(100 * np.percentile(bs, 97.5), 1), len(v)]
    return out
S, rows = {}, {}
V1 = rd(f"{D}.parquet")
if V1 is not None: R = score(V1); S["v1"] = summ(R); rows["v1"] = R.to_dict("records")
V2 = rd(f"{D}_v2pick.parquet")
if V2 is not None:
    V2 = V2.assign(launch_id=[json.loads(p)[0] if json.loads(p or "[]") else None for p in V2.picks], p=1.0).dropna(subset=["launch_id"])
    R = score(V2); S["v2pick (comment attributed to the person's first pick)"] = summ(R); rows["v2"] = R.to_dict("records")
os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
json.dump({"day": D, "judge": "forward_says.judge vs frozen consensus truth", "summary": S, "rows": rows}, open(OUT, "w"), indent=1)
print("AGENTS", json.dumps(S))
