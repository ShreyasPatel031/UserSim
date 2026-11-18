"""Maker replies and total comments at early cuts (orchestrator 02:53Z Nov 13; 214 days Apr-Oct; counts only).
Comment dumps (exact created timestamps). Cuts T = 00:15 (P015), 00:30 (P030), 01:00 (P1) PT. Per launch at T:
  nc      log1p total comments created <= T (any author, replies included)
  nu      log1p distinct non-hunter commenters created <= T
  mrep_f  log1p replies (depth > 0) by the FULL team (hunter + warehouse makers list) created <= T
  mrep_h  log1p replies by the HUNTER only created <= T (lower bound of the 00:05-safe team: the hunter is always named at 00:05;
          makers named in the 00:05 read cannot be reconstructed for Apr-Oct, so the safe set lies between mrep_h and mrep_f)
Base (the current comment-line inputs) = z(clean_nosite) + z(th_n_pre) + z(nu). LODO ridge vs + nc, + mrep, + both.
If positive, the weights (full fit, hunter-only replies, which is what is 00:05-safe for sure) are frozen to
results/frozen/maker_replies_20261113.json. usage: python maker_replies.py -> results/maker_replies.md"""
import json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
os.environ.setdefault("CF_WORK", "/tmp/claude-0/-home-user-UserSim/94f4f0ff-5cdc-5cbe-bb94-5c0d76cd2a8c/scratchpad/cmt_v2")
import comment_forecast as CF
from sklearn.linear_model import Ridge
CUTS = {"P015": 15, "P030": 30, "P1": 60}


def main():
    from pipeline import warehouse as W
    L = W.query("SELECT CAST(id AS VARCHAR) id, slug, day, daily_rank, poster, makers FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    L["poster"] = L.poster.fillna("").str.lower()
    T = pd.read_parquet(os.path.join(HERE, "results", "tw_nosite.parquet")); T["id"] = T.id.astype(str)
    # MR_BASE (orchestrator 11:33Z Nov 13 item 3): swap the base line, e.g. "both" of history_retrain_decomp_preds_arm2.parquet;
    # MR_SUF names the output md, and nothing is frozen in that mode
    SUF = os.environ.get("MR_SUF", "")
    if os.environ.get("MR_BASE"):
        col = os.environ.get("MR_COL", "both"); B_ = pd.read_parquet(os.environ["MR_BASE"]); B_["id"] = B_.id.astype(str)
        T = B_[["id", col]].dropna().rename(columns={col: "clean_v3_nosite"})
    X0 = L.merge(T[["id", "clean_v3_nosite"]].rename(columns={"clean_v3_nosite": "clean"}), on="id")
    X0 = X0[(X0.day >= "2026-04-01") & (X0.day <= "2026-10-31")].copy()
    K, _ = CF.load_comments(); K = K.merge(L[["slug", "id", "day", "poster", "makers"]], on="slug")
    K["d0"] = [pd.Timestamp(d, tz="America/Los_Angeles").tz_convert("UTC") for d in K.day]
    mk = {i: {str(m).lower() for m in (json.loads(v) if isinstance(v, str) and v.startswith("[") else [])} for i, v in zip(L.id, L.makers)}
    K["is_h"] = K.user == K.poster; K["is_team"] = K.is_h | np.array([u in mk.get(i, set()) for u, i in zip(K.user, K.id)], dtype=bool)
    K["rep"] = K.depth > 0
    pre = K[K.ts <= K.d0 + pd.Timedelta(minutes=5)]
    X0["npre"] = X0.id.map(pre[~pre.is_h].groupby("id").user.nunique()).fillna(0)
    zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
    rng = np.random.default_rng(0); md = [f"# Maker replies and total comments at early cuts ({X0.day.nunique()} days Apr-Oct, {len(X0)} launches; LODO)", ""]
    frozen = {}
    for pt, mins in CUTS.items():
        C = K[K.ts <= K.d0 + pd.Timedelta(minutes=mins)]; X = X0.copy()
        X["nc"] = np.log1p(X.id.map(C.groupby("id").size()).fillna(0))
        X["nu"] = np.log1p(X.id.map(C[~C.is_h].groupby("id").user.nunique()).fillna(0))
        X["mrep_f"] = np.log1p(X.id.map(C[C.is_team & C.rep].groupby("id").size()).fillna(0))
        X["mrep_h"] = np.log1p(X.id.map(C[C.is_h & C.rep].groupby("id").size()).fillna(0))
        for c in ("clean", "npre", "nc", "nu", "mrep_f", "mrep_h"):
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
        md += [f"## {pt} ({mins // 60:02d}:{mins % 60:02d} PT): launches with any team reply <= T: full team {(X.mrep_f > 0).mean():.1%}, hunter only {(X.mrep_h > 0).mean():.1%}", "",
               "| variant | top 3 | top 5 | top 10 | diff top 3 | diff top 5 | diff top 10 |", "|---|---|---|---|---|---|---|",
               f"| base: clean + th_n_pre + distinct commenters | {base[:,0].mean():.1f} | {base[:,1].mean():.1f} | {base[:,2].mean():.1f} | - | - | - |"]
        res = {}
        for nm, cols in (("+ total comments", ["z_nc"]), ("+ team replies (full team)", ["z_mrep_f"]), ("+ team replies (hunter only, 00:05-safe floor)", ["z_mrep_h"]),
                         ("+ total + replies (full)", ["z_nc", "z_mrep_f"]), ("+ total + replies (hunter only)", ["z_nc", "z_mrep_h"])):
            P = lodo(BASE + cols); dP = P - base; b = np.array([dP[rng.integers(0, len(dP), len(dP))].mean(0) for _ in range(3000)])
            if os.environ.get("MR_DUMP"):   # per-day hits for paired comparisons across base lines (orchestrator 19:10Z Nov 13)
                pd.DataFrame(P, columns=["t3", "t5", "t10"]).assign(day=days, point=pt, variant=nm).to_csv(os.environ["MR_DUMP"], mode="a", header=not os.path.exists(os.environ["MR_DUMP"]), index=False)
            lo = [np.percentile(b[:, k], 2.5) for k in range(3)]; res[nm] = (dP.mean(0), lo, BASE + cols)
            md.append(f"| {nm} | {P[:,0].mean():.1f} | {P[:,1].mean():.1f} | {P[:,2].mean():.1f} | " +
                      " | ".join(f"{dP[:,k].mean():+.1f} [{lo[k]:+.1f}, {np.percentile(b[:,k],97.5):+.1f}]" for k in range(3)) + " |")
        md.append("")
        if pt == "P1" and not SUF:   # orchestrator 02:57Z Nov 13: P1 live uses the true 00:05-safe set with weights from the FULL-team fit
            fp1 = os.path.join(HERE, "results", "frozen", "maker_replies_P1_fullteam_20261113.json")
            if not os.path.exists(fp1):
                cols1 = res["+ total + replies (full)"][2]; m1 = Ridge(alpha=3.0).fit(X[cols1], X.y)
                json.dump({"frozen_at": pd.Timestamp.now(tz="UTC").isoformat(), "days": "214 Apr-Oct", "team_fit": "full team (hunter + warehouse makers)",
                           "team_live": "hunter + makers named (non-redacted id) in raw/daily/<d>/today_0005.json",
                           "features": "z within day: clean_nosite, th_n_pre, log1p distinct non-hunter commenters <= 01:00, log1p total comments <= 01:00, log1p team replies <= 01:00",
                           "points": {"P1": {"coef": dict(zip([c.replace("mrep_f", "mrep") for c in cols1], map(float, m1.coef_))), "intercept": float(m1.intercept_), "cut_minutes": 60}}},
                          open(fp1, "w"), indent=1)
                md.append(f"Frozen P1 full-team weights -> {os.path.relpath(fp1, HERE)}")
        safe = res["+ total + replies (hunter only)"]
        if safe[0][0] > 0 and safe[1][0] > 0:   # positive top-3 interval for the 00:05-safe variant -> freeze
            m = Ridge(alpha=3.0).fit(X[safe[2]], X.y)
            frozen[pt] = {"coef": dict(zip(safe[2], map(float, m.coef_))), "intercept": float(m.intercept_), "cut_minutes": mins}
    fp = os.path.join(HERE, "results", "frozen", "maker_replies_20261113.json")
    if frozen and not os.path.exists(fp) and not SUF:
        json.dump({"frozen_at": pd.Timestamp.now(tz="UTC").isoformat(), "days": "214 Apr-Oct", "team": "hunter only (00:05-safe)",
                   "features": "z within day: clean_nosite, th_n_pre, log1p distinct non-hunter commenters <= T, log1p total comments <= T, log1p hunter replies <= T",
                   "points": frozen}, open(fp, "w"), indent=1)
        md.append(f"Frozen (positive top-3 interval, hunter-only variant): {', '.join(frozen)} -> {os.path.relpath(fp, HERE)}")
    else:
        md.append("Nothing frozen: no point has a positive top-3 interval for the 00:05-safe (hunter-only) variant." if not frozen else "Frozen file exists; not overwritten.")
    open(os.path.join(HERE, "results", f"maker_replies{SUF}.md"), "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
