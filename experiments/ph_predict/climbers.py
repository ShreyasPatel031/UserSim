"""Late climbers (orchestrator 01:38Z Nov 13; REPLAY, counts only). Every finished day with an early post-reveal vote read:
early rank = order of votes at the first read fetched >= 04:00 PT (live posts_ts votes_at_fetch, else vote_snapshots).
climber = gains >= 4 places from the early rank to the final daily rank AND finishes top 10; fader = loses >= 4 places from
an early top-10 rank. 00:05-known features (z within day): clean_nosite (clean_live_rows_nosite), th_n_pre (non-hunter
commenters created <= 00:05, comments_ts + replies, hunter by post.user.id), team size (len(makers); the count does not
drift after 00:05), n topics. Maker follower counts are excluded (they need named makers = the positional leak).
(2) standardized differences climbers vs non-climbers with the same early-rank band (4-15), day bootstrap;
(3) leave-one-day-out ridge: z(-log final) ~ z(log early rank) [+ features]; top 5 / 10 vs early rank alone; then the same
fitted adjustment applied to the hidden rank at 03:00 PT on the 7 hidden-window days (prereveal_top5_10 constant 71.4 / 81.4).
usage: python climbers.py -> results/climbers.md + .json"""
import json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from early_forecast import B
import prior_blend as PB
from sklearn.linear_model import Ridge
TMP = os.environ.get("TMPDIR", "/tmp")


def get(path):
    p = tempfile.mkdtemp(dir=TMP) + "/" + os.path.basename(path)
    return p if subprocess.run(["gsutil", "-q", "cp", path, p], stderr=subprocess.DEVNULL).returncode == 0 else None


def early_votes(d, V):
    t4 = pd.Timestamp(d + " 04:00", tz="America/Los_Angeles").tz_convert("UTC")
    pp = get(f"{B}/raw/ph_at_launch/{d}/live/posts_ts.jsonl")
    if pp:
        R = []
        for l in open(pp):
            r = json.loads(l)
            if r.get("fetch_status") == 200 and r.get("votes_at_fetch") is not None and str(r.get("source", "")).startswith("ph_api_v2"):
                R.append((pd.Timestamp(r.get("fetched_at") or r["snapshot_ts"]), str(r["launch_id"]), float(r["votes_at_fetch"])))
        R = pd.DataFrame(R, columns=["a", "id", "v"]); R = R[R.a >= t4]
        if len(R):
            first = R.a.min(); R = R[R.a <= first + pd.Timedelta(minutes=20)]
            if R.v.sum() > 0:
                return R.sort_values("a").groupby("id").v.last(), "posts_ts", first
    g = V[(V.d == d) & (V.a >= t4)]
    if len(g):
        first = g.a.min(); g = g[g.a <= first + pd.Timedelta(minutes=20)]
        return g.sort_values("a").groupby("id").votes.last().astype(float), "vote_snapshots", first
    return None, None, None


def main():
    from pipeline import warehouse as W
    L = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank, makers, topics FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    V = W.query('SELECT "day" d, "at" a, CAST(launch_id AS VARCHAR) id, votes FROM vote_snapshots', do_sync=False); V["a"] = pd.to_datetime(V.a, utc=True)
    CL = pd.read_parquet(os.path.join(HERE, "results", "clean_live_rows_nosite.parquet")); CL["id"] = CL.id.astype(str)
    rows, info = [], {}
    for d in sorted(CL.day.unique()):
        g = L[L.day == d]
        if len(g) < 10:
            continue
        ev, src, first = early_votes(d, V)
        if ev is None:
            info[d] = "no early read"; continue
        ids = g.id.tolist(); E, nc, _ = PB.thread(d, ids)
        er = pd.Series({i: -ev.get(i, -1) for i in ids}).rank(method="first")
        cl = dict(zip(CL[CL.day == d].id, CL[CL.day == d].clean_v3_nosite))
        info[d] = {"early_source": src, "early_read_PT": first.tz_convert("America/Los_Angeles").strftime("%H:%M"), "launches": len(ids), "comments": nc > 0}
        for i, fr, mk, tp in zip(g.id, g.daily_rank, g.makers, g.topics):
            ms = json.loads(mk) if isinstance(mk, str) and mk.startswith("[") else []
            tps = json.loads(tp) if isinstance(tp, str) and tp.startswith("[") else (list(tp) if isinstance(tp, (list, np.ndarray)) else [])
            rows.append({"day": d, "id": i, "final": int(fr), "early": float(er[i]), "clean": cl.get(i, np.nan),
                         "npre": float(E.th_n_pre.get(i, np.nan)), "team": float(len(ms)), "ntopics": float(len(tps))})
    X = pd.DataFrame(rows)
    X["clean"] = X.groupby("day").clean.transform(lambda s: s.fillna(s.mean()))
    X["climber"] = ((X.early - X.final >= 4) & (X.final <= 10)).astype(int); X["fader"] = ((X.final - X.early >= 4) & (X.early <= 10)).astype(int)
    zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
    F = ["clean", "npre", "team", "ntopics"]
    for c in F + ["early"]:
        X["z_" + c] = X.groupby("day")[c].transform(zf if c != "early" else (lambda s: zf(np.log(s))))
    X["y"] = X.groupby("day").final.transform(lambda s: zf(-np.log(s)))
    days = sorted(X.day.unique()); rng = np.random.default_rng(0)
    md = [f"# Late climbers (REPLAY; {len(days)} days, {len(X)} launches; climbers {int(X.climber.sum())}, faders {int(X.fader.sum())})", "",
          f"Days: {json.dumps(info)}", "", "## Climbers vs non-climbers with early rank 4-15 (standardized difference, day bootstrap 95%)", "",
          "| feature | diff (climber - other) |", "|---|---|"]
    band = X[(X.early >= 4) & (X.early <= 15)]
    for c in F:
        def sd(S):
            a, b = S[S.climber == 1]["z_" + c], S[S.climber == 0]["z_" + c]
            return a.mean() - b.mean() if len(a) and len(b) else np.nan
        v = sd(band); bs = []
        for _ in range(2000):
            dd = rng.choice(days, len(days)); S = pd.concat([band[band.day == x] for x in dd]); bs.append(sd(S))
        md.append(f"| {c} | {v:+.2f} [{np.nanpercentile(bs, 2.5):+.2f}, {np.nanpercentile(bs, 97.5):+.2f}] |")
    def lodo(cols, data):
        out = []
        for d in days:
            te = data[data.day == d]; tr = data[data.day != d]; t = te.sort_values("final").id.tolist()
            sc = Ridge(alpha=3.0).fit(tr[cols], tr.y).predict(te[cols]) if cols != ["z_early"] or True else None
            o = te.assign(s=sc).sort_values(["s", "id"], ascending=[False, True]).id.tolist()
            out.append([len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)])
        return np.array(out)
    base = np.array([[len(set(g.sort_values(["early", "id"]).id[:k]) & set(g.sort_values("final").id[:k])) / k * 100 for k in (3, 5, 10)] for _, g in X.groupby("day")])
    md += ["", "## Leave-one-day-out, early read + features (top 3 / 5 / 10, paired vs early rank as is)", "", "| variant | top 3 | top 5 | top 10 |", "|---|---|---|---|"]
    md.append(f"| early rank as is | {base[:,0].mean():.1f} | {base[:,1].mean():.1f} | {base[:,2].mean():.1f} |")
    fits = {}
    for nm, cols in (("early only (ridge)", ["z_early"]), ("early + clean", ["z_early", "z_clean"]), ("early + all four", ["z_early"] + ["z_" + c for c in F])):
        P = lodo(cols, X); dP = P - base; b = np.array([dP[rng.integers(0, len(dP), len(dP))].mean(0) for _ in range(3000)])
        md.append(f"| {nm} | {P[:,0].mean():.1f} | {P[:,1].mean():.1f} ({dP[:,1].mean():+.1f} [{np.percentile(b[:,1],2.5):+.1f}, {np.percentile(b[:,1],97.5):+.1f}]) | {P[:,2].mean():.1f} ({dP[:,2].mean():+.1f} [{np.percentile(b[:,2],2.5):+.1f}, {np.percentile(b[:,2],97.5):+.1f}]) |")
        fits[nm] = Ridge(alpha=3.0).fit(X[cols], X.y)
    open(os.path.join(HERE, "results", "climbers.md"), "w").write("\n".join(md) + "\n")
    json.dump({"days": info, "n": int(len(X)), "climbers": int(X.climber.sum()), "faders": int(X.fader.sum()),
               "coef_all_four": dict(zip(["z_early"] + ["z_" + c for c in F], map(float, fits["early + all four"].coef_)))},
              open(os.path.join(HERE, "results", "climbers.json"), "w"), indent=1)
    print("\n".join(md))


if __name__ == "__main__":
    main()
