"""Calibrated chances for the running weekly / monthly boards (orchestrator 01:28Z Nov 14). Counts only.
Periods: Mon-Sun PT weeks and calendar months, 2025 (API day lists) + 2026 (warehouse, Jan-Oct), complete periods with weeklyRank /
monthlyRank. Running board at the end of call point c (weekday 1..6; month day 10/15/20/25): launches dated <= c ranked by votes at day
close (reconstructed = late votes / g(age), growth curve from growth_calls.py, g ~ 1.03-1.06; flagged 'reconstructed' - true close reads
exist only from Oct 31). Rows = launches in the running top 15. Target = final weeklyRank / monthlyRank <= k (k = 3, 5, 10).
Features: ln(running position), ln(votes / votes of running k-th) and ln(votes / votes of running (k+1)-th), share of the period's launch
days remaining, and position x remaining. Logistic per (period type, k), WALK-FORWARD (fit on periods that closed before this period
started). Baseline POSITION-ONLY = earlier periods' share finishing top k by (running position, call point). Metrics per period type and
year: Brier skill vs position-only and vs base rate (period bootstrap), reliability by bin. Frozen fit on all periods -> frozen_period_prob.json.
    python period_prob.py <scratchpad> <out dir>
"""
import glob, json, os, sys
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
SP, OUT = sys.argv[1:3]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
L = pd.concat([pd.read_parquet(f) for f in glob.glob(f"{SP}/early/launches/*.parquet")]); L["id"] = L.id.astype(str); L["votes"] = pd.to_numeric(L.votes, errors="coerce")
L["at"] = pd.to_datetime(L.updated_at, utc=True, errors="coerce"); L = L.sort_values("at").drop_duplicates("id", keep="last").dropna(subset=["daily_rank", "votes"])
L["age"] = (L["at"] - pd.to_datetime(L.day).dt.tz_localize("America/Los_Angeles").dt.tz_convert("UTC")).dt.total_seconds() / 86400
A = L.rename(columns={"weekly_rank": "wr", "monthly_rank": "mr"})[["id", "day", "wr", "mr", "votes", "age"]]; A["yr"] = 2026
r25 = []
for f in sorted(glob.glob(f"{SP}/ph2025/*.json")):
    d = os.path.basename(f)[:10]
    for p in json.load(open(f)):
        if p.get("dailyRank"): r25.append((str(p["id"]), d, p.get("weeklyRank"), p.get("monthlyRank"), p.get("votesCount"), 400.0))
A = pd.concat([A, pd.DataFrame(r25, columns=["id", "day", "wr", "mr", "votes", "age"]).assign(yr=2025)])
GC = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports", "growth_calls", "growth_calls.json")))["(1) growth g = votes / votes at close"]["all"]
gv = [v[0] for v in GC.values()]; mid = np.array([1.0, 1.6, 2.5, 4, 6, 8.5, 12, 17.5, 25.5, 45, 75, 135, 290])
A["close"] = A.votes / np.interp(A.age.clip(lower=1), mid, gv); A["dt"] = pd.to_datetime(A.day)
A["wk"] = (A.dt - pd.to_timedelta(A.dt.dt.weekday, unit="D")).dt.strftime("%Y-%m-%d"); A["mon"] = A.day.str[:7]
KS = (3, 5, 10); rows = []
for per, key, rk in (("week", "wk", "wr"), ("month", "mon", "mr")):
    for pk, g in A.groupby(key):
        g = g[g[rk].notna()]
        if per == "week":
            if g.dt.dt.weekday.nunique() < 7 or len(g) < 30: continue
            start = pd.Timestamp(pk); ndays = 7; cps = list(range(1, 7))
        else:
            start = pd.Timestamp(pk + "-01"); ndays = start.days_in_month
            if g.dt.dt.day.nunique() < ndays - 1: continue
            cps = [10, 15, 20, 25]
        for c in cps:
            s = g[g.dt < start + pd.Timedelta(days=c)].sort_values("close", ascending=False).reset_index(drop=True)
            if len(s) < 11: continue
            for i, r in s.head(15).iterrows():
                o = {"per": per, "pk": pk, "yr": int(r.yr), "c": c, "pos": i + 1, "rem": (ndays - c) / ndays, "id": r.id, "final": float(r[rk]), "start": start.strftime("%Y-%m-%d")}
                for k in KS: o[f"mk{k}"] = np.log((r.close + 1) / (s.close.iloc[k - 1] + 1)); o[f"mk1{k}"] = np.log((r.close + 1) / (s.close.iloc[k] + 1))
                rows.append(o)
R = pd.DataFrame(rows); R["lnpos"] = np.log(R.pos); R["posrem"] = R.lnpos * R.rem
res = {"design": __doc__.split("\n    python")[0], "periods": {f"{a} {b}": int(v) for (a, b), v in R.groupby(["per", "yr"]).pk.nunique().items()}, "rows": len(R)}
FZ = {"basis": "2025 API lists + 2026 warehouse, complete weeks / months; close votes reconstructed (late / g)", "models": {}, "position tables": {}}
for per in ("week", "month"):
    P = R[R.per == per].copy(); pks = sorted(P.start.unique())
    for k in KS:
        X = ["lnpos", f"mk{k}", f"mk1{k}", "rem", "posrem"]; y = (P.final <= k).astype(float); P[f"y{k}"] = y; P[f"p{k}"] = np.nan; P[f"q{k}"] = np.nan; P[f"b{k}"] = np.nan
        for s0 in pks:
            tr = P[P.start < s0]; te = P.start == s0
            if tr.pk.nunique() < 4 or tr[f"y{k}"].nunique() < 2: continue
            P.loc[te, f"p{k}"] = LogisticRegression(C=1.0, max_iter=1000).fit(tr[X], tr[f"y{k}"]).predict_proba(P.loc[te, X])[:, 1]
            tb = tr.groupby(["c", "pos"])[f"y{k}"].mean(); P.loc[te, f"q{k}"] = [tb.get((c, p), tr[f"y{k}"].mean()) for c, p in zip(P.loc[te, "c"], P.loc[te, "pos"])]
            P.loc[te, f"b{k}"] = tr[f"y{k}"].mean()
        lr = LogisticRegression(C=1.0, max_iter=1000).fit(P[X], P[f"y{k}"]); FZ["models"][f"{per}_top{k}"] = {"features": X, "intercept": float(lr.intercept_[0]), "coef": dict(zip(X, map(float, lr.coef_[0])))}
        FZ["position tables"][f"{per}_top{k}"] = {f"{c}|{p}": round(float(v), 4) for (c, p), v in P.groupby(["c", "pos"])[f"y{k}"].mean().items()}
    for yr in (2025, 2026, "all"):
        S = P if yr == "all" else P[P.yr == yr]; o = {}
        for k in KS:
            S2 = S.dropna(subset=[f"p{k}"]); y, p, q, b = S2[f"y{k}"].values, S2[f"p{k}"].values, S2[f"q{k}"].values, S2[f"b{k}"].values
            if not len(y): continue
            ps = S2.pk.values; up = np.unique(ps); ix = {u: np.flatnonzero(ps == u) for u in up}; bs = []
            for _ in range(1000):
                j = np.concatenate([ix[u] for u in rng.choice(up, len(up))]); bs.append([1 - np.mean((p[j] - y[j]) ** 2) / np.mean((q[j] - y[j]) ** 2), 1 - np.mean((p[j] - y[j]) ** 2) / np.mean((b[j] - y[j]) ** 2)])
            bs = np.array(bs); cb = pd.cut(p, [0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1.01], right=False)
            rel = pd.DataFrame({"b": cb, "p": p, "y": y}).groupby("b", observed=True).agg(pred=("p", "mean"), obs=("y", "mean"), n=("y", "size"))
            o[f"top{k}"] = {"periods scored": int(len(up)), "rows": int(len(y)), "Brier skill vs position-only [CI]": [round(float(1 - np.mean((p - y) ** 2) / np.mean((q - y) ** 2)), 3), round(float(np.percentile(bs[:, 0], 2.5)), 3), round(float(np.percentile(bs[:, 0], 97.5)), 3)],
                            "Brier skill vs base rate [CI]": [round(float(1 - np.mean((p - y) ** 2) / np.mean((b - y) ** 2)), 3), round(float(np.percentile(bs[:, 1], 2.5)), 3), round(float(np.percentile(bs[:, 1], 97.5)), 3)],
                            "reliability (pred %, obs %, n)": {str(i): [round(float(r.pred) * 100, 1), round(float(r.obs) * 100, 1), int(r.n)] for i, r in rel.iterrows()}}
        res[f"{per} | {yr}"] = o
json.dump(FZ, open(os.path.join(OUT, "frozen_period_prob.json"), "w"), indent=1); json.dump(res, open(os.path.join(OUT, "period_prob.json"), "w"), indent=1, default=str)
for k_, v in res.items():
    if k_ != "design": print(k_, json.dumps(v, default=str)[:1800])
