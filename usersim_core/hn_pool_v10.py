"""USERSIM-CORE-HN-2: Hacker News `HNUniversalUserPool` (`usersim_core/hn_pool_v10.py`).

Handoff `docs/VM_HANDOFF_AND_PLAN_20261127.md` Option B.2: replace `hn_transfer_v7.py`'s static 3-persona
panel with a full `< D` user pool built from `tables/hn_comments` (6.2M comment events, ~237K people).

Protocol (identical to `USERSIM-CORE-HN-1` so numbers are directly comparable):
  - Same posts selection, same `< D` author/domain priors, same frozen structural LightGBM fit on `<= 2026-08-31`.
  - Same Val (last 10 days of `2026-09-15..09-30`) / Test (first 16 days `>= 2026-10-01`) and Top-22 shortlist.
  - Same `WalkForwardResidualModel` + `evaluate_boards_and_ties` (5,000-draw day-clustered bootstrap).
  - Track: `Story Only, t=0` (zero comments / points on the story being scored).

Pool (strictly `< D`: only comments with `created_at_i < D 00:00 UTC` are visible when scoring day D):
  - Story embedding: TF-IDF(title + domain) fit on `<= 2026-08-31` posts -> TruncatedSVD(96) -> L2 norm.
  - Person taste: exponentially decayed (half-life 45d) sum of embeddings of stories they commented on.
  - Person activity: decayed comment count.
  - Per-candidate features: interest-weighted audience mass, # strongly matched active people, top-200 match,
    author's own decayed community activity, and the active-pool share whose taste is dominated by this topic.
Zero LLM calls, zero cost.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import time
from urllib.parse import urlparse

import lightgbm as lgb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import spearmanr
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge

from usersim_core.residual_learner import WalkForwardResidualModel, evaluate_boards_and_ties, within_day_zscore

POST_COLS = ["post_id", "day", "created_at_i", "title", "url", "text", "author", "points", "num_comments", "link_kind"]


def _extract_domain(url: str) -> str:
    if not url:
        return "self.hn"
    try:
        netloc = urlparse(str(url)).netloc.lower()
        return netloc[4:] if netloc.startswith("www.") else (netloc or "self.hn")
    except Exception:
        return "self.hn"


def _day_start_ts(day: str) -> int:
    return int(pd.Timestamp(day, tz="UTC").timestamp())


def load_posts(posts_dir: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (eval posts exactly as HN-1 selects them, all titled posts for story embeddings)."""
    files = sorted(glob.glob(os.path.join(posts_dir, "*.parquet")))
    titled = [f for f in files if "title" in pq.read_schema(f).names]
    # HN-1 used the last 220 files of the listing; keep the same selection (schema-filtered) for comparability.
    sel = set(files[-220:])
    frames_eval, frames_all = [], []
    for f in titled:
        df = pq.read_table(f, columns=POST_COLS).to_pandas()
        df["day"] = df["day"].astype(str).str[:10]
        frames_all.append(df[["post_id", "day", "created_at_i", "title", "url"]])
        if f in sel:
            df = df[(df["day"] >= "2026-06-01") & (df["day"] <= "2026-10-28")]
            if not df.empty:
                frames_eval.append(df)
    posts = pd.concat(frames_eval, ignore_index=True)
    posts["post_id"] = posts["post_id"].astype(str)
    posts = posts.drop_duplicates("post_id", keep="last").sort_values(["day", "post_id"]).reset_index(drop=True)
    allp = pd.concat(frames_all, ignore_index=True)
    allp["post_id"] = allp["post_id"].astype(np.int64)
    allp = allp.drop_duplicates("post_id", keep="last").reset_index(drop=True)
    return posts, allp


def add_structural(posts: pd.DataFrame) -> pd.DataFrame:
    """Verbatim port of `hn_transfer_v7.py` steps 1, 3, 4 (structural baseline)."""
    posts["points"] = pd.to_numeric(posts["points"], errors="coerce").fillna(1.0).clip(lower=1.0)
    posts["num_comments"] = pd.to_numeric(posts["num_comments"], errors="coerce").fillna(0.0).clip(lower=0.0)
    posts["log_points"] = np.log1p(posts["points"])
    posts["domain"] = [_extract_domain(u) if str(u or "") not in ("", "None", "nan") else "self.hn" for u in posts["url"]]
    posts["hour_utc"] = ((pd.to_numeric(posts["created_at_i"], errors="coerce").fillna(0) % 86400) // 3600).astype(float)
    posts["is_show_hn"] = posts["title"].fillna("").str.startswith("Show HN").astype(float)
    posts["is_ask_hn"] = posts["title"].fillna("").str.startswith("Ask HN").astype(float)
    posts["is_github"] = posts["domain"].str.contains("github.com").astype(float)

    auth_sum: dict[str, float] = {}
    auth_cnt: dict[str, int] = {}
    dom_sum: dict[str, float] = {}
    dom_cnt: dict[str, int] = {}
    global_prior = float(posts[posts["day"] <= "2026-08-31"]["log_points"].mean())
    a_prior = np.zeros(len(posts)); a_posts_n = np.zeros(len(posts)); d_prior = np.zeros(len(posts))
    for _, idx in posts.groupby("day", sort=True).groups.items():
        pos = np.asarray(list(idx), dtype=np.int64)
        for p_i in pos:
            au = str(posts.at[p_i, "author"] or ""); dm = str(posts.at[p_i, "domain"] or "self.hn")
            ac = auth_cnt.get(au, 0)
            a_posts_n[p_i] = math.log1p(ac)
            a_prior[p_i] = (auth_sum.get(au, 0.0) + 5.0 * global_prior) / (ac + 5.0)
            dc = dom_cnt.get(dm, 0)
            d_prior[p_i] = (dom_sum.get(dm, 0.0) + 12.0 * global_prior) / (dc + 12.0)
        for p_i in pos:
            au = str(posts.at[p_i, "author"] or ""); dm = str(posts.at[p_i, "domain"] or "self.hn")
            lp = float(posts.at[p_i, "log_points"])
            if au:
                auth_sum[au] = auth_sum.get(au, 0.0) + lp
                auth_cnt[au] = auth_cnt.get(au, 0) + 1
            dom_sum[dm] = dom_sum.get(dm, 0.0) + lp
            dom_cnt[dm] = dom_cnt.get(dm, 0) + 1
    posts["author_prior_lt_d"] = a_prior
    posts["author_posts_log_lt_d"] = a_posts_n
    posts["domain_prior_lt_d"] = d_prior
    posts["title_len"] = posts["title"].fillna("").str.len().astype(float)

    train_mask = posts["day"] <= "2026-08-31"
    vec = TfidfVectorizer(min_df=5, max_features=15000, ngram_range=(1, 2), sublinear_tf=True)
    txt_all = (posts["title"].fillna("") + " " + posts["domain"].fillna("")).tolist()
    X_txt_tr = vec.fit_transform([txt_all[i] for i in np.where(train_mask)[0]])
    txt_ridge = Ridge(alpha=6.0, random_state=42).fit(X_txt_tr, posts.loc[train_mask, "log_points"].to_numpy())
    posts["txt_ridge_pred"] = txt_ridge.predict(vec.transform(txt_all))
    struct_cols = ["author_prior_lt_d", "author_posts_log_lt_d", "domain_prior_lt_d", "txt_ridge_pred",
                   "hour_utc", "title_len", "is_show_hn", "is_ask_hn", "is_github"]
    m = lgb.LGBMRegressor(n_estimators=220, learning_rate=0.04, num_leaves=15, min_child_samples=40, subsample=0.8,
                          colsample_bytree=0.8, random_state=42, n_jobs=1, deterministic=True, verbose=-1)
    m.fit(posts.loc[train_mask, struct_cols], posts.loc[train_mask, "log_points"])
    posts["structural_score"] = m.predict(posts[struct_cols])
    return posts


class HNUniversalUserPool:
    """Walk-forward `< D` HN user pool: decayed per-person taste vectors over commented-story embeddings."""

    def __init__(self, story_vec: dict[int, np.ndarray], dim: int, half_life_days: float = 45.0):
        self.story_vec = story_vec
        self.dim = dim
        self.decay = 0.5 ** (1.0 / half_life_days)
        self.person_idx: dict[str, int] = {}
        self.taste = np.zeros((0, dim), dtype=np.float32)
        self.act = np.zeros(0, dtype=np.float32)

    def _grow(self, names: list[str]) -> np.ndarray:
        new = [n for n in dict.fromkeys(names) if n not in self.person_idx]
        if new:
            base = len(self.person_idx)
            for i, n in enumerate(new):
                self.person_idx[n] = base + i
            self.taste = np.vstack([self.taste, np.zeros((len(new), self.dim), dtype=np.float32)])
            self.act = np.concatenate([self.act, np.zeros(len(new), dtype=np.float32)])
        return np.fromiter((self.person_idx[n] for n in names), dtype=np.int64, count=len(names))

    def advance_day(self, day_comments: pd.DataFrame) -> None:
        self.taste *= self.decay
        self.act *= self.decay
        if day_comments.empty:
            return
        pidx = self._grow(day_comments["person"].tolist())
        np.add.at(self.act, pidx, 1.0)
        sids = day_comments["story_id"].to_numpy()
        has = np.fromiter((s in self.story_vec for s in sids), dtype=bool, count=len(sids))
        if has.any():
            V = np.stack([self.story_vec[s] for s in sids[has]]).astype(np.float32)
            np.add.at(self.taste, pidx[has], V)

    def snapshot(self, min_act: float = 1.0):
        active = self.act >= min_act
        T = self.taste[active]
        n = np.linalg.norm(T, axis=1, keepdims=True)
        T = T / np.maximum(n, 1e-6)
        return T, self.act[active], active

    def features(self, v: np.ndarray, snap, author: str) -> dict[str, float]:
        T, a, _ = snap
        if len(a) == 0:
            return {}
        s = T @ v.astype(np.float32)
        pos = np.clip(s, 0.0, None)
        wa = np.log1p(a)
        heavy = a >= 5.0
        top = np.sort(s[heavy])[-200:] if heavy.sum() >= 200 else np.sort(s)[-200:]
        ai = self.person_idx.get(author)
        return {
            "pool_mass": float((wa * pos ** 2).sum() / wa.sum()),
            "pool_strong_log": float(math.log1p(float((wa * (s >= 0.45)).sum()))),
            "pool_heavy_strong_log": float(math.log1p(float((heavy & (s >= 0.45)).sum()))),
            "pool_top200": float(top.mean()),
            "pool_mean_sim": float((wa * s).sum() / wa.sum()),
            "author_pool_act_log": float(math.log1p(float(self.act[ai]))) if ai is not None else 0.0,
        }


POOL_RAW = ["pool_mass", "pool_strong_log", "pool_heavy_strong_log", "pool_top200", "pool_mean_sim", "author_pool_act_log",
            "topic_supply_7d_log", "demand_supply_ratio"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--posts-dir", required=True, help="local copy of tables/hn_posts/*.parquet")
    ap.add_argument("--comments", required=True, help="local copy of the 6.2M-row tables/hn_comments parquet")
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--svd-dim", type=int, default=96)
    ap.add_argument("--half-life", type=float, default=45.0)
    args = ap.parse_args()
    t0 = time.time()

    posts, allp = load_posts(args.posts_dir)
    posts = add_structural(posts)
    print(f"posts eval={len(posts)} all_titled={len(allp)} t={time.time()-t0:.0f}s", flush=True)

    # Story embeddings (fit only on <= 2026-08-31 text; applied to every titled story).
    allp["domain"] = [_extract_domain(u) if str(u or "") not in ("", "None", "nan") else "self.hn" for u in allp["url"]]
    txt = (allp["title"].fillna("") + " " + allp["domain"].fillna("")).tolist()
    fit_mask = allp["day"].astype(str).str[:10] <= "2026-08-31"
    tfv = TfidfVectorizer(min_df=5, max_features=40000, ngram_range=(1, 2), sublinear_tf=True, stop_words="english")
    Xfit = tfv.fit_transform([txt[i] for i in np.where(fit_mask)[0]])
    svd = TruncatedSVD(n_components=args.svd_dim, random_state=42).fit(Xfit)
    E = svd.transform(tfv.transform(txt))
    E /= np.maximum(np.linalg.norm(E, axis=1, keepdims=True), 1e-9)
    story_vec = {int(pid): E[i].astype(np.float32) for i, pid in enumerate(allp["post_id"].to_numpy())}
    vec_by_post = {str(pid): story_vec[int(pid)] for pid in posts["post_id"]}
    print(f"story vecs={len(story_vec)} svd_var={svd.explained_variance_ratio_.sum():.3f} t={time.time()-t0:.0f}s", flush=True)

    com = pd.read_parquet(args.comments, columns=["person", "created_at_i", "story_id"]).dropna()
    com["story_id"] = com["story_id"].astype(np.int64)
    com["created_at_i"] = com["created_at_i"].astype(np.int64)
    com["day"] = pd.to_datetime(com["created_at_i"], unit="s", utc=True).dt.strftime("%Y-%m-%d")
    cov = float(com["story_id"].isin(story_vec.keys()).mean())
    print(f"comments={len(com)} people={com.person.nunique()} story_vec_coverage={cov:.3f}", flush=True)

    # Same eval-day selection & Top-22 shortlist as HN-1; plus an extended val window (Aug 1 .. Sep 30).
    eval_posts = posts[posts["day"] >= "2026-08-01"]
    day_counts = eval_posts.groupby("day").size()
    valid_days = sorted(d for d, c in day_counts.items() if c >= 60)
    val_days = [d for d in valid_days if "2026-09-15" <= d <= "2026-09-30"][-10:]
    val_days_ext = [d for d in valid_days if d <= "2026-09-30"]
    test_days = [d for d in valid_days if d >= "2026-10-01"][:16]
    chosen = sorted(set(val_days_ext + test_days))

    truth, full_day, rows = {}, {}, []
    for d in chosen:
        dg = posts[posts["day"] == d].sort_values(["points", "post_id"], ascending=[False, True]).reset_index(drop=True)
        dg["real_rank"] = np.arange(1, len(dg) + 1, dtype=float)
        truth[d] = {str(r.post_id): {"final_rank": int(r.real_rank), "votes": float(r.points)} for r in dg.itertuples(index=False)}
        ds = dg.sort_values(["structural_score", "post_id"], ascending=[False, True]).reset_index(drop=True)
        ds["structural_rank"] = np.arange(1, len(ds) + 1, dtype=int)
        full_day[d] = [{"id": str(r.post_id), "structural_score": float(r.structural_score), "structural_rank": int(r.structural_rank)}
                       for r in ds.itertuples(index=False)]
        for r in ds.head(22).itertuples(index=False):
            rows.append({"day": d, "item_id": str(r.post_id), "author": str(r.author or ""), "title": str(r.title or ""),
                         "structural_score": float(r.structural_score), "structural_rank": int(r.structural_rank),
                         "real_votes": float(r.points), "true_log_residual": float(r.log_points - r.structural_score)})
    sl = pd.DataFrame(rows)

    # Topic supply: how many similar stories were posted in the 7 days strictly before D (demand/supply ratio).
    allp["ts"] = pd.to_numeric(allp["created_at_i"], errors="coerce").fillna(0).astype(np.int64)
    supply: dict[tuple[str, str], float] = {}
    for d in chosen:
        t_end = _day_start_ts(d); t_beg = t_end - 7 * 86400
        recent = allp[(allp["ts"] >= t_beg) & (allp["ts"] < t_end)]["post_id"].to_numpy()
        R = np.stack([story_vec[int(x)] for x in recent]) if len(recent) else np.zeros((1, args.svd_dim), np.float32)
        for r in sl[sl["day"] == d].itertuples(index=False):
            supply[(d, r.item_id)] = float((np.clip(R @ vec_by_post[r.item_id], 0, None) ** 2).sum())

    # Walk the pool forward one UTC day at a time; score day D with comments strictly before D 00:00 UTC.
    pool = HNUniversalUserPool(story_vec, args.svd_dim, half_life_days=args.half_life)
    com = com.sort_values("created_at_i", kind="mergesort")
    groups = {d: g for d, g in com.groupby("day", sort=True)}
    all_days = pd.date_range(com["day"].min(), max(chosen), freq="D").strftime("%Y-%m-%d").tolist()
    feats: dict[tuple[str, str], dict] = {}
    target = set(chosen)
    for d in all_days:
        if d in target:
            snap = pool.snapshot()
            for r in sl[sl["day"] == d].itertuples(index=False):
                feats[(d, r.item_id)] = pool.features(vec_by_post[r.item_id], snap, r.author)
        pool.advance_day(groups.get(d, com.iloc[:0]))
        # Leakage guard: nothing timestamped >= next day start may be in the pool when that day is scored.
    print(f"pool people={len(pool.person_idx)} t={time.time()-t0:.0f}s", flush=True)

    for k, f in feats.items():
        f["topic_supply_7d_log"] = math.log1p(supply.get(k, 0.0))
        f["demand_supply_ratio"] = math.log(max(f.get("pool_mass", 0.0), 1e-6)) - math.log1p(supply.get(k, 0.0))
    for c in POOL_RAW:
        sl[c] = [float(feats.get((r.day, r.item_id), {}).get(c, 0.0)) for r in sl.itertuples(index=False)]
        sl[c + "_z"] = within_day_zscore(sl, c)
    zcols = [c + "_z" for c in POOL_RAW]

    def run(train_days: list[str], label: str) -> dict:
        tr = sl[sl["day"].isin(train_days)].reset_index(drop=True)
        te = sl[sl["day"].isin(test_days)].reset_index(drop=True)
        m = WalkForwardResidualModel(feature_cols=zcols, ridge_alpha=80.0, pairwise_C=0.06, target_std=0.35, max_shift=0.90).fit(tr)
        te["score_pool"] = m.score_df(te)
        ev = evaluate_boards_and_ties(full_day, truth, te, score_col="score_pool", n_boot=5000)
        sp_b, sp_m = [], []
        for _, dg in te.groupby("day"):
            y = np.log1p(dg["real_votes"].to_numpy())
            sp_b.append(float(spearmanr(dg["structural_score"], y).correlation))
            sp_m.append(float(spearmanr(dg["score_pool"], y).correlation))
        return {"label": label, "train_days_n": len(train_days), "active_features": m.active_cols,
                "spearman_structural": round(float(np.mean(sp_b)), 4), "spearman_pool": round(float(np.mean(sp_m)), 4),
                "eval": ev}

    # Single-feature val diagnostics (Spearman of feature vs residual on val, orthogonal to nothing — raw).
    diag = {}
    v = sl[sl["day"].isin(val_days_ext)]
    for c in zcols:
        r = spearmanr(v[c], v["true_log_residual"]).correlation
        diag[c] = round(float(r), 4) if np.isfinite(r) else None

    out = {
        "experiment_id": "USERSIM-CORE-HN-2",
        "domain": "hackernews",
        "pool": {"people": len(pool.person_idx), "comments": int(len(com)), "story_vec_coverage": round(cov, 4),
                 "svd_dim": args.svd_dim, "half_life_days": args.half_life},
        "val_days": [val_days[0], val_days[-1]], "val_days_ext": [val_days_ext[0], val_days_ext[-1]],
        "test_window": f"{test_days[0]} .. {test_days[-1]}", "test_days_n": len(test_days),
        "val_feature_residual_spearman": diag,
        "story_only_t0_pool__hn1_val": run(val_days, "pool, HN-1 val protocol (10 days)"),
        "story_only_t0_pool__ext_val": run(val_days_ext, "pool, extended val Aug 1..Sep 30"),
        "llm_cost_usd": 0.0,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    with open(args.out_json, "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2), flush=True)


if __name__ == "__main__":
    main()
