"""TIES-1 on Benchmark v0, Task V: is the person's tie to the team the missing signal once activity is matched?

Stages (private files go to --out and, with --sync gs://prefix, are copied there after each stage):

  data     team / backing / follow tables from the domain adapter (Product Hunt)
  hard     tie features on the round-1 HARD rows; logistic models fit on VAL-HARD, scored once on HARD
  full     full-pool ranking on every test launch: round-1 logistic vs logistic + dated ties (fit on validation)
  agg      results.json + table.md (aggregates only) into --results-dir

  python -m simharness.run_ties STAGE --bench BENCH --round1 ROUND1_OUT --out OUT [--sync gs://...]

Dated tie features use only launches and events before the item's day and the item's team as listed at the start
of its day. Follow edges are undated snapshots: every line that uses them is an upper bound that can leak.
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import subprocess

import numpy as np
import pandas as pd

LOGI = ("ln_rw", "tm", "ln_rw_x_tm")


def sync(paths, dest):
    if dest and paths:
        subprocess.run(["gsutil", "-q", "-m", "cp", *paths, dest.rstrip("/") + "/"], check=False)


def load_bench(a):
    from simharness.bench import Benchmark
    return Benchmark(a.bench)


def load_td(a, b):
    from simharness.ties import TieData, load_tables
    return TieData(b.n_people, len(b.items), load_tables(f"{a.out}/tables"))


# ------------------------------------------------------------------------------------------------ data
def stage_data(a):
    from simharness.domains.producthunt import build_tie_tables
    from simharness.ties import save_tables
    b = load_bench(a)
    t = build_tie_tables(b, a.store, a.items_v2, a.daily, b.days("val") + b.days("test"))
    cov = t["coverage"]
    # which target launches have a team, by split
    have = set(t["target_team"]["item_idx"].unique().tolist())
    for split in ("val", "test"):
        its = [int(i) for d in b.days(split) for i in b.items_on(d)]
        cov[f"{split}_launches"] = len(its)
        cov[f"{split}_launches_with_team"] = int(sum(i in have for i in its))
    files = save_tables(t, f"{a.out}/tables")
    print(json.dumps(cov, indent=1))
    sync(files, f"{a.sync.rstrip('/')}/tables" if a.sync else "")


# ------------------------------------------------------------------------------------------------ hard
def _fit_eval(Xv, yv, Xt):
    from sklearn.linear_model import LogisticRegression
    mu, sd = Xv.mean(0), Xv.std(0) + 1e-9
    clf = LogisticRegression(max_iter=2000, C=1.0).fit((Xv - mu) / sd, yv)
    return clf.predict_proba((Xt - mu) / sd)[:, 1], (clf.coef_[0] / sd)


def stage_hard(a):
    from simharness.models.baselines import features as logi_features
    from simharness.score import _logit, paired_diff, score_rows, summarize
    from simharness.ties import DATED, UNDATED, featurize_rows
    b = load_bench(a)
    td = load_td(a, b)
    rows, X, base = {}, {}, {}
    for split in ("val", "test"):
        r = pd.read_parquet(f"{a.round1}/preds_nonllm_hard_{split}.parquet")  # rows + round-1 model scores
        rows[split] = r
        ties = featurize_rows(td, r, DATED + UNDATED)
        lf = np.zeros((len(r), len(LOGI)), np.float32)
        for (d, it), g in r.groupby(["day", "item_idx"], sort=True):
            lf[g.index.to_numpy()] = logi_features(b.batch(d, g["person_idx"].to_numpy()), b.item(it), LOGI)
        X[split] = {"dated": ties[:, :len(DATED)], "undated": ties[:, len(DATED):], "logi": lf,
                    "taste": _logit(r["taste-v1"].to_numpy())[:, None]}
        base[split] = {"logistic": r["logistic"].to_numpy(), "taste-v1": r["taste-v1"].to_numpy()}
        np.save(f"{a.out}/ties_X_hard_{split}.npy", ties)
        r[["day", "item_idx", "person_idx", "y"]].assign(
            **{k: ties[:, i] for i, k in enumerate(DATED + UNDATED)}).to_parquet(f"{a.out}/ties_rows_hard_{split}.parquet")
    yv, yt = rows["val"].y.to_numpy(), rows["test"].y.to_numpy()
    sets = {"dated ties": ["dated"], "dated ties + logistic features": ["dated", "logi"],
            "dated ties + taste-v1": ["dated", "taste"],
            "dated ties + logistic features + taste-v1": ["dated", "logi", "taste"],
            "follow ties only (undated, upper bound)": ["undated"],
            "dated + follow ties (upper bound)": ["dated", "undated"],
            "dated + follow ties + logistic features (upper bound)": ["dated", "undated", "logi"],
            "dated + follow ties + taste-v1 (upper bound)": ["dated", "undated", "taste"]}
    NB = 2000
    per = {k: score_rows(rows["test"], v) for k, v in base["test"].items()}
    res = {"models": {}, "coef": {}}
    for k, df in per.items():
        s = summarize(df, pooled_auc=True, n_boot=NB, cluster="day")
        res["models"][f"round-1 {k}"] = {"HARD_auc_pooled": s["auc_pooled"], "HARD_auc_mean_per_launch": s["auc_mean"]}
    preds = rows["test"][["day", "item_idx", "person_idx", "y"]].copy()
    for name, parts in sets.items():
        cols = [n for p in parts for n in {"dated": DATED, "undated": UNDATED, "logi": LOGI, "taste": ("taste_logit",)}[p]]
        p, coef = _fit_eval(np.hstack([X["val"][q] for q in parts]), yv, np.hstack([X["test"][q] for q in parts]))
        preds[name] = p
        df = score_rows(rows["test"], p)
        s = summarize(df, pooled_auc=True, n_boot=NB, cluster="day")
        res["models"][name] = {
            "HARD_auc_pooled": s["auc_pooled"], "HARD_auc_mean_per_launch": s["auc_mean"],
            "vs_logistic": paired_diff(df, per["logistic"], "auc_pooled", NB, pooled_auc=True, cluster="day"),
            "vs_taste-v1": paired_diff(df, per["taste-v1"], "auc_pooled", NB, pooled_auc=True, cluster="day"),
            "vs_logistic_mean_per_launch": paired_diff(df, per["logistic"], "auc_mean", NB, cluster="day"),
            "vs_taste-v1_mean_per_launch": paired_diff(df, per["taste-v1"], "auc_mean", NB, cluster="day")}
        res["coef"][name] = dict(zip(cols, np.round(coef, 3).tolist()))
        print(name, json.dumps({k: v for k, v in res["models"][name].items() if k.startswith("HARD") or k.startswith("vs_l")}),
              flush=True)
    # how many rows have a tie at all
    shares = {}
    for split in ("val", "test"):
        D_, U_ = X[split]["dated"], X[split]["undated"]
        y = rows[split].y.to_numpy()
        g = lambda M, n: M[:, n]  # noqa: E731
        di, ui = {k: i for i, k in enumerate(DATED)}, {k: i for i, k in enumerate(UNDATED)}
        flags = {"on the team": g(D_, di["self_team"]) > 0,
                 "backed an earlier launch of the team": g(D_, di["back_any"]) > 0,
                 "team member backed the person's earlier launch": g(D_, di["recip_any"]) > 0,
                 "shares an earlier upvote with a held team member": g(D_, di["co_n"]) > 0,
                 "follows a team member (undated)": g(U_, ui["fol_p2t_any"]) > 0,
                 "followed by a team member (undated)": g(U_, ui["fol_t2p_any"]) > 0}
        flags["any dated tie (team / backed / reciprocal)"] = (flags["on the team"] | flags["backed an earlier launch of the team"]
                                                               | flags["team member backed the person's earlier launch"])
        flags["any follow tie (undated)"] = flags["follows a team member (undated)"] | flags["followed by a team member (undated)"]
        shares[split] = {k: {"voters": round(float(f[y == 1].mean()), 4), "matched_non_voters": round(float(f[y == 0].mean()), 4),
                             "n_voters_with": int(f[y == 1].sum()), "n_non_voters_with": int(f[y == 0].sum())}
                         for k, f in flags.items()}
        have = np.array([int(i) in td.target for i in rows[split].item_idx.to_numpy()])
        shares[split]["rows_on_launches_with_a_known_team"] = round(float(have.mean()), 4)
    res["tie_shares_on_HARD"] = shares
    # precision view on test: among rows with the tie, share that are voters (matched 1:1, so 0.5 = no signal)
    json.dump(res, open(f"{a.out}/ties_hard_results.json", "w"), indent=1, default=float)
    preds.to_parquet(f"{a.out}/ties_preds_hard_test.parquet")
    print(json.dumps(shares["test"], indent=1))
    sync([f"{a.out}/ties_hard_results.json", f"{a.out}/ties_preds_hard_test.parquet",
          f"{a.out}/ties_rows_hard_val.parquet", f"{a.out}/ties_rows_hard_test.parquet"], a.sync)


# ------------------------------------------------------------------------------------------------ full
def stage_full(a):
    """Full pool: logit(walk-forward logistic) + dated ties, weights fit on a weighted validation pool sample."""
    from sklearn.linear_model import LogisticRegression
    from simharness.models.baselines import backer_logistic
    from simharness.score import _logit, paired_diff, predict_rows, score_item, summarize
    from simharness.ties import DATED, UNDATED, featurize_rows
    b = load_bench(a)
    td = load_td(a, b)
    lg = backer_logistic()
    vs = b.training_sample(b.days("val"), k=50, seed=5)
    pl = predict_rows(lg, b, vs)
    T = featurize_rows(td, vs, DATED + UNDATED)
    variants = {"logistic + dated ties": list(range(len(DATED))),
                "logistic + dated + follow ties (upper bound)": list(range(len(DATED) + len(UNDATED)))}
    fits = {}
    for name, ix in variants.items():
        Xv = np.column_stack([_logit(pl), T[:, ix]])
        mu, sd = Xv.mean(0), Xv.std(0) + 1e-9
        fits[name] = (LogisticRegression(max_iter=2000).fit((Xv - mu) / sd, vs.y.to_numpy(),
                                                           sample_weight=vs.w.to_numpy()), mu, sd, ix)
    full = {k: [] for k in ["logistic"] + list(variants)}
    names = DATED + UNDATED
    for d in b.days("test"):
        pool = b.pool(d)
        hb = b.batch(d, pool)
        lg.prepare(b, d)
        for it in b.items_on(d):
            y = np.isin(pool, b.positives(d, it)).astype(np.int8)
            if y.sum() == 0:
                continue
            p0 = lg.score(hb, b.item(it))
            full["logistic"].append({"day": d, "item_idx": int(it), **score_item(p0, y)})
            Tt = td.features(d, int(it), pool, names)
            for name, (clf, mu, sd, ix) in fits.items():
                X = np.column_stack([_logit(p0), Tt[:, ix]])
                full[name].append({"day": d, "item_idx": int(it), **score_item(clf.predict_proba((X - mu) / sd)[:, 1], y)})
        print("full", d, flush=True)
    per = {k: pd.DataFrame(v) for k, v in full.items()}
    res = {}
    for k, df in per.items():
        s = summarize(df, n_boot=2000)
        res[k] = {"recall_at_N_pooled": s["recall_at_N_pooled"], "recall_at_N_mean": s["recall_at_N_mean"],
                  "auc_mean": s["auc_mean"], "items": s["items"], "positives": s["positives"]}
        if k != "logistic":
            res[k]["recall_diff_vs_logistic"] = paired_diff(df, per["logistic"], "recall_at_N_pooled", 2000)
            clf, mu, sd, ix = fits[k]
            res[k]["coef"] = dict(zip(["logit_logistic"] + [names[i] for i in ix], np.round(clf.coef_[0] / sd, 3).tolist()))
        print(k, json.dumps(res[k]), flush=True)
    pickle.dump(per, open(f"{a.out}/ties_full_test.pkl", "wb"))
    json.dump(res, open(f"{a.out}/ties_full_results.json", "w"), indent=1, default=float)
    sync([f"{a.out}/ties_full_test.pkl", f"{a.out}/ties_full_results.json"], a.sync)


# ------------------------------------------------------------------------------------------------ agg
def _f(d):
    return f"{d['value']:.3f} [{d['ci95'][0]:.3f}, {d['ci95'][1]:.3f}]"


def _fd(d):
    return f"{d['diff']:+.3f} [{d['ci95'][0]:+.3f}, {d['ci95'][1]:+.3f}]"


def stage_agg(a):
    res = {"task": "Benchmark v0 Task V, TIES-1", "intervals": "day-clustered bootstrap 95%",
           "coverage": json.load(open(f"{a.out}/tables/coverage.json")),
           "hard": json.load(open(f"{a.out}/ties_hard_results.json"))}
    if os.path.exists(f"{a.out}/ties_full_results.json"):
        res["full"] = json.load(open(f"{a.out}/ties_full_results.json"))
    if os.path.exists(f"{a.out}/ties_leak_checks.json"):
        res["leak_checks"] = json.load(open(f"{a.out}/ties_leak_checks.json"))
    L = ["| Model (fit on VAL-HARD, scored once on HARD, 50,100 rows) | HARD AUC | mean per-launch AUC | vs round-1 logistic "
         "| vs taste-v1 |", "|---|---|---|---|---|"]
    for k, e in res["hard"]["models"].items():
        L.append(f"| {k} | {_f(e['HARD_auc_pooled'])} | {_f(e['HARD_auc_mean_per_launch'])} "
                 f"| {_fd(e['vs_logistic']) if 'vs_logistic' in e else ''} | {_fd(e['vs_taste-v1']) if 'vs_taste-v1' in e else ''} |")
    L += ["", "| Tie (HARD test rows) | voters with it | matched non-voters with it |", "|---|---|---|"]
    for k, e in res["hard"]["tie_shares_on_HARD"]["test"].items():
        if isinstance(e, dict):
            L.append(f"| {k} | {e['voters'] * 100:.2f}% ({e['n_voters_with']}) | {e['matched_non_voters'] * 100:.2f}% ({e['n_non_voters_with']}) |")
    if "full" in res:
        L += ["", "| Full pool, all test launches | recall@N | vs logistic |", "|---|---|---|"]
        for k, e in res["full"].items():
            v = e["recall_at_N_pooled"]
            d = e.get("recall_diff_vs_logistic")
            L.append(f"| {k} | {v['value'] * 100:.1f} [{v['ci95'][0] * 100:.1f}, {v['ci95'][1] * 100:.1f}] "
                     f"| {'%+.1f [%+.1f, %+.1f]' % (d['diff'] * 100, d['ci95'][0] * 100, d['ci95'][1] * 100) if d else ''} |")
    os.makedirs(a.results_dir, exist_ok=True)
    json.dump(res, open(f"{a.results_dir}/results.json", "w"), indent=1, default=float)
    open(f"{a.results_dir}/table.md", "w").write("\n".join(L) + "\n")
    print("\n".join(L))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["data", "hard", "full", "agg"])
    ap.add_argument("--bench", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--round1", default="")
    ap.add_argument("--sync", default="")
    ap.add_argument("--store", default="")
    ap.add_argument("--items-v2", default="")
    ap.add_argument("--daily", default="")
    ap.add_argument("--results-dir", default="")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    globals()[f"stage_{a.stage}"](a)


if __name__ == "__main__":
    main()
