"""Observability examples: segments for shallow questions, factors for sharp ones.

Selection rule (no cherry-picking): the first eval question, in question-id order, in each of shallow-subgroup,
shallow-country, sharp-subgroup, sharp-country that both tools cover. The real answer is printed only for comparison.
Nothing here uses the target question's real answer in a fit: neighbours exclude it, eval/dev rows are excluded."""

from __future__ import annotations

from collections import Counter

import numpy as np

from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_l3 as L

CL_CFG = ("gmm", 19, 8)
DR_CFG = ("fa", 19, 2)


def pct(v):
    return "{" + ", ".join(f"{k}: {round(100 * x)}%" for k, x in v.items()) + "}"


def dist(keys, v):
    return pct(dict(zip(keys, v)))


def short(t, n=110):
    t = " ".join(str(t).split())
    return t if len(t) <= n else t[: n - 1] + "…"


def segments(F, t, keys):
    ds = t["q"]["dataset"]
    f = F.get(ds, t["text"], t["stem"], CL_CFG[1], CL_CFG[0], CL_CFG[2])
    R, prof = f["extra"]
    sv = F.sv[ds]
    sizes = np.array([sv["size"].get(c, 1.0) or 1.0 for c in f["rows"]])
    if t["split"] == "Pop":
        scope = [i for i, c in enumerate(f["rows"]) if c[1] == t["country"]]
        who = f"cells of {t['country']}"
    else:
        scope = list(range(len(f["rows"])))
        who = "all cells in the survey"
    w = (R[scope] * sizes[scope, None]).sum(0)
    share = w / w.sum()
    lines = [f"Segments found by the clustering tool (Gaussian mixture, {CL_CFG[2]} clusters, on {who}; share = respondent-weighted):", "",
             "| Segment | Share | Who is in it (most typical cells) | Composition (attribute values) | Its predicted answer to this question |",
             "| --- | --- | --- | --- | --- |"]
    order = np.argsort(-share)
    for j in order:
        if share[j] < 0.03:
            continue
        mem = [i for i in scope if R[i, j] == R[i].max()]
        top = sorted(mem, key=lambda i: -R[i, j])[:3]
        comp = Counter(f"{a}={b}" for i in mem for a, b in f["rows"][i][2]).most_common(3)
        p = L.aligned_mix(prof[j], f["cols"], f["nb"], len(keys), t.get("labels"), sv["labels"])
        lines.append(f"| {j + 1} | {round(100 * share[j])}% | {'; '.join(sv['label'][f['rows'][i]] for i in top)} | "
                     f"{', '.join(f'{k} ({n})' for k, n in comp) or '-'} | {dist(keys, p) if p is not None else 'no aligned neighbour'} |")
    if t["split"] == "Grouped" and t["cell"] in f["ridx"]:
        r = R[f["ridx"][t["cell"]]]
        lines += ["", f"Target group ({sv['label'][t['cell']]}) membership: " +
                  ", ".join(f"segment {j + 1} {round(100 * r[j])}%" for j in np.argsort(-r)[:3] if r[j] > 0.05)]
    nb = [s for s, _ in f["nb"][:2]]
    lines += ["", "What separates the biggest segments, on the two most similar other questions:"]
    for st in nb:
        sl = f["cols"][st]
        k2 = sv["keys"][st]
        lines.append(f"- *{short(st, 90)}*: " + "; ".join(f"segment {j + 1} {dist(k2, prof[j][sl])}" for j in order[:3]))
    return lines


def factors(F, t, keys):
    ds = t["q"]["dataset"]
    f = F.get(ds, t["text"], t["stem"], DR_CFG[1], DR_CFG[0], DR_CFG[2])
    comp, scores = f["extra"]
    sv = F.sv[ds]
    X = f["X"]
    tot = float(np.nansum(np.nanvar(X, axis=0))) or 1.0
    lines = [f"Factors found by the component tool (factor analysis, {comp.shape[0]} factors, varimax, on the 19 most similar other questions):", ""]
    for j in range(comp.shape[0]):
        load = {st: float(np.abs(comp[j, sl]).sum()) for st, sl in f["cols"].items()}
        top = sorted(load, key=lambda s: -load[s])[:3]
        ve = float((comp[j] ** 2).sum()) / tot
        lines.append(f"**Factor {j + 1}** (≈{round(100 * ve)}% of the cell-to-cell variation). Questions that load most:")
        for st in top:
            sl = f["cols"][st]
            k2 = sv["keys"][st]
            hi = k2[int(np.argmax(comp[j, sl]))]
            lo = k2[int(np.argmin(comp[j, sl]))]
            lines.append(f"- *{short(st, 95)}* (high on this factor → more '{hi}', less '{lo}')")
        if t["split"] == "Grouped" and t["cell"] in f["ridx"]:
            s = scores[f["ridx"][t["cell"]], j]
            pctl = float((scores[:, j] < s).mean())
            lines.append(f"- Target group ({sv['label'][t['cell']]}) sits at the {round(100 * pctl)}th percentile of cells on this factor.")
        ex = np.argsort(scores[:, j])
        lines.append(f"- Highest cells: {'; '.join(sv['label'][f['rows'][i]] for i in ex[-3:][::-1])}. "
                     f"Lowest: {'; '.join(sv['label'][f['rows'][i]] for i in ex[:3])}.")
        lines.append("")
    return lines


def main():
    F = L.Fitter(L.build_surveys(L.held_rows()))
    ev = sorted(L.targets("eval"), key=lambda t: t["q"]["qid"])
    picks = {}
    for t in ev:
        kind = "shallow" if t["q"]["Hn"] >= 0.65 else "sharp"
        key = (kind, t["split"])
        if key in picks:
            continue
        if L.predict(F, t, *CL_CFG) is None or L.predict(F, t, *DR_CFG) is None:
            continue
        picks[key] = t
        if len(picks) == 4:
            break
    out = ["# Observability examples: segments and factors", "",
           "Selection rule: the first eval question (question-id order) in each category that both tools cover. "
           "The real answer is shown only for comparison; no fit ever sees the target question's answers.", ""]
    for key in (("shallow", "Grouped"), ("shallow", "Pop"), ("sharp", "Grouped"), ("sharp", "Pop")):
        t = picks.get(key)
        if t is None:
            continue
        q = t["q"]
        keys = q["keys"]
        texts = q["texts"]
        out += [f"## {key[0].capitalize()} question, {'subgroup' if key[1] == 'Grouped' else 'country-level'}: {q['dataset']}", "",
                f"**Population:** {short(q['persona'], 160)}", "", f"**Question:** {short(t['stem'], 300)}", "",
                "**Options:** " + "; ".join(f"{k} = {short(texts.get(k, ''), 40)}" for k in keys), "",
                f"| | Answer |", "| --- | --- |",
                f"| Real answer (comparison only) | {dist(keys, q['h'])} |",
                f"| Model (`retr6_rev2`) | {dist(keys, q['preds']['plain']) if 'plain' in q['preds'] else '-'} |",
                f"| Clustering tool alone | {dist(keys, L.predict(F, t, *CL_CFG))} |",
                f"| Component tool alone | {dist(keys, L.predict(F, t, *DR_CFG))} |", ""]
        out += (segments(F, t, keys) if key[0] == "shallow" else factors(F, t, keys)) + [""]
    path = M.OUT.parent.parent / "docs" / "experiments" / "structure_observability_examples.md"
    path.write_text("\n".join(out))
    print("\n".join(out))


if __name__ == "__main__":
    main()
