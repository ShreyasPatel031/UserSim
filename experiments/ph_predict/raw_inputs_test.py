"""Ignored-field inputs at 00:30 / 01:00 (orchestrator 14:39Z Nov 13): commenter follower counts and reply counts, paired LODO vs
the current comment-line base (z clean_nosite + z th_n_pre + z distinct non-hunter commenters), 214 days Apr-Oct, counts only.
  rep_nt  log1p replies (depth > 0) by non-team authors created <= T
  rep_all log1p all replies created <= T
  fol_sum log1p sum of commenters' PH followers (distinct non-team commenters <= T); fol_med median; fol_big n commenters >= 1,000
Follower counts are the store_v3 pull-time values (persons.header_json, joined on ph_user_id = comment uid): NOT dated before the
launch (followers only grow, so the value is an upper bound of the launch-time count). Read the result as an upper bound until a dated
source exists; the live feed's commenter_followers_count is the launch-time value for forward days.
reviewsRating / reviewsCount at 00:05: not testable on a backtest (pre-launch review reads exist only for Oct 29-Nov 13 in
launch_snapshots, 13 days; the 2025 list values were read after the fact). usage: python raw_inputs_test.py <persons.parquet>"""
import json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
os.environ.setdefault("CF_WORK", "/tmp/claude-0/-home-user-UserSim/94f4f0ff-5cdc-5cbe-bb94-5c0d76cd2a8c/scratchpad/cmt_v2")
import comment_forecast as CF
from sklearn.linear_model import Ridge
CUTS = {"P030": 30, "P1": 60}


def main(pp):
    from pipeline import warehouse as W
    L = W.query("SELECT CAST(id AS VARCHAR) id, slug, day, daily_rank, poster, makers FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    L["poster"] = L.poster.fillna("").str.lower()
    T = pd.read_parquet(os.path.join(HERE, "results", "tw_nosite.parquet")); T["id"] = T.id.astype(str)
    X0 = L.merge(T[["id", "clean_v3_nosite"]].rename(columns={"clean_v3_nosite": "clean"}), on="id")
    X0 = X0[(X0.day >= "2026-04-01") & (X0.day <= "2026-10-31")].copy()
    P = pd.read_parquet(pp, columns=["ph_user_id", "header_json"]).dropna()
    fol = {}
    for u, h in zip(P.ph_user_id.astype(str), P.header_json):
        try: fol[u] = float(json.loads(h).get("followers") or 0)
        except Exception: pass
    K, _ = CF.load_comments(); K = K.merge(L[["slug", "id", "day", "poster", "makers"]], on="slug")
    K["d0"] = [pd.Timestamp(d, tz="America/Los_Angeles").tz_convert("UTC") for d in K.day]
    mk = {i: {str(m).lower() for m in (json.loads(v) if isinstance(v, str) and v.startswith("[") else [])} for i, v in zip(L.id, L.makers)}
    K["is_h"] = K.user == K.poster; K["is_team"] = K.is_h | np.array([u in mk.get(i, set()) for u, i in zip(K.user, K.id)], dtype=bool)
    K["rep"] = K.depth > 0; K["fol"] = K.uid.astype(str).map(fol)
    pre = K[K.ts <= K.d0 + pd.Timedelta(minutes=5)]
    X0["npre"] = X0.id.map(pre[~pre.is_h].groupby("id").user.nunique()).fillna(0)
    zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
    rng = np.random.default_rng(0)
    md = [f"# Ignored-field inputs at 00:30 / 01:00 ({X0.day.nunique()} days Apr-Oct, {len(X0)} launches; LODO ridge, paired day bootstrap)", "",
          f"Commenter follower counts matched for {K[~K.is_team].fol.notna().mean():.1%} of non-team comment rows (store_v3 pull-time values: upper bound, see docstring).", ""]
    for pt, mins in CUTS.items():
        C = K[K.ts <= K.d0 + pd.Timedelta(minutes=mins)]; X = X0.copy(); nt = C[~C.is_team]
        X["nu"] = np.log1p(X.id.map(C[~C.is_h].groupby("id").user.nunique()).fillna(0))
        X["rep_nt"] = np.log1p(X.id.map(nt[nt.rep].groupby("id").size()).fillna(0))
        X["rep_all"] = np.log1p(X.id.map(C[C.rep].groupby("id").size()).fillna(0))
        u1 = nt.drop_duplicates(["id", "user"])
        X["fol_sum"] = np.log1p(X.id.map(u1.groupby("id").fol.sum()).fillna(0))
        X["fol_med"] = np.log1p(X.id.map(u1.groupby("id").fol.median()).fillna(0))
        X["fol_big"] = X.id.map((u1.fol >= 1000).groupby(u1.id).sum()).fillna(0)
        for c in ("clean", "npre", "nu", "rep_nt", "rep_all", "fol_sum", "fol_med", "fol_big"):
            X["z_" + c] = X.groupby("day")[c].transform(zf)
        X["y"] = X.groupby("day").daily_rank.transform(lambda s: zf(-np.log(s)))
        days = sorted(X.day.unique())
        def lodo(cols):
            o_ = []
            for d in days:
                te, tr = X[X.day == d], X[X.day != d]; t = te.sort_values("daily_rank").id.tolist()
                o = te.assign(s=Ridge(alpha=3.0).fit(tr[cols], tr.y).predict(te[cols])).sort_values(["s", "id"], ascending=[False, True]).id.tolist()
                o_.append([len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)])
            return np.array(o_)
        BASE = ["z_clean", "z_npre", "z_nu"]; base = lodo(BASE)
        md += [f"## {pt} ({mins // 60:02d}:{mins % 60:02d} PT)", "", "| variant | top 3 | top 5 | top 10 | diff t3 / t5 / t10 (95%) |", "|---|---|---|---|---|",
               f"| base: clean + th_n_pre + distinct commenters | {base[:,0].mean():.1f} | {base[:,1].mean():.1f} | {base[:,2].mean():.1f} | - |"]
        for nm, cols in (("+ non-team replies", ["z_rep_nt"]), ("+ all replies", ["z_rep_all"]), ("+ commenter followers (sum)", ["z_fol_sum"]),
                         ("+ commenter followers (median)", ["z_fol_med"]), ("+ commenters with >= 1k followers", ["z_fol_big"]),
                         ("+ replies + followers (sum)", ["z_rep_nt", "z_fol_sum"])):
            dP = lodo(BASE + cols) - base; b = np.array([dP[rng.integers(0, len(dP), len(dP))].mean(0) for _ in range(3000)])
            md.append(f"| {nm} | {(base + dP)[:,0].mean():.1f} | {(base + dP)[:,1].mean():.1f} | {(base + dP)[:,2].mean():.1f} | " +
                      " / ".join(f"{dP[:,k].mean():+.1f} [{np.percentile(b[:,k],2.5):+.1f}, {np.percentile(b[:,k],97.5):+.1f}]" for k in range(3)) + " |")
        md.append("")
    md += ["reviewsRating / reviewsCount at 00:05: not testable on a backtest (13 days of pre-launch review reads; see docstring); logged forward only."]
    open(os.path.join(HERE, "results", "raw_inputs_test.md"), "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main(sys.argv[1])
