"""STACK-1 (docs/ledger/experiments.jsonl): BACKER-v2 features + logit P(yes) of the CHOICE-FT-1 500k adapter.

  python -m simharness.finetune.stack1 export --bench B --lineup choice_lineup.parquet --out O
  python -m simharness.finetune.stack1 agg    --bench B --ft1 FT1 --out O --val-scores V.jsonl --test-scores T.jsonl \
                                              --results-dir R

export  O/val_eval.jsonl + O/val_pairs.parquet: validation days (Nov 1-10) with a 00:05 or same-day line-up, the same
        fixed 15% pool sample rule as CHOICE-FT-1's test (seed = day ordinal), for the GPU scorer.
agg     fits a logistic on [ln_rw, tm, ln_rw_x_tm, logit P(yes)] on validation pairs only (standardised, one fit, no
        refit on test), scores the CHOICE-FT-1 test pairs, and compares with BACKER-v2 walk-forward (CHOICE-FT-1's
        primary baseline) and with a BACKER-v2 logistic fit on the same validation pairs: recall@N pooled and
        per-launch AUC, launch bootstrap, paired. Aggregates only into --results-dir.
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np
import pandas as pd

from simharness.bench import Benchmark, day_ord
from simharness.finetune.choice_ft1 import EVAL_FRAC, Histories, _handles, day_matrix, load_scores

NB = 2000
FEATS = ("ln_rw", "tm", "ln_rw_x_tm")


def stage_export(a):
    b = Benchmark(a.bench)
    H = Histories(b)
    lu = pd.read_parquet(a.lineup)
    os.makedirs(a.out, exist_ok=True)
    ev, pairs, days = [], [], []
    for d in b.days("val"):
        items = lu.loc[lu["day"] == d, "item_idx"].to_numpy().astype(np.int64)
        if not len(items):
            continue
        days.append(d)
        pool, Y = day_matrix(b, d, items)
        r = np.random.default_rng(day_ord(d))
        sel = np.sort(r.choice(len(pool), int(round(EVAL_FRAC * len(pool))), replace=False))
        for k in sel:
            p = int(pool[k])
            ev.append({"prefix": H.prefix(p, d), "suffixes": [H.launch(int(i)) for i in items],
                       "meta": {"day": d, "person_idx": p, "items": [int(i) for i in items]}})
            pairs.append(pd.DataFrame({"day": d, "item_idx": items, "person_idx": p, "y": Y[k].astype(np.int8)}))
    with open(f"{a.out}/val_eval.jsonl", "w") as f:
        for r in ev:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    vp = pd.concat(pairs, ignore_index=True)
    vp.to_parquet(f"{a.out}/val_pairs.parquet")
    late = sum(int((H.events(r["meta"]["person_idx"], r["meta"]["day"])[0] >= day_ord(r["meta"]["day"])).sum())
               for r in ev[:3000])
    info = {"val_days": days, "val_person_days": len(ev), "val_pairs": int(len(vp)), "val_positives": int(vp.y.sum()),
            "val_launches": int(vp[["day", "item_idx"]].drop_duplicates().shape[0]),
            "line_up_source": lu[lu["day"].isin(days)].groupby("source")["day"].nunique().to_dict(),
            "history_endorsements_on_or_after_day": late,
            "handles_in_prompts": sum(_handles(t) for r in ev for t in [r["prefix"]] + r["suffixes"])}
    json.dump(info, open(f"{a.out}/val_export_info.json", "w"), indent=1)
    print(json.dumps(info, indent=1))


def feats(b, rows: pd.DataFrame, pyes: np.ndarray) -> np.ndarray:
    from simharness.models.baselines import features
    X = np.zeros((len(rows), len(FEATS)))
    for (d, it), g in rows.groupby(["day", "item_idx"], sort=True):
        X[g.index.to_numpy()] = features(b.batch(d, g["person_idx"].to_numpy()), b.item(it), FEATS)
    p = np.clip(pyes, 1e-6, 1 - 1e-6)
    return np.column_stack([X, np.log(p / (1 - p))])


def stage_agg(a):
    from sklearn.linear_model import LogisticRegression
    from simharness.score import paired_diff, score_rows, summarize
    b = Benchmark(a.bench)
    vp = pd.read_parquet(f"{a.out}/val_pairs.parquet")
    tp = pd.read_parquet(f"{a.ft1}/eval_pairs.parquet")
    Xv = feats(b, vp, load_scores(a.val_scores, vp))
    Xt = feats(b, tp, load_scores(a.test_scores, tp))
    assert np.isfinite(Xv).all() and np.isfinite(Xt).all()
    mu, sd = Xv.mean(0), Xv.std(0) + 1e-9
    fits = {}
    for name, cols in (("stack", [0, 1, 2, 3]), ("backer_v2_valfit", [0, 1, 2]), ("pyes_only", [3])):
        clf = LogisticRegression(max_iter=2000).fit(((Xv - mu) / sd)[:, cols], vp["y"].to_numpy())
        fits[name] = (clf, cols)
    ok = lambda df: df[(df.N > 0) & (df.n > df.N)]  # noqa: E731
    bs = np.load(f"{a.ft1}/baseline_scores.npz")
    per = {"backer_v2_wf": ok(score_rows(tp, bs["backer_v2_wf__eval"]))}
    for name, (clf, cols) in fits.items():
        per[name] = ok(score_rows(tp, clf.predict_proba(((Xt - mu) / sd)[:, cols])[:, 1]))
    res = {"experiment": "STACK-1", "intervals": "launch-clustered bootstrap, 95%, 2,000 draws",
           "fit": {"rows": int(len(vp)), "positives": int(vp.y.sum()), "days": sorted(vp.day.unique().tolist()),
                   "features": list(FEATS) + ["logit_pyes"],
                   "stack_coef_standardised": dict(zip(list(FEATS) + ["logit_pyes"],
                                                       np.round(fits["stack"][0].coef_[0], 4).tolist()))},
           "test": {"pairs": int(len(tp)), "launches_scored": int(len(per["stack"]))}, "models": {}, "paired": {}}
    for k, df in per.items():
        s = summarize(df, n_boot=NB, cluster="item")
        res["models"][k] = {m: s[m] for m in ("recall_at_N_pooled", "auc_mean")}
    for k, ref in (("stack", "backer_v2_wf"), ("stack", "backer_v2_valfit"), ("backer_v2_valfit", "backer_v2_wf"),
                   ("pyes_only", "backer_v2_wf")):
        res["paired"][f"{k} - {ref}"] = {m: paired_diff(per[k], per[ref], m, NB, cluster="item")
                                         for m in ("recall_at_N_pooled", "auc_mean")}
    os.makedirs(a.results_dir, exist_ok=True)
    json.dump(res, open(f"{a.results_dir}/results.json", "w"), indent=1, default=float)
    print(json.dumps({k: {m: (v[m]["value"], v[m]["ci95"]) for m in v} for k, v in res["models"].items()}, indent=0))
    print(json.dumps({k: {m: (v[m]["diff"], v[m]["ci95"]) for m in v} for k, v in res["paired"].items()}, indent=0))
    print(res["fit"]["stack_coef_standardised"])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["export", "agg"])
    ap.add_argument("--bench", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--lineup", default=""); ap.add_argument("--ft1", default="")
    ap.add_argument("--val-scores", default=""); ap.add_argument("--test-scores", default="")
    ap.add_argument("--results-dir", default="")
    a = ap.parse_args(argv)
    globals()[f"stage_{a.stage}"](a)


if __name__ == "__main__":
    main()
