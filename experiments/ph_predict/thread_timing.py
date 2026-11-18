"""WHEN the pre-launch commenters posted (orchestrator 02:51Z Nov 13; 214 days Apr-Oct; counts only).
Comment dumps (comment_forecast.load_comments; exact created timestamps, read after the day). Launch = 00:01 PT of the day.
Per launch, distinct non-hunter commenters by the time of their FIRST comment created <= 00:05 PT:
  a  > 24 h before launch      b  1-24 h before      c  last hour before 00:01      d  00:01-00:05
  span   hours between the first and last pre-00:05 comment (0 if < 2 comments)
  maker_pre  a named maker (warehouse makers list) commented before 00:01
Coverage: launches with any comment row in the dumps (thread page held). LODO ridge, base z(clean_nosite) + z(th_n_pre).
usage: python thread_timing.py -> results/thread_timing.md"""
import json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
os.environ.setdefault("CF_WORK", "/tmp/claude-0/-home-user-UserSim/94f4f0ff-5cdc-5cbe-bb94-5c0d76cd2a8c/scratchpad/cmt_v2")
import comment_forecast as CF
from sklearn.linear_model import Ridge


def main():
    from pipeline import warehouse as W
    L = W.query("SELECT CAST(id AS VARCHAR) id, slug, day, daily_rank, poster, makers FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    L["poster"] = L.poster.fillna("").str.lower()
    T = pd.read_parquet(os.path.join(HERE, "results", "tw_nosite.parquet")); T["id"] = T.id.astype(str)
    X = L.merge(T[["id", "clean_v3_nosite"]].rename(columns={"clean_v3_nosite": "clean"}), on="id")
    X = X[(X.day >= "2026-04-01") & (X.day <= "2026-10-31")].copy()
    K, _ = CF.load_comments(); K = K.merge(L[["slug", "id", "day", "poster", "makers"]], on="slug")
    K["t0"] = [(pd.Timestamp(d, tz="America/Los_Angeles") + pd.Timedelta(minutes=1)).tz_convert("UTC") for d in K.day]
    K["t5"] = K.t0 + pd.Timedelta(minutes=4)
    held = set(K.id)
    P = K[K.ts <= K.t5]
    mk = {i: {str(m).lower() for m in (json.loads(v) if isinstance(v, str) and v.startswith("[") else [])} for i, v in zip(L.id, L.makers)}
    F = P[P.user != P.poster].groupby(["id", "user"]).agg(first=("ts", "min"), t0=("t0", "first")).reset_index()
    F["lead_h"] = (F.t0 - F["first"]).dt.total_seconds() / 3600
    F["bin"] = pd.cut(F.lead_h, [-1e9, 0, 1, 24, 1e9], labels=["d", "c", "b", "a"], right=False)
    cnt = F.groupby(["id", "bin"], observed=False).size().unstack(fill_value=0)
    span = P.groupby("id").ts.agg(lambda s: (s.max() - s.min()).total_seconds() / 3600 if len(s) > 1 else 0.0)
    mpre = {i: float(any(u in mk.get(i, set()) for u in g[g.ts < g.t0].user)) for i, g in P.groupby("id")}
    X["npre"] = X.id.map(F.groupby("id").size()).fillna(0)
    for b in "abcd":
        X["n_" + b] = np.log1p(X.id.map(cnt[b]) if b in cnt else 0).fillna(0)
    X["span"] = np.log1p(X.id.map(span).fillna(0)); X["maker_pre"] = X.id.map(mpre).fillna(0.0)
    X["held"] = X.id.isin(held)
    zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
    FT = ["n_a", "n_b", "n_c", "n_d", "span", "maker_pre"]
    for c in ["clean", "npre"] + FT:
        X["z_" + c] = X.groupby("day")[c].transform(zf)
    X["y"] = X.groupby("day").daily_rank.transform(lambda s: zf(-np.log(s)))
    days = sorted(X.day.unique()); rng = np.random.default_rng(0)
    def lodo(cols):
        o_ = []
        for d in days:
            te, tr = X[X.day == d], X[X.day != d]; t = te.sort_values("daily_rank").id.tolist()
            o = te.assign(s=Ridge(alpha=3.0).fit(tr[cols], tr.y).predict(te[cols])).sort_values(["s", "id"], ascending=[False, True]).id.tolist()
            o_.append([len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)])
        return np.array(o_)
    BASE = ["z_clean", "z_npre"]; base = lodo(BASE); t10 = X.daily_rank <= 10
    md = [f"# Pre-launch commenter timing ({len(days)} days Apr-Oct, {len(X)} ranked launches; LODO)", "",
          f"Coverage: thread held (any comment row) {X.held.mean():.1%} of launches; final top 10 {X[t10].held.mean():.1%} vs 11+ {X[~t10].held.mean():.1%}. "
          f"Launches with any pre-launch outside commenter {(X.npre > 0).mean():.1%}.", "",
          "Mean distinct commenters per launch by first-comment time (final top 10 vs 11+): " +
          "; ".join(f"{nm} {np.expm1(X[t10]['n_' + b]).mean():.2f} vs {np.expm1(X[~t10]['n_' + b]).mean():.2f}"
                    for b, nm in zip("abcd", (">24h before", "1-24h before", "last hour", "00:01-00:05"))) +
          f"; maker commented before launch {X[t10].maker_pre.mean():.2f} vs {X[~t10].maker_pre.mean():.2f}", "",
          "| variant | top 3 | top 5 | top 10 | diff top 3 | diff top 5 | diff top 10 |", "|---|---|---|---|---|---|---|",
          f"| clean_nosite + th_n_pre | {base[:,0].mean():.1f} | {base[:,1].mean():.1f} | {base[:,2].mean():.1f} | - | - | - |"]
    for nm, cols in [("+ split a-d", ["z_n_a", "z_n_b", "z_n_c", "z_n_d"]), ("split a-d instead of th_n_pre", None), ("+ span", ["z_span"]),
                     ("+ maker commented before launch", ["z_maker_pre"]), ("+ all", ["z_n_a", "z_n_b", "z_n_c", "z_n_d", "z_span", "z_maker_pre"])]:
        P_ = lodo(["z_clean", "z_n_a", "z_n_b", "z_n_c", "z_n_d"]) if cols is None else lodo(BASE + cols)
        dP = P_ - base; b = np.array([dP[rng.integers(0, len(dP), len(dP))].mean(0) for _ in range(3000)])
        md.append(f"| {nm} | {P_[:,0].mean():.1f} | {P_[:,1].mean():.1f} | {P_[:,2].mean():.1f} | " +
                  " | ".join(f"{dP[:,k].mean():+.1f} [{np.percentile(b[:,k],2.5):+.1f}, {np.percentile(b[:,k],97.5):+.1f}]" for k in range(3)) + " |")
    m = Ridge(alpha=3.0).fit(X[BASE + ["z_n_a", "z_n_b", "z_n_c", "z_n_d"]], X.y)
    md += ["", "Full-fit ridge coefficients (clean, th_n_pre, a, b, c, d): " + ", ".join(f"{c:+.3f}" for c in m.coef_)]
    open(os.path.join(HERE, "results", "thread_timing.md"), "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
