"""Where is the divided-question error, and is it within or across demographics?

Step A  decompose real disagreement into within-group and between-group parts (no calls)
Step B  error anatomy of logged Haiku predictions on divided questions (no calls)
Step C  common-mode vs group-specific error, direction of group gaps (logged group outputs)

Usage:
  PYTHONPATH=src python -m human_sim.simbench_divided_anatomy A|B|C
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from human_sim.simbench_ablate import OUT_DIR, ROOT, _as_dict, _country_of, _COUNTRY_KEYS

SHARED = ("Afrobarometer", "ESS", "ISSP", "LatinoBarometro", "OpinionQA")
POP_ONLY_TASKS = ("OSPsychMACH", "Choices13k", "NumberGame", "OSPsychMGKT")
DIVIDED = 0.84
MIN_CELL = 100
rng = np.random.default_rng(0)


def H(p: np.ndarray) -> float:
    q = p[p > 0]
    return float(-(q * np.log(q)).sum())


def Hn(p: np.ndarray) -> float:
    return H(p) / np.log(len(p)) if len(p) > 1 else 0.0


def grouped_cells() -> dict:
    """(dataset, country, question, attribute) -> [(value, size, answer dict)] for
    single-attribute cells with at least MIN_CELL respondents."""
    g = pd.read_csv(ROOT / "data" / "simbench" / "SimBenchGrouped.csv")
    cells = defaultdict(list)
    for _, r in g.iterrows():
        vm = _as_dict(r["group_prompt_variable_map"])
        ha = _as_dict(r["human_answer"])
        other = [k for k in vm if k not in _COUNTRY_KEYS]
        if len(other) == 1 and r["group_size"] >= MIN_CELL and len(ha) > 1:
            cells[(r["dataset_name"], _country_of(vm), r["input_template"], other[0])].append(
                (str(vm[other[0]]), float(r["group_size"]), ha)
            )
    return {k: v for k, v in cells.items() if len(v) >= 2}


def decompose(cells: list) -> dict:
    keys = list(cells[0][2].keys())
    P = np.array([[c[2].get(k, 0.0) for k in keys] for c in cells], dtype=float)
    P = P / P.sum(axis=1, keepdims=True)
    n = np.array([c[1] for c in cells])
    w = n / n.sum()
    mix = w @ P
    within = float(sum(wi * H(p) for wi, p in zip(w, P)))
    total = H(mix)
    between = total - within  # = generalized Jensen-Shannon divergence
    # sampling-noise floor: same mixture, each cell redrawn with its own size
    sims = []
    for _ in range(200):
        Q = np.array([rng.multinomial(int(ni), mix) / ni for ni in n])
        sims.append(H(w @ Q) - sum(wi * H(q) for wi, q in zip(w, Q)))
    noise = float(np.mean(sims))
    return {
        "k": len(cells),
        "total_H": total,
        "Hn_mix": Hn(mix),
        "between": between,
        "between_share": between / total if total > 0 else 0.0,
        "noise_between": noise,
        "between_share_net": max(between - noise, 0.0) / total if total > 0 else 0.0,
        "min_cell": float(n.min()),
    }


def step_a() -> dict:
    cells = grouped_cells()
    rows = []
    for (ds, country, q, att), cs in cells.items():
        d = decompose(cs)
        d.update({"dataset": ds, "country": country, "attribute": att, "question": q[:160]})
        rows.append(d)
    df = pd.DataFrame(rows)
    df["type"] = np.where(df.Hn_mix >= DIVIDED, "divided", np.where(df.Hn_mix >= 0.65, "mixed", "consensus"))
    out = {"min_cell": MIN_CELL, "groups_total": len(df)}
    for t in ("divided", "mixed", "consensus"):
        sub = df[df.type == t]
        out[t] = {
            "n": int(len(sub)),
            "between_share_mean": round(float(sub.between_share.mean()), 4),
            "between_share_net_mean": round(float(sub.between_share_net.mean()), 4),
            "between_share_p90": round(float(sub.between_share.quantile(0.9)), 4),
            "by_dataset": {
                ds: {
                    "n": int(len(x)),
                    "between_share": round(float(x.between_share.mean()), 4),
                    "between_share_net": round(float(x.between_share_net.mean()), 4),
                }
                for ds, x in sub.groupby("dataset")
            },
            "by_attribute_top": {
                att: {"n": int(len(x)), "between_share": round(float(x.between_share.mean()), 4)}
                for att, x in sorted(sub.groupby("attribute"), key=lambda kv: -kv[1].between_share.mean())[:8]
                if len(x) >= 15
            },
        }
    out["cell_size_quantiles"] = [float(v) for v in np.percentile(df.min_cell, [5, 50, 95])]
    df.to_json(OUT_DIR / "divided_stepA_per_question.json", orient="records", indent=1)
    (OUT_DIR / "divided_stepA_summary.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    return out




# --------------------------------------------------------------------------- #
# Step B: error anatomy
# --------------------------------------------------------------------------- #

DK_RE = re.compile(
    r"don.?t know|\bdk\b|refus|no answer|not sure|declin|can.?t choose|cannot choose|"
    r"no opinion|haven.?t heard|not applicable|prefer not|not heard enough",
    re.I,
)
NEUTRAL_RE = re.compile(
    r"neither|neutral|in between|in the middle|undecided|depends|both equally|about the same|"
    r"half and half|50.?50|mixed feelings",
    re.I,
)
POLAR_RE = re.compile(
    r"strongly|very|completely|extremely|totally|always|never|a lot|great deal|not at all|"
    r"agree|disagree|good|bad|satisf|likely|approve|favou?r|oppose|support|trust|important|"
    r"often|rarely|high|low|much|none|well|poor|excellent|fair|definitely|probably|worse|"
    r"better|more|less|increase|decrease|interested|confident|worried|happy|unhappy",
    re.I,
)


def parse_options(template: str) -> dict:
    tail = template.rsplit("Options:", 1)[1] if "Options:" in template else ""
    parts = re.split(r"\n\(([A-Z])\): ", "\n" + tail.strip())
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}


def option_roles(keys: list, texts: dict, dataset: str) -> dict:
    """keys -> role ('dk' | position in [0,1] for ordinal scales | 'cat'), plus scale flag."""
    dk = [k for k in keys if DK_RE.search(texts.get(k, ""))]
    subs = [k for k in keys if k not in dk]
    lab = [texts.get(k, "") for k in subs]
    numeric = sum(bool(re.match(r"^\s*-?\d", t)) for t in lab) >= max(2, len(lab) // 2)
    polar = len(lab) >= 3 and bool(POLAR_RE.search(lab[0])) and bool(POLAR_RE.search(lab[-1]))
    ordinal = len(subs) >= 3 and (numeric or polar or dataset.startswith("OSPsych"))
    roles = {k: "dk" for k in dk}
    for i, k in enumerate(subs):
        if ordinal:
            roles[k] = i / (len(subs) - 1)
        else:
            roles[k] = "neutral" if NEUTRAL_RE.search(texts.get(k, "")) else "cat"
    if ordinal:
        for k in subs:
            if NEUTRAL_RE.search(texts.get(k, "")):
                roles[k] = 0.5 if len(subs) % 2 == 1 else roles[k]
    return {"roles": roles, "ordinal": ordinal, "subs": subs}


def load_eval_logs(arms: list[str]) -> list[dict]:
    from human_sim.simbench_ablate import build_env

    sample, _, _ = build_env(25, 100, 7, "eval")
    norms = json.loads((OUT_DIR / "dataset_norms.json").read_text())
    data = {
        a: {r["i"]: r for r in json.loads((OUT_DIR / f"{a}_claude-haiku-4-5_p25g100s7.json").read_text())["rows"] if r.get("ok")}
        for a in arms
    }
    ids = sorted(set.intersection(*[set(v) for v in data.values()]))
    cases = []
    for i in ids:
        row = sample.iloc[i]
        keys = list(row["human_answer"].keys())
        v = lambda d: np.array([d.get(k, 0.0) for k in keys], float) / max(sum(d.get(k, 0.0) for k in keys), 1e-12)  # noqa: E731
        h = v(row["human_answer"])
        texts = parse_options(row["input_template"])
        cases.append(
            {
                "i": i,
                "split": row["split"],
                "ds": row["dataset_name"],
                "question": row["input_template"],
                "persona": str(row["group_prompt_template"]),
                "keys": keys,
                "texts": texts,
                "h": h,
                "Hn": Hn(h),
                "norm": norms[row["dataset_name"]],
                **option_roles(keys, texts, row["dataset_name"]),
                **{a: v(data[a][i]["llm_answer"]) for a in arms},
            }
        )
    return cases


def _pos_stats(c: dict, p: np.ndarray):
    pos = np.array([c["roles"][k] for k in c["subs"]], float)
    m = np.array([p[c["keys"].index(k)] for k in c["subs"]])
    if m.sum() <= 0:
        return None
    m = m / m.sum()
    mean = float((m * pos).sum())
    sd = float(np.sqrt((m * (pos - mean) ** 2).sum()))
    top = float(pos[int(np.argmax(m))])
    return mean, sd, top


def _bin5(x: float) -> int:
    return min(int(x * 5 - 1e-9), 4) if x > 0 else 0


def anatomy(cases: list[dict], arm: str) -> dict:
    out = {"n": len(cases)}
    ordc = [c for c in cases if c["ordinal"]]
    out["n_ordinal"] = len(ordc)
    # 1. signed residual by position bin (ordinal) and by role
    res = defaultdict(list)
    for c in ordc:
        r = c[arm] - c["h"]
        acc = defaultdict(float)
        for k, val in zip(c["keys"], r):
            role = c["roles"][k]
            acc["dk" if role == "dk" else f"pos{_bin5(role)}"] += val
        for b in ["pos0", "pos1", "pos2", "pos3", "pos4", "dk"]:
            res[b].append(acc.get(b, 0.0))
    out["ordinal_residual_by_position"] = {b: round(float(np.mean(v)), 4) for b, v in res.items()}
    # 2. scale shift and spread (ordinal)
    sh, sdp, sdt, pol, conf = [], [], [], [], Counter()
    for c in ordc:
        a, b = _pos_stats(c, c[arm]), _pos_stats(c, c["h"])
        if not a or not b:
            continue
        sh.append(a[0] - b[0])
        sdp.append(a[1])
        sdt.append(b[1])
        if a[2] != 0.5 and b[2] != 0.5:
            pol.append((a[2] - 0.5) * (b[2] - 0.5) < 0)
        conf[(_bin5(b[2]), _bin5(a[2]))] += 1
    out["scale_mean_shift"] = round(float(np.mean(sh)), 4) if sh else None
    out["scale_abs_shift"] = round(float(np.mean(np.abs(sh))), 4) if sh else None
    out["scale_sd_pred_vs_true"] = [round(float(np.mean(sdp)), 4), round(float(np.mean(sdt)), 4)] if sdp else None
    out["polarity_flip_rate"] = round(float(np.mean(pol)), 4) if pol else None
    out["top_option_confusion_true_by_pred"] = {f"{t}->{p}": n for (t, p), n in sorted(conf.items())}
    # 3. non-ordinal questions: mass on true top, on true runner-up, and on dk
    cat = [c for c in cases if not c["ordinal"]]
    top_r, second_r = [], []
    for c in cat:
        order = np.argsort(-c["h"])
        top_r.append(c[arm][order[0]] - c["h"][order[0]])
        if len(order) > 1:
            second_r.append(c[arm][order[1]] - c["h"][order[1]])
    out["n_categorical"] = len(cat)
    out["categorical_residual_true_top"] = round(float(np.mean(top_r)), 4) if top_r else None
    out["categorical_residual_true_second"] = round(float(np.mean(second_r)), 4) if second_r else None
    # 4. neutral / middle and dk mass
    def mass(c, p, roles):
        return float(sum(p[c["keys"].index(k)] for k in c["keys"] if c["roles"][k] in roles))
    out["dk_mass_pred_vs_true"] = [
        round(float(np.mean([mass(c, c[arm], ("dk",)) for c in cases])), 4),
        round(float(np.mean([mass(c, c["h"], ("dk",)) for c in cases])), 4),
    ]
    mid = [c for c in cases if any(c["roles"][k] in (0.5, "neutral") for k in c["keys"])]
    out["n_with_middle"] = len(mid)
    out["middle_mass_pred_vs_true"] = [
        round(float(np.mean([mass(c, c[arm], (0.5, "neutral")) for c in mid])), 4) if mid else None,
        round(float(np.mean([mass(c, c["h"], (0.5, "neutral")) for c in mid])), 4) if mid else None,
    ]
    out["top_option_right"] = round(float(np.mean([np.argmax(c[arm]) == np.argmax(c["h"]) for c in cases])), 4)
    out["TVD"] = round(float(np.mean([0.5 * np.abs(c[arm] - c["h"]).sum() for c in cases])), 4)
    out["S"] = round(float(np.mean([100 * (1 - 0.5 * np.abs(c[arm] - c["h"]).sum() / c["norm"]) for c in cases])), 2)
    out["entropy_gap"] = round(float(np.mean([Hn(c[arm]) - c["Hn"] for c in cases])), 4)
    return out


def step_b() -> dict:
    arms = ["retr6", "retr6_rev2", "P_groundall5"]
    cases = [c for c in load_eval_logs(arms) if c["Hn"] >= DIVIDED]
    groups = {
        "shared_surveys": [c for c in cases if c["ds"] in SHARED],
        "pop_only_tasks": [c for c in cases if c["ds"] in POP_ONLY_TASKS],
        "other_pop_only": [c for c in cases if c["ds"] not in SHARED and c["ds"] not in POP_ONLY_TASKS],
    }
    out = {}
    for gname, cs in groups.items():
        out[gname] = {a: anatomy(cs, a) for a in arms}
        out[gname]["by_dataset_retr6_rev2"] = {
            ds: anatomy([c for c in cs if c["ds"] == ds], "retr6_rev2")
            for ds in sorted({c["ds"] for c in cs})
        }
    worst = sorted(cases, key=lambda c: -0.5 * np.abs(c["retr6_rev2"] - c["h"]).sum())[:20]
    out["worst20_retr6_rev2"] = [
        {
            "dataset": c["ds"],
            "split": c["split"],
            "group": c["persona"][:120],
            "question": c["question"].split("Options:")[0].strip()[:300],
            "options": c["texts"],
            "truth": {k: round(float(x), 3) for k, x in zip(c["keys"], c["h"])},
            "pred": {k: round(float(x), 3) for k, x in zip(c["keys"], c["retr6_rev2"])},
            "TVD": round(0.5 * float(np.abs(c["retr6_rev2"] - c["h"]).sum()), 3),
        }
        for c in worst
    ]
    (OUT_DIR / "divided_stepB_anatomy.json").write_text(json.dumps(out, indent=1))
    return out


# --------------------------------------------------------------------------- #
# Step C: common-mode vs group-specific error
# --------------------------------------------------------------------------- #


def _corr(a: np.ndarray, b: np.ndarray) -> float | None:
    if a.std() < 1e-9 or b.std() < 1e-9:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def common_mode(groups: list[dict]) -> dict:
    """groups: [{'pred': [k x m], 'true': [k x m], 'w': [k]}] for one question each."""
    err_corr, real_corr, spec_share, pair_corr, sign_ok, btw_pred, btw_true, own_tvd = [], [], [], [], [], [], [], []
    for g in groups:
        P, T, w = np.asarray(g["pred"]), np.asarray(g["true"]), np.asarray(g["w"], float)
        w = w / w.sum()
        E = P - T
        tbar = w @ T
        D = T - tbar
        k = len(P)
        for a in range(k):
            for b in range(a + 1, k):
                c = _corr(E[a], E[b])
                if c is not None:
                    err_corr.append(c)
                c = _corr(D[a], D[b])
                if c is not None:
                    real_corr.append(c)
                btw_pred.append(0.5 * float(np.abs(P[a] - P[b]).sum()))
                btw_true.append(0.5 * float(np.abs(T[a] - T[b]).sum()))
                gap_t, gap_p = T[a] - T[b], P[a] - P[b]
                if 0.5 * np.abs(gap_t).sum() >= 0.10:
                    c = _corr(gap_p, gap_t)
                    if c is not None:
                        pair_corr.append(c)
                    j = int(np.argmax(np.abs(gap_t)))
                    sign_ok.append(np.sign(gap_p[j]) == np.sign(gap_t[j]))
        ebar = w @ E
        tot = float((E**2).sum())
        if tot > 0:
            spec_share.append(float(((E - ebar) ** 2).sum()) / tot)
        own_tvd += [0.5 * float(np.abs(E[a]).sum()) for a in range(k)]
    mean = lambda v: round(float(np.mean(v)), 4) if v else None  # noqa: E731
    return {
        "questions": len(groups),
        "group_pairs": len(btw_true),
        "error_corr_across_groups": mean(err_corr),
        "real_deviation_corr_across_groups": mean(real_corr),
        "group_specific_error_share": mean(spec_share),
        "between_group_TVD_pred": mean(btw_pred),
        "between_group_TVD_true": mean(btw_true),
        "each_group_TVD_to_own_truth": mean(own_tvd),
        "direction_pairs_with_real_gap_ge_0.10": len(sign_ok),
        "direction_sign_agreement": mean(sign_ok),
        "direction_gap_corr": mean(pair_corr),
    }


def _stepc_groups() -> list[dict]:
    from human_sim.simbench_ablate import build_env

    sample, _, _ = build_env(25, 100, 7, "stepc")
    rows = {r["i"]: r for r in json.loads((OUT_DIR / "retr6_rev2_claude-haiku-4-5_p25g100s7stepc.json").read_text())["rows"] if r.get("ok")}
    by = defaultdict(list)
    for i, r in rows.items():
        row = sample.iloc[i]
        vm = row["group_prompt_variable_map"]
        att = [k for k in vm if k not in _COUNTRY_KEYS][0]
        by[(row["dataset_name"], _country_of(vm), row["input_template"], att)].append((row, r))
    groups = []
    for key, items in by.items():
        if len(items) < 2:
            continue
        keys = list(items[0][0]["human_answer"].keys())
        v = lambda d: np.array([d.get(k, 0.0) for k in keys], float) / max(sum(d.get(k, 0.0) for k in keys), 1e-12)  # noqa: E731
        groups.append(
            {
                "dataset": key[0],
                "pred": [v(r["llm_answer"]) for _, r in items],
                "true": [v(row["human_answer"]) for row, _ in items],
                "w": [float(row["group_size"]) for row, _ in items],
            }
        )
    return groups


def _c2_groups() -> list[dict]:
    """Logged per-group answers of C2_comp_personas on questions with same-question subgroup truth."""
    from human_sim.simbench_ablate import build_env, _composition
    from human_sim.simbench_failure_mode import _oracle_index

    g = pd.read_csv(ROOT / "data" / "simbench" / "SimBenchGrouped.csv")
    oidx = _oracle_index(g)
    groups = []
    for which, suf in (("dev", "dev10x40"), ("eval", "")):
        sample, _, ctx = build_env(25, 100, 7, which)
        rows = {r["i"]: r for r in json.loads((OUT_DIR / f"C2_comp_personas_claude-haiku-4-5_p25g100s7{suf}.json").read_text())["rows"] if r.get("ok")}
        for i, r in rows.items():
            row = sample.iloc[i]
            comp = _composition(row, ctx)
            if not comp:
                continue
            att = comp[0]["attribute"]
            truth = {t[0]: (t[1], t[2]) for t in oidx.get((row["dataset_name"], _country_of(row["group_prompt_variable_map"]), row["input_template"], att), [])}
            keys = list(row["human_answer"].keys())
            v = lambda d: np.array([d.get(k, 0.0) for k in keys], float) / max(sum(d.get(k, 0.0) for k in keys), 1e-12)  # noqa: E731
            pred = {sg["desc"].split(" = ", 1)[1]: sg["dist"] for sg in r.get("segments", [])}
            common = [x for x in pred if x in truth]
            if len(common) >= 2:
                groups.append(
                    {
                        "dataset": row["dataset_name"],
                        "pred": [v(pred[x]) for x in common],
                        "true": [v(truth[x][1]) for x in common],
                        "w": [truth[x][0] for x in common],
                    }
                )
    return groups


def step_c() -> dict:
    sc = _stepc_groups()
    c2 = _c2_groups()
    out = {
        "stepc_cells_retr6_rev2": common_mode(sc),
        "stepc_by_dataset": {ds: common_mode([g for g in sc if g["dataset"] == ds]) for ds in sorted({g["dataset"] for g in sc})},
        "c2_country_level_groups": common_mode(c2),
    }
    (OUT_DIR / "divided_stepC_common_mode.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    return out


# --------------------------------------------------------------------------- #
# Step D: demo-source test
# --------------------------------------------------------------------------- #

D_ARMS = ["D0_retr6", "D1_same_topic", "D2_same_group", "D3_same_group_same_topic", "D4_other_groups_same_question"]


def load_logs(which: str, arms: list[str]) -> dict:
    from human_sim.simbench_ablate import build_env, dataset_norms

    sample, _, _ = build_env(25, 100, 7, which)
    norms = json.loads((OUT_DIR / "dataset_norms.json").read_text()) if which == "eval" else dataset_norms(sample)
    suffix = "" if which == "eval" else "dev10x40"
    data = {
        a: {r["i"]: r for r in json.loads((OUT_DIR / f"{a}_claude-haiku-4-5_p25g100s7{suffix}.json").read_text())["rows"] if r.get("ok")}
        for a in arms
    }
    cases = {}
    for i in set().union(*[set(v) for v in data.values()]):
        row = sample.iloc[i]
        keys = list(row["human_answer"].keys())
        v = lambda d: np.array([d.get(k, 0.0) for k in keys], float) / max(sum(d.get(k, 0.0) for k in keys), 1e-12)  # noqa: E731
        h = v(row["human_answer"])
        texts = parse_options(row["input_template"])
        c = {
            "i": i, "split": row["split"], "ds": row["dataset_name"], "keys": keys, "texts": texts,
            "h": h, "Hn": Hn(h), "norm": norms[row["dataset_name"]],
            **option_roles(keys, texts, row["dataset_name"]),
        }
        for a in arms:
            if i in data[a]:
                c[a] = v(data[a][i]["llm_answer"])
        cases[i] = c
    return cases


def _qt(h: float) -> str:
    return "consensus" if h < 0.65 else ("mixed" if h < DIVIDED else "divided")


def _paired(cs, a, b) -> list | None:
    d = [100 * (0.5 * np.abs(c[b] - c["h"]).sum() - 0.5 * np.abs(c[a] - c["h"]).sum()) / c["norm"] for c in cs]
    if len(d) < 2:
        return None
    boots = sorted(float(np.mean(rng.choice(d, len(d)))) for _ in range(1000))
    return [round(float(np.mean(d)), 2), round(boots[25], 2), round(boots[975], 2)]


def step_d() -> dict:
    out = {}
    for which in ("dev", "eval"):
        cases = list(load_logs(which, D_ARMS).values())
        res = {}
        for sp in ("Pop", "Grouped", "all"):
            for qt in ("consensus", "mixed", "divided", "all"):
                sel = [c for c in cases if (sp == "all" or c["split"] == sp) and (qt == "all" or _qt(c["Hn"]) == qt)]
                cell = {}
                for a in D_ARMS:
                    cs = [c for c in sel if a in c and "D0_retr6" in c]
                    if not cs:
                        continue
                    an = anatomy(cs, a)
                    cell[a] = {
                        "n": len(cs),
                        "S": an["S"],
                        "TVD": an["TVD"],
                        "top_option_right": an["top_option_right"],
                        "entropy_gap": an["entropy_gap"],
                        "polarity_flip_rate": an["polarity_flip_rate"],
                        "scale_abs_shift": an["scale_abs_shift"],
                        "middle_mass_pred_vs_true": an["middle_mass_pred_vs_true"],
                        "dk_mass_pred_vs_true": an["dk_mass_pred_vs_true"],
                    }
                    if a != "D0_retr6":
                        cell[a]["vs_D0_same_questions"] = _paired(cs, a, "D0_retr6")
                        cell[a]["D0_S_same_questions"] = anatomy(cs, "D0_retr6")["S"]
                res[f"{sp}/{qt}"] = cell
        out[which] = res
    (OUT_DIR / "divided_stepD_demo_sources.json").write_text(json.dumps(out, indent=1))
    return out


STEPS = {"A": "step_a", "B": "step_b", "C": "step_c", "D": "step_d"}

if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else "A"
    globals()[STEPS[step]]()
