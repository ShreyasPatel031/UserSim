"""Which outside data moves HUMAINE scores, and which calibration carries over between benchmarks.

Three tracks, reported separately (never mixed):
  zero_data   only external sources: LMArena leaderboard + votes, SimBench (a different benchmark), product metadata.
              No HUMAINE row is used to choose, fit or tune anything.
  pilot       simulates a customer running a small study: N HUMAINE conversations are drawn at random as the 'pilot',
              used to calibrate tie share and confidence, and REMOVED from every cell they belong to before scoring.
  diagnostic  uses HUMAINE answers to split the remaining error into 'tie share' vs 'who wins'. Not a method; it only
              says which kind of data would close the gap.

Transfers tested (all fixed before looking at HUMAINE scores, except where marked post hoc)
  arena_tie_<v>   tie share from LMArena votes (140k): v = 'tie' (15.9%) or 'tie_bothbad' (27.5%, the variant
                  written into humaine_external.py before any score existed). Decisive split kept from the arm.
  simbench_T      temperature fitted on Gemini 2.5 Flash vs humans on SimBench (981 questions), applied unchanged.
  simbench_mix    uniform-mix weight fitted the same way.
  simbench_ind    indifference shift: how far Gemini under/over-predicts 'neither / neutral / about the same'
                  options on SimBench, applied to the HUMAINE tie option (logit shift).
  arena_dims      no-LLM Elo predictor per dimension from a pre-declared arena category (see DIM_CATEGORY).

Writes results/humaine/transfer.json."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from human_sim import humaine_bench as HB
from human_sim import humaine_external as X
from human_sim.humaine_eval import load_preds

OUT = HB.OUT
SIMBENCH_PREDS = HB.ROOT / "results" / "simbench_ablate" / "base_gemini-2.5-flash_p25g100s7.json"
ARENA_TIE_ONLY = 21532 / 135634
ARENA_TIE_BOTHBAD = X.ARENA_TIE_RATE
# Arena category used for each HUMAINE dimension (declared before scoring; trust has no arena analogue).
DIM_CATEGORY = {"overall_winner": ("text", "overall"), "core_task_performance_and_reasoning": ("text", "hard_prompts"),
                "interaction_fluidity_and_adaptiveness": ("text", "multi_turn"),
                "communication_style_and_presentation": ("text", "creative_writing"), "trust_ethics_and_safety": ("text", "overall")}
IND = re.compile(r"\b(neither|no difference|about the same|the same|same as|equally|tie|no preference|indifferent|neutral|no opinion|undecided|in between|in the middle)\b", re.I)
DK = re.compile(r"(don.?t know|refused|no answer|not sure|can.?t choose|cannot choose|prefer not)", re.I)
OPT = re.compile(r"^\(([A-Z])\):\s*(.+)$", re.M)


# ------------------------------------------------------------------ transforms on [first wins, second wins, tie]
def with_tie(p, t):
    p = np.asarray(p, float)
    d = p[:2].sum()
    split = p[:2] / d if d > 0 else np.array([0.5, 0.5])
    return np.array([(1 - t) * split[0], (1 - t) * split[1], t])


def temper(p, T, eps=0.005):
    q = np.clip(np.asarray(p, float), eps, None) ** (1.0 / T)
    return q / q.sum()


def temper_split(p, T, eps=0.005):
    """Temperature on the decisive split only; tie share unchanged."""
    p = np.asarray(p, float)
    s = temper(p[:2] / max(p[:2].sum(), 1e-12), T, eps)
    return np.array([(1 - p[2]) * s[0], (1 - p[2]) * s[1], p[2]])


def mix(p, a):
    p = np.asarray(p, float)
    return (1 - a) * p + a / len(p)


def tie_shift(p, delta):
    p = np.asarray(p, float)
    t = np.clip(p[2], 1e-3, 1 - 1e-3)
    t2 = 1 / (1 + np.exp(-(np.log(t / (1 - t)) + delta)))
    return with_tie(p, t2)


# ------------------------------------------------------------------ SimBench-fitted calibration (other benchmark)
def simbench_calibration():
    cache = OUT / "simbench_calibration.json"
    if cache.exists():
        return json.loads(cache.read_text())
    from human_sim import simbench_ablate as A
    s, _, _ = A.build_env(25, 100, 7)
    d = json.loads(SIMBENCH_PREDS.read_text())
    recs = []
    for r in d["rows"]:
        if not r["ok"]:
            continue
        row = s.iloc[r["i"]]
        ha = row["human_answer"]
        keys = list(ha.keys())
        h = np.array([ha[k] for k in keys], float)
        h /= h.sum()
        g = np.array([float(r["llm_answer"].get(k, 0)) for k in keys])
        g = g / g.sum() if g.sum() > 0 else np.full(len(keys), 1 / len(keys))
        opts = dict(OPT.findall(str(row["input_template"])))
        ind = np.array([bool(IND.search(opts.get(k, ""))) and not DK.search(opts.get(k, "")) for k in keys])
        recs.append((h, g, ind))
    tvd = lambda a, b: 0.5 * np.abs(a - b).sum()
    U = np.mean([tvd(h, np.full(len(h), 1 / len(h))) for h, _, _ in recs])
    S = lambda f: 100 * (1 - np.mean([tvd(h, f(g)) for h, g, _ in recs]) / U)
    Ts = np.round(np.arange(0.7, 3.01, 0.05), 2)
    sT = [S(lambda g, T=T: temper(g, T)) for T in Ts]
    As = np.round(np.arange(0, 0.61, 0.02), 2)
    sA = [S(lambda g, a=a: mix(g, a)) for a in As]
    lo = lambda p: np.log(np.clip(p, 1e-3, 1 - 1e-3) / (1 - np.clip(p, 1e-3, 1 - 1e-3)))
    H = np.array([h[i].sum() for h, _, i in recs if i.any()])
    G = np.array([g[i].sum() for _, g, i in recs if i.any()])
    out = {"questions": len(recs), "S_raw": round(S(lambda g: g), 2),
           "T": float(Ts[int(np.argmax(sT))]), "S_T": round(float(max(sT)), 2),
           "mix": float(As[int(np.argmax(sA))]), "S_mix": round(float(max(sA)), 2),
           "indiff_questions": int(len(H)), "indiff_human_mean": round(float(H.mean()), 4), "indiff_gemini_mean": round(float(G.mean()), 4),
           "indiff_logit_shift": round(float(np.mean(lo(H) - lo(G))), 4)}
    cache.write_text(json.dumps(out, indent=1))
    return out


# ------------------------------------------------------------------ arena per-dimension direct predictor
def arena_dims_pred(m1, m2, tie):
    out = {}
    for m, (board, cat) in DIM_CATEGORY.items():
        r1, r2 = X.arena_rating(m1, cat), X.arena_rating(m2, cat)
        if r1 is None or r2 is None:
            r1, r2 = X.arena_rating(m1), X.arena_rating(m2)
        if r1 is None or r2 is None:
            out[m] = [1 / 3] * 3
            continue
        p = 1 / (1 + 10 ** ((r2 - r1) / 400))
        out[m] = [(1 - tie) * p, (1 - tie) * (1 - p), tie]
    return out


# ------------------------------------------------------------------ scoring
def score_all(P, pred_of):
    """pred_of(row, metric) -> 3-vector. Returns S per dimension (+CI) and P4 extras on overall."""
    row = {}
    for m in HB.METRICS:
        reals = np.stack(P[f"real_{m}"].to_numpy())
        preds = np.stack([pred_of(r, m) for r in P.itertuples()])
        norm = float(np.mean(HB.tvd(np.full(3, 1 / 3), reals)))
        s = 100 * (1 - HB.tvd(preds, reals) / norm)
        row[m] = {"S": round(float(s.mean()), 2), "ci": HB.bootstrap_ci(s, B=500)}
    return row


def mean_reasons(row):
    return round(float(np.mean([row[m]["S"] for m in HB.METRICS[1:]])), 2)


# ------------------------------------------------------------------ pilot track
def wide_frame(f):
    return f.pivot_table(index=["conversation_id", "m1", "m2", "age_band", "country", "leaning", "edu", "eth"], columns="metric",
                         values="y", aggfunc="first").reset_index()


def cells_without(P, wide, drop_ids, by_pair):
    """Recompute the real distributions of every cell that contains a dropped conversation."""
    dw = wide[wide.conversation_id.isin(drop_ids)]
    P2 = P.copy()
    affected = set()
    for r in dw.itertuples():
        affected.add(f"{r.m1}|{r.m2}|all=None")
        for k in ("age_band", "country", "leaning", "edu", "eth"):
            affected.add(f"{r.m1}|{r.m2}|{k}={getattr(r, k)}")
    idx = P2.index[P2.cell.isin(affected)]
    for i in idx:
        r = P2.loc[i]
        g = by_pair[(r.m1, r.m2)]
        g = g[~g.conversation_id.isin(drop_ids)]
        if r.seg_key != "all":
            g = g[g[r.seg_key] == r.seg_val]
        if len(g) < HB.MIN_N:
            P2.loc[i, "n"] = -1
            continue
        P2.loc[i, "n"] = len(g)
        for m in HB.METRICS:
            P2.at[i, f"real_{m}"] = (np.bincount(g[m].dropna().astype(int), minlength=3) / max(g[m].notna().sum(), 1)).tolist()
    return P2[P2.n > 0].reset_index(drop=True)


def fit_pilot(pilot, preds_by_pair, prior_tie, prior_strength=10):
    """From pilot conversations: tie share per dimension (Beta prior at the external tie share) and one temperature on
    the decisive split (maximum likelihood over pilot decisive votes, grid 0.3-5)."""
    cal = {}
    for m in HB.METRICS:
        y = pilot[m].dropna().astype(int).to_numpy()
        cal[f"tie_{m}"] = float(((y == 2).sum() + prior_strength * prior_tie) / (len(y) + prior_strength))
    Ts = np.exp(np.linspace(np.log(0.3), np.log(5), 41))
    ll = np.zeros(len(Ts))
    for r in pilot.itertuples():
        base = preds_by_pair.get((r.m1, r.m2))
        if base is None:
            continue
        for m in HB.METRICS:
            y = getattr(r, m)
            if pd.isna(y) or int(y) == 2:
                continue
            p = np.asarray(base[m], float)
            d = p[:2] / max(p[:2].sum(), 1e-12)
            for j, T in enumerate(Ts):
                q = np.clip(d, 0.005, None) ** (1 / T)
                q /= q.sum()
                ll[j] += np.log(q[int(y)])
    cal["T"] = float(Ts[int(np.argmax(ll))]) if ll.any() else 1.0
    return cal


def pilot_track(P, f, arm_preds, sizes=(25, 50, 100, 200, 400), reps=8, seed=0):
    wide = wide_frame(f)
    groups = {k: g for k, g in wide.groupby(["m1", "m2"])}
    ids = wide.conversation_id.to_numpy()
    rng = np.random.default_rng(seed)
    out = {}
    # pair-level (segment 'all') predictions are what a pilot calibrates against
    for arm, pr in arm_preds.items():
        by_pair = {(r.m1, r.m2): pr[r.cell] for r in P.itertuples() if r.seg_key == "all" and r.cell in pr}
        res = {}
        for n in sizes:
            S_over, S_reason = [], []
            for _ in range(reps):
                pick = rng.choice(ids, size=n, replace=False)
                pilot = wide[wide.conversation_id.isin(pick)]
                cal = fit_pilot(pilot, by_pair, ARENA_TIE_ONLY)
                P2 = cells_without(P, wide, set(pick), groups)
                row = score_all(P2, lambda r, m: temper_split(with_tie(pr[r.cell][m], cal[f"tie_{m}"]), cal["T"]))
                S_over.append(row["overall_winner"]["S"])
                S_reason.append(mean_reasons(row))
            res[str(n)] = {"overall_S": round(float(np.mean(S_over)), 2), "overall_sd": round(float(np.std(S_over)), 2),
                           "reasons_mean_S": round(float(np.mean(S_reason)), 2), "reasons_sd": round(float(np.std(S_reason)), 2)}
            print(f"  pilot {arm} n={n}: overall {res[str(n)]['overall_S']} reasons {res[str(n)]['reasons_mean_S']}", flush=True)
        out[arm] = res
    return out


# ------------------------------------------------------------------ main
def run(with_pilot=True):
    f, _ = HB.load()
    P = pd.read_pickle(OUT / "p4_cells.pkl")
    sbc = simbench_calibration()
    arms = {}
    for a in ("plain", "meta", "arena"):
        pr = load_preds(a, "p4")
        if pr and len(pr) >= 0.98 * len(P):
            arms[f"gemini_{a}"] = {k: v["pred"] for k, v in pr.items()}
    P = P[P.cell.isin(set.intersection(*[set(v) for v in arms.values()]))].reset_index(drop=True)
    res = {"cells": int(len(P)), "simbench_calibration": sbc, "zero_data": {}, "diagnostic": {}, "pilot": {}}

    zd = res["zero_data"]
    zd["uniform"] = score_all(P, lambda r, m: [1 / 3] * 3)
    for arm, pr in arms.items():
        variants = {
            "": lambda r, m: pr[r.cell][m],
            "+arena_tie_tie_bothbad": lambda r, m: with_tie(pr[r.cell][m], ARENA_TIE_BOTHBAD),
            "+arena_tie_tie": lambda r, m: with_tie(pr[r.cell][m], ARENA_TIE_ONLY),
            "+simbench_T": lambda r, m: temper(pr[r.cell][m], sbc["T"]),
            "+simbench_mix": lambda r, m: mix(pr[r.cell][m], sbc["mix"]),
            "+simbench_ind": lambda r, m: tie_shift(pr[r.cell][m], sbc["indiff_logit_shift"]),
            "+arena_tie_tie+simbench_T": lambda r, m: temper_split(with_tie(pr[r.cell][m], ARENA_TIE_ONLY), sbc["T"]),
        }
        for name, fn in variants.items():
            zd[arm + name] = score_all(P, fn)
    for name, t in (("arena_dims_tie_bothbad", ARENA_TIE_BOTHBAD), ("arena_dims_tie", ARENA_TIE_ONLY)):
        cache = {}
        def fn(r, m, t=t, cache=cache):
            if (r.m1, r.m2) not in cache:
                cache[(r.m1, r.m2)] = arena_dims_pred(r.m1, r.m2, t)
            return cache[(r.m1, r.m2)][m]
        zd[name] = score_all(P, fn)

    # diagnostics: what if the tie share (global per dimension) or the decisive split (per cell) were known
    tie = {m: float((f[f.metric == m].y == 2).mean()) for m in HB.METRICS}
    dg = res["diagnostic"]
    dg["humaine_tie_rate"] = {m: round(v, 4) for m, v in tie.items()}
    for arm, pr in arms.items():
        dg[arm + "+known_tie_share"] = score_all(P, lambda r, m: with_tie(pr[r.cell][m], tie[m]))
        def known_split(r, m, pr=pr):
            real = np.asarray(getattr(r, f"real_{m}"), float)
            return with_tie(real, np.asarray(pr[r.cell][m])[2])
        dg[arm + "+known_split"] = score_all(P, known_split)

    if with_pilot:
        res["pilot"] = pilot_track(P, f, {k: arms[k] for k in arms if k in ("gemini_plain", "gemini_arena")})
    (OUT / "transfer.json").write_text(json.dumps(res, indent=1))
    return res


def show(res):
    print(f"cells {res['cells']}; SimBench calibration: {res['simbench_calibration']}")
    for track in ("zero_data", "diagnostic"):
        print(f"--- {track}")
        for k, row in res[track].items():
            if not isinstance(row, dict) or not isinstance(row.get("overall_winner"), dict):
                continue
            print(f"{k:44s} overall {row['overall_winner']['S']:6.1f}  reasons mean {mean_reasons(row):6.1f}  "
                  + " / ".join(f"{row[m]['S']:.1f}" for m in HB.METRICS[1:]))
    if res.get("pilot"):
        print("--- pilot", json.dumps(res["pilot"], indent=1))


if __name__ == "__main__" and "--pilot-evidence" not in sys.argv:
    show(run(with_pilot="--no-pilot" not in sys.argv))


# ------------------------------------------------------------------ pilot as evidence: arena prior updated by pilot votes
PRIOR_SD = 0.5  # prior SD of log-strength around the arena rating (about 87 Elo); fixed before any run, not tuned


def bt_posterior(votes, products, prior_mu, sd=PRIOR_SD):
    """MAP Bradley-Terry log-strengths: Gaussian prior at the arena rating, likelihood from pilot decisive votes."""
    from scipy.optimize import minimize
    ix = {p: i for i, p in enumerate(products)}
    if not votes:
        return dict(zip(products, prior_mu))
    a = np.array([ix[w] for w, _ in votes])
    b = np.array([ix[l] for _, l in votes])

    def f(th):
        d = th[a] - th[b]
        nll = np.sum(np.logaddexp(0, -d)) + np.sum((th - prior_mu) ** 2) / (2 * sd ** 2)
        s = 1 / (1 + np.exp(d))  # = 1 - sigmoid(d)
        g = (th - prior_mu) / sd ** 2
        np.add.at(g, a, -s)
        np.add.at(g, b, s)
        return nll, g
    th = minimize(f, prior_mu.copy(), jac=True, method="L-BFGS-B").x
    return dict(zip(products, th))


def pilot_evidence_track(P, f, gem_arena, sizes=(25, 50, 100, 200, 400), reps=8, seed=1):
    wide = wide_frame(f)
    groups = {k: g for k, g in wide.groupby(["m1", "m2"])}
    ids = wide.conversation_id.to_numpy()
    products = sorted(set(wide.m1) | set(wide.m2))
    r = np.array([X.arena_rating(p) if X.arena_rating(p) is not None else np.nan for p in products])
    mu = (r - np.nanmean(r)) * np.log(10) / 400
    mu = np.where(np.isnan(mu), 0.0, mu)
    by_pair = {(row.m1, row.m2): gem_arena[row.cell] for row in P.itertuples() if row.seg_key == "all" and row.cell in gem_arena}
    rng = np.random.default_rng(seed)
    out = {}
    for n in sizes:
        acc = {"evidence": [], "evidence_reasons": [], "calib_only": [], "calib_only_reasons": [], "prior_only": []}
        for _ in range(reps):
            pick = rng.choice(ids, size=n, replace=False)
            pilot = wide[wide.conversation_id.isin(pick)]
            cal = fit_pilot(pilot, by_pair, ARENA_TIE_ONLY)
            theta = {}
            for m in HB.METRICS:
                votes = [((row.m1, row.m2) if int(getattr(row, m)) == 0 else (row.m2, row.m1)) for row in pilot.itertuples()
                         if not pd.isna(getattr(row, m)) and int(getattr(row, m)) != 2]
                theta[m] = bt_posterior(votes, products, mu)
            P2 = cells_without(P, wide, set(pick), groups)

            def ev(row, m):
                p = 1 / (1 + np.exp(-(theta[m][row.m1] - theta[m][row.m2])))
                t = cal[f"tie_{m}"]
                return [(1 - t) * p, (1 - t) * (1 - p), t]

            def prior_only(row, m):
                p = 1 / (1 + np.exp(-(mu[products.index(row.m1)] - mu[products.index(row.m2)])))
                t = cal[f"tie_{m}"]
                return [(1 - t) * p, (1 - t) * (1 - p), t]
            e = score_all(P2, ev)
            c = score_all(P2, lambda row, m: temper_split(with_tie(gem_arena[row.cell][m], cal[f"tie_{m}"]), cal["T"]))
            po = score_all(P2, prior_only)
            acc["evidence"].append(e["overall_winner"]["S"]); acc["evidence_reasons"].append(mean_reasons(e))
            acc["calib_only"].append(c["overall_winner"]["S"]); acc["calib_only_reasons"].append(mean_reasons(c))
            acc["prior_only"].append(po["overall_winner"]["S"])
        out[str(n)] = {k: round(float(np.mean(v)), 2) for k, v in acc.items()} | {"evidence_sd": round(float(np.std(acc["evidence"])), 2)}
        print(f"  evidence n={n}: {out[str(n)]}", flush=True)
    return out


if __name__ == "__main__" and "--pilot-evidence" in sys.argv:
    f, _ = HB.load()
    P = pd.read_pickle(OUT / "p4_cells.pkl")
    ga = {k: v["pred"] for k, v in load_preds("arena", "p4").items()}
    res = json.loads((OUT / "transfer.json").read_text()) if (OUT / "transfer.json").exists() else {}
    res["pilot_evidence"] = {"prior_sd": PRIOR_SD, "note": "arena-rating prior on Bradley-Terry log-strengths, updated with pilot votes per dimension; tie share from the pilot; pilot conversations removed from scored cells",
                             "results": pilot_evidence_track(P, f, ga)}
    (OUT / "transfer.json").write_text(json.dumps(res, indent=1))
