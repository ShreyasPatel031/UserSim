"""Team's own recent community engagement before launch (orchestrator 10:34Z Nov 13). No LLM. Counts only.
Team = hunter (launches.poster, always) and, variant TEAM, also every named maker (launches.makers; the 00:05 read lists makers, the
warehouse list may be later: flagged). Members count only if COMPLETE in the merged store (61,468). Per member, strictly before 00:00 PT of
the target launch day:
  up7 / up30   upvotes given on launches dated in the 7 / 30 days before (an upvote's date = the acted-on launch's day: upvote rows are
               snapshots, so a late vote on an older launch cast after the target day cannot be excluded - stated leak risk)
  com30        comments (exact createdAt) on other launches in the 30 days before
  forum14      forum posts / discussions (exact) in the 14 days before
  makers30     distinct first-named makers of the launches upvoted in the 30 days before
  days_since   days since the member's last dated activity (upvoted launch day / comment / discussion) before the day (capped 365)
Team value = sum over members (days_since: min). Launches without a complete member: missing (indicator) - coverage reported.
Tests (launches with an honest_preds_v2 score, Mar 1 - Nov 10): standardized difference top-3 / top-10 vs rest among covered launches
(day bootstrap); within-day partial Spearman beyond the clean score; beyond the hunter's followersCount (deployed forecast files, Oct 28 on)
; leave-day-out ridge top 3/5/10, paired day bootstrap.
    python team_engage.py <scratchpad> <merged store> <out dir>
"""
import glob, hashlib, json, os, subprocess, sys
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge
SP, ST, OUT = sys.argv[1:4]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0); PT = "America/Los_Angeles"
SALT = open(os.path.join(SP, "early/salt")).read().strip(); pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(SP, "early/launches/*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str)
def mk(m):
    try: return [pid(x) for x in json.loads(m) if x and not str(x).startswith("[")] if isinstance(m, str) and m.startswith("[") else []
    except Exception: return []
L["h"] = [pid(p) if isinstance(p, str) and p and not p.startswith("[") else None for p in L.poster]; L["m"] = [mk(m) for m in L.makers]
lday = dict(zip(L.id, L.day)); fmaker = {i: (m[0] if m else None) for i, m in zip(L.id, L.m)}
P = pd.read_parquet(os.path.join(ST, "persons.parquet")); C = set(P[P.complete].person_id)
E = pd.read_parquet(os.path.join(ST, "events.parquet"), columns=["person_id", "kind", "target_id", "ts_lo"]); E = E[E.person_id.isin(C) & E.kind.isin(["upvote", "comment", "discussion"])].copy()
E["target_id"] = E.target_id.astype(str)
up = E[E.kind == "upvote"].drop_duplicates(["person_id", "target_id"]).copy(); up["d"] = pd.to_datetime(up.target_id.map(lday)); up = up[up.d.notna()]
ex = E[E.kind != "upvote"].copy(); ex["t"] = pd.to_datetime(ex.ts_lo, utc=True).dt.tz_convert(PT).dt.tz_localize(None); ex = ex[ex.t.notna()]
UP = {p: g for p, g in up.groupby("person_id")}; EX = {p: g for p, g in ex.groupby("person_id")}
def member_feats(p, D, own):
    u = UP.get(p); x = EX.get(p); o = {"up7": 0, "up30": 0, "com30": 0, "forum14": 0, "makers30": set(), "last": None}
    if u is not None:
        b = u[u.d < D]; b30 = b[b.d >= D - pd.Timedelta(days=30)]; o["up30"] = len(b30); o["up7"] = int((b30.d >= D - pd.Timedelta(days=7)).sum())
        o["makers30"] = {fmaker.get(t) for t in b30.target_id} - {None}; o["last"] = b.d.max() if len(b) else None
    if x is not None:
        b = x[x.t < D]
        c = b[(b.kind == "comment") & (b.t >= D - pd.Timedelta(days=30)) & (b.target_id != own)]; o["com30"] = len(c)
        o["forum14"] = int(((b.kind == "discussion") & (b.t >= D - pd.Timedelta(days=14))).sum())
        if len(b): o["last"] = max([v for v in (o["last"], b.t.max()) if v is not None])
    return o
H = pd.read_parquet(os.path.join(SP, "honest_preds_v2.parquet"))[["id", "honest"]]; H["id"] = H.id.astype(str)
B = L[L.daily_rank.notna()].merge(H, on="id"); B["rank"] = B.daily_rank.astype(float)
FEATS = ["up7", "up30", "com30", "forum14", "makers30", "days_since"]; rows = []
for r in B.itertuples():
    D = pd.Timestamp(r.day); o = {"id": r.id}
    for var, mem in (("H", [r.h] if r.h else []), ("T", list(dict.fromkeys(([r.h] if r.h else []) + r.m)))):
        mm = [m for m in mem if m in C]; o[f"{var}_cov"] = float(bool(mm))
        fs = [member_feats(m, D, r.id) for m in mm]
        if fs:
            o.update({f"{var}_{k}": float(sum(f[k] for f in fs)) for k in ("up7", "up30", "com30", "forum14")}); o[f"{var}_makers30"] = float(len(set().union(*[f["makers30"] for f in fs])))
            last = [f["last"] for f in fs if f["last"] is not None]; o[f"{var}_days_since"] = float(min(365, min((D - x).days for x in last))) if last else 365.0
    rows.append(o)
F = B.merge(pd.DataFrame(rows), on="id"); F.to_parquet(os.path.join(OUT, "team_engage_rows.parquet"))
# hunter followersCount from deployed forecast files (Oct 28 on)
hf = {}
for d in sorted(F.day.unique()):
    if d < "2026-10-28": continue
    raw = subprocess.run(["gsutil", "cat", f"gs://usersim-bakeoff-347838016394/usersim_sim/raw/daily/{d}/forecast_{d}.parquet"], capture_output=True).stdout
    if raw: import io; f_ = pd.read_parquet(io.BytesIO(raw)); hf.update(dict(zip(f_.id.astype(str), f_.ph_hunter_followers)))
F["hfollow"] = F.id.map(hf)
rk = lambda a: pd.Series(a).rank().to_numpy()
def partial(y, b, x):
    y, b, x = rk(y), rk(b), rk(x); return float(np.corrcoef(y - np.polyval(np.polyfit(b, y, 1), b), x - np.polyval(np.polyfit(b, x, 1), b))[0, 1])
def dboot(vals):
    v = np.array([x for x in vals if x == x]); bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)] if len(v) else [np.nan]
    return [round(float(v.mean()), 3) if len(v) else None, round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3), len(v)]
res = {"design": __doc__.split("\n    python")[0], "launches": len(F), "days": int(F.day.nunique()),
       "coverage": {"hunter complete": round(float(F.H_cov.mean()), 3), "hunter or a named maker complete": round(float(F.T_cov.mean()), 3)}}
for var in ("H", "T"):
    G = F[F[f"{var}_cov"] == 1].copy(); o = {}
    for k in FEATS:
        c = f"{var}_{k}"; sgn = -1 if k == "days_since" else 1
        sd = []; pc = []; pc_hf = []
        for d, g in G.groupby("day"):
            if len(g) < 5 or g[c].nunique() < 2: continue
            s = g[c].std() or 1; t3 = g["rank"] <= 3; t10 = g["rank"] <= 10
            sd.append(((g[c][t3].mean() - g[c][~t3].mean()) / s) if t3.any() and (~t3).any() else np.nan)
            pc.append(partial(-g["rank"].to_numpy(), g.honest.to_numpy(), sgn * g[c].to_numpy()))
            gh = g[g.hfollow.notna()]
            if len(gh) >= 5 and gh[c].nunique() > 1: pc_hf.append(partial(-gh["rank"].to_numpy(), np.log1p(gh.hfollow.to_numpy()), sgn * gh[c].to_numpy()))
        o[k] = {"std_diff_top3_vs_rest": dboot(sd), "partial_beyond_clean": dboot(pc), "partial_beyond_hunter_followers (Oct 28+)": dboot(pc_hf)}
    res[{"H": "hunter only", "T": "hunter + named makers"}[var]] = o
# leave-day-out top-k: clean vs clean + team block (missing -> 0 + coverage flag), within-day z
z = lambda s: (s - s.mean()) / (s.std() or 1)
for var in ("H", "T"):
    X = F.copy(); cols = [f"{var}_{k}" for k in FEATS]
    for c in cols: X[c] = X[c].fillna(0 if not c.endswith("days_since") else 365); X[c] = np.log1p(X[c])
    for c in cols + ["honest", f"{var}_cov"]: X["z_" + c] = X.groupby("day")[c].transform(z)
    X["y"] = X.groupby("day")["rank"].transform(lambda r: z(-np.log(r))); X["mon"] = X.day.str[:7]; Z = ["z_honest"] + ["z_" + c for c in cols] + [f"z_{var}_cov"]
    X["p"] = np.nan
    for m in sorted(X.mon.unique())[1:]:
        tr, te = X[X.mon < m], X[X.mon == m]; X.loc[te.index, "p"] = Ridge(alpha=10).fit(tr[Z], tr.y).predict(te[Z])
    def ov(g, col): o_ = g.sort_values(col, ascending=False).id.tolist(); t = g.sort_values("rank").id.tolist(); return [len(set(o_[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
    G = X[X.p.notna()]; per = np.array([np.array(ov(g, "p")) - np.array(ov(g, "z_honest")) for _, g in G.groupby("day") if len(g) >= 10])
    bs = np.array([per[rng.integers(0, len(per), len(per))].mean(0) for _ in range(2000)])
    res[f"month-forward top3/5/10 gain ({var})"] = [[round(float(per[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(3)] + [len(per)]
json.dump(res, open(os.path.join(OUT, "team_engage.json"), "w"), indent=1, default=float); print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=float)[:4000])
