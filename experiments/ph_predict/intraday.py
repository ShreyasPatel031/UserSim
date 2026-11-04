"""Intraday PH model (Shreyas's directive via the orchestrator, Nov 4 02:00 UTC): at every snapshot of launch day, predict
each featured launch's final daily votes and final rank from what is visible then, and learn how the pre-launch
forecast grows into the end-of-day result. A TOOL, not a north-star number: the north star stays the pre-launch forecast.

Inputs at snapshot t (per launch), all observable at t:
  pre_rank_pct   the pre-launch forecast's rank within the day (forecasts table, model launch_model), as a percentile
  v              log1p(votes so far); NaN while PH hides counts (~first 4 h: 0 shown) -> hidden flag
  rank_now_pct   PH's own ordering at t (rank_now / daily_rank_at_fetch), percentile within the day's line-up
  c, c_pct       log1p(comments so far) and its within-day percentile
  h              hours since the launch start; n = line-up size
Target: log1p(final daily votes) (launches table, final the day after). Learner: ridge on the inputs and their
interactions with hour buckets (0-2, 2-4, 4-8, 8-16, 16+ h), so the weight on observed votes grows through the day.
"Pre-launch alone" is the same learner with pre_rank_pct and n only (the baseline each hour is compared against).
Sources: training / backtest from warehouse vote_snapshots (hourly, ~Oct 31 on; read with pipeline.snapshots, late
reads corrected); live from raw/ph_at_launch/<day>/live/posts_ts.jsonl (15-min, API light loop).
Reports per hour since start: top-3/5/10 hit (final daily rank) of the intraday ranking vs pre-launch alone, vote MAE
(log), the share of the pre-launch error resolved (1 - MAE_h / MAE_pre), and per hour the Spearman between the observed
partial residual (rank_now / votes vs the pre-launch rank) and the final residual (when the shock becomes visible).
usage: python intraday.py backtest <day> [<day> ...]        leave-one-day-out over the given settled days
       python intraday.py test <test_day> <train_day> ...    train on train days, score the test day
       python intraday.py live <day> <train_day> ...          predict the newest live snapshot -> bucket pred_<snap>.jsonl
       python intraday.py loop <day> <train_day> ...          live every 15 min until 23:59 PT of <day>"""
import json, os, subprocess, sys, tempfile, time
import numpy as np, pandas as pd
from scipy.stats import spearmanr

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
BUCKET = "gs://usersim-bakeoff-347838016394/usersim_sim"
BUCKETS = [(0, 2), (2, 4), (4, 8), (8, 16), (16, 99)]
BASE = ["pre_rank_pct", "n_log"]
OBS = ["v", "hidden", "rank_now_pct", "c", "c_pct"]
OUT = os.environ.get("OUT", os.path.join(HERE, "results", "intraday.json"))
MIN_BUCKET = int(os.environ.get("MIN_BUCKET", "30"))   # training rows an hour bucket needs before its weights are used


def con():
    from pipeline import warehouse as W
    return W


def prelaunch(days):
    W = con(); q = ",".join(repr(d) for d in days)
    F = W.query(f"SELECT forecast_date AS day, launch_id::VARCHAR AS id, min(predicted_rank) AS pre_rank FROM forecasts "
                f"WHERE model = 'launch_model' AND forecast_date IN ({q}) GROUP BY 1, 2")
    return F


def finals(days):
    W = con(); q = ",".join(repr(d) for d in days)
    return W.query(f'SELECT id::VARCHAR AS id, "day"::VARCHAR AS day, votes AS final_votes, daily_rank AS final_rank FROM launches '
                   f'WHERE "day"::VARCHAR IN ({q}) AND votes IS NOT NULL AND daily_rank IS NOT NULL')


def hist_snapshots(days):
    from pipeline import snapshots
    S = snapshots.load(day_from=min(days), day_to=max(days))
    S = S[S.day.isin(days)]
    return S.rename(columns={"hours_since_start": "h"})[["day", "at", "h", "launch_id", "votes", "comments", "rank_now"]].rename(columns={"launch_id": "id"})


def live_snapshots(day):
    d = tempfile.mkdtemp(prefix="intra_")
    subprocess.run(["gsutil", "-q", "cp", f"{BUCKET}/raw/ph_at_launch/{day}/live/posts_ts.jsonl", d], check=True)
    P = pd.read_json(f"{d}/posts_ts.jsonl", lines=True, dtype=False)
    P = P[P.fetch_status.astype(str) == "200"].copy()
    if "source" in P:
        P = P[P.source.astype(str).str.startswith("ph_api_v2")]
    start = pd.to_datetime(P.featured_at, utc=True, errors="coerce", format="ISO8601") if "featured_at" in P else None
    st = pd.to_datetime(P.snapshot_ts, utc=True, format="ISO8601")
    day0 = pd.Timestamp(f"{day} 00:01", tz="America/Los_Angeles").tz_convert("UTC")
    P["h"] = ((st - (start.fillna(day0) if start is not None else day0)).dt.total_seconds() / 3600).round(2)
    hidden = P.hide_votes_count.fillna(False).astype(bool) if "hide_votes_count" in P else pd.Series(False, index=P.index)
    v = pd.to_numeric(P.votes_at_fetch, errors="coerce")
    P["votes"] = v.where(~hidden & v.notna(), 0)
    P["comments"] = pd.to_numeric(P.get("comments_count_at_fetch"), errors="coerce")
    P["rank_now"] = pd.to_numeric(P.get("daily_rank_at_fetch"), errors="coerce")
    P = P.assign(day=day, at=P.snapshot_ts, id=P.launch_id.astype(str)).drop_duplicates(["at", "id"])
    return P[["day", "at", "h", "id", "votes", "comments", "rank_now"]]


def features(S, F):
    """S: snapshots (day, at, h, id, votes, comments, rank_now); F: pre-launch ranks (day, id, pre_rank)."""
    X = S.merge(F, on=["day", "id"], how="inner").copy()
    g = X.groupby(["day", "at"])
    X["n"] = g.id.transform("size"); X["n_log"] = np.log(X.n)
    X["pre_rank_pct"] = g.pre_rank.rank(pct=True)
    X["hidden"] = ((X.votes.fillna(0) == 0) & (X.h < 6)).astype(float)   # PH masks counts as 0 for ~4 h
    X["v"] = np.where(X.hidden > 0, 0.0, np.log1p(X.votes.fillna(0)))
    X["rank_now_pct"] = g.rank_now.rank(pct=True).fillna(0.5)
    X["c"] = np.log1p(X.comments.fillna(0)); X["c_pct"] = g.c.rank(pct=True)
    for i, (lo, hi) in enumerate(BUCKETS):
        X[f"b{i}"] = ((X.h >= lo) & (X.h < hi)).astype(float)
    return X


def design(X, cols):
    parts = [X[cols].values]
    for i in range(len(BUCKETS)):
        parts.append(X[cols].values * X[[f"b{i}"]].values)
        parts.append(X[[f"b{i}"]].values)
    return np.hstack(parts)


class Ridge:
    def __init__(self, cols, lam=3.0):
        self.cols, self.lam = cols, lam

    def fit(self, X, y):
        self.seen = [float(X[f"b{i}"].sum()) for i in range(len(BUCKETS))]   # training rows per hour bucket
        Z = design(X, self.cols); self.mu, self.sd = Z.mean(0), Z.std(0) + 1e-9
        Zs = np.c_[np.ones(len(Z)), (Z - self.mu) / self.sd]
        P = self.lam * np.eye(Zs.shape[1]); P[0, 0] = 0
        self.w = np.linalg.solve(Zs.T @ Zs + P, Zs.T @ y); return self

    def predict(self, X):
        Z = design(X, self.cols)
        return np.c_[np.ones(len(Z)), (Z - self.mu) / self.sd] @ self.w


def score(T):
    """T: test rows with y, p_intra, p_pre, final_rank, h, day, at, plus partial-residual inputs. Per hour bucket (integer h)."""
    T = T.assign(hr=np.floor(T.h).astype(int))
    out = {}
    for hr, g in T.groupby("hr"):
        r = {"rows": int(len(g)), "snapshots": int(g.groupby(["day", "at"]).ngroups), "fallback_rows": int(g.get("fallback", pd.Series(0)).sum())}
        for k in (3, 5, 10):
            hi, hp = [], []
            for _, s in g.groupby(["day", "at"]):
                if (s.final_rank <= k).sum() < k:
                    continue
                truth = set(s[s.final_rank <= k].id)
                hi.append(len(set(s.nlargest(k, "p_intra").id) & truth) / k); hp.append(len(set(s.nlargest(k, "p_pre").id) & truth) / k)
            r[f"top{k}_intraday"] = round(100 * float(np.mean(hi)), 1) if hi else None
            r[f"top{k}_prelaunch"] = round(100 * float(np.mean(hp)), 1) if hp else None
        mi, mp = float(np.abs(g.p_intra - g.y).mean()), float(np.abs(g.p_pre - g.y).mean())
        r.update(mae_log_intraday=round(mi, 3), mae_log_prelaunch=round(mp, 3), error_resolved=round(1 - mi / mp, 3) if mp else None)
        rho = [spearmanr(s.partial, s.final_resid).correlation for _, s in g.groupby(["day", "at"]) if s.partial.nunique() > 1 and len(s) >= 5]
        r["shock_visible_rho"] = round(float(np.nanmean(rho)), 3) if rho else None
        out[int(hr)] = r
    return out


def build(days):
    S, F, Y = hist_snapshots(days), prelaunch(days), finals(days)
    X = features(S, F).merge(Y[["id", "final_votes", "final_rank"]], on="id")
    X["y"] = np.log1p(X.final_votes)
    return X


def fit_pair(X):
    return Ridge(BASE + OBS).fit(X, X.y.values), Ridge(BASE).fit(X, X.y.values)


def apply(m_intra, m_pre, T):
    T = T.copy(); T["p_intra"] = m_intra.predict(T); T["p_pre"] = m_pre.predict(T)
    # an hour bucket with too few training rows has no learned weights (e.g. the first hours, which only Nov 2 has):
    # fall back to the pre-launch prediction there instead of extrapolating
    unseen = np.zeros(len(T), dtype=bool)
    for i in range(len(BUCKETS)):
        if m_intra.seen[i] < MIN_BUCKET:
            unseen |= T[f"b{i}"].values > 0
    T["p_intra"] = np.where(unseen, T.p_pre, T.p_intra); T["fallback"] = unseen.astype(int)
    # partial residual visible at t: PH's current standing vs the pre-launch standing (positive = running ahead)
    T["partial"] = T.rank_now_pct.rsub(1) - T.pre_rank_pct.rsub(1) + np.where(T.hidden > 0, 0, T.groupby(["day", "at"]).v.rank(pct=True) - T.pre_rank_pct.rsub(1))
    if "y" in T:
        T["final_resid"] = T.y - T.p_pre
    return T


def backtest(*days):
    X = build(list(days)); res = {"label": "intraday tool (not a north-star number)", "days": list(days), "mode": "leave one day out", "by_hour": {}}
    parts = []
    for d in days:
        tr, te = X[X.day != d], X[X.day == d]
        if not len(te) or not len(tr):
            continue
        parts.append(apply(*fit_pair(tr), te))
    res["by_hour"] = score(pd.concat(parts)); res["rows"] = int(len(X)); res["launches"] = int(X.id.nunique())
    return res


def test(test_day, *train_days):
    X = build(list(train_days) + [test_day])
    tr, te = X[X.day != test_day], X[X.day == test_day]
    res = {"label": "intraday tool (not a north-star number)", "train": list(train_days), "test": test_day,
           "by_hour": score(apply(*fit_pair(tr), te)), "test_launches": int(te.id.nunique())}
    return res


def live(day, *train_days):
    X = build(list(train_days)); mi, mp = fit_pair(X)
    S = live_snapshots(day); F = prelaunch([day])
    if not len(F):
        raise SystemExit(f"{day}: no pre-launch forecast rows yet")
    T = features(S, F); latest = T["at"].max(); T = apply(mi, mp, T[T["at"] == latest])
    T["pred_votes"] = np.expm1(T.p_intra).round(1); T["pred_rank"] = T.p_intra.rank(ascending=False, method="first").astype(int)
    T["pre_rank_now"] = T.p_pre.rank(ascending=False, method="first").astype(int)
    rows = T[["day", "at", "h", "id", "pred_votes", "pred_rank", "pre_rank_now"]].assign(model="intraday_ridge_v1", trained_on=",".join(train_days))
    tag = pd.Timestamp(latest).tz_convert("America/Los_Angeles").strftime("%Y%m%dT%H%MPT")
    loc = os.path.join(tempfile.mkdtemp(prefix="pred_"), f"pred_{tag}.jsonl")
    rows.to_json(loc, orient="records", lines=True)
    subprocess.run(["gsutil", "-q", "cp", loc, f"{BUCKET}/raw/ph_predict_data/intraday/{day}/pred_{tag}.jsonl"], check=True)
    print(json.dumps({"day": day, "snapshot": str(latest), "launches": int(len(rows)), "file": f"pred_{tag}.jsonl"}), flush=True)
    return tag


def loop(day, *train_days):
    end = pd.Timestamp(f"{day} 23:59", tz="America/Los_Angeles").tz_convert("UTC"); last = None
    while pd.Timestamp.now(tz="UTC") < end:
        try:
            tag = live(day, *train_days)
            last = tag
        except SystemExit as e:
            print(json.dumps({"day": day, "skip": str(e)}), flush=True)
        except Exception as e:  # noqa: BLE001  (keep the loop alive; log and retry next slot)
            print(json.dumps({"day": day, "error": f"{type(e).__name__}: {e}"[:300]}), flush=True)
        time.sleep(900 - time.time() % 900 + 120)   # 2 min after each quarter hour (the light loop needs ~20 s)


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd in ("backtest", "test"):
        r = backtest(*args) if cmd == "backtest" else test(*args)
        json.dump(r, open(OUT, "w"), indent=1); print(json.dumps(r, indent=1))
    elif cmd == "live":
        live(*args)
    elif cmd == "loop":
        loop(*args)
