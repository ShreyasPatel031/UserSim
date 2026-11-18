"""Does the SHAPE of the first hours separate late builders from false favourites before the reveal? (orchestrator 08:45Z
Nov 12). Days with hourly hidden API ranks (vote_snapshots rank_now) and a live comment capture (live/comments_ts.jsonl).
Base = pred_rank_best at P3 (0.75 x hidden-rank position + 0.25 x published 00:05 LM position, 03:00 read).
Movement terms (all as of 03:00 PT, nothing later):
  d_rank     hidden-rank position at 01:00 minus at 03:00 (positive = rising)
  c_acc      top-level comments in (02:00, 03:00] minus in (00:00, 01:00]  (identity-free: excludes the first top-level
             author and the hunter)
  nt_share   share of comments by 03:00 not from the first top-level author or the hunter
Test: score = base position - beta x z(term) for each term alone and all three; beta chosen leave-one-day-out from
{0, 0.5, 1, 2, 4}. Metrics top 3 and #1-in-top-3 vs base, paired across days (n small: no intervals beyond the day range).
usage: python shape_test.py -> results/shape_test.md"""
import json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from early_forecast import B, lm_scores
TMP = os.environ.get("TMPDIR", "/tmp")


def comments(day):
    p = tempfile.mkdtemp(dir=TMP) + "/c.jsonl"
    if subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/ph_at_launch/{day}/live/comments_ts.jsonl", p]).returncode:
        return pd.DataFrame()
    rows, seen = [], set()
    for l in open(p):
        r = json.loads(l); cid = r.get("comment_id")
        if cid in seen or not r.get("created_at"):
            continue
        seen.add(cid)
        rows.append((str(r["launch_id"]), str(r.get("commenter_user_id") or ""), pd.Timestamp(r["created_at"]), r.get("parent_id")))
    return pd.DataFrame(rows, columns=["id", "user", "ts", "parent"])


def main():
    from pipeline import warehouse as W
    R = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    V = W.query('SELECT "day" d, "at" a, CAST(launch_id AS VARCHAR) id, rank_now FROM vote_snapshots', do_sync=False)
    V["a"] = pd.to_datetime(V.a, utc=True)
    rows = []
    for d in sorted(set(V.d) & set(R.day)):
        truth = R[R.day == d].sort_values("daily_rank").id.tolist()
        t0 = pd.Timestamp(d + " 00:00", tz="America/Los_Angeles").tz_convert("UTC")
        g = V[V.d == d]
        S1 = g[g.a <= t0 + pd.Timedelta(hours=1)].sort_values("a").groupby("id").rank_now.last()
        S3 = g[g.a <= t0 + pd.Timedelta(hours=3)].sort_values("a").groupby("id").rank_now.last()
        lm = lm_scores(d)
        if S1.empty or S3.empty or not lm or len(truth) < 10:
            continue
        C = comments(d)
        if C.empty:
            continue
        base_ids = sorted(truth)
        p1 = pd.Series({i: S1.get(i, 999) for i in base_ids}).rank(method="first")
        p3 = pd.Series({i: S3.get(i, 999) for i in base_ids}).rank(method="first")
        lmp = pd.Series({i: -lm.get(i, -99) for i in base_ids}).rank(method="first")
        C = C[C.ts <= t0 + pd.Timedelta(hours=3)]
        for i in base_ids:
            c = C[C.id == i].sort_values("ts"); tops = c[c.parent.isna()]
            fa = tops.user.iloc[0] if len(tops) else None
            nt = c[c.user != fa]; nt_top = nt[nt.parent.isna()]
            h = lambda a, b: int(((nt_top.ts > t0 + pd.Timedelta(hours=a)) & (nt_top.ts <= t0 + pd.Timedelta(hours=b))).sum())
            rows.append({"day": d, "id": i, "final": truth.index(i) + 1, "base": 0.75 * p3[i] + 0.25 * lmp[i],
                         "d_rank": p1[i] - p3[i], "c_acc": h(2, 3) - h(0, 1), "nt_share": len(nt) / len(c) if len(c) else 0.0})
    X = pd.DataFrame(rows)
    for c in ("d_rank", "c_acc", "nt_share"):
        X["z_" + c] = X.groupby("day")[c].transform(lambda s: (s - s.mean()) / (s.std() + 1e-9))
    X["z_all"] = X[["z_d_rank", "z_c_acc", "z_nt_share"]].mean(axis=1)
    days = sorted(X.day.unique()); BETAS = [0, 0.5, 1, 2, 4]
    def score(d, term, beta):
        g = X[X.day == d]; s = g.base - beta * g[term] if term else g.base
        o = g.assign(s=s).sort_values(["s", "id"]).id.tolist(); t = g.sort_values("final").id.tolist()
        return len(set(o[:3]) & set(t[:3])) / 3 * 100, float(o[0] in set(t[:3])) * 100
    md = [f"# Shape of the first hours vs late builders ({len(days)} days: {', '.join(days)})", "",
          "| variant | top 3 | #1 in top 3 | LODO betas |", "|---|---|---|---|"]
    b = np.array([score(d, None, 0) for d in days]); md.append(f"| pred_rank_best at P3 (base) | {b[:, 0].mean():.1f} | {b[:, 1].mean():.1f} | - |")
    for term in ("z_d_rank", "z_c_acc", "z_nt_share", "z_all"):
        res, picks = [], []
        for dh in days:
            bb = max(BETAS, key=lambda be: np.mean([sum(score(d, term, be)) for d in days if d != dh]))
            picks.append(bb); res.append(score(dh, term, bb))
        r = np.array(res)
        md.append(f"| base + {term[2:]} | {r[:, 0].mean():.1f} ({r[:, 0].mean() - b[:, 0].mean():+.1f}) | {r[:, 1].mean():.1f} ({r[:, 1].mean() - b[:, 1].mean():+.1f}) | {picks} |")
    late = X[(X.final <= 3)].assign(missed=lambda x: x.groupby("day").base.rank() > 3)
    md += ["", "Final top-3 launches, missed by the base vs caught (means): " +
           late.groupby("missed")[["d_rank", "c_acc", "nt_share"]].mean().round(2).to_string().replace("\n", "; ")]
    open(os.path.join(HERE, "results", "shape_test.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
