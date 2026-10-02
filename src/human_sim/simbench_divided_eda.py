"""Exploratory analysis of divided-question error. No model calls: logged runs only.

Step 1  analysis table (one row per question x arm), eval and dev
Step 2  where the error concentrates (variance decomposition, slices, group view, cross-model)
Step 3  headroom per lever (ceilings and counterfactuals from logs)
Step 4  can the error be predicted before seeing the answer?

Usage:
  PYTHONPATH=src python -m human_sim.simbench_divided_eda
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from human_sim import simbench_ablate as A
from human_sim.simbench_divided_anatomy import option_roles, parse_options

OUT = A.OUT_DIR
IMG = A.ROOT / "docs" / "experiments" / "img"
SHARED = ("Afrobarometer", "ESS", "ISSP", "LatinoBarometro", "OpinionQA")
POP_TASKS = ("OSPsychMACH", "Choices13k", "NumberGame", "OSPsychMGKT")
DIV = 0.84
HAIKU = "claude-haiku-4-5"
# Haiku arms logged on both eval and dev (router candidates and slices)
ARMS = ["base", "retr6", "retr6_rev2", "P_groundall5", "P_adapt", "B_n3_soft", "B_n3_soft_rev2"]
OTHER_EVAL = {"gemini_retr6": ("retr6", "gemini-2.5-flash")}
OTHER_DEV = {
    "gemini_retr6": ("retr6", "gemini-2.5-flash"),
    "sonnet46_retr6": ("retr6", "claude-sonnet-4-6"),
    "sonnet55_retr6": ("retr6", "claude-sonnet-5-5"),
    "panel_R": ("P_groundall5_R", HAIKU),
    "B_ground3_rev2": ("B_ground3_rev2", HAIKU),
}

# ------------------------------------------------------------------ helpers


def Hn(p: np.ndarray) -> float:
    q = p[p > 0]
    return float(-(q * np.log(q)).sum() / np.log(len(p))) if len(p) > 1 else 0.0


def tvd(p, q) -> float:
    return 0.5 * float(np.abs(np.asarray(p) - np.asarray(q)).sum())


def stem(t: str) -> str:
    return re.sub(r"\s+", " ", t.split("Options:")[0]).strip()


# ------------------------------------------------------------------ population fields

REGIONS = {
    "Africa": "Algeria Angola Benin Botswana Burkina Cabo Cameroon Congo Côte Ivoire Eswatini Ethiopia Gabon "
    "Gambia Ghana Guinea Kenya Lesotho Liberia Madagascar Malawi Mali Mauritania Mauritius Morocco Mozambique "
    "Namibia Niger Nigeria Senegal Sierra Leone South Africa Sudan Tanzania Togo Tunisia Uganda Zambia Zimbabwe Egypt",
    "Latin America": "Argentina Bolivia Brazil Chile Colombia Costa Rica Dominican Ecuador El Salvador Guatemala "
    "Honduras Mexico Nicaragua Panama Paraguay Peru Uruguay Venezuela",
    "Europe": "Austria Belgium Bulgaria Croatia Cyprus Czechia Czech Denmark Estonia Finland France Germany Greece "
    "Hungary Iceland Ireland Italy Latvia Lithuania Netherlands Norway Poland Portugal Russia Serbia Slovakia "
    "Slovenia Spain Sweden Switzerland United Kingdom Great Britain Britain Ukraine Montenegro Kosovo",
    "North America": "United States America Canada",
    "Asia/Oceania": "Australia New Zealand China Japan Korea Taiwan Philippines Thailand India Indonesia Israel "
    "Turkey Türkiye Singapore Vietnam Malaysia Hong Kong",
}


def country_of(row) -> str:
    vm = row["group_prompt_variable_map"]
    c = A._country_of(vm)
    if c:
        return c
    m = re.search(r"You are from ([^.]+)\.", str(A._filled_persona(row)))
    return m.group(1).replace("the ", "").strip() if m else "unspecified"


def region_of(country: str) -> str:
    for reg, names in REGIONS.items():
        if any(n in country for n in names.split()) and len(country) > 1:
            return reg
    return "unspecified"


def year_of(row) -> str:
    m = re.search(r"(?:year is|timeframe is) ([0-9]{4}(?:-[0-9]{4})?)", str(A._filled_persona(row)))
    return m.group(1) if m else "unspecified"


def subgroup_of(row) -> tuple[str, str]:
    vm = row["group_prompt_variable_map"]
    other = [k for k in vm if k not in A._COUNTRY_KEYS]
    if not other:
        return "population", "population"
    return other[0], str(vm[other[0]])


# ------------------------------------------------------------------ value-laden rule

VALUE_RULE = """Keyword rule, question stem and option texts only (never answers).
Value-laden topics (stem regex): sexual minorities (gay|lesbian|homosexual|same-sex|sex change|transgender),
gender roles (husband|wife|housewife|a woman should|men make better), immigration (immigra|foreigner|refugee|
people from (the )?poorer countries|allow people), democracy vs authoritarian rule (democra|military government|
strong leader), civic participation (petition|demonstration|boycott|contacted a politician|discuss politics|
talk about politics), racial justice (slavery|black people|racial), secular morality (believe in god in order to be),
reproductive / family autonomy (abortion|never to have children|not married|divorce), environment (protected nature|
protect the environment|climate).
Textbook option(s): the tolerant / egalitarian / pro-democracy / civic / secular / pro-environment side, chosen from
option text: agree-side (agree, not disagree) unless the statement is negatively framed (ashamed|job is to earn|look
after the home|men make better|wrong|military government|prefer a society that defends), then disagree-side;
approve-side; 'yes' for participation; beneficial / allow many / allow some for immigration; 'under no circumstance'
and 'democracy' for regime questions; not-wrong for abortion; unwilling for reducing protected areas; 'great deal' /
'fair amount' for the slavery legacy; 'not important' for belief-in-god-to-be-moral; 'open' for the
traditional-vs-open society item. Everything else: not value-laden."""

_TOPIC_RE = re.compile(
    r"gay|lesbian|homosexual|same-sex|sex change|transgender|husband|wife|housewife|a woman should|men make better|"
    r"immigra|foreigner|refugee|poorer countries|allow people|democra|military government|strong leader|petition|"
    r"demonstration|boycott|contacted a politician|discuss politics|talk about politics|slavery|black people|racial|"
    r"believe in god in order to be|abortion|never to have children|not married|divorce|protected nature|"
    r"protect the environment|climate",
    re.I,
)
_NEG_FRAME = re.compile(
    r"ashamed|job is to earn|look after the home|men make better|military government|prefer a society that defends",
    re.I,
)


def textbook_options(question: str, texts: dict) -> list[str]:
    st = stem(question).lower()
    if not _TOPIC_RE.search(st):
        return []
    opts = {k: v.lower() for k, v in texts.items()}
    pick = lambda f: [k for k, v in opts.items() if f(v)]  # noqa: E731
    if "military government" in st or "democra" in st:
        out = pick(lambda v: "no circumstance" in v or ("democracy" in v and "not" not in v[:12]))
        if out:
            return out
    if "abortion" in st or " wrong " in f" {st} ":
        out = pick(lambda v: "not wrong" in v or "only sometimes" in v)
        if out:
            return out
    if "protected nature" in st or "reduction" in st:
        return pick(lambda v: "unwilling" in v)
    if "slavery" in st:
        return pick(lambda v: "great deal" in v or "fair amount" in v)
    if "believe in god in order to be" in st:
        return pick(lambda v: "not too important" in v or "not at all important" in v)
    if "defends our trad" in " ".join(opts.values()) or "open to" in " ".join(opts.values()):
        out = pick(lambda v: "open to" in v)
        if out:
            return out
    if any("approve" in v for v in opts.values()):
        return pick(lambda v: "approve" in v and "disapprove" not in v)
    if any("agree" in v for v in opts.values()):
        neg = bool(_NEG_FRAME.search(st))
        if neg:
            return pick(lambda v: "disagree" in v)
        return pick(lambda v: "agree" in v and "disagree" not in v and "neither" not in v)
    if any(w in st for w in ("immigra", "poorer countries", "allow people", "foreigner", "refugee")):
        return pick(lambda v: "benefi" in v or "allow many" in v or "allow some" in v)
    if any(w in st for w in ("petition", "demonstration", "boycott", "contacted", "discuss politics", "talk about politics")):
        return pick(lambda v: v.startswith("yes") or "very frequently" in v or v == "frequently" or "frequently" == v)
    return []


# ------------------------------------------------------------------ cache-only embeddings for topics


def _cache_only_embed(texts):
    import pickle

    store = pickle.loads(A.EMB_CACHE.read_bytes()) if A.EMB_CACHE.exists() else {}
    missing = [t for t in texts if t not in store]
    if missing:
        raise KeyError(f"{len(missing)} stems not in embedding cache")
    return [store[t] for t in texts]


def topic_clusters(stems_by_ds: dict) -> dict:
    """(dataset, stem) -> cluster. Shared surveys: k-means on cached embeddings (as in D1);
    other datasets or cache misses: k-means on TF-IDF. No API calls."""
    from sklearn.cluster import KMeans
    from sklearn.feature_extraction.text import TfidfVectorizer

    out, method = {}, {}
    for ds, stems in stems_by_ds.items():
        stems = sorted(stems)
        k = min(len(stems), max(4, round(len(stems) / 30)))
        try:
            X = np.array(_cache_only_embed([s.lower() for s in stems]))
            method[ds] = "embedding"
        except KeyError:
            X = TfidfVectorizer(stop_words="english").fit_transform(stems).toarray()
            method[ds] = "tfidf"
        labels = KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(X) if k > 1 else [0] * len(stems)
        for s, lab in zip(stems, labels):
            out[(ds, s)] = f"{ds}:{int(lab)}"
    return out, method


# ------------------------------------------------------------------ Step 1


def _load(arm: str, model: str, suffix: str) -> dict:
    p = OUT / f"{arm}_{model}_p25g100s7{suffix}.json"
    if not p.exists():
        return {}
    return {r["i"]: r for r in json.loads(p.read_text())["rows"] if r.get("ok")}


def build_table(which: str):
    sample, norms, ctx = A.build_env(25, 100, 7, which)
    if which == "eval":
        norms = json.loads((OUT / "dataset_norms.json").read_text())
    suffix = "" if which == "eval" else "dev10x40"
    preds = {a: _load(a, HAIKU, suffix) for a in ARMS}
    others = OTHER_EVAL if which == "eval" else OTHER_DEV
    for name, (arm, model) in others.items():
        preds[name] = _load(arm, model, suffix)
    # topic clusters over target stems (+ demo pool stems of the same dataset)
    stems_by_ds = defaultdict(set)
    for _, r in sample.iterrows():
        stems_by_ds[r["dataset_name"]].add(stem(r["input_template"]))
    topics, topic_method = topic_clusters(stems_by_ds)

    qrows, long = [], []
    for i, row in sample.iterrows():
        keys = list(row["human_answer"].keys())
        vec = lambda d: np.array([d.get(k, 0.0) for k in keys], float) / max(sum(d.get(k, 0.0) for k in keys), 1e-12)  # noqa: E731
        h = vec(row["human_answer"])
        texts = parse_options(row["input_template"])
        roles = option_roles(keys, texts, row["dataset_name"])
        att, val = subgroup_of(row)
        country = country_of(row)
        # retr6 demos, recomputed deterministically (same functions as the logged run)
        pool = A._demo_pool(row, ctx)
        ranked = A._rank_by_similarity(row, pool, ctx)[:6]
        sims = A._similarities(row, pool, ctx, "tfidf") if pool else []
        sim_of = {id(d): float(s) for d, s in zip(pool, sims)}
        demo_sims = [sim_of.get(id(d), np.nan) for d in ranked]
        opt_list = [texts.get(k, "").strip().lower() for k in keys]
        aligned = []
        for d in ranked:
            dt = parse_options(d["input_template"])
            dk = list(d["human_answer"].keys())
            if [dt.get(k, "").strip().lower() for k in dk] == opt_list and len(dk) == len(keys):
                aligned.append(vec(d["human_answer"]))
        tb = textbook_options(row["input_template"], texts)
        q = {
            "set": which,
            "qid": f"{which}:{i}",
            "i": int(i),
            "dataset": row["dataset_name"],
            "split": row["split"],
            "group": "pop_only_task" if row["dataset_name"] in POP_TASKS else ("shared_survey" if row["dataset_name"] in SHARED else "other_pop_only"),
            "country": country,
            "region": region_of(country),
            "year": year_of(row),
            "sub_attribute": att,
            "sub_value": val,
            "n_options": len(keys),
            "scale_type": "ordinal" if roles["ordinal"] else ("binary" if len([k for k in keys if roles["roles"][k] != "dk"]) == 2 else "categorical"),
            "has_dk": any(v == "dk" for v in roles["roles"].values()),
            "q_len": len(stem(row["input_template"])),
            "topic": topics.get((row["dataset_name"], stem(row["input_template"])), "none"),
            "value_laden": bool(tb),
            "textbook": "".join(tb),
            "demo_mean_sim": float(np.nanmean(demo_sims)) if demo_sims else np.nan,
            "demo_mean_entropy": float(np.mean([d["h"] for d in ranked])) if ranked else np.nan,
            "n_aligned_demos": len(aligned),
            "aligned_demo_avg_entropy": Hn(np.mean(aligned, axis=0)) if aligned else np.nan,
            # truth-using demo diagnostics (NOT available at prediction time)
            "TRUTH_aligned_avg_tvd": tvd(np.mean(aligned, axis=0), h) if aligned else np.nan,
            "TRUTH_any_aligned_within_0.10": bool(aligned) and min(tvd(a, h) for a in aligned) <= 0.10,
            "true_entropy": Hn(h),
            "qtype": "divided" if Hn(h) >= DIV else ("mixed" if Hn(h) >= 0.65 else "consensus"),
            "norm": norms[row["dataset_name"]],
        }
        # model behaviour (prediction-time)
        r2 = preds["retr6_rev2"].get(i)
        if r2 and len(r2.get("segments", [])) == 2:
            q["order_sensitivity"] = tvd(vec(r2["segments"][0]["dist"]), vec(r2["segments"][1]["dist"]))
        if i in preds["retr6"] and i in preds["P_groundall5"]:
            q["harness_disagreement"] = tvd(vec(preds["retr6"][i]["llm_answer"]), vec(preds["P_groundall5"][i]["llm_answer"]))
        if i in preds["retr6"] and i in preds.get("gemini_retr6", {}):
            q["model_disagreement"] = tvd(vec(preds["retr6"][i]["llm_answer"]), vec(preds["gemini_retr6"][i]["llm_answer"]))
        if i in preds["retr6_rev2"]:
            p = vec(preds["retr6_rev2"][i]["llm_answer"])
            q["pred_entropy_rev2"] = Hn(p)
            q["pred_top_mass_rev2"] = float(p.max())
        qrows.append(q)
        for arm, d in preds.items():
            if i not in d:
                continue
            p = vec(d[i]["llm_answer"])
            pos_t = _top_side(roles, keys, h)
            pos_p = _top_side(roles, keys, p)
            long.append(
                {
                    "qid": q["qid"],
                    "arm": arm,
                    "TVD": tvd(p, h),
                    "S": 100 * (1 - tvd(p, h) / q["norm"]),
                    "top_right": bool(np.argmax(p) == np.argmax(h)),
                    "flip": (pos_t * pos_p < 0) if (pos_t and pos_p) else np.nan,
                    "pred_entropy": Hn(p),
                    "textbook_residual": float(sum(p[keys.index(k)] - h[keys.index(k)] for k in tb if k in keys)) if tb else np.nan,
                    "pred": p.tolist(),
                    "truth": h.tolist(),
                }
            )
    qdf = pd.DataFrame(qrows)
    ldf = pd.DataFrame(long)
    return qdf, ldf, topic_method


def _top_side(roles, keys, p) -> float:
    """+1 / -1 for the side of the scale midpoint of the top substantive option (ordinal only)."""
    if not roles["ordinal"]:
        return 0.0
    subs = roles["subs"]
    m = np.array([p[keys.index(k)] for k in subs])
    pos = roles["roles"][subs[int(np.argmax(m))]]
    return float(np.sign(pos - 0.5)) if isinstance(pos, float) else 0.0


def step1():
    qs, ls, methods = [], [], {}
    for which in ("eval", "dev"):
        q, l, m = build_table(which)
        qs.append(q)
        ls.append(l)
        methods[which] = m
    qdf = pd.concat(qs, ignore_index=True)
    ldf = pd.concat(ls, ignore_index=True)
    table = ldf.merge(qdf, on="qid", how="left")
    table.drop(columns=["pred", "truth"]).to_csv(OUT / "divided_eda_table.csv", index=False)
    table.to_pickle(OUT / "divided_eda_table.pkl")
    return table, qdf, methods


# ------------------------------------------------------------------ Step 2

DIMS = ["dataset", "country", "region", "year", "topic", "scale_type", "n_options", "value_laden", "sub_attribute", "split"]
PRED_FEATURES_NUM = [
    "n_options", "q_len", "demo_mean_sim", "demo_mean_entropy", "n_aligned_demos", "aligned_demo_avg_entropy",
    "order_sensitivity", "harness_disagreement", "model_disagreement", "pred_entropy_rev2", "pred_top_mass_rev2",
]
PRED_FEATURES_CAT = ["dataset", "split", "scale_type", "has_dk", "value_laden", "region"]


def _r2(y: np.ndarray, X: np.ndarray) -> tuple[float, float]:
    """R2 and adjusted R2 of OLS with intercept."""
    X1 = np.column_stack([np.ones(len(y)), X]) if X.size else np.ones((len(y), 1))
    beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
    resid = y - X1 @ beta
    ss_res, ss_tot = float((resid**2).sum()), float(((y - y.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    p = np.linalg.matrix_rank(X1) - 1
    n = len(y)
    adj = 1 - (1 - r2) * (n - 1) / max(n - p - 1, 1)
    return r2, adj


def _dummies(df: pd.DataFrame, dims: list[str]) -> np.ndarray:
    if not dims:
        return np.zeros((len(df), 0))
    return pd.get_dummies(df[dims].astype(str), drop_first=True).to_numpy(float)


def variance_decomposition(d: pd.DataFrame, dims=DIMS) -> dict:
    y = d["TVD"].to_numpy(float)
    dims = [c for c in dims if d[c].astype(str).nunique() > 1]
    full_r2, full_adj = _r2(y, _dummies(d, dims))
    out = {"n": len(d), "joint_R2": round(full_r2, 3), "joint_adjR2": round(full_adj, 3), "dims": {}}
    for c in dims:
        r2, adj = _r2(y, _dummies(d, [c]))
        _, adj_wo = _r2(y, _dummies(d, [x for x in dims if x != c]))
        out["dims"][c] = {
            "levels": int(d[c].astype(str).nunique()),
            "alone_R2": round(r2, 3),
            "alone_adjR2": round(adj, 3),
            "unique_adjR2": round(full_adj - adj_wo, 3),
        }
    out["dims"] = dict(sorted(out["dims"].items(), key=lambda kv: -kv[1]["alone_adjR2"]))
    return out


def _boot_ci(v, n=1000, seed=0):
    v = np.asarray(v, float)
    v = v[~np.isnan(v)]
    if len(v) < 2:
        return [None, None]
    rng = np.random.default_rng(seed)
    b = np.sort([rng.choice(v, len(v)).mean() for _ in range(n)])
    return [round(float(b[int(0.025 * n)]), 2), round(float(b[int(0.975 * n)]), 2)]


def slices(d: pd.DataFrame, dims=DIMS, top=10) -> dict:
    out = {}
    for c in dims:
        g = d.groupby(d[c].astype(str))
        rows = []
        for lvl, x in g:
            rows.append(
                {
                    "level": lvl,
                    "n": int(len(x)),
                    "S": round(float(x.S.mean()), 2),
                    "S_ci": _boot_ci(x.S),
                    "flip_rate": round(float(x.flip.dropna().mean()), 3) if x.flip.notna().any() else None,
                    "top_right": round(float(x.top_right.mean()), 3),
                    "small": len(x) < 30,
                }
            )
        out[c] = sorted(rows, key=lambda r: r["S"])[:top]
    return out


def group_view() -> dict:
    """Per country x attribute x value: shared part (question's mean error) vs group-specific part."""
    from human_sim.simbench_divided_anatomy import _c2_groups

    sample, _, _ = A.build_env(25, 100, 7, "stepc")
    rows = {r["i"]: r for r in json.loads((OUT / f"retr6_rev2_{HAIKU}_p25g100s7stepc.json").read_text())["rows"] if r.get("ok")}
    by = defaultdict(list)
    for i, r in rows.items():
        row = sample.iloc[i]
        vm = row["group_prompt_variable_map"]
        att = [k for k in vm if k not in A._COUNTRY_KEYS][0]
        by[(row["dataset_name"], A._country_of(vm), row["input_template"], att)].append((row, r, str(vm[att])))
    recs = []
    for (ds, country, q, att), items in by.items():
        if len(items) < 2:
            continue
        keys = list(items[0][0]["human_answer"].keys())
        v = lambda d: np.array([d.get(k, 0.0) for k in keys], float) / max(sum(d.get(k, 0.0) for k in keys), 1e-12)  # noqa: E731
        P = np.array([v(r["llm_answer"]) for _, r, _ in items])
        T = np.array([v(row["human_answer"]) for row, _, _ in items])
        w = np.array([float(row["group_size"]) for row, _, _ in items])
        w = w / w.sum()
        E = P - T
        ebar = w @ E
        for (row, _, val), e in zip(items, E):
            recs.append(
                {
                    "question": f"{ds}|{country}|{hash(q)}",
                    "dataset": ds,
                    "country": country,
                    "attribute": att,
                    "value": val,
                    "label": f"{ds} · {country} · {att}={val}",
                    "tvd": 0.5 * float(np.abs(e).sum()),
                    "shared": 0.5 * float(np.abs(ebar).sum()),
                    "specific": 0.5 * float(np.abs(e - ebar).sum()),
                    "P": None,
                }
            )
    df = pd.DataFrame(recs)
    agg = df.groupby("label").agg(n=("tvd", "size"), tvd=("tvd", "mean"), shared=("shared", "mean"), specific=("specific", "mean")).reset_index()
    agg = agg.sort_values("specific", ascending=False)
    # permutation null: shuffle group labels within each question; statistic = max mean specific over labels with n >= 3
    rng = np.random.default_rng(0)
    obs = agg[agg.n >= 3].specific.max()
    null = []
    for _ in range(500):
        d2 = df.copy()
        d2["label"] = d2.groupby("question")["label"].transform(lambda s: rng.permutation(s.values))
        a2 = d2.groupby("label").agg(n=("tvd", "size"), sp=("specific", "mean"))
        null.append(a2[a2.n >= 3].sp.max())
    by_attr = df.groupby("attribute").agg(n=("tvd", "size"), shared=("shared", "mean"), specific=("specific", "mean")).sort_values("specific", ascending=False)
    return {
        "cells": len(df),
        "questions": int(df.question.nunique()),
        "mean_shared": round(float(df.shared.mean()), 4),
        "mean_specific": round(float(df.specific.mean()), 4),
        "top_groups_by_specific": agg[agg.n >= 3].head(10).round(4).to_dict("records"),
        "max_group_specific_observed": round(float(obs), 4),
        "max_group_specific_null_p95": round(float(np.percentile(null, 95)), 4),
        "max_group_specific_perm_p": round(float(np.mean(np.array(null) >= obs)), 3),
        "by_attribute": by_attr[by_attr.n >= 10].round(4).reset_index().to_dict("records"),
        "_scatter": agg[agg.n >= 3][["label", "shared", "specific", "n"]].to_dict("records"),
    }


def cross_model(table: pd.DataFrame) -> dict:
    out = {}
    for s, arms in (("dev", ["retr6", "sonnet46_retr6", "sonnet55_retr6", "gemini_retr6"]), ("eval", ["retr6", "gemini_retr6"])):
        for qt in ("divided", "all"):
            d = table[(table.set == s) & ((table.qtype == qt) | (qt == "all"))]
            w = d.pivot_table(index="qid", columns="arm", values="TVD")[arms].dropna()
            corr = w.corr().round(3).to_dict()
            spear = w.rank().corr().round(3).to_dict()
            worst = {a: set(w[a].sort_values(ascending=False).index[: max(1, int(0.2 * len(w)))]) for a in arms}
            inter = set.intersection(*worst.values())
            union = set.union(*worst.values())
            out[f"{s}/{qt}"] = {
                "n": len(w),
                "pearson": corr,
                "spearman": spear,
                "worst20_size": len(next(iter(worst.values()))),
                "worst20_shared_by_all": len(inter),
                "worst20_share_of_first_model_worst_for_all": round(len(inter) / max(1, len(worst[arms[0]])), 3),
                "worst20_union": len(union),
            }
    return out


# ------------------------------------------------------------------ Step 3


def _flatten_to_entropy(p: np.ndarray, target: float) -> np.ndarray:
    """Temperature-scale p so that its normalized entropy matches target (oracle)."""
    lp = np.log(np.clip(p, 1e-9, 1))
    lo, hi = 0.05, 50.0
    for _ in range(60):
        t = (lo + hi) / 2
        q = np.exp(lp / t)
        q /= q.sum()
        if Hn(q) < target:
            lo = t
        else:
            hi = t
    q = np.exp(lp / ((lo + hi) / 2))
    return q / q.sum()


def headroom(table: pd.DataFrame, qdf: pd.DataFrame) -> dict:
    out = {}
    ev = table[table.set == "eval"]
    for gname, gsel in (("shared_survey", "shared_survey"), ("pop_only_task", "pop_only_task"), ("other_pop_only", "other_pop_only")):
        d = ev[(ev.qtype == "divided") & (ev.group == gsel)]
        base = d[d.arm == "retr6_rev2"].set_index("qid")
        res = {"n": len(base), "retr6_rev2": round(float(base.S.mean()), 2)}
        # A. oracle best logged Haiku arm
        piv = d[d.arm.isin(ARMS)].pivot_table(index="qid", columns="arm", values="S")
        res["A_oracle_best_arm"] = round(float(piv.max(axis=1).mean()), 2)
        res["A_best_single_arm"] = {a: round(float(piv[a].mean()), 2) for a in ARMS}
        # C / D / E / H on retr6_rev2 predictions
        C, D_, Ef, Hf = [], [], [], []
        for qid, r in base.iterrows():
            p, h = np.array(r.pred), np.array(r.truth)
            norm = r.norm
            sc = lambda x: 100 * (1 - tvd(x, h) / norm)  # noqa: E731
            q = np.zeros_like(p)
            q[np.argsort(-h)] = np.sort(p)[::-1]
            C.append(sc(q))
            q = p.copy()
            a_, b_ = int(np.argmax(p)), int(np.argmax(h))
            q[a_], q[b_] = p[b_], p[a_]
            D_.append(sc(q))
            Hf.append(sc(_flatten_to_entropy(p, Hn(h))))
        res["C_fix_placement_only"] = round(float(np.mean(C)), 2)
        res["D_fix_top_option_only"] = round(float(np.mean(D_)), 2)
        res["H_fix_entropy_only"] = round(float(np.mean(Hf)), 2)
        # E. order: best of original / reversed / average
        rows = {r["i"]: r for r in json.loads((OUT / f"retr6_rev2_{HAIKU}_p25g100s7.json").read_text())["rows"] if r.get("ok")}
        for qid, r in base.iterrows():
            i = int(qid.split(":")[1])
            segs = rows[i].get("segments", [])
            h, norm = np.array(r.truth), r.norm
            keys = list(rows[i]["human_answer"].keys())
            cands = [np.array(r.pred)] + [np.array([s["dist"].get(k, 0) for k in keys]) for s in segs]
            Ef.append(max(100 * (1 - tvd(c / c.sum(), h) / norm) for c in cands))
        res["E_fix_order_bias_oracle"] = round(float(np.mean(Ef)), 2)
        # G. other model (eval: Gemini retr6)
        g = d[d.arm == "gemini_retr6"].set_index("qid").S
        res["G_gemini_retr6"] = round(float(g.mean()), 2)
        res["G_oracle_best_of_haiku_rev2_gemini"] = round(float(np.maximum(base.S, g.reindex(base.index)).mean()), 2)
        out[gname] = res
    # A'. dev-fitted router using prediction-time features (fit on dev, applied to eval)
    out["A_router_dev_fitted"] = router(table, qdf)
    # B. demo averages (needs the demo pool again)
    out["B_demo_average"] = demo_average(table)
    # F. fix the shared error (Step C cell set)
    out["F_fix_shared_error"] = fix_shared_error()
    # G on dev: larger models
    dv = table[(table.set == "dev") & (table.qtype == "divided") & (table.group == "shared_survey")]
    piv = dv.pivot_table(index="qid", columns="arm", values="S")
    best_mix = dev_best_mix(table)
    out["G_dev_shared_divided"] = {
        "n": len(piv),
        **{a: round(float(piv[a].mean()), 2) for a in ["retr6", "retr6_rev2", "P_groundall5", "sonnet46_retr6", "sonnet55_retr6", "gemini_retr6"] if a in piv},
        "oracle_best_of_haiku_and_larger": round(float(piv[["retr6_rev2", "sonnet46_retr6", "sonnet55_retr6"]].max(axis=1).mean()), 2),
        "best_divided_mix_4.10": best_mix,
    }
    return out


def dev_best_mix(table: pd.DataFrame) -> dict:
    """§4.10 mix on dev: 0.75 * (panel + panel_R)/2 + 0.25 * B_ground3_rev2, pulled 29% toward uniform."""
    dv = table[table.set == "dev"]
    p = {a: dv[dv.arm == a].set_index("qid") for a in ("P_groundall5", "panel_R", "B_ground3_rev2", "retr6_rev2")}
    ids = sorted(set.intersection(*[set(x.index) for x in p.values()]))
    res = defaultdict(list)
    for q in ids:
        h = np.array(p["P_groundall5"].loc[q].truth)
        mix = 0.75 * (np.array(p["P_groundall5"].loc[q].pred) + np.array(p["panel_R"].loc[q].pred)) / 2 + 0.25 * np.array(p["B_ground3_rev2"].loc[q].pred)
        mix = 0.71 * mix + 0.29 / len(mix)
        norm = p["P_groundall5"].loc[q].norm
        qt = p["P_groundall5"].loc[q].qtype
        grp = p["P_groundall5"].loc[q].group
        res[(qt, grp)].append((100 * (1 - tvd(mix, h) / norm), p["retr6_rev2"].loc[q].S))
    return {f"{k[0]}/{k[1]}": {"n": len(v), "mix_S": round(float(np.mean([a for a, _ in v])), 2), "retr6_rev2_S": round(float(np.mean([b for _, b in v])), 2)} for k, v in sorted(res.items())}


def _features(qdf: pd.DataFrame) -> pd.DataFrame:
    X = qdf[PRED_FEATURES_NUM].astype(float).copy()
    X = X.fillna(X.median())
    C = pd.get_dummies(qdf[PRED_FEATURES_CAT].astype(str))
    return pd.concat([X, C], axis=1).astype(float)


def router(table: pd.DataFrame, qdf: pd.DataFrame) -> dict:
    from sklearn.linear_model import Ridge

    feats = _features(qdf)
    feats.index = qdf.qid
    piv = table[table.arm.isin(ARMS)].pivot_table(index="qid", columns="arm", values="TVD")
    dev_ids = [q for q in qdf[qdf.set == "dev"].qid if q in piv.index and piv.loc[q].notna().all()]
    ev_ids = [q for q in qdf[qdf.set == "eval"].qid if q in piv.index and piv.loc[q].notna().all()]
    mu, sd = feats.loc[dev_ids].mean(), feats.loc[dev_ids].std().replace(0, 1)
    Z = (feats - mu) / sd
    preds = {}
    for a in ARMS:
        m = Ridge(alpha=10.0).fit(Z.loc[dev_ids], piv.loc[dev_ids, a])
        preds[a] = pd.Series(m.predict(Z.loc[ev_ids]), index=ev_ids)
    choice = pd.DataFrame(preds).idxmin(axis=1)
    sS = table[table.set == "eval"].pivot_table(index="qid", columns="arm", values="S")
    meta = qdf.set_index("qid")
    out = {"choice_counts": choice.value_counts().to_dict()}
    for name, sel in (("divided_shared", lambda q: meta.loc[q, "qtype"] == "divided" and meta.loc[q, "group"] == "shared_survey"),
                      ("divided_all", lambda q: meta.loc[q, "qtype"] == "divided"), ("all", lambda q: True)):
        ids = [q for q in ev_ids if sel(q)]
        out[name] = {
            "n": len(ids),
            "router_S": round(float(np.mean([sS.loc[q, choice[q]] for q in ids])), 2),
            "retr6_rev2_S": round(float(sS.loc[ids, "retr6_rev2"].mean()), 2),
            "oracle_S": round(float(sS.loc[ids, ARMS].max(axis=1).mean()), 2),
        }
    return out


def demo_average(table: pd.DataFrame) -> dict:
    """Ceiling B on eval divided questions that have option-aligned demos in the eligible pool."""
    sample, _, ctx = A.build_env(25, 100, 7, "eval")
    norms = json.loads((OUT / "dataset_norms.json").read_text())
    ev = table[(table.set == "eval") & (table.arm == "retr6_rev2") & (table.qtype == "divided")].set_index("qid")
    rec = defaultdict(list)
    moved = []
    for qid, r in ev.iterrows():
        i = int(qid.split(":")[1])
        row = sample.iloc[i]
        keys = list(row["human_answer"].keys())
        texts = parse_options(row["input_template"])
        opt = [texts.get(k, "").strip().lower() for k in keys]
        h, p = np.array(r.truth), np.array(r.pred)
        norm = norms[row["dataset_name"]]
        sc = lambda x: 100 * (1 - tvd(x, h) / norm)  # noqa: E731
        pool = A._demo_pool(row, ctx)

        def aligned(d):
            dt = parse_options(d["input_template"])
            dk = list(d["human_answer"].keys())
            if len(dk) != len(keys) or [dt.get(k, "").strip().lower() for k in dk] != opt:
                return None
            v = np.array([d["human_answer"].get(k, 0.0) for k in dk], float)
            return v / v.sum()

        al = [x for x in (aligned(d) for d in pool) if x is not None]
        own = [x for x in (aligned(d) for d in A._rank_by_similarity(row, pool, ctx)[:6]) if x is not None]
        grp = r.group
        rec[(grp, "n_with_aligned_pool")].append(1 if al else 0)
        if own:
            avg = np.mean(own, axis=0)
            rec[(grp, "own_demo_avg")].append((sc(avg), sc(p)))
            mv = tvd(p, avg)
            moved.append((grp, mv > 0.05, sc(p) > sc(avg)))
        if al:
            chosen, best = [], None
            for _ in range(6):  # greedy forward selection, oracle
                cand = None
                for j, x in enumerate(al):
                    m = np.mean(chosen + [x], axis=0)
                    s = sc(m)
                    if cand is None or s > cand[0]:
                        cand = (s, j)
                if best is not None and cand[0] <= best:
                    break
                best = cand[0]
                chosen.append(al[cand[1]])
            rec[(grp, "oracle_best_avg")].append((best, sc(p)))
    out = {}
    for grp in ("shared_survey", "pop_only_task", "other_pop_only"):
        o = {
            "n_divided": int(len(ev[ev.group == grp])),
            "share_with_aligned_pool": round(float(np.mean(rec[(grp, "n_with_aligned_pool")])), 3) if rec[(grp, "n_with_aligned_pool")] else 0,
        }
        if rec[(grp, "own_demo_avg")]:
            a = np.array(rec[(grp, "own_demo_avg")])
            o.update({"own_avg_n": len(a), "own_demo_avg_S": round(float(a[:, 0].mean()), 2), "model_S_same_q": round(float(a[:, 1].mean()), 2)})
        if rec[(grp, "oracle_best_avg")]:
            a = np.array(rec[(grp, "oracle_best_avg")])
            o.update({"oracle_n": len(a), "oracle_best_avg_S": round(float(a[:, 0].mean()), 2), "model_S_same_q_oracle": round(float(a[:, 1].mean()), 2)})
        mv = [m for m in moved if m[0] == grp]
        if mv:
            o["model_moves_away_from_demo_avg"] = round(float(np.mean([m[1] for m in mv])), 3)
            o["when_moving_model_beats_avg"] = round(float(np.mean([m[2] for m in mv if m[1]])), 3) if any(m[1] for m in mv) else None
        out[grp] = o
    return out


def fix_shared_error() -> dict:
    sample, _, _ = A.build_env(25, 100, 7, "stepc")
    norms = json.loads((OUT / "dataset_norms.json").read_text())
    rows = {r["i"]: r for r in json.loads((OUT / f"retr6_rev2_{HAIKU}_p25g100s7stepc.json").read_text())["rows"] if r.get("ok")}
    by = defaultdict(list)
    for i, r in rows.items():
        row = sample.iloc[i]
        vm = row["group_prompt_variable_map"]
        att = [k for k in vm if k not in A._COUNTRY_KEYS][0]
        by[(row["dataset_name"], A._country_of(vm), row["input_template"], att)].append((row, r))
    before, after, ds_ = [], [], []
    for (ds, *_), items in by.items():
        if len(items) < 2:
            continue
        keys = list(items[0][0]["human_answer"].keys())
        v = lambda d: np.array([d.get(k, 0.0) for k in keys], float) / max(sum(d.get(k, 0.0) for k in keys), 1e-12)  # noqa: E731
        P = np.array([v(r["llm_answer"]) for _, r in items])
        T = np.array([v(row["human_answer"]) for row, _ in items])
        w = np.array([float(row["group_size"]) for row, _ in items])
        w = w / w.sum()
        ebar = w @ (P - T)
        for p, t in zip(P, T):
            q = np.clip(p - ebar, 0, None)
            q = q / q.sum() if q.sum() > 0 else np.full_like(q, 1 / len(q))
            nm = norms.get(ds, 0.3)
            before.append(100 * (1 - tvd(p, t) / nm))
            after.append(100 * (1 - tvd(q, t) / nm))
    return {
        "cells": len(before),
        "S_model": round(float(np.mean(before)), 2),
        "S_shared_error_removed": round(float(np.mean(after)), 2),
        "note": "Step C cell set (Grouped subgroup cells of divided questions), not the eval sample",
    }


# ------------------------------------------------------------------ Step 4


def predictability(table: pd.DataFrame, qdf: pd.DataFrame) -> dict:
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score

    feats = _features(qdf)
    feats.index = qdf.qid
    base = table[table.arm == "retr6_rev2"].set_index("qid")
    meta = qdf.set_index("qid")
    targets = {
        "polarity_flip": lambda q: base.loc[q, "flip"],
        "bad_question_TVD_gt_0.30": lambda q: float(base.loc[q, "TVD"] > 0.30),
        "error_toward_textbook": lambda q: float(base.loc[q, "textbook_residual"] > 0) if not np.isnan(base.loc[q, "textbook_residual"]) else np.nan,
    }
    out = {}
    rng = np.random.default_rng(0)
    for name, f in targets.items():
        def xy(ids):
            y = pd.Series({q: f(q) for q in ids}).dropna()
            return feats.loc[y.index], y.astype(int)
        dev_ids = [q for q in meta.index if meta.loc[q, "set"] == "dev" and q in base.index]
        Xd, yd = xy(dev_ids)
        res = {"train": "dev, all question types", "n_train": int(len(yd)), "pos_rate_train": round(float(yd.mean()), 3)}
        if yd.nunique() < 2 or len(yd) < 20:
            res["skipped"] = "too few training examples"
            out[name] = res
            continue
        mu, sd = Xd.mean(), Xd.std().replace(0, 1)
        lr = LogisticRegression(C=0.5, max_iter=2000).fit((Xd - mu) / sd, yd)
        gb = GradientBoostingClassifier(max_depth=2, n_estimators=100, learning_rate=0.05, random_state=0).fit(Xd, yd)
        for tname, sel in (("eval_divided", lambda q: meta.loc[q, "qtype"] == "divided"), ("eval_all", lambda q: True)):
            ev_ids = [q for q in meta.index if meta.loc[q, "set"] == "eval" and q in base.index and sel(q)]
            Xe, ye = xy(ev_ids)
            if ye.nunique() < 2:
                continue
            for mname, prob in (("logistic", lr.predict_proba((Xe - mu) / sd)[:, 1]), ("gbm", gb.predict_proba(Xe)[:, 1])):
                auc = roc_auc_score(ye, prob)
                boots = []
                for _ in range(500):
                    idx = rng.integers(0, len(ye), len(ye))
                    if ye.iloc[idx].nunique() == 2:
                        boots.append(roc_auc_score(ye.iloc[idx], prob[idx]))
                res[f"{tname}/{mname}"] = {
                    "n": int(len(ye)),
                    "pos_rate": round(float(ye.mean()), 3),
                    "AUC": round(float(auc), 3),
                    "ci95": [round(float(np.percentile(boots, 2.5)), 3), round(float(np.percentile(boots, 97.5)), 3)],
                }
        coef = pd.Series(lr.coef_[0], index=Xd.columns)
        res["top_features_logistic"] = coef.reindex(coef.abs().sort_values(ascending=False).index).head(6).round(3).to_dict()
        res["top_features_gbm"] = pd.Series(gb.feature_importances_, index=Xd.columns).sort_values(ascending=False).head(6).round(3).to_dict()
        out[name] = res
    return out
