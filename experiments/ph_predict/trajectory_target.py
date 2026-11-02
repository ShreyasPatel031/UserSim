"""Pre-launch forecast trained on the early vote trajectory as well as the final total (pre-launch only: the inputs are
the launch model's inputs, all known before launch; the trajectory is used only as a training target).
Targets from the Wayback homepage captures (hours 4-12 after 00:00 PT, votes visible from hour 4) for past launches:
  vel   log1p(votes at the capture) - log(hours since 00:00 PT), the day's mean removed (early speed within the day)
Steps, rolling monthly (train on earlier months; test Aug-Oct):
  aux   LightGBM on vel from the launch-model inputs, trained on the captured launches of earlier months
  stack LightGBM on final log votes from [launch-model prediction, aux prediction], trained on earlier months
  blend mean of the within-day percentile ranks of the launch-model prediction and the aux prediction (no fitted weight)
Reported: pre-launch daily / weekly top 3/5/10 for the launch model, stack and blend, paired over lists; plus how well
aux predicts the held-out early speed (within-day Spearman on captured days).
usage: python trajectory_target.py <wayback parsed.jsonl> -> results/trajectory_target.json"""
import json, os, sys
import numpy as np, pandas as pd, lightgbm as lgb
from scipy.stats import spearmanr
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from simlab import store
import model as M
from buildcache import build_cached

RANK = {"daily": "out_dailyRank", "weekly": "out_weeklyRank"}


def fit(tr, te, cols, y):
    return np.mean([lgb.LGBMRegressor(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1,
                                      colsample_bytree=0.5, random_state=s, verbose=-1, n_jobs=16).fit(tr[cols], tr[y]).predict(te[cols]) for s in range(3)], 0)


def per_list(T, col, board, k, key):
    out = {}
    for g_key, g in T.groupby(key):
        real = g[g[RANK[board]] <= k]
        if len(real) == k:
            out[g_key] = len(set(g.nlargest(k, col).id) & set(real.id)) / k
    return out


def main(path):
    P, I, E = store.load(); I = I.assign(id=I.id.astype(str))
    B = build_cached(); B["id"] = B.id.astype(str); B = B.drop_duplicates("id")
    C = pd.read_parquet("results/ctrl_preds.parquet"); C["id"] = C.id.astype(str); C = C.drop_duplicates("id")
    inputs = M.cols(B, M.LIVE_SOURCES + M.PAGE_SOURCES)
    W = pd.read_json(path, lines=True, dtype={"post_id": str, "capture_ts": str})
    W = W[(W.capture_kind == "home") & (W.day.astype(str).str.len() == 10) & W.votes.notna()]
    ts = pd.to_datetime(W.capture_ts, format="%Y%m%d%H%M%S", utc=True)
    W["h"] = (ts - pd.to_datetime(W.day).dt.tz_localize("America/Los_Angeles").dt.tz_convert("UTC")).dt.total_seconds() / 3600
    W = W[(W.h >= 4) & (W.h < 12) & (W.votes > 0)].sort_values("h").drop_duplicates("post_id", keep="last")
    W["vel"] = np.log1p(W.votes) - np.log(W.h); W["vel"] -= W.groupby("day").vel.transform("mean")
    A = C[["id", "day", "logv", "all"]].merge(I[["id"] + list(RANK.values())], on="id").merge(B[["id"] + inputs], on="id", how="left")
    A["vel"] = A.id.map(dict(zip(W.post_id, W.vel)))
    A["week"] = pd.to_datetime(A.day).dt.strftime("%G-W%V"); A["mon"] = A.day.str[:7]
    out = []
    for m in sorted(A.mon.unique()):
        if m < "2026-08":
            continue
        tr, te = A[A.mon < m], A[A.mon == m].copy()
        trv = tr[tr.vel.notna()]
        te["aux"] = fit(trv, te, inputs, "vel")
        tr = tr.copy(); tr["aux"] = np.nan
        # aux for training rows of the stack: out-of-sample by month as well
        for m2 in sorted(tr.mon.unique()):
            if m2 < "2026-08":
                continue
            t2 = A[(A.mon < m2) & A.vel.notna()]
            tr.loc[tr.mon == m2, "aux"] = fit(t2, tr[tr.mon == m2], inputs, "vel")
        trs = tr[tr.aux.notna()]
        te["stack"] = fit(trs, te, ["all", "aux"], "logv") if len(trs) > 200 else np.nan
        te["blend"] = te.groupby("day")["all"].rank(pct=True) + te.groupby("day").aux.rank(pct=True)
        out.append(te)
    T = pd.concat(out)
    H = T[T.vel.notna()]
    res = {"launches": len(T), "captured_launches_with_vel": int(A.vel.notna().sum()),
           "aux_spearman_with_heldout_early_speed": round(float(np.nanmean([spearmanr(g.aux, g.vel).correlation for _, g in H.groupby("day") if len(g) >= 5])), 3),
           "launch_model_spearman_with_heldout_early_speed": round(float(np.nanmean([spearmanr(g["all"], g.vel).correlation for _, g in H.groupby("day") if len(g) >= 5])), 3)}
    rng = np.random.default_rng(0)
    for board, key in (("daily", "day"), ("weekly", "week")):
        for k in (3, 5, 10):
            base = per_list(T, "all", board, k, key); line = {"launch model": round(100 * float(np.mean(list(base.values()))), 1), "lists": len(base)}
            for c in ("stack", "blend"):
                if T[c].notna().all() or c == "blend":
                    cur = per_list(T.dropna(subset=[c]), c, board, k, key); ks = sorted(set(base) & set(cur))
                    d = np.array([cur[x] - base[x] for x in ks]); bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(5000)]
                    line[c] = [round(100 * float(np.mean([cur[x] for x in ks])), 1), round(100 * float(d.mean()), 1), [round(100 * float(x), 1) for x in np.percentile(bs, [2.5, 97.5])]]
            res[f"{board} top{k}"] = line
    json.dump(res, open("results/trajectory_target.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
