"""First-time hunters vs the deployed 00:05 model (orchestrator 23:05Z Nov 13). Counts only.
First-time hunter (FTH): the launch's hunter (warehouse poster) hunted no featured launch on an earlier day in the 2025 daily lists
(raw/ph_history/2025) or the 2026 warehouse. Team = hunter + named makers. Per person, from the people store, DATED BEFORE the launch day:
  age_d      account age (persons.joined) at the launch day
  up30/90/365 upvotes on launches dated in the window (target launch day from the 2025 lists + 2026 warehouse)
  top5_365   upvotes on launches dated in the prior 365 d that finished top 5
  com90/365  comments + replies with ts before the day
  disc365    discussions (forum) with ts before the day;  rev365 reviews with ts before the day
  made_prior 'launched' events (maker role) with ts before the day
Undated fields (follows, collections, stacks, follower counts) are not used. Unheld people contribute 0 plus held flags.
Launch features: hunter_* (hunter's values) and team_* (sum over held team members, age = max), n_held, hunter_held.
(1) Descriptive, FTH launches Apr - Oct (arm 2 days): standardized difference (top 3 minus rest; top 10 minus rest) with day bootstrap;
    coverage: share of FTH hunters held, by entry route (request_provenance); by launch-age tercile; mean within-day partial Spearman of
    each feature with the arm-2 residual (arm-2 rank - final rank) among FTH launches.
(2) Score: month-forward ridge on within-day z (target z(-ln rank)), base = z(arm2) [+ FTH indicator]; augmented = base + FTH x z(log1p feat)
    for a small fixed set. Paired top 3/5/10 vs base, day bootstrap: all days; days with >= 1 FTH launch in arm 2's top 6; by age tercile.
    python first_hunter.py <store dir> <scratchpad> <arm2 parquet> <out dir>
"""
import glob, hashlib, json, os, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge
ST, SP, A2P, OUT = sys.argv[1:5]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
SALT = open(f"{SP}/early/salt").read().strip(); pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
def mk(m):
    try: return [x for x in json.loads(m) if x and not str(x).startswith("[")] if isinstance(m, str) and m.startswith("[") else []
    except Exception: return []
L = pd.concat([pd.read_parquet(f) for f in glob.glob(f"{SP}/early/launches/*.parquet")]).sort_values("updated_at").drop_duplicates("id", keep="last")
L["id"] = L.id.astype(str); L = L[L.daily_rank.notna()].copy(); L["rank"] = L.daily_rank.astype(float)
H25 = []
for f in sorted(glob.glob(f"{SP}/ph2025/*.json")):
    d = os.path.basename(f)[:10]
    for p in json.load(open(f)): H25.append((str(p["id"]), d, str((p.get("user") or {}).get("username") or "").lower(), p.get("dailyRank")))
H25 = pd.DataFrame(H25, columns=["id", "day", "hunter", "rank"])
lday = dict(zip(H25.id, H25.day)); lday.update(dict(zip(L.id, L.day)))
lrank = dict(zip(H25.id, pd.to_numeric(H25["rank"], errors="coerce"))); lrank.update(dict(zip(L.id, L["rank"])))
first_hunt = {}
for h, d in list(zip(H25.hunter, H25.day)) + list(zip(L.poster.astype(str).str.lower(), L.day)):
    if h and not h.startswith("["): first_hunt[h] = min(first_hunt.get(h, "9999"), d)
L["hunter"] = L.poster.astype(str).str.lower(); L["fth"] = [first_hunt.get(h, "9999") >= d for h, d in zip(L.hunter, L.day)]
L["hpid"] = L.hunter.map(pid); L["team"] = [list(dict.fromkeys([hp] + [pid(x) for x in mk(m)])) for hp, m in zip(L.hpid, L.makers)]
A2 = pd.read_parquet(A2P)[["id", "both"]]; A2["id"] = A2.id.astype(str); L = L.merge(A2, on="id")
L = L[L.groupby("day").id.transform("count") >= 10].copy()
P = pd.read_parquet(f"{ST}/persons.parquet").set_index("person_id"); comp = set(P.index[P.complete])
JD = pd.to_datetime(P.joined, utc=True, errors="coerce").dt.tz_convert(None)
need = set(p for t in L.team for p in t) & comp
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id", "ts_lo"]); E = E[E.person_id.isin(need)]
U = E[E.kind == "upvote"].drop_duplicates(["person_id", "target_id"]).copy(); U["d"] = U.target_id.astype(str).map(lday); U = U[U.d.notna()]
U["top5"] = U.target_id.astype(str).map(lrank) <= 5
TS = E[E.kind.isin(["comment", "reply", "discussion", "review", "launched"]) & E.ts_lo.notna()].copy()
TS["d"] = pd.to_datetime(TS.ts_lo, utc=True, errors="coerce").dt.strftime("%Y-%m-%d"); TS = TS[TS.d.notna()]
TS["k"] = TS.kind.replace({"reply": "comment"})
UD = {p: (np.sort(g.d.values), g.sort_values("d").top5.values) for p, g in U.groupby("person_id")}
KD = {(p, k): np.sort(g.d.values) for (p, k), g in TS.groupby(["person_id", "k"])}
print("people", len(need), "upvotes", len(U), "ts events", len(TS), flush=True)
FEATS = ["age_d", "up30", "up90", "up365", "top5_365", "com90", "com365", "disc365", "rev365", "made_prior"]
def pf(p, day):
    D = pd.Timestamp(day); w = {k: (D - pd.Timedelta(days=k)).strftime("%Y-%m-%d") for k in (30, 90, 365)}; o = dict.fromkeys(FEATS, 0.0)
    j = JD.get(p); o["age_d"] = float((D - j).days) if j is not None and pd.notna(j) and j < D else 0.0
    if p in UD:
        u, t5 = UD[p]; b = u < day
        for k in (30, 90, 365): o[f"up{k}"] = float((b & (u >= w[k])).sum())
        o["top5_365"] = float((b & (u >= w[365]) & t5).sum())
    for k, nm, win in (("comment", "com90", 90), ("comment", "com365", 365), ("discussion", "disc365", 365), ("review", "rev365", 365)):
        a = KD.get((p, k)); o[nm] = float(((a < day) & (a >= w[win])).sum()) if a is not None else 0.0
    a = KD.get((p, "launched")); o["made_prior"] = float((a < day).sum()) if a is not None else 0.0
    return o
rows = []
for r in L.itertuples():
    hp = r.hpid; held = [p for p in r.team if p in comp]; o = {"id": r.id, "hunter_held": float(hp in comp), "n_held": float(len(held)), "team_n": float(len(r.team))}
    hf = pf(hp, r.day) if hp in comp else dict.fromkeys(FEATS, 0.0); o.update({f"h_{k}": v for k, v in hf.items()})
    tf = [pf(p, r.day) for p in held]
    for k in FEATS: o[f"t_{k}"] = (max([x[k] for x in tf]) if k == "age_d" else sum(x[k] for x in tf)) if tf else 0.0
    rows.append(o)
L = L.merge(pd.DataFrame(rows), on="id"); L["mon"] = L.day.str[:7]
if os.environ.get("DUMP"): L[["id", "day", "fth", "t_top5_365", "t_up365", "h_top5_365"]].to_parquet(os.environ["DUMP"]); sys.exit(0)   # per-launch features for the joint stack
z = lambda s: (s - s.mean()) / (s.std() or 1)
L["zb"] = L.groupby("day").both.transform(z); L["y"] = L.groupby("day")["rank"].transform(lambda r: z(-np.log(r)))
L["a2rank"] = L.groupby("day").both.rank(ascending=False); L["resid"] = L.a2rank - L["rank"]
days = sorted(L.day.unique()); terc = {d: k for k, part in enumerate(np.array_split(np.array(days), 3)) for d in part}; L["terc"] = L.day.map(terc)
F = L[L.fth]; FC = [c for c in L.columns if c.startswith(("h_", "t_"))] + ["hunter_held", "n_held"]
def dboot(df, fn, B=1000):
    dd = df.day.unique(); g = {d: x for d, x in df.groupby("day")}; v = fn(df)
    bs = [fn(pd.concat([g[d] for d in rng.choice(dd, len(dd))])) for _ in range(B)]
    return [round(float(v), 3), round(float(np.nanpercentile(bs, 2.5)), 3), round(float(np.nanpercentile(bs, 97.5)), 3)]
def smd(col, thr):
    def f(x):
        a, b = np.log1p(x[x["rank"] <= thr][col]), np.log1p(x[x["rank"] > thr][col]); s = np.sqrt((a.var() + b.var()) / 2) or np.nan
        return (a.mean() - b.mean()) / s
    return f
res = {"design": __doc__.split("\n    python")[0], "arm2 days": len(days), "launches": len(L), "FTH launches": int(L.fth.sum()), "FTH share": round(float(L.fth.mean()), 3)}
# replicate the orchestrator's arm-2 stat
def top3hit(g): return len(set(g.nsmallest(3, "a2rank").id) & set(g.nsmallest(3, "rank").id)) / 3
cnt = {d: int(g.nsmallest(3, "rank").fth.sum()) for d, g in L.groupby("day")}; hit = {d: top3hit(g) for d, g in L.groupby("day")}
res["arm2 top-3 hit by # FTH in true top 3"] = {k: [round(float(np.mean([hit[d] for d in days if min(cnt[d], 2) == k])) * 100, 1), sum(min(cnt[d], 2) == k for d in days)] for k in (0, 1, 2)}
win = L[L["rank"] <= 3]; caught = win[win.a2rank <= 3]; missed = win[win.a2rank > 3]
res["FTH share among arm2-missed / caught winners"] = [round(float(missed.fth.mean()), 3), round(float(caught.fth.mean()), 3)]
res["FTH top-3 rate / non-FTH top-3 rate"] = [round(float((F["rank"] <= 3).mean()), 3), round(float((L[~L.fth]["rank"] <= 3).mean()), 3)]
# coverage
hh = F.drop_duplicates("hpid"); er = P.entry_route.reindex(hh.hpid[hh.hpid.isin(comp)]).fillna("unknown").value_counts()
res["coverage"] = {"FTH hunters": len(hh), "held (complete)": int(hh.hpid.isin(comp).sum()), "share held": round(float(hh.hpid.isin(comp).mean()), 3),
    "held by entry route": er.to_dict(), "FTH launches with >= 1 held team member": round(float((F.n_held > 0).mean()), 3),
    "held share among FTH top-3 vs rest": [round(float(F[F['rank'] <= 3].hunter_held.mean()), 3), round(float(F[F['rank'] > 3].hunter_held.mean()), 3)]}
d1 = {}
for c in FC:
    d1[c] = {"SMD top3 vs rest [day boot]": dboot(F, smd(c, 3)), "SMD top10 vs rest": dboot(F, smd(c, 10))}
    pc = {}
    for k in range(3):
        g = F[F.terc == k]; pc[f"terc{k}"] = dboot(g, smd(c, 10), 400)
    d1[c]["SMD top10 by age tercile (0 = oldest)"] = pc
    sp = [spearmanr(g[c], g.resid).correlation for _, g in F.groupby("day") if len(g) >= 3 and g[c].nunique() > 1]
    d1[c]["mean within-day Spearman(feat, arm2 residual), FTH only"] = [round(float(np.mean(sp)), 3), len(sp)] if sp else None
res["(1) FTH launches: top vs rest"] = d1
print(json.dumps({k: v for k, v in res.items() if k not in ("design",)}, default=float)[:4000], flush=True)
# (2) score
SC = ["h_age_d", "h_up365", "h_top5_365", "h_com365", "t_up365", "t_top5_365", "t_made_prior", "hunter_held"]
for c in SC: L["z_" + c] = L.groupby("day")[c].transform(lambda s: z(np.log1p(s))) * L.fth
L["fthf"] = L.fth.astype(float)
mons = sorted(L.mon.unique()); ARMS = {"base": ["zb"], "base+FTH": ["zb", "fthf"], "base+FTH+score": ["zb", "fthf"] + ["z_" + c for c in SC]}
for a, X in ARMS.items():
    L["p_" + a] = np.nan
    for m in mons[1:]:
        tr, te = L[L.mon < m], L[L.mon == m]; L.loc[te.index, "p_" + a] = Ridge(alpha=10).fit(tr[X], tr.y).predict(te[X])
T = L[L.p_base.notna()]; td = sorted(T.day.unique())
def dm(g, col):
    o = g.sort_values(col, ascending=False).id.tolist(); t = g.sort_values("rank").id.tolist(); return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
def pdiff(A, B):
    df = A - B; bs = np.array([df[rng.integers(0, len(df), len(df))].mean(0) for _ in range(4000)])
    return [[round(float(df[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(3)]
seg = [d for d in td if T[T.day == d].nsmallest(6, "a2rank").fth.any()]
o2 = {"scored days": len(td), "days with >= 1 FTH in arm2 top 6": len(seg), "score features": SC}
for nm, dl in (("all days", td), ("FTH-in-top6 days", seg)):
    B0 = np.array([dm(T[T.day == d], "p_base") for d in dl]); o2[nm] = {"base top3/5/10": B0.mean(0).round(1).tolist()}
    for a in list(ARMS)[1:]:
        A = np.array([dm(T[T.day == d], "p_" + a) for d in dl]); o2[nm][a] = {"top3/5/10": A.mean(0).round(1).tolist(), "vs base": pdiff(A, B0)}
B0 = {d: dm(T[T.day == d], "p_base") for d in td}; A = {d: dm(T[T.day == d], "p_base+FTH+score") for d in td}
o2["score vs base top3 by age tercile (0 = oldest)"] = {k: pdiff(np.array([A[d] for d in td if terc[d] == k]), np.array([B0[d] for d in td if terc[d] == k]))[0] for k in range(3)}
coef = Ridge(alpha=10).fit(T[ARMS["base+FTH+score"]], T.y).coef_; o2["full-fit coefficients (illustrative)"] = dict(zip(ARMS["base+FTH+score"], np.round(coef, 3).tolist()))
res["(2) month-forward score"] = o2
json.dump(res, open(os.path.join(OUT, "first_hunter.json"), "w"), indent=1, default=float); print(json.dumps(o2, default=float))
