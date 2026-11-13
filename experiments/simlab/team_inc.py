"""Does the held-team signal add OVER clean? (orchestrator 19:50Z Nov 13). Counts only.
Team = hunter + named (non-redacted) makers of the launch (warehouse). Per launch, as-of-date features:
  held_full   team members complete in the store (any pull time: the selection-exposed version)
  held_pool   team members complete AND in_pool (pool fixed by Nov 3)
  active90    held team members with >= 1 upvote on a launch dated in the 90 days before the launch day
  estab       held team members with prior footing: a team role on another launch >= 30 days earlier OR >= 5 upvotes on launches dated
              >= 30 days before (activity that cannot be caused by this launch; held status itself may still be)
  entry_via   (diagnostic, pre-Nov-3 launches) held pool team members with NO dated store activity before the launch and no earlier
              team role: plausibly entered the store via this launch
(1) Pool days Nov 4, 8, 9, 10, 11, base clean_v3_nosite: base z(clean) + w z(ln(1+feature)), w leave-one-day-out from {0, .25, .5, 1, 2};
    paired top 3/5/10 vs base (day bootstrap); partial Spearman of the feature with the clean residual (clean rank - final rank).
(2) All days Mar 1 - Nov 10, base clean_v3 (honest_preds_v2; clean_nosite is not held before Oct 25): month-forward ridge on within-day z,
    target z(-ln rank), base [clean] vs + each feature; paired top 3/5/10, day bootstrap; days with >= 10 launches.
    python team_inc.py <store dir> <scratchpad> <out dir>
"""
import glob, hashlib, json, os, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge
ST, SP, OUT = sys.argv[1:4]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
SALT = open(f"{SP}/early/salt").read().strip(); pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
L = pd.concat([pd.read_parquet(f) for f in glob.glob(f"{SP}/early/launches/*.parquet")]).sort_values("updated_at").drop_duplicates("id", keep="last")
L["id"] = L.id.astype(str); L = L[L.daily_rank.notna()].copy(); L["rank"] = L.daily_rank.astype(float)
def mk(m):
    try: return [x for x in json.loads(m) if x and not str(x).startswith("[")] if isinstance(m, str) and m.startswith("[") else []
    except Exception: return []
L["team"] = [list(dict.fromkeys(pid(h) for h in (([p] if isinstance(p, str) and p and not p.startswith("[") else []) + mk(m)))) for p, m in zip(L.poster, L.makers)]
P = pd.read_parquet(f"{ST}/persons.parquet"); comp = set(P[P.complete].person_id); pool = set(P[P.complete & P.in_pool].person_id)
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id"]); U = E[(E.kind == "upvote") & E.person_id.isin(comp)].drop_duplicates(["person_id", "target_id"]).copy()
U["target_id"] = U.target_id.astype(str); U["d"] = U.target_id.map(dict(zip(L.id, L.day))); U = U[U.d.notna()]
UD = {p: np.sort(g.d.values) for p, g in U.groupby("person_id")}
roles = {}
for d, t in zip(L.day, L.team):
    for p in t: roles.setdefault(p, []).append(d)
def feats(r):
    D = pd.Timestamp(r.day); d90 = (D - pd.Timedelta(days=90)).strftime("%Y-%m-%d"); d30 = (D - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    held = [p for p in r.team if p in comp]; o = {"held_full": len(held), "held_pool": sum(p in pool for p in held)}
    a = e = v = 0
    for p in held:
        u = UD.get(p, np.array([])); before = u[u < r.day] if len(u) else u
        a += int(((before >= d90)).any()) if len(before) else 0
        early_role = any(x <= d30 for x in roles.get(p, []) if x != r.day)
        e += int(early_role or (len(before) and (before <= d30).sum() >= 5))
        if p in pool: v += int(not len(before) and not any(x < r.day for x in roles.get(p, [])))
    o.update({"active90": a, "estab": e, "entry_via": v}); return o
L = pd.concat([L.reset_index(drop=True), pd.DataFrame([feats(r) for r in L.itertuples()])], axis=1)
FE = ["held_full", "held_pool", "active90", "estab"]; z = lambda s: (s - s.mean()) / (s.std() or 1)
def dm(g, col):
    o = g.sort_values(col, ascending=False).id.tolist(); t = g.sort_values("rank").id.tolist(); return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
def pdiff(a, b):
    df = a - b; bs = np.array([df[rng.integers(0, len(df), len(df))].mean(0) for _ in range(4000)])
    return [[round(float(df[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(3)]
res = {"design": __doc__.split("\n    python")[0]}
pre = L[(L.day < "2026-11-03") & (L.held_pool > 0)]
res["diagnostic: pre-Nov-3 launches with a pool-held team member"] = {"launches": len(pre), "pool-held team members": int(pre.held_pool.sum()),
    "of which plausibly entered via this launch (no earlier dated activity or team role)": int(pre.entry_via.sum()),
    "share": round(float(pre.entry_via.sum() / max(pre.held_pool.sum(), 1)), 3)}
# (1) pool days
CN = pd.read_parquet(f"{SP}/clean_live_rows_nosite.parquet")[["id", "clean_v3_nosite"]]; CN["id"] = CN.id.astype(str)
DAYS5 = ["2026-11-04", "2026-11-08", "2026-11-09", "2026-11-10", "2026-11-11"]
G = L[L.day.isin(DAYS5)].merge(CN, on="id"); G["zc"] = G.groupby("day").clean_v3_nosite.transform(z)
for f in FE: G["z_" + f] = G.groupby("day")[f].transform(lambda s: z(np.log1p(s)))
G["resid"] = G.groupby("day").clean_v3_nosite.rank(ascending=False) - G["rank"]
o1 = {"launches": len(G), "days": DAYS5}
B0 = np.array([dm(G[G.day == d], "zc") for d in DAYS5]); o1["clean_nosite top3/5/10"] = B0.mean(0).round(1).tolist()
for f in FE:
    per = []
    for d in DAYS5:
        tr = [x for x in DAYS5 if x != d]
        w = max((0, .25, .5, 1, 2), key=lambda w: np.mean([dm(G[G.day == x].assign(s=G[G.day == x].zc + w * G[G.day == x]["z_" + f]), "s")[0] for x in tr]))
        g = G[G.day == d]; per.append(dm(g.assign(s=g.zc + w * g["z_" + f]), "s"))
    A = np.array(per); ds = G.day.unique()
    sp = lambda X: spearmanr(X[f], X.resid).correlation
    bs = [sp(pd.concat([G[G.day == x] for x in rng.choice(ds, len(ds))])) for _ in range(1000)]
    o1[f"+ {f}"] = {"top3/5/10": A.mean(0).round(1).tolist(), "vs clean": pdiff(A, B0), "Spearman(feature, clean residual) [CI]": [round(float(sp(G)), 3), round(float(np.nanpercentile(bs, 2.5)), 3), round(float(np.nanpercentile(bs, 97.5)), 3)],
                     "launches with feature > 0": int((G[f] > 0).sum())}
res["(1) pool days, base clean_nosite"] = o1
# (2) all days, month-forward, base clean_v3 (honest_preds_v2)
H = pd.read_parquet(f"{SP}/honest_preds_v2.parquet")[["id", "honest"]]; H["id"] = H.id.astype(str)
M = L.merge(H, on="id"); M = M[M.groupby("day").id.transform("count") >= 10].copy(); M["mon"] = M.day.str[:7]
M["y"] = M.groupby("day")["rank"].transform(lambda r: z(-np.log(r))); M["z_honest"] = M.groupby("day").honest.transform(z)
for f in FE: M["z_" + f] = M.groupby("day")[f].transform(lambda s: z(np.log1p(s)))
ARMS = {"clean": ["z_honest"], **{f"clean + {f}": ["z_honest", "z_" + f] for f in FE}}; mons = sorted(M.mon.unique())
for a, X in ARMS.items():
    M[a] = np.nan
    for m in mons[1:]:
        tr, te = M[M.mon < m], M[M.mon == m]; M.loc[te.index, a] = Ridge(alpha=10).fit(tr[X], tr.y).predict(te[X])
T = M[M["clean"].notna()]; days = sorted(T.day.unique()); C0 = np.array([dm(T[T.day == d], "clean") for d in days])
o2 = {"days": len(days), "launches": len(T), "clean top3/5/10": C0.mean(0).round(1).tolist(), "launches with feature > 0": {f: int((T[f] > 0).sum()) for f in FE}}
for a in list(ARMS)[1:]:
    A = np.array([dm(T[T.day == d], a) for d in days]); o2[a] = {"top3/5/10": A.mean(0).round(1).tolist(), "vs clean": pdiff(A, C0)}
res["(2) all days Mar-Nov 10, month-forward, base clean_v3 (honest_preds_v2)"] = o2
json.dump(res, open(os.path.join(OUT, "team_inc.json"), "w"), indent=1, default=float); print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=float))
