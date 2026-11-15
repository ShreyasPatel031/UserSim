"""Is the CF vote model person-specific? Nov 8-12 frozen CF lists, strict observed voters (as cf_launch_calib.py).
(a) within-person AUC: for people who voted on >=1 listed launch that day, does their p rank the launch they voted on above the ones they skipped?
(b) per-launch lists: rank by p (raw), by lift = p / person's mean p that day, by blend p x lift^0.5; recall@N, recall@15, distinct people in top-15s."""
import os, sys, json, numpy as np, pandas as pd
sys.path.insert(0, "/home/user/UserSim/experiments/simlab"); sys.path.insert(0, "/home/user/UserSim/experiments")
import period_parts as PP
from pipeline import warehouse
from sklearn.metrics import roc_auc_score
ST, SP = sys.argv[1:3]; DAYS = sys.argv[3:]; rng = np.random.default_rng(0)
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id", "fetched_at"]); U = E[E.kind == "upvote"].copy()
U["target_id"] = U.target_id.astype(str); U["ft"] = pd.to_datetime(U.fetched_at, utc=True)
held = set(pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id"]).person_id)
lr = U.groupby("person_id").ft.max(); fr = U.groupby("person_id").ft.min()
W = warehouse.table("launches", do_sync=False).drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str); U["lday"] = U.target_id.map(dict(zip(W.id, W.day.astype(str).str[:10])))
rows, aucs = [], []
for D in DAYS:
    F = pd.read_parquet(f"{SP}/bp/backer_arms_{D}.parquet"); F = F[F.arm == "CF-only"][["launch_id", "person_id", "p"]]; F["launch_id"] = F.launch_id.astype(str)
    close = PP.close_utc(D); ok = (set(lr[lr > close].index) & set(fr[fr < close - pd.Timedelta(days=1)].index) & held)
    obs = U[(U.lday == D) & U.person_id.isin(ok)].groupby("target_id").person_id.agg(set).to_dict()
    F = F[F.person_id.isin(ok)].copy(); F["y"] = [p_ in obs.get(l, ()) for l, p_ in zip(F.launch_id, F.person_id)]
    m = F.groupby("person_id").p.transform("mean"); F["lift"] = F.p / m; F["blend"] = F.p * np.sqrt(F.lift)
    for pid, g in F.groupby("person_id"):
        if g.y.any() and not g.y.all() and len(g) >= 3: aucs.append({"day": D, "auc": roc_auc_score(g.y, g.p), "n": len(g)})
    for lid, g in F.groupby("launch_id"):
        o = obs.get(lid, set()) & set(g.person_id); n = len(o)
        if not n: continue
        r = {"day": D, "launch": lid, "N": n}
        for a in ("p", "lift", "blend"):
            s = g.sort_values(a, ascending=False).person_id.tolist(); r[a] = len(set(s[:n]) & o); r[a + "@15"] = len(set(s[:15]) & o); r[a + "_top15"] = s[:15]
        rows.append(r)
A = pd.DataFrame(aucs); P = pd.DataFrame(rows)
def boot(f, df):
    d = df.day.unique(); g = {x: df[df.day == x] for x in d}; v = [f(pd.concat([g[x] for x in rng.choice(d, len(d))])) for _ in range(2000)]
    return [round(float(f(df)), 3), round(float(np.percentile(v, 2.5)), 3), round(float(np.percentile(v, 97.5)), 3)]
out = {"days": DAYS, "within_person_auc (0.5 = no launch preference)": boot(lambda x: x.auc.mean(), A), "people": len(A), "launches": len(P)}
for a in ("p", "lift", "blend"):
    out[a] = {"recall@N %": boot(lambda x: 100 * x[a].sum() / x.N.sum(), P), "hits in top 15 per launch": boot(lambda x: x[a + "@15"].mean(), P),
              "distinct people across top-15 lists (per day, mean)": round(float(np.mean([len(set().union(*map(set, g[a + "_top15"]))) / (15 * len(g)) for _, g in P.groupby("day")])) * 100, 1)}
for a in ("lift", "blend"):
    out[f"{a} minus p recall@N (paired)"] = boot(lambda x: 100 * (x[a].sum() - x.p.sum()) / x.N.sum(), P)
print(json.dumps(out, indent=1)); json.dump(out, open(f"{SP}/person_specific.json", "w"), indent=1)
