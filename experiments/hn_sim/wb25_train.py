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

AGE = int(os.environ.get("WB_AGE", "15"))       # checkpoint in minutes: 15 (checkpoint 2) or 60 (checkpoint 1)
SFX = "" if AGE == 15 else f"_{AGE}"
PRM = dict(n_estimators=500, learning_rate=0.03, num_leaves=31, min_child_samples=30, subsample=0.8, subsample_freq=1,
           colsample_bytree=0.8, verbose=-1, random_state=0)
SRC = {"jan_jun": "usersim_sim/raw/hn_early_votes_2025/early_snapshots.jsonl",
       "jul_dec": "usersim_sim/raw/hn_early_votes_2025/jul_dec/early_snapshots.jsonl"}          # Data Feeder (moved from hn-agent)


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
    return A[(A.page == "newest") & (A.age_min >= 0) & (A.age_min <= AGE)]


def build():
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
    Q["cm15"] = Q.post_id.map(c[(lat >= 0) & (lat < AGE * 60)].groupby("story_id").size()).fillna(0)
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
    # content model score (content_ft.py), out of sample everywhere: 2025 rows from the quarter models never trained on
    # their own quarter (oof25_q1..q4), 2026 rows from the cut-Jun-30 model; each as a percentile within its own model
    import store as S
    parts = []
    for n in ["oof25_q1", "oof25_q2", "oof25_q3", "oof25_q4", "jun30"]:
        f = os.path.join(H.CACHE, f"content_scores_{n}.parquet")
        if not os.path.exists(f):
            S._bucket().get_blob(f"usersim_sim/hn_jobs/cache/content_ft/scores_{n}.parquet").download_to_filename(f)
        c_ = pd.read_parquet(f).drop_duplicates("post_id")
        parts.append(c_.assign(content=c_.s.rank(pct=True))[["post_id", "content"]])
    CT = pd.concat(parts).drop_duplicates("post_id", keep="last").set_index("post_id").content
    Q["content"] = Q.post_id.map(CT)
    base_cols = ["text_score"] + bcols + REC + PC + ["cm15", "v_has", "v_score", "v_age", "v_rate", "v_rank_new", "v_comments", "x_vol30", "x_hour"]
    y = Q.y.to_numpy()
    is25 = (Q.day < "2026-01-01").to_numpy()
    print(f"2025 rows {int(is25.sum())} ({int(y[is25].sum())} winners; with a /newest snapshot by 15 min {Q.v_has[is25].mean():.1%}; "
          f"content score {Q.content[is25].notna().mean():.1%}); 2026 rows {int((~is25).sum())} (content {Q.content[~is25].notna().mean():.1%})", flush=True)
    return Q, base_cols, y, is25


def daily_light(first="2026-09-01", last="2026-10-14"):
    """Light model (all 2025 + 2026 rows + content) with a forward daily retrain (train on days <= d - 2) over
    first..last, for the gate / stacker (gate15.py); saves wb25_daily_scores.parquet."""
    Q, base_cols, y, is25 = build()
    cols = base_cols + ["content"]
    days = sorted(d for d in Q.day.unique() if first <= d <= last)
    s = np.full(len(Q), np.nan)
    for d in days:
        tr = (Q.day <= (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")).to_numpy()
        te = (Q.day == d).to_numpy()
        s[te] = lgb.LGBMClassifier(**PRM).fit(Q.loc[tr, cols], y[tr]).predict_proba(Q.loc[te, cols])[:, 1]
    sel = Q.day.isin(days).to_numpy()
    pd.DataFrame({"post_id": Q.post_id[sel].to_numpy(), "light": s[sel]}).to_parquet(os.path.join(H.CACHE, "wb25_daily_scores.parquet"), index=False)
    print(f"saved wb25_daily_scores.parquet ({int(sel.sum())} posts, {len(days)} days)", flush=True)


def main():
    Q, base_cols, y, is25 = build()
    import caught_types as CTY
    kind = CTY.kinds_for(Q)
    arms = {"2026 rows": (base_cols, False), "2026 rows + content": (base_cols + ["content"], False),
            "2025 + 2026 rows": (base_cols, True), "2025 + 2026 rows + content": (base_cols + ["content"], True)}
    # (1) Oct 2-14, forward daily retrain (train on days <= d - 2)
    days = sorted(d for d in Q.day.unique() if "2026-10-02" <= d <= "2026-10-14")
    sc = {a: np.full(len(Q), np.nan) for a in arms}
    for d in days:
        tr = (Q.day <= (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")).to_numpy()
        te = (Q.day == d).to_numpy()
        for a, (cols, with25) in arms.items():
            m = tr & (np.ones(len(Q), bool) if with25 else ~is25)
            sc[a][te] = lgb.LGBMClassifier(**PRM).fit(Q.loc[m, cols], y[m]).predict_proba(Q.loc[te, cols])[:, 1]
    report("Oct 2-14 forward daily retrain", Q, Q.day.isin(days).to_numpy(), sc, kind)
    # (2) Sep 1 - Oct 14, one fit on days <= Aug 31 (same split as the 24.7% full-period headline)
    tr, te = (Q.day <= "2026-08-31").to_numpy(), ((Q.day >= "2026-09-01") & (Q.day <= "2026-10-14")).to_numpy()
    sc2 = {a: np.full(len(Q), np.nan) for a in arms}
    for a, (cols, with25) in arms.items():
        m = tr & (np.ones(len(Q), bool) if with25 else ~is25)
        sc2[a][te] = lgb.LGBMClassifier(**PRM).fit(Q.loc[m, cols], y[m]).predict_proba(Q.loc[te, cols])[:, 1]
    report("Sep 1 - Oct 14, fit on days <= Aug 31", Q, te, sc2, kind)
    # per-post scores for the paired headline test (paired15.py)
    sel1 = Q.day.isin(days).to_numpy()
    out = pd.concat([pd.DataFrame({"post_id": Q.post_id[sel1].to_numpy(), "test": "oct2_14", **{a: v[sel1] for a, v in sc.items()}}),
                     pd.DataFrame({"post_id": Q.post_id[te].to_numpy(), "test": "sep1_oct14", **{a: v[te] for a, v in sc2.items()}})])
    out.to_parquet(os.path.join(H.CACHE, f"wb25_scores{SFX}.parquet"), index=False)
    print(f"saved wb25_scores{SFX}.parquet", flush=True)


def report(title, Q, sel, sc, kind):
    T = Q[sel][["post_id", "day", "y"]].reset_index(drop=True)
    kt = kind[sel]
    c = {a: W.caught_on(T, s[sel]) for a, s in sc.items()}
    ref = c["2026 rows"]
    print(f"\nCaught at 15 min (posting clock), {title} ({int(T.y.sum())} winners):", flush=True)
    for a, v in c.items():
        k = int(T.y.sum())
        flag = pd.Series(sc[a][sel]).rank(ascending=False, method="first").to_numpy() <= k
        types = ", ".join(f"{t} {int((flag & (kt == t)).sum())}/{int((kt == t).sum())}" for t in ("fast", "late", "reup"))
        print(f"   {a:28s} {W.ci2(v)}" + ("" if a == "2026 rows" else f"  vs 2026 rows {W.ci2(v, ref)}") + f" | {types}", flush=True)
    if "2026 rows + content" in c:
        print(f"   2025 rows effect with content: {W.ci2(c['2025 + 2026 rows + content'], c['2026 rows + content'])}", flush=True)


if __name__ == "__main__":
    import sys
    daily_light() if sys.argv[1:] == ["daily"] else main()
