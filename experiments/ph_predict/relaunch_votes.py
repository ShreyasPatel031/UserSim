import pickle, numpy as np, pandas as pd
df = pickle.load(open("data/build_cache.pkl", "rb"))
P = pd.read_parquet("results/ctrl_preds.parquet")
df = df[["id", "domain"]].merge(P, on="id")
SKIP = {"", "github.com", "apps.apple.com", "chromewebstore.google.com", "chrome.google.com", "play.google.com", "producthunt.com", "x.com", "notion.site", "vercel.app"}
df["prod"] = df.domain.fillna("").str.lower().str.replace(r"^www\.", "", regex=True); df = df[~df["prod"].isin(SKIP)]
pairs = [(a, b) for _, g in df.sort_values("day").groupby("prod") for a, b in zip(g.to_dict("records"), g.to_dict("records")[1:]) if a["day"] != b["day"]]
real = np.array([b["logv"] > a["logv"] for a, b in pairs])
rng = np.random.default_rng(0)
def acc(f):
    h = np.array([(f(b) - f(a) > 0) == r for (a, b), r in zip(pairs, real)], float)
    bs = [rng.choice(h, len(h)).mean() for _ in range(2000)]
    return f"{100*h.mean():.1f}% [{100*np.percentile(bs,2.5):.1f}, {100*np.percentile(bs,97.5):.1f}]"
print("pairs", len(pairs), "later got more votes:", f"{100*real.mean():.1f}%")
for name, f in [("fixed (reach only)", lambda r: r["fixed"]), ("full model", lambda r: r["all"]),
                ("fixed + page", lambda r: r["fixed+page"]), ("fixed + day", lambda r: r["fixed+day"]), ("fixed + effort", lambda r: r["fixed+effort"])]:
    print(f"{name:20s} {acc(f)}")
# does the page model add over reach when the two disagree on direction?
