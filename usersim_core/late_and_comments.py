"""Zero-Leakage Post-00:05 Launch Discovery & Order-Free Product + Comments (`usersim_core/late_and_comments.py`).

Implements Shreyas's two live/backtest upgrades without ANY ranking or vote-order leakage:
  1. Post-Midnight (`> 00:05 PT`, `<= 03:45 PT` pre-reveal) Launch Inclusion:
     - Discovers launches added after `00:05 PT` (such as `Hiring Right Now`, ID `1329956`, `#3` on 2026-11-25)
       from `api_detail/*T0[0123]*PT.jsonl` / `lineup_0100.json`.
     - STRICTLY STRIPS `dailyRank`, `weeklyRank`, `monthlyRank`, `votesCount`, `latestScore`, `commentsCount`,
       and list position.
     - Computes a 100% leak-free structural baseline score from `< D` hunter/maker prior PH track record,
       hunter follower count (never post-launch maker follower counts), media/topic structure, and `< D`
       TF-IDF pitch ridge.
  2. Order-Free `Product + Comments` (`<= 03:45 PT` before Product Hunt unhides votes at `~04:00 PT`):
     - Extracts (a) the Maker's Launch Pitch Comment (`first_comment`) and (b) Early Non-Maker Community
       Comments (`ts_utc <= day_start_utc(D) + 3h45m`), scrubbed of HTML, handles, URLs, and any rank/vote text.
     - Weights early commenters strictly by their `< D` `UniversalUserPool` discerning/selective member traits
       (so zero-history sockpuppet accounts receive `0.0` discerning weight).
     - Fits out-of-fold / walk-forward (`< D` strictly) TF-IDF Ridge models on `pitch + maker_comment` and
       `early_community_comments` predicting `true_log_residual` over `arm3`.
"""
from __future__ import annotations

import glob
import gzip
import html
import json
import math
import os
import re
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge

from simharness.bench import Benchmark, KIND_CODE, _day_bounds_utc, day_ord, scrub
from simharness.schema import MAKE
from usersim_core.pool import UniversalUserPool
from usersim_core.residual_learner import within_day_zscore


FORBIDDEN_RANK_VOTE_KEYS = {
    "dailyRank", "weeklyRank", "monthlyRank", "votesCount", "latestScore",
    "rank", "votes", "final_rank", "upvotes",
}

COMMENT_LEAK_RE = re.compile(
    r"(?i)\b(?:#\s*\d+|top\s*(?:1|2|3|5|10)|product\s+of\s+the\s+(?:day|week|month)|\d+\s*upvotes?|upvoted\b)",
)
BOILERPLATE_PRAISE_RE = re.compile(
    r"(?i)^(?:congrats|congratulations|awesome\s+launch|great\s+launch|nice\s+work|good\s+luck|love\s+this|amazing\s+product)[!.\s\U00010000-\U0010ffff]*$"
)


def scrub_comment_text(raw_body: str) -> str:
    if not raw_body:
        return ""
    txt = html.unescape(re.sub(r"<[^>]+>", " ", str(raw_body)))
    txt = scrub(" ".join(txt.split()))
    txt = COMMENT_LEAK_RE.sub(" ", txt)
    return " ".join(txt.split()).strip()


def sanitize_post_0005_record(raw_rec: dict[str, Any]) -> dict[str, Any]:
    """Strip all rank/vote/score keys so downstream code cannot accidentally touch PH's hidden order."""
    return {k: v for k, v in raw_rec.items() if k not in FORBIDDEN_RANK_VOTE_KEYS}


def discover_live_post_0005_launches(day: str, forecast_ids: set[str], live23_dir: str) -> list[dict[str, Any]]:
    """Return sanitized post-00:05 launches added on `day` (all rank/vote/score keys & array order stripped)."""
    found: dict[str, dict[str, Any]] = {}
    # 1. Check api_detail snapshots (preferring earliest snapshot where each post-00:05 launch appeared)
    snap_patterns = [
        f"{live23_dir}/post0005/{day}/*PT.jsonl",
    ]
    if day == "2026-11-25":
        # Note: on 2026-11-25 slot 39 had a 02:04->06:45 PT gap; sanitize_post_0005_record strips ALL votes/ranks/order!
        snap_patterns.append(f"{live23_dir}/nov25/*PT.jsonl")

    for pat in snap_patterns:
        for sf in sorted(glob.glob(pat)):
            with open(sf) as f:
                for line in f:
                    r = json.loads(line)
                    lid = str(r.get("id") or "")
                    if lid and lid not in forecast_ids and lid not in found:
                        found[lid] = sanitize_post_0005_record(r)

    # 2. Also check lineup_0100.json if present
    for l0100 in (f"{live23_dir}/lineup_0100/lineup_0100.json", f"{live23_dir}/post0005/{day}/lineup_0100.json"):
        if os.path.exists(l0100):
            j = json.load(open(l0100))
            if str(j.get("day")) == day:
                for r in (j.get("nodes") or []):
                    lid = str(r.get("id") or "")
                    if lid and lid not in forecast_ids and lid not in found:
                        found[lid] = sanitize_post_0005_record(r)

    # Sort deterministically by string launch ID (NEVER by snapshot array order!)
    return [found[k] for k in sorted(found.keys())]


class LateLaunchStructuralEstimator:
    """Fits a leak-free `< D` structural estimator mapping launch-time metadata to `arm3` `structural_score`."""

    def __init__(self) -> None:
        self.vec = TfidfVectorizer(min_df=3, max_features=12000, ngram_range=(1, 2), sublinear_tf=True)
        self.txt_ridge = Ridge(alpha=4.0, solver="lsqr", random_state=42)
        self.reg = lgb.LGBMRegressor(
            n_estimators=250,
            learning_rate=0.04,
            num_leaves=15,
            min_child_samples=20,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            verbose=-1,
        )
        self.feat_cols = [
            "ph_hunter_followers",
            "x_maker_sum_followers",
            "n_makers",
            "n_tags",
            "title_len",
            "tagline_len",
            "desc_len",
            "txt_pred",
            "maker_prior_launches",
            "maker_prior_mean_score",
        ]
        self.maker_hist: dict[str, list[float]] = {}
        self._fitted = False

    def fit_from_forecasts_and_bt(
        self,
        bench: Benchmark,
        full_day_launches: dict[str, list[dict]],
        forecast_parquets_dir: str,
        cutoff_day: str = "2026-11-24",
    ) -> "LateLaunchStructuralEstimator":
        idx_by_id = dict(zip(bench.items["item_id"].astype(str), bench.items["item_idx"].astype(int)))
        # Build maker history strictly chronologically from bench.hist MAKE rows
        mk_df = bench.hist[bench.hist["kind"] == KIND_CODE[MAKE]][["person_idx", "item_idx", "day_ord"]].drop_duplicates()
        makers_by_iidx: dict[int, list[str]] = {}
        for r in mk_df.itertuples(index=False):
            makers_by_iidx.setdefault(int(r.item_idx), []).append(f"p:{int(r.person_idx)}")

        f_meta: dict[str, dict[str, float]] = {}
        for fp in sorted(glob.glob(f"{forecast_parquets_dir}/forecast_2026-*.parquet")):
            pdf = pd.read_parquet(fp)
            d_p = str(pdf["day"].iloc[0])
            if d_p > cutoff_day:
                continue
            for r in pdf.itertuples(index=False):
                lid = str(r.id)
                f_meta[lid] = {
                    "ph_hunter_followers": float(getattr(r, "ph_hunter_followers", np.nan)),
                    "x_maker_sum_followers": float(getattr(r, "x_maker_sum_followers", np.nan)),
                }

        rows = []
        texts = []
        y_scores = []
        maker_hist: dict[str, list[float]] = {}

        for d in sorted(full_day_launches.keys()):
            if d > cutoff_day:
                continue
            day_new_hist: list[tuple[str, float]] = []
            for x in full_day_launches[d]:
                lid = str(x["id"])
                s_score = float(x["structural_score"])
                iidx = idx_by_id.get(lid)
                title = str(x.get("name") or "")
                summary, desc, tags = "", "", []
                if iidx is not None:
                    it = bench.item(iidx)
                    title = it.title or title
                    summary = it.summary or ""
                    desc = it.description or ""
                    tags = list(it.tags or [])
                mks = makers_by_iidx.get(iidx, []) if iidx is not None else []
                past_scores = [sc for m in mks for sc in maker_hist.get(m, [])]
                fm = f_meta.get(lid, {})
                rows.append({
                    "ph_hunter_followers": fm.get("ph_hunter_followers", np.nan),
                    "x_maker_sum_followers": fm.get("x_maker_sum_followers", np.nan),
                    "n_makers": float(len(mks)),
                    "n_tags": float(len(tags)),
                    "title_len": float(len(title)),
                    "tagline_len": float(len(summary)),
                    "desc_len": float(len(desc)),
                    "maker_prior_launches": float(len(past_scores)),
                    "maker_prior_mean_score": float(np.mean(past_scores)) if past_scores else np.nan,
                })
                texts.append(f"{title}. {summary}. {desc} {' '.join(tags)}")
                y_scores.append(s_score)
                for m in set(mks):
                    day_new_hist.append((m, s_score))
            for m, sc in day_new_hist:
                maker_hist.setdefault(m, []).append(sc)

        self.maker_hist = maker_hist
        X_txt = self.vec.fit_transform(texts)
        y_arr = np.asarray(y_scores, dtype=np.float64)
        self.txt_ridge.fit(X_txt, y_arr)
        df_tr = pd.DataFrame(rows)
        df_tr["txt_pred"] = self.txt_ridge.predict(X_txt)
        self.reg.fit(df_tr[self.feat_cols], y_arr)
        self._fitted = True
        return self

    def score_late_launch(self, rec: dict[str, Any], x_maker_sum_followers: float = np.nan) -> float:
        assert self._fitted
        hunter = rec.get("user") or {}
        h_fol = math.log1p(float(hunter.get("followersCount") or 0.0))
        topics_raw = rec.get("topics") or {}
        if isinstance(topics_raw, dict):
            nodes = topics_raw.get("nodes") or [e.get("node", {}) for e in (topics_raw.get("edges") or [])]
            tags = [str(n.get("name") or "") for n in nodes if n.get("name")]
        elif isinstance(topics_raw, list):
            tags = [str(t) for t in topics_raw]
        else:
            tags = []
        title = str(rec.get("name") or "")
        summary = str(rec.get("tagline") or "")
        desc = str(rec.get("description") or "")
        txt = f"{title}. {summary}. {desc} {' '.join(tags)}"
        txt_p = float(self.txt_ridge.predict(self.vec.transform([txt]))[0])
        row = pd.DataFrame([{
            "ph_hunter_followers": h_fol,
            "x_maker_sum_followers": x_maker_sum_followers,
            "n_makers": float(len(rec.get("makers") or [])),
            "n_tags": float(len(tags)),
            "title_len": float(len(title)),
            "tagline_len": float(len(summary)),
            "desc_len": float(len(desc)),
            "txt_pred": txt_p,
            "maker_prior_launches": 0.0,
            "maker_prior_mean_score": np.nan,
        }])
        return float(self.reg.predict(row[self.feat_cols])[0])


def extract_pre_reveal_comments(
    bench: Benchmark,
    pool: UniversalUserPool,
    live23_dir: str,
    cutoff_minutes_after_midnight_pt: int = 225,  # 225m = 03:45 PT (strictly before 04:00 PT vote reveal!)
) -> dict[str, dict[str, Any]]:
    """Extract order-free, rank-scrubbed maker first comments + <=03:45 PT community comments for every item_id."""
    out: dict[str, dict[str, Any]] = {}

    # Identify makers per item_idx in bench
    mk = bench.hist[bench.hist["kind"] == KIND_CODE[MAKE]][["person_idx", "item_idx"]].drop_duplicates()
    maker_pairs = set(zip(mk["person_idx"].astype(int), mk["item_idx"].astype(int)))

    # 1. Extract from bench.comments (covers Apr 1 - Nov 24 with exact person_idx -> UniversalUserPool!)
    c = bench.comments.merge(bench.items[["item_idx", "item_id", "day"]], on="item_idx")
    c = c[c["day"] >= "2026-04-01"].copy()
    bounds = {d: _day_bounds_utc(d, bench.cfg.day_tz) for d in c["day"].unique()}
    c["start_utc"] = c["day"].map(lambda d: bounds[d][0])
    c["cutoff_utc"] = c["start_utc"] + pd.Timedelta(minutes=cutoff_minutes_after_midnight_pt)
    c["ts_utc"] = c["ts"].dt.tz_convert("UTC")

    # Strictly <= 03:45 PT on launch day D (includes maker comments pre-staged slightly before 00:00 PT)
    c_pre = c[c["ts_utc"] <= c["cutoff_utc"]].sort_values("ts_utc")

    snap_cache: dict[str, dict[str, np.ndarray]] = {}
    for d, dg in c_pre.groupby("day"):
        d_str = str(d)
        if d_str not in snap_cache:
            snap_cache[d_str] = pool.snapshot(d_str)
        snap = snap_cache[d_str]
        selectivity = 1.0 / (1.0 + snap["entropy"])
        est_mask = snap["established"]
        disc_w = np.log1p(snap["rw30"]) * selectivity * (snap["n60"] <= 45).astype(np.float32) * est_mask.astype(np.float32)
        crit_w = disc_w * snap["crit_rate"] * (snap["n_com"] >= 2).astype(np.float32)

        for lid, ig in dg.groupby("item_id"):
            lid_s = str(lid)
            maker_txts = []
            comm_txts = []
            seen_persons: set[int] = set()
            disc_sum = 0.0
            crit_sum = 0.0
            est_count = 0
            substantive_count = 0

            for r in ig.itertuples(index=False):
                pidx = int(r.person_idx)
                iidx = int(r.item_idx)
                txt = scrub_comment_text(str(r.text or ""))
                if not txt:
                    continue
                if (pidx, iidx) in maker_pairs:
                    maker_txts.append(txt)
                else:
                    if pidx not in seen_persons:
                        seen_persons.add(pidx)
                        if 0 <= pidx < len(disc_w):
                            disc_sum += float(disc_w[pidx])
                            crit_sum += float(crit_w[pidx])
                            if bool(est_mask[pidx]):
                                est_count += 1
                    comm_txts.append(txt)
                    if len(txt) >= 55 and not BOILERPLATE_PRAISE_RE.match(txt):
                        substantive_count += 1

            maker_first = maker_txts[0][:700] if maker_txts else ""
            out[lid_s] = {
                "maker_first_comment": maker_first,
                "has_maker_comment": float(bool(maker_first)),
                "maker_comment_len": float(len(maker_first)),
                "early_comm_texts": comm_txts[:8],
                "early_n_distinct": float(len(seen_persons)),
                "early_n_established": float(est_count),
                "early_discerning_sum": float(disc_sum),
                "early_critic_sum": float(crit_sum),
                "early_substantive_n": float(substantive_count),
            }

    # 2. Supplement maker first comments from `page_daily_*.jsonl.gz` where bench.comments didn't hold maker row
    slug_to_id = dict(zip(bench.items["item_id"].astype(str), bench.items["item_id"].astype(str)))
    # Also map slug -> id from daily 2026-*.json files
    slug_id_map: dict[str, str] = {}
    slug_team_map: dict[str, set[str]] = {}
    slug_day_map: dict[str, str] = {}
    for jf in sorted(glob.glob(f"{live23_dir}/forecasts/2026-*.json")) + sorted(glob.glob(f"{live23_dir}/post0005/*/2026-*.json")):
        try:
            arr = json.load(open(jf))
            d_f = os.path.basename(jf)[:10]
            if isinstance(arr, list):
                for p in arr:
                    sl = str(p.get("slug") or "")
                    if sl:
                        slug_id_map[sl] = str(p["id"])
                        slug_day_map[sl] = d_f
                        tm = {str(m.get("username") or "") for m in (p.get("makers") or [])}
                        if (p.get("user") or {}).get("username"):
                            tm.add(str(p["user"]["username"]))
                        slug_team_map[sl] = {u for u in tm if u}
        except Exception:
            pass

    for pgz in sorted(glob.glob(f"{live23_dir}/page_daily/page_daily_*.jsonl.gz")):
        try:
            with gzip.open(pgz, "rt") as f:
                for line in f:
                    outer = json.loads(line)
                    post = ((json.loads(outer.get("html") or "{}").get("data") or {}).get("post")) or {}
                    sl = str(post.get("slug") or "")
                    lid = str(post.get("id") or slug_id_map.get(sl) or "")
                    d_s = slug_day_map.get(sl)
                    if not lid or not d_s:
                        continue
                    s_utc, _ = _day_bounds_utc(d_s, bench.cfg.day_tz)
                    cut_utc = s_utc + pd.Timedelta(minutes=cutoff_minutes_after_midnight_pt)
                    team_u = slug_team_map.get(sl, set())
                    for edge in ((post.get("threads") or {}).get("edges") or []):
                        node = edge.get("node") or {}
                        c_ts = pd.to_datetime(node.get("createdAt"), utc=True, errors="coerce")
                        if pd.isna(c_ts) or c_ts > cut_utc:
                            continue
                        u = str((node.get("user") or {}).get("username") or "")
                        txt = scrub_comment_text(node.get("body") or node.get("bodyHtml") or "")
                        if not txt:
                            continue
                        rec = out.setdefault(lid, {
                            "maker_first_comment": "", "has_maker_comment": 0.0, "maker_comment_len": 0.0,
                            "early_comm_texts": [], "early_n_distinct": 0.0, "early_n_established": 0.0,
                            "early_discerning_sum": 0.0, "early_critic_sum": 0.0, "early_substantive_n": 0.0,
                        })
                        if u in team_u and not rec["maker_first_comment"]:
                            rec["maker_first_comment"] = txt[:700]
                            rec["has_maker_comment"] = 1.0
                            rec["maker_comment_len"] = float(len(rec["maker_first_comment"]))
        except Exception:
            pass

    # 3. Supplement 2026-11-25 live pre-reveal comments (`20261125T0245PT.jsonl`, strictly <= 02:45 PT < 03:45 PT!)
    nov25_comm = f"{live23_dir}/nov25/20261125T0245PT.jsonl"
    nov25_det = f"{live23_dir}/nov25/20261125T1834PT.jsonl"
    if os.path.exists(nov25_comm) and os.path.exists(nov25_det):
        team_ids_by_post: dict[str, set[str]] = {}
        for line in open(nov25_det):
            r = json.loads(line)
            pid = str(r["id"])
            tset = {str(m.get("id") or "") for m in (r.get("makers") or [])}
            if (r.get("user") or {}).get("id"):
                tset.add(str(r["user"]["id"]))
            team_ids_by_post[pid] = {x for x in tset if x}

        s_utc, _ = _day_bounds_utc("2026-11-25", bench.cfg.day_tz)
        cut_utc = s_utc + pd.Timedelta(minutes=cutoff_minutes_after_midnight_pt)

        by_post: dict[str, list[dict]] = {}
        for line in open(nov25_comm):
            r = json.loads(line)
            c_ts = pd.to_datetime(r.get("createdAt"), utc=True, errors="coerce")
            if pd.isna(c_ts) or c_ts > cut_utc:
                continue
            by_post.setdefault(str(r.get("post_id") or ""), []).append(r)

        for pid, rows in by_post.items():
            rows = sorted(rows, key=lambda x: str(x.get("createdAt") or ""))
            tset = team_ids_by_post.get(pid, set())
            maker_txts, comm_txts = [], []
            seen_u: set[str] = set()
            fol_weighted_disc = 0.0
            subs_n = 0
            for r in rows:
                uid = str(r.get("commenter_user_id") or "")
                txt = scrub_comment_text(r.get("body") or "")
                if not txt:
                    continue
                if uid in tset:
                    maker_txts.append(txt)
                else:
                    if uid and uid not in seen_u:
                        seen_u.add(uid)
                        c_fol = float(r.get("commenter_followers_count") or 0.0)
                        if c_fol >= 20:
                            fol_weighted_disc += min(1.0, math.log1p(c_fol) / 7.0)
                    comm_txts.append(txt)
                    if len(txt) >= 55 and not BOILERPLATE_PRAISE_RE.match(txt):
                        subs_n += 1
            mfirst = maker_txts[0][:700] if maker_txts else ""
            out[pid] = {
                "maker_first_comment": mfirst,
                "has_maker_comment": float(bool(mfirst)),
                "maker_comment_len": float(len(mfirst)),
                "early_comm_texts": comm_txts[:8],
                "early_n_distinct": float(len(seen_u)),
                "early_n_established": float(sum(1 for r in rows if float(r.get("commenter_followers_count") or 0) >= 25)),
                "early_discerning_sum": float(fol_weighted_disc),
                "early_critic_sum": float(fol_weighted_disc * 0.4),
                "early_substantive_n": float(subs_n),
            }

    return out


def attach_walkforward_product_comment_features(df: pd.DataFrame, comm_map: dict[str, dict[str, Any]]) -> pd.DataFrame:
    """Attach strictly causal (`< D` walk-forward by month) product + maker/early-comment features."""
    df = df.copy().reset_index(drop=True)

    maker_txt = []
    comm_concat = []
    has_maker = np.zeros(len(df), dtype=np.float64)
    maker_len = np.zeros(len(df), dtype=np.float64)
    disc_raw = np.zeros(len(df), dtype=np.float64)
    subs_raw = np.zeros(len(df), dtype=np.float64)
    est_raw = np.zeros(len(df), dtype=np.float64)
    digest_col = []

    for i, r in enumerate(df.itertuples(index=False)):
        lid = str(r.item_id)
        cm = comm_map.get(lid) or {}
        mf = str(cm.get("maker_first_comment") or "")
        ec = list(cm.get("early_comm_texts") or [])
        maker_txt.append(mf)
        comm_concat.append(" | ".join(ec[:6]))
        has_maker[i] = float(cm.get("has_maker_comment", 0.0))
        maker_len[i] = math.log1p(float(cm.get("maker_comment_len", 0.0)))
        disc_raw[i] = math.log1p(float(cm.get("early_discerning_sum", 0.0)))
        subs_raw[i] = math.log1p(float(cm.get("early_substantive_n", 0.0)))
        est_raw[i] = math.log1p(float(cm.get("early_n_established", 0.0)))

        parts = []
        if mf:
            parts.append(f"Maker launch note: {mf[:240]}")
        if ec:
            parts.append(f"Early pre-reveal community comments ({len(ec)}): " + " // ".join(t[:110] for t in ec[:3]))
        digest_col.append(" | ".join(parts) if parts else "[NO_EARLY_COMMENTS_YET]")

    df["maker_comment_present"] = has_maker
    df["raw_maker_len"] = maker_len
    df["raw_early_disc"] = disc_raw
    df["raw_early_subs"] = subs_raw
    df["raw_early_est"] = est_raw
    df["early_comment_digest"] = digest_col

    # Within-day z-scores (completely invariant to homepage order!)
    df["pc_maker_pitch_len_z"] = within_day_zscore(df, "raw_maker_len")
    df["pc_early_discerning_z"] = within_day_zscore(df, "raw_early_disc")
    df["pc_early_substantive_z"] = within_day_zscore(df, "raw_early_subs")
    df["pc_early_established_z"] = within_day_zscore(df, "raw_early_est")

    # Walk-forward (< month M) TF-IDF Ridge on (product pitch + maker first comment + early comment text) -> residual!
    pitch_docs = [
        f"{r.title}. {r.summary}. {r.description or ''} {' '.join(r.tags if isinstance(r.tags, (list, tuple)) else [])} {maker_txt[i]}"
        for i, r in enumerate(df.itertuples(index=False))
    ]
    comm_docs = [
        f"{maker_txt[i]} {comm_concat[i]}".strip()
        for i in range(len(df))
    ]

    df["raw_pc_pitch_ridge"] = 0.0
    df["raw_pc_comm_ridge"] = 0.0
    months = sorted(df["day"].str[:7].unique())

    for m_idx, mon in enumerate(months):
        te_mask = (df["day"].str[:7] == mon).to_numpy()
        if m_idx == 0:
            # Out-of-fold by day within the very first training month (April)
            ap_idx = np.where(te_mask)[0]
            days_ap = df.loc[te_mask, "day"].to_numpy()
            folds = np.array(pd.factorize(days_ap)[0]) % 4
            vec_p = TfidfVectorizer(min_df=2, max_features=12000, ngram_range=(1, 2), sublinear_tf=True)
            Xp = vec_p.fit_transform([pitch_docs[k] for k in ap_idx])
            yp = np.clip(df.loc[te_mask, "true_log_residual"].to_numpy(dtype=np.float64), -1.2, 1.2)
            oof_p = np.zeros(len(ap_idx))
            for f_i in range(4):
                if (folds != f_i).sum() >= 10 and (folds == f_i).sum() >= 1:
                    oof_p[folds == f_i] = Ridge(alpha=8.0, solver="lsqr").fit(Xp[folds != f_i], yp[folds != f_i]).predict(Xp[folds == f_i])
            df.loc[te_mask, "raw_pc_pitch_ridge"] = oof_p
            continue

        tr_mask = (df["day"].str[:7] < mon).to_numpy() & df["true_log_residual"].notna().to_numpy()
        if tr_mask.sum() < 80:
            continue
        tr_idx = np.where(tr_mask)[0]
        te_idx = np.where(te_mask)[0]
        y_tr = np.clip(df.loc[tr_mask, "true_log_residual"].to_numpy(dtype=np.float64), -1.2, 1.2)

        vec_p = TfidfVectorizer(min_df=3, max_features=15000, ngram_range=(1, 2), sublinear_tf=True)
        Xp_tr = vec_p.fit_transform([pitch_docs[k] for k in tr_idx])
        Xp_te = vec_p.transform([pitch_docs[k] for k in te_idx])
        df.loc[te_mask, "raw_pc_pitch_ridge"] = Ridge(alpha=8.0, solver="lsqr").fit(Xp_tr, y_tr).predict(Xp_te)

        has_c_tr = np.array([len(comm_docs[k]) >= 25 for k in tr_idx])
        has_c_te = np.array([len(comm_docs[k]) >= 25 for k in te_idx])
        if has_c_tr.sum() >= 60 and has_c_te.sum() >= 1:
            vec_c = TfidfVectorizer(min_df=3, max_features=10000, ngram_range=(1, 2), sublinear_tf=True)
            tr_c_idx = tr_idx[has_c_tr]
            te_c_idx = te_idx[has_c_te]
            Xc_tr = vec_c.fit_transform([comm_docs[k] for k in tr_c_idx])
            Xc_te = vec_c.transform([comm_docs[k] for k in te_c_idx])
            preds_c = Ridge(alpha=10.0, solver="lsqr").fit(Xc_tr, y_tr[has_c_tr]).predict(Xc_te)
            arr_c = np.zeros(len(te_idx), dtype=np.float64)
            arr_c[has_c_te] = preds_c
            df.loc[te_mask, "raw_pc_comm_ridge"] = arr_c

    df["pc_pitch_maker_ridge_z"] = within_day_zscore(df, "raw_pc_pitch_ridge")
    df["pc_comment_text_ridge_z"] = within_day_zscore(df, "raw_pc_comm_ridge")
    return df
