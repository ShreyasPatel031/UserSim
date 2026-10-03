"""Layer 2 step for the divided bucket: tune D3 (same subgroup cell, same topic) with a stand-in predictor (free).

Grouped targets in the 5 shared surveys only. Pool = the same spare rows D3 uses (never eval rows, never the target's
question stem). Stand-in = mean of the selected demos that share the target's option count; if none does, the retr6
top-6 stand-in for that row, so configs differ only where they supply aligned demos."""

from __future__ import annotations

import itertools
import json
import re
from collections import defaultdict

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans

from human_sim import simbench_ablate as A
from human_sim import simbench_mass_levers as M
from human_sim.simbench_structure_l2 import standin as retr_standin

NS = (1, 2, 3, 4, 6, 8, 12)
TOPIC = ("same", "near2", "any")
FILL = ("none", "country_other_attr", "retr6")
MIN_N = (0, 200, 500)
WAVE = ("any", "same")
DEFAULT = (6, "same+cell", "none", 0, "any")  # D3 as run: same-topic same-cell first, then same-cell other topics


def year_of(persona):
    m = re.search(r"year is (\d{4})", persona)
    return m.group(1) if m else ""


def pool_and_topics():
    pop, grp = A.load_split("Pop"), A.load_split("Grouped")
    rows = A.extended_pool(grp, 100, 7, 3, 10**6)
    pool = defaultdict(list)
    for _, r in rows.iterrows():
        if r["dataset_name"] not in A.D_DATASETS:
            continue
        e = A._demo_entry(r)
        e.update(stem=A._stem(r["input_template"]), cell=A._cell_key(r), size=float(r.get("group_size", 0) or 0),
                 year=year_of(e["persona"]))
        pool[r["dataset_name"]].append(e)
    topics, cents = {}, {}
    for ds in A.D_DATASETS:
        stems = sorted({A._stem(t) for t in grp[grp.dataset_name == ds].input_template})
        X = np.array(A._embed(stems))
        X = X / np.linalg.norm(X, axis=1, keepdims=True)
        k = min(len(stems), max(6, round(len(stems) / 30)))
        km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(X)
        for s, lab, x in zip(stems, km.labels_, X):
            topics[(ds, s)] = (int(lab), np.argsort(((km.cluster_centers_ - x) ** 2).sum(1))[:2].tolist())
    return pool, topics


def candidates(row, q, pool, topics, ctx, topic, fill, min_n, wave):
    ds, stem, cell, yr = row["dataset_name"], A._stem(row["input_template"]), A._cell_key(row), year_of(A._filled_persona(row))
    tlab, near = topics.get((ds, stem), (None, []))
    same = [e for e in pool[ds] if e["cell"] == cell and e["stem"] != stem and e["size"] >= min_n and (wave == "any" or e["year"] == yr)]
    ranked = A._rank_by_similarity(row, same, ctx, max_per_question=10**6) if same else []
    if topic == "same":
        sel = [e for e in ranked if topics.get((ds, e["stem"]), (None,))[0] == tlab]
    elif topic == "near2":
        sel = [e for e in ranked if topics.get((ds, e["stem"]), (None,))[0] in near]
    elif topic == "same+cell":
        sel = [e for e in ranked if topics.get((ds, e["stem"]), (None,))[0] == tlab]
        sel += [e for e in ranked if e not in sel]
    else:
        sel = ranked
    out = list(sel)
    if fill == "country_other_attr":
        other = [e for e in pool[ds] if e["cell"][1] == cell[1] and e["cell"][2] != cell[2] and e["stem"] != stem and e["size"] >= min_n]
        out += A._rank_by_similarity(row, other, ctx, max_per_question=1) if other else []
    elif fill == "retr6":
        out += A._rank_by_similarity(row, A._demo_pool(row, ctx), ctx)
    return out, len(sel)


def standin(q, demos, n, fallback):
    nk = len(q["keys"])
    al = [d for d in demos[:n] if len(d["human_answer"]) == nk]
    if not al:
        return fallback
    return np.mean([np.array(list(d["human_answer"].values()), float) / sum(d["human_answer"].values()) for d in al], axis=0)


def S(q, p):
    return 100 * (1 - M.tvd(p, q["h"]) / q["norm"])


def ci(d):
    rng = np.random.default_rng(0)
    b = np.sort([rng.choice(d, len(d)).mean() for _ in range(2000)])
    return round(float(b[50]), 1), round(float(b[1949]), 1)


def run(which, pool, topics, retr_rows):
    sample, _, ctx = A.build_env(25, 100, 7, which)
    retr = {r["qid"]: r for r in retr_rows}
    res = []
    for q in M.load(which):
        if q["split"] != "Grouped" or q["dataset"] not in A.D_DATASETS:
            continue
        row = sample.loc[q["i"]]
        fb = retr_standin(retr[q["qid"]], 6) if q["qid"] in retr and retr[q["qid"]]["aligned"] else np.ones(len(q["keys"])) / len(q["keys"])
        rec = {"qid": q["qid"], "band": "consensus" if q["Hn"] < 0.65 else ("mixed" if q["Hn"] < M.DIV else "divided"), "S": {}, "n_same": {}}
        for topic, fill, min_n, wave in list(itertools.product(TOPIC, FILL, MIN_N, WAVE)) + [("same+cell", "none", 0, "any")]:
            demos, n_same = candidates(row, q, pool, topics, ctx, topic, fill, min_n, wave)
            rec["n_same"][(topic, min_n, wave)] = n_same
            for n in NS:
                rec["S"][(n, topic, fill, min_n, wave)] = S(q, standin(q, demos, n, fb))
        res.append(rec)
    return res


def main():
    from human_sim.simbench_structure_l2 import build
    pool, topics = pool_and_topics()
    out = {}
    dev = run("dev", pool, topics, build("dev"))
    ev = run("eval", pool, topics, build("eval"))
    configs = list(dev[0]["S"])
    dscore = {c: float(np.mean([r["S"][c] for r in dev])) for c in configs}
    best = max(configs, key=dscore.get)
    base = DEFAULT
    e_best = np.array([r["S"][best] for r in ev])
    e_base = np.array([r["S"][base] for r in ev])
    n_same = [r["n_same"][("same+cell", 0, "any")] for r in dev]
    out = {"N_dev": len(dev), "N_eval": len(ev), "mean_same_cell_demos_dev": float(np.mean(n_same)),
           "dev_default_S": dscore[base], "dev_best": {"config": list(best), "S": dscore[best]},
           "eval_default_S": float(e_base.mean()), "eval_best_S": float(e_best.mean()),
           "eval_best_vs_default": float((e_best - e_base).mean()), "ci": ci(e_best - e_base),
           "dev_top10": [[list(c), dscore[c]] for c in sorted(configs, key=dscore.get, reverse=True)[:10]]}
    marg = {}
    for i, name in enumerate(("n", "topic", "fill", "min_n", "wave")):
        vals = sorted({c[i] for c in configs}, key=str)
        marg[name] = {str(v): float(np.mean([dscore[c] for c in configs if c[i] == v])) for v in vals}
    out["dev_marginals"] = marg
    for b in ("consensus", "mixed", "divided"):
        m = np.array([r["band"] == b for r in ev])
        out[f"eval_{b}"] = {"N": int(m.sum()), "default": float(e_base[m].mean()), "best": float(e_best[m].mean()),
                            "diff_ci": ci((e_best - e_base)[m]) if m.sum() > 5 else None}
    print(f"dev Grouped targets {len(dev)}, eval {len(ev)}; same-cell demos per dev target (any topic, any wave): {np.mean(n_same):.1f}")
    print(f"default D3 stand-in: dev {dscore[base]:.1f}, eval {e_base.mean():.1f}")
    print(f"best dev config {best}: dev {dscore[best]:.1f}, eval {e_best.mean():.1f} ({(e_best - e_base).mean():+.1f} {ci(e_best - e_base)})")
    print("dev marginals (mean stand-in S over all other settings):")
    for k, v in marg.items():
        print(f"   {k:6s}", {a: round(b, 1) for a, b in v.items()})
    for b in ("consensus", "mixed", "divided"):
        print(f"   eval {b}: {out[f'eval_{b}']}")
    (M.OUT / "structure_l2_d3_sweep.json").write_text(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    main()
