"""Checkpoint 2 (15 min) with a 2025+ training set: honest early votes from Wayback /newest for 2025 (Data Feeder
Jan-Jun: raw/hn_early_votes_2025/early_snapshots.jsonl; hn-agent Jul-Dec: .../hn_agent_h2/early_snapshots.jsonl)
plus the October 2026 archive. Same forward daily retrain on Oct 2-14 2026; with vs without the 2025 rows, paired.

Inputs that exist for 2025 posts without leaking: post features (b_*), title score, the real-list record (domain /
site / author, earlier settled posts only), title embedding (PCA 64, every 2025+ title embedded), comments by 15 min,
Wayback votes by 15 min (votes15), posting volume in the 30 min before and hour. Not used: who commented early (their
records are measured before Jul 2026, i.e. after the 2025 rows) and the history score (trained on 2025).

    python wb25_train.py     # uses whatever 2025 months have landed
"""
import json
import os

import lightgbm as lgb
import numpy as np
import pandas as pd

import emb_io
import levers as LV
import odds_live as OL
import store as S
import top100 as H
import wb_caught as W

PRM = dict(n_estimators=500, learning_rate=0.03, num_leaves=31, min_child_samples=30, subsample=0.8, subsample_freq=1,
           colsample_bytree=0.8, verbose=-1, random_state=0)
SRC = {"jan_jun": "usersim_sim/raw/hn_early_votes_2025/early_snapshots.jsonl",
       "jul_dec": "usersim_sim/raw/hn_early_votes_2025/hn_agent_h2/early_snapshots.jsonl"}


def snapshots():
    b = S._bucket()
    parts = [pd.read_json(W.EV, lines=True, convert_dates=False)]
    for k, path in SRC.items():
        x = b.get_blob(path)
        if x is not None:
            f = os.path.join(H.CACHE, "early_votes", f"early_snapshots_2025_{k}.jsonl")
            x.download_to_filename(f)
            parts.append(pd.read_json(f, lines=True, convert_dates=False))
    A = pd.concat(parts, ignore_index=True)
    return A[(A.page == "newest") & (A.age_min >= 0) & (A.age_min <= 15)]


def main():
    N = snapshots()
    months25 = sorted(pd.to_datetime(N[N.capture_ts.astype(str).str[:4] == "2025"].capture_ts.astype(str).str[:6], format="%Y%m").dt.strftime("%Y-%m").unique())
    print("2025 months with captures:", months25, flush=True)
    p = H.stories()
    p = p[((p.day >= "2025-01-01") & (p.day <= "2025-12-31")) | ((p.day >= "2026-07-01") & (p.day <= "2026-10-14"))].reset_index(drop=True)
    p = p[(p.day >= "2026-07-01") | p.day.str[:7].isin(months25)].reset_index(drop=True)
    L = OL.lists()
    p["y"] = p.post_id.isin(set(L[L["rank"] <= 30].post_id)).astype(int)
    B = pd.read_parquet(os.path.join(H.CACHE, "daily_cache.parquet"))
    bcols = [c for c in B.columns if c.startswith("b_") and not c.startswith(("b_w30_", "b_w60_"))]
    B = B[["post_id", "text_score"] + bcols].drop_duplicates("post_id")
    R = LV.record(H.stories(), set(p.post_id))
    Q = p.merge(B, on="post_id", how="left").merge(R, on="post_id", how="left")
    # title embedding PCA (fit on 2025 rows)
    from sklearn.decomposition import PCA
    emb, ei = emb_io.load()
    rows = ei.reindex(Q.post_id).to_numpy()
    ok = ~np.isnan(rows)
    fit_idx = np.where(ok & (Q.day < "2026-07-01").to_numpy())[0]
    rng = np.random.default_rng(0)
    samp = np.sort(rng.choice(fit_idx, min(60000, len(fit_idx)), replace=False)) if len(fit_idx) else np.where(ok)[0][:60000]
    pca = PCA(32, random_state=0).fit(np.asarray(emb[np.sort(rows[samp].astype(int))], np.float32))
    Z = np.full((len(Q), 32), np.nan, np.float32)
    idx = np.where(ok)[0]
    for i in range(0, len(idx), 50000):
        j = idx[i:i + 50000]
        r = rows[j].astype(int)
        o = np.argsort(r)
        Z[j[o]] = pca.transform(np.asarray(emb[r[o]], np.float32))
    PC = [f"pc{k}" for k in range(32)]
    Q = pd.concat([Q, pd.DataFrame(Z, columns=PC)], axis=1)
    # comments by 15 min
    c = pd.read_parquet(os.path.join(H.CACHE, "bq_comments.parquet"), columns=["story_id", "created_at_i"])
    born = Q.set_index("post_id").created_at_i
    c = c[c.story_id.isin(born.index)]
    lat = c.created_at_i - c.story_id.map(born).to_numpy()
    Q["cm15"] = Q.post_id.map(c[(lat >= 0) & (lat < 900)].groupby("story_id").size()).fillna(0)
    # Wayback votes by 15 min
    last = N.sort_values("age_min").drop_duplicates("item_id", keep="last").set_index("item_id")
    Q["v_has"] = Q.post_id.isin(last.index).astype(int)
    Q["v_score"], Q["v_age"] = Q.post_id.map(last.score), Q.post_id.map(last.age_min)
    Q["v_rate"] = (Q.v_score - 1) / Q.v_age.clip(lower=1)
    Q["v_rank_new"], Q["v_comments"] = Q.post_id.map(last["rank"]), Q.post_id.map(last.comments)
    b = Q.created_at_i.to_numpy()
    ct = np.sort(b)
    Q["x_vol30"] = np.searchsorted(ct, b) - np.searchsorted(ct, b - 1800)
    Q["x_hour"] = (b // 3600) % 24
    REC = [c_ for c_ in R.columns if c_ != "post_id"]
    X = Q[["text_score"] + bcols + REC + PC + ["cm15", "v_has", "v_score", "v_age", "v_rate", "v_rank_new", "v_comments", "x_vol30", "x_hour"]]
    y = Q.y.to_numpy()
    is25 = (Q.day < "2026-01-01").to_numpy()
    print(f"2025 rows {int(is25.sum())} ({int(y[is25].sum())} winners; with a /newest snapshot by 15 min {Q.v_has[is25].mean():.1%}); "
          f"2026 rows {int((~is25).sum())}", flush=True)
    days = sorted(d for d in Q.day.unique() if "2026-10-02" <= d <= "2026-10-14")
    s0, s1 = np.full(len(Q), np.nan), np.full(len(Q), np.nan)
    for d in days:
        tr = (Q.day <= (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")).to_numpy()
        te = (Q.day == d).to_numpy()
        s0[te] = lgb.LGBMClassifier(**PRM).fit(X[tr & ~is25], y[tr & ~is25]).predict_proba(X[te])[:, 1]
        s1[te] = lgb.LGBMClassifier(**PRM).fit(X[tr], y[tr]).predict_proba(X[te])[:, 1]
    sel = Q.day.isin(days).to_numpy()
    T = Q[sel][["post_id", "day", "y"]].reset_index(drop=True)
    c0, c1 = W.caught_on(T, s0[sel]), W.caught_on(T, s1[sel])
    print(f"Caught at 15 min, Oct 2-14 ({int(T.y.sum())} winners): trained Jul 2026+ {W.ci2(c0)}; + 2025 rows {W.ci2(c1)}; "
          f"difference {W.ci2(c1, c0)}", flush=True)


if __name__ == "__main__":
    main()
