"""Layer 1: what structure does each question have? (no model calls)

Modality labels use the real answers: diagnostic only, never routing. The bucket classifier uses only pre-answer
features (question metadata + the retr6 demos), fit on dev and scored on eval."""

from __future__ import annotations

import json
from collections import Counter

import diptest
import numpy as np
import pandas as pd
from scipy.signal import find_peaks
from scipy.stats import kurtosis, skew
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

from human_sim import simbench_ablate as A
from human_sim import simbench_mass_levers as M
from human_sim.simbench_divided_anatomy import option_roles, parse_options

PROMINENCE, DIP_ALPHA, NARROW_SD, N_CAP = 0.05, 0.05, 0.20, 5000
BANDS = ("consensus", "mixed", "divided")
LABELS = ("unimodal-narrow", "unimodal-wide", "multimodal", "binary/3-option", "categorical")


def band(hn):
    return "consensus" if hn < 0.65 else ("mixed" if hn < M.DIV else "divided")


def n_peaks(m):
    pk, _ = find_peaks(np.r_[0.0, m, 0.0], prominence=PROMINENCE)
    return len(pk)


def pseudo_sample(m, n):
    """Expand a distribution to n pseudo-respondents; even jitter inside each option avoids ties."""
    counts = np.round(np.asarray(m) * n).astype(int)
    return np.concatenate([j + (np.arange(c) + 0.5) / c - 0.5 for j, c in enumerate(counts) if c > 0])


def ordinal_parts(keys, roles, h):
    parts = M._ord_parts(roles, keys)
    if not parts:
        return None
    idx, pos = parts
    m = np.asarray(h)[idx]
    return (m / m.sum(), pos) if m.sum() > 0 else None


def modality(keys, roles, h, n_resp):
    subs = len(roles["subs"]) if "subs" in roles else len(keys)
    out = {"n_sub": subs}
    op = ordinal_parts(keys, roles, h)
    if subs <= 3:
        out["label"] = "binary/3-option"
        return out
    if op is None:
        out["label"] = "categorical"
        return out
    m, pos = op
    mu = float((m * pos).sum())
    sd = float(np.sqrt((m * (pos - mu) ** 2).sum()))
    x = pseudo_sample(m, int(min(max(n_resp, 30), N_CAP)))
    dip, p = diptest.diptest(x)
    n = len(x)
    bc = (skew(x, bias=False) ** 2 + 1) / (kurtosis(x, bias=False) + 3 * (n - 1) ** 2 / ((n - 2) * (n - 3)))
    pk = n_peaks(m)
    out.update(peaks=pk, dip=float(dip), dip_p=float(p), bc=float(bc), sd=sd, N_used=int(min(max(n_resp, 30), N_CAP)))
    out["label"] = "multimodal" if (pk >= 2 and p < DIP_ALPHA) else ("unimodal-narrow" if sd < NARROW_SD else "unimodal-wide")
    return out


def demo_features(demos):
    """Pre-answer features of the 6 retrieved demos (their own real answers, never the target's)."""
    ents, multi, reps = [], [], []
    for d in demos:
        keys = list(d["human_answer"])
        tot = sum(d["human_answer"].values()) or 1.0
        h = np.array([d["human_answer"][k] / tot for k in keys])
        roles = option_roles(keys, parse_options(d["input_template"]), "")
        ents.append(M.Hn(h))
        op = ordinal_parts(keys, roles, h)
        if op is not None and len(op[0]) >= 4:
            multi.append(float(n_peaks(op[0]) >= 2))
            m, pos = op
            mu = float((m * pos).sum())
            reps.append([mu, float(np.sqrt((m * (pos - mu) ** 2).sum())), M.Hn(h), h.max()])
        else:
            reps.append([np.nan, np.nan, M.Hn(h), h.max()])
    R = np.array(reps, float)
    spread = np.nanmean([np.nansum(np.abs(R[i] - R[j])) for i in range(len(R)) for j in range(i + 1, len(R))]) if len(R) > 1 else 0.0
    return {"demo_mean_entropy": float(np.mean(ents)) if ents else np.nan,
            "demo_share_multimodal": float(np.mean(multi)) if multi else 0.0,
            "demo_spread": float(spread), "n_demos": len(demos)}


def rows_for(which, topic_of):
    sample, _, ctx = A.build_env(25, 100, 7, which)
    out = []
    for q in M.load(which):
        r = sample.loc[q["i"]]
        mod = modality(q["keys"], q["roles"], q["h"], float(r.get("group_size", 0) or 0))
        demos = A._rank_by_similarity(r, A._demo_pool(r, ctx), ctx)[:6]
        out.append({"set": which, "qid": q["qid"], "i": q["i"], "dataset": q["dataset"], "split": q["split"],
                    "group3": q["group3"], "format": q["format"], "n_options": q["n_options"],
                    "value_laden": float(q["value_laden"]), "Hn": q["Hn"], "band": band(q["Hn"]),
                    "topic": topic_of(A._stem(q["question"])), **mod, **demo_features(demos)})
    return pd.DataFrame(out)


def ci_auc(y, s, n=2000):
    rng = np.random.default_rng(0)
    vals = []
    for _ in range(n):
        idx = rng.integers(0, len(y), len(y))
        if len(set(y[idx])) == 2:
            vals.append(roc_auc_score(y[idx], s[idx]))
    vals = np.sort(vals)
    return round(float(vals[int(0.025 * len(vals))]), 3), round(float(vals[int(0.975 * len(vals)) - 1]), 3)


def crosstab(df):
    out = {}
    for grp, d in [("all", df), ("shared_survey", df[df.group3 == "shared_survey"]),
                   ("other_pop_only", df[df.group3 == "other_pop_only"]), ("pop_only_task", df[df.group3 == "pop_only_task"])]:
        t = {}
        for b in BANDS:
            db = d[d.band == b]
            t[b] = {lab: {"N": int((db.label == lab).sum()), "pct": round(100 * float((db.label == lab).mean()), 1) if len(db) else 0.0}
                    for lab in LABELS}
            t[b]["N_total"] = int(len(db))
        out[grp] = t
    return out


def main():
    full = pd.concat([A.load_split("Pop"), A.load_split("Grouped")])
    stems = sorted({A._stem(t) for t in full.input_template})
    vec = TfidfVectorizer(stop_words="english", min_df=2)
    X = vec.fit_transform(stems)
    km = KMeans(n_clusters=20, n_init=10, random_state=0).fit(X)
    lut = dict(zip(stems, km.labels_))
    topic_of = lambda s: int(lut.get(s, km.predict(vec.transform([s]))[0]))  # noqa: E731

    df = pd.concat([rows_for("eval", topic_of), rows_for("dev", topic_of)], ignore_index=True)
    df.to_pickle(M.OUT / "structure_l1_rows.pkl")
    ev, dv = df[df.set == "eval"], df[df.set == "dev"]
    rep = {"rule": {"prominence": PROMINENCE, "dip_alpha": DIP_ALPHA, "narrow_sd": NARROW_SD, "N_cap": N_CAP,
                    "multimodal": "peaks >= 2 AND dip p < 0.05", "ordinal": ">= 4 substantive options, DK excluded"},
           "crosstab_eval": crosstab(ev), "crosstab_dev": crosstab(dv)}

    print("== Layer 1 cross-tab (eval): band x structure, N (%)")
    for grp in ("all", "shared_survey", "other_pop_only", "pop_only_task"):
        t = rep["crosstab_eval"][grp]
        print(f"-- {grp}")
        print(f"{'band':10s}" + "".join(f"{lab:>19s}" for lab in LABELS) + f"{'total':>7s}")
        for b in BANDS:
            print(f"{b:10s}" + "".join(f"{t[b][lab]['N']:>10d} ({t[b][lab]['pct']:4.1f}%)" for lab in LABELS) + f"{t[b]['N_total']:>7d}")

    both = df[df.label.isin(("unimodal-narrow", "unimodal-wide", "multimodal"))]
    div = both[both.band == "divided"]
    cons = both[both.band == "consensus"]
    hyp = {"divided_ordinal_N": int(len(div)), "divided_multimodal_share": float((div.label == "multimodal").mean()),
           "divided_unimodal_wide_share": float((div.label == "unimodal-wide").mean()),
           "consensus_ordinal_N": int(len(cons)), "consensus_unimodal_narrow_share": float((cons.label == "unimodal-narrow").mean())}
    sens = {}
    for sd_t in (0.15, 0.20, 0.25):
        lab = np.where((both.peaks >= 2) & (both.dip_p < DIP_ALPHA), "multimodal", np.where(both.sd < sd_t, "narrow", "wide"))
        sens[f"narrow_sd<{sd_t}"] = {"consensus_narrow_share": float((lab[both.band.values == "consensus"] == "narrow").mean()),
                                     "divided_wide_share": float((lab[both.band.values == "divided"] == "wide").mean())}
    sens["divided_multimodal_share_peaks_only"] = float((div.peaks >= 2).mean())
    sens["divided_multimodal_share_bc>0.555"] = float((div.bc > 0.555).mean())
    sens["divided_multimodal_share_dip_only"] = float((div.dip_p < DIP_ALPHA).mean())
    rep["hypothesis"], rep["sensitivity"] = hyp, sens
    print("\n== hypothesis check (eval + dev, ordinal >= 4 options):", {k: round(v, 3) if isinstance(v, float) else v for k, v in hyp.items()})
    print("   sensitivity:", {k: (round(v, 3) if isinstance(v, float) else {a: round(b, 3) for a, b in v.items()}) for k, v in sens.items()})

    # 3.3 can the bucket be predicted before the answer? multimodal (clustering bucket) vs unimodal
    feats_num = ["n_options", "value_laden", "demo_mean_entropy", "demo_share_multimodal", "demo_spread"]
    datasets = sorted(df.dataset.unique())

    def design(d):
        Xn = d[feats_num].fillna(d[feats_num].mean()).values
        Xd = np.array([[float(x == ds) for ds in datasets] for x in d.dataset])
        Xt = np.array([[float(t == k) for k in range(20)] for t in d.topic])
        return np.c_[Xn, Xd, Xt]

    out = {}
    for name, sub in {"clustering_vs_dimred (ordinal>=4)": both,
                      "consensus_vs_rest (all, context)": df}.items():
        y_fn = (lambda d: (d.label == "multimodal").astype(int).values) if "clustering" in name else (lambda d: (d.band == "consensus").astype(int).values)
        tr, te = sub[sub.set == "dev"], sub[sub.set == "eval"]
        if len(set(y_fn(tr))) < 2 or len(set(y_fn(te))) < 2:
            out[name] = {"note": "one class only"}
            continue
        sc = StandardScaler().fit(design(tr))
        clf = LogisticRegression(C=0.5, max_iter=5000).fit(sc.transform(design(tr)), y_fn(tr))
        s = clf.predict_proba(sc.transform(design(te)))[:, 1]
        y = y_fn(te)
        auc = roc_auc_score(y, s)
        out[name] = {"N_dev": int(len(tr)), "N_eval": int(len(te)), "positives_eval": int(y.sum()), "AUC_eval": float(auc), "CI": ci_auc(y, s)}
        print(f"\n== classifier {name}: dev N {len(tr)}, eval N {len(te)} ({int(y.sum())} positive): AUC {auc:.3f} {ci_auc(y, s)}")
    rep["classifier"] = out
    rep["counts"] = {"eval": dict(Counter(ev.label)), "dev": dict(Counter(dv.label))}
    (M.OUT / "structure_l1_report.json").write_text(json.dumps(rep, indent=2, default=float))


if __name__ == "__main__":
    main()
