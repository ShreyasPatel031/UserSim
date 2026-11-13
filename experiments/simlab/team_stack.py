"""Team engagement on top of the stack base (orchestrator 10:38Z Nov 13). Base = clean 00:05 (honest_preds_v2) + th_n_pre (distinct
non-hunter commenters by 00:05 PT, launch thread dumps, as early_stack.py), month-forward ridge (alpha 10) on within-day z, target z of
-log(rank). Added block: team (hunter + named makers, complete in the merged store) upvotes given 7 d / 30 d, distinct makers supported
30 d (log1p) + coverage flag; variant LAG2 = only launches dated >= 2 days before. Days = those with thread data and >= 10 launches.
Paired day bootstrap top 3 / 5 / 10, overall and on days with >= 40% covered launches. Counts only.
    python team_stack.py <scratchpad> <merged store> <out dir>
"""
import glob, gzip, hashlib, json, os, sys
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge
SP, ST, OUT = sys.argv[1:4]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0); PT = "America/Los_Angeles"
SALT = open(f"{SP}/early/salt").read().strip(); pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
L = pd.concat([pd.read_parquet(f) for f in glob.glob(f"{SP}/early/launches/*.parquet")]).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str); L = L[L.daily_rank.notna()].reset_index(drop=True)
def mk(m):
    try: return [pid(x) for x in json.loads(m) if x and not str(x).startswith("[")] if isinstance(m, str) and m.startswith("[") else []
    except Exception: return []
L["h"] = [pid(p) if isinstance(p, str) and p and not p.startswith("[") else None for p in L.poster]; L["m"] = [mk(m) for m in L.makers]
bys = {s: i for i, s in enumerate(L.slug)}; npre = {}
for f in sorted(glob.glob(f"{SP}/cf/page*.jsonl.gz")):
    for line in gzip.open(f):
        x = json.loads(line)
        try: p_ = json.loads(x["html"])["data"]["post"]
        except Exception: continue
        if not p_ or p_.get("slug") not in bys: continue
        i = bys[p_["slug"]]; t5 = pd.Timestamp(L.day.iat[i]).tz_localize(PT, ambiguous=True).tz_convert("UTC") + pd.Timedelta(minutes=5); us = set()
        def walk(n):
            u = ((n.get("user") or {}).get("username") or "").lower(); t = n.get("createdAt")
            if u and t and pd.Timestamp(t) <= t5 and pid(u) != L.h.iat[i]: us.add(pid(u))
            for e in ((n.get("replies") or {}).get("edges") or []): walk(e["node"])
        for e in ((p_.get("threads") or {}).get("edges") or []): walk(e["node"])
        npre[i] = max(npre.get(i, 0), len(us))
L["th_n_pre"] = [npre.get(i, np.nan) for i in range(len(L))]
P = pd.read_parquet(f"{ST}/persons.parquet"); C = set(P[P.complete].person_id); lday = dict(zip(L.id, pd.to_datetime(L.day))); fmaker = {i: (m[0] if m else None) for i, m in zip(L.id, L.m)}
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id"]); U = E[(E.kind == "upvote") & E.person_id.isin(C)].drop_duplicates(["person_id", "target_id"]).copy(); U["target_id"] = U.target_id.astype(str)
U["d"] = U.target_id.map(lday); U = U[U.d.notna()]; G = {p: g[["d", "target_id"]] for p, g in U.groupby("person_id")}
H = pd.read_parquet(f"{SP}/honest_preds_v2.parquet")[["id", "honest"]]; H["id"] = H.id.astype(str); B = L.merge(H, on="id"); B["rank"] = B.daily_rank.astype(float); feats = []
for r in B.itertuples():
    D = pd.Timestamp(r.day); mem = [m for m in dict.fromkeys(([r.h] if r.h else []) + r.m) if m in C]; o = {"covr": float(bool(mem))}
    rows = pd.concat([G[m] for m in mem if m in G]) if any(m in G for m in mem) else None
    for suf, lag in (("", 1), ("_lag2", 2)):
        w = rows[(rows.d <= D - pd.Timedelta(days=lag)) & (rows.d >= D - pd.Timedelta(days=30))] if rows is not None else None
        o[f"up7{suf}"] = float((w.d >= D - pd.Timedelta(days=7)).sum()) if w is not None else 0.0; o[f"up30{suf}"] = float(len(w)) if w is not None else 0.0
        o[f"mk30{suf}"] = float(len({fmaker.get(t) for t in w.target_id} - {None})) if w is not None else 0.0
    feats.append(o)
B = pd.concat([B.reset_index(drop=True), pd.DataFrame(feats)], axis=1); B = B[B.th_n_pre.notna()]
B = B[B.groupby("day").id.transform("count") >= 10]
z = lambda s: (s - s.mean()) / (s.std() or 1)
for c in ["honest", "th_n_pre", "covr"] + [f"{a}{s}" for a in ("up7", "up30", "mk30") for s in ("", "_lag2")]:
    B["z_" + c] = B.groupby("day")[c].transform(lambda s: z(np.log1p(s) if c not in ("honest", "covr") else s))
B["y"] = B.groupby("day")["rank"].transform(lambda r: z(-np.log(r))); B["mon"] = B.day.str[:7]; B["covday"] = B.groupby("day").covr.transform("mean")
ARMS = {"base (clean + th_n_pre)": ["z_honest", "z_th_n_pre"], "base + team": ["z_honest", "z_th_n_pre", "z_up7", "z_up30", "z_mk30", "z_covr"],
        "base + team LAG2": ["z_honest", "z_th_n_pre", "z_up7_lag2", "z_up30_lag2", "z_mk30_lag2", "z_covr"], "clean + team (no th)": ["z_honest", "z_up7", "z_up30", "z_mk30", "z_covr"], "clean only": ["z_honest"]}
mons = sorted(B.mon.unique())
for a, X in ARMS.items():
    B[a] = np.nan
    for m in mons[1:]:
        tr, te = B[B.mon < m], B[B.mon == m]; B.loc[te.index, a] = Ridge(alpha=10).fit(tr[X], tr.y).predict(te[X])
def ov(g, col): o = g.sort_values(col, ascending=False).id.tolist(); t = g.sort_values("rank").id.tolist(); return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
T = B[B["base + team"].notna()]; res = {"design": __doc__.split("\n    python")[0], "days": int(T.day.nunique()), "launches": len(T), "coverage": round(float(T.covr.mean()), 3)}
for sub, m in (("all days", T.day.notna()), ("days with >= 40% covered", T.covday >= 0.4)):
    S = T[m]; o = {"days": int(S.day.nunique()), "levels top3/5/10": {a: np.array([ov(g, a) for _, g in S.groupby("day")]).mean(0).round(1).tolist() for a in ARMS}}
    for a, b in (("base + team", "base (clean + th_n_pre)"), ("base + team LAG2", "base (clean + th_n_pre)"), ("base (clean + th_n_pre)", "clean only"), ("clean + team (no th)", "clean only")):
        d = np.array([np.array(ov(g, a)) - np.array(ov(g, b)) for _, g in S.groupby("day")]); bs = np.array([d[rng.integers(0, len(d), len(d))].mean(0) for _ in range(2000)])
        o[f"{a} - {b}"] = [[round(float(d[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(3)]
    res[sub] = o
json.dump(res, open(f"{OUT}/team_stack.json", "w"), indent=1, default=float); print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=float))
