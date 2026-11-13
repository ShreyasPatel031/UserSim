"""Near-miss tie-break at 00:05 (orchestrator 01:43Z Nov 13; backtest, counts only). Base = clean_nosite (tw_nosite.parquet
clean_v3_nosite, month-forward OOF). Within each day, only the clean model's positions 2-6 are re-ordered by a ridge on
[z(clean), z(th_n_pre), z(log1p hunter prior hunts), video present] (z within day; target z(-log final rank)), fitted
leave-one-day-out on the rows at clean positions 2-6. No follower counts (pending the leak check).
  th_n_pre      distinct non-hunter commenters created <= 00:05 PT (comment dumps; hunter = warehouse poster)
  prior hunts   earlier days on which the poster hunted a daily-ranked launch (strictly before the day)
  video         any media item of type video (raw/ph_api/page_media.jsonl; product media, read after the day)
usage: python tiebreak.py -> results/tiebreak.md"""
import json, os, sys, subprocess, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
os.environ.setdefault("CF_WORK", "/tmp/claude-0/-home-user-UserSim/94f4f0ff-5cdc-5cbe-bb94-5c0d76cd2a8c/scratchpad/cmt_v2")
import comment_forecast as CF
from early_forecast import B
from sklearn.linear_model import Ridge


def main():
    from pipeline import warehouse as W
    L = W.query("SELECT CAST(id AS VARCHAR) id, slug, day, daily_rank, poster FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    L["poster"] = L.poster.fillna("").str.lower()
    T = pd.read_parquet(os.path.join(HERE, "results", "tw_nosite.parquet")); T["id"] = T.id.astype(str)
    X = L.merge(T[["id", "clean_v3_nosite"]].rename(columns={"clean_v3_nosite": "clean"}), on="id")
    X = X[(X.day >= "2026-04-01") & (X.day <= "2026-10-31")]
    K, _ = CF.load_comments()
    K = K.merge(L[["slug", "id", "day", "poster"]], on="slug")
    K["t5"] = [pd.Timestamp(d + " 00:05", tz="America/Los_Angeles").tz_convert("UTC") for d in K.day]
    K = K[K.ts <= K.t5]
    npre = K[K.user != K.poster].groupby("id").user.nunique()
    X["npre"] = X.id.map(npre).fillna(0)
    dd = L.sort_values("day").drop_duplicates(["poster", "day"])
    first_n = {}
    for p_, g in dd.groupby("poster"):
        ds = g.day.tolist()
        for k, d in enumerate(ds):
            first_n[(p_, d)] = k
    X["hunts"] = np.log1p([first_n.get((p_, d), 0) if p_ else 0 for p_, d in zip(X.poster, X.day)])
    p = tempfile.mkdtemp(dir=os.environ.get("TMPDIR", "/tmp")) + "/m.jsonl"
    subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/ph_api/page_media.jsonl", p], check=True)
    vid = {}
    for l in open(p):
        r = json.loads(l); vid[str(r["id"])] = float(any((m or {}).get("type") == "video" for m in (r.get("media") or [])))
    X["video"] = X.id.map(vid)
    cov = {"video_known": round(float(X.video.notna().mean()), 3)}
    X["video"] = X.video.fillna(0.0)
    zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
    for c in ("clean", "npre", "hunts", "video"):
        X["z_" + c] = X.groupby("day")[c].transform(zf)
    X["y"] = X.groupby("day").daily_rank.transform(lambda s: zf(-np.log(s)))
    X["cpos"] = X.groupby("day").clean.rank(ascending=False, method="first")
    days = sorted(X.day.unique()); rng = np.random.default_rng(0)
    VARS = {"+ th_n_pre": ["z_clean", "z_npre"], "+ hunts": ["z_clean", "z_hunts"], "+ video": ["z_clean", "z_video"],
            "+ all three": ["z_clean", "z_npre", "z_hunts", "z_video"]}
    base, res = [], {k: [] for k in VARS}
    W26 = X[(X.cpos >= 2) & (X.cpos <= 6)]
    for d in days:
        g = X[X.day == d].sort_values("cpos"); t = g.sort_values("daily_rank").id.tolist(); o0 = g.id.tolist()
        base.append([len(set(o0[:k]) & set(t[:k])) / k * 100 for k in (3, 5)])
        tr = W26[W26.day != d]
        for nm, F in VARS.items():
            m = Ridge(alpha=3.0).fit(tr[F], tr.y)
            mid = g[(g.cpos >= 2) & (g.cpos <= 6)]
            mid = mid.assign(s=m.predict(mid[F])).sort_values(["s", "id"], ascending=[False, True]).id.tolist()
            o = o0[:1] + mid + [i for i in o0 if i not in set(mid) and i != o0[0]]
            res[nm].append([len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5)])
    base = np.array(base)
    md = [f"# Near-miss tie-break at 00:05 (clean positions 2-6 re-ordered; {len(days)} days Apr-Oct; LODO)", "", json.dumps(cov), "",
          "| variant | top 3 | top 5 | diff top 3 | diff top 5 |", "|---|---|---|---|---|",
          f"| clean_nosite as is | {base[:,0].mean():.1f} | {base[:,1].mean():.1f} | - | - |"]
    for nm in VARS:
        P = np.array(res[nm]); dP = P - base; b = np.array([dP[rng.integers(0, len(dP), len(dP))].mean(0) for _ in range(3000)])
        md.append(f"| {nm} | {P[:,0].mean():.1f} | {P[:,1].mean():.1f} | {dP[:,0].mean():+.1f} [{np.percentile(b[:,0],2.5):+.1f}, {np.percentile(b[:,0],97.5):+.1f}] | {dP[:,1].mean():+.1f} [{np.percentile(b[:,1],2.5):+.1f}, {np.percentile(b[:,1],97.5):+.1f}] |")
    open(os.path.join(HERE, "results", "tiebreak.md"), "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
