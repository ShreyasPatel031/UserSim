"""Refit the honest backtest without the llm / page sources (same folds, 5 seeds, ctrl.fit), orchestrator 05:20Z Nov 12."""
import os, sys, json
os.environ.setdefault("LGB_THREADS", "1"); os.environ["HONEST"] = "0"
import numpy as np, pandas as pd, multiprocessing as mp
import honest as Hn, model as M, run as RN
from buildcache import build_cached
from ctrl import MONTHS, fit
def variants(cols):
    h = Hn.honest_cols(cols)
    V = {"honest": h}
    for p in ("ph_", "hist_", "x_", "promo_", "busy_"): V["- " + p] = [c for c in h if not c.startswith(p)]
    V["- makers fields"] = [c for c in h if c not in ("ph_n_makers", "ph_n_makers_new", "x_n_makers_with_x", "ph_maker_has_headline", "ph_dayrank_ph_n_makers", "ph_maker_max_age_d", "ph_maker_min_age_d")]
    V["- non-base (fold) cols"] = [c for c in h if c in BASE]
    V["only page + llm"] = [c for c in h if c.startswith(("llm_", "ps_", "pf_", "vs_"))]
    return V
BASE = set()
def job(a):
    m, tr, te, seed = a
    base = set(M.cols(tr, M.LIVE_SOURCES + M.PAGE_SOURCES)); BASE.clear(); BASE.update(base); tr, te = M.add_fold_feats(tr, te); cols = M.cols(tr, M.LIVE_SOURCES + M.PAGE_SOURCES)
    out = {"id": te.id.values}
    for k, c in variants(cols).items(): out[k] = fit(tr, te, c, seed)
    return pd.DataFrame(out)
if __name__ == "__main__":
    print("fold-added cols example:", flush=True)
    df = build_cached(); df = df[~df.known].copy()
    jobs = [(m, tr, te, s) for m, tr, te in RN.folds(df, MONTHS) for s in range(5)]
    with mp.get_context("fork").Pool(os.cpu_count()) as pool: out = pool.map(job, jobs)
    P = pd.concat(out); V = [c for c in P.columns if c != "id"]
    A = P.groupby("id")[V].mean().reset_index().merge(df[["id", "day", "dailyRank"]], on="id"); A = A[A.dailyRank.notna()]
    A.to_parquet("/tmp/refit2_preds.parquet"); print("saved", len(A), A.day.nunique())
