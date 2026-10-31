"""Daily list v4: built on how HN files stories. Every story is on exactly one day's list (checked on 20,159 stories);
that day is the UTC day it first reached the front page, or its posting day if it got there within 30 min (93.6% of
list entries). Second-chance re-ups come back days later, so candidates reach back 7 days.

For a forecast at T on day D, per candidate (only what is known at T, from Quality News' 10-minute series kept for the
story's whole life): points, rank, best rank and time in the top 30 / top 10 during D so far, exposure during D, points
gained in the last 30 / 60 min, hours since posting and since first reaching the front page, whether its assignment
day is already D / earlier / still open, whether it is on an earlier day's list (then it cannot be on D), plus the
comment-based stage-1 score from daily_cache.parquet (stories under 72 h; backtest only).
Old stories (over 72 h at the end of D) are candidates at T only once they have been on the front page during D by T.
The same functions serve the backtest and the live forecast (forecast_daily.py).

Stage 2: per-T LambdaRank on days before SPLIT, tested from SPLIT.

    python daily_v4.py [split=2026-09-01] [from=2026-07-06] [to=2026-10-16]
"""
import json
import os
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd

import fine_io
import rank as R
import top100 as H

TIMES = {"t12": 12, "t15": 9, "t18": 6, "t20": 4, "t21": 3, "t22": 2, "t23": 1, "eod": 0}
NS = 1008                                                      # 10-minute slots: 7 days
WIN = 144 + 1                                                  # slots in one day (+1 edge)
VC = ("points", "rank_now", "gain30", "gain60", "best_rank_D", "slots_top30_D", "slots_top10_D", "exposure_D", "age_h",
      "h_since_first_page", "assigned", "reup", "rate", "rate60", "pts_per_h_page")


def series(q: pd.DataFrame, born: np.ndarray) -> dict:
    """7-day 10-minute arrays per story (rank, 91 = not on the front page; upvotes carried forward) and when it first
    reached the front page (its assignment time if that came over 30 min after posting)."""
    n = len(q)
    RK = np.full((n, NS), 91, np.float32)
    UP = np.full((n, NS), np.nan, np.float32)
    RK[:, :216] = np.array([[x if x is not None else 91 for x in r] for r in q.qn_rank_10m], np.float32)
    EX = np.full((n, NS), np.nan, np.float32)                      # Quality News' expected upvotes (accumulated)
    UP[:, :216] = pd.DataFrame(list(q.qn_up_10m), dtype=float).to_numpy()
    EX[:, :216] = pd.DataFrame(list(q.qn_exp_10m), dtype=float).to_numpy()
    for r, late in enumerate(q.qn_late if "qn_late" in q else [None] * n):
        if isinstance(late, list):
            for k, rk, up, ex in late:
                RK[r, k], UP[r, k], EX[r, k] = rk, up, ex
    UP = pd.DataFrame(UP).ffill(axis=1).fillna(1).to_numpy(np.float32)
    EX = pd.DataFrame(EX).ffill(axis=1).fillna(0).to_numpy(np.float32)
    F0 = q.qn_f0.to_numpy().astype(float)
    on = RK <= 90
    k_first = np.where(on.any(1), on.argmax(1), -1)
    t_first = np.where(k_first >= 0, F0 + 600 * (k_first + 1), np.nan)   # end of the first on-page slot
    reup = (t_first - born) > 1800
    return {"RK": RK, "UP": UP, "EX": EX, "F0": F0, "on": on, "born": born, "t_first": t_first, "reup": reup,
            "t_assign": np.where(reup, t_first, born), "post_id": q.post_id.to_numpy()}


def candidates(S: dict, days) -> pd.DataFrame:
    """Rows (day, story): posted in the 72 h before the end of D, or up to 7 days and on the front page during D."""
    born, F0, on = S["born"], S["F0"], S["on"]
    rows = []
    for d in days:
        t0 = pd.Timestamp(d, tz="UTC").timestamp()
        t1 = t0 + 86400
        young = (born >= t1 - 72 * 3600) & (born < t1)
        k0 = np.floor((t0 - F0) / 600).astype(int)
        k1 = np.floor((t1 - F0) / 600).astype(int)
        old = (born >= t1 - 7 * 86400) & (born < t1 - 72 * 3600) & (k1 > 0) & (k0 < NS)
        old &= np.array([on[r, max(k0[r], 0):min(k1[r], NS)].any() if o else False for r, o in enumerate(old)])
        rows.append(pd.DataFrame({"day": d, "r": np.flatnonzero(young | old), "t0": t0, "t1": t1}))
    C = pd.concat(rows, ignore_index=True)
    C["post_id"] = S["post_id"][C.r]
    return C


def features(C: pd.DataFrame, S: dict, name: str, T: np.ndarray) -> None:
    """Add <name>_<input> columns for a forecast at times T (one per row), from slots fully before T."""
    RK, UP, F0, born = S["RK"], S["UP"], S["F0"], S["born"]
    r = C.r.to_numpy()
    kT = np.clip(np.floor((T - F0[r]) / 600).astype(int), 0, NS)
    kD = np.clip(np.floor((C.t0.to_numpy() - F0[r]) / 600).astype(int), 0, NS)
    last = np.maximum(kT - 1, 0)
    idx = kD[:, None] + np.arange(WIN)[None, :]
    rkD = np.where(idx < kT[:, None], RK[r[:, None], np.minimum(idx, NS - 1)], 91)
    f = {}
    f["points"] = np.where(kT > 0, UP[r, last], 1)
    f["rank_now"] = np.where(kT > 0, RK[r, last], 91)
    f["gain30"] = f["points"] - np.where(kT > 3, UP[r, np.maximum(kT - 4, 0)], 1)
    f["gain60"] = f["points"] - np.where(kT > 6, UP[r, np.maximum(kT - 7, 0)], 1)
    f["best_rank_D"] = rkD.min(1)
    f["slots_top30_D"] = (rkD <= 30).sum(1)
    f["slots_top10_D"] = (rkD <= 10).sum(1)
    f["exposure_D"] = np.where(rkD < 91, 1 / rkD, 0).sum(1)
    f["age_h"] = (T - born[r]) / 3600
    seen = S["t_first"][r] <= T
    f["h_since_first_page"] = np.where(seen, (T - S["t_first"][r]) / 3600, -1)
    # assignment day so far: 1 = D, -1 = earlier day, 0 = not yet on the page (still open)
    f["assigned"] = np.where(~seen, 0, np.where(S["t_assign"][r] >= C.t0.to_numpy(), 1, -1))
    f["reup"] = np.where(seen, S["reup"][r].astype(float), 0)
    # Quality News' upvote rate: upvotes / upvotes expected at the ranks shown (overall and last hour); placement-free
    ex = np.where(kT > 0, S["EX"][r, last], 0)
    ex60 = ex - np.where(kT > 6, S["EX"][r, np.maximum(kT - 7, 0)], 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        f["rate"] = np.where(ex > 0.5, f["points"] / ex, np.nan)
        f["rate60"] = np.where(ex60 > 0.5, f["gain60"] / ex60, np.nan)
        f["pts_per_h_page"] = np.where(seen, f["points"] / np.maximum(f["h_since_first_page"], 0.17), np.nan)
    f["visible"] = ((born[r] < T) & ((C.t1.to_numpy() - born[r] <= 72 * 3600) | ((rkD < 91).sum(1) > 0))).astype(np.int8)
    for k_, v in f.items():
        C[f"{name}_{k_}"] = v


def fit_rank(df, cols):
    df = df.sort_values("day", kind="stable")
    grp = df.groupby("day", sort=False).size().to_numpy()
    lab = np.clip(31 - df.real_rank.to_numpy(), 0, 30).astype(int)
    return lgb.LGBMRanker(n_estimators=400, learning_rate=0.05, num_leaves=15, min_child_samples=10, subsample=0.8,
                          subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0,
                          label_gain=list(range(31))).fit(df[cols], lab, group=grp)


def score(P, col):
    out = {}
    for k, m in ((30, 30), (10, 10), (10, 30)):
        v = [len(set(g[g.real_rank <= k].post_id) & set(g.nlargest(m, col).post_id)) / k for _, g in P.groupby("day")]
        out[f"real{k}_in_top{m}"] = R.boot(v)
    return out


def lists() -> pd.DataFrame:
    L = pd.read_json(os.path.join(H.CACHE, "frontday.jsonl"), lines=True, dtype={"day": str})
    return L.sort_values("rank").drop_duplicates(["day", "post_id"])


def build(A: str, B: str) -> pd.DataFrame:
    L = lists()
    p = H.stories()
    _, q = fine_io.load()
    print("series", len(q), flush=True)
    S = series(q, q.post_id.map(p.set_index("post_id").created_at_i).to_numpy().astype(float))
    C = candidates(S, sorted(d for d in L.day.unique() if A <= d <= B))
    lr = L.set_index(["day", "post_id"])["rank"]
    C["list_rank"] = lr.reindex(pd.MultiIndex.from_frame(C[["day", "post_id"]])).fillna(999).to_numpy()
    C["real_rank"] = np.where(C.list_rank <= 30, C.list_rank, 999)
    C["on_earlier_list"] = (C.post_id.map(L.groupby("post_id").day.min()).fillna("9999") < C.day).astype(np.int8)
    S1 = pd.read_parquet(os.path.join(H.CACHE, "daily_cache.parquet"), columns=["day", "post_id", "text_score"] + [
        f"{t}_{c}" for t in TIMES for c in ("stage1", "c_all", "c_last3h")])
    C = C.merge(S1, on=["day", "post_id"], how="left")
    print("rows", len(C), "days", C.day.nunique(), flush=True)
    for name, off in TIMES.items():
        features(C, S, name, C.t1.to_numpy() - off * 3600)
    C.drop(columns=["r"]).to_parquet(os.path.join(H.CACHE, "daily_v4.parquet"), index=False)
    return C


if __name__ == "__main__":
    SPLIT = sys.argv[1] if len(sys.argv) > 1 else "2026-09-01"
    C = build(sys.argv[2] if len(sys.argv) > 2 else "2026-07-06", sys.argv[3] if len(sys.argv) > 3 else "2026-10-16")
    for t in TIMES:
        vc = [f"{t}_{c}" for c in VC]
        cc = [f"{t}_stage1", f"{t}_c_all", f"{t}_c_last3h", "text_score"]
        D = C[C[f"{t}_visible"] == 1]
        trd, ted = D[D.day < SPLIT], D[D.day >= SPLIT]
        print(f"\n{t}: train days {trd.day.nunique()}, test days {ted.day.nunique()}, real top 30 visible "
              f"{(ted.real_rank <= 30).sum() / ted.day.nunique() / 30:.3f}", flush=True)
        for vname, cols in (("v4 votes/page only", ["on_earlier_list"] + vc), ("v4 + comments stage 1", ["on_earlier_list"] + vc + cc)):
            s = fit_rank(trd, cols).predict(ted[cols])
            s = np.where(ted.on_earlier_list == 1, -1e9, s)
            print(f"  {vname:28s}", json.dumps(score(ted.assign(s=s), "s")), flush=True)
