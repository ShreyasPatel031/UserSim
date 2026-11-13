"""Freeze clean_nosite_hf (orchestrator 05:00Z Nov 13): ridge on z(clean_nosite OOF) + z(th_n_pre) + z(log1p hunter PH followersCount),
z within day, target z(-log final rank), fitted on the 214 backtest days (Apr-Oct). Hunter followers in the backtest = warehouse
people.ph_followers of the hunter (profile read Oct 28 - Nov 4; the orchestrator's leak check: stable between pre-launch and later
reads, Spearman 0.994); LIVE the column uses ONLY the 00:05 read's user.followersCount (raw/daily/<d>/today_0005.json).
Also prints the LODO top 3/5/10 vs clean_nosite + th_n_pre. -> results/frozen/clean_nosite_hf_20261113.json"""
import json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
os.environ.setdefault("CF_WORK", "/tmp/claude-0/-home-user-UserSim/94f4f0ff-5cdc-5cbe-bb94-5c0d76cd2a8c/scratchpad/cmt_v2")
import comment_forecast as CF
from sklearn.linear_model import Ridge


def main():
    from pipeline import warehouse as W
    L = W.query("SELECT CAST(id AS VARCHAR) id, slug, day, daily_rank, poster FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    L["poster"] = L.poster.fillna("").str.lower()
    P = W.query("SELECT lower(person) p, ph_followers FROM people", do_sync=False).drop_duplicates("p").set_index("p")
    T = pd.read_parquet(os.path.join(HERE, "results", "tw_nosite.parquet")); T["id"] = T.id.astype(str)
    X = L.merge(T[["id", "clean_v3_nosite"]].rename(columns={"clean_v3_nosite": "clean"}), on="id")
    X = X[(X.day >= "2026-04-01") & (X.day <= "2026-10-31")].copy()
    K, _ = CF.load_comments(); K = K.merge(L[["slug", "id", "day", "poster"]], on="slug")
    K["t5"] = [(pd.Timestamp(d, tz="America/Los_Angeles") + pd.Timedelta(minutes=5)).tz_convert("UTC") for d in K.day]
    X["npre"] = X.id.map(K[(K.ts <= K.t5) & (K.user != K.poster)].groupby("id").user.nunique()).fillna(0)
    X["hf"] = np.log1p(X.poster.map(P.ph_followers).astype(float))
    X["hf"] = X.groupby("day").hf.transform(lambda s: s.fillna(s.median() if s.notna().any() else 0.0))
    zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
    for c in ("clean", "npre", "hf"):
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
    B_ = lodo(["z_clean", "z_npre"]); H_ = lodo(["z_clean", "z_npre", "z_hf"]); dP = H_ - B_
    b = np.array([dP[rng.integers(0, len(dP), len(dP))].mean(0) for _ in range(3000)])
    cols = ["z_clean", "z_npre", "z_hf"]; m = Ridge(alpha=3.0).fit(X[cols], X.y)
    fz = {"frozen_at": pd.Timestamp.now(tz="UTC").isoformat(), "days": len(days), "label": "top-10 candidate",
          "coef": dict(zip(cols, map(float, m.coef_))), "live_inputs": "clean_nosite (shadow pred_clean_nosite), th_n_pre (00:07 read only), "
          "log1p hunter followersCount from raw/daily/<d>/today_0005.json only",
          "lodo": {"base": B_.mean(0).round(1).tolist(), "with_hf": H_.mean(0).round(1).tolist(),
                   "diff_ci": [[round(float(dP[:, k].mean()), 1), round(float(np.percentile(b[:, k], 2.5)), 1), round(float(np.percentile(b[:, k], 97.5)), 1)] for k in range(3)]}}
    fp = os.path.join(HERE, "results", "frozen", "clean_nosite_hf_20261113.json")
    if not os.path.exists(fp):
        json.dump(fz, open(fp, "w"), indent=1)
    print(json.dumps(fz))


if __name__ == "__main__":
    main()
