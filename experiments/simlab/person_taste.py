"""Product-specific person signals vs the CF p, same Nov 8-12 frame as person_specific.py. Within-person AUC (which launch does this person pick?)
for: CF p; topic lift (person's topic shares in the 180 days before D vs population, averaged over the launch's topics); team tie (person upvoted an
earlier launch by this launch's poster/maker); combined = p x topic_lift x (1 + 4 x tie). Plus per-launch recall@N and distinct people in top-15s."""
import os, sys, json, numpy as np, pandas as pd
sys.path.insert(0, "/home/user/UserSim/experiments/simlab"); sys.path.insert(0, "/home/user/UserSim/experiments")
import period_parts as PP
from pipeline import warehouse
from sklearn.metrics import roc_auc_score
ST, SP = sys.argv[1:3]; DAYS = sys.argv[3:]; rng = np.random.default_rng(0)
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id", "fetched_at"]); U = E[E.kind == "upvote"].copy(); del E
U["target_id"] = U.target_id.astype(str); U["ft"] = pd.to_datetime(U.fetched_at, utc=True)
held = set(pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id"]).person_id)
lr = U.groupby("person_id").ft.max(); fr = U.groupby("person_id").ft.min()
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str); W["day"] = W.day.astype(str).str[:10]
J = lambda t: json.loads(t) if isinstance(t, str) and t.startswith("[") else []
W["tops"] = W.topics.map(J); W["team"] = [{str(x).lower() for x in J(m) if x} | ({str(p).lower()} if isinstance(p, str) and p else set()) for m, p in zip(W.makers, W.poster)]
lday = dict(zip(W.id, W.day)); ltops = dict(zip(W.id, W.tops)); lteam = dict(zip(W.id, W.team)); U["lday"] = U.target_id.map(lday); U = U[U.lday.notna()]
by_member = {}
for i, d, t in zip(W.id, W.day, W.team):
    for u in t: by_member.setdefault(u, []).append((d, i))
voters = U.groupby("target_id").person_id.agg(set).to_dict()
rows, aucs = [], []
for D in DAYS:
    F = pd.read_parquet(f"{SP}/bp/backer_arms_{D}.parquet"); F = F[F.arm == "CF-only"][["launch_id", "person_id", "p"]]; F["launch_id"] = F.launch_id.astype(str)
    close = PP.close_utc(D); ok = (set(lr[lr > close].index) & set(fr[fr < close - pd.Timedelta(days=1)].index) & held)
    obs = U[(U.lday == D) & U.person_id.isin(ok)].groupby("target_id").person_id.agg(set).to_dict()
    F = F[F.person_id.isin(ok)].copy(); F["y"] = [p_ in obs.get(l, ()) for l, p_ in zip(F.launch_id, F.person_id)]
    d180 = (pd.Timestamp(D) - pd.Timedelta(days=180)).strftime("%Y-%m-%d"); H = U[(U.lday < D) & (U.lday >= d180)]
    T = H.drop_duplicates(["person_id", "target_id"]).assign(t=H.target_id.map(ltops)).explode("t").dropna(subset=["t"]).reset_index(drop=True); pop = T.t.value_counts(normalize=True)
    ct = pd.crosstab(T.person_id, T.t); sh = (ct + 5 * pop.reindex(ct.columns).values).div(ct.sum(1) + 5, axis=0); LIFT = sh / pop.reindex(ct.columns).values
    def tl(pid, lid):
        tp = [t for t in ltops.get(lid, []) if t in LIFT.columns]
        return float(LIFT.loc[pid, tp].mean()) if tp and pid in LIFT.index else 1.0
    F["topic_lift"] = [tl(p_, l) for p_, l in zip(F.person_id, F.launch_id)]
    tie = {}
    for lid in F.launch_id.unique():
        earlier = {i for u in lteam.get(lid, ()) for (d, i) in by_member.get(u, []) if d < D and i != lid}
        tie[lid] = set().union(*[voters.get(i, set()) for i in earlier]) if earlier else set()
    F["tie"] = [p_ in tie[l] for p_, l in zip(F.person_id, F.launch_id)]
    F["combined"] = F.p * F.topic_lift * (1 + 4 * F.tie)
    for pid, g in F.groupby("person_id"):
        if g.y.any() and not g.y.all() and len(g) >= 3:
            aucs.append({"day": D, **{a: roc_auc_score(g.y, g[a]) for a in ("p", "topic_lift", "tie", "combined")}})
    for lid, g in F.groupby("launch_id"):
        o = obs.get(lid, set()) & set(g.person_id); n = len(o)
        if not n: continue
        r = {"day": D, "N": n}
        for a in ("p", "combined"):
            s = g.sort_values(a, ascending=False).person_id.tolist(); r[a] = len(set(s[:n]) & o); r[a + "_top15"] = s[:15]
        rows.append(r)
    print(D, len(F), "ties", int(F.tie.sum()), flush=True)
A = pd.DataFrame(aucs); P = pd.DataFrame(rows)
def boot(f, df):
    d = df.day.unique(); g = {x: df[df.day == x] for x in d}; v = [f(pd.concat([g[x] for x in rng.choice(d, len(d))])) for _ in range(2000)]
    return [round(float(f(df)), 3), round(float(np.percentile(v, 2.5)), 3), round(float(np.percentile(v, 97.5)), 3)]
out = {"people": len(A), "launches": len(P), "within_person_auc (0.5 = no launch preference)": {a: boot(lambda x, a=a: x[a].mean(), A) for a in ("p", "topic_lift", "tie", "combined")},
       "combined minus p, within-person auc (paired)": boot(lambda x: (x.combined - x.p).mean(), A)}
for a in ("p", "combined"):
    out[a] = {"recall@N %": boot(lambda x, a=a: 100 * x[a].sum() / x.N.sum(), P),
              "distinct people across top-15 lists %": round(float(np.mean([len(set().union(*map(set, g[a + "_top15"]))) / (15 * len(g)) for _, g in P.groupby("day")])) * 100, 1)}
out["combined minus p recall@N (paired)"] = boot(lambda x: 100 * (x.combined.sum() - x.p.sum()) / x.N.sum(), P)
print(json.dumps(out, indent=1)); json.dump(out, open(f"{SP}/person_taste.json", "w"), indent=1)
