"""Round 1 on Benchmark v0, Task V: does anything beat the per-person logistic once activity is controlled for?

Stages (each writes its files to --out and, with --sync gs://prefix, copies them there so a restart loses one stage):

  sets     HARD rows (activity-matched, test / validation / a train sample), the shared prompt-model subsamples
  leak     leak checks on the built rows, features and prompts
  taste    item embeddings, taste-v1 variants, choice on validation
  nonllm   most-active, logistic, taste-v1 on every set + full-pool ranking + the logistic+taste stack
  llm      one prompt model on the shared subsample (--models a,b --split test|val --cap USD); every call cached
  agg      results.json + README.md table (aggregates only) into --results-dir

  PYTHONPATH=src:. GOOGLE_CLOUD_PROJECT=... python -m simharness.run_round1 STAGE --bench BENCH --out OUT [...]

All files under --out are private (they carry person indexes and model outputs); only `agg` output is aggregate.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import pickle
import re
import subprocess
import time

import numpy as np
import pandas as pd

SEEDS = {"hard_test": 11, "hard_val": 12, "sub_test": 101, "sub_val": 102, "train_rows": 1}
SCHEMA_NOTE = ("HARD activity-matched Task V rows. Columns: day (launch day, ISO), item_idx (row of bench_v0 "
               "data/items.parquet), person_idx (row of data/people.parquet; salted ids live only there), y (1 = the "
               "person upvoted the launch; 0 = a non-voter of that launch from the same day pool, matched 1:1 on the "
               "nearest rw30 = recency-weighted upvotes in the 30 days before the day, 7-day half-life). "
               "hard_test: every test launch Nov 11-22; hard_val: Nov 1-10; hard_train_sample: train days <= Oct 31, "
               "up to 60 voters per launch + their matches (neg_kind pos / hard). llm_sub_*: the fixed subsample "
               "every prompt model scores (12 voters + 12 matches per launch; 40 test launches, 20 validation).")


def sync(paths, dest):
    if dest and paths:
        subprocess.run(["gsutil", "-q", "-m", "cp", *paths, dest.rstrip("/") + "/"], check=False)


def load_bench(a):
    from simharness.bench import Benchmark
    return Benchmark(a.bench)


def subsample(hard: pd.DataFrame, n_items: int, per: int, seed: int) -> pd.DataFrame:
    """n_items launches spread over the days (round-robin), `per` voters + `per` matched non-voters each."""
    rng = np.random.default_rng(seed)
    g = hard.groupby(["day", "item_idx"]).y.agg(["sum", "size"]).reset_index()
    g = g[(g["sum"] >= per) & (g["size"] - g["sum"] >= per)]
    days = sorted(g.day.unique())
    picks = []
    q = [rng.permutation(g[g.day == d].item_idx.to_numpy()).tolist() for d in days]
    while len(picks) < n_items:
        for d, lst in zip(days, q):
            if lst and len(picks) < n_items:
                picks.append((d, lst.pop()))
    rows = []
    for d, it in sorted(picks):
        x = hard[(hard.day == d) & (hard.item_idx == it)]
        rows.append(pd.concat([x[x.y == 1].sample(per, random_state=int(rng.integers(1e9))),
                               x[x.y == 0].sample(per, random_state=int(rng.integers(1e9)))]))
    return pd.concat(rows, ignore_index=True)


# ------------------------------------------------------------------------------------------------ sets
def stage_sets(a):
    from simharness.features import build_hard_set
    from simharness.models.taste import training_rows
    b = load_bench(a)
    out, info = [], {}
    for split in ("test", "val"):
        h = build_hard_set(b, b.days(split), seed=SEEDS[f"hard_{split}"])
        f = f"{a.out}/hard_{split}.parquet"
        h.to_parquet(f); out.append(f)
        st = {d: b.state(d) for d in h.day.unique()}
        rw = np.array([st[d]["rw30"][p] for d, p in zip(h.day, h.person_idx)])
        n60 = np.array([st[d]["n60"][p] for d, p in zip(h.day, h.person_idx)])
        info[f"hard_{split}"] = {"rows": len(h), "voters": int(h.y.sum()), "launches": int(h.item_idx.nunique()),
                                 "days": int(h.day.nunique()),
                                 "rw30_mean_voters": round(float(rw[h.y == 1].mean()), 3),
                                 "rw30_mean_matched": round(float(rw[h.y == 0].mean()), 3),
                                 "n60_mean_voters": round(float(n60[h.y == 1].mean()), 1),
                                 "n60_mean_matched": round(float(n60[h.y == 0].mean()), 1)}
        s = subsample(h, 40 if split == "test" else 20, 12, SEEDS[f"sub_{split}"])
        f = f"{a.out}/llm_sub_{split}.parquet"
        s.to_parquet(f); out.append(f)
        info[f"llm_sub_{split}"] = {"rows": len(s), "launches": int(s.item_idx.nunique()), "days": int(s.day.nunique())}
    tr = training_rows(b, b.days("train"), seed=SEEDS["train_rows"])
    assert tr.day.max() <= b.cfg.train_end
    f = f"{a.out}/taste_train_rows.parquet"
    tr.to_parquet(f); out.append(f)
    hs = tr[tr.neg_kind != "rand"].reset_index(drop=True)
    f = f"{a.out}/hard_train_sample.parquet"
    hs.to_parquet(f); out.append(f)
    info["hard_train_sample"] = {"rows": len(hs), "voters": int(hs.y.sum()), "launches": int(hs.item_idx.nunique()),
                                 "last_day": tr.day.max()}
    info["schema"] = SCHEMA_NOTE
    json.dump(info, open(f"{a.out}/sets_info.json", "w"), indent=1)
    open(f"{a.out}/SCHEMA.txt", "w").write(SCHEMA_NOTE + "\n")
    print(json.dumps(info, indent=1))
    sync(out + [f"{a.out}/sets_info.json", f"{a.out}/SCHEMA.txt"], a.sync)


# ------------------------------------------------------------------------------------------------ leak checks
def stage_leak(a):
    from simharness.bench import KIND_CODE, _day_bounds_utc, day_ord
    from simharness.models.llm import build_prompt
    from simharness.schema import ENDORSE
    b = load_bench(a)
    res = {}
    res["items_columns"] = list(b.items.columns)  # no vote / rank column may be present
    res["items_have_no_outcome_columns"] = not any(k in c.lower() for c in b.items.columns
                                                   for k in ("vote", "rank", "score", "out_"))
    tr = pd.read_parquet(f"{a.out}/taste_train_rows.parquet")
    res["train_rows_last_day"] = tr.day.max()
    res["train_rows_within_train_split"] = bool(tr.day.max() <= b.cfg.train_end)
    # 1. state(D) recomputed independently from history rows with item day < D
    rng = np.random.default_rng(3)
    worst = 0.0
    for d in rng.choice(b.days("test"), 3, replace=False):
        o, st = day_ord(d), b.state(d)
        h = b.hist[(b.hist.kind == KIND_CODE[ENDORSE]) & (b.hist.day_ord < o)]
        age = o - h.day_ord.to_numpy()
        ref_rw = pd.Series(0.5 ** (age / 7.0)).groupby(h.person_idx.to_numpy()).sum()
        ref_n30 = pd.Series((age <= 30).astype(float)).groupby(h.person_idx.to_numpy()).sum()
        pool = b.pool(d)
        worst = max(worst, float(np.abs(st["rw"][pool] - ref_rw.reindex(pool).fillna(0).to_numpy()).max()),
                    float(np.abs(st["n30"][pool] - ref_n30.reindex(pool).fillna(0).to_numpy()).max()))
        # nothing from day D or later: dropping those rows must not change the state
        assert h.day_ord.max() < o
    res["state_vs_independent_recompute_max_abs_diff"] = worst
    # 2. every event behind a prompt is before the day; prompts carry no handle and no outcome
    sub = pd.concat([pd.read_parquet(f"{a.out}/llm_sub_test.parquet"), pd.read_parquet(f"{a.out}/llm_sub_val.parquet")])
    bad_day = bad_ts = handles = n = 0
    max_gap = 10 ** 9
    for (d, it), g in sub.groupby(["day", "item_idx"]):
        hb = b.batch(d, g.person_idx.to_numpy())
        start, _ = _day_bounds_utc(d, b.cfg.day_tz)
        item = b.item(it)
        for j in range(0, len(hb), 6):
            ev = hb.events(j)
            bad_day += int((ev.day_ord >= day_ord(d)).sum())
            bad_ts += int((ev.ts.notna() & (ev.ts >= start)).sum())
            if len(ev):
                max_gap = min(max_gap, int(day_ord(d) - ev.day_ord.max()))
            pr = build_prompt(hb.render(j), item, 2)
            handles += len([m for m in re.findall(r"@[A-Za-z0-9_.-]+", pr) if m != "@someone"])
            n += 1
        # the item's own events exist in the store (they are the labels) but must never be in a history
        assert all((hb.events(j).item_idx != it).all() for j in range(0, len(hb), 6)), "label item in history"
    res["prompts_checked"] = n
    res["history_events_on_or_after_day"] = bad_day
    res["history_events_timed_after_day_start"] = bad_ts
    res["min_days_between_last_history_item_and_day"] = max_gap
    res["usernames_or_handles_in_prompts"] = handles
    # 3. the HARD negatives never voted for their item, and are in the day's pool
    for nm in ("hard_test", "hard_val"):
        h = pd.read_parquet(f"{a.out}/{nm}.parquet")
        viol = out_pool = 0
        for (d, it), g in h.groupby(["day", "item_idx"]):
            pos = set(b.positives(d, it).tolist())
            neg = g.person_idx[g.y == 0].to_numpy()
            viol += sum(int(p in pos) for p in neg)
            out_pool += int((~np.isin(g.person_idx.to_numpy(), b.pool(d))).sum())
        res[f"{nm}_negatives_that_voted"] = viol
        res[f"{nm}_rows_outside_pool"] = out_pool
    res["comment_events_in_state_use"] = "comments on items with day < D and (time unknown or before D starts)"
    res["known_residual_risk"] = ("upvotes are undated and attributed to the launch day, so a late upvote on an older "
                                  "launch cast after D can enter the history; the logistic's walk-forward labels for "
                                  "day D-1 come from reads made after D (offline convention)")
    json.dump(res, open(f"{a.out}/leak_checks.json", "w"), indent=1)
    print(json.dumps(res, indent=1))
    sync([f"{a.out}/leak_checks.json"], a.sync)


# ------------------------------------------------------------------------------------------------ taste
def _taste(a, b):
    from simharness.features import TasteFeatures
    return TasteFeatures(b, np.load(f"{a.out}/item_emb_bge_small.npy"))


def stage_taste(a):
    from simharness.features import TASTE_NAMES, embed_items
    from simharness.models.taste import TasteVote, featurize, pool_weights
    from simharness.score import evaluate_full, predict_rows, score_rows, summarize
    b = load_bench(a)
    t = time.time()
    ef = f"{a.out}/item_emb_bge_small.npy"
    if not os.path.exists(ef):
        np.save(ef, embed_items(b))
        sync([ef], a.sync)
    tf = _taste(a, b)
    tr = pd.read_parquet(f"{a.out}/taste_train_rows.parquet")
    assert tr.day.max() <= b.cfg.train_end
    xf = f"{a.out}/taste_Xtr.npy"
    if not os.path.exists(xf):
        np.save(xf, featurize(tf, tr))
    X, y = np.load(xf), tr.y.to_numpy()
    print("train rows", len(tr), tr.neg_kind.value_counts().to_dict(), round(time.time() - t), flush=True)
    vh = pd.read_parquet(f"{a.out}/hard_val.parquet")
    variants = {"unweighted (hard negatives = half the rows)": None,
                "pool-weighted, hard share 0.1": pool_weights(b, tr, 0.1),
                "pool-weighted, hard share 0.3": pool_weights(b, tr, 0.3)}
    report, models = {}, {}
    for name, w in variants.items():
        m = TasteVote(tf, "lgbm", name=name).fit(X, y, sample_weight=w)
        sh = summarize(score_rows(vh, predict_rows(m, b, vh)), pooled_auc=True, n_boot=300, cluster="item")
        sf = summarize(evaluate_full(m, b, b.days("val"), log=lambda *x: None), n_boot=300)
        report[name] = {"val_hard_auc_pooled": sh["auc_pooled"], "val_hard_auc_mean": sh["auc_mean"],
                        "val_full_recall_at_N": sf["recall_at_N_pooled"], "val_full_auc_mean": sf["auc_mean"]}
        models[name] = m.clf
        print(name, json.dumps(report[name]), round(time.time() - t), flush=True)
        pickle.dump(models, open(f"{a.out}/taste_models.pkl", "wb"))
        json.dump(report, open(f"{a.out}/taste_val_report.json", "w"), indent=1)
    # choice on validation: best VAL-HARD AUC among variants whose full-pool ranking still works (AUC >= 0.85)
    ok = {k: v for k, v in report.items() if v["val_full_auc_mean"]["value"] >= 0.85} or report
    chosen = max(ok, key=lambda k: ok[k]["val_hard_auc_pooled"]["value"])
    report["_chosen"] = chosen
    report["_rule"] = "highest VAL-HARD pooled AUC among variants with validation full-pool mean AUC >= 0.85"
    report["_feature_gain"] = dict(zip(TASTE_NAMES, np.round(
        models[chosen].booster_.feature_importance("gain") / models[chosen].booster_.feature_importance("gain").sum(),
        3).tolist()))
    json.dump(report, open(f"{a.out}/taste_val_report.json", "w"), indent=1)
    print("chosen", chosen, report["_feature_gain"])
    sync([f"{a.out}/taste_models.pkl", f"{a.out}/taste_val_report.json"], a.sync)


def _models(a, b):
    from simharness.models.baselines import backer_logistic, most_active
    from simharness.models.taste import TasteVote
    rep = json.load(open(f"{a.out}/taste_val_report.json"))
    clfs = pickle.load(open(f"{a.out}/taste_models.pkl", "rb"))
    tf = _taste(a, b)
    out = {"most-active": most_active(), "logistic": backer_logistic()}
    tv = TasteVote(tf, "lgbm", name="taste-v1"); tv.clf = clfs[rep["_chosen"]]
    out["taste-v1"] = tv
    for k, c in clfs.items():
        if k.startswith("unweighted"):
            t2 = TasteVote(tf, "lgbm", name="taste-v1 hard-only"); t2.clf = c
            out["taste-v1 hard-only (ablation)"] = t2
    return out


# ------------------------------------------------------------------------------------------------ nonllm
def stage_nonllm(a):
    from simharness.score import predict_rows, score_item, stack_apply, stack_fit
    b = load_bench(a)
    models = _models(a, b)
    sets = {k: pd.read_parquet(f"{a.out}/{k}.parquet") for k in ("hard_test", "hard_val", "llm_sub_test", "llm_sub_val")}
    sets["easy"] = pd.read_parquet(a.easy)
    done = []
    for sname, rows in sets.items():
        f = f"{a.out}/preds_nonllm_{sname}.parquet"
        if not os.path.exists(f):
            r = rows[["day", "item_idx", "person_idx", "y"]].reset_index(drop=True)
            for mn, m in models.items():
                r[mn] = predict_rows(m, b, r)
            r.to_parquet(f)
            print("scored", sname, len(r), flush=True)
        done.append(f)
    sync(done, a.sync)
    # full-pool ranking on every test launch, and the logistic + taste stack fit on a weighted validation sample
    f = f"{a.out}/full_test.pkl"
    if not os.path.exists(f):
        vs = b.training_sample(b.days("val"), k=50, seed=5)
        pv = {mn: predict_rows(models[mn], b, vs) for mn in ("logistic", "taste-v1")}
        clf = stack_fit([pv["logistic"], pv["taste-v1"]], vs.y.to_numpy()) if a.unweighted_full_stack else None
        if clf is None:
            from sklearn.linear_model import LogisticRegression
            from simharness.score import _logit
            clf = LogisticRegression(max_iter=1000).fit(
                np.column_stack([_logit(pv["logistic"]), _logit(pv["taste-v1"])]), vs.y.to_numpy(),
                sample_weight=vs.w.to_numpy())
        full = {mn: [] for mn in list(models) + ["logistic + taste-v1 (stack)"]}
        for d in b.days("test"):
            pool = b.pool(d)
            hb = b.batch(d, pool)
            for m in models.values():
                m.prepare(b, d)
            for it in b.items_on(d):
                yy = np.isin(pool, b.positives(d, it)).astype(np.int8)
                if yy.sum() == 0:
                    continue
                item = b.item(it)
                ps = {mn: m.score(hb, item) for mn, m in models.items()}
                ps["logistic + taste-v1 (stack)"] = stack_apply(clf, [ps["logistic"], ps["taste-v1"]])
                for mn, p in ps.items():
                    full[mn].append({"day": d, "item_idx": int(it), **score_item(p, yy)})
            print("full", d, flush=True)
        pickle.dump({"per_item": {k: pd.DataFrame(v) for k, v in full.items()},
                     "stack_weights": clf.coef_[0].round(3).tolist()}, open(f, "wb"))
    sync([f], a.sync)


# ------------------------------------------------------------------------------------------------ llm
def backend_for(name: str, project: str, budget):
    from simharness.models.llm import VertexClaude, VertexGemini, VertexOpenAICompat
    if name == "gpt-oss-120b":
        return VertexOpenAICompat("openai/gpt-oss-120b-maas", project, "us-central1", budget=budget, max_out=700,
                                  extra={"reasoning_effort": "low"})
    if name == "llama-4-maverick":
        return VertexOpenAICompat("meta/llama-4-maverick-17b-128e-instruct-maas", project, "us-east5", budget=budget,
                                  max_out=150, extra={"response_format": {"type": "json_object"}})
    if name.startswith("gemini"):
        return VertexGemini(name, project, "us-central1", budget=budget, max_out=150)
    if name.startswith("claude"):
        return VertexClaude(name, project, "global", budget=budget, max_out=120)
    raise ValueError(name)


def stage_llm(a):
    from simharness.models.llm import Budget, BudgetExceeded, JsonlCache, PromptVote
    b = load_bench(a)
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    rows = pd.read_parquet(f"{a.out}/llm_sub_{a.split}.parquet").reset_index(drop=True)
    budget = Budget(a.cap)
    for name in a.models.split(","):
        cdir = f"{a.out}/llm_cache/{name}/{a.split}"
        cache = JsonlCache(cdir)
        be = backend_for(name, project, budget)
        pm = PromptVote(be, workers=a.workers, cache=cache, prompt_version=2)
        p = np.full(len(rows), np.nan)
        t = time.time()
        gsdir = f"{a.sync.rstrip('/')}/llm_cache/{name}/{a.split}" if a.sync else None
        stopped = False
        for k, ((d, it), g) in enumerate(rows.groupby(["day", "item_idx"], sort=True)):
            try:
                p[g.index.to_numpy()] = pm.score(b.batch(d, g.person_idx.to_numpy()), b.item(it))
            except BudgetExceeded as e:
                print("STOP", name, e, flush=True)
                stopped = True
            if stopped or k % 5 == 4:
                part = cache.roll()
                sync([part] if part else [], gsdir)
                st = be.stats(); st.update(model=name, split=a.split, at=time.time(), failures=pm.failures)
                with open(f"{a.out}/spend_ledger.jsonl", "a") as f:
                    f.write(json.dumps(st) + "\n")
            if stopped:
                break
        part = cache.roll()
        sync([part] if part else [], gsdir)
        st = be.stats()
        st.update(model=name, split=a.split, at=time.time(), failures=pm.failures, wall_s=round(time.time() - t),
                  final=True, unparsed=int(np.isnan(p).sum()), rows=len(rows))
        with open(f"{a.out}/spend_ledger.jsonl", "a") as f:
            f.write(json.dumps(st) + "\n")
        if not stopped:
            f1 = f"{a.out}/preds_llm_{name}_{a.split}.parquet"
            rows.assign(p=p).to_parquet(f1)
            sync([f1], a.sync)
        sf = f"{a.out}/spend_ledger_{int(time.time())}.jsonl"
        open(sf, "w").write(open(f"{a.out}/spend_ledger.jsonl").read())
        sync([sf], f"{a.sync.rstrip('/')}/spend" if a.sync else None)
        print(name, a.split, json.dumps(st), flush=True)
        if stopped:
            break
    print("this run spent", round(budget.spent, 4), {k: round(v, 4) for k, v in budget.lines.items()})


# ------------------------------------------------------------------------------------------------ agg
def stage_agg(a):
    from simharness.score import paired_diff, score_rows, stack_apply, stack_fit, summarize
    NB = 2000

    def S(rows, p, cl="item"):
        s = summarize(score_rows(rows, p), pooled_auc=True, n_boot=NB, cluster=cl)
        return {"auc_pooled": s["auc_pooled"], "auc_mean_per_launch": s["auc_mean"], "n": s["pairs"],
                "launches": s["items"], "days": s["days"]}

    def D(rows, pa, pb, metric="auc_pooled"):
        return paired_diff(score_rows(rows, pa), score_rows(rows, pb), metric, NB, pooled_auc=True, cluster="item")

    P = {k: pd.read_parquet(f"{a.out}/preds_nonllm_{k}.parquet")
         for k in ("hard_test", "hard_val", "llm_sub_test", "llm_sub_val", "easy")}
    full = pickle.load(open(f"{a.out}/full_test.pkl", "rb"))
    nonllm = [c for c in P["hard_test"].columns if c not in ("day", "item_idx", "person_idx", "y")]
    res = {"task": "Benchmark v0 Task V, round 1", "intervals": "bootstrap 95%, resampling launches (FULL: days)",
           "sets": json.load(open(f"{a.out}/sets_info.json")), "models": {}, "paired_vs_logistic": {}, "stacks": {},
           "leak_checks": json.load(open(f"{a.out}/leak_checks.json")),
           "taste_v1_validation": json.load(open(f"{a.out}/taste_val_report.json"))}
    for mn in nonllm:
        e = {"HARD": S(P["hard_test"], P["hard_test"][mn]), "HARD_LLM": S(P["llm_sub_test"], P["llm_sub_test"][mn]),
             "VAL_HARD": S(P["hard_val"], P["hard_val"][mn]), "EASY": S(P["easy"], P["easy"][mn]),
             "cost_per_1k_usd": 0.0}
        if mn in full["per_item"]:
            s = summarize(full["per_item"][mn], n_boot=NB)
            e["FULL"] = {k: s[k] for k in ("recall_at_N_pooled", "recall_at_N_mean", "auc_mean", "items", "positives")}
        res["models"][mn] = e
        if mn != "logistic":
            res["paired_vs_logistic"][mn] = {
                "HARD": D(P["hard_test"], P["hard_test"][mn], P["hard_test"]["logistic"]),
                "HARD_mean_per_launch": D(P["hard_test"], P["hard_test"][mn], P["hard_test"]["logistic"], "auc_mean"),
                "HARD_LLM": D(P["llm_sub_test"], P["llm_sub_test"][mn], P["llm_sub_test"]["logistic"])}
    sk = "logistic + taste-v1 (stack)"
    s = summarize(full["per_item"][sk], n_boot=NB)
    res["stacks"][sk + ", FULL"] = {"FULL": {k: s[k] for k in ("recall_at_N_pooled", "recall_at_N_mean", "auc_mean")},
                                    "weights_logit": full["stack_weights"], "fit_on": "weighted validation pool sample",
                                    "recall_diff_vs_logistic": paired_diff(full["per_item"][sk],
                                                                           full["per_item"]["logistic"],
                                                                           "recall_at_N_pooled", NB)}
    # stacks on HARD: weights from VAL-HARD only
    yv = P["hard_val"].y.to_numpy()
    for members in (["logistic", "taste-v1"],):
        clf = stack_fit([P["hard_val"][m] for m in members], yv)
        for sname, lab in (("hard_test", "HARD"), ("llm_sub_test", "HARD_LLM")):
            ps = stack_apply(clf, [P[sname][m].to_numpy() for m in members])
            res["stacks"].setdefault(" + ".join(members) + " (stack)", {"weights_logit": clf.coef_[0].round(3).tolist(),
                                                                         "fit_on": "VAL-HARD"})[lab] = {
                **S(P[sname], ps), "diff_vs_logistic": D(P[sname], ps, P[sname]["logistic"]),
                "diff_vs_logistic_mean_per_launch": D(P[sname], ps, P[sname]["logistic"], "auc_mean")}
    # prompt models
    led = {}
    lf = f"{a.out}/spend_ledger.jsonl"
    for line in (open(lf) if os.path.exists(lf) else []):
        r = json.loads(line)
        if r.get("final"):
            led[(r["model"], r["split"])] = r
    spend = {}
    for f in sorted(glob.glob(f"{a.out}/preds_llm_*_test.parquet")):
        name = os.path.basename(f)[len("preds_llm_"):-len("_test.parquet")]
        r = pd.read_parquet(f)
        base = P["llm_sub_test"]
        assert (r.person_idx.to_numpy() == base.person_idx.to_numpy()).all()
        st = led.get((name, "test"), {})
        e = {"HARD_LLM": S(r, r.p), "HARD_LLM_day_bootstrap": S(r, r.p, "day"),
             "cost_per_1k_usd": st.get("cost_per_1k_usd"), "latency_s_median": st.get("latency_s_median"),
             "latency_s_p90": st.get("latency_s_p90"), "tokens_in": st.get("tokens_in"),
             "unparsed": int(r.p.isna().sum())}
        res["models"][name] = e
        res["paired_vs_logistic"][name] = {"HARD_LLM": D(r, r.p, base["logistic"]),
                                           "HARD_LLM_mean_per_launch": D(r, r.p, base["logistic"], "auc_mean"),
                                           "HARD_LLM_vs_taste-v1": D(r, r.p, base["taste-v1"])}
        vf = f"{a.out}/preds_llm_{name}_val.parquet"
        if os.path.exists(vf):
            v = pd.read_parquet(vf)
            bv = P["llm_sub_val"]
            assert (v.person_idx.to_numpy() == bv.person_idx.to_numpy()).all()
            e["VAL_HARD_LLM"] = S(v, v.p)
            for mem in ("logistic", "taste-v1"):
                clf = stack_fit([bv[mem].to_numpy(), v.p.to_numpy()], bv.y.to_numpy())
                ps = stack_apply(clf, [base[mem].to_numpy(), r.p.to_numpy()])
                res["stacks"][f"{mem} + {name} (stack)"] = {
                    "weights_logit": clf.coef_[0].round(3).tolist(), "fit_on": "VAL-HARD-LLM (480 rows)",
                    "HARD_LLM": {**S(r, ps), "diff_vs_logistic": D(r, ps, base["logistic"]),
                                 "diff_vs_member": D(r, ps, base[mem])}}
    for (m, sp), r in led.items():
        spend[f"{m} / {sp}"] = r["cost_usd"]
    res["spend_usd_this_run"] = spend
    if a.prior and os.path.exists(a.prior):
        res["before_restart"] = json.load(open(a.prior))
    os.makedirs(a.results_dir, exist_ok=True)
    json.dump(res, open(f"{a.results_dir}/results.json", "w"), indent=1, default=float)
    print("wrote", f"{a.results_dir}/results.json")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["sets", "leak", "taste", "nonllm", "llm", "agg"])
    ap.add_argument("--bench", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sync", default="")
    ap.add_argument("--easy", default="")
    ap.add_argument("--models", default="")
    ap.add_argument("--split", default="test")
    ap.add_argument("--cap", type=float, default=0.0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--results-dir", default="")
    ap.add_argument("--prior", default="")
    ap.add_argument("--unweighted-full-stack", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    globals()[f"stage_{a.stage}"](a)


if __name__ == "__main__":
    main()
