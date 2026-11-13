"""Over-covered launches: store-only new-account proxy + voters pilot list for the createdAt pull (orchestrator 12:00Z Nov 13).
Over-covered = store upvoters > displayed votes (same definition and window as vote_weight.py: Oct 1 - Nov 10, official store_v3).
Proxy (COMPLETE upvoters only, full upvote tab): share whose FIRST upvote is on that launch's day. Upvote day = warehouse launch day
(2026 launches), else the bounded ts_lo, else "before 2026" (older than any 2026 day). Also share whose first upvote is within 7 days
before the launch day, and share with <=3 upvotes in total. Matched set: not-over-covered launches, same month and rank band, votes
within +/-30%. Diff = over minus mean of its matched pool; 95% CI by bootstrap over over-covered launches.
Pilot: 10 over-covered top-3 + 10 matched top-3 (nearest votes, same month); store upvoters written to a BUCKET file by handle
(handle map built in scratch from held handle lists; never committed). Output here: counts only.
    python vote_newacct.py <store dir> <pid_map.parquet> <out dir> <bucket list path>
"""
import json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
ST, MAP, OUT, GS = sys.argv[1:5]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")); from pipeline import warehouse  # noqa: E402
WL = warehouse.table("launches", do_sync=False); WL["id"] = WL.id.astype(str); WL = WL.sort_values("updated_at").drop_duplicates("id", keep="last")
lday = dict(zip(WL.id, WL.day))
W = WL[WL.daily_rank.notna() & (WL.day >= "2026-10-01") & (WL.day <= "2026-11-10")].copy(); W["votes"] = pd.to_numeric(W.votes, errors="coerce").astype(float); W["rank"] = W.daily_rank.astype(float)
P = pd.read_parquet(os.path.join(ST, "persons.parquet")); C = set(P[P.complete].person_id)
E = pd.read_parquet(os.path.join(ST, "events.parquet"), columns=["person_id", "kind", "target_id", "ts_lo", "ts_quality"])
U = E[E.kind == "upvote"].copy(); U["target_id"] = U.target_id.astype(str); U = U.sort_values("ts_quality").drop_duplicates(["person_id", "target_id"])
U["d"] = U.target_id.map(lday); m = U.d.isna() & (U.ts_quality == "bounded"); U.loc[m, "d"] = U.loc[m, "ts_lo"].dt.tz_convert("America/Los_Angeles").dt.strftime("%Y-%m-%d")
U["d"] = U.d.fillna("0000-00-00")
Uc = U[U.person_id.isin(C)]; first = Uc.groupby("person_id").d.min(); ntot = Uc.groupby("person_id").size()
L = U[U.target_id.isin(set(W.id))]; su = L.groupby("target_id").size(); W = W.set_index("id"); W["store_up"] = su.reindex(W.index).fillna(0); W = W[W.store_up > 0]
W["over"] = W.store_up > W.votes; W["mon"] = W.day.str[:7]; W["rb"] = pd.cut(W["rank"], [0, 3, 10, 1000], labels=["1-3", "4-10", "11+"]).astype(str)
Lc = L[L.person_id.isin(C)].copy(); Lc["lday"] = Lc.target_id.map(lday); Lc["f"] = Lc.person_id.map(first)
Lc["first_same"] = Lc.f == Lc.lday; Lc["first_7"] = (Lc.f <= Lc.lday) & (Lc.f >= (pd.to_datetime(Lc.lday) - pd.Timedelta(days=7)).dt.strftime("%Y-%m-%d")); Lc["low3"] = Lc.person_id.map(ntot) <= 3
S = Lc.groupby("target_id")[["first_same", "first_7", "low3"]].mean(); S["n_c"] = Lc.groupby("target_id").size(); W = W.join(S)
W = W[W.n_c >= 5]
ov = W[W.over]; nov = W[~W.over]; pairs = []
for i, r in ov.iterrows():
    pool = nov[(nov.mon == r.mon) & (nov.rb == r.rb) & (nov.votes.between(0.7 * r.votes, 1.3 * r.votes))]
    if len(pool): pairs.append((i, pool.index.tolist()))
res = {"n launches with >=5 complete upvoters": len(W), "over-covered (>=5 complete upvoters)": len(ov), "over-covered with a matched pool": len(pairs)}
for k in ("first_same", "first_7", "low3"):
    a = np.array([W.at[i, k] for i, _ in pairs]); b = np.array([W.loc[p, k].mean() for _, p in pairs]); d = a - b
    bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)]
    res[k] = {"over mean": round(float(a.mean()), 4), "matched mean": round(float(b.mean()), 4), "diff": round(float(d.mean()), 4),
              "95% CI": [round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4)]}
    for rb in ("1-3", "4-10", "11+"):
        ix = [j for j, (i, _) in enumerate(pairs) if W.at[i, "rb"] == rb]
        if len(ix) >= 3:
            dd = d[ix]; bb = [dd[rng.integers(0, len(dd), len(dd))].mean() for _ in range(2000)]
            res[k][f"rank {rb} (n={len(ix)})"] = [round(float(dd.mean()), 4), round(float(np.percentile(bb, 2.5)), 4), round(float(np.percentile(bb, 97.5)), 4)]
# pilot list
t3o = ov[ov.rb == "1-3"].sort_values("store_up", ascending=False).head(10); t3n = nov[nov.rb == "1-3"]; ctl = []
for i, r in t3o.iterrows():
    c = t3n[(t3n.mon == r.mon) & ~t3n.index.isin(ctl)]; c = c if len(c) else t3n[~t3n.index.isin(ctl)]
    ctl.append((c.votes - r.votes).abs().idxmin())
M = pd.read_parquet(MAP).set_index("person_id").h; rows = []
for grp, ids in (("over", list(t3o.index)), ("control", ctl)):
    for lid in ids:
        for p in L[L.target_id == lid].person_id.unique(): rows.append((grp, lid, p, M.get(p)))
R = pd.DataFrame(rows, columns=["group", "launch_id", "person_id", "handle"])
with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
    fh.write("# voters pilot: group\tlaunch_id\tperson_id\thandle(empty=unmapped). Store upvoters of 10 over-covered top-3 + 10 matched top-3 (Oct 1-Nov 10). Bucket only.\n")
    R.fillna("").to_csv(fh, sep="\t", index=False, header=False); tmp = fh.name
subprocess.run(["gsutil", "-q", "cp", tmp, GS], check=True); os.unlink(tmp)
res["pilot"] = {"launches over / control": [len(t3o), len(ctl)], "voter rows": len(R), "unique persons": int(R.person_id.nunique()),
                "unique with handle": int(R.dropna(subset=["handle"]).person_id.nunique()),
                "by group rows / with handle": {g: [len(x), int(x.handle.notna().sum())] for g, x in R.groupby("group")},
                "over votes vs control votes (median)": [float(t3o.votes.median()), float(W.loc[ctl].votes.median())]}
json.dump(res, open(os.path.join(OUT, "result.json"), "w"), indent=1); print(json.dumps(res, indent=1))
