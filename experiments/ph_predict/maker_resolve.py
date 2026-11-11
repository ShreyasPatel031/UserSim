"""Resolve placeholder makers ("[REDACTED]", id "0") to identities, recompute maker history, re-run the honest launch
model month-forward (orchestrator 00:50Z Nov 12). Runs on the pipeline VM (feature cache), read-only for the pipeline.

Identity map (built off the VM, maker_tokens.json, salted ids only, no usernames): per launch, one token per maker slot:
named makers -> salted id of their username; placeholder slots -> salted ids of store_v3 people with a "launched" event on
that launch who are not among the named makers (in order); placeholders left over -> a unique "unk:<launch>:<i>" token
(no history). A maker listed on a launch is known at launch; history uses only earlier days (features.add_history).
Variants (same folds, seeds, LightGBM as E5's ctrl.fit, honest column set as honest.honest_cols):
  i    current features (placeholders share id "0", so they pool every placeholder launch's history)
  ii   placeholder slots as missing (unique unknown tokens: no history); named makers as their salted ids
  iii  resolved identities (ii + store-resolved placeholders)
ctx_ columns derived from hist_maker are precomputed elsewhere and would be stale, so all hist_maker-derived ctx_ columns
are dropped in every variant (listed in the output).
usage (VM, from ph_predict): PYTHONPATH=~/w/mk python3 maker_resolve.py ~/w/mk/maker_tokens.json -> results/maker_resolve_preds.parquet"""
import json, multiprocessing as mp, os, sys
os.environ.setdefault("LGB_THREADS", "1")
import numpy as np, pandas as pd
import features as F, model as M, run as RN
from buildcache import build_cached
from ctrl import MONTHS, fit
from honest import honest_cols

HIST = ["hist_maker_n", "hist_maker_rel_max", "hist_maker_top5"]


def rehist(df, toks):
    base = df[["id", "day", "votes", "dailyRank", "hunter_id", "maker_ids"]].copy()
    base["maker_ids"] = [toks.get(str(i), m) for i, m in zip(base.id, base.maker_ids)]
    H = F.add_history(base)[["id"] + HIST]
    out = df.drop(columns=HIST).merge(H, on="id", how="left")
    for c in [c for c in out.columns if c.startswith("hist_dayrank_hist_maker")]:
        src = c[len("hist_dayrank_"):]
        out[c] = out.groupby("day")[src].rank(pct=True)
    return out


DF = {}


def job(a):
    v, m, seed = a
    df = DF[v]
    tr, te = df[df.mon < m], df[df.mon == m]
    tr, te = M.add_fold_feats(tr, te)
    cols = [c for c in honest_cols(M.cols(tr, M.LIVE_SOURCES + M.PAGE_SOURCES)) if not (c.startswith("ctx_") and "hist_maker" in c)]
    return pd.DataFrame({"id": te.id.values, "seed": seed, "variant": v, "pred": fit(tr, te, cols, seed)})


def main(tokfile):
    T = json.load(open(tokfile))
    df = build_cached(); df = df[~df.known].copy(); df["id"] = df.id.astype(str)
    if "mon" not in df:
        df["mon"] = df.day.str[:7]
    full = {i: v["tokens"] for i, v in T.items()}
    miss = {i: [t if not t.startswith("p_") or k < len(v["tokens"]) - v["n_ph"] else f"unk:{i}:{k}" for k, t in enumerate(v["tokens"])] for i, v in T.items()}
    DF["i"] = df
    DF["ii"] = rehist(df, miss)
    DF["iii"] = rehist(df, full)
    ph = {i for i, v in T.items() if v["n_ph"] > 0}; res = {i for i, v in T.items() if v["n_res"] > 0}
    jobs = [(v, m, s) for v in ("i", "ii", "iii") for m in MONTHS for s in range(5) if len(df[df.mon < m]) > 200 and len(df[df.mon == m])]
    with mp.get_context("fork").Pool(int(os.environ.get("PROCS", "3"))) as pool:
        P = pd.concat(pool.map(job, jobs))
    A = P.groupby(["id", "variant"]).pred.mean().unstack().reset_index()
    A = A.merge(df[["id", "day", "dailyRank", "logv"]], on="id")
    A["placeholder"] = A.id.isin(ph); A["resolved"] = A.id.isin(res)
    for v in ("i", "ii", "iii"):
        A[f"hm_n_{v}"] = A.id.map(DF[v].set_index("id").hist_maker_n)
    A.to_parquet("results/maker_resolve_preds.parquet")
    print(json.dumps({"launches": int(len(A)), "days": int(A.day.nunique()), "placeholder": int(A.placeholder.sum()), "resolved": int(A.resolved.sum()),
                      "dropped_ctx": sorted({c for c in df.columns if c.startswith("ctx_") and "hist_maker" in c})}))


if __name__ == "__main__":
    main(sys.argv[1])
