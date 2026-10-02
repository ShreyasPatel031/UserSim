"""Scoreboard: does the demographic persona panel beat the best competing method on consensus AND divided questions?

Bands use the real answers only to slice the scoring; no method sees them. Usage: python -m ... <panel_arm> [more arms]"""

from __future__ import annotations

import json
import sys

import numpy as np

from human_sim import simbench_mass_levers as M

H = M.HAIKU
COMPETITORS = {
    "plain (retr6_rev2)": ("retr6_rev2", H), "retr6": ("retr6", H), "invented personas": ("P_groundall5", H),
    "adaptive personas": ("P_adapt", H), "segments": ("B_n3_soft_rev2", H), "agents": ("B_agents", H),
    "same-group data (D3)": ("D3_same_group_same_topic", H),
}
BANDS = ("consensus", "mixed", "divided")


def band(q):
    return "consensus" if q["Hn"] < 0.65 else ("mixed" if q["Hn"] < M.DIV else "divided")


def ci(d):
    rng = np.random.default_rng(0)
    b = np.sort([rng.choice(d, len(d)).mean() for _ in range(2000)])
    return round(float(b[50]), 1), round(float(b[1949]), 1)


def scoreboard(which, panels, extra=None):
    arms = {**COMPETITORS, **{p: (p, H) for p in panels}}
    M.EVAL_ARMS, M.DEV_ARMS = arms, arms
    qs = [q for q in M.load(which) if all(a in q["preds"] for a in arms)]
    for q in qs:
        q["preds"]["50/50 plain+invented"] = (q["preds"]["plain (retr6_rev2)"] + q["preds"]["invented personas"]) / 2
        for name, fn in (extra or {}).items():
            q["preds"][name] = fn(q)
    comp = list(COMPETITORS) + ["50/50 plain+invented"]
    cand = list(panels) + list(extra or {})
    S = {m: np.array([M.components(q, q["preds"][m])["S"] for q in qs]) for m in comp + cand}
    out = {"N": len(qs), "bands": {}}
    print(f"\n==== {which}: {len(qs)} questions with real demographic personas and every competitor")
    print(f"{'method':28s}" + "".join(f"{b:>22s}" for b in BANDS) + f"{'all':>8s}")
    masks = {b: np.array([band(q) == b for q in qs]) for b in BANDS}
    for m in comp + cand:
        print(f"{m:28s}" + "".join(f"{S[m][masks[b]].mean():>22.1f}" for b in BANDS) + f"{S[m].mean():8.1f}")
    for b in BANDS:
        best = max(comp, key=lambda m: S[m][masks[b]].mean())
        out["bands"][b] = {"N": int(masks[b].sum()), "best_competitor": best, "best_S": float(S[best][masks[b]].mean()),
                           "panels": {}}
        for p in cand:
            d = S[p][masks[b]] - S[best][masks[b]]
            out["bands"][b]["panels"][p] = {"S": float(S[p][masks[b]].mean()), "vs_best": float(d.mean()), "ci": ci(d),
                                            "beats": bool(d.mean() > 0)}
    print("\ncriteria (panel vs the best competitor in that band):")
    for p in cand:
        line = []
        for b in ("consensus", "divided"):
            r = out["bands"][b]["panels"][p]
            line.append(f"{b}: {r['S']:.1f} vs {out['bands'][b]['best_S']:.1f} ({out['bands'][b]['best_competitor']}) "
                        f"{r['vs_best']:+.1f} {r['ci']} {'MET' if r['beats'] else 'not met'}")
        print(f"  {p}:\n     " + "\n     ".join(line))
    return out, qs


def main():
    panels = sys.argv[1:] or ["C5b_demo_mix"]
    res = {w: scoreboard(w, panels)[0] for w in ("dev", "eval")}
    (M.OUT / "panel_criteria_report.json").write_text(json.dumps(res, indent=2, default=float))


if __name__ == "__main__":
    main()
