"""STACK-1b: the frozen STACK-1 stack on the full test pool (Nov 11-22, every pool person-day x the 00:05 line-up).

  python -m simharness.finetune.stack1b export --bench B --ft1 FT1 --out O
  python -m simharness.finetune.stack1b agg --bench B --ft1 FT1 --stack1 S1 --out O --scores DIR --results-dir R

export  O/rest_eval.jsonl: the test person-days NOT in CHOICE-FT-1's 15% sample (that sample's 500k scores are reused),
        O/full_pairs.parquet (day, item_idx, person_idx, y) for every pool person-day x line-up launch.
agg     rebuilds the STACK-1 fit from its validation pairs and scores (the same deterministic fit; its coefficients are
        checked against STACK-1's results.json, no test data used), applies it to the full pool, compares with
        BACKER-v2 walk-forward (CHOICE-FT-1's full-pool scores): recall@N pooled and per-launch AUC, launch bootstrap.
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np
import pandas as pd

from simharness.bench import Benchmark
from simharness.finetune.choice_ft1 import Histories, _handles, day_matrix, load_scores
from simharness.finetune.stack1 import feats

NB = 2000


def stage_export(a):
    b = Benchmark(a.bench)
    H = Histories(b)
    ep = pd.read_parquet(f"{a.ft1}/eval_pairs.parquet")
    lu = ep[["day", "item_idx"]].drop_duplicates()
    done = set(zip(ep["day"], ep["person_idx"]))
    os.makedirs(a.out, exist_ok=True)
    pairs, n, hd = [], 0, 0
    with open(f"{a.out}/rest_eval.jsonl", "w") as f:
        for d, g in lu.groupby("day"):
            items = g["item_idx"].to_numpy().astype(np.int64)
            pool, Y = day_matrix(b, d, items)
            for k, p in enumerate(pool):
                p = int(p)
                pairs.append(pd.DataFrame({"day": d, "item_idx": items, "person_idx": p, "y": Y[k].astype(np.int8)}))
                if (d, p) in done:
                    continue
                r = {"prefix": H.prefix(p, d), "suffixes": [H.launch(int(i)) for i in items],
                     "meta": {"day": d, "person_idx": p, "items": [int(i) for i in items]}}
                hd += sum(_handles(t) for t in [r["prefix"]] + r["suffixes"])
                f.write(json.dumps(r, ensure_ascii=False) + "\n"); n += 1
    fp = pd.concat(pairs, ignore_index=True)
    fp.to_parquet(f"{a.out}/full_pairs.parquet")
    info = {"full_person_days": int(fp[["day", "person_idx"]].drop_duplicates().shape[0]), "full_pairs": int(len(fp)),
            "full_positives": int(fp.y.sum()), "rest_person_days_to_score": n, "reused_person_days": len(done),
            "handles_in_prompts": hd}
    json.dump(info, open(f"{a.out}/export_info.json", "w"), indent=1)
    print(json.dumps(info))


def stage_agg(a):
    from sklearn.linear_model import LogisticRegression
    from simharness.score import paired_diff, score_rows, summarize
    b = Benchmark(a.bench)
    vp = pd.read_parquet(f"{a.stack1}/val_pairs.parquet")
    Xv = feats(b, vp, load_scores(f"{a.stack1}/scores_val_eval.jsonl", vp))
    mu, sd = Xv.mean(0), Xv.std(0) + 1e-9
    clf = LogisticRegression(max_iter=2000).fit((Xv - mu) / sd, vp["y"].to_numpy())
    ref = json.load(open(a.stack1_results))["fit"]["stack_coef_standardised"]
    coef = np.round(clf.coef_[0], 4).tolist()
    assert coef == list(ref.values()), (coef, ref)  # the frozen STACK-1 fit, reproduced exactly
    fp = pd.read_parquet(f"{a.out}/full_pairs.parquet")
    # P(yes): CHOICE-FT-1's 15% sample scores + this run's scores for the rest
    key = {(d, int(i), int(p)): k for k, (d, i, p) in enumerate(zip(fp["day"], fp["item_idx"], fp["person_idx"]))}
    py = np.full(len(fp), np.nan)
    for path in (f"{a.scores}/scores_final_500000.jsonl", f"{a.scores}/scores_rest_eval.jsonl"):
        for line in open(path):
            r = json.loads(line)
            m = r["meta"]
            for i, s in zip(m["items"], r["p"]):
                py[key[(m["day"], int(i), int(m["person_idx"]))]] = s
    assert not np.isnan(py).any(), int(np.isnan(py).sum())
    Xt = feats(b, fp, py)
    ok = lambda df: df[(df.N > 0) & (df.n > df.N)]  # noqa: E731
    # BACKER-v2 walk-forward full-pool scores from CHOICE-FT-1 (same rows, same order)
    f1 = pd.read_parquet(f"{a.ft1}/full_pairs.parquet")
    assert (f1[["day", "item_idx", "person_idx", "y"]].to_numpy() == fp[["day", "item_idx", "person_idx", "y"]].to_numpy()).all()
    bs = np.load(f"{a.ft1}/baseline_scores.npz")
    per = {"backer_v2_wf": ok(score_rows(fp, bs["backer_v2_wf__full"])),
           "stack": ok(score_rows(fp, clf.predict_proba((Xt - mu) / sd)[:, 1])),
           "pyes_only": ok(score_rows(fp, py))}
    res = {"experiment": "STACK-1b", "intervals": "launch-clustered bootstrap, 95%, 2,000 draws",
           "full_pool": json.load(open(f"{a.out}/export_info.json")), "stack_coef_standardised": dict(zip(ref, coef)),
           "models": {}, "paired": {}}
    for k, df in per.items():
        s = summarize(df, n_boot=NB, cluster="item")
        res["models"][k] = {m: s[m] for m in ("recall_at_N_pooled", "auc_mean")} | {"launches": s["items"],
                                                                                    "positives": s["positives"]}
    for k in ("stack", "pyes_only"):
        res["paired"][f"{k} - backer_v2_wf"] = {m: paired_diff(per[k], per["backer_v2_wf"], m, NB, cluster="item")
                                                for m in ("recall_at_N_pooled", "auc_mean")}
    if os.path.exists(f"{a.scores}/serving.json"):
        res["serving"] = json.load(open(f"{a.scores}/serving.json"))
    os.makedirs(a.results_dir, exist_ok=True)
    json.dump(res, open(f"{a.results_dir}/results.json", "w"), indent=1, default=float)
    print(json.dumps({k: {m: (v[m]["value"], v[m]["ci95"]) for m in ("recall_at_N_pooled", "auc_mean")}
                      for k, v in res["models"].items()}))
    print(json.dumps({k: {m: (v[m]["diff"], v[m]["ci95"]) for m in v} for k, v in res["paired"].items()}))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["export", "agg"])
    ap.add_argument("--bench", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--ft1", default=""); ap.add_argument("--stack1", default="")
    ap.add_argument("--stack1-results", default="simharness/bench_v0/choice_ft1/stack1/results.json")
    ap.add_argument("--scores", default=""); ap.add_argument("--results-dir", default="")
    a = ap.parse_args(argv)
    globals()[f"stage_{a.stage}"](a)


if __name__ == "__main__":
    main()
