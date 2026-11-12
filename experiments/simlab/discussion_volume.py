"""How much discussion to expect (orchestrator 03:15Z Nov 12, item 2). Target per launch: number of non-team comments (threads
and replies) created in the first 24 h after 00:00 PT of the launch day, from the thread dumps (exact created_at; the page query
holds the top 50 threads by votes, so very busy launches are capped - counts are a lower bound there), and the share of those
comments that are questions (contains "?"). Launches = the comment-forecast days (>= 80% of the line-up in the dumps).
Predictors (00:05-known): the product-only score ('base', landing_retrieval) alone, and with the hunter + maker features of
landing_ladder (both rung). Ridge on ln(1 + comments) and on the question share, expanding month-forward (first two months
train). Metrics: Spearman overall and within day, calibrated 10-90% band of the comment count per predicted decile (deciles and
bands from earlier months) with coverage and width; day-bootstrap CIs; paired product-only vs both.
    python discussion_volume.py <cf dir (page*.jsonl.gz, cf_rows.parquet)> <launches dir> <landing_rows.parquet> <out dir>
"""
import glob, gzip, html, json, os, re, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge

CFD, LDIR, LROWS, OUT = sys.argv[1:5]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna() & L.votes.notna()].copy().sort_values(["day", "id"]).reset_index(drop=True)
L["id"] = L.id.astype(str); L["y"] = np.log1p(pd.to_numeric(L.votes, errors="coerce").astype(float)); L["rank"] = L.daily_rank.astype(float)
real = lambda u: bool(u) and not str(u).startswith("[")
L["mk"] = [[str(u).lower() for u in (json.loads(m) if isinstance(m, str) and m.startswith("[") else []) if real(u)] for m in L.makers]
L["hunter"] = L.poster.fillna("").str.lower(); L["team"] = [set(m) | ({h} if h else set()) for m, h in zip(L.mk, L.hunter)]
bys = {s: i for i, s in enumerate(L.slug)}
cnt, q = np.zeros(len(L)), np.zeros(len(L)); seen = set()
t0 = {i: pd.Timestamp(d + " 00:00", tz="America/Los_Angeles") for i, d in enumerate(L.day)}
for f in sorted(glob.glob(os.path.join(CFD, "page*.jsonl.gz"))):
    for line in gzip.open(f):
        x = json.loads(line)
        try: p_ = json.loads(x["html"])["data"]["post"]
        except Exception: continue
        if not p_ or p_.get("slug") not in bys: continue
        i = bys[p_["slug"]]
        def walk(n):
            cid = n.get("id"); u = ((n.get("user") or {}).get("username") or "").lower()
            if cid not in seen and u and u not in L.team.iat[i] and n.get("createdAt"):
                seen.add(cid); ts = pd.Timestamp(n["createdAt"])
                if t0[i] <= ts <= t0[i] + pd.Timedelta(hours=24):
                    cnt[i] += 1; q[i] += "?" in (n.get("bodyHtml") or "")
            for e in ((n.get("replies") or {}).get("edges") or []): walk(e["node"])
        for e in ((p_.get("threads") or {}).get("edges") or []): walk(e["node"])
L["n24"] = cnt; L["qshare"] = np.where(cnt > 0, q / np.maximum(cnt, 1), np.nan)
days = set(pd.read_parquet(os.path.join(CFD, "cf_rows.parquet")).day.unique())
B = pd.read_parquet(LROWS)[["id", "base"]]; B["id"] = B.id.astype(str)
D = L[L.day.isin(days)].merge(B, on="id", how="inner").reset_index(drop=True); D["mon"] = D.day.str[:7]
# hunter / maker features (history strictly before the day), as in landing_ladder
hist_h, hist_m = {}, {}
for r in L.itertuples():
    if r.hunter: hist_h.setdefault(r.hunter, []).append((r.day, r.y, r.rank))
    for m in r.mk: hist_m.setdefault(m, []).append((r.day, r.y, r.rank))
def hs(lst, d):
    v = [(y, k) for dd, y, k in lst if dd < d]
    if not v: return 0, np.nan, np.nan, np.nan
    ys, ks = np.array([a for a, _ in v]), np.array([b for _, b in v]); return len(v), (ks <= 3).mean(), (ks <= 10).mean(), ys.mean()
hh = [hs(hist_h.get(h, []), d) for h, d in zip(D.hunter, D.day)]
D["h_n"] = np.log1p([a[0] for a in hh]); D["h_top3"] = [a[1] for a in hh]; D["h_top10"] = [a[2] for a in hh]; D["h_ymean"] = [a[3] for a in hh]
# MASK=1 (Nov 12 leak fix): the launch's own makers as seen at 00:05 = its first named maker; m_count = total maker count
MASK = os.environ.get("MASK") == "1"
D["mk_own"] = [m[:1] for m in D.mk] if MASK else D.mk
D["n_total"] = [len(json.loads(m)) if isinstance(m, str) and m.startswith("[") else 0 for m in D.makers]
D["h_self"] = [float(h in set(m)) for h, m in zip(D.hunter, D.mk_own)]
mm = []
for ms, d in zip(D.mk_own, D.day):
    v = [x for m in ms for x in hist_m.get(m, []) if x[0] < d]
    mm.append((len(v), min([k for _, _, k in v]) if v else np.nan, np.mean([y for _, y, _ in v]) if v else np.nan, max([y for _, y, _ in v]) if v else np.nan))
D["m_count"] = D.n_total if MASK else D.mk.str.len(); D["m_prior"] = np.log1p([a[0] for a in mm]); D["m_best_rank"] = np.log1p([a[1] for a in mm]); D["m_ymean"] = [a[2] for a in mm]; D["m_ymax"] = [a[3] for a in mm]
for c in ("h_top3", "h_top10", "h_ymean", "m_best_rank", "m_ymean", "m_ymax"):
    D[c + "_na"] = D[c].isna().astype(float); D[c] = D[c].fillna(D[c].median())
SETS = {"product_only": ["base"], "hunter": ["base", "h_n", "h_top3", "h_top10", "h_ymean", "h_self", "h_top3_na"],
        "makers": ["base", "m_count", "m_prior", "m_best_rank", "m_ymean", "m_ymax", "m_best_rank_na"], "both": ["base", "h_n", "h_top3", "h_top10", "h_ymean", "h_self", "h_top3_na", "m_count", "m_prior", "m_best_rank", "m_ymean", "m_ymax", "m_best_rank_na"]}
D["ln24"] = np.log1p(D.n24); mons = sorted(D.mon.unique())
print("launches", len(D), "days", D.day.nunique(), "median comments 24h", D.n24.median(), "share zero", round(float((D.n24 == 0).mean()), 3), flush=True)


def fit(cols, target):
    p = pd.Series(np.nan, index=D.index)
    for m in mons[2:]:
        tr, te = D[(D.mon < m) & D[target].notna()], D[D.mon == m]
        mu, sd = tr[cols].mean(), tr[cols].std() + 1e-9; p[te.index] = Ridge(alpha=3.0).fit((tr[cols] - mu) / sd, tr[target]).predict((te[cols] - mu) / sd)
    return p


def boot(v, B=2000):
    v = np.asarray(v, float); v = v[~np.isnan(v)]; bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(B)]
    return [round(float(v.mean()), 3), round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3), int(len(v))]


res = {"design": __doc__.split("\n    python")[0], "launches": int(len(D)), "days": int(D.day.nunique()),
       "comments_24h": {"median": float(D.n24.median()), "p10_p90": [float(x) for x in np.percentile(D.n24, [10, 90])], "share_zero": round(float((D.n24 == 0).mean()), 3)},
       "question_share": {"mean": round(float(D.qshare.mean()), 3)}, "volume": {}, "question_share_model": {}}
WD = {}
for nm, cols in SETS.items():
    D[f"p_{nm}"] = fit(cols, "ln24"); T = D[D[f"p_{nm}"].notna()]
    wd = T.groupby("day").apply(lambda g: spearmanr(g[f"p_{nm}"], g.n24).correlation if len(g) >= 8 and g.n24.nunique() > 1 else np.nan); WD[nm] = wd
    cov, w, n = 0, [], 0
    for m in mons[3:]:
        tr, te = T[T.mon < m], T[T.mon == m]
        cuts = np.percentile(tr[f"p_{nm}"], np.arange(10, 100, 10)); dt, de = np.searchsorted(cuts, tr[f"p_{nm}"]), np.searchsorted(cuts, te[f"p_{nm}"])
        lo = {k: np.percentile(tr.n24[dt == k], 10) for k in range(10)}; hi = {k: np.percentile(tr.n24[dt == k], 90) for k in range(10)}
        for k, v in zip(de, te.n24): cov += lo[k] <= v <= hi[k]; w.append(hi[k] - lo[k]); n += 1
    bands = None
    cuts = np.percentile(T[f"p_{nm}"], np.arange(10, 100, 10)); dt = np.searchsorted(cuts, T[f"p_{nm}"])
    bands = [{"decile": k, "comments_p10_p50_p90": [float(x) for x in np.percentile(T.n24[dt == k], [10, 50, 90])]} for k in range(10)]
    res["volume"][nm] = {"spearman_overall": round(float(spearmanr(T[f"p_{nm}"], T.n24).correlation), 3), "within_day_spearman": boot(wd.values),
                         "band_coverage": round(cov / n, 3), "band_mean_width_comments": round(float(np.mean(w)), 1), "bands_by_decile": bands}
    D[f"q_{nm}"] = fit(cols, "qshare"); Tq = D[D[f"q_{nm}"].notna() & D.qshare.notna() & (D.n24 >= 5)]
    res["question_share_model"][nm] = {"spearman": round(float(spearmanr(Tq[f"q_{nm}"], Tq.qshare).correlation), 3), "n": int(len(Tq))}
j = WD["both"].dropna().index.intersection(WD["product_only"].dropna().index)
res["volume"]["both - product_only within-day spearman (paired)"] = boot((WD["both"][j] - WD["product_only"][j]).values)
json.dump(res, open(os.path.join(OUT, "discussion_volume.json"), "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1, default=str)[:3500])
