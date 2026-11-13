"""Description-only rank band with 2025 training rows (orchestrator 11:33Z Nov 13). No LLM.
Model = the deployed product-only ridge recipe (landing_retrieval / web_launch_band: TF-IDF 1-2 grams, min_df 5, 4,000 features, top-80
2026 topic flags, log lengths, n topics; Ridge alpha 3), month-forward. Training rows: 2026 launches before the test month, optionally
+ every 2025 featured launch with a dailyRank (raw/ph_history/2025/<day>.json; votes as of fetch, ranks frozen).
Targets: Y_LN = ln(1+votes) (deployed); Y_PCT = within-day rank percentile 1 - (rank - 0.5) / n_ranked (comparable across years: 2025
days have fewer featured launches, median 11 vs about 25-50); Y_ZLN = within-day z of ln(1+votes).
Arms: A0 2026 / Y_LN (current), A1 2026 / Y_PCT, A2 2025+2026 / Y_PCT, A3 2025+2026 / Y_ZLN, A4 2025+2026 / Y_LN (2025 votes as of fetch).
Test: band_v2's 856 launches (Sep 1 - Nov 10) and the 130 most recent (fresh). Pooled Spearman with -rank, paired launch bootstrap vs A0;
80% rank-percentile band coverage / width cross-fit Sep <-> Oct + fresh (band_knn.calib). Part 2: month-forward OOF text score for every
2026 month from March; within-day partial correlation beyond honest_preds_v2 (clean 00:05) and month-forward ridge top 3/5/10 of
clean + text, paired day bootstrap, for A0 (= the PH agent's text ridge design) and the best 2025 arm.
    python band_2025.py <scratchpad> <out dir>
"""
import glob, json, os, subprocess, sys
import numpy as np, pandas as pd
from scipy import sparse
from scipy.stats import spearmanr
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge
SP, OUT = sys.argv[1:3]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0); TOKEN = r"(?u)\b[a-z0-9]+\b"; BK = "gs://usersim-bakeoff-347838016394/usersim_sim/raw/ph_history/2025"
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(SP, "early/launches/*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna() & L.votes.notna() & (L.day < "2026-11-11")].copy(); L["id"] = L.id.astype(str); L["tp"] = [json.loads(t) if isinstance(t, str) and t.startswith("[") else [] for t in L.topics]
L["votes"] = pd.to_numeric(L.votes, errors="coerce").astype(float); L["rank"] = L.daily_rank.astype(float); L["yr"] = 2026
cache = os.path.join(OUT, "ph2025.parquet")
if os.path.exists(cache): Y5 = pd.read_parquet(cache); Y5["tp"] = [list(t) for t in Y5.tp]
else:
    rows = []
    for p in subprocess.run(["gsutil", "ls", f"{BK}/"], capture_output=True, text=True).stdout.split():
        if not p.endswith(".json"): continue
        day = os.path.basename(p)[:-5]
        for x in json.loads(subprocess.run(["gsutil", "cat", p], capture_output=True).stdout or b"[]"):
            if not x.get("dailyRank"): continue
            tp = [e["node"]["name"] for e in ((x.get("topics") or {}).get("edges") or [])] if isinstance(x.get("topics"), dict) else []
            rows.append({"id": "y25_" + str(x["id"]), "day": day, "name": x.get("name"), "tagline": x.get("tagline"), "description": x.get("description"), "tp": tp,
                         "votes": float(x.get("votesCount") or 0), "rank": float(x["dailyRank"]), "yr": 2025})
    Y5 = pd.DataFrame(rows); Y5.to_parquet(cache)
A = pd.concat([L[["id", "day", "name", "tagline", "description", "tp", "votes", "rank", "yr"]], Y5], ignore_index=True)
A["text"] = (A.name.fillna("") + ". " + A.tagline.fillna("") + ". " + A.description.fillna("") + " " + A.tp.str.join(" ")).str.lower()
A["n"] = A.groupby("day")["rank"].transform("count"); A["y_ln"] = np.log1p(A.votes); A["y_pct"] = 1 - (A["rank"] - 0.5) / A.n
A["y_zln"] = A.groupby("day").y_ln.transform(lambda s: (s - s.mean()) / (s.std() or 1)); A["mon"] = A.day.str[:7]
print("2025 rows", int((A.yr == 2025).sum()), "days", A[A.yr == 2025].day.nunique(), "median launches/day 2025 / 2026:", int(A[A.yr == 2025].groupby("day").size().median()), int(A[A.yr == 2026].groupby("day").size().median()), flush=True)
top_topics = pd.Series([t for s in L.tp for t in s]).value_counts().head(80).index.tolist()
dense = lambda D: np.c_[np.array([[float(t in s) for t in top_topics] for s in D.tp]), np.log1p(D.description.fillna("").str.len()), np.log1p(D.tagline.fillna("").str.len()), D.tp.str.len()]
ARMS = {"A0 2026 ln(votes) [current]": (False, "y_ln"), "A1 2026 pct": (False, "y_pct"), "A2 2025+2026 pct": (True, "y_pct"), "A3 2025+2026 z ln(votes)": (True, "y_zln"), "A4 2025+2026 ln(votes)": (True, "y_ln")}
mons = sorted(A[A.yr == 2026].mon.unique())
for a, (use25, y) in ARMS.items():
    A[a] = np.nan
    for m in mons[2:]:
        tr = A[((A.yr == 2026) & (A.mon < m)) | ((A.yr == 2025) & use25)]; te = A[(A.yr == 2026) & (A.mon == m)]
        vec = TfidfVectorizer(token_pattern=TOKEN, ngram_range=(1, 2), min_df=5, max_features=4000, sublinear_tf=True)
        Xt, Xe = vec.fit_transform(tr.text), vec.transform(te.text); Dt, De = dense(tr), dense(te); mu, sd = Dt.mean(0), Dt.std(0) + 1e-9
        At = sparse.hstack([Xt, sparse.csr_matrix((Dt - mu) / sd)]).tocsr(); Ae = sparse.hstack([Xe, sparse.csr_matrix((De - mu) / sd)]).tocsr()
        A.loc[te.index, a] = Ridge(alpha=3.0).fit(At, tr[y]).predict(Ae)
    print("done", a, flush=True)
T6 = pd.read_parquet(os.path.join(SP, "band_v2/test_pct.parquet"))[["id", "set"]]; T6["id"] = T6.id.astype(str)
T = T6.merge(A[A.yr == 2026], on="id"); res = {"design": __doc__.split("\n    python")[0], "rows_2025": int((A.yr == 2025).sum()), "test_856": len(T)}
def boot(f, idx):
    v = f(idx); bs = [f(idx[rng.integers(0, len(idx), len(idx))]) for _ in range(2000)]; return [round(v, 3), round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3), len(idx)]
sp = lambda s, idx: spearmanr(T[s].to_numpy()[idx], -T["rank"].to_numpy()[idx]).correlation
def calib(col):
    tr = (T.set == "2026-09").to_numpy(); truth = T.y_pct.to_numpy(); score = T[col].to_numpy(); cov, wid = [], []
    for a_, b_ in ((tr, ~tr), (~tr, tr)):
        cuts = np.quantile(score[a_], np.linspace(0.1, 0.9, 9)); da, db = np.digitize(score[a_], cuts), np.digitize(score[b_], cuts)
        lo = {d: np.quantile(truth[a_][da == d], 0.1) for d in range(10)}; hi = {d: np.quantile(truth[a_][da == d], 0.9) for d in range(10)}
        for t, d in zip(truth[b_], db): cov.append(lo[d] <= t <= hi[d]); wid.append(hi[d] - lo[d])
    return {"coverage_80": round(float(np.mean(cov)) * 100, 1), "mean_width_pct_of_day": round(float(np.mean(wid)) * 100, 1)}
for sub, m in (("856", np.ones(len(T), bool)), ("fresh 130", (T.set == "fresh").to_numpy())):
    idx = np.flatnonzero(m); o = {a: boot(lambda ii, a=a: sp(a, ii), idx) for a in ARMS}
    for a in list(ARMS)[1:]: o[f"{a} - A0"] = boot(lambda ii, a=a: sp(a, ii) - sp("A0 2026 ln(votes) [current]", ii), idx)
    res[sub] = o
res["calibration (80% band, cross-fit)"] = {a: calib(a) for a in ARMS}
# part 2: beyond the clean 00:05 base
H = pd.read_parquet(os.path.join(SP, "honest_preds_v2.parquet"))[["id", "honest"]]; H["id"] = H.id.astype(str); B = A[(A.yr == 2026)].merge(H, on="id")
best = max(list(ARMS)[2:], key=lambda a: res["856"][a][0]); rk = lambda a: pd.Series(a).rank().to_numpy()
def partial(y, b, x):
    y, b, x = rk(y), rk(b), rk(x); return float(np.corrcoef(y - np.polyval(np.polyfit(b, y, 1), b), x - np.polyval(np.polyfit(b, x, 1), b))[0, 1])
z = lambda s: (s - s.mean()) / (s.std() or 1); p2 = {}
for a in ("A0 2026 ln(votes) [current]", best):
    G = B[B[a].notna()]; pc = np.array([partial(-g["rank"].to_numpy(), g.honest.to_numpy(), g[a].to_numpy()) for _, g in G.groupby("day") if len(g) >= 8])
    bs = [pc[rng.integers(0, len(pc), len(pc))].mean() for _ in range(2000)]; p2[f"partial beyond clean: {a}"] = [round(float(pc.mean()), 3), round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3), len(pc)]
G = B[B[best].notna() & B["A0 2026 ln(votes) [current]"].notna()].copy()
for c in ("honest", "A0 2026 ln(votes) [current]", best): G["z_" + c] = G.groupby("day")[c].transform(z)
G["yy"] = G.groupby("day")["rank"].transform(lambda r: z(-np.log(r))); gm = sorted(G.mon.unique())
for nm, X in (("clean + A0", ["z_honest", "z_A0 2026 ln(votes) [current]"]), (f"clean + {best}", ["z_honest", f"z_{best}"]), ("clean + A0 + best", ["z_honest", "z_A0 2026 ln(votes) [current]", f"z_{best}"])):
    G[nm] = np.nan
    for m in gm[1:]:
        tr, te = G[G.mon < m], G[G.mon == m]; G.loc[te.index, nm] = Ridge(alpha=10).fit(tr[X], tr.yy).predict(te[X])
def ov(g, col): o = g.sort_values(col, ascending=False).id.tolist(); t = g.sort_values("rank").id.tolist(); return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
Gt = G[G["clean + A0"].notna()]
for a, b in ((f"clean + {best}", "clean + A0"), ("clean + A0 + best", "clean + A0"), ("clean + A0", "z_honest")):
    d = np.array([np.array(ov(g, a)) - np.array(ov(g, b)) for _, g in Gt.groupby("day") if len(g) >= 10]); bs = np.array([d[rng.integers(0, len(d), len(d))].mean(0) for _ in range(2000)])
    p2[f"{a} - {b} top3/5/10"] = [[round(float(d[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(3)] + [len(d)]
res["part2 beyond clean"] = p2; res["best 2025 arm"] = best
B[["id", "day", "A0 2026 ln(votes) [current]", best]].to_parquet(os.path.join(OUT, "text_scores_2026.parquet"))
json.dump(res, open(os.path.join(OUT, "band_2025.json"), "w"), indent=1, default=float); print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=float))
