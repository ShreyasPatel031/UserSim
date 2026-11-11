"""Votes on comments before the reveal (orchestrator 01:30Z Nov 12). While post votes are hidden, the official API's
per-snapshot comment reads (raw/ph_at_launch/<day>/api_comments/<YYYYMMDD>T<HHMM>PT.jsonl: post_id, comment_id,
commenter_user_id, createdAt, parentId, votesCount at that read) give a dated engagement count. The backtest dump only has
final-time comment votes, so these exist only on live days.

features(day, T) -> per launch id, from the latest snapshot file read at or before T (and the one at or before T - 1 h):
  cv_sum        sum of comment votes            cv_max       max votes on one comment
  cv_maker1     votes on the team's earliest comment (team = people_ts makers + hunter user ids)
  cv_per_out    votes on non-team comments / number of non-team comments
  cv_growth1h   cv_sum now - cv_sum one hour earlier (0 if no earlier read)
  cv_snapshot   the read used (PT label)
Also: dump_mismatch(day, T) - share of comments created by T that sit in threads outside the top 50 threads by
end-of-day votes (what the top-50-thread page dump used for training would have missed).
usage: python comment_votes.py replay <dry dir> -> results/comment_votes_replay.json (per day, no intervals)"""
import glob, json, os, re, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
_C = {}


def snaps(day):
    if day in _C:
        return _C[day]
    tmp = tempfile.mkdtemp(prefix="cv_")
    subprocess.run(["gsutil", "-q", "-m", "cp", f"{B}/raw/ph_at_launch/{day}/api_comments/*.jsonl", tmp + "/"], capture_output=True)
    rows = []
    for f in sorted(glob.glob(f"{tmp}/*.jsonl")):
        m = re.search(r"(\d{8})T(\d{4})PT", f)
        if not m:
            continue
        t = pd.Timestamp(f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]} {m.group(2)[:2]}:{m.group(2)[2:]}", tz="America/Los_Angeles").tz_convert("UTC")
        for l in open(f):
            r = json.loads(l)
            rows.append((t, m.group(0), str(r.get("post_id")), str(r.get("comment_id")), str(r.get("commenter_user_id") or ""),
                         r.get("createdAt"), r.get("parentId"), float(r.get("votesCount") or 0)))
    X = pd.DataFrame(rows, columns=["t", "label", "id", "cid", "uid", "created", "parent", "v"])
    if len(X):
        X["created"] = pd.to_datetime(X.created, utc=True, errors="coerce")
    tm = {}
    p = f"{tmp}/people.jsonl"
    if subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/ph_at_launch/{day}/live/people_ts.jsonl", p]).returncode == 0:
        for l in open(p):
            r = json.loads(l)
            for i in r.get("launch_ids") or []:
                if r.get("user_id"):
                    tm.setdefault(str(i), set()).add(str(r["user_id"]))
    _C[day] = (X, tm)
    return _C[day]


def _at(X, T):
    ok = X[X.t <= T]
    if ok.empty:
        return ok, None
    t = ok.t.max(); return ok[ok.t == t].drop_duplicates("cid"), ok[ok.t == t].label.iloc[0]


def features(day, T):
    X, tm = snaps(day)
    if X.empty:
        return pd.DataFrame()
    S, lab = _at(X, T)
    if S.empty:
        return pd.DataFrame()
    S = S[S.created <= T]
    P, _ = _at(X, T - pd.Timedelta(hours=1))
    prev = P[P.created <= T - pd.Timedelta(hours=1)].groupby("id").v.sum() if len(P) else pd.Series(dtype=float)
    out = []
    for i, g in S.groupby("id"):
        team = tm.get(i, set()); it = g.uid.isin(team); o = g[~it]
        first = g[it].sort_values("created").head(1)
        out.append({"id": i, "cv_sum": g.v.sum(), "cv_max": g.v.max(), "cv_maker1": float(first.v.iloc[0]) if len(first) else 0.0,
                    "cv_per_out": float(o.v.sum() / len(o)) if len(o) else 0.0, "cv_growth1h": float(g.v.sum() - prev.get(i, 0.0)) if len(prev) else 0.0,
                    "cv_snapshot": lab})
    return pd.DataFrame(out)


def dump_mismatch(day, T):
    """share of comments created by T in threads outside the top 50 threads (by votes at the day's last read)."""
    X, _ = snaps(day)
    if X.empty:
        return None
    L = X[X.t == X.t.max()].drop_duplicates("cid")
    top = L[L.parent.isna()].copy(); top["r"] = top.groupby("id").v.rank(ascending=False, method="first")
    keep = set(top[top.r <= 50].cid)
    root = dict(zip(L.cid, L.parent.fillna(L.cid)))
    E = L[L.created <= T]
    inside = [(root.get(c) or c) in keep for c in E.cid]
    return {"comments_by_T": int(len(E)), "outside_top50_threads": int(len(E) - sum(inside)),
            "share_outside": round(1 - (sum(inside) / len(E)), 4) if len(E) else None}


def replay(dry):
    from pipeline import warehouse as W
    from early_forecast import lm_scores
    R = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    res = []
    for d in ("2026-11-04", "2026-11-08", "2026-11-10"):
        rk = R[R.day == d].set_index("id").daily_rank; lm = lm_scores(d)
        real = lambda k: set(rk.nsmallest(k).index)
        for h in (1, 2, 3, 4):
            T = pd.Timestamp(d + " 00:00", tz="America/Los_Angeles").tz_convert("UTC") + pd.Timedelta(hours=h)
            Fv = features(d, T)
            row = {"day": d, "point": f"P{h}", "snapshot": None if Fv.empty else Fv.cv_snapshot.iloc[0], "dump_mismatch": dump_mismatch(d, T)}
            ids = list(rk.index)
            G = pd.DataFrame({"id": ids}); G["lm"] = [lm.get(i, -99) for i in ids]
            if not Fv.empty:
                G = G.merge(Fv.drop(columns="cv_snapshot"), on="id", how="left").fillna(0)
                for c in ("cv_sum", "cv_max", "cv_maker1", "cv_per_out", "cv_growth1h"):
                    s = G[c] + 1e-6 * G.lm
                    row[c] = [len(set(G.loc[s.nlargest(k).index].id) & real(k)) / k * 100 for k in (3, 5, 10)]
            pf = os.path.join(dry, f"{d}_P{h}.json")
            if os.path.exists(pf):
                F = pd.DataFrame(json.load(open(pf))["forecast"])
                for nm, c in (("ridge", "pred_rank"), ("api", "pred_rank_api"), ("blend", "pred_rank_blend")):
                    if c in F:
                        o = F.sort_values(c).id.astype(str).tolist()
                        row[nm] = [len(set(o[:k]) & real(k)) / k * 100 for k in (3, 5, 10)]
            row["LM"] = [len(set(G.sort_values("lm", ascending=False).id[:k]) & real(k)) / k * 100 for k in (3, 5, 10)]
            res.append(row); print(json.dumps(row))
    json.dump(res, open(os.path.join(HERE, "results", "comment_votes_replay.json"), "w"), indent=1)


if __name__ == "__main__":
    if sys.argv[1] == "replay":
        replay(sys.argv[2])
