"""Accuracy-by-time after the reveal (orchestrator 02:36Z Nov 13; held data only; counts only).
Data: live 15-min feed raw/ph_at_launch/<d>/live/posts_ts.jsonl (votes_at_fetch, daily_rank_at_fetch, hide_votes_count) for
every day that has it; truth = warehouse launches.daily_rank. A point t is used on a day only if that day has a snapshot within
20 min before t (gaps are skipped, days per point reported).
  plain   order by latest votes at <= t; while counts are hidden (before the reveal), the API's hidden rank
  model   leave-one-day-out ridge on z(log1p votes or -log hidden rank), z(clean_nosite 00:05), z(log1p votes in last 30 min),
          z(log1p votes in last 60 min) -> z(-log final rank)
Reveal time per day = first snapshot where >= half the launches show non-zero votes (early_forecast.reveal).
Climbers = final top 10 launches outside the plain top 10 at t; reported: how many the model puts in its top 10 vs plain (0).
usage: python reveal_curve.py -> results/reveal_curve.md"""
import json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from early_forecast import B, pt_day
from sklearn.linear_model import Ridge
PTS = ["03:15", "03:30", "04:00", "04:30", "05:00", "06:00", "08:00", "10:00", "12:00", "16:00", "20:00"]


def load(day, tmp):
    p = f"{tmp}/{day}.jsonl"
    if subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/ph_at_launch/{day}/live/posts_ts.jsonl", p], stderr=subprocess.DEVNULL).returncode:
        return None
    rows = []
    for l in open(p):
        r = json.loads(l)
        if str(r.get("fetch_status")) == "200" and pt_day(r, day) == day:
            hr = r.get("daily_rank_at_fetch")
            rows.append((pd.Timestamp(r["snapshot_ts"]), str(r["launch_id"]), float(r.get("votes_at_fetch") or 0),
                         float(hr) if hr not in (None, "None", "") else np.nan))
    T = pd.DataFrame(rows, columns=["ts", "id", "v", "hr"]) if rows else None
    return T if T is not None and T.ts.nunique() >= 10 else None   # single late backfill reads (Oct days) are not a live feed


def load_vs(day, VS):
    """Fallback: hourly vote_snapshots (pipeline/hourly.py own reads); rank_now = API rank (hidden rank before the reveal)."""
    g = VS[VS.d == day]
    return g.rename(columns={"a": "ts"})[["ts", "id", "v", "hr"]].copy() if g.a.nunique() >= 10 else None


def main():
    from pipeline import warehouse as W
    Q = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank FROM launches WHERE daily_rank IS NOT NULL AND day >= '2026-10-26'", do_sync=False)
    CL = pd.read_parquet(os.path.join(HERE, "results", "clean_live_rows_nosite.parquet")); CL["id"] = CL.id.astype(str)
    cl = dict(zip(CL.id, CL.clean_v3_nosite)); tmp = tempfile.mkdtemp(dir=os.environ.get("TMPDIR", "/tmp"))
    VS = W.query('SELECT "day" d, "at" a, CAST(launch_id AS VARCHAR) id, CAST(votes AS DOUBLE) v, CAST(rank_now AS DOUBLE) hr FROM vote_snapshots', do_sync=False)
    VS["a"] = pd.to_datetime(VS.a, utc=True)
    rows, rev, src = [], {}, {}
    import prior_blend as PB
    CC, NP = {}, {}
    for d in sorted(Q.day.unique()):
        cp_ = subprocess.run(["gsutil", "-q", "cat", f"{B}/raw/ph_at_launch/{d}/live/comments_ts.jsonl"], capture_output=True, text=True)
        if cp_.returncode == 0 and cp_.stdout:
            c_ = pd.DataFrame([json.loads(l) for l in cp_.stdout.splitlines() if l.strip()]).drop_duplicates("comment_id")
            CC[d] = pd.DataFrame({"id": c_.launch_id.astype(str), "ts": pd.to_datetime(c_.created_at, utc=True, errors="coerce")})
        try:
            E_, _, _ = PB.thread(d, Q[Q.day == d].id.tolist()); NP[d] = E_.th_n_pre.to_dict()
        except Exception:
            NP[d] = {}
    for d in sorted(Q.day.unique()):
        T = load(d, tmp); src[d] = "15min"
        if T is None:
            T = load_vs(d, VS); src[d] = "hourly"
        if T is None:
            continue
        g = T.groupby("ts").v.apply(lambda x: (x > 0).mean()).sort_index(); ok = g[g >= 0.5]
        R0 = ok.index.min() if len(ok) else None
        rev[d] = R0.tz_convert("America/Los_Angeles").strftime("%H:%M") if R0 is not None else None
        fin = Q[Q.day == d].set_index("id").daily_rank
        base = pd.Timestamp(d, tz="America/Los_Angeles")
        for pt in PTS:
            t = (base + pd.Timedelta(hours=int(pt[:2]), minutes=int(pt[3:]))).tz_convert("UTC")
            S = T[T.ts <= t]
            if not len(S) or (t - S.ts.max()) > pd.Timedelta(minutes=20):
                continue
            last = S.sort_values("ts").groupby("id").last()
            def ago(m):
                return T[T.ts <= t - pd.Timedelta(minutes=m)].sort_values("ts").groupby("id").v.last().reindex(last.index).fillna(0)
            A = last.assign(v30=last.v - ago(30), v60=last.v - ago(60)).reset_index()
            A = A[A.id.isin(fin.index)]
            if len(A) < 10:
                continue
            revealed = R0 is not None and t >= R0
            A["key"] = np.log1p(A.v) if revealed else -np.log(A.hr.fillna(A.hr.max() + 1 if A.hr.notna().any() else 99))
            A["clean"] = A.id.map(cl); A["clean"] = A.clean.fillna(A.clean.min() if A.clean.notna().any() else 0)
            A["l30"] = np.log1p(A.v30.clip(lower=0)); A["l60"] = np.log1p(A.v60.clip(lower=0))
            A["fr"] = A.id.map(fin); A["day"] = d; A["pt"] = pt; A["revealed"] = revealed
            H3 = T[T.ts <= (base + pd.Timedelta(hours=3, minutes=45)).tz_convert("UTC")].sort_values("ts").groupby("id").hr.last()
            A["h345"] = -np.log(A.id.map(H3).fillna(H3.max() + 1 if len(H3) and H3.notna().any() else 99))
            A["nc"] = np.log1p(A.id.map(CC.get(d, pd.DataFrame(columns=["id", "ts"])).pipe(lambda c: c[c.ts <= t].groupby("id").size())).fillna(0))
            A["npre"] = A.id.map(NP.get(d, {})).fillna(0)
            rows.append(A)
    X = pd.concat(rows, ignore_index=True)
    zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
    for c in ("key", "clean", "l30", "l60", "h345", "nc", "npre"):
        X["z_" + c] = X.groupby(["day", "pt"])[c].transform(zf)
    X["y"] = X.groupby(["day", "pt"]).fr.transform(lambda s: zf(-np.log(s)))
    rng = np.random.default_rng(0)
    def hits(o, t):
        return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
    md = [f"# Accuracy by time after the reveal (live 15-min feed, hourly vote_snapshots where the feed is missing ({sum(src[d] == 'hourly' for d in set(X.day))} days; their 30-min velocity is the previous hourly read); {X.day.nunique()} days {X.day.min()}..{X.day.max()})", "",
          "Reveal time (first snapshot with >= half the launches showing votes), PT: " + ", ".join(f"{d[5:]} {r}{'' if src[d] == '15min' else ' (hourly)'}" for d, r in rev.items() if d in set(X.day)), "",
          "| point | days | revealed days | plain top 3 | plain top 5 | plain top 10 | model top 3 | model top 5 | model top 10 | model - plain (3 / 5 / 10, 95%) | climbers caught (model vs plain 0) |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    cross = {3: None, 10: None}; VAR = {"+ clean": ["z_key", "z_clean"], "+ velocity 30/60": ["z_key", "z_l30", "z_l60"]}
    extra = []
    for pt in PTS:
        G = X[X.pt == pt]
        if not len(G):
            continue
        days = sorted(G.day.unique()); P, M, ccount, ctot, V = [], [], 0, 0, {k: [] for k in VAR}
        for d in days:
            te, tr = G[G.day == d], G[G.day != d]; t = te.sort_values("fr").id.tolist()
            o = te.sort_values(["key", "id"], ascending=[False, True]).id.tolist(); P.append(hits(o, t))
            cols = ["z_key", "z_clean", "z_l30", "z_l60"]
            m = te.assign(s=Ridge(alpha=3.0).fit(tr[cols], tr.y).predict(te[cols]) if len(tr) else te.z_key).sort_values(["s", "id"], ascending=[False, True]).id.tolist()
            M.append(hits(m, t)); cl_ = set(t[:10]) - set(o[:10]); ctot += len(cl_); ccount += len(cl_ & set(m[:10]))
            for k, c in VAR.items():
                v = te.assign(s=Ridge(alpha=3.0).fit(tr[c], tr.y).predict(te[c]) if len(tr) else te.z_key).sort_values(["s", "id"], ascending=[False, True]).id.tolist()
                V[k].append(hits(v, t))
        P, M = np.array(P), np.array(M); dP = M - P
        b = np.array([dP[rng.integers(0, len(dP), len(dP))].mean(0) for _ in range(2000)])
        md.append(f"| {pt} | {len(days)} | {int(G.groupby('day').revealed.first().sum())} | {P[:,0].mean():.1f} | {P[:,1].mean():.1f} | {P[:,2].mean():.1f} | "
                  f"{M[:,0].mean():.1f} | {M[:,1].mean():.1f} | {M[:,2].mean():.1f} | " +
                  " / ".join(f"{dP[:,k].mean():+.1f} [{np.percentile(b[:,k],2.5):+.1f}, {np.percentile(b[:,k],97.5):+.1f}]" for k in range(3)) +
                  f" | {ccount} of {ctot} |")
        extra.append(f"| {pt} | " + " | ".join(f"{(np.array(V[k]) - P).mean(0)[0]:+.1f} / {(np.array(V[k]) - P).mean(0)[1]:+.1f} / {(np.array(V[k]) - P).mean(0)[2]:+.1f}" for k in VAR) + " |")
        for k, i in ((3, 0), (10, 2)):
            if cross[k] is None and max(P[:, i].mean(), M[:, i].mean()) >= 90:
                cross[k] = f"{pt} ({'plain' if P[:, i].mean() >= 90 else 'model'})"
    md += ["", "Split of the model gain (diff vs plain, top 3 / 5 / 10):", "", "| point | " + " | ".join(VAR) + " |", "|---|---|---|"] + extra
    # orchestrator 02:39Z Nov 13: the weak 04:00-05:00 window: vote order + clean + th_n_pre + comments so far + hidden rank at 03:45
    WV = {"votes + clean + th_n_pre + comments": ["z_key", "z_clean", "z_npre", "z_nc"],
          "+ hidden rank at 03:45": ["z_key", "z_clean", "z_npre", "z_nc", "z_h345"], "votes + hidden rank at 03:45 only": ["z_key", "z_h345"]}
    md += ["", "Weak window (revealed days only; diff vs plain vote order, 95% day bootstrap):", "",
           "| point | days | plain t3/t5/t10 | " + " | ".join(WV) + " |", "|---|---|---|" + "---|" * len(WV)]
    for pt in ("04:00", "04:30", "05:00"):
        G = X[(X.pt == pt) & X.revealed]; days = sorted(G.day.unique())
        if len(days) < 3:
            continue
        P = []; R = {k: [] for k in WV}
        for d in days:
            te, tr = G[G.day == d], G[G.day != d]; t = te.sort_values("fr").id.tolist()
            P.append(hits(te.sort_values(["key", "id"], ascending=[False, True]).id.tolist(), t))
            for k, c in WV.items():
                R[k].append(hits(te.assign(s=Ridge(alpha=3.0).fit(tr[c], tr.y).predict(te[c])).sort_values(["s", "id"], ascending=[False, True]).id.tolist(), t))
        P = np.array(P); cells = []
        for k in WV:
            dP = np.array(R[k]) - P; b = np.array([dP[rng.integers(0, len(dP), len(dP))].mean(0) for _ in range(2000)])
            cells.append(" / ".join(f"{dP[:,j].mean():+.1f} [{np.percentile(b[:,j],2.5):+.1f}, {np.percentile(b[:,j],97.5):+.1f}]" for j in range(3)))
        md.append(f"| {pt} | {len(days)} | {P[:,0].mean():.1f} / {P[:,1].mean():.1f} / {P[:,2].mean():.1f} | " + " | ".join(cells) + " |")
    md += ["", f"Earliest point with mean top 3 >= 90%: {cross[3] or 'not reached by 20:00'}; top 10 >= 90%: {cross[10] or 'not reached by 20:00'}"]
    open(os.path.join(HERE, "results", "reveal_curve.md"), "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
