"""Launch-day forecasts from real intraday votes (Wayback homepage captures, Jul-Oct 2026) plus comments and the
pre-launch prior, on the daily, weekly and monthly boards.
For a cutoff H (hours after 00:00 PT of each launch's own day), each launch gets, using only data before H on its day:
  prior      the pre-launch launch model (ctrl.py, out of sample)
  lv         log1p(votes) at the latest homepage capture of its day before H (votes are hidden before hour 4); NaN if
             its day has no such capture
  lv_h       hours since 00:00 PT of that capture
  comments   non-team comments, distinct commenters, team comments before H (launchday.comments)
Model: LightGBM on final log votes, trained on earlier months only (Aug-Oct tested; Jul trains), 3 seeds. Launches
without a capture fall back to prior + comments, so every launch of a week or month gets a score.
Test 1 (weekly / monthly): rank each week's / month's launches by the predicted final log votes at H = 8, 12, 24.
  Reported with the share of the board's launches that had a capture (coverage).
Test 2 (daily, early): H = 2, 4, 6, on days that have a capture before H (for H = 2 all days: comments only).
  Variants: prior; prior + comments; prior + comments + votes; votes alone.
Intervals: bootstrap over lists (days / weeks), paired vs the prior.
usage: python wayback_boards.py <parsed.jsonl> -> results/wayback_boards.json"""
import json, os, sys
import numpy as np, pandas as pd, lightgbm as lgb
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from simlab import store
import launchday as LD

RANK = {"daily": "out_dailyRank", "weekly": "out_weeklyRank", "monthly": "out_monthlyRank"}


def fit(tr, te, cols):
    return np.mean([lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1,
                                      colsample_bytree=0.8, random_state=s, verbose=-1, n_jobs=8).fit(tr[cols], tr.logv).predict(te[cols]) for s in range(3)], 0)


def per_list(T, col, board, k, key):
    out = {}
    for g_key, g in T.groupby(key):
        real = g[g[RANK[board]] <= k]
        if len(real) == k:
            out[g_key] = len(set(g.nlargest(k, col).id) & set(real.id)) / k
    return out


def boot(a, b, rng):
    ks = sorted(set(a) & set(b)); d = np.array([b[x] - a[x] for x in ks])
    if not len(d):
        return None
    bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(5000)]
    return [round(100 * float(d.mean()), 1), [round(100 * float(x), 1) for x in np.percentile(bs, [2.5, 97.5])], len(d)]


def main(path):
    P, I, E = store.load(); I = I.assign(id=I.id.astype(str))
    C = pd.read_parquet("results/ctrl_preds.parquet"); C["id"] = C.id.astype(str); C = C.drop_duplicates("id")
    A = C[["id", "day", "logv", "all"]].merge(I[["id"] + list(RANK.values())], on="id")
    A = A[A.day >= "2026-07-01"].copy()
    A["week"] = pd.to_datetime(A.day).dt.strftime("%G-W%V"); A["mon"] = A.day.str[:7]
    W = pd.read_json(path, lines=True, dtype={"post_id": str, "capture_ts": str})
    W = W[(W.capture_kind == "home") & (W.day.astype(str).str.len() == 10) & W.votes.notna()]
    ts = pd.to_datetime(W.capture_ts, format="%Y%m%d%H%M%S", utc=True)
    W["h"] = (ts - pd.to_datetime(W.day).dt.tz_localize("America/Los_Angeles").dt.tz_convert("UTC")).dt.total_seconds() / 3600
    W = W[(W.h >= 4) & (W.h < 24)]
    CM = LD.comments()
    rng = np.random.default_rng(0); res = {"launches": len(A), "days": int(A.day.nunique())}

    def frame(H):
        X = A.copy()
        w = W[W.h < H].sort_values("h").drop_duplicates(["day", "post_id"], keep="last")
        cap_days = set(w.day)
        X["lv"] = X.id.map(dict(zip(w.post_id, np.log1p(w.votes))))
        X.loc[X.day.isin(cap_days) & X.lv.isna(), "lv"] = 0.0   # the day was captured but the launch was not on the page
        X["lv_h"] = X.day.map(w.groupby("day").h.max())
        X["cap"] = X.day.isin(cap_days)
        S = CM[(CM.h >= -24) & (CM.h < H)]
        X["c"] = np.log1p(X.id.map(S[~S.team].groupby("id").size()).fillna(0))
        X["u"] = np.log1p(X.id.map(S[~S.team].groupby("id").person.nunique()).fillna(0))
        X["t"] = np.log1p(X.id.map(S[S.team].groupby("id").size()).fillna(0))
        X["lv_dayr"] = X.groupby("day").lv.rank(pct=True); X["c_dayr"] = X.groupby("day").c.rank(pct=True)
        return X

    def predict(X, cols):
        out = []
        for m in sorted(X.mon.unique()):
            if m < "2026-08":
                continue
            tr, te = X[X.mon < m], X[X.mon == m].copy()
            te["p"] = fit(tr, te, cols); out.append(te)
        return pd.concat(out)
    # test 1: weekly / monthly
    res["boards_by_cutoff"] = {}
    for H in (8, 12, 24):
        X = frame(H)
        full = predict(X, ["all", "c", "u", "t", "lv", "lv_h"]); base = predict(X, ["all"])
        T = full.merge(base[["id", "p"]].rename(columns={"p": "p_prior"}), on="id")
        b = {}
        for board, key in (("daily", "day"), ("weekly", "week"), ("monthly", "mon")):
            cov = T.groupby(key).cap.mean()
            for k in (3, 5, 10):
                A0, A1 = per_list(T, "p_prior", board, k, key), per_list(T, "p", board, k, key)
                if A1:
                    b[f"{board} top{k}"] = {"prior": round(100 * float(np.mean(list(A0.values()))), 1), "launch-day": round(100 * float(np.mean(list(A1.values()))), 1),
                                            "delta": boot(A0, A1, rng), "lists": len(A1), "mean_capture_coverage": round(float(cov[list(A1)].mean()), 3)}
            # lists with full capture coverage only (every day of the week / month captured)
            full_keys = [k_ for k_, v in cov.items() if v >= 0.999]
            b[f"{board} lists fully captured"] = len(full_keys)
        res["boards_by_cutoff"][f"H={H}"] = b
    # test 2: early daily reads
    res["early_daily"] = {}
    for H in (2, 4, 6):
        X = frame(H)
        X["lv0"] = X.lv.fillna(-1)
        V = {"prior": ["all"], "prior + comments": ["all", "c", "u", "t", "c_dayr"], "prior + comments + votes": ["all", "c", "u", "t", "c_dayr", "lv", "lv_h", "lv_dayr"]}
        T = None
        for name, cols in V.items():
            p = predict(X, cols)[["id", "day", "cap", "lv", "out_dailyRank", "p"]].rename(columns={"p": name})
            T = p if T is None else T.merge(p[["id", name]], on="id")
        T["votes alone"] = T.lv.fillna(-1)
        capd = T[T.cap].day.unique()
        days = capd if len(capd) else T.day.unique()   # votes are hidden before hour 4: at H <= 4 every day, comments only
        U = T[T.day.isin(days)]
        line = {"days": int(U.day.nunique())}
        for k in (3, 5, 10):
            base = per_list(U, "prior", "daily", k, "day")
            for name in list(V)[1:] + (["votes alone"] if len(capd) else []):
                cur = per_list(U, name, "daily", k, "day")
                line[f"{name} top{k}"] = [round(100 * float(np.mean(list(cur.values()))), 1), boot(base, cur, rng)]
            line[f"prior top{k}"] = round(100 * float(np.mean(list(base.values()))), 1)
        res["early_daily"][f"H={H}"] = line
    json.dump(res, open("results/wayback_boards.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
