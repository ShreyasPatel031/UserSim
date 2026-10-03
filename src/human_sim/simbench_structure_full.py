"""Full benchmark (13,510 questions): the principled sharp/shallow routed method vs retr6_rev2. No model calls.

Sharp = top substantive answer >= 70% (DK / refused ignored). A pre-answer classifier (question metadata + the retr6
demos' own answers), trained on dev, predicts sharpness. Predicted sharp -> retr6_rev2 answer unchanged; predicted
shallow -> 75% retr6_rev2 + 25% Dirichlet-multinomial mixture (3 segments, 10 most similar other questions). Cutoff,
tool and weight are the dev-fitted values for this definition. No target question's answers are used for any group:
neighbour questions exclude the target, and the tool only exists for the 5 shared surveys (elsewhere: model answer)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from human_sim import simbench_ablate as A
from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_l3 as L
from human_sim.simbench_structure_l1 import demo_features
from human_sim.simbench_structure_sharp import ci
from human_sim.simbench_structure_sharpdef import sub_shares

THETA = 0.70
CACHE = M.OUT / "structure_full_toolpreds.pkl"
NUM = ["n_options", "value_laden", "demo_mean_entropy", "demo_share_multimodal", "demo_spread"]


def routing():
    r = json.loads((M.OUT / "structure_sharpdef_report.json").read_text())
    row = next(x for x in r["method"] if x["definition"] == "top share >= 70%")["routing"]
    return row["prob_cutoff"], tuple(row["shallow_tool"]), row["weight"]


def topic_model():
    full = pd.concat([A.load_split("Pop"), A.load_split("Grouped")])
    stems = sorted({A._stem(t) for t in full.input_template})
    vec = TfidfVectorizer(stop_words="english", min_df=2)
    km = KMeans(n_clusters=20, n_init=10, random_state=0).fit(vec.fit_transform(stems))
    lut = dict(zip(stems, km.labels_))
    return lambda s: int(lut.get(s, km.predict(vec.transform([s]))[0]))


def features(qs, sample, ctx, topic_of):
    rows = []
    for q in qs:
        r = sample.loc[q["i"]]
        demos = A._rank_by_similarity(r, A._demo_pool(r, ctx), ctx)[:6]
        rows.append({"qid": q["qid"], "dataset": q["dataset"], "n_options": q["n_options"], "value_laden": float(q["value_laden"]),
                     "topic": topic_of(A._stem(q["question"])), **demo_features(demos)})
    return pd.DataFrame(rows)


def design(d, ds, means):
    return np.c_[d[NUM].fillna(means).values, np.array([[float(x == k) for k in ds] for x in d.dataset]),
                 np.array([[float(t == k) for k in range(20)] for t in d.topic])]


def main():
    cut, tool, w = routing()
    print(f"routing (dev-fitted for top share >= 70%): sharp if P(sharp) >= {cut}; shallow -> {tool} weight {w:.2f}", flush=True)
    # classifier trained on dev rows, exactly as in the threshold analysis
    l1 = pd.read_pickle(M.OUT / "structure_l1_rows.pkl")
    ds = sorted(l1.dataset.unique())
    means = l1[NUM].mean()
    M.EVAL_ARMS = M.DEV_ARMS = {}
    dev_top = {q["qid"]: sub_shares(q["keys"], q["roles"], q["h"])[0] for q in M.load("dev")}
    tr = l1[l1.set == "dev"]
    sc = StandardScaler().fit(design(tr, ds, means))
    clf = LogisticRegression(C=0.5, max_iter=5000).fit(sc.transform(design(tr, ds, means)), np.array([dev_top[q] >= THETA for q in tr.qid], int))

    M.EVAL_ARMS = M.DEV_ARMS = {"plain": ("retr6_rev2", M.HAIKU)}
    sample, _, ctx = A.build_env(25, 100, 7, "full")
    qs = [q for q in M.load("full") if "plain" in q["preds"]]
    print(f"full-benchmark questions with a retr6_rev2 answer: {len(qs)}", flush=True)
    feat = features(qs, sample, ctx, topic_model())
    p_sharp = dict(zip(feat.qid, clf.predict_proba(sc.transform(design(feat, ds, means)))[:, 1]))

    # tool predictions for predicted-shallow shared-survey questions only
    cache = pd.read_pickle(CACHE) if CACHE.exists() else {}
    targets = [t for t in L.targets("full") if p_sharp.get(t["q"]["qid"], 1.0) < cut and t["q"]["qid"] not in cache]
    if targets:
        F = L.Fitter(L.build_surveys(set()))
        for i, t in enumerate(targets):
            cache[t["q"]["qid"]] = L.predict(F, t, *tool)
            if i % 500 == 0:
                pd.to_pickle(cache, CACHE)
                print(f"   tool predictions {i}/{len(targets)}", flush=True)
        pd.to_pickle(cache, CACHE)

    dev_sample, _, _ = A.build_env(25, 100, 7, "dev")
    dev_keys = {(r.dataset_name, A._filled_persona(r), r.input_template) for _, r in dev_sample.iterrows()}
    S = L.S
    recs = []
    for q in qs:
        p = np.asarray(q["preds"]["plain"])
        x = cache.get(q["qid"])
        routed_shallow = p_sharp[q["qid"]] < cut
        f = w * x + (1 - w) * p if (routed_shallow and x is not None) else p
        r = sample.loc[q["i"]]
        top = sub_shares(q["keys"], q["roles"], q["h"])[0]
        recs.append({"dataset": q["dataset"], "group3": q["group3"], "split": q["split"], "S_model": S(q, p), "S_method": S(q, f),
                     "changed": bool(routed_shallow and x is not None), "true_sharp": top >= THETA,
                     "in_dev": (r.dataset_name, A._filled_persona(r), r.input_template) in dev_keys})
    df = pd.DataFrame(recs)
    d = (df.S_method - df.S_model).values
    out = {"N": len(df), "changed": int(df.changed.sum()), "S_model": float(df.S_model.mean()), "S_method": float(df.S_method.mean()),
           "diff": float(d.mean()), "ci": ci(d), "slices": {}}
    for name, m in [("excluding dev rows", ~df.in_dev), ("shared surveys", df.group3 == "shared_survey"),
                    ("shared surveys, changed questions", df.changed), ("true sharp (>= 70%)", df.true_sharp),
                    ("true shallow (< 70%)", ~df.true_sharp), ("shared surveys, Grouped", (df.group3 == "shared_survey") & (df.split == "Grouped")),
                    ("shared surveys, Pop", (df.group3 == "shared_survey") & (df.split == "Pop"))]:
        m = m.values
        out["slices"][name] = {"N": int(m.sum()), "S_model": float(df.S_model[m].mean()), "S_method": float(df.S_method[m].mean()),
                               "diff": float(d[m].mean()), "ci": ci(d[m])}
    out["by_dataset"] = {k: {"N": int(len(g)), "S_model": float(g.S_model.mean()), "S_method": float(g.S_method.mean()),
                             "changed": int(g.changed.sum())} for k, g in df.groupby("dataset")}
    print(f"\n== FULL BENCHMARK: {out['N']} questions, method changed {out['changed']}")
    print(f"   retr6_rev2 {out['S_model']:.2f} -> method {out['S_method']:.2f} ({out['diff']:+.2f} {out['ci']})")
    for k, v in out["slices"].items():
        print(f"   {k:36s} N {v['N']:5d}  {v['S_model']:.1f} -> {v['S_method']:.1f}  {v['diff']:+.2f} {v['ci']}")
    print("   by dataset (changed only):", {k: f"{v['S_model']:.1f}->{v['S_method']:.1f}" for k, v in out["by_dataset"].items() if v["changed"]})
    (M.OUT / "structure_full_report.json").write_text(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    main()
