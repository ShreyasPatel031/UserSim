import json, numpy as np, pandas as pd
P = pd.read_parquet("results/ctrl_preds.parquet")
F = pd.DataFrame.from_dict(json.load(open("data/ps_features.json")), orient="index"); F.index.name = "id"
P = P.merge(F.reset_index(), on="id", how="left")
rng = np.random.default_rng(0); rows = []
for d, g in P.groupby("day"):
    g = g.to_dict("records")
    for i in range(len(g)):
        for j in range(i + 1, len(g)):
            a, b = g[i], g[j]
            if abs(a["fixed"] - b["fixed"]) < 0.15 and a["logv"] != b["logv"]:
                rows.append((a, b))
print("matched same-day pairs (reach-only predictions within 0.15 log votes):", len(rows))
real = np.array([b["logv"] > a["logv"] for a, b in rows])
def acc(f):
    h = np.array([(f(b) - f(a) > 0) == r for (a, b), r in zip(rows, real) if f(a) == f(a) and f(b) == f(b) and f(a) != f(b)], float)
    bs = [rng.choice(h, len(h)).mean() for _ in range(1000)]
    return f"{100*h.mean():.1f}% [{100*np.percentile(bs,2.5):.1f}, {100*np.percentile(bs,97.5):.1f}] n={len(h)}"
for name, f in [("page model lift", lambda r: r["fixed+page"] - r["fixed"]), ("day model lift", lambda r: r["fixed+day"] - r["fixed"]),
                ("effort model lift", lambda r: r["fixed+effort"] - r["fixed"]), ("all changeable", lambda r: r["all"] - r["fixed"]),
                ("Gemini top-5 chance", lambda r: r.get("ps_top5_chance")), ("Gemini wow", lambda r: r.get("ps_wow")),
                ("Gemini tagline", lambda r: r.get("ps_tagline")), ("Gemini first comment", lambda r: r.get("ps_first_comment"))]:
    print(f"{name:22s} {acc(f)}")
