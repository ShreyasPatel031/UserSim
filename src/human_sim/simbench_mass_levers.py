"""Divided questions: what exactly is wrong with the mass, and which lever fixes which part?

Part 1  mass anatomy: component metrics and a counterfactual decomposition of each question's
        error into location / assignment / profile (Shapley over the three fixes), plus peaks.
Part 2  lever map: every logged lever vs retr6_rev2 on slices of divided questions, what each
        lever moves, panel-vs-segments mechanism on the task datasets, a simple routing rule.

No model calls (except the optional traced segments run Bdiag_n3_soft_tasks, run separately).
All counterfactual fixes and the dominant-component slice use the truth: diagnostics only.

Usage:
  PYTHONPATH=src python -m human_sim.simbench_mass_levers
"""

from __future__ import annotations

import ast
import itertools
import json
import math
import re
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from human_sim import simbench_ablate as A
from human_sim.simbench_divided_anatomy import option_roles, parse_options
from human_sim.simbench_divided_eda import textbook_options

OUT = A.OUT_DIR
IMG = A.ROOT / "docs" / "experiments" / "img"
HAIKU = "claude-haiku-4-5"
SHARED = ("Afrobarometer", "ESS", "ISSP", "LatinoBarometro", "OpinionQA")
TASKS = ("OSPsychMACH", "Choices13k", "NumberGame", "OSPsychMGKT")
DIV = 0.84
BASE = "retr6_rev2"

EVAL_ARMS = {
    "base": ("base", HAIKU), "fs_k6": ("fs_k6", HAIKU), "retr6": ("retr6", HAIKU), "retr6_rev2": ("retr6_rev2", HAIKU),
    "panel": ("P_groundall5", HAIKU), "P_adapt": ("P_adapt", HAIKU), "B_n3_soft": ("B_n3_soft", HAIKU),
    "B_n3_soft_rev2": ("B_n3_soft_rev2", HAIKU), "B_agents": ("B_agents", HAIKU), "B_adaptive": ("B_adaptive", HAIKU),
    "gemini_retr6": ("retr6", "gemini-2.5-flash"),
}
DEV_ARMS = {
    "base": ("base", HAIKU), "retr6": ("retr6", HAIKU), "retr6_rev2": ("retr6_rev2", HAIKU), "retr6_vs3": ("retr6_vs3", HAIKU),
    "panel": ("P_groundall5", HAIKU), "panel_R": ("P_groundall5_R", HAIKU), "P_adapt": ("P_adapt", HAIKU),
    "B_n3_soft": ("B_n3_soft", HAIKU), "B_n3_soft_rev2": ("B_n3_soft_rev2", HAIKU), "B_ground3": ("B_ground3", HAIKU),
    "B_ground3_rev2": ("B_ground3_rev2", HAIKU), "B_agents": ("B_agents", HAIKU), "B_adaptive": ("B_adaptive", HAIKU),
    "gemini_retr6": ("retr6", "gemini-2.5-flash"), "sonnet46_retr6": ("retr6", "claude-sonnet-4-6"),
    "sonnet55_retr6": ("retr6", "claude-sonnet-5-5"),
}


# ------------------------------------------------------------------ basics


def tvd(p, q) -> float:
    return 0.5 * float(np.abs(np.asarray(p) - np.asarray(q)).sum())


def Hn(p) -> float:
    p = np.asarray(p)
    q = p[p > 0]
    return float(-(q * np.log(q)).sum() / np.log(len(p))) if len(p) > 1 else 0.0


def _norm(v) -> np.ndarray:
    v = np.clip(np.asarray(v, float), 0, None)
    s = v.sum()
    return v / s if s > 0 else np.full(len(v), 1 / len(v))


# ------------------------------------------------------------------ ordinal helpers


def _ord_parts(roles: dict, keys: list) -> tuple[list[int], np.ndarray] | None:
    """Indices of substantive ordinal options (scale order) and their positions in [0, 1]."""
    if not roles["ordinal"]:
        return None
    idx = [keys.index(k) for k in roles["subs"]]
    pos = np.array([roles["roles"][k] if isinstance(roles["roles"][k], float) else np.nan for k in roles["subs"]])
    if np.isnan(pos).any():
        pos = np.linspace(0, 1, len(idx))
    return idx, pos


def _moments(m: np.ndarray, pos: np.ndarray):
    m = _norm(m)
    mu = float((m * pos).sum())
    sd = float(np.sqrt((m * (pos - mu) ** 2).sum()))
    sk = float((m * (pos - mu) ** 3).sum() / sd**3) if sd > 1e-9 else 0.0
    return mu, sd, sk


def _peaks(m: np.ndarray, prom: float = 0.05) -> int:
    """Local maxima along the scale whose height exceeds both neighbouring minima by >= prom."""
    m = np.asarray(m, float)
    n, count = len(m), 0
    for i in range(n):
        left = m[i - 1] if i > 0 else -1
        right = m[i + 1] if i < n - 1 else -1
        if m[i] > left and m[i] >= right:
            lmin = m[:i].min() if i > 0 else 0.0
            rmin = m[i + 1 :].min() if i < n - 1 else 0.0
            if m[i] - max(lmin, rmin) >= prom or (i in (0, n - 1) and m[i] - (rmin if i == 0 else lmin) >= prom):
                count += 1
    return max(count, 1)


def _emd(a: np.ndarray, b: np.ndarray, pos: np.ndarray) -> float:
    ca, cb = np.cumsum(_norm(a)), np.cumsum(_norm(b))
    gaps = np.diff(pos)
    return float((np.abs(ca[:-1] - cb[:-1]) * gaps).sum())


def _translate(m: np.ndarray, pos: np.ndarray, delta: float) -> np.ndarray:
    """Move every unit of mass by delta along the scale (linear split between neighbouring
    options, clipped at the ends). A pure translation is the minimum-cost (EMD) way to move
    the mean by delta."""
    out = np.zeros_like(m)
    for j, w in enumerate(m):
        x = min(max(pos[j] + delta, pos[0]), pos[-1])
        k = int(np.searchsorted(pos, x, side="right") - 1)
        k = min(max(k, 0), len(pos) - 2)
        t = (x - pos[k]) / (pos[k + 1] - pos[k]) if pos[k + 1] > pos[k] else 0.0
        out[k] += w * (1 - t)
        out[k + 1] += w * t
    return out


def fix_location(p, h, roles, keys) -> np.ndarray:
    parts = _ord_parts(roles, keys)
    if parts is None:
        return np.asarray(p, float).copy()
    idx, pos = parts
    p, h = np.asarray(p, float), np.asarray(h, float)
    mp, mh = p[idx], h[idx]
    if mp.sum() <= 0 or mh.sum() <= 0:
        return p.copy()
    target = _moments(mh, pos)[0]
    lo, hi = -1.0, 1.0
    for _ in range(50):
        mid = (lo + hi) / 2
        mu = _moments(_translate(_norm(mp), pos, mid), pos)[0]
        lo, hi = (mid, hi) if mu < target else (lo, mid)
    q = p.copy()
    q[idx] = _translate(_norm(mp), pos, (lo + hi) / 2) * mp.sum()
    return q


def fix_assignment(p, h, roles=None, keys=None) -> np.ndarray:
    p, h = np.asarray(p, float), np.asarray(h, float)
    q = np.zeros_like(p)
    q[np.argsort(-h, kind="stable")] = np.sort(p)[::-1]
    return q


def fix_profile(p, h, roles=None, keys=None) -> np.ndarray:
    p, h = np.asarray(p, float), np.asarray(h, float)
    q = np.zeros_like(p)
    q[np.argsort(-p, kind="stable")] = np.sort(h)[::-1]
    return q


FIXES = {"location": fix_location, "assignment": fix_assignment, "profile": fix_profile}


def shapley(p, h, roles, keys) -> dict:
    """Shapley split of the TVD removed by the three fixes. v(S) = TVD(p) - mean over the orders
    of S of TVD(fixes applied in that order)."""
    names = list(FIXES)
    base = tvd(p, h)
    cache = {}

    def v(S):
        S = tuple(sorted(S))
        if S in cache:
            return cache[S]
        if not S:
            cache[S] = 0.0
            return 0.0
        vals = []
        for order in itertools.permutations(S):
            q = np.asarray(p, float)
            for nme in order:
                q = FIXES[nme](q, h, roles, keys)
            vals.append(tvd(_norm(q), h))
        cache[S] = base - float(np.mean(vals))
        return cache[S]

    n = len(names)
    phi = {}
    for i in names:
        others = [x for x in names if x != i]
        tot = 0.0
        for r in range(len(others) + 1):
            for S in itertools.combinations(others, r):
                w = math.factorial(len(S)) * math.factorial(n - len(S) - 1) / math.factorial(n)
                tot += w * (v(S + (i,)) - v(S))
        phi[i] = tot
    alone = {i: v((i,)) for i in names}
    return {"tvd": base, "phi": phi, "alone": alone, "all": v(tuple(names))}


# ------------------------------------------------------------------ loading


def _load(arm, model, suffix):
    p = OUT / f"{arm}_{model}_p25g100s7{suffix}.json"
    return {r["i"]: r for r in json.loads(p.read_text())["rows"] if r.get("ok")} if p.exists() else {}


def load(which: str):
    sample, norms, ctx = A.build_env(25, 100, 7, which)
    if which == "eval":
        norms = json.loads((OUT / "dataset_norms.json").read_text())
    suffix = {"eval": "", "full": "full"}.get(which, "dev10x40")
    arms = EVAL_ARMS if which == "eval" else DEV_ARMS
    raw = {k: _load(a, m, suffix) for k, (a, m) in arms.items()}
    eda = pd.read_pickle(OUT / "divided_eda_table.pkl")
    nbr = eda.drop_duplicates("qid").set_index("qid")["demo_mean_entropy"].to_dict()
    qs = []
    for i, row in sample.iterrows():
        keys = list(row["human_answer"].keys())
        vec = lambda d: _norm([d.get(k, 0.0) for k in keys])  # noqa: E731
        h = vec(row["human_answer"])
        texts = parse_options(row["input_template"])
        roles = option_roles(keys, texts, row["dataset_name"])
        nsub = len([k for k in keys if roles["roles"][k] != "dk"])
        q = {
            "set": which, "i": int(i), "qid": f"{which}:{i}", "dataset": row["dataset_name"], "split": row["split"],
            "group": "shared_survey" if row["dataset_name"] in SHARED else (row["dataset_name"] if row["dataset_name"] in TASKS else "other_pop_only"),
            "group3": "shared_survey" if row["dataset_name"] in SHARED else ("pop_only_task" if row["dataset_name"] in TASKS else "other_pop_only"),
            "format": "ordinal" if roles["ordinal"] else ("binary" if nsub == 2 else "categorical"),
            "n_options": len(keys), "value_laden": bool(textbook_options(row["input_template"], texts)),
            "keys": keys, "texts": texts, "roles": roles, "h": h, "Hn": Hn(h), "norm": norms[row["dataset_name"]],
            "question": row["input_template"], "persona": A._filled_persona(row), "aux": row.get("auxiliary"),
            "nbr_h": nbr.get(f"{which}:{i}", np.nan), "preds": {},
        }
        for k, d in raw.items():
            if i in d:
                q["preds"][k] = vec(d[i]["llm_answer"])
                if "segments" in d[i]:
                    q.setdefault("traces", {})[k] = d[i]["segments"]
        qs.append(q)
    return qs


# ------------------------------------------------------------------ Part 1: components


def components(q: dict, p: np.ndarray) -> dict:
    h, keys, roles = q["h"], q["keys"], q["roles"]
    c = {
        "TVD": tvd(p, h),
        "S": 100 * (1 - tvd(p, h) / q["norm"]),
        "entropy_gap": Hn(p) - q["Hn"],
        "profile_error": tvd(np.sort(p)[::-1], np.sort(h)[::-1]),
        "spearman": float(spearmanr(p, h).correlation) if np.std(p) > 1e-9 and np.std(h) > 1e-9 else np.nan,
        "top_right": float(np.argmax(p) == np.argmax(h)),
        "top2_right": float(set(np.argsort(-p)[:2]) == set(np.argsort(-h)[:2])) if len(p) > 2 else np.nan,
    }
    parts = _ord_parts(roles, keys)
    if parts:
        idx, pos = parts
        mp, mh = p[idx], h[idx]
        if mp.sum() > 0 and mh.sum() > 0:
            (mu_p, sd_p, sk_p), (mu_h, sd_h, sk_h) = _moments(mp, pos), _moments(mh, pos)
            c.update({
                "loc_shift": mu_p - mu_h, "loc_abs": abs(mu_p - mu_h), "sd_gap": sd_p - sd_h,
                "emd": _emd(mp, mh, pos),
            })
            tp, th = pos[int(np.argmax(mp))], pos[int(np.argmax(mh))]
            c["flip"] = float((tp - 0.5) * (th - 0.5) < 0) if tp != 0.5 and th != 0.5 else np.nan
            if len(idx) >= 4:
                kp, kh = _peaks(_norm(mp)), _peaks(_norm(mh))
                c.update({
                    "skew_gap": sk_p - sk_h, "peaks_pred": kp, "peaks_true": kh,
                    "true2_pred1": float(kh >= 2 and kp == 1), "true1_pred2": float(kh == 1 and kp >= 2),
                    "peak_mismatch": float(kh != kp),
                })
    dk = [j for j, k in enumerate(keys) if roles["roles"][k] == "dk"]
    mid = [j for j, k in enumerate(keys) if roles["roles"][k] in (0.5, "neutral")]
    if dk:
        c["dk_gap"] = float(p[dk].sum() - h[dk].sum())
    if mid:
        c["mid_gap"] = float(p[mid].sum() - h[mid].sum())
    return c


def part1(qs: list[dict], arms=("retr6_rev2", "panel", "B_n3_soft_rev2")) -> dict:
    out = {}
    rows = []
    for q in qs:
        if q["Hn"] < DIV:
            continue
        for arm in arms:
            if arm not in q["preds"]:
                continue
            p = q["preds"][arm]
            c = components(q, p)
            sh = shapley(p, q["h"], q["roles"], q["keys"])
            fixed = {f"S_fix_{k}": 100 * (1 - tvd(_norm(FIXES[k](p, q["h"], q["roles"], q["keys"])), q["h"]) / q["norm"]) for k in FIXES}
            rows.append({
                "set": q["set"], "qid": q["qid"], "arm": arm, "group": q["group"], "group3": q["group3"],
                "dataset": q["dataset"], "format": q["format"], **c, **fixed,
                **{f"phi_{k}": v for k, v in sh["phi"].items()}, **{f"alone_{k}": v for k, v in sh["alone"].items()},
                "removed_all": sh["all"],
            })
    df = pd.DataFrame(rows)
    df["dominant"] = df.apply(_dominant, axis=1)
    return df


def _dominant(r) -> str:
    if r.get("true2_pred1") == 1 or r.get("true1_pred2") == 1:
        return "peaks"
    phis = {k: r[f"phi_{k}"] for k in FIXES}
    return max(phis, key=phis.get)


def _ci(v):
    v = np.asarray([x for x in v if not (isinstance(x, float) and math.isnan(x))], float)
    if len(v) < 2:
        return [None, None]
    rng = np.random.default_rng(0)
    b = np.sort([rng.choice(v, len(v)).mean() for _ in range(1000)])
    return [round(float(b[25]), 3), round(float(b[975]), 3)]


def summarize_part1(df: pd.DataFrame) -> dict:
    out = {}
    for (s, arm, g3, fmt), d in df.groupby(["set", "arm", "group3", "format"]):
        tv = d.TVD.sum()
        r = {
            "n": len(d), "S": round(float(d.S.mean()), 2), "S_ci": _ci(d.S),
            "entropy_gap": round(float(d.entropy_gap.mean()), 3), "profile_error": round(float(d.profile_error.mean()), 3),
            "spearman": round(float(d.spearman.mean()), 3), "top_right": round(float(d.top_right.mean()), 3),
            "top2_right": round(float(d.top2_right.mean()), 3) if d.top2_right.notna().any() else None,
        }
        for c in ("loc_shift", "loc_abs", "sd_gap", "emd", "flip", "skew_gap", "true2_pred1", "true1_pred2", "dk_gap", "mid_gap"):
            if c in d and d[c].notna().any():
                r[c] = round(float(d[c].mean()), 3)
                r[f"{c}_n"] = int(d[c].notna().sum())
        if "emd" in d and d.emd.notna().any():
            r["emd_over_tvd"] = round(float((d.emd / d.TVD.replace(0, np.nan)).mean()), 3)
        for k in FIXES:
            r[f"S_fix_{k}"] = round(float(d[f"S_fix_{k}"].mean()), 2)
            r[f"share_alone_{k}"] = round(float(d[f"alone_{k}"].sum() / tv), 3) if tv > 0 else None
            r[f"share_shapley_{k}"] = round(float(d[f"phi_{k}"].sum() / tv), 3) if tv > 0 else None
        r["share_unexplained"] = round(float(1 - d.removed_all.sum() / tv), 3) if tv > 0 else None
        pk = d[(d.get("true2_pred1", 0) == 1) | (d.get("true1_pred2", 0) == 1)] if "true2_pred1" in d else d.iloc[0:0]
        r["peak_mismatch_questions"] = int(len(pk))
        r["peak_mismatch_tvd_share"] = round(float(pk.TVD.sum() / tv), 3) if tv > 0 else None
        r["dominant_counts"] = d.dominant.value_counts().to_dict()
        out[f"{s}/{arm}/{g3}/{fmt}"] = r
    return out


# ------------------------------------------------------------------ Part 2: levers


def derived_levers(qs: list[dict], which: str):
    """Mixes and averages recomputed from logs (no calls)."""
    blend = json.loads((OUT / "panel_blend_report.json").read_text())["fitted_on_dev"]
    edges, wts = blend["blend_nbr_entropy_edges"], blend["blend_retr6_weight_by_nbr_third"]
    for q in qs:
        P = q["preds"]
        n = len(q["keys"])
        P["even_split"] = np.full(n, 1 / n)
        for a in (BASE, "panel"):
            if a in P:
                P[f"{a}_pull29"] = 0.71 * P[a] + 0.29 / n
        if "panel" in P and "B_n3_soft" in P:
            P["mix_panel_segments"] = 0.4 * P["panel"] + 0.6 * P["B_n3_soft"]
        if "panel" in P and "retr6" in P and not math.isnan(q["nbr_h"]):
            third = sum(q["nbr_h"] >= e for e in edges)
            P["blend_panel_retr6"] = wts[third] * P["retr6"] + (1 - wts[third]) * P["panel"]
        if which == "dev" and all(k in P for k in ("panel", "panel_R", "B_ground3_rev2")):
            mix = 0.75 * (P["panel"] + P["panel_R"]) / 2 + 0.25 * P["B_ground3_rev2"]
            P["best_mix_no_pull"] = mix
            P["best_mix_pull29"] = 0.71 * mix + 0.29 / len(mix)
            P["panel_both_orders"] = (P["panel"] + P["panel_R"]) / 2


def demo_avg_lever(qs: list[dict], which: str):
    """Plain average of the option-aligned retr6 demos, used as the prediction (where they exist)."""
    sample, _, ctx = A.build_env(25, 100, 7, which)
    for q in qs:
        row = sample.iloc[q["i"]]
        opt = [q["texts"].get(k, "").strip().lower() for k in q["keys"]]
        al = []
        for d in A._rank_by_similarity(row, A._demo_pool(row, ctx), ctx)[:6]:
            dt = parse_options(d["input_template"])
            dk = list(d["human_answer"].keys())
            if len(dk) == len(q["keys"]) and [dt.get(k, "").strip().lower() for k in dk] == opt:
                al.append(_norm([d["human_answer"].get(k, 0.0) for k in dk]))
        if al:
            q["preds"]["demo_average"] = np.mean(al, axis=0)


def lever_matrix(qs: list[dict], dom: dict, pick=lambda q: q["Hn"] >= DIV) -> dict:
    """pick = which questions count as divided. Default uses the truth's entropy (diagnostic);
    pick on neighbour entropy for the truth-free version."""
    div = [q for q in qs if pick(q) and BASE in q["preds"]]
    levers = sorted({k for q in div for k in q["preds"]} - {BASE})
    slices = {"all divided": lambda q: True}
    for g in ("shared_survey",) + TASKS + ("other_pop_only",):
        slices[f"group: {g}"] = (lambda g: lambda q: q["group"] == g)(g)
    counts = pd.Series([q["dataset"] for q in div]).value_counts()
    for ds in counts[counts >= 10].index:
        slices[f"dataset: {ds}"] = (lambda ds: lambda q: q["dataset"] == ds)(ds)
    for f in ("ordinal", "binary", "categorical"):
        slices[f"format: {f}"] = (lambda f: lambda q: q["format"] == f)(f)
    for lo, hi, lab in ((2, 2, "2"), (3, 4, "3-4"), (5, 6, "5-6"), (7, 99, "7+")):
        slices[f"options: {lab}"] = (lambda lo, hi: lambda q: lo <= q["n_options"] <= hi)(lo, hi)
    slices["value-laden: yes"] = lambda q: q["value_laden"]
    slices["value-laden: no"] = lambda q: not q["value_laden"]
    for comp in ("location", "assignment", "profile", "peaks"):
        slices[f"dominant (diagnostic): {comp}"] = (lambda comp: lambda q: dom.get(q["qid"]) == comp)(comp)
    rng = np.random.default_rng(0)
    out = {}
    for sname, f in slices.items():
        cell = {}
        for lev in levers:
            qq = [q for q in div if f(q) and lev in q["preds"]]
            if len(qq) < 5:
                continue
            d = np.array([100 * (tvd(q["preds"][BASE], q["h"]) - tvd(q["preds"][lev], q["h"])) / q["norm"] for q in qq])
            b = np.sort([rng.choice(d, len(d)).mean() for _ in range(1000)])
            cell[lev] = {"n": len(d), "dS": round(float(d.mean()), 2), "ci": [round(float(b[25]), 2), round(float(b[975]), 2)],
                         "base_S": round(float(np.mean([100 * (1 - tvd(q["preds"][BASE], q["h"]) / q["norm"]) for q in qq])), 2)}
        if cell:
            sig = {k: v for k, v in cell.items() if v["n"] >= 30 and v["ci"][0] > 0}
            best = max(cell, key=lambda k: cell[k]["dS"])
            out[sname] = {"levers": cell, "best": best, "best_significant": max(sig, key=lambda k: sig[k]["dS"]) if sig else None}
    return out


def lever_components(qs: list[dict]) -> dict:
    div = [q for q in qs if q["Hn"] >= DIV and BASE in q["preds"]]
    levers = sorted({k for q in div for k in q["preds"]} - {BASE})
    keys = ["loc_abs", "spearman", "top_right", "profile_error", "entropy_gap_abs", "peak_mismatch", "flip", "emd"]
    out = {}
    for grp in ("shared_survey", "pop_only_task", "other_pop_only"):
        g = [q for q in div if q["group3"] == grp]
        res = {}
        for lev in levers:
            qq = [q for q in g if lev in q["preds"]]
            if len(qq) < 10:
                continue
            delta = defaultdict(list)
            for q in qq:
                a, b = components(q, q["preds"][BASE]), components(q, q["preds"][lev])
                a["entropy_gap_abs"], b["entropy_gap_abs"] = abs(a["entropy_gap"]), abs(b["entropy_gap"])
                for k in keys:
                    if k in a and k in b and not (np.isnan(a[k]) or np.isnan(b[k])):
                        delta[k].append(b[k] - a[k])
            res[lev] = {"n": len(qq), **{k: round(float(np.mean(v)), 3) for k, v in delta.items() if len(v) >= 5}}
        out[grp] = res
    return out


# ------------------------------------------------------------------ Part 2.3.3: mechanism on task datasets


def _ev_expert(question: str) -> str | None:
    """Higher expected-value machine for Choices13k gambles."""
    evs = {}
    for mach in ("A", "B"):
        m = re.search(rf"Machine {mach}: (.+?)\.\n", question + "\n")
        if not m:
            return None
        pairs = re.findall(r"\$(-?[0-9.]+) with ([0-9.]+)% chance", m.group(1))
        if not pairs:
            return None
        evs[mach] = sum(float(v) * float(pc) / 100 for v, pc in pairs)
    if abs(evs["A"] - evs["B"]) < 1e-9:
        return None
    return "A" if evs["A"] > evs["B"] else "B"


def expert_option(q: dict) -> str | None:
    if q["dataset"] == "Choices13k":
        return _ev_expert(q["question"])
    if q["dataset"] == "OSPsychMGKT":
        aux = q["aux"]
        aux = ast.literal_eval(aux) if isinstance(aux, str) else (aux or {})
        if "answer_value" in aux:
            return "A" if int(aux["answer_value"]) == 1 else "B"
    return None


def mechanism(qs: list[dict]) -> dict:
    seg = _load("Bdiag_n3_soft_tasks", HAIKU, "")
    pop = pd.read_csv(A.ROOT / "data" / "simbench" / "SimBenchPop.csv")
    aux_by_q = {r.input_template: r.auxiliary for r in pop.itertuples()}
    sample, _, ctx = A.build_env(25, 100, 7, "eval")
    out = {}
    for ds in TASKS:
        items = [q for q in qs if q["dataset"] == ds and q["Hn"] >= DIV and "panel" in q.get("traces", {})]
        rec = defaultdict(list)
        worst = []
        for q in items:
            keys = q["keys"]
            vec = lambda d: _norm([d.get(k, 0.0) for k in keys])  # noqa: E731
            types = [(t["desc"], float(t["share"]), vec(t["dist"])) for t in q["traces"]["panel"] if t.get("dist")]
            if len(types) >= 2:
                rec["panel_type_diversity"].append(np.mean([tvd(a[2], b[2]) for a, b in itertools.combinations(types, 2)]))
                w = np.array([t[1] for t in types])
                eq = np.mean([t[2] for t in types], axis=0)
                ms = _norm(sum(wi * t[2] for wi, t in zip(w / w.sum(), types)))
                rec["panel_S_model_shares"].append(100 * (1 - tvd(ms, q["h"]) / q["norm"]))
                rec["panel_S_equal_weights"].append(100 * (1 - tvd(eq, q["h"]) / q["norm"]))
                rec["panel_top_share"].append(float(w.max() / w.sum()))
            srow = seg.get(q["i"])
            segs = [(float(s["share"]), vec(s["dist"])) for s in (srow or {}).get("segments", [])]
            if len(segs) >= 2:
                rec["segment_diversity"].append(np.mean([tvd(a[1], b[1]) for a, b in itertools.combinations(segs, 2)]))
            ex = expert_option(q)
            if ex and ex in keys:
                j = keys.index(ex)
                rec["truth_mass_on_expert"].append(q["h"][j])
                if types:
                    rec["panel_types_mass_on_expert"].append(np.mean([t[2][j] for t in types]))
                    rec["panel_final_mass_on_expert"].append(q["preds"]["panel"][j])
                    # does the planner overweight the most expert-like type?
                    exp_type = max(range(len(types)), key=lambda k: types[k][2][j])
                    rec["share_of_most_expert_type"].append(types[exp_type][1] / sum(t[1] for t in types))
                if segs:
                    rec["segments_mass_on_expert"].append(np.mean([s[1][j] for s in segs]))
                if "B_n3_soft" in q["preds"]:
                    rec["segments_final_mass_on_expert"].append(q["preds"]["B_n3_soft"][j])
                if BASE in q["preds"]:
                    rec["retr6_rev2_mass_on_expert"].append(q["preds"][BASE][j])
                # retrieved demos: real humans' mass on the expert option of each demo question
                row = sample.iloc[q["i"]]
                dm = []
                for d in A._rank_by_similarity(row, A._demo_pool(row, ctx), ctx)[:6]:
                    dq = {"dataset": ds, "question": d["input_template"], "aux": aux_by_q.get(d["input_template"])}
                    de = expert_option(dq)
                    if de and de in d["human_answer"]:
                        tot = sum(d["human_answer"].values()) or 1
                        dm.append(d["human_answer"][de] / tot)
                if dm:
                    rec["demo_humans_mass_on_expert"].append(np.mean(dm))
            if "panel" in q["preds"]:
                worst.append((100 * (1 - tvd(q["preds"]["panel"], q["h"]) / q["norm"]), q, types))
        worst.sort(key=lambda x: x[0])
        out[ds] = {
            "n_divided_with_panel_traces": len(items),
            "n_with_segment_traces": len(rec["segment_diversity"]),
            **{k: round(float(np.mean(v)), 3) for k, v in rec.items()},
            **{f"{k}_n": len(v) for k, v in rec.items()},
            "worst5_panel": [
                {
                    "S_panel": round(s, 1),
                    "question": q["question"].split("Options:")[0].strip()[:260],
                    "truth": {k: round(float(x), 2) for k, x in zip(q["keys"], q["h"])},
                    "expert_option": expert_option(q),
                    "types": [{"desc": t[0][:140], "share": round(t[1], 1), "answer": {k: round(float(x), 2) for k, x in zip(q["keys"], t[2])}} for t in types],
                }
                for s, q, types in worst[:5]
            ],
        }
    return out


# ------------------------------------------------------------------ Part 2.3.4: simple routing rule

ROUTE_ARMS = ["base", "retr6", "retr6_rev2", "panel", "P_adapt", "B_n3_soft", "B_n3_soft_rev2", "B_agents", "B_adaptive",
              "retr6_rev2_pull29", "panel_pull29"]


def routing(dev: list[dict], ev: list[dict]) -> dict:
    def S(q, a):
        return 100 * (1 - tvd(q["preds"][a], q["h"]) / q["norm"])

    dev = [q for q in dev if all(a in q["preds"] for a in ROUTE_ARMS)]
    ev = [q for q in ev if all(a in q["preds"] for a in ROUTE_ARMS)]
    overall = max(ROUTE_ARMS, key=lambda a: np.mean([S(q, a) for q in dev]))
    keyf = [
        lambda q: (q["dataset"], q["format"], q["value_laden"]),
        lambda q: (q["dataset"], q["format"]),
        lambda q: (q["dataset"],),
        lambda q: (q["format"], q["n_options"] if q["n_options"] <= 6 else 7),
    ]
    tables = []
    for kf in keyf:
        cells = defaultdict(list)
        for q in dev:
            cells[kf(q)].append(q)
        tables.append({k: max(ROUTE_ARMS, key=lambda a: np.mean([S(q, a) for q in v])) for k, v in cells.items() if len(v) >= 8})

    def choose(q):
        for kf, t in zip(keyf, tables):
            if kf(q) in t:
                return t[kf(q)]
        return overall

    blend = json.loads((OUT / "panel_blend_report.json").read_text())["fitted_on_dev"]
    th = blend["route_threshold_nbr_entropy"]
    out = {"best_single_on_dev": overall, "rule_cells": {str(k): v for t in tables for k, v in t.items()}}
    rng = np.random.default_rng(0)
    for name, sel in (("all", lambda q: True), ("divided", lambda q: q["Hn"] >= DIV), ("divided shared", lambda q: q["Hn"] >= DIV and q["group3"] == "shared_survey"),
                      ("divided pop_only_task", lambda q: q["Hn"] >= DIV and q["group3"] == "pop_only_task"), ("pop_only_task all", lambda q: q["group3"] == "pop_only_task")):
        qq = [q for q in ev if sel(q)]
        rule = np.array([S(q, choose(q)) for q in qq])
        base = np.array([S(q, BASE) for q in qq])
        nbr = np.array([S(q, "P_adapt" if (not math.isnan(q["nbr_h"]) and q["nbr_h"] < th) else "panel") for q in qq])
        d = rule - base
        b = np.sort([rng.choice(d, len(d)).mean() for _ in range(1000)])
        out[name] = {
            "n": len(qq),
            "rule_S": round(float(rule.mean()), 2),
            "rule_vs_retr6_rev2": [round(float(d.mean()), 2), round(float(b[25]), 2), round(float(b[975]), 2)],
            "always_retr6_rev2": round(float(base.mean()), 2),
            "best_single_dev_arm": round(float(np.mean([S(q, overall) for q in qq])), 2),
            "neighbour_router_P_adapt_or_panel": round(float(nbr.mean()), 2),
        }
    return out


# ------------------------------------------------------------------ orchestration


def _headline(df: pd.DataFrame, sel) -> dict:
    d = df[sel]
    tv = d.TVD.sum()
    sh = {k: float(d[f"phi_{k}"].sum() / tv) for k in FIXES}
    al = {k: float(d[f"alone_{k}"].sum() / tv) for k in FIXES}
    pk = d[(d.get("true2_pred1", 0) == 1) | (d.get("true1_pred2", 0) == 1)]
    # per-question bootstrap of the shares
    rng = np.random.default_rng(0)
    boots = defaultdict(list)
    arr = d[[f"phi_{k}" for k in FIXES] + ["TVD"]].to_numpy()
    for _ in range(1000):
        b = arr[rng.integers(0, len(arr), len(arr))]
        for j, k in enumerate(FIXES):
            boots[k].append(b[:, j].sum() / b[:, -1].sum())
    return {
        "n": int(len(d)), "S": round(float(d.S.mean()), 2),
        "shapley_share": {k: round(v, 3) for k, v in sh.items()},
        "shapley_ci": {k: [round(float(np.percentile(boots[k], 2.5)), 3), round(float(np.percentile(boots[k], 97.5)), 3)] for k in FIXES},
        "alone_share": {k: round(v, 3) for k, v in al.items()},
        "interaction_share": round(1 - sum(al.values()), 3),
        "peaks_questions": int(len(pk)), "peaks_tvd_share": round(float(pk.TVD.sum() / tv), 3) if tv else None,
        "S_fix": {k: round(float(d[f"S_fix_{k}"].mean()), 2) for k in FIXES},
    }


def _qbrief(q, p):
    return {
        "qid": q["qid"], "dataset": q["dataset"], "format": q["format"],
        "question": q["question"].split("Options:")[0].strip()[-300:],
        "options": {k: q["texts"].get(k, k)[:60] for k in q["keys"]},
        "truth": [round(float(x), 3) for x in q["h"]], "pred": [round(float(x), 3) for x in p],
        "S": round(100 * (1 - tvd(p, q["h"]) / q["norm"]), 1), "TVD": round(tvd(p, q["h"]), 3),
        "profile_error": round(tvd(np.sort(p)[::-1], np.sort(q["h"])[::-1]), 3), "Hn_truth": round(q["Hn"], 3), "Hn_pred": round(Hn(p), 3),
    }


def main():
    import pickle

    ev, dev = load("eval"), load("dev")
    for qs, w in ((ev, "eval"), (dev, "dev")):
        derived_levers(qs, w)
        demo_avg_lever(qs, w)
    df = pd.concat([part1(ev), part1(dev)], ignore_index=True)
    rep = {"counts": {}}
    for nm, qs in (("eval", ev), ("dev", dev)):
        div = [q for q in qs if q["Hn"] >= DIV]
        rep["counts"][nm] = {"all": len(qs), "divided": len(div),
                             "by_group3_format": pd.Series([f"{q['group3']}/{q['format']}" for q in div]).value_counts().to_dict()}
    rep["part1_summary"] = summarize_part1(df)
    head = {}
    for s in ("eval", "dev"):
        for arm in ("retr6_rev2", "panel", "B_n3_soft_rev2"):
            for g3 in ("shared_survey", "pop_only_task", "other_pop_only"):
                for fmt in ("ordinal", "all"):
                    sel = (df.set == s) & (df.arm == arm) & (df.group3 == g3) & ((df.format == fmt) if fmt != "all" else True)
                    if sel.sum() >= 5:
                        head[f"{s}/{arm}/{g3}/{fmt}"] = _headline(df, sel)
    rep["headline"] = head
    dom = df[df.arm == BASE].set_index("qid")["dominant"].to_dict()
    byq = {q["qid"]: q for q in ev + dev}
    worst = {}
    for g in ("shared_survey",) + TASKS + ("other_pop_only",):
        d = df[(df.set == "eval") & (df.arm == BASE) & (df.group == g)].sort_values("S").head(10)
        worst[g] = [{**_qbrief(byq[r.qid], byq[r.qid]["preds"][BASE]), "dominant": r.dominant,
                     "phi": {k: round(float(getattr(r, f"phi_{k}")), 3) for k in FIXES}} for r in d.itertuples()]
    rep["worst10"] = worst
    # worked examples: spread right, mass wrong (eval, baseline)
    d = df[(df.set == "eval") & (df.arm == BASE) & (df.profile_error <= 0.06) & (df.TVD >= 0.25)].sort_values("TVD", ascending=False)
    ex, seen = [], set()
    for r in d.itertuples():
        if r.dataset in seen:
            continue
        seen.add(r.dataset)
        ex.append({**_qbrief(byq[r.qid], byq[r.qid]["preds"][BASE]), "dominant": r.dominant})
        if len(ex) == 4:
            break
    rep["worked_examples"] = ex
    rep["spread_right_mass_wrong_rate"] = {}
    for s in ("eval", "dev"):
        b = df[(df.set == s) & (df.arm == BASE)]
        rep["spread_right_mass_wrong_rate"][s] = {
            "n": int(len(b)), "abs_entropy_gap_le_0.05": round(float((b.entropy_gap.abs() <= 0.05).mean()), 3),
            "of_those_TVD_ge_0.2": round(float((b[b.entropy_gap.abs() <= 0.05].TVD >= 0.2).mean()), 3),
            "mean_abs_entropy_gap": round(float(b.entropy_gap.abs().mean()), 3), "mean_TVD": round(float(b.TVD.mean()), 3),
            "mean_profile_error": round(float(b.profile_error.mean()), 3),
        }
    rep["lever_matrix"] = {"eval": lever_matrix(ev, dom), "dev": lever_matrix(dev, dom)}
    nb = lambda q: not math.isnan(q["nbr_h"]) and q["nbr_h"] >= DIV  # noqa: E731
    rep["lever_matrix_truthfree"] = {"eval": lever_matrix(ev, {}, nb), "dev": lever_matrix(dev, {}, nb)}
    rep["lever_matrix_allq"] = {"eval": lever_matrix(ev, {}, lambda q: True), "dev": lever_matrix(dev, {}, lambda q: True)}
    rep["truthfree_slice_sizes"] = {w: {"n": sum(nb(q) for q in qs), "truly_divided": sum(nb(q) and q["Hn"] >= DIV for q in qs),
                                        "divided_caught": sum(nb(q) for q in qs if q["Hn"] >= DIV), "divided": sum(q["Hn"] >= DIV for q in qs)}
                                    for w, qs in (("eval", ev), ("dev", dev))}
    rep["lever_components"] = {"eval": lever_components(ev), "dev": lever_components(dev)}
    rep["mechanism_eval"] = mechanism(ev)
    rep["routing"] = routing(dev, ev)
    (OUT / "mass_levers_report.json").write_text(json.dumps(rep, indent=1, default=float))
    with open(OUT / "mass_levers_part1.pkl", "wb") as f:
        pickle.dump({"df": df, "examples": ex}, f)
    print(json.dumps({k: head[k] for k in head if "/retr6_rev2/" in k}, indent=1))
    return rep


# ------------------------------------------------------------------ plots

S1, S2, S3, S4, BG = "#2a78d6", "#eb6834", "#8a8f98", "#3aa37a", "#fcfcfb"


def plots():
    import pickle

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rep = json.loads((OUT / "mass_levers_report.json").read_text())
    df = pickle.load(open(OUT / "mass_levers_part1.pkl", "rb"))["df"]
    plt.rcParams.update({"figure.facecolor": BG, "axes.facecolor": BG, "font.size": 9, "axes.spines.top": False, "axes.spines.right": False})

    # 1. decomposition: Shapley shares per group x arm (eval)
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8), sharey=True)
    for ax, fmt in zip(axes, ("ordinal", "all")):
        labels, vals = [], []
        for g3 in ("shared_survey", "pop_only_task", "other_pop_only"):
            for arm, lab in (("retr6_rev2", "retr6_rev2"), ("panel", "panel"), ("B_n3_soft_rev2", "segments")):
                h = rep["headline"].get(f"eval/{arm}/{g3}/{fmt}")
                if not h:
                    continue
                sh = h["shapley_share"]
                labels.append(f"{g3.replace('_', ' ')}\n{lab} (n={h['n']})")
                vals.append([sh["location"], sh["assignment"], sh["profile"], 1 - sum(sh.values())])
        vals = np.array(vals) * 100
        left = np.zeros(len(vals))
        for j, (nm, c) in enumerate(zip(("location", "order beyond location", "shape (profile)", "rest / interaction"), (S1, S2, S4, S3))):
            ax.barh(range(len(vals)), vals[:, j], left=left, color=c, label=nm)
            for k, v in enumerate(vals[:, j]):
                if v >= 7:
                    ax.text(left[k] + v / 2, k, f"{v:.0f}", ha="center", va="center", color="white", fontsize=8)
            left += vals[:, j]
        ax.set_yticks(range(len(vals)), labels, fontsize=7.5)
        ax.invert_yaxis()
        ax.set_xlim(0, 100)
        ax.set_xlabel("% of total TVD (Shapley)")
        ax.set_title(f"Divided questions, eval: {'ordinal only' if fmt == 'ordinal' else 'all formats'}")
    axes[0].legend(loc="lower center", bbox_to_anchor=(1.0, -0.32), ncol=4, frameon=False)
    fig.tight_layout()
    fig.subplots_adjust(wspace=0.04)
    fig.savefig(IMG / "mass_decomposition.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # 2. lever x slice heatmaps (eval): truth-divided vs all questions
    levers = ["fs_k6", "retr6", "demo_average", "gemini_retr6", "panel", "P_adapt", "blend_panel_retr6", "B_n3_soft", "B_n3_soft_rev2",
              "B_agents", "B_adaptive", "mix_panel_segments", "retr6_rev2_pull29", "panel_pull29", "even_split"]
    slices = ["all divided", "group: shared_survey", "group: other_pop_only", "group: OSPsychMACH", "group: Choices13k", "group: NumberGame",
              "group: OSPsychMGKT", "format: ordinal", "format: binary", "format: categorical", "value-laden: yes", "value-laden: no"]
    fig, axes = plt.subplots(1, 3, figsize=(17, 5.6), sharey=True)
    for ax, key, title in zip(axes, ("lever_matrix", "lever_matrix_truthfree", "lever_matrix_allq"),
                              ("Truly divided (truth entropy >= 0.84; diagnostic)", "Predicted divided (neighbour entropy >= 0.84)", "All questions")):
        m = rep[key]["eval"]
        M_ = np.full((len(slices), len(levers)), np.nan)
        N_ = np.zeros_like(M_)
        for i, sl in enumerate(slices):
            for j, lv in enumerate(levers):
                c = m.get(sl, {}).get("levers", {}).get(lv)
                if c:
                    M_[i, j], N_[i, j] = c["dS"], c["n"]
        im = ax.imshow(np.clip(M_, -30, 30), cmap="RdBu", vmin=-30, vmax=30, aspect="auto")
        for i in range(len(slices)):
            for j in range(len(levers)):
                if not np.isnan(M_[i, j]):
                    ax.text(j, i, f"{M_[i, j]:+.0f}" + ("*" if N_[i, j] < 30 else ""), ha="center", va="center", fontsize=6.5)
        ax.set_xticks(range(len(levers)), levers, rotation=60, ha="right", fontsize=7)
        ax.set_yticks(range(len(slices)), [s if s != "all divided" else "all (this selection)" for s in slices], fontsize=7.5)
        ax.set_title(title, fontsize=9)
    fig.colorbar(im, ax=axes, shrink=0.6, label="ΔS vs retr6_rev2 (clipped ±30)")
    fig.savefig(IMG / "lever_slice_heatmap.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # 3. worked examples
    ex = rep["worked_examples"]
    fig, axes = plt.subplots(1, len(ex), figsize=(3.6 * len(ex), 3.4))
    for ax, e in zip(np.atleast_1d(axes), ex):
        k = list(e["options"].keys())
        x = np.arange(len(k))
        ax.bar(x - 0.2, e["truth"], 0.4, color=S1, label="real people")
        ax.bar(x + 0.2, e["pred"], 0.4, color=S2, label="retr6_rev2")
        ax.set_xticks(x, [e["options"][kk][:14] for kk in k], rotation=35, ha="right", fontsize=7)
        ax.set_title(f"{e['dataset']} (S={e['S']:.0f})\nentropy {e['Hn_truth']:.2f} vs {e['Hn_pred']:.2f}; shape err {e['profile_error']:.2f}", fontsize=8)
        ax.set_ylim(0, 0.8)
    np.atleast_1d(axes)[0].legend(frameon=False, fontsize=7)
    fig.tight_layout()
    fig.savefig(IMG / "mass_worked_examples.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    import sys

    plots() if sys.argv[1:] == ["plots"] else main()
