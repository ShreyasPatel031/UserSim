"""Cross-national factor completion (no model calls): factor analysis / PCA as low-rank matrix completion.

Matrix = subgroup cells x per-option answer shares on the target question plus its K text-nearest neighbour questions,
from the benchmark's training rows of the same survey (eval/dev rows never enter). For the TARGET question column,
every cell from the target's own country is blanked, so no respondent of the population being predicted contributes
an answer to the target question (the target cell itself is an eval/dev row, so it is never there to begin with).
The tool estimates the target question's loadings from other countries' groups and the target group's factor scores
from its own answers on the neighbour questions; the completed entry is the prediction.
Grouped targets: the target cell's completed row. Pop targets: size-weighted mean of the country's attribute cells.
Output: structure_xnat_preds.pkl {(tool, K, r): {qid: prediction or None}} + coverage/diagnostics."""

from __future__ import annotations

import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_l3 as L

OUT = M.OUT / "structure_xnat_preds.pkl"
CFGS = [("fa", 10, 2), ("fa", 10, 3), ("pca", 10, 2), ("pca", 10, 3), ("ppca", 10, 3), ("fa", 5, 2),
        ("dmm", 10, 3), ("dmm", 10, 5), ("dmm", 10, 8), ("dmm", 19, 5), ("dmm", 19, 8), ("gmm", 10, 4), ("kmeans", 10, 4),
        ("seg", 10, 3), ("seg", 10, 5), ("seg", 10, 8), ("seg", 19, 5), ("segsoft", 10, 5), ("segsoft", 19, 8)]
EXTRA = [tuple([a.split("=")[1].split(",")[0], int(a.split(",")[1]), int(a.split(",")[2])]) for a in sys.argv if a.startswith("--cfg=")]
ONLY = EXTRA if EXTRA else [c for c in CFGS if c[0].startswith("seg")] if "--seg" in sys.argv else ([c for c in CFGS if c[0] in L.CL_TOOLS] if "--cl" in sys.argv else CFGS)
MIN_OTHER = int(os.environ.get("XN_MIN_OTHER", 3))  # other-country groups that must have answered the target question
PRIOR = 2.0  # pseudo-rows of the other-country average added to each segment's profile on the target question


def answered_index(sv):
    """Stems each cell / each country's attribute cells answered in the training pool (cached on the survey dict)."""
    if "_by_cell" not in sv:
        by_cell, by_country = defaultdict(set), defaultdict(set)
        for (c, st) in sv["obs"]:
            by_cell[c].add(st)
            if c[2]:
                by_country[c[1]].add(st)
        sv["_by_cell"], sv["_by_country"] = by_cell, by_country
    return sv["_by_cell"], sv["_by_country"]


def neighbours_tn(sv, t, K):
    """K text-nearest questions among those the target group itself answered (target question excluded)."""
    by_cell, by_country = answered_index(sv)
    mine = by_country[t["country"]] if t["split"] == "Pop" else by_cell.get(t["cell"], set())
    sims = (sv["S_mat"] @ sv["vec"].transform([t["text"]]).T).toarray().ravel()
    order = [i for i in np.argsort(-sims) if sv["stems"][i] != t["stem"] and sv["stems"][i] in mine]
    return [(sv["stems"][i], float(sims[i])) for i in order[:K]]


def neighbours_tp(sv, t, K):
    """D3's retrieved set: questions the target group answered in the target question's own topic, most similar first;
    topped up with the group's other answered questions if the topic has fewer than 5."""
    by_cell, by_country = answered_index(sv)
    mine = by_country[t["country"]] if t["split"] == "Pop" else by_cell.get(t["cell"], set())
    tm, ds = t["topic_map"], t["q"]["dataset"]
    tgt_topic = tm.get((ds, t["stem"]))
    sims = (sv["S_mat"] @ sv["vec"].transform([t["text"]]).T).toarray().ravel()
    order = [i for i in np.argsort(-sims) if sv["stems"][i] != t["stem"] and sv["stems"][i] in mine]
    same = [i for i in order if tgt_topic is not None and tm.get((ds, sv["stems"][i])) == tgt_topic]
    pick = same[:K]
    if len(pick) < 5:
        pick += [i for i in order if i not in pick][:K - len(pick)]
    return [(sv["stems"][i], float(sims[i])) for i in pick]


def parse_tool(tool):
    """'segsoft_tn' -> ('segsoft', True); 'seg:0.01:2.0:1.0' -> ('seg', False, scale, prior, temp)."""
    tn = "tp" if tool.endswith("_tp") else tool.endswith("_tn")
    base = tool[:-3] if tn else tool
    parts = base.split(":")
    return parts[0], tn, [float(x) for x in parts[1:]]


def segments(X, cols, counts, k, tgt_sl, scale, prior=None, seeds=(0,)):
    """Soft opinion segments (multinomial mixture over cells' answers on the neighbour questions, target column excluded
    from the memberships); each segment's answer to the target question = membership-weighted mean of the other-country
    cells that answered it, shrunk toward their overall mean. Returns completed target-column values for every row."""
    nb_cols = {st: sl for st, sl in cols.items() if sl != tgt_sl}
    Xn = np.concatenate([X[:, sl] for sl in nb_cols.values()], axis=1)
    sub, start = {}, 0
    for st, sl in nb_cols.items():
        n = sl.stop - sl.start
        sub[st] = slice(start, start + n)
        start += n
    prior = PRIOR if prior is None else prior
    T = X[:, tgt_sl]
    obs = ~np.isnan(T[:, 0])
    g = np.nanmean(T[obs], axis=0)
    acc = 0.0
    for sd in seeds:
        R, _ = L.dmm(Xn, sub, counts * scale, max(1, min(k, X.shape[0])), seed=sd)
        W = R[obs]
        prof = (W.T @ T[obs] + prior * g) / (W.sum(0)[:, None] + prior)
        acc = acc + R @ prof
    out = np.full_like(X, np.nan)
    out[:, tgt_sl] = acc / len(seeds)
    return out


def complete(sv, t, tool, K, r):
    st = t["stem"]
    if st not in sv["keys"]:
        return None, "question not in training pool"
    country = t["country"]
    tool, tn, params = parse_tool(tool)
    nb = ((neighbours_tp(sv, t, K) if tn == "tp" else neighbours_tn(sv, t, K)) if tn else L.neighbours(sv, t["text"], st, K)) if K else []
    X, rows, cols = L.local_matrix(sv, [s for s, _ in nb], (st,))
    sl = cols[st]
    same = np.array([c[1] == country for c in rows])
    X[same, sl] = np.nan  # no answers to the target question from the target's own country
    other_obs = (~np.isnan(X[:, sl.start])).sum()
    if other_obs < MIN_OTHER:
        return None, "fewer than 3 other-country groups answered the question"
    if t["split"] == "Pop":
        tgt = [i for i, c in enumerate(rows) if c[1] == country and c[2]]
    else:
        tgt = [i for i, c in enumerate(rows) if c == t["cell"]]
    if not tgt:
        return None, "target group has no answers on neighbour questions"
    if tool == "mean":
        # baseline: same attribute cell in other countries (Grouped) / all other-country cells (Pop), no factors
        attrs = rows[tgt[0]][2] if t["split"] != "Pop" else None
        pick = [i for i, c in enumerate(rows) if not same[i] and not np.isnan(X[i, sl.start]) and (attrs is None or c[2] == attrs)]
        if not pick:
            pick = [i for i in range(len(rows)) if not same[i] and not np.isnan(X[i, sl.start])]
        fitted = np.full_like(X, np.nan)
        fitted[tgt] = np.nanmean(X[pick], axis=0)
    elif tool == "knn":
        # nearest groups: the r other-country groups whose answers on the neighbour questions are closest to the target
        # group's; their answers to the target question, distance-weighted, shrunk toward the other-country mean
        others = [i for i in range(len(rows)) if not same[i] and not np.isnan(X[i, sl.start])]
        nb_sl = [c for st2, c in cols.items() if c != sl]
        g = np.nanmean(X[others][:, sl], axis=0)
        fitted = np.full_like(X, np.nan)
        for ti in tgt:
            ds_ = []
            for i in others:
                d = [0.5 * np.abs(X[ti, c] - X[i, c]).sum() for c in nb_sl if not np.isnan(X[ti, c.start]) and not np.isnan(X[i, c.start])]
                if len(d) >= 2:
                    ds_.append((float(np.mean(d)), i))
            if not ds_:
                fitted[ti, sl] = g
                continue
            ds_.sort()
            near = ds_[:max(1, r)]
            tau = np.median([d for d, _ in near]) + 1e-6
            w = np.array([np.exp(-d / tau) for d, _ in near])
            fitted[ti, sl] = (sum(wi * X[i, sl] for wi, (_, i) in zip(w, near)) + 0.5 * g) / (w.sum() + 0.5)
    elif tool.startswith("seg"):
        counts = np.array([min(max(sv["size"].get(c, 100), 30), 1000) for c in rows], float)
        if params:  # seg:scale:prior:temp, averaged over 3 seeds
            fitted = segments(X, cols, counts, r, sl, params[0], params[1], seeds=(0, 1, 2))
            fitted[:, sl] = np.power(np.clip(fitted[:, sl], 1e-9, None), params[2])
        else:
            fitted = segments(X, cols, counts, r, sl, 0.01 if tool == "segsoft" else 0.05)
    elif tool in L.CL_TOOLS:
        # segments: mixture over cells' answer profiles; target question's per-segment profile from other countries only
        counts = np.array([min(max(sv["size"].get(c, 100), 30), 1000) for c in rows])
        fitted = L.fit_cl(X, cols, counts, tool, r)[0]
    else:
        fitted = L.fit_dr(X, tool, r)[0]
    keys = sv["keys"][st]
    order = [keys.index(k) for k in t["q"]["keys"]] if set(keys) == set(t["q"]["keys"]) else None
    if order is None:
        return None, "option keys differ"
    if t["split"] == "Pop":
        by_attr = defaultdict(list)
        for i in tgt:
            v = np.clip(fitted[i, sl], 0, None)
            if v.sum() > 0:
                by_attr[rows[i][2][0][0]].append((sv["size"].get(rows[i], 1.0) or 1.0, v / v.sum()))
        if not by_attr:
            return None, "no usable cells"
        p = np.mean([sum(w * v for w, v in a) / sum(w for w, _ in a) for a in by_attr.values()], axis=0)
    else:
        p = np.clip(fitted[tgt[0], sl], 0, None)
        if p.sum() <= 0:
            return None, "degenerate"
    p = p[order]
    return p / p.sum(), "ok"


def complete_px(sv, t, tool, K, r, n_proxy=3):
    """complete(); if the target question has no cross-national answers, use up to n_proxy most similar questions with
    the same answer options that other countries were asked (target-question answers are never involved)."""
    p, why = complete(sv, t, tool, K, r)
    if p is not None or why not in ("question not in training pool", "fewer than 3 other-country groups answered the question"):
        return p, why
    lab = t.get("labels") or []
    if not lab or not all(lab):
        return None, why + " (no labels for proxy)"
    sims = (sv["S_mat"] @ sv["vec"].transform([t["text"]]).T).toarray().ravel()
    got = []
    for i in np.argsort(-sims):
        s2 = sv["stems"][i]
        if s2 == t["stem"]:
            continue
        l2 = sv["labels"].get(s2, [])
        if len(l2) != len(lab) or not all(x in l2 for x in lab):
            continue
        t2 = dict(t, stem=s2, text=s2, q=dict(t["q"], keys=sv["keys"][s2]))
        p2, w2 = complete(sv, t2, tool, K, r)
        if p2 is None:
            continue
        got.append((max(float(sims[i]), 0.01), p2[[l2.index(x) for x in lab]]))
        if len(got) >= n_proxy:
            break
    if not got:
        return None, why + " (no proxy question)"
    p = sum(w * v for w, v in got) / sum(w for w, _ in got)
    return p / p.sum(), "proxy"


def main():
    sv = L.build_surveys(L.held_rows())
    sets = {w: L.targets(w) for w in ("dev", "eval")}
    if any(c[0].endswith("_tp") for c in ONLY):
        from human_sim import simbench_ablate as A
        for w in sets:
            sample, _, ctx = A.build_env(25, 100, 7, w)
            ctx["dpool"] = A._build_dpool(A.load_split("Pop"), A.load_split("Grouped"), 25, 100, 7)
            ctx["_target_stems"] = [(r["dataset_name"], A._stem(r["input_template"])) for _, r in sample.iterrows()]
            tm = A._topics(ctx)  # the same topic clusters D3 retrieves from (cached embeddings)
            for t in sets[w]:
                t["topic_map"] = tm
    out = pd.read_pickle(OUT) if (OUT.exists() and ("--cl" in sys.argv or "--seg" in sys.argv or EXTRA)) else {"why": {}}
    for cfg in ONLY:
        res = {}
        for w in sets:
            for t in sets[w]:
                if cfg[0].endswith("+px"):
                    p, why = complete_px(sv[t["q"]["dataset"]], t, cfg[0][:-3], cfg[1], cfg[2])
                else:
                    p, why = complete(sv[t["q"]["dataset"]], t, *cfg)
                res[t["q"]["qid"]] = p
                out.setdefault(("why", cfg), {})[t["q"]["qid"]] = why
                if cfg == CFGS[0] and len(ONLY) == len(CFGS):
                    out["why"][t["q"]["qid"]] = why
        out[cfg] = res
        ev = [t for t in sets["eval"] if res[t["q"]["qid"]] is not None]
        dv = [t for t in sets["dev"] if res[t["q"]["qid"]] is not None]
        sharp = lambda t: t["q"]["h"].max() >= 0.7  # noqa: E731  (diagnostic split only)
        div = lambda t: t["q"]["Hn"] >= 0.84  # noqa: E731
        s = lambda ts: np.mean([L.S(t["q"], res[t["q"]["qid"]]) for t in ts]) if ts else float("nan")  # noqa: E731
        print(f"{str(cfg):18s} coverage dev {len(dv)}/{len(sets['dev'])} eval {len(ev)}/{len(sets['eval'])}; "
              f"dev S {s(dv):.1f} (sharp {s([t for t in dv if sharp(t)]):.1f}); eval S {s(ev):.1f} (sharp {s([t for t in ev if sharp(t)]):.1f})"
              f" | divided: dev {s([t for t in dv if div(t)]):.1f} eval {s([t for t in ev if div(t)]):.1f}", flush=True)
    pd.to_pickle(out, OUT)
    print(pd.Series(out["why"]).value_counts())


if __name__ == "__main__":
    main()
