"""Blend the Layer 3 statistical tool with the model's answer (no new model calls).

final = w * tool + (1 - w) * model, w fitted on dev per bucket and tool family, applied unchanged to eval.
Where the tool has no prediction (no cell data, no neighbour with the same option count) the model answer is kept."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from human_sim import simbench_mass_levers as M
from human_sim import simbench_structure_l3 as L

MODEL = "retr6_rev2"
WS = np.linspace(0, 1, 21)


def ci(d):
    d = np.asarray(d, float)
    rng = np.random.default_rng(0)
    b = np.sort([rng.choice(d, len(d)).mean() for _ in range(2000)])
    return round(float(b[50]), 1), round(float(b[1949]), 1)


def band(q):
    return "consensus" if q["Hn"] < 0.65 else ("mixed" if q["Hn"] < M.DIV else "divided")


def main():
    tun = pd.read_pickle(M.OUT / "structure_l3_tuning.pkl")
    best = tun["best"]
    sets = {w: L.targets(w) for w in ("dev", "eval")}
    S = L.S
    cache_path = M.OUT / "structure_blend_toolpreds.pkl"
    cache = pd.read_pickle(cache_path) if cache_path.exists() else {}
    if not cache:
        F = L.Fitter(L.build_surveys(L.held_rows()))
        for w, tt in sets.items():
            for t in tt:
                cache[t["q"]["qid"]] = {fam: (L.predict(F, t, *best[(t["bucket"], fam)]) if (t["bucket"], fam) in best else None)
                                        for fam in ("DR", "CL")}
        pd.to_pickle(cache, cache_path)
    for tt in sets.values():
        for t in tt:
            t["tool"] = cache[t["q"]["qid"]]
    rep = {"configs": {f"{b} | {fam}": list(c) for (b, fam), c in best.items()}, "weights": {}, "eval": {}}
    for fam in ("DR", "CL"):
        wts = {}
        for b in ("dimension-reduction", "clustering"):
            dv = [t for t in sets["dev"] if t["bucket"] == b and t["tool"][fam] is not None and MODEL in t["q"]["preds"]]
            if len(dv) < 5:
                wts[b] = 0.0
                continue
            wts[b] = float(max(WS, key=lambda x: np.mean([S(t["q"], x * t["tool"][fam] + (1 - x) * np.asarray(t["q"]["preds"][MODEL])) for t in dv])))
        rep["weights"][fam] = wts
        ev = [t for t in sets["eval"] if MODEL in t["q"]["preds"]]
        base = np.array([S(t["q"], t["q"]["preds"][MODEL]) for t in ev])
        fin = np.array([S(t["q"], wts[t["bucket"]] * t["tool"][fam] + (1 - wts[t["bucket"]]) * np.asarray(t["q"]["preds"][MODEL]))
                        if t["tool"][fam] is not None else S(t["q"], t["q"]["preds"][MODEL]) for t in ev])
        cov = np.array([t["tool"][fam] is not None for t in ev], dtype=bool)
        d = fin - base
        row = {"N": len(ev), "covered": int(cov.sum()), "model": float(base.mean()), "blend": float(fin.mean()),
               "diff": float(d.mean()), "ci": ci(d), "diff_on_covered": float(d[cov].mean()) if cov.any() else None,
               "ci_on_covered": ci(d[cov]) if cov.sum() > 4 else None}
        for bb in ("consensus", "mixed", "divided"):
            m = np.array([band(t["q"]) == bb for t in ev], dtype=bool) & cov
            if m.sum() > 4:
                row[f"covered {bb}"] = {"N": int(m.sum()), "diff": float(d[m].mean()), "ci": ci(d[m])}
        for sp in ("Grouped", "Pop"):
            m = np.array([t["split"] == sp for t in ev], dtype=bool) & cov
            if m.sum() > 4:
                row[f"covered {sp}"] = {"N": int(m.sum()), "diff": float(d[m].mean()), "ci": ci(d[m])}
        rep["eval"][fam] = row
        print(f"\n== blend model ({MODEL}) with {fam} tool, dev weights {wts}")
        print(f"   eval shared-survey questions N {row['N']} (tool covers {row['covered']}): model {row['model']:.1f} -> blend {row['blend']:.1f} "
              f"({row['diff']:+.1f} {row['ci']}); on covered questions {row['diff_on_covered']:+.1f} {row['ci_on_covered']}")
        print("   " + " | ".join(f"{k} N{v['N']} {v['diff']:+.1f} {v['ci']}" for k, v in row.items() if k.startswith("covered ") and isinstance(v, dict)))
    (M.OUT / "structure_blend_report.json").write_text(json.dumps(rep, indent=2, default=float))


if __name__ == "__main__":
    main()
