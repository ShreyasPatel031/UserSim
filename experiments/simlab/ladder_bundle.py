"""Site lookup for "where it would land" with optional hunter / makers (orchestrator 03:00Z Nov 12).
Bundle (bucket only): key = sha256("ph-ladder-v1:" + lowercase PH handle).hexdigest()[:20] -> aggregate launch stats as of a
date: hunted {n, n_top3, n_top10, sum_lnv}, made {n, best_rank, sum_lnv, max_lnv}. Only public launch outcomes; no names.
Model JSON (plain, like launch_band.json): for each rung (product_only, hunter, makers, both) the feature list, medians for
missing values, standardisation mean/sd, ridge coefficients/intercept on ln(1+votes), and the calibrated band table (deciles of
the rung score -> final daily rank p10/p50/p90, from month-forward held-out scores). Feature recipe (same as landing_ladder):
  base     the product-only score (launch_band.json recipe on the site; here the month-forward product-only ridge)
  hunter   h_n = ln(1+hunts), h_top3 = top-3 share, h_top10 = top-10 share, h_ymean = mean ln votes of hunts (median if none),
           h_self = hunter is one of the makers, h_top3_na / h_ymean_na = no earlier hunts
  makers   m_count = number of makers, m_prior = ln(1 + sum of makers' earlier launches), m_best_rank = ln(1 + best earlier rank),
           m_ymean = sum ln votes / launches, m_ymax = max ln votes (medians if none), m_best_rank_na / m_ymean_na
Validation: bundle and models built AS OF 2026-10-24 (training launches <= Oct 24); every ranked launch Oct 25 - Nov 10 scored
through the bundle path (hash the real handles, look up, compute features, apply the JSON ridge); per-day top 3/5/10 and
Spearman for each rung, band coverage; plus a 50-launch end-to-end check that bundle features equal the direct computation.
Production bundle + JSON built as of the latest day.
    python ladder_bundle.py <launches dir> <landing_rows.parquet> <out dir>
"""
import glob, hashlib, json, os, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge

LDIR, LROWS, OUT = sys.argv[1:4]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
key = lambda h: hashlib.sha256(("ph-ladder-v1:" + str(h).lower()).encode()).hexdigest()[:20]
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna() & L.votes.notna()].copy().sort_values(["day", "id"]).reset_index(drop=True)
L["id"] = L.id.astype(str); L["y"] = np.log1p(pd.to_numeric(L.votes, errors="coerce").astype(float)); L["rank"] = L.daily_rank.astype(float)
real = lambda u: bool(u) and not str(u).startswith("[")
L["mk"] = [[str(u).lower() for u in (json.loads(m) if isinstance(m, str) and m.startswith("[") else []) if real(u)] for m in L.makers]
L["hunter"] = L.poster.fillna("").str.lower()
B = pd.read_parquet(LROWS)[["id", "base"]]; B["id"] = B.id.astype(str); L = L.merge(B, on="id", how="left"); L["mon"] = L.day.str[:7]


def build_bundle(asof):
    """aggregate stats per handle from launches with day <= asof (completed days)"""
    H = L[L.day <= asof]; bund = {}
    for r in H.itertuples():
        if r.hunter:
            b = bund.setdefault(key(r.hunter), {"h": [0, 0, 0, 0.0], "m": [0, 9999, 0.0, 0.0]})
            b["h"][0] += 1; b["h"][1] += r.rank <= 3; b["h"][2] += r.rank <= 10; b["h"][3] += r.y
        for m in r.mk:
            b = bund.setdefault(key(m), {"h": [0, 0, 0, 0.0], "m": [0, 9999, 0.0, 0.0]})
            b["m"][0] += 1; b["m"][1] = min(b["m"][1], r.rank); b["m"][2] += r.y; b["m"][3] = max(b["m"][3], r.y)
    return bund


# MASK=1 (Nov 12 leak fix, v2 outputs): PH names the day #1's makers only after the day ends, so the launch's own maker list
# is the 00:05 view - its first named maker - and m_count = the TOTAL number of makers (named or not). On the site the visitor
# enters the hunter, ONE (main) maker and the number of makers. Earlier launches in the bundle keep their full named teams.
MASK = os.environ.get("MASK") == "1"; VER = "v2" if MASK else "v1"
L["n_total"] = [len(json.loads(m)) if isinstance(m, str) and m.startswith("[") else 0 for m in L.makers]
L["mk_own"] = [m[:1] for m in L.mk] if MASK else L.mk


def feats_from_bundle(bund, hunter, makers, n_total=None):
    """what the site computes from the visitor's entries (handles) -> raw features with NaN for missing"""
    hb = bund.get(key(hunter), {"h": [0, 0, 0, 0.0]})["h"] if hunter else [0, 0, 0, 0.0]
    f = {"h_n": np.log1p(hb[0]), "h_top3": hb[1] / hb[0] if hb[0] else np.nan, "h_top10": hb[2] / hb[0] if hb[0] else np.nan,
         "h_ymean": hb[3] / hb[0] if hb[0] else np.nan, "h_self": float(bool(hunter) and hunter.lower() in {m.lower() for m in makers})}
    ms = [bund.get(key(m), {"m": [0, 9999, 0.0, 0.0]})["m"] for m in makers]
    n = sum(a[0] for a in ms); best = min([a[1] for a in ms] or [9999])
    f.update({"m_count": float(n_total if (MASK and n_total is not None) else len(makers)), "m_prior": np.log1p(n), "m_best_rank": np.log1p(best) if n else np.nan,
              "m_ymean": sum(a[2] for a in ms) / n if n else np.nan, "m_ymax": max([a[3] for a in ms if a[0]] or [np.nan])})
    return f


NA = ["h_top3", "h_top10", "h_ymean", "m_best_rank", "m_ymean", "m_ymax"]
RUNGS = {"product_only": ["base"], "hunter": ["base", "h_n", "h_top3", "h_top10", "h_ymean", "h_self", "h_top3_na", "h_ymean_na"],
         "makers": ["base", "m_count", "m_prior", "m_best_rank", "m_ymean", "m_ymax", "m_best_rank_na", "m_ymean_na"]}
RUNGS["both"] = sorted(set(RUNGS["hunter"]) | set(RUNGS["makers"]), key=lambda c: (c != "base", c))


def feature_table(df):
    """features for each launch from history strictly before its day (via a bundle as of the previous day)"""
    rows = []
    for d, g in df.groupby("day"):
        bund = build_bundle((pd.Timestamp(d) - pd.Timedelta(days=1)).strftime("%Y-%m-%d"))
        for r in g.itertuples(): rows.append({"id": r.id, **feats_from_bundle(bund, r.hunter, r.mk_own, r.n_total)})
    return df.merge(pd.DataFrame(rows), on="id")


def finish(F, med):
    F = F.copy()
    for c in NA: F[c + "_na"] = F[c].isna().astype(float); F[c] = F[c].fillna(med[c])
    return F


def fit_export(T, asof):
    """month-forward held-out scores for bands, final fit on all of T -> JSON"""
    med = {c: float(T[c].median()) for c in NA}; T = finish(T, med); out = {"version": "ph-ladder-v2-masked" if MASK else "ph-ladder-v1", "as_of": asof,
           "inputs": ("hunter handle; ONE main maker handle; total number of makers (m_count)" if MASK else "hunter handle; maker handles"), "key": "sha256('ph-ladder-v1:' + lowercase handle)[:20]", "medians": med, "rungs": {}}
    mons = sorted(T.mon.unique())
    for nm, cols in RUNGS.items():
        T[f"oof_{nm}"] = np.nan
        for m in mons[2:]:
            tr, te = T[T.mon < m], T[T.mon == m]; mu, sd = tr[cols].mean(), tr[cols].std() + 1e-9
            T.loc[te.index, f"oof_{nm}"] = Ridge(alpha=3.0).fit((tr[cols] - mu) / sd, tr.y).predict((te[cols] - mu) / sd)
        H = T[T[f"oof_{nm}"].notna()]; cuts = np.percentile(H[f"oof_{nm}"], np.arange(10, 100, 10)); dec = np.searchsorted(cuts, H[f"oof_{nm}"])
        band = [{"decile": q, "rank_p10_p50_p90": [float(x) for x in np.percentile(H["rank"][dec == q], [10, 50, 90])], "n": int((dec == q).sum())} for q in range(10)]
        mu, sd = T[cols].mean(), T[cols].std() + 1e-9; rg = Ridge(alpha=3.0).fit((T[cols] - mu) / sd, T.y)
        out["rungs"][nm] = {"features": cols, "mean": [float(x) for x in mu], "sd": [float(x) for x in sd], "coef": [float(x) for x in rg.coef_],
                            "intercept": float(rg.intercept_), "score_decile_cuts": [float(x) for x in cuts], "bands": band}
    return out


def score(model, F):
    med = model["medians"]; F = finish(F, med); res = {}
    for nm, r in model["rungs"].items():
        X = (F[r["features"]].to_numpy() - np.array(r["mean"])) / np.array(r["sd"]); s = X @ np.array(r["coef"]) + r["intercept"]
        dec = np.searchsorted(np.array(r["score_decile_cuts"]), s); bands = {b["decile"]: b["rank_p10_p50_p90"] for b in r["bands"]}
        res[nm] = (s, [bands[q] for q in dec])
    return res


# ---------- validation: as of Oct 24
TR = L[(L.day <= "2026-10-24") & L.base.notna()]; VA = L[(L.day >= "2026-10-25") & (L.day <= "2026-11-10") & L.base.notna()]
print("train", len(TR), "validation launches", len(VA), "days", VA.day.nunique(), flush=True)
FT = feature_table(TR); M_val = fit_export(FT, "2026-10-24")
bund_val = build_bundle("2026-10-24")
FV = VA.merge(pd.DataFrame([{"id": r.id, **feats_from_bundle(bund_val, r.hunter, r.mk_own, r.n_total)} for r in VA.itertuples()]), on="id")   # visitor path: bundle as of Oct 24
SV = score(M_val, FV)
res = {"design": __doc__.split("\n    python")[0], "validation": {"launches": int(len(FV)), "days": int(FV.day.nunique())}}
for nm, (s, bands) in SV.items():
    FV[f"s_{nm}"] = s; FV[f"lo_{nm}"] = [b[0] for b in bands]; FV[f"hi_{nm}"] = [b[2] for b in bands]
for nm in RUNGS:
    per = []
    for d, g in FV.groupby("day"):
        if len(g) >= 10:
            per.append([spearmanr(g[f"s_{nm}"], -g["rank"]).correlation * 100] + [len(set(g.nlargest(k, f"s_{nm}").id) & set(g.nsmallest(k, "rank").id)) / k * 100 for k in (3, 5, 10)])
    per = np.array(per); bs = np.array([per[rng.integers(0, len(per), len(per))].mean(0) for _ in range(2000)])
    cov = float(((FV["rank"] >= FV[f"lo_{nm}"]) & (FV["rank"] <= FV[f"hi_{nm}"])).mean()); width = float((FV[f"hi_{nm}"] - FV[f"lo_{nm}"]).mean())
    res["validation"][nm] = {k: [round(float(per[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j, k in enumerate(["spearman", "top3", "top5", "top10"])} \
        | {"band_coverage": round(cov, 3), "band_width": round(width, 1), "days": int(len(per))}
# 50-launch end-to-end check: bundle path == direct computation (history <= Oct 24 for both)
samp = FV.sample(min(50, len(FV)), random_state=0); direct = []
for r in samp.itertuples():
    hist = L[L.day <= "2026-10-24"]; hn = hist[hist.hunter == r.hunter] if r.hunter else hist.iloc[:0]
    mk_hist = hist[[bool(set(m) & set(r.mk_own)) for m in hist.mk]]
    direct.append(abs(np.log1p(len(hn)) - r.h_n) + abs(np.log1p(sum(sum(1 for m in mm if m in r.mk_own) for mm in mk_hist.mk)) - r.m_prior))
res["validation"]["end_to_end_50_max_feature_diff"] = round(float(max(direct)), 6)
# ---------- production: as of the latest completed day
asof = L.day.max(); FP = feature_table(L[L.base.notna()]); M_prod = fit_export(FP, asof); bund = build_bundle(asof)
json.dump(M_prod, open(os.path.join(OUT, f"ladder_model_{VER}.json"), "w")); json.dump(bund, open(os.path.join(OUT, f"ladder_handles_{VER}.json"), "w"))
res["production"] = {"as_of": asof, "handles": len(bund), "model_bytes": os.path.getsize(os.path.join(OUT, f"ladder_model_{VER}.json")), "bundle_bytes": os.path.getsize(os.path.join(OUT, f"ladder_handles_{VER}.json"))}
json.dump(res, open(os.path.join(OUT, f"ladder_bundle_{VER}.json"), "w"), indent=1)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1))
