"""Top-10 / top-5 at 00:05 (orchestrator 01:52Z Nov 13; backtest Apr-Oct, 214 days, counts only).
Base = clean_nosite + th_n_pre ridge (tiebreak/precommenters base). 00:05-safe features (z within day where per-launch):
clean (tw_nosite clean_v3_nosite OOF), npre (non-hunter commenters <= 00:05), hunts (log1p hunter's earlier hunting days),
ntopics, team (len makers; count does not drift after 00:05), tag_len, desc_len (log1p chars), video (page_media; product
media read later), weekday, n_day (log launches that day).
(1) miss anatomy: final top 10 ranked 11+ by clean ("missed in") vs clean 6-10 that finished 11+ ("false in"):
    clean-rank distribution and standardized differences (missed-in vs other launches with clean rank 11-20; false-in vs
    clean 6-10 that stayed top 10), day bootstrap.
(2)/(3) per-launch P(final top 10) / P(final top 5): logistic and a small GBM, leave-one-day-out; rank by P; top 3/5/10
    vs the base, paired day bootstrap. usage: python top10_target.py -> results/top10_target.md"""
import json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
os.environ.setdefault("CF_WORK", "/tmp/claude-0/-home-user-UserSim/94f4f0ff-5cdc-5cbe-bb94-5c0d76cd2a8c/scratchpad/cmt_v2")
import comment_forecast as CF
from early_forecast import B
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier


def main():
    from pipeline import warehouse as W
    L = W.query("SELECT CAST(id AS VARCHAR) id, slug, day, daily_rank, poster, makers, topics, tagline, description FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    L["poster"] = L.poster.fillna("").str.lower()
    T = pd.read_parquet(os.path.join(HERE, "results", "tw_nosite.parquet")); T["id"] = T.id.astype(str)
    X = L.merge(T[["id", "clean_v3_nosite"]].rename(columns={"clean_v3_nosite": "clean"}), on="id")
    X = X[(X.day >= "2026-04-01") & (X.day <= "2026-10-31")].copy()
    K, _ = CF.load_comments(); K = K.merge(L[["slug", "id", "day", "poster"]], on="slug")
    K["t5"] = [pd.Timestamp(d + " 00:05", tz="America/Los_Angeles").tz_convert("UTC") for d in K.day]
    X["npre"] = X.id.map(K[(K.ts <= K.t5) & (K.user != K.poster)].groupby("id").user.nunique()).fillna(0)
    dd = L.sort_values("day").drop_duplicates(["poster", "day"]); first_n = {}
    for p_, g in dd.groupby("poster"):
        for k, d in enumerate(g.day.tolist()):
            first_n[(p_, d)] = k
    X["hunts"] = np.log1p([first_n.get((p_, d), 0) if p_ else 0 for p_, d in zip(X.poster, X.day)])
    js = lambda v: json.loads(v) if isinstance(v, str) and v.startswith("[") else (list(v) if isinstance(v, (list, np.ndarray)) else [])
    X["ntopics"] = [len(js(t)) for t in X.topics]; X["team"] = [len(js(m)) for m in X.makers]
    X["tag_len"] = np.log1p(X.tagline.fillna("").str.len()); X["desc_len"] = np.log1p(X.description.fillna("").str.len())
    p = tempfile.mkdtemp(dir=os.environ.get("TMPDIR", "/tmp")) + "/m.jsonl"
    subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/ph_api/page_media.jsonl", p], check=True)
    vid = {str(r["id"]): float(any((m or {}).get("type") == "video" for m in (r.get("media") or []))) for r in map(json.loads, open(p))}
    X["video"] = X.id.map(vid).fillna(0.0)
    X["weekday"] = pd.to_datetime(X.day).dt.dayofweek.astype(float); X["n_day"] = np.log(X.groupby("day").id.transform("size"))
    zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
    PER = ["clean", "npre", "hunts", "ntopics", "team", "tag_len", "desc_len", "video"]
    for c in PER:
        X["z_" + c] = X.groupby("day")[c].transform(zf)
    X["cr"] = X.groupby("day").clean.rank(ascending=False, method="first")
    X["y"] = X.groupby("day").daily_rank.transform(lambda s: zf(-np.log(s)))
    X["t10"] = (X.daily_rank <= 10).astype(int); X["t5"] = (X.daily_rank <= 5).astype(int)
    days = sorted(X.day.unique()); rng = np.random.default_rng(0)
    # (1) miss anatomy
    mi = X[(X.daily_rank <= 10) & (X.cr > 10)]; fi = X[(X.cr <= 10) & (X.cr >= 6) & (X.daily_rank > 10)]
    md = [f"# Top 10 / top 5 at 00:05 ({len(days)} days Apr-Oct)", "",
          f"Missed in (final top 10, clean rank 11+): {len(mi)} launches; clean-rank distribution: " +
          ", ".join(f"{a}: {b}" for a, b in pd.cut(mi.cr, [10, 15, 20, 30, 1000], labels=["11-15", "16-20", "21-30", "31+"]).value_counts().sort_index().items()),
          f"False in (clean 6-10, finished 11+): {len(fi)} launches", "",
          "Standardized differences, day bootstrap 95%: missed-in vs other launches at clean rank 11-20; false-in vs clean 6-10 that stayed top 10", "",
          "| feature | missed-in minus others (11-20) | false-in minus stayed (6-10) |", "|---|---|---|"]
    o11 = X[(X.cr >= 11) & (X.cr <= 20) & (X.daily_rank > 10)]; st = X[(X.cr >= 6) & (X.cr <= 10) & (X.daily_rank <= 10)]
    def sd(a, b, c):
        return a[c].mean() - b[c].mean()
    for c in ["z_" + c for c in PER] + ["weekday", "n_day"]:
        cells = []
        for a, b in ((mi, o11), (fi, st)):
            v = sd(a, b, c); bs = []
            for _ in range(1000):
                ds = set(rng.choice(days, len(days)))
                aa, bb = a[a.day.isin(ds)], b[b.day.isin(ds)]
                if len(aa) and len(bb):
                    bs.append(sd(aa, bb, c))
            cells.append(f"{v:+.2f} [{np.percentile(bs, 2.5):+.2f}, {np.percentile(bs, 97.5):+.2f}]")
        md.append(f"| {c.replace('z_', '')} | {cells[0]} | {cells[1]} |")
    # (2)/(3) targeted models
    FT = ["z_" + c for c in PER] + ["weekday", "n_day"]
    def run(kind, target=None):
        out = []
        for d in days:
            te = X[X.day == d]; tr = X[X.day != d]; t = te.sort_values("daily_rank").id.tolist()
            if kind == "base":
                s = Ridge(alpha=3.0).fit(tr[["z_clean", "z_npre"]], tr.y).predict(te[["z_clean", "z_npre"]])
            elif kind == "logit":
                s = LogisticRegression(C=1.0, max_iter=2000).fit(tr[FT], tr[target]).predict_proba(te[FT])[:, 1]
            else:
                s = HistGradientBoostingClassifier(max_depth=3, max_iter=150, learning_rate=0.05, random_state=0).fit(tr[FT], tr[target]).predict_proba(te[FT])[:, 1]
            o = te.assign(s=s).sort_values(["s", "id"], ascending=[False, True]).id.tolist()
            out.append([len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)])
        return np.array(out)
    base = run("base")
    md += ["", "| model | top 3 | top 5 | top 10 | diff top 3 | diff top 5 | diff top 10 |", "|---|---|---|---|---|---|---|",
           f"| base: clean_nosite + th_n_pre (ridge) | {base[:,0].mean():.1f} | {base[:,1].mean():.1f} | {base[:,2].mean():.1f} | - | - | - |"]
    for kind in ("logit", "gbm"):
        for tg in ("t10", "t5"):
            P = run(kind, tg); dP = P - base; b = np.array([dP[rng.integers(0, len(dP), len(dP))].mean(0) for _ in range(3000)])
            md.append(f"| P({tg}) {kind} | {P[:,0].mean():.1f} | {P[:,1].mean():.1f} | {P[:,2].mean():.1f} | " +
                      " | ".join(f"{dP[:,k].mean():+.1f} [{np.percentile(b[:,k],2.5):+.1f}, {np.percentile(b[:,k],97.5):+.1f}]" for k in range(3)) + " |")
    open(os.path.join(HERE, "results", "top10_target.md"), "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
