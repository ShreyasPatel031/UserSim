"""Expected day-end votes from a read at T (orchestrator 02:30Z Nov 12, item 1).
multiplier m = day-end votes / votes at T (after the reveal) or / est_votes at T (before it), by
  T     hours after 00:00 PT of the launch day: before the reveal 0.75, 1, 1.5, 2, 2.5, 3, 3.5, 3.75 (est_votes);
        from the reveal 4, 4.25, 4.5, 5, 6, ..., 12 (votes)
  pos   leader position by the read at T within the day: top3 / 4-10 / rest
  wk    weekday / weekend (Sat, Sun PT)
Sources
  live   live/posts_ts.jsonl (15-min official API reads; Nov 4, 8, 9, 10 + later days once they end). Day end = weekly_live.
         dayend_votes (latest read <= 23:59:59 PT). est_votes (estvotes.py) before the reveal, not on Mondays.
  hourly warehouse vote_snapshots (the pipeline's hourly recorder, Oct 31 - Nov 10), days without a live file only; read
         = latest snapshot in (T - 1h, T]. Day end = latest snapshot <= 23:59:59 PT (>= 22:00 PT required).
  wayback E5's Wayback homepage captures, Jul - Oct (raw/ph_homepage_archive/parsed.jsonl), post-reveal T only: read = the
         last same-day capture in (T - 1h, T] (latestScore); day end = launchDayScore from a capture taken after the day
         (frozen; checked constant across later captures).
Fit: median m per (T, pos, wk) (fallback (T, pos), then T) over all sources; spread p10 / p90. Error: leave-one-day-out
(fit on the other days) median abs % error of v x m vs day-end votes, launches with day-end >= 10 votes, by T and source,
next to the plain "no growth" error (v alone) and the T-only multiplier.
usage: python growth.py fit -> results/growth.json + .md;  growth.lookup(T, pos_rank, weekend, kind) -> m"""
import json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from early_forecast import B, load_snaps
OUT = os.path.join(HERE, "results", "growth.json")
T_PRE = [0.75, 1, 1.5, 2, 2.5, 3, 3.5, 3.75]
T_POST = [4, 4.25, 4.5, 5, 6, 7, 8, 9, 10, 11, 12]
LIVE_DAYS = ["2026-11-04", "2026-11-08", "2026-11-09", "2026-11-10"]


def pos_bin(r):
    return "top3" if r <= 3 else ("4-10" if r <= 10 else "rest")


def t0(d):
    return pd.Timestamp(d + " 00:00", tz="America/Los_Angeles").tz_convert("UTC")


def rows_for(d, src, reads, dayend, kind):
    """reads: {T: Series id -> value at T}; dayend: Series id -> day-end votes."""
    wk = int(pd.Timestamp(d).dayofweek >= 5); out = []
    for T, s in reads.items():
        s = s[s.index.isin(dayend.index)]
        if len(s) < 5:
            continue
        rk = s.rank(ascending=False, method="first")
        for i, v in s.items():
            out.append({"day": d, "src": src, "kind": kind, "T": T, "id": i, "v": float(v), "pos": pos_bin(rk[i]), "wk": wk, "end": float(dayend[i])})
    return out


_V = {}


def snaps():
    if "v" not in _V:
        from pipeline import warehouse as W
        V = W.query('SELECT "day" d, "at" a, CAST(launch_id AS VARCHAR) id, votes FROM vote_snapshots', do_sync=False)
        V["a"] = pd.to_datetime(V.a, utc=True); _V["v"] = V
        _V["ids"] = W.query("SELECT CAST(id AS VARCHAR) id, day FROM launches WHERE daily_rank IS NOT NULL", do_sync=False).groupby("day").id.apply(set).to_dict()
    return _V["v"], _V["ids"]


def dayend(d, T=None):
    """latest read <= 00:06 PT of d+1 (the 00:01 read; else the last before midnight) over the live file and the hourly recorder; kept only if that read is >= 22:00 PT (the last 2 h add ~1%);
    the day's ranked launches only."""
    V, ids = snaps(); e = t0(d) + pd.Timedelta(hours=24, minutes=6)   # the 00:01 PT read when held (official rank = midnight votes)
    parts = [V[V.d == d].rename(columns={"a": "ts", "votes": "v"})[["ts", "id", "v"]]]
    if T is not None:
        parts.append(T[["ts", "id", "v"]])
    A = pd.concat(parts); A = A[(A.ts <= e) & A.id.isin(ids.get(d, set()))].sort_values("ts").groupby("id").last()
    A = A[A.ts >= t0(d) + pd.Timedelta(hours=22)]
    return A.v.astype(float)


def live_rows(d):
    import weekly_live as WL, estvotes as EV
    if pd.Timestamp.now(tz="UTC") <= WL.day_end(d) + pd.Timedelta(minutes=30):
        return []
    T = load_snaps(d); T = T[T.id.isin(snaps()[1].get(d, set()))]; end = dayend(d, T)
    reads = {}
    for h in T_POST:
        t = t0(d) + pd.Timedelta(hours=h)
        g = T[(T.ts <= t) & (T.ts > t - pd.Timedelta(minutes=20))]
        if len(g) and (g.v > 0).mean() >= 0.5:
            reads[h] = g.sort_values("ts").groupby("id").v.last()
    rows = rows_for(d, "live", reads, end, "votes")
    E, src = EV.earlier_votes(d)
    if not E.empty:
        pre = {}
        for h in T_PRE:
            X = EV.est_votes(d, t0(d) + pd.Timedelta(hours=h), E)
            if len(X):
                pre[h] = X.set_index("id").est_votes
        rows += rows_for(d, "live", pre, end, "est")
    return rows


def hourly_rows(skip):
    V, ids = snaps(); rows = []
    for d, g in V.groupby("d"):
        if d in skip or pd.Timestamp.now(tz="UTC") <= t0(d) + pd.Timedelta(hours=24):
            continue
        g = g[g.id.isin(ids.get(d, set()))]; end = dayend(d)
        if len(end) < 5:
            continue
        reads = {}
        for h in T_POST:
            t = t0(d) + pd.Timedelta(hours=h); w = g[(g.a <= t) & (g.a > t - pd.Timedelta(hours=1))]
            if len(w) and (w.votes > 0).mean() >= 0.5:
                reads[h] = w.sort_values("a").groupby("id").votes.last().astype(float)
        rows += rows_for(d, "hourly", reads, end, "votes")
    return rows


def wayback_rows():
    p = f"{tempfile.mkdtemp(prefix='gr_')}/parsed.jsonl"
    subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/ph_homepage_archive/parsed.jsonl", p], check=True)
    H = pd.read_json(p, lines=True, dtype={"post_id": str, "day": str})
    H = H[(H.capture_kind == "home") & (H.day != "")].copy()
    H["cap"] = pd.to_datetime(H.capture_ts.astype(str), format="%Y%m%d%H%M%S", utc=True).dt.tz_convert("America/Los_Angeles")
    H["hr"] = (H.cap - pd.to_datetime(H.day).dt.tz_localize("America/Los_Angeles")).dt.total_seconds() / 3600
    end = H[H.hr >= 24.25].dropna(subset=["launchDayScore"]).groupby("post_id").launchDayScore.first().astype(float)
    S = H[(H.hr > 0) & (H.hr < 24)].dropna(subset=["latestScore"]); rows = []
    for d, g in S.groupby("day"):
        reads = {}
        for h in T_POST:
            w = g[(g.hr <= h) & (g.hr > h - 1)]
            if len(w):
                last = w[w.capture_ts == w.sort_values("hr").capture_ts.iloc[-1]]
                reads[h] = last.drop_duplicates("post_id").set_index("post_id").latestScore.astype(float)
        rows += rows_for(d, "wayback", reads, end, "votes")
    return rows


def fit_table(X):
    X = X[(X.v > 0) & (X.end > 0)].assign(m=lambda x: x.end / x.v)
    tab = {}
    for keys, lvl in ((["kind", "T", "pos", "wk"], "full"), (["kind", "T", "pos"], "pos"), (["kind", "T"], "T")):
        for k, g in X.groupby(keys):
            tab["|".join(f"{x:g}" if isinstance(x, (int, float, np.integer, np.floating)) and not isinstance(x, bool) else str(x) for x in (k if isinstance(k, tuple) else (k,)))] = {
                "m": round(float(g.m.median()), 4), "p10": round(float(g.m.quantile(0.1)), 3), "p90": round(float(g.m.quantile(0.9)), 3),
                "n": int(len(g)), "days": int(g.day.nunique())}
    return tab


def lookup(T, pos_rank, weekend, kind="votes", tab=None, min_n=20):
    """multiplier for a read at T hours after 00:00 PT (nearest grid point at or below T)."""
    if tab is None:
        tab = json.load(open(OUT))["table"]
    grid = T_PRE if kind == "est" else T_POST
    Tg = max([g for g in grid if g <= T + 1e-9], default=grid[0])
    Tg = f"{float(Tg):g}"
    p = pos_bin(pos_rank)
    for key in (f"{kind}|{Tg}|{p}|{int(weekend)}", f"{kind}|{Tg}|{p}", f"{kind}|{Tg}"):
        if key in tab and tab[key]["n"] >= min_n:
            return tab[key]["m"]
    return 1.0


def exp_final(vals, T, weekend, kind="votes"):
    """expected day-end votes for a Series id -> votes (or est_votes) read at T hours after 00:00 PT; position = rank of
    the read within the series. NaN stays NaN."""
    tab = json.load(open(OUT))["table"]; v = vals.astype(float); rk = v.rank(ascending=False, method="first")
    return pd.Series({i: (x * lookup(T, rk[i], weekend, kind, tab) if x == x else np.nan) for i, x in v.items()}, dtype=float)


def mape(pred, end):
    return float(np.median(np.abs(pred - end) / end) * 100)


def fit():
    cache = os.environ.get("GR_CACHE")
    if cache and os.path.exists(cache):
        return fit_from(pd.read_pickle(cache))
    rows = []
    for d in LIVE_DAYS + [x for x in pd.date_range("2026-11-11", pd.Timestamp.now(tz="America/Los_Angeles").tz_localize(None).normalize() - pd.Timedelta(days=1)).strftime("%Y-%m-%d")]:
        r = live_rows(d); rows += r; print(d, "live rows", len(r), flush=True)
    live_days = {r["day"] for r in rows}
    h = hourly_rows(live_days); rows += h; print("hourly rows", len(h), flush=True)
    w = wayback_rows(); rows += w; print("wayback rows", len(w), flush=True)
    X = pd.DataFrame(rows); X["T"] = X["T"].astype(float)
    if cache:
        X.to_pickle(cache)
    return fit_from(X)


def fit_from(X):
    tab = fit_table(X)
    # leave-one-day-out error
    ev = []
    Xe = X[(X.end >= 10) & (X.v > 0)]
    for d in sorted(Xe.day.unique()):
        tr = fit_table(X[X.day != d]); te = Xe[Xe.day == d]
        for (kind, T, src), g in te.groupby(["kind", "T", "src"]):
            mf = np.array([lookup(T, {"top3": 1, "4-10": 5, "rest": 20}[p], wk, kind, tr) for p, wk in zip(g.pos, g.wk)])
            mt = tr.get(f"{kind}|{float(T):g}", {}).get("m", 1.0)
            for j, (_, r) in enumerate(g.iterrows()):
                ev.append({"day": d, "kind": kind, "T": T, "src": src, "pos": r.pos, "end": r.end, "none": r.v, "T_only": r.v * mt, "fitted": r.v * mf[j]})
    E = pd.DataFrame(ev)
    err = {}
    for (kind, T, src), g in E.groupby(["kind", "T", "src"]):
        err[f"{kind}|{float(T):g}|{src}"] = {"n": int(len(g)), "days": int(g.day.nunique()), **{c: round(mape(g[c], g.end), 1) for c in ("none", "T_only", "fitted")},
                                    "fitted_top10": round(mape(g[g.pos != "rest"].fitted, g[g.pos != "rest"].end), 1) if (g.pos != "rest").any() else None}
    res = {"written_at": pd.Timestamp.now(tz="UTC").isoformat(), "grid_pre_est": T_PRE, "grid_post_votes": T_POST,
           "sources": {s: {"days": int(g.day.nunique()), "rows": int(len(g)), "day_range": [g.day.min(), g.day.max()]} for s, g in X.groupby("src")},
           "table": tab, "lodo_error": err}
    json.dump(res, open(OUT, "w"), indent=1)
    md = ["# Expected day-end votes: growth multipliers from a read at T", "",
          "m = day-end votes / votes at T (from the reveal) or / est_votes at T (before it). Median with p10-p90; n launches (days).",
          "Sources: " + "; ".join(f"{s} {v['days']} days ({v['day_range'][0]}..{v['day_range'][1]}), {v['rows']} rows" for s, v in res["sources"].items()) + ".", "",
          "## Multipliers by T and leader position (all days; weekday / weekend split in growth.json)", "",
          "| kind | T (h after 00:00 PT) | top 3 | 4-10 | rest | all |", "|---|---|---|---|---|---|"]
    f = lambda k: (f"{tab[k]['m']:.2f} [{tab[k]['p10']:.2f}-{tab[k]['p90']:.2f}] n {tab[k]['n']} ({tab[k]['days']})" if k in tab else "-")
    for kind, grid in (("est", T_PRE), ("votes", T_POST)):
        for T in grid:
            Tk = f"{float(T):g}"
            md.append(f"| {kind} | {Tk} | {f(f'{kind}|{Tk}|top3')} | {f(f'{kind}|{Tk}|4-10')} | {f(f'{kind}|{Tk}|rest')} | {f(f'{kind}|{Tk}')} |")
    md += ["", "## Weekday vs weekend (votes, all positions)", "", "| T | weekday | weekend |", "|---|---|---|"]
    for T in T_POST:
        Tk = f"{float(T):g}"
        wd = X[(X.kind == "votes") & (X["T"].astype(float) == float(T)) & (X.v > 0)]
        cell = lambda s: f"{(s.end / s.v).median():.2f} n {len(s)} ({s.day.nunique()})" if len(s) else "-"
        md.append(f"| {Tk} | {cell(wd[wd.wk == 0])} | {cell(wd[wd.wk == 1])} |")
    md += ["", "## Leave-one-day-out error of predicted day-end votes (median abs % error; launches with day-end >= 10)", "",
           "none = the read alone; T-only = one multiplier per T; fitted = per T x position x weekday/weekend.", "",
           "| kind | T | source | n (days) | none | T-only | fitted | fitted, top-10 positions |", "|---|---|---|---|---|---|---|---|"]
    for k, v in sorted(err.items(), key=lambda kv: (kv[0].split("|")[0] != "est", float(kv[0].split("|")[1]), kv[0].split("|")[2])):
        kind, T, src = k.split("|")
        md.append(f"| {kind} | {T} | {src} | {v['n']} ({v['days']}) | {v['none']} | {v['T_only']} | {v['fitted']} | {v['fitted_top10']} |")
    open(os.path.join(HERE, "results", "growth.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    if sys.argv[1] == "fit":
        fit()


def weekly_replay(days=("2026-11-04", "2026-11-09", "2026-11-10")):
    """the weekly call with the hand factors vs the fitted ones (fitted without the scored day): R0+4h votes x 1.069 vs x m;
    03:45 PT est_votes x 2 vs x m. Truth = the week-so-far order by day-end votes at the end of the scored day."""
    import weekly_live as WL, estvotes as EV
    from early_forecast import reveal
    X = pd.read_pickle(os.environ["GR_CACHE"]); res = []
    for d in days:
        tab = fit_table(X[X.day != d]); wk = int(pd.Timestamp(d).dayofweek >= 5)
        feat = set(WL.week_launches(WL.monday(d)).id)
        E = {r["id"]: r["est"] for r in WL.earlier(d) if r["id"] in feat}
        T = load_snaps(d); T = T[T.id.isin(snaps()[1].get(d, set()))]; end = dayend(d, T)
        truth = pd.Series({**E, **end.to_dict()}).sort_values(ascending=False).index.tolist()
        R0 = reveal(T); t4 = R0 + pd.Timedelta(hours=4); h4 = (t4 - t0(d)).total_seconds() / 3600
        V = T[T.ts <= t4].sort_values("ts").groupby("id").v.last(); rk = V.rank(ascending=False, method="first")
        cand = {"R4 x 1.069 (hand)": V * 1.069, "R4 x fitted m": pd.Series({i: v * lookup(h4, rk[i], wk, "votes", tab) for i, v in V.items()})}
        Ev, _ = EV.earlier_votes(d)
        if not Ev.empty:
            S = EV.est_votes(d, t0(d) + pd.Timedelta(hours=3.75), Ev)
            if len(S):
                s = S.set_index("id").est_votes; rk2 = s.rank(ascending=False, method="first")
                cand["03:45 est x 2 (hand)"] = s * 2
                cand["03:45 est x fitted m"] = pd.Series({i: v * lookup(3.75, rk2[i], wk, "est", tab) for i, v in s.items()})
        r = {"day": d, "week_launches": len(truth)}
        for nm, s in cand.items():
            o = pd.Series({**E, **s.to_dict()}).sort_values(ascending=False).index.tolist()
            r[nm] = [len(set(o[:k]) & set(truth[:k])) / k * 100 for k in (3, 5, 10)]
        res.append(r); print(json.dumps(r), flush=True)
    json.dump(res, open(os.path.join(HERE, "results", "growth_weekly_replay.json"), "w"), indent=1)
    return res


if __name__ == "__main__" and sys.argv[1] == "weekly_replay":
    weekly_replay()
