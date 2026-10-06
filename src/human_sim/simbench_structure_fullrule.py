"""Final pick-one rule on the FULL benchmark (13,510 questions), no model calls.

  sharp-routed question  : two-way decomposition with the group gap from other countries (dd3) if it exists, else the
                           plain model answer (retr6_rev2), each with its own dev-fitted exponent
  shallow-routed question: two-way decomposition (dd2: gap from other countries, else from similar questions) if it
                           exists, else retr6_rev2, each with its own dev-fitted exponent
  router                 : dev-trained P(top answer >= 70%) on question metadata + retrieved-demo features (as in the
                           earlier full run), cut chosen on dev by balanced accuracy
Overlap rule: no answer to the target question from any group that may contain the target's respondents. On the full
benchmark the pool holds every Grouped row; the target's own row is never used (only disjoint same-country groups for
the country level, other countries for the group gap). Outside the 5 shared surveys the answer is retr6_rev2 unchanged.
Reports the whole benchmark first, then slices."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler

from human_sim import simbench_ablate as A
from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_l3 as L
from human_sim import simbench_structure_twoway as TW
from human_sim.simbench_structure_full import design, features, topic_model
from human_sim.simbench_structure_sharp import ci
from human_sim.simbench_structure_sharpdef import sub_shares

OUT = M.OUT / "structure_fullrule_preds.pkl"
TEMPS = (0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0)
NUM = ["n_options", "value_laden", "demo_mean_entropy", "demo_share_multimodal", "demo_spread"]


def temper(p, t):
    r = np.power(np.clip(np.asarray(p, float), 1e-9, None), t)
    return r / r.sum()


def S(q, p):
    return 100 * (1 - M.tvd(p, q["h"]) / q["norm"])


def loo_priors(sample):
    """Label prior sums over every full-benchmark row (by dataset + normalised answer labels, else dataset + option
    count). The target's OWN row is subtracted when used (leave-one-out), so its answer never enters its prior."""
    from collections import defaultdict
    from human_sim.simbench_divided_anatomy import parse_options
    lab, pos = defaultdict(lambda: [0.0, 0]), defaultdict(lambda: [0.0, 0])
    own = {}
    for i, r in sample.iterrows():
        keys = list(r.human_answer)
        tot = sum(r.human_answer.values()) or 1.0
        v = np.array([r.human_answer[k] / tot for k in keys])
        texts = parse_options(r.input_template)
        labs = tuple(L.norm_label(texts.get(k, "")) for k in keys)
        kl = (r.dataset_name, labs) if all(labs) else None
        kp = (r.dataset_name, len(keys))
        for key, store in ((kl, lab), (kp, pos)):
            if key is not None:
                store[key][0] = store[key][0] + v
                store[key][1] += 1
        own[i] = (kl, kp, v)
    return lab, pos, own


def prior_loo(i, lab, pos, own):
    kl, kp, v = own[i]
    for key, store in ((kl, lab), (kp, pos)):
        if key is not None and store[key][1] - 1 >= 5:
            return (store[key][0] - v) / (store[key][1] - 1)
    return None


def decomposition_preds(targets, sv):
    out = {}
    for i, t in enumerate(targets):
        s = sv[t["q"]["dataset"]]
        out[t["q"]["qid"]] = {"dd3": TW.predict(s, {}, t, 1.0, None, cross_only=True),
                              "dd2": TW.predict(s, {}, t, 1.0, None, require_gap=True)}
        if i % 1000 == 0:
            print(f"   decomposition {i}/{len(targets)}", flush=True)
    return out


def main():
    # ---- dev: exponents and router (dev questions use the dev pool, i.e. eval/dev rows held out)
    held = L.held_rows()
    sv_dev = L.build_surveys(held)
    M.EVAL_ARMS = M.DEV_ARMS = {"plain": ("retr6_rev2", M.HAIKU)}
    dev_t = [t for t in L.targets("dev") if "plain" in t["q"]["preds"]]
    dev_dec = decomposition_preds(dev_t, sv_dev)
    dq = [t["q"] for t in dev_t]
    for q in dq:
        q["top"] = sub_shares(q["keys"], q["roles"], q["h"])[0]
    sharp_d = [q for q in dq if q["top"] >= 0.7]
    shal_d = [q for q in dq if q["top"] < 0.7]
    fit = lambda qs, key: max(TEMPS, key=lambda t: np.mean([S(q, temper(dev_dec[q["qid"]][key], t)) for q in qs if dev_dec[q["qid"]][key] is not None]))  # noqa: E731
    fitp = lambda qs, cond: max(TEMPS, key=lambda t: np.mean([S(q, temper(q["preds"]["plain"], t)) for q in qs if cond(q)]))  # noqa: E731
    T = {"dd3": fit(sharp_d, "dd3"), "dd2": fit(shal_d, "dd2"),
         "plain_sharp": fitp(sharp_d, lambda q: dev_dec[q["qid"]]["dd3"] is None),
         "plain_shallow": fitp(shal_d, lambda q: dev_dec[q["qid"]]["dd2"] is None)}
    print("dev-fitted exponents:", T, flush=True)

    l1 = pd.read_pickle(M.OUT / "structure_l1_rows.pkl")
    ds_list, means = sorted(l1.dataset.unique()), l1[NUM].mean()
    tr = l1[l1.set == "dev"]
    top_dev = {q["qid"]: q["top"] for q in dq}
    tr = tr[tr.qid.isin(top_dev)]
    Xd = design(tr, ds_list, means)
    yd = np.array([top_dev[q] >= 0.7 for q in tr.qid], int)
    sc = StandardScaler().fit(Xd)
    clf = LogisticRegression(C=0.5, max_iter=5000).fit(sc.transform(Xd), yd)
    cv = np.zeros(len(yd))
    for a, b in StratifiedKFold(5, shuffle=True, random_state=0).split(Xd, yd):
        s2 = StandardScaler().fit(Xd[a])
        cv[b] = LogisticRegression(C=0.5, max_iter=5000).fit(s2.transform(Xd[a]), yd[a]).predict_proba(s2.transform(Xd[b]))[:, 1]
    cut = max(np.arange(0.1, 0.71, 0.05), key=lambda c: np.mean(cv[yd == 1] >= c) + np.mean(cv[yd == 0] < c))
    print(f"router cut (dev balanced accuracy): {cut:.2f}", flush=True)

    # ---- full benchmark
    sv_full = L.build_surveys(set())
    sample, _, ctx = A.build_env(25, 100, 7, "full")
    qs = [q for q in M.load("full") if "plain" in q["preds"]]
    targets = [t for t in L.targets("full") if "plain" in t["q"]["preds"]]
    print(f"full: {len(qs)} questions; shared-survey targets {len(targets)}", flush=True)
    dec = pd.read_pickle(OUT) if OUT.exists() else decomposition_preds(targets, sv_full)
    pd.to_pickle(dec, OUT)
    shared = {t["q"]["qid"] for t in targets}
    feat = features([q for q in qs if q["qid"] in shared], sample, ctx, topic_model())
    p_sharp = dict(zip(feat.qid, clf.predict_proba(sc.transform(design(feat, ds_list, means)))[:, 1]))

    lab, pos, own = loo_priors(sample)
    from human_sim import simbench_popdecomp as PD
    svp_full = L.build_surveys(set(), split="Pop")
    tmap = {t["q"]["qid"]: t for t in targets}
    dd2_full = {k: v["dd2"] for k, v in dec.items()}
    W_PRIOR = 0.4  # dev-fitted weight of the label prior for plain in the shared surveys (simbench_noanchor_ideas)
    import pandas as _pd
    oth = _pd.read_pickle(M.OUT / "structure_othersets_full.pkl").set_index("qid")
    cog = _pd.read_pickle(M.OUT / "cogmodels_full.pkl")
    import re as _re
    from collections import defaultdict as _dd
    OTHS = ["TISP", "MoralMachine", "MoralMachineClassic", "OSPsychBig5", "OSPsychMACH", "OSPsychMGKT", "ConspiracyCorr", "GlobalOpinionQA"]
    ctry = lambda vm: _re.sub(r"\s*\(.*\)\s*", "", str(next(iter(vm.values())) if vm else "")).strip().lower()  # noqa: E731
    idx = _dd(list)
    for _, rr in sample.iterrows():
        if rr.dataset_name in OTHS:
            tt = sum(rr.human_answer.values()) or 1.0
            idx[(rr.dataset_name, rr.input_template)].append((ctry(rr.group_prompt_variable_map), {k: v / tt for k, v in rr.human_answer.items()}))
    dev_keys = {(r.dataset_name, A._filled_persona(r), r.input_template) for _, r in A.build_env(25, 100, 7, "dev")[0].iterrows()}
    recs = []
    for q in qs:
        p0 = np.asarray(q["preds"]["plain"])
        src, p = "outside shared surveys (plain)", p0
        routed = None
        if q["qid"] in shared:
            routed = "sharp" if p_sharp[q["qid"]] >= cut else "shallow"
            d = dec[q["qid"]]
            if routed == "sharp":
                src, p = ("decomposition", temper(d["dd3"], T["dd3"])) if d["dd3"] is not None else ("plain (no decomposition)", temper(p0, T["plain_sharp"]))
            else:
                src, p = ("decomposition", temper(d["dd2"], T["dd2"])) if d["dd2"] is not None else ("plain (no decomposition)", p0)
            if src == "plain (no decomposition)":
                t = tmap[q["qid"]]
                xd, _ = PD.predict(svp_full, t, 1.0) if t["split"] == "Pop" else PD.predict_group(sv_full, t, 1.0, dd2_full)
                if xd is not None and len(xd) == len(p0):
                    p, src = 0.5 * np.asarray(xd) + 0.5 * p0, ("country-level decomposition + model" if t["split"] == "Pop" else "same-group-abroad decomposition + model")
            if src == "plain (no decomposition)":
                pr = prior_loo(q["i"], lab, pos, own)
                p = (1 - W_PRIOR) * p0 + W_PRIOR * pr if pr is not None and len(pr) == len(p0) else p0
                src = "plain + label prior (no decomposition)"
        elif q["dataset"] in OTHS:
            rr = sample.loc[q["i"]]
            c = ctry(rr.group_prompt_variable_map)
            others = [a for cc, a in idx[(q["dataset"], rr.input_template)] if cc != c]
            if others:
                p = np.mean([[a.get(k, 0.0) for k in q["keys"]] for a in others], axis=0)
                p = p / p.sum()
                src = "other countries, identical question"
            else:
                src = "plain (other datasets)"
        elif q["qid"] in cog:
            p = cog[q["qid"]] if q["keys"] == ["A", "B"] else cog[q["qid"]][::-1]
            src = "cognitive model (" + q["dataset"] + ")"
        else:
            src = "plain (other datasets)"
        r = sample.loc[q["i"]]
        top = sub_shares(q["keys"], q["roles"], q["h"])[0]
        recs.append({"dataset": q["dataset"], "shared": q["qid"] in shared, "split": q["split"], "source": src, "routed": routed,
                     "true_shape": "sharp" if top >= 0.7 else "shallow", "S_plain": S(q, p0), "S_rule": S(q, p),
                     "in_dev": (r.dataset_name, A._filled_persona(r), r.input_template) in dev_keys})
    df = pd.DataFrame(recs)
    d = (df.S_rule - df.S_plain).values
    prev = json.loads((M.OUT / "structure_full_report.json").read_text())
    out = {"N": len(df), "S_plain_retr6_rev2": float(df.S_plain.mean()), "S_rule": float(df.S_rule.mean()), "diff": float(d.mean()), "ci": ci(d),
           "previous_best_full_routed_v1": prev["S_method"], "exponents": T, "router_cut": float(cut), "slices": {}}
    print(f"\n== FULL BENCHMARK, all {len(df)} questions: plain retr6_rev2 {out['S_plain_retr6_rev2']:.2f} | previous best (routed v1) {prev['S_method']:.2f} | "
          f"final rule {out['S_rule']:.2f} ({out['diff']:+.2f} {out['ci']} vs plain)")
    sl = [("excluding dev rows (dev was used for fitting)", ~df.in_dev),
          ("5 shared surveys", df.shared), ("other datasets", ~df.shared),
          ("shared, true sharp", df.shared & (df.true_shape == "sharp")), ("shared, true shallow", df.shared & (df.true_shape == "shallow")),
          ("shared, decomposition used", df.source == "decomposition"),
          ("shared, country-level decomposition + model", df.source == "country-level decomposition + model"),
          ("shared, same-group-abroad decomposition + model", df.source == "same-group-abroad decomposition + model"), ("shared, no decomposition (plain + label prior)", df.source == "plain + label prior (no decomposition)"),
          ("other datasets: other countries, identical question", df.source == "other countries, identical question"),
          ("other datasets: cognitive models", df.source.str.startswith("cognitive")),
          ("other datasets: plain", df.source == "plain (other datasets)"),
          ("shared, true sharp, decomposition used", (df.true_shape == "sharp") & (df.source == "decomposition")),
          ("shared, true sharp, no decomposition", (df.true_shape == "sharp") & (df.source == "plain + label prior (no decomposition)")),
          ("shared, true shallow, decomposition used", (df.true_shape == "shallow") & (df.source == "decomposition")),
          ("shared, true shallow, no decomposition", (df.true_shape == "shallow") & (df.source == "plain + label prior (no decomposition)")),
          ("shared, country-level (Pop)", df.shared & (df.split == "Pop")), ("shared, subgroup (Grouped)", df.shared & (df.split == "Grouped"))]
    for name, m in sl:
        m = m.values
        out["slices"][name] = {"N": int(m.sum()), "share_of_full": float(m.mean()), "S_plain": float(df.S_plain[m].mean()), "S_rule": float(df.S_rule[m].mean()),
                               "diff": float(d[m].mean()), "ci": ci(d[m])}
        v = out["slices"][name]
        print(f"   {name:46s} N {v['N']:5d} ({v['share_of_full']:4.0%})  plain {v['S_plain']:.1f} -> rule {v['S_rule']:.1f}  {v['diff']:+.2f} {v['ci']}")
    out["by_dataset"] = {k: {"N": int(len(g)), "S_plain": float(g.S_plain.mean()), "S_rule": float(g.S_rule.mean())} for k, g in df.groupby("dataset")}
    out["sources"] = df.source.value_counts().to_dict()
    (M.OUT / "structure_fullrule_v3_report.json").write_text(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    main()
