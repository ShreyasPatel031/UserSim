"""Weekly shadow line (orchestrator 21:35Z Nov 11), by hand in the checks; no pipeline change.
Week = Monday 00:00 - Sunday 23:59 PT; final weekly rank = warehouse launches.weekly_rank once the week is over.

  python weekly_live.py dayend <day>   after 23:59 PT of <day>: running weekly top 10 by day-end votes of the week's
                                       launches of days <= <day> (the Sunday file is the end-of-week call)
  python weekly_live.py r4 <day>       at <day>'s R0+4h: earlier days by day-end votes + <day>'s launches by projected
                                       day-end votes = votes at R0+4h x the median day-end / R0+4h ratio (fit below)
  python weekly_live.py fit            the ratio, from days whose live capture covers the reveal and the day end
  python weekly_live.py score          score every written file of finished weeks -> results/weekly_forecast_forward.jsonl

Day-end votes: latest live/posts_ts.jsonl votes_at_fetch fetched at or before 23:59:59 PT of the launch day (official
API rows, fetch 200); fallback warehouse vote_snapshots (latest "at" <= day end). Writes
results/weekly_live/<monday>_<day>_<point>.json locally and to gs://.../results/weekly_live/ with written_at."""
import json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from early_forecast import B, load_snaps, reveal
OUT = os.path.join(HERE, "results", "weekly_live")
RATIO_F = os.path.join(HERE, "results", "weekly_live_ratio.json")


def day_end(d):
    return pd.Timestamp(d + " 23:59:59", tz="America/Los_Angeles").tz_convert("UTC")


def monday(d):
    t = pd.Timestamp(d); return (t - pd.Timedelta(days=t.dayofweek)).strftime("%Y-%m-%d")


def posts(d):
    tmp = tempfile.mkdtemp(prefix="wl_"); p = f"{tmp}/p.jsonl"
    if subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/ph_at_launch/{d}/live/posts_ts.jsonl", p]).returncode:
        return pd.DataFrame(columns=["fa", "id", "v"])
    rows = []
    for l in open(p):
        r = json.loads(l)
        if r.get("fetch_status") == 200 and str(r.get("source", "")).startswith("ph_api_v2") and str(r.get("day", d)) == d and r.get("votes_at_fetch") is not None:
            rows.append((pd.Timestamp(r.get("fetched_at") or r["snapshot_ts"]), str(r["launch_id"]), float(r["votes_at_fetch"])))
    return pd.DataFrame(rows, columns=["fa", "id", "v"])


MIDNIGHT_READ = pd.Timedelta(minutes=6)   # orchestrator 04:25Z Nov 12: the official daily rank = votes at midnight PT; use the
                                          # 00:01 PT read (fetched by 00:06) when held, else the last read before midnight


def dayend_votes(d):
    P = posts(d); e = day_end(d) + MIDNIGHT_READ
    # only launches read before midnight: the 00:01 snapshot also carries the NEW day's launches tagged with this day (0 votes)
    ids = set(P[P.fa <= day_end(d)].id)
    V = P[(P.fa <= e) & P.id.isin(ids)].sort_values("fa").groupby("id").v.last()
    src = {i: "posts_ts" for i in V.index}
    from pipeline import warehouse as W
    S = W.query(f"SELECT \"at\" AS at, CAST(launch_id AS VARCHAR) id, votes FROM vote_snapshots WHERE \"day\" = '{d}'", do_sync=False)
    if len(S):
        S["at"] = pd.to_datetime(S["at"], utc=True); S = S[S["at"] <= e].sort_values("at").groupby("id").votes.last()
        for i, v in S.items():
            if i not in V.index:
                V[i] = float(v); src[i] = "vote_snapshots"
    return V, src


def week_launches(mon):
    from pipeline import warehouse as W
    end = (pd.Timestamp(mon) + pd.Timedelta(days=6)).strftime("%Y-%m-%d")
    return W.query(f"SELECT CAST(id AS VARCHAR) id, day, weekly_rank FROM launches WHERE day >= '{mon}' AND day <= '{end}'", do_sync=False)


def write(day, point, A, extra):
    mon = monday(day); now = pd.Timestamp.now(tz="UTC")
    feat = set(week_launches(mon).id)   # competitors = the week's featured (daily-ranked) launches in the warehouse
    n_all = len(A); A = A[A.id.isin(feat)]; extra = {**extra, "dropped_not_featured": int(n_all - len(A))}
    A = A.sort_values("est", ascending=False).reset_index(drop=True); A["pred_rank"] = np.arange(1, len(A) + 1)
    res = {"week_monday": mon, "day": day, "point": point, "written_at": now.isoformat(), "launches": int(len(A)), **extra,
           "forecast": A.head(30)[["id", "day", "pred_rank", "est", "src"]].round(2).to_dict("records")}
    os.makedirs(OUT, exist_ok=True); p = f"{OUT}/{mon}_{day}_{point}.json"; json.dump(res, open(p, "w"), indent=1)
    subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/weekly_live/{mon}_{day}_{point}.json"], check=True)
    print(json.dumps({k: v for k, v in res.items() if k != "forecast"}))


def earlier(day):
    mon = monday(day); rows = []
    for d in pd.date_range(mon, day, inclusive="left").strftime("%Y-%m-%d"):
        V, src = dayend_votes(d)
        rows += [{"id": i, "day": d, "est": v, "src": src[i]} for i, v in V.items()]
    return rows


def dayend(day):
    if pd.Timestamp.now(tz="UTC") <= day_end(day):
        print(json.dumps({"day": day, "status": "day not over"})); return
    V, src = dayend_votes(day)
    rows = earlier(day) + [{"id": i, "day": day, "est": v, "src": src[i]} for i, v in V.items()]
    A = pd.DataFrame(rows)
    write(day, "dayend", A, {"days_covered": sorted(A.day.unique().tolist()), "sunday_call": pd.Timestamp(day).dayofweek == 6})


def r4(day):
    T = load_snaps(day); R0 = reveal(T)
    if R0 is None:
        print(json.dumps({"day": day, "status": "no reveal yet"})); return
    t = R0 + pd.Timedelta(hours=4)
    if pd.Timestamp.now(tz="UTC") < t or T.ts.max() < t:
        print(json.dumps({"day": day, "status": f"R0+4h {t} not reached"})); return
    # orchestrator 02:30Z Nov 12: fitted day-end multiplier by T x leader position x weekday/weekend (growth.md) replaces
    # the single ratio (kept in the file for reference); LODO weekly replay: results/growth_weekly_replay.json
    import growth
    ratio = json.load(open(RATIO_F))["ratio_dayend_over_R4"]
    V = T[T.ts <= t].sort_values("ts").groupby("id").v.last()
    V = V[V.index.isin(set(week_launches(monday(day)).id))]
    th = (t - pd.Timestamp(day + " 00:00", tz="America/Los_Angeles").tz_convert("UTC")).total_seconds() / 3600
    X = growth.exp_final(V, th, pd.Timestamp(day).dayofweek >= 5, "votes")
    rows = earlier(day) + [{"id": i, "day": day, "est": X[i], "src": "R0+4h x fitted m"} for i in V.index]
    A = pd.DataFrame(rows)
    write(day, "R4", A, {"days_covered": sorted(A.day.unique().tolist()), "data_up_to": t.isoformat(), "factor": "growth.json (T x position x weekday/weekend)",
                         "old_ratio": ratio})


def est(day):
    """mid-day call at 03:45 PT, before the reveal: earlier days by day-end votes + today's launches by est_votes x the
    fitted multiplier at 3.75 h (growth.md). Not on Mondays (no earlier-day launches to bracket against)."""
    import growth, estvotes as EV
    t = pd.Timestamp(day + " 03:45", tz="America/Los_Angeles").tz_convert("UTC")
    if pd.Timestamp.now(tz="UTC") < t:
        print(json.dumps({"day": day, "status": f"{t} not reached"})); return
    E, src = EV.earlier_votes(day)
    if E.empty:
        print(json.dumps({"day": day, "status": f"no est_votes ({src})"})); return
    S = EV.est_votes(day, t, E)
    if S.empty:
        print(json.dumps({"day": day, "status": "no weekly ranks read by 03:45 PT"})); return
    s = S.set_index("id").est_votes; s = s[s.index.isin(set(week_launches(monday(day)).id))]
    X = growth.exp_final(s, 3.75, pd.Timestamp(day).dayofweek >= 5, "est")
    rows = earlier(day) + [{"id": i, "day": day, "est": X[i], "src": "est_votes x fitted m"} for i in s.index]
    A = pd.DataFrame(rows)
    write(day, "est", A, {"days_covered": sorted(A.day.unique().tolist()), "data_up_to": t.isoformat(), "earlier_source": src,
                          "factor": "growth.json est (3.75 h x position x weekday/weekend)"})


def fit():
    out = {}
    for d in ("2026-11-04", "2026-11-08", "2026-11-09", "2026-11-10"):
        T = load_snaps(d); R0 = reveal(T)
        if R0 is None:
            continue
        v4 = T[T.ts <= R0 + pd.Timedelta(hours=4)].sort_values("ts").groupby("id").v.last()
        V, _ = dayend_votes(d)
        j = v4[v4 >= 5].index.intersection(V.index)
        out[d] = (V[j] / v4[j]).tolist()
    allr = np.concatenate([np.array(v) for v in out.values()])
    res = {"ratio_dayend_over_R4": round(float(np.median(allr)), 4), "p10_p90": [round(float(x), 3) for x in np.percentile(allr, [10, 90])],
           "days": {d: round(float(np.median(v)), 3) for d, v in out.items()}, "launches": int(len(allr))}
    json.dump(res, open(RATIO_F, "w"), indent=1); print(json.dumps(res))


def score():
    import glob
    done = set()
    fp = os.path.join(HERE, "results", "weekly_forecast_forward.jsonl")
    if os.path.exists(fp):
        done = {(r["week_monday"], r["day"], r["point"]) for r in map(json.loads, open(fp))}
    for p in sorted(glob.glob(f"{OUT}/*.json")):
        F = json.load(open(p)); key = (F["week_monday"], F["day"], F["point"])
        if key in done or pd.Timestamp.now(tz="UTC") <= day_end((pd.Timestamp(F["week_monday"]) + pd.Timedelta(days=6)).strftime("%Y-%m-%d")) + pd.Timedelta(hours=8):
            continue
        L = week_launches(F["week_monday"]).dropna(subset=["weekly_rank"])
        if L.day.nunique() < 7:
            continue
        pr = pd.DataFrame(F["forecast"])
        r = {"week_monday": F["week_monday"], "day": F["day"], "point": F["point"], "written_at": F["written_at"]}
        launched = L[L.day <= F["day"]]
        for k in (3, 5, 10):
            pk = set(pr.nsmallest(k, "pred_rank").id)
            r[f"week_top{k}"] = len(pk & set(L.nsmallest(k, "weekly_rank").id)) / k * 100
            r[f"launched_top{k}"] = len(pk & set(launched.nsmallest(k, "weekly_rank").id)) / k * 100
            r[f"reach{k}"] = len(set(L.nsmallest(k, "weekly_rank").id) & set(launched.id)) / k * 100
        open(fp, "a").write(json.dumps(r) + "\n"); print(json.dumps(r))


if __name__ == "__main__":
    a = sys.argv[1:]
    {"dayend": lambda: dayend(a[1]), "r4": lambda: r4(a[1]), "est": lambda: est(a[1]), "fit": fit, "score": score}[a[0]]()
