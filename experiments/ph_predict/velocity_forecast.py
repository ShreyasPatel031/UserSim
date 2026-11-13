"""Post-reveal velocity forecast (orchestrator 19:25Z Nov 13). Warehouse hourly vote_snapshots (launch-day reads only; snapshots stamped
<= h). At h in {04, 05, 06, 08, 10, 12} PT predict the final dailyRank order from: votes at h, gain in the last 1 h and 2 h, comments at h and
their 1 h gain, launch hour (hours_since_start), clean_nosite score (00:05 shadow, prior), weekday.
  (i)  plain vote order at h (baseline)
  (ii) readable extrapolation: final = votes_h x M(h) x (1 + b * relative 1 h velocity), M(h) the pooled median growth multiplier
       (final votes / votes at h) from earlier days, b fit on earlier days by grid search (walk-forward by day)
  (iii) small GBM on the same inputs (log target), earlier days only
Label: dailyRank. Metric: top 3/5/10 per day, paired diff vs (i), day bootstrap. usage: python velocity_forecast.py -> results/velocity_forecast.md"""
import os, sys, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
from pipeline import warehouse as W
import lightgbm as lgb
HS = [4, 5, 6, 8, 10, 12]


def main():
    V = W.query('SELECT "day", "at", CAST(launch_id AS VARCHAR) id, votes, comments, hours_since_start FROM vote_snapshots WHERE votes IS NOT NULL', do_sync=False)
    V["at"] = pd.to_datetime(V["at"], utc=True); V["pt"] = V["at"].dt.tz_convert("America/Los_Angeles")
    L = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank, votes final FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    prior = {}
    for f in os.listdir(os.path.join(HERE, "results", "shadow_makerfix")):
        if f.endswith(".json"):
            try:
                d = json.load(open(os.path.join(HERE, "results", "shadow_makerfix", f)))
                for r in d.get("forecast", []): prior[str(r["id"])] = r.get("pred_clean_nosite", r.get("pred_clean"))
            except Exception: pass
    rows = []
    for d, g in V.groupby("day"):
        t0 = pd.Timestamp(d, tz="America/Los_Angeles")
        Ld = L[L.day == d]
        if len(Ld) < 10: continue
        for h in HS:
            th = t0 + pd.Timedelta(hours=h); s = g[g.pt <= th]
            if s.empty or (th - s.pt.max()) > pd.Timedelta(hours=1, minutes=5): continue
            last = s.sort_values("pt").groupby("id").last()
            def at(dt):
                x = g[g.pt <= th - dt].sort_values("pt").groupby("id").last(); return x
            m1, m2 = at(pd.Timedelta(hours=1)), at(pd.Timedelta(hours=2))
            X = Ld[["id", "daily_rank", "final"]].merge(last[["votes", "comments", "hours_since_start"]], left_on="id", right_index=True, how="left")
            X["v1"] = X.id.map(m1.votes); X["v2"] = X.id.map(m2.votes); X["c1"] = X.id.map(m1.comments)
            X["votes"] = X.votes.fillna(0); X["g1"] = (X.votes - X.v1.fillna(0)).clip(lower=0); X["g2"] = (X.votes - X.v2.fillna(0)).clip(lower=0)
            X["cg1"] = (X.comments.fillna(0) - X.c1.fillna(0)).clip(lower=0); X["prior"] = X.id.map(prior).astype(float)
            X["day"] = d; X["h"] = h; X["wd"] = t0.weekday(); rows.append(X)
    A = pd.concat(rows, ignore_index=True); days = sorted(A.day.unique())
    A["relv"] = A.g1 / A.groupby(["day", "h"]).g1.transform("mean").replace(0, np.nan); A["relv"] = A.relv.fillna(1.0)
    def hits(o, t): return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
    rng = np.random.default_rng(0); md = [f"# Velocity forecast after reveal ({len(days)} days with hourly snapshots, {days[0]}..{days[-1]}; walk-forward by day)", "",
          "| h (PT) | days | (i) votes t3/t5/t10 | (ii) readable extrapolation | (iii) GBM | (ii) - (i) t3 / t5 / t10 (95%) | (iii) - (i) | (ii) - (iii) |", "|---|---|---|---|---|---|---|---|"]
    for h in HS:
        R = {"i": [], "ii": [], "iii": []}
        for k, d in enumerate(days):
            te = A[(A.day == d) & (A.h == h)]; tr = A[(A.day < d) & (A.h == h)]
            if te.empty or tr.day.nunique() < 3: continue
            t = te.sort_values("daily_rank").id.tolist()
            R["i"].append(hits(te.sort_values(["votes", "id"], ascending=[False, True]).id.tolist(), t))
            M = (tr.final / tr.votes.replace(0, np.nan)).median()
            best, bb = None, 0.0
            for b in (0.0, 0.05, 0.1, 0.2, 0.3, 0.5):
                sc = [np.mean(hits(x.assign(s=x.votes * M * (1 + b * (x.relv - 1))).sort_values(["s", "id"], ascending=[False, True]).id.tolist(), x.sort_values("daily_rank").id.tolist())) for _, x in tr.groupby("day")]
                if best is None or np.mean(sc) > best: best, bb = np.mean(sc), b
            R["ii"].append(hits(te.assign(s=te.votes * M * (1 + bb * (te.relv - 1))).sort_values(["s", "id"], ascending=[False, True]).id.tolist(), t))
            F = ["votes", "g1", "g2", "comments", "cg1", "hours_since_start", "prior", "wd"]
            g = lgb.LGBMRegressor(n_estimators=200, learning_rate=0.05, num_leaves=7, min_child_samples=10, verbose=-1).fit(tr[F], np.log1p(tr.final))
            R["iii"].append(hits(te.assign(s=g.predict(te[F])).sort_values(["s", "id"], ascending=[False, True]).id.tolist(), t))
        if not R["i"]: continue
        I, II, III = (np.array(R[k]) for k in ("i", "ii", "iii"))
        def ci(D):
            b = np.array([D[rng.integers(0, len(D), len(D))].mean(0) for _ in range(3000)]); lo, hi = np.percentile(b, 2.5, 0), np.percentile(b, 97.5, 0)
            return " / ".join(f"{D[:, j].mean():+.1f} [{lo[j]:+.1f}, {hi[j]:+.1f}]" for j in range(3))
        f = lambda X: " / ".join(f"{X[:, j].mean():.1f}" for j in range(3))
        md.append(f"| {h:02d}:00 | {len(I)} | {f(I)} | {f(II)} | {f(III)} | {ci(II - I)} | {ci(III - I)} | {ci(II - III)} |")
    md += ["", "Walk-forward: day d uses only earlier days (needs 3) for M(h), b and the GBM; first test day is the 4th day held. Snapshot at h must be within 65 min of h."]
    open(os.path.join(HERE, "results", "velocity_forecast.md"), "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
