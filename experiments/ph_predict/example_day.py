import json, glob, numpy as np, pandas as pd
T = pd.read_parquet("results/newsim_preds.parquet")
names = {}
for f in glob.glob("data/days/2026-10-*.json"):
    for p in json.load(open(f)):
        names[str(p["id"])] = p["name"]
sim = "+day standing+page"
for d in ("2026-10-24", "2026-10-21"):
    g = T[T.day == d].copy()
    g["real_votes"] = np.expm1(g.logv).round().astype(int)
    g["sim_votes"] = np.expm1(g[sim]).round().astype(int)
    g["lm_votes"] = np.expm1(g["launch only"]).round().astype(int)
    g["sim_rank"] = g[sim].rank(ascending=False).astype(int)
    g["lm_rank"] = g["launch only"].rank(ascending=False).astype(int)
    print(d, "launches that day:", len(g))
    for r in g.sort_values("dailyRank").head(10).itertuples():
        team = "new team" if r.first_time else "repeat"
        print(f"  real #{int(r.dailyRank):2d} {names.get(r.id, r.id)[:26]:26s} real {r.real_votes:4d} | sim #{r.sim_rank:2d} {r.sim_votes:4d} | launch #{r.lm_rank:2d} {r.lm_votes:4d} | {team}")
cols = ["nsa_team_ties", "nsa_hunter_ties", "nsa_comp_ties", "nsa_ph_makers", "nsa_ph_hunter", "nsa_x_makers"]
for nm, i in (("zCAD AI", "1281583"), ("1Password for Agents", "1289449")):
    s = T[T.id == i]
    if len(s):
        r = s.iloc[0]
        print(nm, {c[4:]: int(round(np.expm1(r[c]))) for c in cols}, "| person-sim expected votes", round(float(r["pst_ev"]), 2),
              "| network x conversion", round(float(np.exp(r["tpd_poisson"])), 1))
