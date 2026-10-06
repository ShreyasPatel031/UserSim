"""New interpretable sources for the lowest full-benchmark brackets (no model calls). Output: newsources_full.pkl
{qid: {source key: prediction in the question's key order}} + newsources_report.json.

others_dd   (TISP, GlobalOpinionQA, ConspiracyCorr, OSPsych*, MoralMachine*): two-way decomposition for country questions.
            question level = mean of OTHER countries' answers to q; country offset = mean over this country's answers to
            OTHER questions of the same dataset with the same answer labels of [its answer - other countries' mean].
            Only this country's answers to different questions are used (never to q).
ng_sib      (NumberGame): people shown the SAME example numbers rated other target numbers (different questions). For the
            target y, a kernel over targets (shared membership in the rules consistent with the examples, weighted by the
            size-principle posterior, plus numeric closeness) averages those ratings; fed with the Bayesian rule features
            into a cross-fitted logistic model.
c13_v2      (Choices13k): richer gamble features (chance A pays more than B, stochastic dominance, EV of the paid bonus with
            losses truncated at $0, chance of the best outcome, outcome counts, prospect-theory values at several
            curvatures) in a cross-fitted logistic model; c13_v2_gbm = same features in gradient boosting."""

from __future__ import annotations

import json
import re
from collections import defaultdict

import numpy as np
import pandas as pd
from sklearn.model_selection import KFold

from human_sim import simbench_ablate as A
from human_sim import simbench_cogmodels as C
from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_l3 as L
from human_sim.simbench_divided_anatomy import parse_options
from human_sim.simbench_structure_othersets import DATASETS as OTHS
from human_sim.simbench_structure_othersets import country

OUTF = M.OUT / "newsources_full.pkl"


def S(q, p):
    return 100 * (1 - M.tvd(np.asarray(p), q["h"]) / q["norm"])


# ---------------------------------------------------------------- others_dd
def others_dd(sample, qs, lam=1.0):
    obs = {}  # (dataset, template) -> {country: vector in key order of the row}
    labs = {}
    for _, r in sample.iterrows():
        if r.dataset_name in OTHS:
            keys = list(r.human_answer)
            tot = sum(r.human_answer.values()) or 1.0
            obs.setdefault((r.dataset_name, r.input_template), {})[country(r.group_prompt_variable_map)] = (keys, np.array([r.human_answer[k] / tot for k in keys]))
            t = parse_options(r.input_template)
            labs[(r.dataset_name, r.input_template)] = (tuple(keys), tuple(L.norm_label(t.get(k, "")) for k in keys))
    by_lab = defaultdict(list)
    for k, v in labs.items():
        by_lab[(k[0], v)].append(k[1])
    out, info = {}, {}
    for q in qs:
        if q["dataset"] not in OTHS:
            continue
        r = sample.loc[q["i"]]
        c, key = country(r.group_prompt_variable_map), (q["dataset"], r.input_template)
        oth = [v for cc, (_, v) in obs.get(key, {}).items() if cc != c]
        if not oth:
            continue
        keys = obs[key][next(iter(obs[key]))][0]
        Q = np.mean(oth, axis=0)
        gaps = []
        for t2 in by_lab[(q["dataset"], labs[key])]:
            if t2 == r.input_template or c not in obs[(q["dataset"], t2)]:
                continue
            o2 = [v for cc, (_, v) in obs[(q["dataset"], t2)].items() if cc != c]
            if o2:
                gaps.append(obs[(q["dataset"], t2)][c][1] - np.mean(o2, axis=0))
        G = np.mean(gaps, axis=0) if gaps else np.zeros_like(Q)
        p = np.clip(Q + lam * G, 1e-4, None)
        p = p[[keys.index(k) for k in q["keys"]]]
        out[q["qid"]] = p / p.sum()
        info[q["qid"]] = len(gaps)
    return out, info


# ---------------------------------------------------------------- NumberGame with sibling targets
def ng_kernel(ex, y, y2):
    n = len(ex)
    num, den = 0.0, 0.0
    for h in C.HYP.values():
        if all(e in h for e in ex):
            w = (1 / len(h)) ** n
            den += w
            num += w * ((y in h) == (y2 in h))
    rule_sim = num / den if den else 0.0
    return 0.5 * rule_sim + 0.5 * np.exp(-abs(y - y2) / 10)


FAMILIES = ("even", "odd", "multiples", "mod", "contains", "ends", "decade", "squares", "powers", "primes", "cubes", "digit")


def ng_split(ex, y):
    """P(target fits) under rules only and under intervals only, plus posterior mass of each rule family."""
    n = len(ex)
    rn = rd = 0.0
    fam = dict.fromkeys(FAMILIES, 0.0)
    for name, h in C.HYP.items():
        if all(e in h for e in ex):
            w = (1 / len(h)) ** n
            rd += w
            rn += w * (y in h)
            for f in FAMILIES:
                if f in name:
                    fam[f] += w
    lo, hi = min(ex), max(ex)
    inum = iden = 0.0
    for a in range(1, lo + 1):
        for b in range(hi, 101):
            w = (1 / (b - a + 1)) ** n
            iden += w
            inum += w * (a <= y <= b)
    lg = lambda p: float(np.log(np.clip(p, 1e-4, 1 - 1e-4) / np.clip(1 - p, 1e-4, 1)))  # noqa: E731
    pr = rn / rd if rd else 0.5
    return [lg(pr), lg(inum / iden if iden else 0.5), float(rd > 0)] + [fam[f] / rd if rd else 0.0 for f in FAMILIES]


def ng_features(sample, qs):
    rows = []
    for q in qs:
        t = sample.loc[q["i"]].input_template
        f, meta = C.number_features(t)
        if f is None:
            continue
        rows.append((q, f, meta, C.NUMS.search(t).group(1)))
    by_ex = defaultdict(list)
    for j, (q, f, meta, e) in enumerate(rows):
        by_ex[e].append(j)
    X = []
    for j, (q, f, meta, e) in enumerate(rows):
        sib = [k for k in by_ex[e] if k != j]
        if sib:
            ks = np.array([ng_kernel(meta["examples"], meta["target"], rows[k][2]["target"]) for k in sib])
            ys = np.array([rows[k][0]["h"][rows[k][0]["keys"].index("A")] for k in sib])
            kern = float((ks * ys).sum() / ks.sum())
            mean = float(ys.mean())
            near = float(ys[np.argmax(ks)])
        else:
            kern = mean = near = 0.5
        X.append(f + [kern, mean, near, float(bool(sib)), len(sib)] + ng_split(meta["examples"], meta["target"]))
    return rows, X


# ---------------------------------------------------------------- Choices13k richer features
def c13_features(text):
    g = {m.group(1): [(float(x), float(p) / 100) for x, p in C.OUTCOME.findall(m.group(2))] for m in C.GAMBLE.finditer(text)}
    if "A" not in g or "B" not in g:
        return None
    base = C.gamble_features(text)
    A_, B_ = [(x, p) for x, p in g["A"] if p > 0], [(x, p) for x, p in g["B"] if p > 0]
    pa_better = sum(pa * pb for xa, pa in A_ for xb, pb in B_ if xa > xb)
    pb_better = sum(pa * pb for xa, pa in A_ for xb, pb in B_ if xb > xa)
    xs = sorted({x for x, _ in A_ + B_})
    cdf = lambda G, v: sum(p for x, p in G if x <= v)  # noqa: E731
    domA = float(all(cdf(A_, v) <= cdf(B_, v) + 1e-9 for v in xs))
    domB = float(all(cdf(B_, v) <= cdf(A_, v) + 1e-9 for v in xs))
    trunc = lambda G: sum(max(x, 0) * p for x, p in G)  # noqa: E731
    ta, tb = trunc(A_), trunc(B_)
    pbest = lambda G: sum(p for x, p in G if x == max(xx for xx, _ in G))  # noqa: E731
    sc = abs(ta) + abs(tb) + 1
    f = base + [pa_better - pb_better, domA - domB, (ta - tb) / sc, pbest(A_) - pbest(B_), len(A_) - len(B_)]
    for a in (0.5, 0.7, 1.0):
        va, vb = C.pt_value(A_, a=a), C.pt_value(B_, a=a)
        f.append((va - vb) / (abs(va) + abs(vb) + 1))
    return f


# ---------------------------------------------------------------- GlobalOpinionQA similar questions
def goqa_knn(sample, qs, K=10):
    """answers to the K most similar OTHER GlobalOpinionQA questions with the same answer labels (TF-IDF on the question
    text); same-country answers get double weight. Never the target question itself (identical text excluded)."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    d = sample[sample.dataset_name == "GlobalOpinionQA"]
    rows = []
    for i, r in d.iterrows():
        keys = list(r.human_answer)
        tot = sum(r.human_answer.values()) or 1.0
        t = parse_options(r.input_template)
        rows.append((i, A._stem(r.input_template), tuple(L.norm_label(t.get(k, "")) for k in keys), country(r.group_prompt_variable_map), keys, np.array([r.human_answer[k] / tot for k in keys])))
    vec = TfidfVectorizer(stop_words="english").fit([r[1] for r in rows])
    X = vec.transform([r[1] for r in rows])
    pos = {r[0]: j for j, r in enumerate(rows)}
    out, sims = {}, {}
    for q in qs:
        if q["dataset"] != "GlobalOpinionQA" or q["i"] not in pos:
            continue
        j = pos[q["i"]]
        _, st, labs, c, keys, _ = rows[j]
        sim = (X @ X[j].T).toarray().ravel()
        cand = [k for k in np.argsort(-sim) if rows[k][1] != st and rows[k][2] == labs and all(labs)][:K]
        if not cand:
            continue
        w = np.array([max(sim[k], 0.01) * (2.0 if rows[k][3] == c else 1.0) for k in cand])
        p = (w[:, None] * np.array([rows[k][5] for k in cand])).sum(0) / w.sum()
        p = p[[keys.index(k) for k in q["keys"]]]
        out[q["qid"]] = p / p.sum()
        sims[q["qid"]] = float(sim[cand[0]])
    return out, sims


# ---------------------------------------------------------------- ChaosNLI text cues
NEG = re.compile(r"\b(not|no|never|nobody|nothing|none|n't|cannot)\b")
HEDGE = re.compile(r"\b(some|may|might|could|probably|possibly|sometimes|often|likely)\b")


def chaos_features(text, plain, keys):
    ctx = text.split("Statement:")[0].replace("Context:", "").lower()
    stm = text.split("Statement:")[1].split("Choose the correct")[0].lower() if "Statement:" in text else ""
    cw, sw = set(re.findall(r"[a-z']+", ctx)), set(re.findall(r"[a-z']+", stm))
    ov = len(cw & sw) / max(len(sw), 1)
    p = {k: v for k, v in zip(keys, np.asarray(plain) / np.sum(plain))}
    return [ov, len(sw) / max(len(cw), 1), float(bool(NEG.search(stm))) - float(bool(NEG.search(ctx))) * 0.5, float(bool(HEDGE.search(stm))),
            np.log(p.get("A", 1e-3) + 1e-3), np.log(p.get("B", 1e-3) + 1e-3), np.log(p.get("C", 1e-3) + 1e-3)]


def chaos_lr(sample, qs):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    cs = [q for q in qs if q["dataset"] == "ChaosNLI" and sorted(q["keys"]) == ["A", "B", "C"]]
    X = np.array([chaos_features(sample.loc[q["i"]].input_template, q["preds"]["plain"], q["keys"]) for q in cs])
    H = np.array([[q["h"][q["keys"].index(k)] for k in "ABC"] for q in cs])
    P = np.zeros_like(H)
    for tr, te in KFold(5, shuffle=True, random_state=0).split(X):
        sc = StandardScaler().fit(X[tr])
        Xr = np.vstack([sc.transform(X[tr])] * 3)
        yr = np.repeat([0, 1, 2], len(tr))
        wr = np.concatenate([H[tr, 0], H[tr, 1], H[tr, 2]])
        m = LogisticRegression(C=1.0, max_iter=5000).fit(Xr, yr, sample_weight=wr)
        P[te] = m.predict_proba(sc.transform(X[te]))
    return {q["qid"]: np.array([P[j]["ABC".index(k)] for k in q["keys"]]) for j, q in enumerate(cs)}


def crossfit(X, y, gbm=False):
    C.GBM = gbm
    p = np.zeros(len(X))
    for tr, te in KFold(5, shuffle=True, random_state=0).split(X):
        p[te], _ = C.fit_predict([X[i] for i in tr], [y[i] for i in tr], [X[i] for i in te])
    C.GBM = False
    return p


def main():
    sample, _, _ = A.build_env(25, 100, 7, "full")
    M.EVAL_ARMS = M.DEV_ARMS = {"plain": ("retr6_rev2", M.HAIKU)}
    qs = [q for q in M.load("full") if "plain" in q["preds"]]
    out = pd.read_pickle(OUTF) if OUTF.exists() else {}
    rep = {}

    pd_, info = others_dd(sample, qs)
    for qid, p in pd_.items():
        out.setdefault(qid, {})["others_dd"] = p
    for ds in OTHS:
        sel = [q for q in qs if q["dataset"] == ds and q["qid"] in pd_]
        if sel:
            rep[f"others_dd {ds}"] = {"N": len(sel), "with_offset": sum(info[q["qid"]] > 0 for q in sel), "S": float(np.mean([S(q, pd_[q["qid"]]) for q in sel]))}
            print(f"others_dd {ds:20s} N {len(sel):4d} with an offset {rep[f'others_dd {ds}']['with_offset']:4d}  S {rep[f'others_dd {ds}']['S']:.1f}", flush=True)

    rows, X = ng_features(sample, [q for q in qs if q["dataset"] == "NumberGame"])
    y = [q["h"][q["keys"].index("A")] for q, *_ in rows]
    for gbm, k in ((False, "ng_sib2"),):
        p = crossfit(X, y, gbm)
        for (q, *_), a in zip(rows, p):
            out.setdefault(q["qid"], {})[k] = np.array([a, 1 - a]) if q["keys"] == ["A", "B"] else np.array([1 - a, a])
        rep[k] = float(np.mean([S(q, out[q["qid"]][k]) for q, *_ in rows]))
        print(f"{k}: NumberGame N {len(rows)} S {rep[k]:.1f}", flush=True)

    qc = [q for q in qs if q["dataset"] == "Choices13k"]
    Xc, qq = [], []
    for q in qc:
        f = c13_features(sample.loc[q["i"]].input_template)
        if f is not None:
            Xc.append(f); qq.append(q)
    yc = [q["h"][q["keys"].index("A")] for q in qq]
    for gbm, k in ((False, "c13_v2"), (True, "c13_v2_gbm")):
        p = crossfit(Xc, yc, gbm)
        for q, a in zip(qq, p):
            out.setdefault(q["qid"], {})[k] = np.array([a, 1 - a]) if q["keys"] == ["A", "B"] else np.array([1 - a, a])
        rep[k] = float(np.mean([S(q, out[q["qid"]][k]) for q in qq]))
        print(f"{k}: Choices13k N {len(qq)} S {rep[k]:.1f}", flush=True)

    gk, sims = goqa_knn(sample, qs)
    for qid, p in gk.items():
        out.setdefault(qid, {})["goqa_knn"] = p
    sel = [q for q in qs if q["qid"] in gk]
    rep["goqa_knn"] = {"N": len(sel), "S": float(np.mean([S(q, gk[q["qid"]]) for q in sel])), "near_duplicates_sim_gt_0.9": sum(v > 0.9 for v in sims.values())}
    print("goqa_knn", rep["goqa_knn"], "plain", np.mean([S(q, q["preds"]["plain"]) for q in sel]), flush=True)
    ch = chaos_lr(sample, qs)
    for qid, p in ch.items():
        out.setdefault(qid, {})["chaos_lr"] = p
    sel = [q for q in qs if q["qid"] in ch]
    rep["chaos_lr"] = {"N": len(sel), "S": float(np.mean([S(q, ch[q["qid"]]) for q in sel]))}
    print("chaos_lr", rep["chaos_lr"], "plain", np.mean([S(q, q["preds"]["plain"]) for q in sel]), flush=True)

    pd.to_pickle(out, OUTF)
    rp = M.OUT / "newsources_report.json"
    old = json.loads(rp.read_text()) if rp.exists() else {}
    old.update(rep)
    rp.write_text(json.dumps(old, indent=2))


if __name__ == "__main__":
    main()
