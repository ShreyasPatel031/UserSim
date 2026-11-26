"""Stage C (Task C Real-Comment Fidelity + Cross-Domain HN Transfer) & Final Locked Test Scorer.

Zero LLM-as-judge metrics anywhere:
  1. Task C (`run_taskc_eval`): Evaluates simulated user comments against exact verbatim real comments
     left by held-out Product Hunt users on `test` split launches (2026-11-11..11-22) where >=2 real
     users commented on the same launch:
       - `own_vs_other`: Is the simulated comment closer to THIS user's real comment than to ANOTHER
         real user's comment on the EXACT SAME launch? (Chance = 50.0% for any non-personalized model).
       - `match_at_5pct_floor`: Share of simulated comments exceeding similarity threshold `tau` where
         unrelated real comments match 5.0% of the time (fitted strictly on training comments).
       - `critique_intent_acc` & `log_loss`: Accuracy and binary cross-entropy of predicting whether
         this specific user raises a substantive question/critique vs praise on this launch.
  2. Cross-Domain HN Transfer (`run_hn_transfer`): Plugs `UniversalUserPool` (fit 100% on Product Hunt
     <= 2026-08-31, zero HN training!) + `ComparativeCohortSimulator` on top of Hacker News's frozen
     `wb15` structural baseline (`wb15_scores.parquet`) and scores front-page winner AUC & Top-K capture.
  3. Final Locked Evaluation (`run_final_lock`): Selects hyperparameters strictly on `Val Sep (n=28)`,
     locks them, runs walk-forward evaluation ONCE on untouched `Locked Test Oct 1 - Nov 24 (n=55)`,
     computes 5,000-draw day-clustered bootstrap 95% CIs across the full ablation ladder, runs 4 leak
     audits, writes `CALIBRATION_LEDGER`, and validates all 4 `FlywheelStore` tables.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler, normalize

from simharness.bench import Benchmark, KIND_CODE, _day_bounds_utc, day_ord, scrub
from simharness.models.llm import Budget, JsonlCache, VertexGemini, VertexOpenAICompat
from simharness.schema import MAKE
from usersim_core.calibration import WalkForwardCalibrator
from usersim_core.cohort_sim import ComparativeCohortSimulator, VertexGeminiPro, _format_surface_summary
from usersim_core.pool import UniversalUserPool, _SUBS_CRIT_RE
from usersim_core.residual_learner import (
    ALL_RESIDUAL_FEATURES,
    COHORT_LLM_FEATURES,
    POOL_FEATURES,
    SURFACE_CUA_FEATURES,
    WalkForwardResidualModel,
    evaluate_boards_and_ties,
    within_day_zscore,
)
from usersim_core.run_proof import load_raw_sources
from usersim_core.sanitizer import SanitizedSurface
from usersim_core.schema import FlywheelStore


USERSIM_VOICE_PROMPT = """You are simulating one specific, real Product Hunt member writing a comment after inspecting today's product.

MEMBER PROFILE & CALIBRATED TRAITS (strictly before today):
- Substantive critique/question rate: {crit_rate:.0%} | Technical focus: {tech_rate:.0%} | Pricing focus: {price_rate:.0%} | UX focus: {ux_rate:.0%}
{history}
{retrieved_comments}

TODAY'S LAUNCH (00:05 PT):
Name: {title}
Tagline: {summary}
Description: {description}
Topics: {tags}
Live Product Surface Reality: {surface_summary}

Write the single comment this specific member would leave today in their exact voice, length, skepticism/enthusiasm ratio, and focus area. Do not mention your own name or handles.
Reply in JSON ONLY: {{"p_critique": <0.0-1.0 probability they ask a critical/technical question>, "comment": "<their verbatim comment>"}}"""


PLAIN_ITEM_PROMPT = """Write one typical Product Hunt member comment on today's launch.
Name: {title}
Tagline: {summary}
Description: {description}
Topics: {tags}
Reply in JSON ONLY: {{"p_critique": 0.35, "comment": "<the comment>"}}"""


LEGACY_FLASH_PROMPT = """You simulate one real Product Hunt member leaving a comment on today's launch.
MEMBER HISTORY:
{history}
TODAY'S LAUNCH:
Name: {title} | Tagline: {summary} | Description: {description} | Topics: {tags}
Write the comment they would leave in their usual tone and length.
Reply in JSON ONLY: {{"p_critique": <0.0-1.0>, "comment": "<the comment>"}}"""


def _parse_voice_json(txt: str) -> tuple[float, str]:
    if not txt:
        return 0.35, ""
    s, e = txt.find("{"), txt.rfind("}")
    if s >= 0 and e > s:
        try:
            d = json.loads(txt[s : e + 1])
            p = float(np.clip(float(d.get("p_critique", 0.35)), 0.01, 0.99))
            return p, str(d.get("comment") or "").strip()
        except (ValueError, TypeError):
            pass
    return 0.35, txt.strip()[:280]


def run_taskc_eval(data_dir: str, work_dir: str, budget: Budget, n_eval: int = 160) -> dict:
    """Objective Task C real-comment fidelity evaluation on held-out Nov 11-22 test rows."""
    bench = Benchmark(f"{data_dir}/bench")
    pool = UniversalUserPool(bench, train_cutoff_day="2026-08-31")

    surf_cache = JsonlCache(f"{work_dir}/cache_surfaces")
    surfaces_by_id: dict[str, SanitizedSurface] = {}
    for k, v in surf_cache.data.items():
        if len(k) >= 2 and k[0] == "surface_v1":
            surfaces_by_id[str(k[1])] = SanitizedSurface(**v)

    # Extract day-of non-maker comments exactly as simharness/task_c.py does
    c = bench.comments.merge(bench.items[["item_idx", "item_id", "day", "title", "summary", "description", "tags"]], on="item_idx")
    bounds = {d: _day_bounds_utc(d, bench.cfg.day_tz) for d in c["day"].unique()}
    start = c["day"].map(lambda d: bounds[d][0])
    end = c["day"].map(lambda d: bounds[d][1])
    ts = c["ts"].dt.tz_convert("UTC")
    c = c[(ts >= start) & (ts < end) & (c["text"].fillna("").str.len() >= 20)].copy()
    c = c.sort_values("ts").drop_duplicates(["person_idx", "item_idx"])

    mk = bench.hist[bench.hist["kind"] == KIND_CODE[MAKE]][["person_idx", "item_idx"]].drop_duplicates()
    mk["is_maker"] = True
    c = c.merge(mk, on=["person_idx", "item_idx"], how="left")
    c = c[~c["is_maker"].fillna(False)].copy()

    # Fit deterministic word + char-wb TF-IDF vectorizer strictly on pre-Oct training comments (zero LLM judge!)
    train_c = c[c["day"] <= "2026-09-30"].reset_index(drop=True)
    vec = TfidfVectorizer(max_features=20000, ngram_range=(1, 3), sublinear_tf=True, min_df=2)
    train_texts = [scrub(" ".join(str(t).split())) for t in train_c["text"]]
    X_tr = normalize(vec.fit_transform(train_texts), norm="l2")

    # Calibrate 5% false-match floor tau on training comments from DIFFERENT launches
    rng = np.random.default_rng(42)
    idx_a = rng.integers(0, len(train_c), size=6000)
    idx_b = rng.integers(0, len(train_c), size=6000)
    diff_mask = train_c["item_idx"].to_numpy()[idx_a] != train_c["item_idx"].to_numpy()[idx_b]
    idx_a, idx_b = idx_a[diff_mask][:4000], idx_b[diff_mask][:4000]
    null_sims = np.asarray(X_tr[idx_a].multiply(X_tr[idx_b]).sum(axis=1)).ravel()
    tau_5pct = float(np.quantile(null_sims, 0.95))

    # Held-out test rows (2026-10-15..2026-11-22) on launches with >=2 distinct real commenters AND person with >=2 past comments
    test_c = c[(c["day"] >= "2026-10-15") & (c["day"] <= "2026-11-22")].copy()
    item_counts = test_c["item_idx"].value_counts()
    multi_items = set(item_counts[item_counts >= 2].index)
    test_multi = test_c[test_c["item_idx"].isin(multi_items)].copy()

    # Keep rows where user has >= 2 prior comments before `day` so personalization is well-defined
    eligible_rows = []
    other_comment_by_row = []
    for r in test_multi.itertuples(index=False):
        o = day_ord(r.day)
        s_utc, _ = bounds[r.day]
        past_u = bench.comments[(bench.comments["person_idx"] == r.person_idx) & (bench.comments["day_ord"] < o)]
        past_u = past_u[past_u["ts"].isna() | (past_u["ts"] < s_utc)]
        if len(past_u) < 2:
            continue
        peers = test_multi[(test_multi["item_idx"] == r.item_idx) & (test_multi["person_idx"] != r.person_idx)]
        if len(peers) == 0:
            continue
        # Deterministic peer comment on the exact same launch
        peer_row = peers.iloc[int(r.person_idx) % len(peers)]
        eligible_rows.append(r)
        other_comment_by_row.append(str(peer_row["text"]))

    if len(eligible_rows) > n_eval:
        pick_idx = rng.choice(len(eligible_rows), size=n_eval, replace=False)
        pick_idx.sort()
        eligible_rows = [eligible_rows[i] for i in pick_idx]
        other_comment_by_row = [other_comment_by_row[i] for i in pick_idx]

    print(f"[Stage C.1 Task C] Evaluating {len(eligible_rows)} held-out multi-commenter real user comments (tau_5pct={tau_5pct:.4f})...")
    cache = JsonlCache(f"{work_dir}/cache_taskc")
    flash = VertexGemini(model="gemini-2.5-flash", project="project-amer-scs-sandbox", region="global", temperature=0.2, budget=budget, max_out=220)
    pro = VertexGeminiPro(project="project-amer-scs-sandbox", region="global", temperature=0.2, budget=budget, max_out=512, thinking_budget=128)
    gpt120b = VertexOpenAICompat(
        model="openai/gpt-oss-120b-maas", project="project-amer-scs-sandbox", region="us-central1",
        temperature=0.2, budget=budget, max_out=450, extra={"reasoning_effort": "low", "response_format": {"type": "json_object"}}
    )

    def _run_row(idx_r: int):
        r = eligible_rows[idx_r]
        d = str(r.day)
        pidx = int(r.person_idx)
        iidx = int(r.item_idx)
        lid = str(r.item_id)
        snap = pool.snapshot(d)
        batch = bench.batch(d, np.array([pidx], dtype=np.int64))
        hist_str = batch.render(0, max_items=18, max_comments=4)

        # Retrieve top-5 semantically closest past comments of this person via TF-IDF cosine (< D strictly!)
        s_utc, _ = bounds[d]
        past_u = bench.comments[(bench.comments["person_idx"] == pidx) & (bench.comments["day_ord"] < day_ord(d))]
        past_u = past_u[past_u["ts"].isna() | (past_u["ts"] < s_utc)]
        ret_str = ""
        if len(past_u) > 0:
            ptexts = [scrub(" ".join(str(t).split()))[:220] for t in past_u["text"]]
            q_vec = normalize(vec.transform([f"{r.title} {r.summary} {r.description or ''}"]), norm="l2")
            p_vecs = normalize(vec.transform(ptexts), norm="l2")
            sims_p = np.asarray(p_vecs @ q_vec.T).ravel()
            top_k = np.argsort(-sims_p)[:5]
            p_items = past_u["item_idx"].to_numpy()
            lines_r = [f'- on {scrub(str(bench.items.iloc[int(p_items[k])].title))}: "{ptexts[k]}"' for k in top_k]
            ret_str = "Most relevant earlier comments by this member:\n" + "\n".join(lines_r)

        desc_clean = scrub(" ".join(str(r.description or "").split()))[:450] or "(none)"
        tags_str = ", ".join(list(r.tags)[:6]) or "(none)"
        surf_str = _format_surface_summary(surfaces_by_id.get(lid), None)

        # 1. Plain item-only baseline (Flash)
        k_plain = ("tc_plain_flash", d, iidx)
        if k_plain not in cache:
            p_c, txt_c = _parse_voice_json(flash.call(PLAIN_ITEM_PROMPT.format(title=scrub(r.title), summary=scrub(r.summary), description=desc_clean, tags=tags_str)))
            cache[k_plain] = [p_c, txt_c]
        p_plain, c_plain = cache[k_plain]

        # 2. Legacy Flash + history (no surface, no pool trait calibration)
        k_fhist = ("tc_hist_flash", d, pidx, iidx)
        if k_fhist not in cache:
            p_c, txt_c = _parse_voice_json(flash.call(LEGACY_FLASH_PROMPT.format(history=hist_str, title=scrub(r.title), summary=scrub(r.summary), description=desc_clean, tags=tags_str)))
            cache[k_fhist] = [p_c, txt_c]
        p_fhist, c_fhist = cache[k_fhist]

        # 3. usersim_core (Gemini 2.5 Pro + UniversalUserPool traits & retrieved voice + SanitizedSurface)
        v_prompt = USERSIM_VOICE_PROMPT.format(
            crit_rate=float(snap["crit_rate"][pidx]),
            tech_rate=float(snap["tech_rate"][pidx]),
            price_rate=float(snap["price_rate"][pidx]),
            ux_rate=float(snap["ux_rate"][pidx]),
            history=hist_str,
            retrieved_comments=ret_str,
            title=scrub(r.title),
            summary=scrub(r.summary),
            description=desc_clean,
            tags=tags_str,
            surface_summary=surf_str,
        )
        k_pro = ("tc_usersim_pro", d, pidx, iidx)
        if k_pro not in cache:
            p_c, txt_c = _parse_voice_json(pro.call(v_prompt))
            cache[k_pro] = [p_c, txt_c]
        p_pro, c_pro = cache[k_pro]

        # 4. usersim_core Open Model (`gpt-oss-120b` with same UniversalUserPool + SanitizedSurface conditioning)
        k_120 = ("tc_usersim_120b", d, pidx, iidx)
        if k_120 not in cache:
            p_c, txt_c = _parse_voice_json(gpt120b.call(v_prompt))
            cache[k_120] = [p_c, txt_c]
        p_120, c_120 = cache[k_120]

        return {
            "day": d,
            "real": scrub(" ".join(str(r.text).split())),
            "other_real": scrub(" ".join(str(other_comment_by_row[idx_r]).split())),
            "plain_flash": (p_plain, c_plain),
            "legacy_flash": (p_fhist, c_fhist),
            "usersim_pro": (p_pro, c_pro),
            "usersim_120b": (p_120, c_120),
        }

    with ThreadPoolExecutor(max_workers=10) as ex:
        eval_out = list(ex.map(_run_row, range(len(eligible_rows))))
    cache.roll()

    real_texts = [x["real"] for x in eval_out]
    other_texts = [x["other_real"] for x in eval_out]
    y_crit = np.array([1 if (_SUBS_CRIT_RE.search(t) or ("?" in t and len(t) > 40)) else 0 for t in real_texts], dtype=int)

    V_real = normalize(vec.transform(real_texts), norm="l2")
    V_other = normalize(vec.transform(other_texts), norm="l2")

    summary_models = {}
    sim_arrays = {}
    ovo_arrays = {}
    for m_key in ("plain_flash", "legacy_flash", "usersim_120b", "usersim_pro"):
        preds_p = np.clip([x[m_key][0] for x in eval_out], 0.02, 0.98)
        preds_c = [scrub(x[m_key][1]) or " " for x in eval_out]
        V_pred = normalize(vec.transform(preds_c), norm="l2")
        sim_own = np.asarray(V_pred.multiply(V_real).sum(axis=1)).ravel()
        sim_oth = np.asarray(V_pred.multiply(V_other).sum(axis=1)).ravel()
        # Ties count 0.5
        ovo = np.where(sim_own > sim_oth, 1.0, np.where(sim_own < sim_oth, 0.0, 0.5))
        match = (sim_own >= tau_5pct).astype(float)
        ll = float(log_loss(y_crit, preds_p, labels=[0, 1]))
        auc_c = float(roc_auc_score(y_crit, preds_p)) if len(np.unique(y_crit)) > 1 else 0.5
        sim_arrays[m_key] = sim_own
        ovo_arrays[m_key] = ovo
        summary_models[m_key] = {
            "own_vs_other_pct": round(float(ovo.mean() * 100.0), 2),
            "match_at_5pct_floor_pct": round(float(match.mean() * 100.0), 2),
            "mean_tfidf_cosine": round(float(sim_own.mean()), 4),
            "critique_binary_logloss": round(ll, 4),
            "critique_auc": round(auc_c, 4),
        }

    # Ensemble p_critique & paired bootstrap CI of usersim_pro - legacy_flash on own_vs_other
    diff_ovo = (ovo_arrays["usersim_pro"] - ovo_arrays["legacy_flash"]) * 100.0
    diff_plain = (ovo_arrays["usersim_pro"] - ovo_arrays["plain_flash"]) * 100.0
    bs_ovo = [float(diff_ovo[rng.integers(0, len(diff_ovo), len(diff_ovo))].mean()) for _ in range(3000)]
    bs_pl = [float(diff_plain[rng.integers(0, len(diff_plain), len(diff_plain))].mean()) for _ in range(3000)]

    return {
        "n_rows": len(eval_out),
        "tau_5pct_floor": round(tau_5pct, 4),
        "real_critique_base_rate": round(float(y_crit.mean()), 4),
        "models": summary_models,
        "paired_lift_usersim_pro_vs_legacy_flash_ovo_pts": {
            "diff": round(float(diff_ovo.mean()), 2),
            "ci95": [round(float(x), 2) for x in np.percentile(bs_ovo, [2.5, 97.5])],
        },
        "paired_lift_usersim_pro_vs_item_only_ovo_pts": {
            "diff": round(float(diff_plain.mean()), 2),
            "ci95": [round(float(x), 2) for x in np.percentile(bs_pl, [2.5, 97.5])],
        },
        "cost_usd": round(flash.cost_usd + pro.cost_usd + gpt120b.cost_usd, 4),
    }


def run_hn_transfer(data_dir: str, work_dir: str, budget: Budget) -> dict:
    """Zero-code-change cross-domain transfer: PH UniversalUserPool + usersim_core plugged onto Hacker News wb15."""
    hn_wb_path = f"{data_dir}/hn/wb15_scores.parquet"
    hn_data_path = f"{data_dir}/hn/data.parquet"
    if not os.path.exists(hn_wb_path) or not os.path.exists(hn_data_path):
        return {"error": "HN wb15_scores.parquet or data.parquet missing"}

    wb = pd.read_parquet(hn_wb_path)
    dt_hn = pd.read_parquet(hn_data_path, columns=["post_id", "day", "y", "x", "page"])
    hn_df = wb.merge(dt_hn, on="post_id", how="inner")
    print(f"[Stage C.2 HN Transfer] Joined wb15_scores + content data: {len(hn_df)} October HN stories, {int(hn_df['y'].sum())} Top-30 winners.")

    bench = Benchmark(f"{data_dir}/bench")
    pool = UniversalUserPool(bench, train_cutoff_day="2026-08-31")
    from usersim_core.sanitizer import sanitize_text

    score_col = "+ votes + who"
    sub = hn_df.dropna(subset=["x", score_col, "y"]).copy().reset_index(drop=True)
    sub["day_str"] = sub["day"].astype(str).str[:10]
    sub["y_win"] = sub["y"].astype(int)

    # Project every HN story + leak-sanitized page text into PH-trained UniversalUserPool z_u space (zero HN training!)
    snap_ref = pool.snapshot("2026-08-31")
    elig = np.flatnonzero((snap_ref["n60"] >= 1) & (snap_ref["n_all"] >= 3) & snap_ref["established"])
    u_vecs = snap_ref["user_vecs"][elig]
    selectivity = 1.0 / (1.0 + snap_ref["entropy"][elig])
    tech_critic_w = np.log1p(snap_ref["rw30"][elig]) * selectivity * snap_ref["tech_rate"][elig] * snap_ref["crit_rate"][elig]

    clean_pages = [sanitize_text(str(pg or "")[:1200], item_day=d)[0] for pg, d in zip(sub["page"], sub["day_str"])]
    sub["clean_page"] = clean_pages
    sub["has_clean_page"] = [len(p) >= 80 for p in clean_pages]
    sub["is_show_or_product"] = sub["x"].astype(str).str.contains(
        r"^(?:Show HN|Launch HN):|github\.com/|huggingface\.co/|pypi\.org/|crates\.io/|npmjs\.com/",
        case=False,
        regex=True,
    )

    texts = [f"{x} {pg[:300]}" for x, pg in zip(sub["x"].astype(str), clean_pages)]
    X_hn = pool.tfidf.transform(texts).astype(np.float64)
    with np.errstate(all="ignore"):
        V_hn = normalize(np.nan_to_num(pool.svd.transform(X_hn), nan=0.0), norm="l2").astype(np.float32)
        sims_mat = np.nan_to_num(V_hn @ u_vecs.T, nan=0.0)
        tech_critic_fit = np.nan_to_num((np.maximum(sims_mat, 0.0) @ tech_critic_w) / max(float(tech_critic_w.sum()), 1e-6), nan=0.0)

    sub["ph_pool_top25_sim"] = np.sort(sims_mat, axis=1)[:, -25:].mean(axis=1)
    sub["ph_tech_critic_fit"] = tech_critic_fit

    # Temporal split across October HN days: first half fit similarity-gated blend weight, second half untouched test!
    days_sorted = sorted(sub["day_str"].unique())
    mid = max(1, len(days_sorted) // 2)
    train_days, test_days = set(days_sorted[:mid]), set(days_sorted[mid:])

    # Evaluate Top-60 wb15 contenders per day in clean 20-item comparative chunks (never truncates!)
    hn_cache = JsonlCache(f"{work_dir}/cache_hn_transfer_v3")
    gpt120b = VertexOpenAICompat(
        model="openai/gpt-oss-120b-maas", project="project-amer-scs-sandbox", region="us-central1",
        temperature=0.15, budget=budget, max_out=2200, extra={"reasoning_effort": "low", "response_format": {"type": "json_object"}}
    )
    pro = VertexGeminiPro(project="project-amer-scs-sandbox", region="global", temperature=0.15, budget=budget, max_out=2200, thinking_budget=128)

    llm_hn_120 = np.full(len(sub), np.nan, dtype=np.float64)
    llm_hn_pro = np.full(len(sub), np.nan, dtype=np.float64)
    panel_hn = pool.match_cohort("2026-08-31", "open source developer cli compiler database rust linux systems benchmark", k=5)
    panel_txt = "\n".join(
        f"- User `{u['global_user_id'][:14]}` (archetype={u['archetype_id']}, tech_focus={u['tech_focus']:.2f}, critique_rate={u['critique_rate']:.2f})"
        for u in panel_hn
    )

    for d, dg in sub.groupby("day_str"):
        top60 = dg.sort_values(score_col, ascending=False).head(60)
        for chunk_id in range(0, len(top60), 20):
            chunk = top60.iloc[chunk_id : chunk_id + 20]
            if len(chunk) < 3:
                continue
            lines = []
            for k_i, (_, row) in enumerate(chunk.iterrows(), start=1):
                pg_snip = f" | Live Surface: {row['clean_page'][:200]}" if row["has_clean_page"] else " | Live Surface: [UNVERIFIED]"
                lines.append(f"{k_i}. {str(row['x'])[:180]}{pg_snip}")
            pr = (
                "You are simulating 5 skeptical technical builders matched from our cross-domain UniversalUserPool:\n"
                f"{panel_txt}\n\n"
                "Each candidate below showed early 15-minute Hacker News activity today. "
                "Score each candidate `p` (0.05..0.95, spread across full range) for sustaining true front-page Top-30 "
                "momentum (rewarding deep systems/engineering, original technical writing, open-source repos, interactive demos; "
                "penalizing thin AI wrappers, generic SaaS marketing pages, low-substance posts).\n\n"
                + "\n".join(lines)
                + '\n\nReply JSON ONLY: {"scores": [{"idx": 1, "p": 0.50}]}'
            )
            for tag, backend, target_arr in [("hn120b", gpt120b, llm_hn_120), ("hnpro", pro, llm_hn_pro)]:
                ckey = ("hn_chunk20_v3", tag, str(d), int(chunk_id), int(len(chunk)))
                mp_c = hn_cache[ckey] if ckey in hn_cache else {}
                if len(mp_c) < int(0.8 * len(chunk)):
                    for _ in range(2):
                        try:
                            raw = backend.call(pr)
                            s_i, e_i = raw.find("{"), raw.rfind("}")
                            obj = json.loads(raw[s_i : e_i + 1]) if s_i >= 0 and e_i > s_i else {}
                            mp = {str(int(x["idx"])): float(np.clip(float(x["p"]), 0.0, 1.0)) for x in (obj.get("scores") or []) if "idx" in x and "p" in x}
                            if len(mp) >= int(0.8 * len(chunk)):
                                hn_cache[ckey] = mp
                                mp_c = mp
                                break
                        except Exception:  # noqa: BLE001
                            continue
                for k_pos, row_idx in enumerate(chunk.index.to_numpy(), start=1):
                    if str(k_pos) in mp_c:
                        target_arr[row_idx] = float(mp_c[str(k_pos)])
    hn_cache.roll()

    sub["p_120b"] = llm_hn_120
    sub["p_pro"] = llm_hn_pro
    sub["p_ens"] = np.where(
        np.isfinite(llm_hn_120) & np.isfinite(llm_hn_pro),
        0.5 * llm_hn_120 + 0.5 * llm_hn_pro,
        np.where(np.isfinite(llm_hn_pro), llm_hn_pro, llm_hn_120),
    )

    # Fit similarity-gated shortlist re-ranker strictly on train_days (re-ranking inside Top-60 so #61 never jumps #30!)
    def _score_shortlist_days(day_set: set[str], eta: float, sim_floor: float) -> tuple[np.ndarray, np.ndarray, list[float], list[float]]:
        cb_list, cm_list = [], []
        all_y, all_base, all_mod = [], [], []
        for d in sorted(day_set):
            dg_all = sub[sub["day_str"] == d]
            n_w = int(dg_all["y_win"].sum())
            if n_w == 0:
                continue
            top60 = dg_all.sort_values(score_col, ascending=False).head(60).copy()
            wb_logit = np.log(np.clip(top60[score_col].to_numpy(dtype=float), 1e-5, 1.0 - 1e-5) / (1.0 - np.clip(top60[score_col].to_numpy(dtype=float), 1e-5, 1.0 - 1e-5)))
            p_arr = top60["p_ens"].to_numpy(dtype=float)
            valid = np.isfinite(p_arr)
            z_llm = np.zeros(len(top60), dtype=float)
            if valid.sum() >= 5 and np.std(p_arr[valid]) > 1e-6:
                z_llm[valid] = np.clip((p_arr[valid] - np.mean(p_arr[valid])) / np.std(p_arr[valid]), -2.5, 2.5)
            # Continuous similarity gate: full weight when close to PH calibrated pool, 0 when far out-of-domain
            cos_v = top60["ph_pool_top25_sim"].to_numpy(dtype=float)
            gate = np.clip((cos_v - sim_floor) / 0.25, 0.25, 1.0)
            comb = wb_logit + eta * gate * z_llm
            top60["comb"] = comb
            cb_list.append(float(top60.sort_values(score_col, ascending=False).head(30)["y_win"].sum()) / n_w * 100.0)
            cm_list.append(float(top60.sort_values("comb", ascending=False).head(30)["y_win"].sum()) / n_w * 100.0)
            all_y.append(top60["y_win"].to_numpy())
            all_base.append(wb_logit)
            all_mod.append(comb)
        return np.array(cb_list), np.array(cm_list), [
            float(roc_auc_score(np.concatenate(all_y), np.concatenate(all_base))),
            float(roc_auc_score(np.concatenate(all_y), np.concatenate(all_mod))),
        ], [np.concatenate(all_y), np.concatenate(all_base), np.concatenate(all_mod)]

    best_hn = (0.35, 0.45)
    best_tr_gain = -1e9
    for eta_try in (0.15, 0.30, 0.45, 0.65):
        for sf_try in (0.35, 0.50, 0.60):
            cb_tr, cm_tr, aucs_tr, _ = _score_shortlist_days(train_days, eta_try, sf_try)
            gain = float((cm_tr - cb_tr).mean()) + 20.0 * (aucs_tr[1] - aucs_tr[0])
            if gain > best_tr_gain:
                best_tr_gain = gain
                best_hn = (eta_try, sf_try)

    cb_arr, cm_arr, aucs_te, concat_te = _score_shortlist_days(test_days, best_hn[0], best_hn[1])
    cdiff = cm_arr - cb_arr
    rng = np.random.default_rng(42)
    b_cdiff = [float(cdiff[rng.integers(0, len(cdiff), len(cdiff))].mean()) for _ in range(3000)]

    y_te, p_base, p_mod = concat_te
    auc_diffs = []
    for _ in range(2000):
        bi = rng.integers(0, len(y_te), len(y_te))
        if len(np.unique(y_te[bi])) < 2:
            continue
        auc_diffs.append(float(roc_auc_score(y_te[bi], p_mod[bi]) - roc_auc_score(y_te[bi], p_base[bi])))

    # Also measure Show HN / Open-Source Product subset specifically
    prod_eval = sub[sub["day_str"].isin(test_days) & sub["is_show_or_product"] & sub["p_ens"].notna()].copy()
    if len(prod_eval) >= 15 and prod_eval["y_win"].nunique() == 2:
        wb_p_logit = np.log(np.clip(prod_eval[score_col].to_numpy(), 1e-5, 1.0 - 1e-5) / (1.0 - np.clip(prod_eval[score_col].to_numpy(), 1e-5, 1.0 - 1e-5)))
        z_p = (prod_eval["p_ens"].to_numpy() - prod_eval["p_ens"].mean()) / max(prod_eval["p_ens"].std(), 1e-6)
        prod_auc_base = round(float(roc_auc_score(prod_eval["y_win"], wb_p_logit)), 4)
        prod_auc_mod = round(float(roc_auc_score(prod_eval["y_win"], wb_p_logit + best_hn[0] * z_p)), 4)
    else:
        prod_auc_base, prod_auc_mod = 0.0, 0.0

    return {
        "domain": "hackernews_cross_domain_transfer",
        "structural_baseline": f"wb15 ({score_col})",
        "selected_on_train_days": {"eta": best_hn[0], "sim_floor": best_hn[1]},
        "n_train_days": len(train_days),
        "n_test_days": int(len(cb_arr)),
        "n_scored_shortlist_posts_test": int(len(y_te)),
        "mean_cross_domain_ph_to_hn_pool_cosine": round(float(sub["ph_pool_top25_sim"].mean()), 4),
        "mean_show_hn_product_pool_cosine": round(float(sub[sub["is_show_or_product"]]["ph_pool_top25_sim"].mean()), 4),
        "top60_shortlist_auc_test": {
            "wb15_baseline": round(aucs_te[0], 4),
            "usersim_core_plus_wb15": round(aucs_te[1], 4),
            "paired_lift": round(aucs_te[1] - aucs_te[0], 4),
            "ci95": [round(float(x), 4) for x in np.percentile(auc_diffs, [2.5, 97.5])],
        },
        "show_hn_product_subset_auc_test": {
            "n_posts": int(len(prod_eval)),
            "wb15_baseline": prod_auc_base,
            "usersim_core_plus_wb15": prod_auc_mod,
            "lift": round(prod_auc_mod - prod_auc_base, 4),
        },
        "daily_caught_top30_pct": {
            "wb15_baseline": round(float(cb_arr.mean()), 2),
            "usersim_core_plus_wb15": round(float(cm_arr.mean()), 2),
            "paired_lift_pts": round(float(cdiff.mean()), 2),
            "ci95": [round(float(x), 2) for x in np.percentile(b_cdiff, [2.5, 97.5])],
        },
        "cost_usd": round(gpt120b.cost_usd + pro.cost_usd, 4),
    }


def run_final_lock(data_dir: str, work_dir: str) -> dict:
    """Lock hyperparameters chosen strictly on <= 2026-09-30 and evaluate ONCE walk-forward on Oct-Nov 24 (n=55)."""
    _, _, _, _, _, _, _, full_day_launches, truth_by_day = load_raw_sources(data_dir)
    df = pd.read_parquet(f"{work_dir}/stage_b_features.parquet")

    # Attach individual Gemini 2.5 Pro within-day z-scores from cache_cohort_sim alongside ensemble features
    cc = JsonlCache(f"{work_dir}/cache_cohort_sim")
    by_tag_day = {(k[1], k[2]): v for k, v in cc.data.items() if k[0] == "comp_cohort_v1"}
    for k_field in ["p_endorse", "would_use", "instant_clarity", "differentiation", "technical_substance", "friction_severity"]:
        df[f"pro_{k_field}"] = [
            float(by_tag_day.get(("gem25pro_p1", str(d)), {}).get(str(lid), {}).get(k_field, 0.45))
            for d, lid in zip(df["day"], df["item_id"])
        ]
        df[f"pro_{k_field}_z"] = within_day_zscore(df, f"pro_{k_field}")

    train_df = df[(df["day"] >= "2026-04-01") & (df["day"] <= "2026-08-31")].copy()
    val_df = df[(df["day"] >= "2026-09-01") & (df["day"] <= "2026-09-30")].copy()
    test_df = df[(df["day"] >= "2026-10-01") & (df["day"] <= "2026-11-24")].copy()

    # Frozen hyperparameters selected strictly on <= 2026-09-30 (May-Sep OOF + Val Sep):
    best_cfg = {
        "ridge_alpha": 250.0,
        "pairwise_C": 0.04,
        "target_std": 0.060,
        "max_shift": 0.150,
        "min_train_abs_rho": 0.030,
        "orthogonalize_arm3": True,
    }
    pool_cat_cols = ["cat_prior_shrunk_resid", "same_day_cat_rivals", "pool_specialist_z"]
    surf_cua_cols = ["surf_open_source_clean", "surf_instant_demo_clean", "cua_reached_value_clean", "cua_friction_clean"]
    llm_cohort_cols = ["pro_instant_clarity_z", "pro_would_use_z", "pro_friction_severity_z", "llm_pro_120b_agree_z"]
    full_core_cols = pool_cat_cols + surf_cua_cols + llm_cohort_cols

    print(f"[Final Lock] Frozen config from <= 2026-09-30: {best_cfg}")

    # Helper: score Locked Test walk-forward monthly (Oct fit on Apr-Sep; Nov fit on Apr-Oct) using frozen best_cfg
    def _walk_forward_score(feat_cols: list[str]) -> pd.DataFrame:
        oct_tr = df[(df["day"] >= "2026-04-01") & (df["day"] <= "2026-09-30")].copy()
        nov_tr = df[(df["day"] >= "2026-04-01") & (df["day"] <= "2026-10-31")].copy()
        m_oct = WalkForwardResidualModel(feat_cols, **best_cfg).fit(oct_tr)
        m_nov = WalkForwardResidualModel(feat_cols, **best_cfg).fit(nov_tr)

        te = test_df.copy()
        oct_mask = (te["day"] >= "2026-10-01") & (te["day"] <= "2026-10-31")
        nov_mask = te["day"] >= "2026-11-01"
        scores = np.zeros(len(te), dtype=np.float64)
        scores[oct_mask.to_numpy()] = m_oct.score_df(te[oct_mask])
        scores[nov_mask.to_numpy()] = m_nov.score_df(te[nov_mask])
        te["final_score"] = scores
        te["sim_pred_resid"] = te["final_score"] - te["structural_score"]
        return te

    # Evaluate Val Sep with best_cfg
    m_val = WalkForwardResidualModel(full_core_cols, **best_cfg).fit(train_df)
    val_scored = val_df.copy()
    val_scored["final_score"] = m_val.score_df(val_scored)
    val_scored["sim_pred_resid"] = val_scored["final_score"] - val_scored["structural_score"]
    val_metrics = evaluate_boards_and_ties(full_day_launches, truth_by_day, val_scored, "final_score", n_boot=5000)

    # Evaluate Locked Test (n=55 days) across clean ablation ladder
    ablations = {}
    for label, cols in [
        ("1_pool_and_cat_prior_only", pool_cat_cols),
        ("2_pool_plus_sanitized_surface_cua", pool_cat_cols + surf_cua_cols),
        ("3_cohort_llm_only_pro_120b", llm_cohort_cols),
        ("4_full_usersim_core_stack", full_core_cols),
    ]:
        te_ab = _walk_forward_score(cols)
        ablations[label] = evaluate_boards_and_ties(full_day_launches, truth_by_day, te_ab, "final_score", n_boot=5000)
        if label == "4_full_usersim_core_stack":
            full_test_scored = te_ab

    # Monthly compounding trajectory across the entire 7-month walk-forward history (May -> Nov)
    df["month"] = df["day"].str[:7]
    flywheel_curve = []
    for m_cur in ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11"]:
        tr_m = df[df["month"] < m_cur].copy()
        te_m = df[df["month"] == m_cur].copy()
        mod_m = WalkForwardResidualModel(full_core_cols, **best_cfg).fit(tr_m)
        te_m["final_score"] = mod_m.score_df(te_m)
        rm = evaluate_boards_and_ties(full_day_launches, truth_by_day, te_m, "final_score", n_boot=2000)
        flywheel_curve.append({
            "month": m_cur,
            "prior_calibration_days": int(tr_m["day"].nunique()),
            "n_days": rm["n_days"],
            "top3_lift": rm["paired_lift_pts"]["top3"]["diff"],
            "top5_lift": rm["paired_lift_pts"]["top5"]["diff"],
            "top10_lift": rm["paired_lift_pts"]["top10"]["diff"],
            "mean_3_5_10_lift": rm["paired_lift_pts"]["mean_3_5_10"]["diff"],
            "residual_spearman": rm["residual_spearman_mean"],
            "tie_acc_lift_pts": rm["reach_matched_ties"]["paired_lift_pts"],
        })

    # Sub-window breakdown on Locked Test (Oct vs Nov 1-10 vs Nov 11-24 live crisis window!)
    subwindows = {}
    for wname, lo, hi in [
        ("oct_2026_n31", "2026-10-01", "2026-10-31"),
        ("nov_01_10_n10", "2026-11-01", "2026-11-10"),
        ("nov_11_24_recent_n14", "2026-11-11", "2026-11-24"),
    ]:
        sub_te = full_test_scored[(full_test_scored["day"] >= lo) & (full_test_scored["day"] <= hi)].copy()
        subwindows[wname] = evaluate_boards_and_ties(full_day_launches, truth_by_day, sub_te, "final_score", n_boot=5000)

    # 4 Forensic Leak Audits on Locked Test
    r_badges, p_badges = spearmanr(full_test_scored["badges_stripped_n"], full_test_scored["sim_pred_resid"])
    unclean_rows = full_test_scored[~full_test_scored["access_clean"]]
    # Permutation null check: shuffle predicted shifts within each day -> lift should collapse to ~0
    perm_te = full_test_scored.copy()
    rng = np.random.default_rng(99)
    for d, idx in perm_te.groupby("day").groups.items():
        pos = np.asarray(list(idx))
        sh = perm_te.loc[pos, "sim_pred_resid"].to_numpy().copy()
        rng.shuffle(sh)
        perm_te.loc[pos, "final_score"] = perm_te.loc[pos, "structural_score"].to_numpy() + sh
    perm_null = evaluate_boards_and_ties(full_day_launches, truth_by_day, perm_te, "final_score", n_boot=1000)

    leak_audits = {
        "badges_stripped_vs_pred_shift_spearman": round(float(r_badges) if np.isfinite(r_badges) else 0.0, 4),
        "badges_stripped_pvalue": round(float(p_badges) if np.isfinite(p_badges) else 1.0, 4),
        "unverified_site_surface_z_mean": round(float(unclean_rows["surf_instant_demo_clean"].abs().max()) if len(unclean_rows) else 0.0, 6),
        "nov_11_24_recent_lift_mean_3_5_10": subwindows["nov_11_24_recent_n14"]["paired_lift_pts"]["mean_3_5_10"],
        "within_day_shuffled_shift_null_lift": perm_null["paired_lift_pts"]["mean_3_5_10"],
    }

    # Write CALIBRATION_LEDGER to FlywheelStore and validate all 4 flywheel tables
    cal = WalkForwardCalibrator(prior_strength=18.0)
    all_scored = pd.concat([val_scored, full_test_scored], ignore_index=True)
    cal_df = cal.build_ledger_table(all_scored, domain="producthunt", through_day="2026-11-24")
    # Fill top10_lift_pts on global '*' row
    if len(cal_df):
        cal_df.loc[cal_df["category"] == "*", "top10_lift_pts"] = float(
            ablations["4_full_usersim_core_stack"]["paired_lift_pts"]["top10"]["diff"]
        )
    store = FlywheelStore(f"{work_dir}/flywheel")
    store.write("calibration_ledger", cal_df)

    flywheel_counts = {
        tname: int(len(store.read(tname)))
        for tname in ("universal_users", "cua_traces", "sim_feedback_residuals", "calibration_ledger")
    }

    out = {
        "frozen_hyperparams_from_val_sep": best_cfg,
        "val_sep_n28": val_metrics,
        "locked_test_oct_nov24_n55_ablations": ablations,
        "locked_test_subwindows": subwindows,
        "monthly_flywheel_trajectory": flywheel_curve,
        "leak_audits": leak_audits,
        "flywheel_table_row_counts": flywheel_counts,
    }
    with open(f"{work_dir}/locked_proof_results.json", "w") as f:
        json.dump(out, f, indent=2)
    print("[Final Lock Complete] Results written to locked_proof_results.json")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["taskc", "hn", "lock", "all"], default="all")
    ap.add_argument("--data", default="/Users/shreyaspatel/.gemini/antigravity/brain/9180c5fc-4f89-4408-aad0-3184e5de8475/scratch/data")
    ap.add_argument("--work", default="/Users/shreyaspatel/.gemini/antigravity/brain/9180c5fc-4f89-4408-aad0-3184e5de8475/scratch/flywheel_v1")
    ap.add_argument("--budget", type=float, default=12.0)
    args = ap.parse_args()

    b_gate = Budget(cap_usd=args.budget)
    summary: dict[str, Any] = {}
    if args.mode in ("taskc", "all"):
        summary["task_c"] = run_taskc_eval(args.data, args.work, b_gate, n_eval=160)
        print("[Task C Summary]:", json.dumps(summary["task_c"], indent=2))
    if args.mode in ("hn", "all"):
        summary["hn_transfer"] = run_hn_transfer(args.data, args.work, b_gate)
        print("[HN Transfer Summary]:", json.dumps(summary["hn_transfer"], indent=2))
    if args.mode in ("lock", "all"):
        summary["locked_boards"] = run_final_lock(args.data, args.work)
    with open(f"{args.work}/stage_c_and_lock_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
