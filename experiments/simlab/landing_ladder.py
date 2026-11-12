"""What is each optional input worth to "where it would land"? (orchestrator 02:45Z Nov 12)
Base = the product-only ridge's month-forward score (landing_retrieval.py 'base', the web_launch_band design). Blocks (all
known at 00:05, computed from held data strictly before the launch day):
  CAL     day of week, line-up size (featured launches that day)                      visitor enters: launch date
  HUNTER  hunter's past hunts (count), past top-3 / top-10 rate, mean ln votes of past hunts; self-hunted flag
                                                                                        visitor enters: hunter's PH profile
  MAKERS  number of real makers, makers' prior launches (count), best prior rank, mean / max ln votes of prior launches
                                                                                        visitor enters: makers' PH profiles
  TIES    complete-pool people who upvoted any earlier launch of the team (log count) - "the team's earlier voters"
                                                                                        visitor enters: makers' PH profiles
  FULL    the honest full launch model (its prediction as a feature)                    visitor enters: everything above + more
Ladder (cumulative) and each block alone on top of the base; ridge on ln(1+votes), expanding month-forward (first test month
has two earlier training months). Per day (>= 10 launches): within-day Spearman with -rank, top 3/5/10 overlap; paired by day
vs the base, 2000 day-bootstrap draws. Band: deciles of the score and the 10th-90th percentile of final daily rank per decile,
both from earlier months; reported: mean band width (ranks) and coverage of the true rank.
    python landing_ladder.py <launches dir> <landing out dir (landing_rows.parquet)> <honest_preds.parquet> <v3 dir> <out dir>
"""
import glob, json, os, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge

LDIR, LAND, HON, V3, OUT = sys.argv[1:6]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna() & L.votes.notna() & (L.day < "2026-11-11")].copy().sort_values(["day", "id"]).reset_index(drop=True)
L["id"] = L.id.astype(str); L["y"] = np.log1p(pd.to_numeric(L.votes, errors="coerce").astype(float)); L["rank"] = L.daily_rank.astype(float)
real = lambda u: bool(u) and not str(u).startswith("[")
L["mk"] = [[str(u).lower() for u in (json.loads(m) if isinstance(m, str) and m.startswith("[") else []) if real(u)] for m in L.makers]
L["hunter"] = L.poster.fillna("").str.lower(); L["team"] = [set(m) | ({h} if h else set()) for m, h in zip(L.mk, L.hunter)]
L = L.merge(pd.read_parquet(os.path.join(LAND, "landing_rows.parquet"))[["id", "base"]].assign(id=lambda d: d.id.astype(str)), on="id", how="left")
H = pd.read_parquet(HON)[["id", "honest"]]; H["id"] = H.id.astype(str); L = L.merge(H, on="id", how="left")
L["mon"] = L.day.str[:7]; L["dow"] = pd.to_datetime(L.day).dt.dayofweek; L["lineup"] = L.groupby("day").id.transform("size")
for k in range(7): L[f"dow{k}"] = (L.dow == k).astype(float)
L["llineup"] = np.log(L.lineup)
# hunter and maker history (launches strictly before the day)
hist_h, hist_m = {}, {}
for r in L.itertuples():
    if r.hunter: hist_h.setdefault(r.hunter, []).append((r.day, r.y, r.rank))
    for m in r.mk: hist_m.setdefault(m, []).append((r.day, r.y, r.rank))
def hstats(lst, d):
    v = [(y, k) for dd, y, k in lst if dd < d]
    if not v: return 0, np.nan, np.nan, np.nan, np.nan
    ys, ks = np.array([a for a, _ in v]), np.array([b for _, b in v])
    return len(v), (ks <= 3).mean(), (ks <= 10).mean(), ys.mean(), ys.max()
hh = [hstats(hist_h.get(h, []), d) for h, d in zip(L.hunter, L.day)]
L["h_n"] = np.log1p([a[0] for a in hh]); L["h_top3"] = [a[1] for a in hh]; L["h_top10"] = [a[2] for a in hh]; L["h_ymean"] = [a[3] for a in hh]
L["h_self"] = [float(h in set(m)) for h, m in zip(L.hunter, L.mk)]
mm = []
for ms, d in zip(L.mk, L.day):
    v = [x for m in ms for x in hist_m.get(m, []) if x[0] < d]
    mm.append((len(v), min([k for _, _, k in v]) if v else np.nan, np.mean([y for _, y, _ in v]) if v else np.nan, max([y for _, y, _ in v]) if v else np.nan))
L["m_count"] = L.mk.str.len(); L["m_prior"] = np.log1p([a[0] for a in mm]); L["m_best_rank"] = np.log1p([a[1] for a in mm]); L["m_ymean"] = [a[2] for a in mm]; L["m_ymax"] = [a[3] for a in mm]
# team's earlier voters in the complete pool
comp = set(pd.read_parquet(os.path.join(V3, "persons.parquet")).query("complete").person_id)
ev = pd.read_parquet(os.path.join(V3, "events.parquet"), columns=["person_id", "kind", "target_id"]).query("kind == 'upvote'")
ev = ev[ev.person_id.isin(comp)]; ev["target_id"] = ev.target_id.astype(str)
vot = ev.groupby("target_id").person_id.apply(set).to_dict()
by_member = {}
for i, d, t in zip(L.id, L.day, L.team):
    for m in t: by_member.setdefault(m, []).append((d, i))
L["ties"] = [np.log1p(len(set().union(*[vot.get(j, set()) for m in t for dd, j in by_member.get(m, []) if dd < d] or [set()]))) for t, d in zip(L.team, L.day)]
for c in ("h_top3", "h_top10", "h_ymean", "m_best_rank", "m_ymean", "m_ymax"):
    L[c + "_na"] = L[c].isna().astype(float); L[c] = L[c].fillna(L[c].median())
BLOCKS = {"CAL": [f"dow{k}" for k in range(7)] + ["llineup"], "HUNTER": ["h_n", "h_top3", "h_top10", "h_ymean", "h_self", "h_top3_na", "h_ymean_na"],
          "MAKERS": ["m_count", "m_prior", "m_best_rank", "m_ymean", "m_ymax", "m_best_rank_na", "m_ymean_na"], "TIES": ["ties"], "FULL": ["honest"]}
D = L[L.base.notna() & L.honest.notna()].copy(); mons = sorted(D.mon.unique())
print("launches", len(D), "months", mons, flush=True)


def fit(cols):
    pred = pd.Series(np.nan, index=D.index)
    for m in mons[2:]:
        tr, te = D[D.mon < m], D[D.mon == m]
        mu, sd = tr[cols].mean(), tr[cols].std() + 1e-9
        pred[te.index] = Ridge(alpha=3.0).fit((tr[cols] - mu) / sd, tr.y).predict((te[cols] - mu) / sd)
    return pred


def per_day(col):
    out = {}
    for d, g in D[D[col].notna()].groupby("day"):
        if len(g) >= 10:
            out[d] = [spearmanr(g[col], -g["rank"]).correlation * 100] + [len(set(g.nlargest(k, col).id) & set(g.nsmallest(k, "rank").id)) / k * 100 for k in (3, 5, 10)]
    return pd.DataFrame(out, index=["spearman", "top3", "top5", "top10"]).T


def band(col):
    w, cov, n = [], 0, 0
    for m in mons[3:]:
        tr, te = D[(D.mon < m) & D[col].notna()], D[(D.mon == m) & D[col].notna()]
        cuts = np.percentile(tr[col], np.arange(10, 100, 10)); dt, de = np.searchsorted(cuts, tr[col]), np.searchsorted(cuts, te[col])
        lo = {q: np.percentile(tr["rank"][dt == q], 10) for q in range(10)}; hi = {q: np.percentile(tr["rank"][dt == q], 90) for q in range(10)}
        for q, r in zip(de, te["rank"]): w.append(hi[q] - lo[q]); cov += lo[q] <= r <= hi[q]; n += 1
    return {"mean_width_ranks": round(float(np.mean(w)), 1), "coverage": round(cov / n, 3)}


def boot(v, B=2000):
    v = np.asarray(v, float); bs = np.array([v[rng.integers(0, len(v), len(v))].mean(0) for _ in range(B)])
    return {c: [round(float(v[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j, c in enumerate(["spearman", "top3", "top5", "top10"])}


D["s_base"] = fit(["base"]); B0 = per_day("s_base")
res = {"design": __doc__.split("\n    python")[0], "launches": int(len(D)), "test_days": int(len(B0)), "test_months": mons[2:], "ladder": {}, "alone": {}}
res["ladder"]["0 product-only"] = {**boot(B0.values), "band": band("s_base")}
cum = ["base"]
for i, b in enumerate(BLOCKS, 1):
    cum = cum + BLOCKS[b]; c = f"s_cum{i}"; D[c] = fit(cum); P_ = per_day(c); j = P_.index.intersection(B0.index)
    res["ladder"][f"{i} + {b}"] = {**boot(P_.loc[j].values), "minus product-only (paired)": boot((P_.loc[j] - B0.loc[j]).values), "band": band(c)}
    print("ladder", b, res["ladder"][f"{i} + {b}"]["top3"], flush=True)
for b, cols in BLOCKS.items():
    c = f"s_alone_{b}"; D[c] = fit(["base"] + cols); P_ = per_day(c); j = P_.index.intersection(B0.index)
    res["alone"][f"product-only + {b}"] = {**boot(P_.loc[j].values), "minus product-only (paired)": boot((P_.loc[j] - B0.loc[j]).values), "band": band(c)}
D["s_lm"] = D.honest; res["full LM alone (reference)"] = {**boot(per_day("s_lm").loc[B0.index.intersection(per_day("s_lm").index)].values), "band": band("s_lm")}
res["inputs"] = {"CAL": "launch date (we know the day's line-up size only on the day; before that, a typical size)",
                 "HUNTER": "the hunter's Product Hunt profile (we compute past hunts and hit rate from held launch data)",
                 "MAKERS": "the makers' Product Hunt profiles (prior launches and their votes/ranks from held launch data)",
                 "TIES": "the makers' profiles (we count pool members who upvoted their earlier launches); a visitor cannot type this number reliably",
                 "FULL": "all of the above plus the launch-model inputs (team followers, page facts) - not practical on /try"}
json.dump(res, open(os.path.join(OUT, "landing_ladder.json"), "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1, default=str)[:5000])
