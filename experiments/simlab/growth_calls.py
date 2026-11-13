"""Monthly / weekly calls from votes with a post-day growth model (orchestrator 23:42Z Nov 13). Counts only.
(1) Growth curve: every timestamped read of the same launch (warehouse snapshots ~/.usersim_sim/launches + early/launches, updated_at;
    vote_snapshots Oct 31 - Nov 12; ph_at_launch api_detail snapshots). Age = read time - 00:00 PT of the launch day (days). Reads at
    age < 0.9 d (inside the launch day) are dropped; age bins B = close [0.9,1.2], (1.2,2], (2,3], (3,5], (5,7], (7,10], (10,14], (14,21],
    (21,30], (30,60], (60,90], (90,180], (180,400]. G(bin) = log growth vs close, fit by least squares on all within-launch pairs
    (log(v2+1) - log(v1+1) = G(b2) - G(b1)), G(close) = 0; separately by size tercile (launch's max read votes). Support = launches per bin.
(2) For each launch: late read (latest warehouse read for 2026; the Nov-2026 API list read for 2025, age > 300 d -> last bin) ->
    est votes at call time t: v_late * exp(G(age_t) - G(age_late)); a launch whose age at t is < 1 d is at close (G = 0).
(3) Month calls at day d in {10, 15, 20, 25, end} (end of day d PT, launches dated <= d of that month): top k by est votes at d vs final
    monthlyRank 1..k; rules: RANKS (dailyRank asc, earlier day first), CLOSE (votes at day close, no post-day growth), GROWTH (est votes
    at d), LATE (late-read votes; upper bound, uses later information). Weekly (Mon-Sun PT weeks) at each weekday vs weeklyRank.
    CEILING = share of the final top k already launched by d. Month / week bootstrap; 2025 and 2026 separately.
    python growth_calls.py <scratchpad> <out dir>
"""
import glob, json, os, sys
import numpy as np, pandas as pd
SP, OUT = sys.argv[1:3]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
X = pd.read_parquet(f"{SP}/grow/reads.parquet"); X = X[X.age >= 0.9].copy()
EDGES = [0.9, 1.2, 2, 3, 5, 7, 10, 14, 21, 30, 60, 90, 180, 10000]; NB = len(EDGES) - 1
X["b"] = np.clip(np.searchsorted(EDGES, X.age.values, side="left") - 1, 0, NB - 1); X.loc[X.age <= 1.2, "b"] = 0
X["lv"] = np.log1p(X.votes)
size = X.groupby("id").votes.max(); X["sz"] = X.id.map(pd.qcut(size, 3, labels=False, duplicates="drop"))
def fit(Z):
    rows, ys = [], []
    for _, g in Z.groupby("id"):
        g = g.groupby("b").lv.mean()
        if len(g) < 2: continue
        bs = g.index.values
        for i in range(len(bs) - 1):
            r = np.zeros(NB); r[bs[i + 1]] += 1; r[bs[i]] -= 1; rows.append(r); ys.append(g.iloc[i + 1] - g.iloc[i])
    A = np.array(rows)[:, 1:]; G = np.linalg.lstsq(A, np.array(ys), rcond=None)[0]; G = np.concatenate([[0.0], G])
    sup = Z.groupby("b").id.nunique().reindex(range(NB)).fillna(0).astype(int)
    return G, sup, len(ys)
G, sup, npairs = fit(X); lab = ["close"] + [f"({EDGES[i]},{EDGES[i+1]}]" for i in range(1, NB)]
res = {"design": __doc__.split("\n    python")[0], "(1) growth g = votes / votes at close": {"pairs": npairs, "all": {l: [round(float(np.exp(g)), 3), int(s)] for l, g, s in zip(lab, G, sup)}}}
for s in sorted(X.sz.dropna().unique()):
    Gs, ss, _ = fit(X[X.sz == s]); res["(1) growth g = votes / votes at close"][f"size tercile {int(s)} (0 = smallest)"] = {l: [round(float(np.exp(g)), 3), int(n)] for l, g, n in zip(lab, Gs, ss)}
mid = np.array([1.0, 1.6, 2.5, 4, 6, 8.5, 12, 17.5, 25.5, 45, 75, 135, 290])
def Gof(age):
    age = np.asarray(age, float); return np.where(age <= 1.0, 0.0, np.interp(age, mid, G))
print(json.dumps(res["(1) growth g = votes / votes at close"]["all"]), flush=True)
# launches + late reads
L = pd.concat([pd.read_parquet(f) for f in glob.glob(f"{SP}/early/launches/*.parquet")]); L["id"] = L.id.astype(str); L["votes"] = pd.to_numeric(L.votes, errors="coerce")
L["at"] = pd.to_datetime(L.updated_at, utc=True, errors="coerce"); L = L.sort_values("at").drop_duplicates("id", keep="last").dropna(subset=["daily_rank", "votes"])
L["age_late"] = (L["at"] - pd.to_datetime(L.day).dt.tz_localize("America/Los_Angeles").dt.tz_convert("UTC")).dt.total_seconds() / 86400
L26 = L.rename(columns={"daily_rank": "dr", "weekly_rank": "wr", "monthly_rank": "mr"})[["id", "day", "dr", "wr", "mr", "votes", "age_late"]]
man = {json.loads(l)["path"].split("/")[-1][:10]: json.loads(l).get("fetched_at") for l in os.popen("gsutil cat gs://usersim-bakeoff-347838016394/usersim_sim/raw/ph_history/manifest.jsonl") if l.strip()}
r25 = []
for f in sorted(glob.glob(f"{SP}/ph2025/*.json")):
    d = os.path.basename(f)[:10]; fa = pd.Timestamp(man.get(d) or "2026-11-10T00:00:00Z")
    for p in json.load(open(f)):
        if p.get("dailyRank"): r25.append((str(p["id"]), d, p["dailyRank"], p.get("weeklyRank"), p.get("monthlyRank"), p.get("votesCount"), (fa - pd.Timestamp(d).tz_localize("America/Los_Angeles").tz_convert("UTC")).total_seconds() / 86400))
L25 = pd.DataFrame(r25, columns=["id", "day", "dr", "wr", "mr", "votes", "age_late"])
def run(D, yr):
    D = D.copy(); D["dt"] = pd.to_datetime(D.day); D["close"] = D.votes * np.exp(-Gof(D.age_late)); D["mon"] = D.day.str[:7]
    D["wk"] = (D.dt - pd.to_timedelta(D.dt.dt.weekday, unit="D")).dt.strftime("%Y-%m-%d")
    out = {}
    for per, key, rk, calls in (("month", "mon", "mr", None), ("week", "wk", "wr", None)):
        recs = {}
        for pk, g in D.groupby(key):
            g = g[g[rk].notna()]
            if len(g) < 20 or g[rk].min() > 1: continue
            if per == "month":
                last = g.dt.max().day; cd = {f"day {x}": x for x in (10, 15, 20, 25) if x < last}; cd["month end"] = last
                start = pd.Timestamp(pk + "-01")
            else:
                start = pd.Timestamp(pk); cd = {f"weekday {x+1}": x + 1 for x in range(7)}
            for cn, x in cd.items():
                t_end = start + pd.Timedelta(days=x)   # end of call day
                s = g[g.dt < t_end].copy()
                if not len(s): continue
                s["age_t"] = (t_end - s.dt).dt.total_seconds() / 86400; s["growth"] = s.close * np.exp(Gof(s.age_t))
                s["ranks"] = -s.dr + (t_end - s.dt).dt.days * 1e-3
                tr = g.sort_values(rk); r = recs.setdefault(cn, {k: [] for k in ("RANKS", "CLOSE", "GROWTH", "LATE", "CEILING")})
                for k in (3, 5, 10):
                    T = set(tr.id[:k])
                    for nm, col in (("RANKS", "ranks"), ("CLOSE", "close"), ("GROWTH", "growth"), ("LATE", "votes")):
                        r[nm].append((k, len(T & set(s.sort_values(col, ascending=False).id[:k])) / k * 100, pk))
                    r["CEILING"].append((k, len(T & set(s.id)) / k * 100, pk))
        o = {}
        for cn, r in recs.items():
            o[cn] = {}
            for nm, v in r.items():
                df = pd.DataFrame(v, columns=["k", "hit", "p"]).pivot_table(index="p", columns="k", values="hit").values
                bs = np.array([df[rng.integers(0, len(df), len(df))].mean(0) for _ in range(2000)])
                o[cn][nm] = [f"{df[:, j].mean():.0f} [{np.percentile(bs[:, j], 2.5):.0f}, {np.percentile(bs[:, j], 97.5):.0f}]" for j in range(3)]
            o[cn]["n periods"] = len(df)
            g_ = pd.DataFrame(r["GROWTH"]).pivot_table(index=2, columns=0, values=1).values; c_ = pd.DataFrame(r["CLOSE"]).pivot_table(index=2, columns=0, values=1).values
            u_ = pd.DataFrame(r["LATE"]).pivot_table(index=2, columns=0, values=1).values; rk_ = pd.DataFrame(r["RANKS"]).pivot_table(index=2, columns=0, values=1).values
            dd = g_ - rk_; bs = np.array([dd[rng.integers(0, len(dd), len(dd))].mean(0) for _ in range(2000)])
            o[cn]["GROWTH - RANKS top3/5/10"] = [f"{dd[:, j].mean():+.0f} [{np.percentile(bs[:, j], 2.5):+.0f}, {np.percentile(bs[:, j], 97.5):+.0f}]" for j in range(3)]
            gap = (u_ - rk_).mean(0); o[cn]["share of RANKS->LATE gap closed by GROWTH"] = [round(float((g_ - rk_).mean(0)[j] / gap[j]), 2) if abs(gap[j]) > 1 else None for j in range(3)]
        out[per] = o
    return out
res["(3) 2026 (Jan-Oct, warehouse late reads)"] = run(L26[L26.day < "2026-11-01"], 2026)
res["(3) 2025 (API lists read Nov 2026; late age beyond curve support -> last bin)"] = run(L25, 2025)
json.dump(res, open(os.path.join(OUT, "growth_calls.json"), "w"), indent=1, default=str); print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=str)[:12000])
