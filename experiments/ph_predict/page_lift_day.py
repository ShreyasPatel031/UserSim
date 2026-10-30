"""For example days: how much the launch page moved each launch's simulated votes (simulation with page minus the same
simulation without the page inputs), plus Gemini's element scores and the page facts with a measured effect."""
import json, glob, numpy as np, pandas as pd
T = pd.read_parquet("results/newsim_preds.parquet")
ps = json.load(open("data/ps_features.json")); pf = json.load(open("data/pf_features.json"))
names = {}
for f in glob.glob("data/days/2026-10-*.json"):
    for p in json.load(open(f)):
        names[str(p["id"])] = p["name"]
EL = ["name", "tagline", "description", "first_comment", "website", "video", "gallery", "logo"]
FX = {"free_plan": "+", "open_source": "+", "mac_app": "+", "mentions_competitor": "+", "no_signup_needed": "+", "b2b_product": "-", "price_point_not_stated": "-"}
for d in ("2026-10-24", "2026-10-21"):
    g = T[T.day == d].copy()
    g["with_page"] = np.expm1(g["+day standing+page"]); g["no_page"] = np.expm1(g["+day standing"]); g["lift"] = g.with_page - g.no_page
    g["r_with"] = g["+day standing+page"].rank(ascending=False).astype(int); g["r_no"] = g["+day standing"].rank(ascending=False).astype(int)
    print(d)
    for r in g.sort_values("dailyRank").head(8).itertuples():
        s = ps.get(r.id, {}); f = pf.get(r.id, {})
        el = " ".join(f"{e[:4]}{int(s.get('ps_' + e, 0))}" for e in EL)
        facts = ",".join(("+" if v == "+" else "-") + k for k, v in FX.items() if f.get("pf_" + k))
        print(f"  real #{int(r.dailyRank):2d} {names.get(r.id, r.id)[:22]:22s} page lift {r.lift:+5.0f} votes (rank {r.r_no:2d} -> {r.r_with:2d}) | {el} | {facts}")
