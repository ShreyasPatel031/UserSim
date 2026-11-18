"""Cold-start launches (orchestrator 07:15Z Nov 11): does the user sim's product understanding rank launches the LM is
blind to? Cold-start = no prior PH launch by the hunter or any maker (LM cache hist_hunter_n == hist_maker_n == 0).
Days Oct 20 - Nov 8 with final ranks.
(1) Launch level, within day AMONG cold-start launches only, scorers:
    it9b   product-only browser EV (rows_tl_cp_attr_noctx: sum w*p)
    it8    it8 product-only EV (rows_tl_cp_choice2_noctx: sum w*p)
    lm     the LM at 00:05: honest backtest score (Oct 20-24) / live forecast -log(predicted rank) (Oct 25+)
    fol    honest 00:05 PH follower counts (at_launch_followers read <= 20 min after 00:00 PT): log1p(makers sum + hunter)
  Spearman vs final votes (days with >= 4 cold-start launches); recall of the cold-start launches that made the real top
  10 (per day m = # cold-start in real top 10; the scorer's top m among cold-start launches; pooled hits / pooled m).
  Bootstrap over days; paired vs lm on common days.
(2) Person level: label-filtered people who voted for a cold-start launch on d: rank of that launch by the person's
  product-only p among the person's line-up rows: Hit@1, Hit@3, AUC (share of the person's non-voted launches below it),
  vs the same for their votes on launches WITH team history, and the random baseline.
usage: SIMBT=<dir> python coldstart_sim.py -> results/coldstart_sim.json"""
import glob, json, os, pickle, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
WORK = os.environ["SIMBT"]; S_ = os.path.dirname(WORK)
D0, D1 = "2026-10-20", "2026-11-08"


def main():
    from pipeline import warehouse as W
    import two_level as T
    ok, _ = T._label_maps()
    L = W.query(f"SELECT CAST(id AS VARCHAR) AS id, day::VARCHAR AS day, daily_rank, votes FROM launches WHERE daily_rank IS NOT NULL AND day BETWEEN '{D0}' AND '{D1}'", do_sync=False)
    df = pickle.load(open(f"{S_}/lm/build_cache_gemini.pkl", "rb")); df["id"] = df.id.astype(str); df = df.set_index("id")
    L["cold"] = L.id.map((df.hist_hunter_n.fillna(0) == 0) & (df.hist_maker_n.fillna(0) == 0))
    L = L[L.cold.notna()].copy(); L["cold"] = L.cold.astype(bool)
    # scorers
    sc = {}
    for nm, src in (("it9b", "rows_tl_cp_attr_noctx"), ("it8", "rows_tl_cp_choice2_noctx")):
        ev = {}
        for f in glob.glob(f"{WORK}/{src}/2026-*.parquet"):
            d = os.path.basename(f)[:10]
            if not (D0 <= d <= D1) or "_" in os.path.basename(f)[10:].replace(".parquet", ""):
                continue
            X = pd.read_parquet(f, columns=["id", "w", "p"]); X["id"] = X.id.astype(str)
            ev.update((X.w * X.p).groupby(X.id).sum().to_dict())
        sc[nm] = ev
    H = pd.read_parquet(f"{S_}/e5h/honest_preds.parquet"); H["id"] = H.id.astype(str)
    lm = dict(zip(H.id, H.honest.astype(float)))
    Fc = W.query("SELECT CAST(launch_id AS VARCHAR) AS id, predicted_rank FROM forecasts WHERE model = 'launch_model'", do_sync=False)
    lm.update({r.id: -float(np.log(r.predicted_rank)) for r in Fc.itertuples()})
    sc["lm"] = lm
    A = W.query("SELECT launch_id::VARCHAR AS id, day, role, ph_followers, read_at FROM at_launch_followers")
    rd = A.groupby("day").read_at.max()
    okd = {d for d, r in rd.items() if 0 <= (pd.Timestamp(r).tz_convert("America/Los_Angeles") - pd.Timestamp(d).tz_localize("America/Los_Angeles")).total_seconds() / 60 <= 20}
    A = A[A.day.isin(okd)]
    sc["fol"] = np.log1p(A.groupby("id").ph_followers.sum()).to_dict()
    names = list(sc)
    for nm in names:
        L[nm] = L.id.map(sc[nm])
    C = L[L.cold]
    rng = np.random.default_rng(0)
    per = []
    for d, g in C.groupby("day"):
        m = int((g.daily_rank <= 10).sum())
        row = {"day": d, "cold_n": len(g), "cold_in_top10": m, "lineup": int((L.day == d).sum())}
        for nm in names:
            h = g.dropna(subset=[nm])
            row[f"{nm}_cov"] = len(h) / len(g)
            if len(h) < len(g) * 0.8:       # scorer missing on this day's cold-start launches
                row[f"{nm}_sp"] = np.nan; row[f"{nm}_hit"] = np.nan; continue
            gg = g.assign(s=g[nm].fillna(g[nm].min() - 1))
            row[f"{nm}_sp"] = spearmanr(gg.s, gg.votes).correlation if len(g) >= 4 else np.nan
            row[f"{nm}_hit"] = len(set(gg.nlargest(m, "s").id) & set(gg[gg.daily_rank <= 10].id)) if m else np.nan
            row[f"{nm}_m"] = m
        per.append(row)
    P = pd.DataFrame(per)

    def bmean(x, r=3):
        x = np.asarray(x, float); x = x[~np.isnan(x)]
        if len(x) < 2: return [None, None, None, int(len(x))]
        return [round(float(x.mean()), r)] + [round(float(v), r) for v in np.percentile([x[rng.integers(0, len(x), len(x))].mean() for _ in range(5000)], [2.5, 97.5])] + [int(len(x))]

    def brecall(h, m):
        h = np.asarray(h, float); m = np.asarray(m, float); k = ~np.isnan(h) & (m > 0); h, m = h[k], m[k]
        if not len(h): return [None, None, None, 0, 0]
        bs = []
        for _ in range(5000):
            i = rng.integers(0, len(h), len(h)); bs.append(h[i].sum() / m[i].sum())
        return [round(float(h.sum() / m.sum()), 3)] + [round(float(v), 3) for v in np.percentile(bs, [2.5, 97.5])] + [int(h.sum()), int(m.sum())]
    res = {"cold_launches": int(len(C)), "cold_in_real_top10": int((C.daily_rank <= 10).sum()), "days": int(C.day.nunique()),
           "fol_days": sorted(okd & set(C.day)), "launch_level": {}}
    for nm in names:
        res["launch_level"][nm] = {"spearman": bmean(P[f"{nm}_sp"]), "recall_top10_cold": brecall(P[f"{nm}_hit"], P.get(f"{nm}_m", P.cold_in_top10)),
                                   "days_scored": int(P[f"{nm}_sp"].notna().sum())}
    for nm in ("it9b", "it8", "fol"):
        Q = P.dropna(subset=[f"{nm}_sp", "lm_sp"])
        res["launch_level"][f"{nm} - lm (paired days)"] = {"spearman": bmean(Q[f"{nm}_sp"] - Q.lm_sp),
                                                          "recall_top10_cold": [brecall(Q[f"{nm}_hit"], Q[f"{nm}_m"])[0], brecall(Q.lm_hit, Q.lm_m)[0], int(len(Q))]}
    # random baseline for recall
    exp = sum((m * m / n) for m, n in zip(P.cold_in_top10, P.cold_n) if n) / max(1, P.cold_in_top10.sum())
    res["launch_level"]["random_recall_expected"] = round(float(exp), 3)
    # (2) person level
    cold = set(C.id); warm = set(L[~L.cold].id); pr = {}
    for nm, src in (("it9b", "rows_tl_cp_attr_noctx"), ("it8", "rows_tl_cp_choice2_noctx")):
        rows = []
        for f in sorted(glob.glob(f"{WORK}/{src}/2026-*.parquet")):
            d = os.path.basename(f)[:10]
            if not (D0 <= d <= D1) or not os.path.basename(f).endswith(f"{d}.parquet"):
                continue
            X = pd.read_parquet(f, columns=["person", "id", "p", "y"]); X["id"] = X.id.astype(str)
            X = X[ok(X.person, d)]
            X["p"] = X.p + rng.random(len(X)) * 1e-12
            X["rk"] = X.groupby("person").p.rank(ascending=False, method="first"); X["n"] = X.groupby("person").p.transform("size")
            neg = X[X.y == 0]
            V = X[X.y == 1]
            below = V.merge(neg[["person", "p"]], on="person", suffixes=("", "_n"))
            auc = (below.p_n < below.p).groupby([below.person, below.id]).mean()
            V = V.set_index(["person", "id"]).assign(auc=auc).reset_index()
            V["kind"] = np.where(V.id.isin(cold), "cold", np.where(V.id.isin(warm), "warm", "other"))
            V["nvoted"] = V.groupby("person").y.transform("size")
            rows.append(V[["person", "id", "kind", "rk", "n", "auc", "nvoted"]].assign(day=d))
        R = pd.concat(rows)
        out = {}
        for kd in ("cold", "warm"):
            g = R[R.kind == kd]
            out[kd] = {"votes": int(len(g)), "hit1": bmean((g.rk <= 1).astype(float)), "hit3": bmean((g.rk <= 3).astype(float)),
                       "auc": bmean(g.auc), "random_hit1": round(float((1 / g.n).mean()), 3), "random_hit3": round(float((3 / g.n).clip(upper=1).mean()), 3)}
        pr[nm] = out
    res["person_level"] = pr
    res["per_day"] = P.round(3).to_dict("records")
    json.dump(res, open(os.path.join(HERE, "results", "coldstart_sim.json"), "w"), indent=1, default=float)
    print(json.dumps({k: v for k, v in res.items() if k != "per_day"}, indent=1, default=float))


if __name__ == "__main__":
    main()
