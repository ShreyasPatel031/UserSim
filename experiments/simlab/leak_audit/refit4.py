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
    named = lambda c: (c.startswith(("hist_maker", "hist_dayrank_hist_maker")) or c in {"x_n_makers_with_x", "ph_n_makers_new", "ph_maker_has_headline", "ph_self_hunted", "llm_full"}
                       or ("ph_maker" in c and "age" in c))
    m = [c for c in h if not named(c)]
    V["masked 00:05"] = m
    V["masked - first-comment fields"] = [c for c in m if c not in {"ps_has_first_comment", "ps_first_comment", "pf_first_comment_words", "pf_emoji_in_first_comment", "pf_founder_story", "pf_asks_for_feedback", "pf_asks_for_upvotes"}]
    V["masked - ps,pf"] = [c for c in m if not c.startswith(("ps_", "pf_"))]
    V["masked - all page"] = [c for c in m if not c.startswith(("ps_", "pf_", "vs_", "llm_"))]
    return V
BASE = set()
def job(a):
    m, tr, te, seed = a
    base = set(M.cols(tr, M.LIVE_SOURCES + M.PAGE_SOURCES)); BASE.clear(); BASE.update(base); tr, te = M.add_fold_feats(tr, te); cols = M.cols(tr, M.LIVE_SOURCES + M.PAGE_SOURCES)
    out = {"id": te.id.values}
    for k, c in variants(cols).items(): out[k] = fit(tr, te, c, seed)
    return pd.DataFrame(out)
if __name__ == "__main__":
    print("ok", flush=True)
    df = build_cached(); df = df[~df.known].copy()
    jobs = [(m, tr, te, s) for m, tr, te in RN.folds(df, MONTHS) for s in range(5)]
    with mp.get_context("fork").Pool(os.cpu_count()) as pool: out = pool.map(job, jobs)
    P = pd.concat(out); V = [c for c in P.columns if c != "id"]
    A = P.groupby("id")[V].mean().reset_index().merge(df[["id", "day", "dailyRank"]], on="id"); A = A[A.dailyRank.notna()]
    A.to_parquet("/tmp/refit4_preds.parquet"); print("saved", len(A), A.day.nunique())
