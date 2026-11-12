"""Monthly shadow line (orchestrator 22:45Z Nov 11), by hand in the checks; no pipeline change.
Input: Data Feeder's daily read (23:50 PT, official API) of every featured launch of the current month,
raw/ph_at_launch/monthly_reread/<YYYY-MM>/<read_date_PT>.jsonl (header line first; per launch: id, votesCount,
dailyRank, weeklyRank, monthlyRank, launch_day_PT).

  python monthly_live.py dayend <day>   after the <day> read exists: running monthly top 30 by (a) PH's running
                                        monthlyRank and (b) votes so far; plus a cross-check of weekly_live's dayend
                                        file for <day> against the read's weeklyRank / votes (top 3/5/10 overlap)
  python monthly_live.py score          after a month ends and the warehouse holds its final monthly_rank: score each
                                        file -> results/monthly_forecast_forward.jsonl
Writes results/monthly_live/<YYYY-MM>_<day>_dayend.json locally and to gs://.../results/monthly_live/ (written_at)."""
import glob, json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from early_forecast import B
OUT = os.path.join(HERE, "results", "monthly_live")


def read(day):
    """Day <day>'s day-end read (orchestrator 16:25Z Nov 12): rereads are keyed by their header fetched_at, not the file name;
    the earliest read fetched at or after <day>+1 00:00 PT is the day-end read; none -> (None, None) = "missing read"."""
    tmp = tempfile.mkdtemp(prefix='ml_'); closed = pd.Timestamp(day, tz="America/Los_Angeles") + pd.Timedelta(days=1)
    ls = subprocess.run(["gsutil", "ls", f"{B}/raw/ph_at_launch/monthly_reread/{day[:7]}/"], capture_output=True, text=True).stdout.split()
    best = None
    for u in sorted(x for x in ls if x.endswith(".jsonl")):
        p = os.path.join(tmp, os.path.basename(u))
        if subprocess.run(["gsutil", "-q", "cp", u, p]).returncode:
            continue
        h = json.loads(open(p).readline() or "{}")
        fa = h.get("fetched_at") if h.get("_header") else None
        if fa and pd.Timestamp(fa) >= closed and (best is None or pd.Timestamp(fa) < best[0]):
            best = (pd.Timestamp(fa), p)
    if best is None:
        return None, None
    rows = [json.loads(l) for l in open(best[1])]
    hdr = rows[0] if rows and rows[0].get("_header") else {}
    X = pd.DataFrame([r for r in rows if not r.get("_header")])
    X["id"] = X.id.astype(str)
    # orchestrator 04:25Z Nov 12: the re-read lists the 00:00 PT cohort twice (once under the previous day); keep one row per
    # id, the later launch day
    if "featuredAt" in X:   # day-boundary fix: day from featuredAt in PT (00:00 PT = 08:00:00Z belongs to the new day)
        from early_forecast import pt_day
        X["launch_day_PT"] = [pt_day({"featuredAt": f, "day": d0}) for f, d0 in zip(X.featuredAt, X.get("launch_day_PT", [None] * len(X)))]
    if "launch_day_PT" in X:
        X = X.sort_values("launch_day_PT").drop_duplicates("id", keep="last")
    return hdr, X


def topk_overlap(a, b, k):
    return len(set(a[:k]) & set(b[:k])) / k * 100


def dayend(day):
    hdr, X = read(day)
    if X is None:
        print(json.dumps({"day": day, "status": "missing read (no reread fetched after the day closed)"}))
        import heartbeat; heartbeat.beat("monthly dayend", day, None, "missing read"); return
    X = X[X.launch_day_PT <= day]
    # orchestrator 09:27Z Nov 12: a read taken before <day> ends leaves <day> partial and its same-day monthlyRank values are
    # placeholders: flag the day and drop those ranks from the monthlyRank order
    t_read = pd.Timestamp(hdr.get("fetched_at")) if hdr.get("fetched_at") else None
    day_end = pd.Timestamp(day + " 23:59:59", tz="America/Los_Angeles").tz_convert("UTC")
    early = t_read is not None and t_read < day_end - pd.Timedelta(minutes=30)
    partial = sorted(set(hdr.get("rate_limited_days_missing_or_partial") or []) | ({day} if early else set()))
    if early:
        X.loc[X.launch_day_PT == day, "monthlyRank"] = np.nan
    by_mr = X.dropna(subset=["monthlyRank"]).sort_values("monthlyRank").id.tolist()
    by_v = X.sort_values(["votesCount", "dailyRank"], ascending=[False, True]).id.tolist()
    res = {"month": day[:7], "day": day, "point": "dayend", "written_at": pd.Timestamp.now(tz="UTC").isoformat(),
           "read_fetched_at": hdr.get("fetched_at"), "read_rows": int(len(X)), "read_status": hdr.get("status"),
           "partial_days": partial, "read_time_PT": t_read.tz_convert("America/Los_Angeles").strftime("%Y-%m-%d %H:%M") if t_read is not None else None,
           "read_before_day_end": bool(early),
           "agree_mr_vs_votes": {k: topk_overlap(by_mr, by_v, k) for k in (3, 5, 10)},
           "forecast_monthlyRank": by_mr[:30], "forecast_votes": by_v[:30]}
    # weekly cross-check: weekly_live's dayend list for <day> vs this read's weeklyRank (and votes) within the week
    t = pd.Timestamp(day); mon = (t - pd.Timedelta(days=t.dayofweek)).strftime("%Y-%m-%d")
    wf = os.path.join(HERE, "results", "weekly_live", f"{mon}_{day}_dayend.json")
    if os.path.exists(wf):
        W = [r["id"] for r in sorted(json.load(open(wf))["forecast"], key=lambda r: r["pred_rank"])]
        Wk = X[(X.launch_day_PT >= mon) & (X.launch_day_PT <= day)]
        wr = Wk.dropna(subset=["weeklyRank"]).sort_values("weeklyRank").id.tolist()
        wv = Wk.sort_values("votesCount", ascending=False).id.tolist()
        res["weekly_crosscheck"] = {"vs_weeklyRank": {k: topk_overlap(W, wr, k) for k in (3, 5, 10)},
                                    "vs_votes_at_read": {k: topk_overlap(W, wv, k) for k in (3, 5, 10)}}
        # period-end-consistent weekly line (period_rank.md: PH's period ranks are votes frozen at the period end): rank the
        # week's launches so far by their votes in this 23:50 PT read; written in weekly_live's format as point "reread"
        Wr = Wk.sort_values("votesCount", ascending=False).reset_index(drop=True)
        wres = {"week_monday": mon, "day": day, "point": "reread", "written_at": res["written_at"], "launches": int(len(Wr)),
                "source": f"raw/ph_at_launch/monthly_reread/{day[:7]}/{day}.jsonl votesCount (read at {res['read_time_PT']} PT" + (", before the day ended: partial)" if early else ")"),
                "forecast": [{"id": i, "day": dd, "pred_rank": n + 1, "est": float(v), "src": "reread"} for n, (i, dd, v) in
                             enumerate(zip(Wr.id, Wr.launch_day_PT, Wr.votesCount)) if n < 30]}
        wp = os.path.join(HERE, "results", "weekly_live", f"{mon}_{day}_reread.json"); json.dump(wres, open(wp, "w"), indent=1)
        subprocess.run(["gsutil", "-q", "cp", wp, f"{B}/results/weekly_live/{mon}_{day}_reread.json"], check=True)
    os.makedirs(OUT, exist_ok=True); p = f"{OUT}/{day[:7]}_{day}_dayend.json"; json.dump(res, open(p, "w"), indent=1)
    subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/monthly_live/{day[:7]}_{day}_dayend.json"], check=True)
    import heartbeat; heartbeat.beat("monthly dayend", day, hdr.get("fetched_at"), "partial" if early else "ok")
    print(json.dumps({k: v for k, v in res.items() if not k.startswith("forecast")}))


def running(day):
    """PH's running monthlyRank after <day> ends (warehouse launches.monthly_rank after the next ranks step; orchestrator
    09:27Z Nov 12). Written like dayend (forecast_monthlyRank) as point "running"."""
    from pipeline import warehouse as W
    nxt = (pd.Timestamp(day) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    R = W.query("SELECT step, status, run_date FROM pipeline_runs", do_sync=True)
    if not len(R[(R.run_date.astype(str).str[:10] == nxt) & (R.step == "ranks") & (R.status == "ok")]):
        print(json.dumps({"day": day, "status": f"ranks step of {nxt} not finished"})); return
    L = W.query(f"SELECT CAST(id AS VARCHAR) id, day, monthly_rank FROM launches WHERE day >= '{day[:7]}-01' AND day <= '{day}' AND monthly_rank IS NOT NULL", do_sync=False)
    res = {"month": day[:7], "day": day, "point": "running", "written_at": pd.Timestamp.now(tz="UTC").isoformat(), "launches": int(len(L)),
           "source": f"warehouse launches.monthly_rank after the {nxt} ranks step", "forecast_monthlyRank": L.sort_values(["monthly_rank", "id"]).id.tolist()[:30]}
    os.makedirs(OUT, exist_ok=True); p = os.path.join(OUT, f"{day[:7]}_{day}_running.json"); json.dump(res, open(p, "w"), indent=1)
    subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/monthly_live/{day[:7]}_{day}_running.json"], check=True)
    import heartbeat; heartbeat.beat("monthly running", day, None, "ok")
    print(json.dumps({k: v for k, v in res.items() if k != "forecast_monthlyRank"}))


def score():
    from pipeline import warehouse as W
    fp = os.path.join(HERE, "results", "monthly_forecast_forward.jsonl")
    done = {(r["month"], r["day"]) for r in map(json.loads, open(fp))} if os.path.exists(fp) else set()
    for p in sorted(glob.glob(f"{OUT}/*.json")):
        F = json.load(open(p)); m = F["month"]
        if (m, F["day"]) in done:
            continue
        end = (pd.Timestamp(m + "-01") + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d")
        if pd.Timestamp.now(tz="America/Los_Angeles").strftime("%Y-%m-%d") <= end:
            continue
        L = W.query(f"SELECT CAST(id AS VARCHAR) id, day, monthly_rank FROM launches WHERE day >= '{m}-01' AND day <= '{end}' AND monthly_rank IS NOT NULL", do_sync=False)
        if L.empty:
            continue
        truth = L.sort_values("monthly_rank").id.tolist(); launched = L[L.day <= F["day"]].sort_values("monthly_rank").id.tolist()
        r = {"month": m, "day": F["day"], "written_at": F["written_at"]}
        for nm in ("monthlyRank", "votes"):
            for k in (3, 5, 10):
                r[f"{nm}_month_top{k}"] = topk_overlap(F[f"forecast_{nm}"], truth, k)
                r[f"{nm}_launched_top{k}"] = topk_overlap(F[f"forecast_{nm}"], launched, k)
        for k in (3, 5, 10):
            r[f"reach{k}"] = len(set(truth[:k]) & set(L[L.day <= F["day"]].id)) / k * 100
        open(fp, "a").write(json.dumps(r) + "\n"); print(json.dumps(r))


if __name__ == "__main__":
    a = sys.argv[1:]
    {"dayend": lambda: dayend(a[1]), "score": score, "running": lambda: running(a[1])}[a[0]]()
