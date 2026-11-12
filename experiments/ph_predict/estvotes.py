"""Hidden votes bracketed before the reveal from the weekly rank (orchestrator 00:40Z Nov 12).
While today's votes are hidden, the official API still returns weeklyRank for today's launches, ranked among the week's
launches whose votes are visible. So a launch's hidden votes lie between the votes of the earlier-day launches ranked just
above and just below it.
est_votes(day, T): for every today launch at the latest snapshot fetched by T (live/posts_ts.jsonl weekly_rank_at_fetch):
  E = earlier-day launches of the same Mon-Sun week, by votes descending. Their votes "now" are proxied by the latest read we
      hold: Data Feeder's 23:50 PT monthly_reread of the previous day when it exists, else their day-end votes
      (weekly_live.dayend_votes)
  k = today's launches with a smaller weekly rank; a = w - 1 - k = earlier-day launches above it
  est = sqrt(E[a-1] * E[a]) between the bracketing votes; top edge (a = 0): E[0] * 1.25; bottom edge: E[-1] / 2
  Mondays have no earlier-day launches: no estimate.
validate: est at the last snapshot before the reveal vs real votes at the reveal snapshot (R0) - Spearman, median absolute
log error, share within the bracket.
usage: python estvotes.py validate -> results/estvotes_validate.json"""
import json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from early_forecast import B, reveal, load_snaps, pt_day
_P = {}


def posts(day):
    if day in _P:
        return _P[day]
    p = f"{tempfile.mkdtemp(prefix='ev_')}/p.jsonl"
    if subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/ph_at_launch/{day}/live/posts_ts.jsonl", p]).returncode:
        _P[day] = pd.DataFrame(); return _P[day]
    rows = []
    for l in open(p):
        r = json.loads(l)
        if r.get("fetch_status") == 200 and str(r.get("source", "")).startswith("ph_api_v2") and pt_day(r, day) == day:
            rows.append((pd.Timestamp(r["snapshot_ts"]), pd.Timestamp(r.get("fetched_at") or r["snapshot_ts"]), str(r["launch_id"]),
                         r.get("weekly_rank_at_fetch"), r.get("daily_rank_at_fetch"), r.get("votes_at_fetch")))
    _P[day] = pd.DataFrame(rows, columns=["ts", "fa", "id", "wr", "dr", "v"])
    return _P[day]


def earlier_votes(day):
    """votes of the week's earlier-day launches: previous day's 23:50 PT reread if held, else day-end votes."""
    t = pd.Timestamp(day); mon = t - pd.Timedelta(days=t.dayofweek)
    if t.dayofweek == 0:
        return pd.Series(dtype=float), "monday"
    prev = (t - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    p = f"{tempfile.mkdtemp(prefix='ev_')}/r.jsonl"
    if subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/ph_at_launch/monthly_reread/{prev[:7]}/{prev}.jsonl", p]).returncode == 0:
        X = pd.DataFrame([json.loads(l) for l in open(p) if '"_header"' not in l])
        if "featuredAt" in X:   # day from featuredAt in PT (00:00 PT belongs to the new day)
            X["launch_day_PT"] = [pt_day({"featuredAt": f, "day": d0}) for f, d0 in zip(X.featuredAt, X.launch_day_PT)]
        X = X.assign(id=X.id.astype(str)).sort_values("launch_day_PT").drop_duplicates("id", keep="last")   # 00:00 PT cohort listed twice
        X = X[(X.launch_day_PT >= mon.strftime("%Y-%m-%d")) & (X.launch_day_PT < day)]
        if len(X):
            return X.set_index(X.id.astype(str)).votesCount.astype(float), "reread"
    import weekly_live as WL
    V = {}
    for d in pd.date_range(mon, t, inclusive="left").strftime("%Y-%m-%d"):
        v, _ = WL.dayend_votes(d); V.update(v.to_dict())
    return pd.Series(V, dtype=float), "dayend"


def est_votes(day, T, E=None):
    P = posts(day)
    if P.empty:
        return pd.DataFrame()
    if E is None:
        E, _ = earlier_votes(day)
    if E.empty:
        return pd.DataFrame()
    S = P[(P.fa <= T) & P.wr.notna()].sort_values("fa").groupby("id").last()
    if S.empty:
        return pd.DataFrame()
    ev = np.sort(E.values)[::-1]
    out = []
    w_all = S.wr.astype(float)
    for i, w in w_all.items():
        k = int((w_all < w).sum()); a = int(w) - 1 - k
        if a <= 0:
            est, lo, hi = ev[0] * 1.25, ev[0], np.nan
        elif a >= len(ev):
            est, lo, hi = ev[-1] / 2, 0.0, ev[-1]
        else:
            hi, lo = ev[a - 1], ev[a]; est = float(np.sqrt(max(hi, 1) * max(lo, 1)))
        out.append({"id": i, "est_votes": float(est), "bracket_lo": float(lo), "bracket_hi": float(hi) if hi == hi else None, "weekly_rank": int(w)})
    return pd.DataFrame(out)


def validate():
    from scipy.stats import spearmanr
    res = []
    for d in ("2026-11-04", "2026-11-08", "2026-11-10", "2026-11-11"):
        T = load_snaps(d); R0 = reveal(T)
        E, src = earlier_votes(d)
        pre = R0 - pd.Timedelta(minutes=15)
        X = est_votes(d, pre + pd.Timedelta(minutes=5), E)
        V = T[T.ts == R0].groupby("id").v.last()
        X["real_R0"] = X.id.map(V)
        X = X.dropna(subset=["real_R0"])
        inb = ((X.real_R0 >= X.bracket_lo) & (X.bracket_hi.isna() | (X.real_R0 <= X.bracket_hi.fillna(np.inf)))).mean()
        r = {"day": d, "earlier_source": src, "earlier_launches": int(len(E)), "launches": int(len(X)), "pre_snapshot": str(pre),
             "spearman": round(float(spearmanr(X.est_votes, X.real_R0).correlation), 3),
             "median_abs_log_err": round(float(np.median(np.abs(np.log1p(X.est_votes) - np.log1p(X.real_R0)))), 3),
             "share_in_bracket": round(float(inb), 3), "top3_overlap": len(set(X.nlargest(3, "est_votes").id) & set(X.nlargest(3, "real_R0").id)) / 3 * 100}
        res.append(r); print(json.dumps(r))
    json.dump(res, open(os.path.join(HERE, "results", "estvotes_validate.json"), "w"), indent=1)


if __name__ == "__main__":
    if sys.argv[1] == "validate":
        validate()
