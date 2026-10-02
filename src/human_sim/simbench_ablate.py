"""SimBench prompt/harness ablation runner for Vertex Gemini.

Runs the same model under several prompt "arms" on one fixed stratified
subsample, then scores every arm with the official SimBench formula
(vendor/SimBench_release/calculate_simbench_score.py):

    S_i = 100 * (1 - TVD(pred_i, human_i) / mean_j TVD(human_j, uniform_j))

with the denominator taken per source dataset. Dataset norms are computed once
from the shared subsample so arms are directly comparable.

Usage:
  PYTHONPATH=src python -m human_sim.simbench_ablate --arms base,no_persona --pop 25 --grouped 100
  PYTHONPATH=src python -m human_sim.simbench_ablate --score-only
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import random
import re
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
from google import genai
from google.genai import types

from auth import invalidate_credentials, vertex_credentials
from config import GCP_LOCATION, GCP_PROJECT, MODEL, RESULTS_DIR, ROOT
from human_sim.simbench_cost import PRICES

DATA = ROOT / "data" / "simbench"
OUT_DIR = RESULTS_DIR / "simbench_ablate"

_thread_local = threading.local()

SYSTEM_PREFIX = "You are a group of individuals with these shared characteristics:\n"

RULES = (
    "1. Use whole numbers from 0 to 100\n"
    "2. Ensure the percentages sum to exactly 100\n"
    "3. Only include the numbers (no % symbols)\n"
    "4. Use this exact valid JSON format: {fmt} and do NOT include anything else.\n"
    "5. Only output your final answer and nothing else. "
    "No explanations or intermediate steps are needed.\n"
)


def _client() -> genai.Client:
    c = getattr(_thread_local, "client", None)
    if c is None:
        c = genai.Client(
            vertexai=True,
            project=GCP_PROJECT,
            location=GCP_LOCATION,
            credentials=vertex_credentials(),
        )
        _thread_local.client = c
    return c


# --------------------------------------------------------------------------- #
# data
# --------------------------------------------------------------------------- #


def _as_dict(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = ast.literal_eval(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, SyntaxError):
            return {}
    return {}


def load_split(split: str) -> pd.DataFrame:
    path = DATA / f"SimBench{split}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Download with: PYTHONPATH=src python -m human_sim.simbench_setup"
        )
    df = pd.read_csv(path)
    df["human_answer"] = df["human_answer"].map(_as_dict)
    df["group_prompt_variable_map"] = df["group_prompt_variable_map"].map(_as_dict)
    df = df[df["human_answer"].map(len) > 1].reset_index(drop=True)
    df["split"] = split
    return df


def _filled_persona(row) -> str:
    persona = str(row["group_prompt_template"])
    for variable, value in row["group_prompt_variable_map"].items():
        persona = persona.replace(f"{{{variable}}}", str(value))
    return persona


def stratified_sample(
    df: pd.DataFrame, per_dataset: int, seed: int, reserve: int = 0
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split each dataset into (eval sample, reserve pool for few-shot demos)."""
    evals, pools = [], []
    for _, group in df.groupby("dataset_name"):
        shuffled = group.sample(frac=1.0, random_state=seed)
        pools.append(shuffled.iloc[:reserve])
        evals.append(shuffled.iloc[reserve : reserve + per_dataset])
    return (
        pd.concat(evals).reset_index(drop=True),
        pd.concat(pools).reset_index(drop=True) if reserve else pd.DataFrame(),
    )


# --------------------------------------------------------------------------- #
# arms: each returns (system, user, gen_kwargs)
# --------------------------------------------------------------------------- #


def _fmt(keys: list[str]) -> str:
    return "{" + ", ".join(f'"{k}": X' for k in keys) + "}"


def _official_user(question: str, keys: list[str]) -> str:
    return (
        f"**Question**: {question}\n"
        "\nEstimate what percentage of your group would choose each option. "
        "Follow these rules:\n" + RULES.format(fmt=_fmt(keys)) + "Replace X with your "
        "estimated percentages for each option.\n**Answer**:"
    )


def arm_base(row, ctx) -> tuple[str, str, dict]:
    keys = list(row["human_answer"].keys())
    return (
        SYSTEM_PREFIX + _filled_persona(row),
        _official_user(row["input_template"], keys),
        {},
    )


def arm_no_persona(row, ctx) -> tuple[str, str, dict]:
    """Strip all group information: how much does the persona actually add?"""
    keys = list(row["human_answer"].keys())
    return (
        "You are a group of individuals.",
        _official_user(row["input_template"], keys),
        {},
    )


def arm_swap_persona(row, ctx) -> tuple[str, str, dict]:
    """Wrong-but-plausible persona from the same dataset: is conditioning real?"""
    keys = list(row["human_answer"].keys())
    own = _filled_persona(row)
    alternatives = ctx["personas_by_dataset"].get(row["dataset_name"], [])
    choices = [p for p in alternatives if p != own]
    rng = random.Random(f"{row['dataset_name']}|{row.name}")
    persona = rng.choice(choices) if choices else own
    return (
        SYSTEM_PREFIX + persona,
        _official_user(row["input_template"], keys),
        {},
    )


def arm_cot(row, ctx) -> tuple[str, str, dict]:
    """Official Appendix D zero-shot CoT prompt (text reasoning, not thinking tokens)."""
    keys = list(row["human_answer"].keys())
    user = (
        f"**Question**: {row['input_template']}\n"
        "\nEstimate what percentage of your group would choose each option.\n"
        "Think step by step about how people with your shared characteristics would "
        "reason about this question.\n"
        "Consider different perspectives within your group and what factors would "
        "influence their choices.\n"
        "Please provide your reasoning first, then give your final answer in JSON format.\n"
        "Follow these rules for your final answer:\n" + RULES.format(fmt=_fmt(keys)).replace(
            "5. Only output your final answer and nothing else. "
            "No explanations or intermediate steps are needed.\n",
            "5. Replace X with your estimated percentages for each option.\n",
        )
        + "**Answer**:"
    )
    return (
        SYSTEM_PREFIX + _filled_persona(row),
        user,
        {"json_mime": False, "max_output_tokens": 1200},
    )


def arm_think(row, ctx) -> tuple[str, str, dict]:
    """Official prompt but with a real thinking budget (inference-time compute)."""
    system, user, _ = arm_base(row, ctx)
    return system, user, {"thinking_budget": 1024, "max_output_tokens": 2048}


def arm_plural(row, ctx) -> tuple[str, str, dict]:
    """Anti-mode-seeking instruction: push back on alignment's entropy collapse."""
    keys = list(row["human_answer"].keys())
    system = (
        SYSTEM_PREFIX
        + _filled_persona(row)
        + "\n\nYour group is not uniform. Its members hold genuinely different views, "
        "and real survey responses from this group are usually spread across several "
        "options rather than concentrated on one. Report the spread you would actually "
        "observe, including minority positions."
    )
    return system, _official_user(row["input_template"], keys), {}


def arm_fewshot(row, ctx) -> tuple[str, str, dict]:
    """In-context calibration: real human distributions for other questions."""
    keys = list(row["human_answer"].keys())
    demos = ctx["demos_by_dataset"].get(row["dataset_name"], [])
    blocks = []
    for demo in demos:
        total = sum(demo["human_answer"].values()) or 1.0
        pct = {k: round(100 * v / total) for k, v in demo["human_answer"].items()}
        blocks.append(
            f"**Question**: {demo['input_template']}\n"
            f"**Answer**: {json.dumps(pct)}"
        )
    prefix = ""
    if blocks:
        prefix = (
            "Here are real response distributions previously measured for this group:\n\n"
            + "\n\n".join(blocks)
            + "\n\nNow estimate the same for a new question.\n\n"
        )
    return (
        SYSTEM_PREFIX + _filled_persona(row),
        prefix + _official_user(row["input_template"], keys),
        {},
    )


def arm_plural_fewshot(row, ctx) -> tuple[str, str, dict]:
    """Stack the two cheapest wins: plurality framing + in-context distributions."""
    plural_system, _, _ = arm_plural(row, ctx)
    _, fewshot_user, _ = arm_fewshot(row, ctx)
    return plural_system, fewshot_user, {}


def arm_ensemble(row, ctx) -> tuple[str, str, dict]:
    """Official prompt sampled k times at T=1, distributions averaged."""
    system, user, _ = arm_base(row, ctx)
    return system, user, {"samples": 5, "temperature": 1.0}


# --------------------------------------------------------------------------- #
# distribution-injection arms (entropy-aware demos)
# --------------------------------------------------------------------------- #


def _entropy(dist: dict) -> float:
    total = sum(dist.values()) or 1.0
    probs = [v / total for v in dist.values() if v > 0]
    k = len(dist)
    if k < 2:
        return 0.0
    return -sum(p * math.log(p) for p in probs) / math.log(k)


def _spread_label(h: float) -> str:
    if h < 0.55:
        return "concentrated (most people agree)"
    if h < 0.80:
        return "moderately split"
    return "widely spread (people disagree)"


def _pool_key(row) -> str:
    return f"{row['split']}|{row['dataset_name']}"


def _demo_pool(row, ctx) -> list[dict]:
    """Candidate demos for this row's dataset, never the same question text.

    A rewritten row (e.g. reversed options) carries its original text in `_orig_template`,
    so the original question can never leak back in as a demo."""
    own = row.get("_orig_template", row["input_template"])
    return [d for d in ctx["ext_by_dataset"].get(_pool_key(row), []) if d["input_template"] != own]


EMB_MODEL = "text-embedding-005"
EMB_CACHE = DATA / "emb_cache.pkl"
_emb_lock = threading.Lock()
_emb_store: dict[str, list[float]] | None = None


def _embed(texts: list[str]) -> list[list[float]]:
    """Cached text embeddings (Vertex). Cache is a gitignored pickle next to the data."""
    import pickle

    global _emb_store
    with _emb_lock:
        if _emb_store is None:
            _emb_store = pickle.loads(EMB_CACHE.read_bytes()) if EMB_CACHE.exists() else {}
        missing = [t for t in dict.fromkeys(texts) if t not in _emb_store]
        for i in range(0, len(missing), 50):
            chunk = missing[i : i + 50]
            resp = _client().models.embed_content(model=EMB_MODEL, contents=chunk)
            for t, e in zip(chunk, resp.embeddings):
                _emb_store[t] = list(e.values)
        if missing:
            EMB_CACHE.write_bytes(pickle.dumps(_emb_store))
        return [_emb_store[t] for t in texts]


def _similarities(row, pool: list[dict], ctx, method: str):
    cache = ctx.setdefault("_sim", {})
    key = (method, _pool_key(row), len(pool), pool[0]["input_template"][:40])
    if method == "emb":
        import numpy as np

        if key not in cache:
            mat = np.array(_embed([d["input_template"] for d in pool]))
            cache[key] = mat / np.linalg.norm(mat, axis=1, keepdims=True)
        q = np.array(_embed([row["input_template"]])[0])
        return cache[key] @ (q / np.linalg.norm(q))
    from sklearn.feature_extraction.text import TfidfVectorizer

    if key not in cache:
        vec = TfidfVectorizer(stop_words="english")
        cache[key] = (vec, vec.fit_transform([d["input_template"] for d in pool]))
    vec, mat = cache[key]
    return (mat @ vec.transform([row["input_template"]]).T).toarray().ravel()


def _rank_by_similarity(
    row, pool: list[dict], ctx=None, max_per_question: int = 2, method: str = "tfidf"
) -> list[dict]:
    """Same-group demos first, then by similarity to the question.

    At most `max_per_question` demos share a question text (Grouped data repeats each
    question across groups), so the demo set stays varied.
    """
    if len(pool) <= 1:
        return pool
    sims = _similarities(row, pool, ctx if ctx is not None else {}, method)
    persona = _filled_persona(row)
    order = sorted(
        range(len(pool)),
        key=lambda i: (-(pool[i].get("persona") == persona), -sims[i]),
    )
    seen: dict[str, int] = {}
    ranked = []
    for i in order:
        q = pool[i]["input_template"]
        if seen.get(q, 0) >= max_per_question:
            continue
        seen[q] = seen.get(q, 0) + 1
        ranked.append(pool[i])
    return ranked


def _span_entropy(ranked: list[dict], k: int) -> list[dict]:
    """k demos, most similar first within each entropy tercile of the pool."""
    if len(ranked) <= k:
        return ranked
    by_h = sorted(ranked, key=lambda d: d["h"])
    third = max(1, len(by_h) // 3)
    bins = [by_h[:third], by_h[third : 2 * third], by_h[2 * third :]]
    rank = {id(d): i for i, d in enumerate(ranked)}
    picked: list[dict] = []
    per = [k // 3 + (1 if i < k % 3 else 0) for i in range(3)]
    for b, n in zip(bins, per):
        picked += sorted(b, key=lambda d: rank[id(d)])[:n]
    return sorted(picked, key=lambda d: rank[id(d)])


def _demo_block(demos: list[dict], annotate: bool) -> str:
    blocks = []
    for d in demos:
        total = sum(d["human_answer"].values()) or 1.0
        pct = {k: round(100 * v / total) for k, v in d["human_answer"].items()}
        note = f"\n(How spread out real answers were: {_spread_label(d['h'])})" if annotate else ""
        blocks.append(f"**Question**: {d['input_template']}\n**Answer**: {json.dumps(pct)}{note}")
    return "\n\n".join(blocks)


def _inject(row, ctx, demos: list[dict], annotate: bool, hint: str = "") -> tuple[str, str, dict]:
    keys = list(row["human_answer"].keys())
    prefix = ""
    if demos:
        prefix = (
            "Here are real response distributions previously measured for this group:\n\n"
            + _demo_block(demos, annotate)
            + "\n\n"
            + hint
            + "Now estimate the same for a new question.\n\n"
        )
    return (
        SYSTEM_PREFIX + _filled_persona(row),
        prefix + _official_user(row["input_template"], keys),
        {},
    )


_SPREAD_HINT = (
    "Note that how contested a question is varies a lot: for some questions nearly "
    "everyone picks one option, for others answers are spread across several. "
    "Judge how contested the new question is, and let your distribution be as "
    "concentrated or as spread as real answers would be.\n\n"
)


def _fewshot_k(k: int):
    def arm(row, ctx):
        return _inject(row, ctx, _demo_pool(row, ctx)[:k], annotate=False)

    return arm


def arm_retr6(row, ctx):
    """Question-similar demos from the dataset (TF-IDF), no annotations."""
    demos = _rank_by_similarity(row, _demo_pool(row, ctx), ctx)[:6]
    return _inject(row, ctx, demos, annotate=False)


def arm_retr6_ent(row, ctx):
    """Similar demos, each labelled with how spread out the real answers were."""
    demos = _rank_by_similarity(row, _demo_pool(row, ctx), ctx)[:6]
    return _inject(row, ctx, demos, annotate=True, hint=_SPREAD_HINT)



def arm_retr6_rev(row, ctx):
    """retr6 with the most similar demo placed last (closest to the question)."""
    demos = _rank_by_similarity(row, _demo_pool(row, ctx), ctx)[:6][::-1]
    return _inject(row, ctx, demos, annotate=False)


def arm_retr6_emb(row, ctx):
    """retr6 with embedding (semantic) retrieval instead of TF-IDF."""
    demos = _rank_by_similarity(row, _demo_pool(row, ctx), ctx, method="emb")[:6]
    return _inject(row, ctx, demos, annotate=False)


def _profile_distance(a: list[float], b: list[float], width: int = 4) -> float:
    a = (a + [0.0] * width)[:width]
    b = (b + [0.0] * width)[:width]
    return sum(abs(x - y) for x, y in zip(a, b))


def arm_retr6_shape(row, ctx, candidates: int = 30):
    """Shape-conditioned retrieval: among the most similar candidates, keep the 6 whose
    answer profile is closest to a first-pass (base prompt) prediction."""
    ranked = _rank_by_similarity(row, _demo_pool(row, ctx), ctx)[:candidates]
    first = ctx.get("first_pass", {}).get(int(row.name))
    if first is None or len(ranked) <= 6:
        return _inject(row, ctx, ranked[:6], annotate=False)
    dist = {id(d): _profile_distance(first, _sorted_probs(d["human_answer"])) for d in ranked}
    keep = set(map(id, sorted(ranked, key=lambda d: dist[id(d)])[:6]))
    return _inject(row, ctx, [d for d in ranked if id(d) in keep], annotate=False)


def arm_span6_ent(row, ctx):
    """Demos spanning low/mid/high-entropy questions, labelled, plus the spread hint."""
    ranked = _rank_by_similarity(row, _demo_pool(row, ctx), ctx)
    demos = _span_entropy(ranked, 6)
    return _inject(row, ctx, demos, annotate=True, hint=_SPREAD_HINT)


def arm_span6(row, ctx):
    """Entropy-spanning demos with no labels (isolates selection from annotation)."""
    ranked = _rank_by_similarity(row, _demo_pool(row, ctx), ctx)
    return _inject(row, ctx, _span_entropy(ranked, 6), annotate=False)



# --------------------------------------------------------------------------- #
# variant A: option-agnostic shape statistics (no example questions)
# --------------------------------------------------------------------------- #


def _sorted_probs(human_answer: dict) -> list[float]:
    total = sum(human_answer.values()) or 1.0
    return sorted((v / total for v in human_answer.values()), reverse=True)


def _median(values: list[float]) -> float:
    v = sorted(values)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def _stats_lines(demos: list[dict], label: str, profiles: bool) -> str:
    profs = [_sorted_probs(d["human_answer"]) for d in demos]
    top1 = [p[0] for p in profs]
    top2 = [p[1] if len(p) > 1 else 0.0 for p in profs]
    dominant = sum(1 for t in top1 if t > 0.7) / len(top1)
    lines = [
        f"{label} ({len(demos)} questions):",
        f"- The most popular option received a median of {100 * _median(top1):.0f}% "
        f"(range {100 * min(top1):.0f}-{100 * max(top1):.0f}%).",
        f"- The second most popular option received a median of {100 * _median(top2):.0f}%.",
        f"- In {100 * dominant:.0f}% of these questions a single option got more than 70% of answers.",
        f"- Spread of answers (0 = everyone agrees, 1 = evenly split): median "
        f"{_median([d['h'] for d in demos]):.2f}.",
    ]
    if profiles:
        shown = "; ".join("/".join(f"{100 * x:.0f}" for x in p[:4]) for p in profs)
        lines.append(f"- Sorted answer shares per question (top 4 options): {shown}.")
    return "\n".join(lines)


def _stats_arm(k: int, with_pool: bool, profiles: bool):
    def arm(row, ctx):
        keys = list(row["human_answer"].keys())
        pool = _demo_pool(row, ctx)
        ranked = _rank_by_similarity(row, pool, ctx)
        nbrs = ranked[:k]
        parts = []
        if nbrs:
            parts.append(_stats_lines(nbrs, "Summary of real answers to similar questions", profiles))
        if with_pool and len(pool) >= 8:
            parts.append(_stats_lines(pool, "Summary across all questions in this survey", False))
        prefix = ""
        if parts:
            prefix = (
                "\n\n".join(parts)
                + "\n\nUse this only as a guide to how concentrated real answers tend to be; "
                "decide for yourself which options get the share.\n\n"
            )
        return (
            SYSTEM_PREFIX + _filled_persona(row),
            prefix + _official_user(row["input_template"], keys),
            {},
        )

    return arm


# --------------------------------------------------------------------------- #
# variant B: segment decomposition (reasoning structure, no gold data)
# --------------------------------------------------------------------------- #


def _segments_arm(n_seg: int, soft: bool):
    def arm(row, ctx):
        keys = list(row["human_answer"].keys())
        seg_fmt = (
            '{"share": X, "dist": ' + _fmt(keys) + "}"
            if soft
            else '{"share": X, "choice": "<one option letter>"}'
        )
        what = (
            "the percentages of that segment choosing each option (summing to 100)"
            if soft
            else "the single option that segment would choose"
        )
        user = (
            f"**Question**: {row['input_template']}\n\n"
            f"Your group is made up of different kinds of people. Split it into {n_seg} "
            "distinct segments that would tend to answer differently. For each segment give "
            f"its share of the group (the shares sum to 100) and {what}.\n"
            'Output only valid JSON: {"segments": [' + seg_fmt + ", ...]}\n**Answer**:"
        )
        return (
            SYSTEM_PREFIX + _filled_persona(row),
            user,
            {"segments": "soft" if soft else "hard", "max_output_tokens": 900},
        )

    return arm



def _soft_segments_arm(instruction: str, max_tokens: int = 1000):
    """Segment prompt where the instruction text varies; segments always answer softly."""

    def arm(row, ctx):
        keys = list(row["human_answer"].keys())
        user = (
            f"**Question**: {row['input_template']}\n\n{instruction}\n"
            'Output only valid JSON: {"segments": [{"share": X, "dist": '
            + _fmt(keys)
            + "}, ...]}\n**Answer**:"
        )
        return (
            SYSTEM_PREFIX + _filled_persona(row),
            user,
            {"segments": "soft", "max_output_tokens": max_tokens},
        )

    return arm


_ADAPTIVE = (
    "Your group is made up of different kinds of people. First decide how contested this "
    "question is within your group. If nearly everyone in the group would answer the same "
    "way, use ONE segment (share 100) and just give that distribution. If views are mixed, "
    "use 2-3 segments. If the group is deeply divided, use 4-5 segments. For each segment "
    "give its share of the group (shares sum to 100) and the percentages of that segment "
    "choosing each option (summing to 100)."
)

_RESPONSE_STYLE = (
    "Your group is a mix of: (a) 2-3 opinion-driven segments that hold substantive, "
    "differing views on this question; (b) one segment with no strong view (undecided, "
    "does not know, or does not care) that would pick a neutral, middle or 'don't know' "
    "style option if one exists; (c) one segment that answers casually and tends to agree "
    "with whatever is stated. Give each segment's share of the group (shares sum to 100) "
    "and the percentages of that segment choosing each option (summing to 100)."
)


def _archetypes_for(row, ctx) -> list[str]:
    return ctx.get("archetypes", {}).get(_filled_persona(row), [])


def arm_B_dict(row, ctx):
    """Fixed archetype dictionary per group; the model sets shares and answers per archetype."""
    arch = _archetypes_for(row, ctx)
    if not arch:
        return arm_B_n3_soft_fallback(row, ctx)
    listing = "\n".join(f"{i + 1}. {a}" for i, a in enumerate(arch))
    return _soft_segments_arm(
        "Your group consists of these types of people:\n" + listing + "\n"
        "For each type, give its share of the group on this question (shares sum to 100) and "
        "the percentages of that type choosing each option (summing to 100). Use exactly one "
        "segment per type, in the order listed.",
        max_tokens=1200,
    )(row, ctx)


def arm_B_agents(row, ctx):
    """One independent call per archetype; the answers are averaged with equal weight."""
    arch = _archetypes_for(row, ctx)
    keys = list(row["human_answer"].keys())
    user = _official_user(row["input_template"], keys)
    base_system = SYSTEM_PREFIX + _filled_persona(row)
    prompts = [
        (
            base_system + "\n\nAnswer specifically for this type of person within the group: " + a,
            user,
        )
        for a in arch
    ] or [(base_system, user)]
    return base_system, user, {"prompts": prompts}


arm_B_n3_soft_fallback = _segments_arm(3, True)



# --------------------------------------------------------------------------- #
# hybrids: segments from a first call, one independent persona call per segment,
# combined with the segments' shares (not equal weights)
# --------------------------------------------------------------------------- #


def _parse_json_obj(raw: str):
    start, end = (raw or "").find("{"), (raw or "").rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None


def _weighted_merge(dists: list[dict], weights: list[float], keys: list[str]):
    pairs = [(d, w) for d, w in zip(dists, weights) if d is not None and w > 0]
    total = sum(w for _, w in pairs)
    if not pairs or total <= 0:
        return None
    return {k: sum(d[k] * w for d, w in pairs) / total for k in keys}


def _segment_agent_calls(call, row, keys, descriptions: list[str], rephrase: bool):
    """One independent call per segment description; returns (dists, pt, ot)."""
    user = _official_user(row["input_template"], keys)
    if rephrase:
        user = user.replace("your group", "your segment")
    base_system = SYSTEM_PREFIX + _filled_persona(row)
    dists, pt_sum, ot_sum = [], 0, 0
    for desc in descriptions:
        raw, pt, ot = call(
            base_system
            + "\n\nYou are answering as one specific segment of this group, not as the "
            + f"whole group: {desc}\nGive the distribution for this segment only.",
            user,
            {},
        )
        pt_sum, ot_sum = pt_sum + pt, ot_sum + ot
        dists.append(_parse_dist(raw, keys))
    return dists, pt_sum, ot_sum


def _hybrid_arm(n_seg: int):
    """Stage 1: the model invents n segments that span the range of views and gives their
    shares. Stage 2: one persona call per segment. Final: share-weighted average."""

    def arm(row, ctx):
        keys = list(row["human_answer"].keys())

        def pipeline(call):
            user1 = (
                f"**Question**: {row['input_template']}\n\n"
                f"Your group is made up of different kinds of people. Split it into {n_seg} "
                "distinct segments that together cover the full range of views in the group on "
                "this question, from the most common to the least common, including any "
                "minority or outlier view. For each segment give a short description of who "
                "they are and what shapes their view (one or two sentences; do not state their "
                "answer yet) and its share of the group (the shares sum to 100).\n"
                'Output only valid JSON: {"segments": [{"description": "...", "share": X}, ...]}'
                "\n**Answer**:"
            )
            raw, pt, ot = call(SYSTEM_PREFIX + _filled_persona(row), user1, {"max_output_tokens": 900})
            obj = _parse_json_obj(raw)
            try:
                segs = [(str(x["description"]), float(x["share"])) for x in obj["segments"]]
            except (TypeError, KeyError, ValueError):
                return None, pt, ot
            if len(segs) < 2:
                return None, pt, ot
            dists, pt2, ot2 = _segment_agent_calls(call, row, keys, [d for d, _ in segs], True)
            diag = [
                {"desc": desc, "share": w, "dist": d}
                for (desc, w), d in zip(segs, dists)
                if d is not None
            ]
            return _weighted_merge(dists, [w for _, w in segs], keys), pt + pt2, ot + ot2, diag

        return "", "", {"pipeline": pipeline}

    return arm


def arm_B_agents_w(row, ctx):
    """B_agents with the cached archetypes, but weighted by model-estimated shares for this
    question instead of equal weights."""
    arch = _archetypes_for(row, ctx)
    keys = list(row["human_answer"].keys())

    def pipeline(call):
        if not arch:
            return None, 0, 0
        listing = "\n".join(f"{i + 1}. {a}" for i, a in enumerate(arch))
        user1 = (
            f"**Question**: {row['input_template']}\n\n"
            "Your group consists of these types of people:\n" + listing + "\n\n"
            "For THIS question, estimate what share of the group each type makes up in terms of "
            "how many people would answer this question substantively (the shares sum to 100). "
            f'Output only valid JSON: {{"shares": [X, ...]}} with exactly {len(arch)} numbers in '
            "the order listed.\n**Answer**:"
        )
        raw, pt, ot = call(SYSTEM_PREFIX + _filled_persona(row), user1, {"max_output_tokens": 200})
        obj = _parse_json_obj(raw)
        try:
            weights = [float(x) for x in obj["shares"]]
            if len(weights) != len(arch):
                raise ValueError
        except (TypeError, KeyError, ValueError):
            weights = [1.0] * len(arch)  # fall back to equal weights
        dists, pt2, ot2 = _segment_agent_calls(call, row, keys, arch, False)
        diag = [
            {"desc": a, "share": w, "dist": d}
            for a, w, d in zip(arch, weights, dists)
            if d is not None
        ]
        return _weighted_merge(dists, weights, keys), pt + pt2, ot + ot2, diag

    return "", "", {"pipeline": pipeline}


def _segments_detail(raw: str, keys: list[str]) -> list[dict] | None:
    """Per-segment shares and normalized distributions from a soft segment answer."""
    obj = _parse_json_obj(raw)
    try:
        out = []
        for seg in obj["segments"]:
            d = {k: float(seg["dist"].get(k, 0.0)) for k in keys}
            total = sum(d.values())
            if total > 0:
                out.append({"share": float(seg["share"]), "dist": {k: v / total for k, v in d.items()}})
        return out or None
    except (TypeError, KeyError, ValueError, AttributeError):
        return None



# --------------------------------------------------------------------------- #
# persona panels (observable): planner writes question-specific personas + shares,
# one independent call per persona, share-weighted merge. Every step is logged.
# --------------------------------------------------------------------------- #

_GROUND_NOTE = (
    "Here are real response distributions previously measured for this group on similar "
    "questions:\n\n{demos}\n\nUse them to judge which views are common in this group, which "
    "way the group leans, and how divided it is.\n\n"
)


_PLANNER_FREE = (
    "Describe {n} types of people in your group that matter for THIS question. For "
    "each, say who they are and how they see this issue (one or two sentences; do "
    "not give percentages). Types may agree with each other: only make them differ "
    "where real people in this group differ. Give each type's share of the group "
    "(shares sum to 100). If most of the group thinks alike, give that type a large "
    "share.\n"
    'Output only valid JSON: {{"types": [{{"description": "...", "share": X}}, ...]}}'
)

_PLANNER_CONSENSUS = (
    "First, using the real distributions above as evidence, estimate how much this group "
    "agrees on THIS question: the percentage of the group that would pick the single most "
    "common answer. Real survey groups often agree strongly (70-95%) on factual or "
    "everyday questions and split on contested ones.\n"
    "Then describe {n} types of people in your group that matter for this question: who "
    "they are and how they see this issue (one or two sentences; no percentages). Several "
    "types may give the same answer. The types who would pick the most common answer must "
    "together make up about the agreement percentage you estimated; do not invent more "
    "disagreement than the evidence shows. Give each type's share of the group (shares sum "
    "to 100).\n"
    'Output only valid JSON: {{"agreement": X, "types": [{{"description": "...", "share": X}}, ...]}}'
)

_PLANNER_ADAPTIVE = (
    "First, using the real distributions above as evidence, estimate how much this group "
    "agrees on THIS question: the percentage of the group that would pick the single most "
    "common answer. Real survey groups often agree strongly (70-95%) on factual or "
    "everyday questions and split on contested ones.\n"
    "Then describe between 1 and 5 types of people in your group that matter for this "
    "question: who they are and how they see this issue (one or two sentences; no "
    "percentages). Use few types when the group mostly agrees and more when it is divided. "
    "The types who would pick the most common answer must together make up about the "
    "agreement percentage you estimated. Give each type's share of the group (shares sum "
    "to 100).\n"
    'Output only valid JSON: {{"agreement": X, "types": [{{"description": "...", "share": X}}, ...]}}'
)


def _panel_arm(n: int, ground_planner: bool, ground_agents: bool, planner: str = "free"):
    template = {"free": _PLANNER_FREE, "consensus": _PLANNER_CONSENSUS, "adaptive": _PLANNER_ADAPTIVE}[planner]

    def arm(row, ctx):
        keys = list(row["human_answer"].keys())
        demos = (
            _rank_by_similarity(row, _demo_pool(row, ctx), ctx)[:6]
            if (ground_planner or ground_agents)
            else []
        )
        ground = _GROUND_NOTE.format(demos=_demo_block(demos, False)) if demos else ""
        base_system = SYSTEM_PREFIX + _filled_persona(row)

        def pipeline(call):
            user1 = (
                (ground if ground_planner else "")
                + f"**Question**: {row['input_template']}\n\n"
                + template.format(n=n)
                + "\n**Answer**:"
            )
            raw, pt, ot = call(base_system, user1, {"max_output_tokens": 900})
            obj = _parse_json_obj(raw)
            try:
                types = [(str(x["description"]), float(x["share"])) for x in obj["types"]]
            except (TypeError, KeyError, ValueError):
                return None, pt, ot
            if not types:
                return None, pt, ot
            agreement = obj.get("agreement") if isinstance(obj, dict) else None
            agent_user = (ground if ground_agents else "") + _official_user(
                row["input_template"], keys
            ).replace("your group", "people of your type")
            dists, pt2, ot2 = [], 0, 0
            for desc, _ in types:
                r2, a, b = call(
                    base_system
                    + "\n\nYou are answering as one specific type of person in this group: "
                    + desc,
                    agent_user,
                    {},
                )
                pt2, ot2 = pt2 + a, ot2 + b
                dists.append(_parse_dist(r2, keys))
            diag = [
                {"desc": d, "share": w, "dist": dist, **({"agreement": agreement} if agreement is not None else {})}
                for (d, w), dist in zip(types, dists)
                if dist is not None
            ]
            return _weighted_merge(dists, [w for _, w in types], keys), pt + pt2, ot + ot2, diag

        return "", "", {"pipeline": pipeline}

    return arm



# --------------------------------------------------------------------------- #
# option-order debiasing and multi-candidate answers
# --------------------------------------------------------------------------- #


def _reversed_row(row):
    """Same question with the option texts in reverse order (letters stay A, B, ...).
    Returns (row copy, mapping new_letter -> original_letter)."""
    keys = list(row["human_answer"].keys())
    head, opts = row["input_template"].rsplit("Options:", 1)
    lines = [ln for ln in opts.strip().split("\n") if ln.strip()]
    if any(not re.match(r"^\([A-Z]\): ", ln) for ln in lines):
        return None, None  # multi-line options: keep the original order only
    texts = dict(re.findall(r"^\(([A-Z])\): (.*)$", opts, re.M))
    if [k for k in keys if k in texts] != keys:
        return None, None
    rev = keys[::-1]
    r2 = row.copy()
    r2["_orig_template"] = row["input_template"]
    r2["_rev_map"] = {k: rev[j] for j, k in enumerate(keys)}
    r2["input_template"] = head + "Options:\n" + "\n".join(
        f"({k}): {texts[rev[j]]}" for j, k in enumerate(keys)
    )
    r2["human_answer"] = {k: row["human_answer"][rev[j]] for j, k in enumerate(keys)}
    return r2, {k: rev[j] for j, k in enumerate(keys)}


def _rev2(base):
    """Run a single-call arm on the original and the reversed option order; average after
    mapping the reversed answer back to the original options. Both orders are logged."""

    def arm(row, ctx):
        keys = list(row["human_answer"].keys())
        probe = base(row, ctx)[2]
        if "pipeline" in probe:  # base skips this row (out of scope)
            return "", "", probe

        def parse(raw, opts):
            seg = opts.get("segments")
            return _parse_segments(raw, keys, seg == "soft") if seg else _parse_dist(raw, keys)

        def pipeline(call):
            s1, u1, o1 = base(row, ctx)
            raw1, pt, ot = call(s1, u1, {k: v for k, v in o1.items() if k != "segments"})
            d1 = parse(raw1, o1)
            r2, mp = _reversed_row(row)
            d2 = None
            if r2 is not None:
                s2, u2, o2 = base(r2, ctx)
                raw2, a, b = call(s2, u2, {k: v for k, v in o2.items() if k != "segments"})
                pt, ot = pt + a, ot + b
                d2r = parse(raw2, o2)
                d2 = {mp[k]: v for k, v in d2r.items()} if d2r else None
            diag = [
                {"desc": "original order", "share": 1.0, "dist": d1},
                {"desc": "reversed order (mapped back)", "share": 1.0, "dist": d2},
            ]
            diag = [x for x in diag if x["dist"] is not None]
            return _weighted_merge([d1, d2], [1.0, 1.0], keys), pt, ot, diag

        return "", "", {"pipeline": pipeline}

    return arm


def arm_retr6_vs3(row, ctx):
    """retr6 demos; the model gives 3 candidate distributions with confidences, mixed."""
    keys = list(row["human_answer"].keys())
    demos = _rank_by_similarity(row, _demo_pool(row, ctx), ctx)[:6]
    prefix = (
        "Here are real response distributions previously measured for this group:\n\n"
        + _demo_block(demos, False)
        + "\n\nNow estimate the same for a new question.\n\n"
        if demos
        else ""
    )
    user = (
        prefix
        + f"**Question**: {row['input_template']}\n\n"
        "You are unsure what your group's real answer distribution is. Give 3 different "
        "plausible distributions (percentages over the options, each summing to 100), each "
        "with your confidence that it is the closest to the truth (confidences sum to 100).\n"
        'Output only valid JSON: {"candidates": [{"confidence": X, "dist": '
        + _fmt(keys)
        + "}, ...]}\n**Answer**:"
    )
    system = SYSTEM_PREFIX + _filled_persona(row)

    def pipeline(call):
        raw, pt, ot = call(system, user, {"max_output_tokens": 700})
        obj = _parse_json_obj(raw)
        try:
            cands = []
            for c in obj["candidates"]:
                d = {k: float(c["dist"].get(k, 0.0)) for k in keys}
                tot = sum(d.values())
                if tot > 0:
                    cands.append((float(c["confidence"]), {k: v / tot for k, v in d.items()}))
        except (TypeError, KeyError, ValueError, AttributeError):
            return None, pt, ot
        if not cands:
            return None, pt, ot
        diag = [{"desc": f"candidate {i + 1}", "share": w, "dist": d} for i, (w, d) in enumerate(cands)]
        return _weighted_merge([d for _, d in cands], [w for w, _ in cands], keys), pt, ot, diag

    return "", "", {"pipeline": pipeline}



def _on_reversed(base):
    """Run a pipeline arm on the reversed option order and map its answer (and every
    logged component) back to the original options."""

    def arm(row, ctx):
        r2, mp = _reversed_row(row)
        if r2 is None:
            return base(row, ctx)
        inner = base(r2, ctx)[2]["pipeline"]

        def back(d):
            return {mp[k]: v for k, v in d.items()} if d else d

        def pipeline(call):
            out = inner(call)
            merged = back(out[0])
            diag = [{**x, "dist": back(x["dist"])} for x in (out[3] if len(out) > 3 else [])]
            return merged, out[1], out[2], diag

        return "", "", {"pipeline": pipeline}

    return arm


def _grounded_segments_arm(n_seg: int):
    """B_n3_soft with the 6 retrieved real distributions shown first."""
    plain = _segments_arm(n_seg, True)

    def arm(row, ctx):
        system, user, opts = plain(row, ctx)
        demos = _rank_by_similarity(row, _demo_pool(row, ctx), ctx)[:6]
        if demos:
            user = _GROUND_NOTE.format(demos=_demo_block(demos, False)) + user
        return system, user, opts

    return arm


def _sampled(base, n: int, temperature: float):
    def arm(row, ctx):
        system, user, opts = base(row, ctx)
        return system, user, {**opts, "samples": n, "temperature": temperature}

    return arm



# --------------------------------------------------------------------------- #
# population composition (shares and attributes only, never answers)
# --------------------------------------------------------------------------- #

_COUNTRY_KEYS = ("country", "cntry")
_CONTEXT_SENTENCE = re.compile(r"(the year is|the timeframe is|you are from)", re.I)


def _country_of(vm: dict) -> str:
    for k in _COUNTRY_KEYS:
        if k in vm:
            return str(vm[k])
    return ""


def _group_sentence(persona: str) -> str:
    parts = re.split(r"(?<=\.)\s+", persona.strip())
    return " ".join(p for p in parts if not _CONTEXT_SENTENCE.search(p)).strip()


def _composition_index(grouped: pd.DataFrame) -> dict:
    """(dataset, country) -> attribute -> value -> [(group_size, question_text, sentence)].
    Built from single-attribute Grouped cells. Only sizes are kept, never answers."""
    idx: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for _, r in grouped.iterrows():
        vm = r["group_prompt_variable_map"]
        other = [k for k in vm if k not in _COUNTRY_KEYS]
        if len(other) != 1 or not r["group_size"] or r["group_size"] <= 0:
            continue
        sentence = _group_sentence(_filled_persona(r))
        idx[(r["dataset_name"], _country_of(vm))][other[0]][vm[other[0]]].append(
            (float(r["group_size"]), r["input_template"], sentence)
        )
    return idx


def _composition(row, ctx, min_coverage: float = 0.8, max_cells: int = 5) -> list[dict]:
    """Attributes whose cells cover the target population, each as cells with real shares.
    Sizes from the same question as the target are excluded."""
    vm = row["group_prompt_variable_map"]
    if any(k not in _COUNTRY_KEYS for k in vm):
        return []  # the target is already a subgroup
    dims = ctx.get("comp_index", {}).get((row["dataset_name"], _country_of(vm)), {})
    own = row.get("_orig_template", row["input_template"])
    raw = {}
    for dim, cells in dims.items():
        sized = {}
        for value, obs in cells.items():
            sizes = [sz for sz, q, _ in obs if q != own]
            if sizes:
                sized[value] = (float(np.median(sizes)), obs[0][2])
        if len(sized) >= 2:
            raw[dim] = sized
    if not raw:
        return []
    total = float(row["group_size"]) if row.get("group_size", -1) and row["group_size"] > 0 else 0.0
    total = total or max(sum(v[0] for v in c.values()) for c in raw.values())
    out = []
    for dim, sized in raw.items():
        coverage = sum(v[0] for v in sized.values()) / total
        if coverage < min_coverage:
            continue
        top = sorted(sized.items(), key=lambda kv: -kv[1][0])[:max_cells]
        tot = sum(v[0] for _, v in top)
        out.append(
            {
                "attribute": dim,
                "coverage": round(min(coverage, 9.99), 3),
                "cells": [
                    {"value": str(val), "share": v[0] / tot, "sentence": v[1]} for val, v in top
                ],
            }
        )
    # deterministic preference: more groups (so real vs equal weights can differ), then
    # coverage; no answer information is used
    out.sort(key=lambda d: (-len(d["cells"]), -min(d["coverage"], 1.0), d["attribute"]))
    return out


def _composition_text(comp: list[dict], max_attrs: int = 3) -> str:
    lines = ["Who makes up this population (share of respondents):"]
    for d in comp[:max_attrs]:
        cells = ", ".join(f"{c['value']} {round(100 * c['share'])}%" for c in d["cells"])
        lines.append(f"- {d['attribute']}: {cells}")
    return "\n".join(lines) + "\n\n"


def arm_C1_comp_direct(row, ctx):
    """retr6 + a short composition table; direct prediction. Uncovered targets are skipped."""
    comp = _composition(row, ctx)
    if not comp:
        return "", "", {"pipeline": lambda call: (None, 0, 0)}
    system, user, opts = arm_retr6(row, ctx)
    return system, _composition_text(comp) + user, opts


def arm_C2_comp_personas(row, ctx):
    """One call per top group of the preferred attribute (both option orders), with retr6
    demos; mixed with the groups' REAL shares. Equal-weight mix (C3) is computed offline
    from the logged per-group answers."""
    comp = _composition(row, ctx)
    if not comp:
        return "", "", {"pipeline": lambda call: (None, 0, 0)}
    dim = comp[0]
    keys = list(row["human_answer"].keys())

    def group_arm(sentence):
        def arm(r, c):
            system, user, opts = arm_retr6(r, c)
            return system + " " + sentence, user, opts

        return arm

    def pipeline(call):
        dists, diag, pt, ot = [], [], 0, 0
        for cell in dim["cells"]:
            inner = _rev2(group_arm(cell["sentence"]))(row, ctx)[2]["pipeline"]
            merged, a, b, both = inner(call)
            pt, ot = pt + a, ot + b
            dists.append(merged)
            diag.append(
                {
                    "desc": f"{dim['attribute']} = {cell['value']}",
                    "share": cell["share"],
                    "dist": merged,
                    "orders": both,
                }
            )
        diag = [x for x in diag if x["dist"] is not None]
        merged = _weighted_merge(dists, [c["share"] for c in dim["cells"]], keys)
        for x in diag:
            x["attribute_coverage"] = dim["coverage"]
        return merged, pt, ot, diag

    return "", "", {"pipeline": pipeline}



# --------------------------------------------------------------------------- #
# demo-source test (D0-D4): shared surveys only, both option orders
# --------------------------------------------------------------------------- #

D_DATASETS = ("Afrobarometer", "ESS", "ISSP", "LatinoBarometro", "OpinionQA")


def _stem(template: str) -> str:
    return re.sub(r"\s+", " ", template.split("Options:")[0]).strip().lower()


def _dpool(row, ctx) -> list[dict]:
    """Demo candidates for the D arms: spare rows of the same split and dataset (Pop uses all
    spare rows, not just 40), never a row whose question stem equals the target's."""
    key = f"{row['split']}|{row['dataset_name']}"
    own = _stem(row.get("_orig_template", row["input_template"]))
    return [d for d in ctx["dpool"].get(key, []) if d["stem"] != own]


def _build_dpool(pop_full, grouped_full, pop_n, grouped_n, seed) -> dict:
    out = defaultdict(list)
    for df, per in ((pop_full, pop_n), (grouped_full, grouped_n)):
        for _, row in extended_pool(df, per, seed, 3, 10**6).iterrows():
            if row["dataset_name"] not in D_DATASETS:
                continue
            e = _demo_entry(row)
            e["stem"] = _stem(row["input_template"])
            e["cell"] = _cell_key(row)
            out[f"{row['split']}|{row['dataset_name']}"].append(e)
    return dict(out)


def _topics(ctx) -> dict:
    """stem -> topic id, from k-means on question-stem embeddings per dataset (cached)."""
    if "_topics" in ctx:
        return ctx["_topics"]
    from sklearn.cluster import KMeans

    stems_by_ds = defaultdict(set)
    for key, pool in ctx["dpool"].items():
        ds = key.split("|", 1)[1]
        for d in pool:
            stems_by_ds[ds].add(d["stem"])
    for t in ctx.get("_target_stems", []):
        if t[0] in D_DATASETS:
            stems_by_ds[t[0]].add(t[1])
    topics = {}
    for ds, stems in stems_by_ds.items():
        stems = sorted(stems)
        X = np.array(_embed(stems))
        k = min(len(stems), max(6, round(len(stems) / 30)))
        labels = KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(X)
        for st, lab in zip(stems, labels):
            topics[(ds, st)] = int(lab)
    ctx["_topics"] = topics
    return topics


def _cap_per_stem(items: list[dict], n: int, cap: int = 2) -> list[dict]:
    seen, out = Counter(), []
    for d in items:
        if seen[d["stem"]] < cap:
            seen[d["stem"]] += 1
            out.append(d)
        if len(out) == n:
            break
    return out


def _shuffled(items: list[dict], row) -> list[dict]:
    items = list(items)
    random.Random(f"{row['dataset_name']}|{row.get('_orig_template', row['input_template'])}|{_filled_persona(row)}").shuffle(items)
    return items


def _cell_key(row) -> tuple:
    """Subgroup identity independent of survey wave: dataset, country, other attributes."""
    vm = row["group_prompt_variable_map"]
    return (
        row["dataset_name"],
        _country_of(vm),
        tuple(sorted((k, str(v)) for k, v in vm.items() if k not in _COUNTRY_KEYS)),
    )


def _d_demos(row, ctx, mode: str) -> list[dict]:
    pool = _dpool(row, ctx)
    if not pool:
        return []
    persona = _filled_persona(row)
    if mode == "D0":
        return _cap_per_stem(_rank_by_similarity(row, pool, ctx, max_per_question=10**6), 6)
    topics = _topics(ctx)
    tgt_topic = topics.get((row["dataset_name"], _stem(row.get("_orig_template", row["input_template"]))))
    same_topic = [d for d in pool if topics.get((row["dataset_name"], d["stem"])) == tgt_topic]
    cell = _cell_key(row)
    same_group = [d for d in pool if d["cell"] == cell]
    if mode == "D1":
        return _cap_per_stem(_shuffled(same_topic, row), 6)
    if mode == "D2":
        return _cap_per_stem(_shuffled(same_group, row), 6)
    if mode == "D3":
        both = [d for d in same_group if topics.get((row["dataset_name"], d["stem"])) == tgt_topic]
        picked = _cap_per_stem(_shuffled(both, row), 6)
        if len(picked) < 6:  # fill with same group, other topics
            rest = [d for d in _shuffled(same_group, row) if d not in picked]
            picked += _cap_per_stem(rest, 6 - len(picked))
        return picked
    raise ValueError(mode)


def _d_arm(mode: str):
    def arm(row, ctx):
        if row["dataset_name"] not in D_DATASETS:
            return "", "", {"pipeline": lambda call: (None, 0, 0)}
        return _inject(row, ctx, _d_demos(row, ctx, mode), annotate=False)

    return arm


def _same_question_other_groups(row, ctx, k: int = 6) -> list[tuple[str, dict]]:
    """DIAGNOSTIC ONLY. Other single-attribute groups' real answers to this same question
    in the same country; never the target's own cell, never the country total."""
    own_q = row.get("_orig_template", row["input_template"])
    vm = row["group_prompt_variable_map"]
    if not any(kk not in _COUNTRY_KEYS for kk in vm):
        return []
    own_sentence = _group_sentence(_filled_persona(row))
    cand = []
    for r in ctx["_grouped_by_q"].get((row["dataset_name"], _country_of(vm), own_q), []):
        if r["sentence"] == own_sentence:  # the target's own subgroup, any wave
            continue
        cand.append(r)
    cand.sort(key=lambda r: -r["size"])
    return [(r["sentence"], r["answer"]) for r in cand[:k]]


def arm_D4(row, ctx):
    if row["dataset_name"] not in D_DATASETS or row["split"] != "Grouped":
        return "", "", {"pipeline": lambda call: (None, 0, 0)}
    others = _same_question_other_groups(row, ctx)
    if not others:
        return "", "", {"pipeline": lambda call: (None, 0, 0)}
    keys = list(row["human_answer"].keys())
    mp = row.get("_rev_map")  # reversed-order run: show the other groups in the same letters
    lines = []
    for sentence, ans in others:
        tot = sum(ans.values()) or 1.0
        dist = {kk: round(100 * ans.get(mp[kk] if mp else kk, 0.0) / tot) for kk in keys}
        lines.append(f"- {sentence or 'Another group'}: {json.dumps(dist)}")
    prefix = (
        "Real answer distributions to THIS question from other groups in the same country "
        "(not your group):\n" + "\n".join(lines) + "\n\n"
    )
    return (
        SYSTEM_PREFIX + _filled_persona(row),
        prefix + _official_user(row["input_template"], keys),
        {},
    )


def _index_grouped_by_question(grouped: pd.DataFrame) -> dict:
    idx = defaultdict(list)
    for _, r in grouped.iterrows():
        vm = r["group_prompt_variable_map"]
        other = [k for k in vm if k not in _COUNTRY_KEYS]
        if len(other) == 1 and r["dataset_name"] in D_DATASETS:
            p = _filled_persona(r)
            idx[(r["dataset_name"], _country_of(vm), r["input_template"])].append(
                {"persona": p, "sentence": _group_sentence(p), "size": float(r["group_size"]), "answer": r["human_answer"]}
            )
    return idx


def _parse_segments(raw: str, keys: list[str], soft: bool) -> dict[str, float] | None:
    start, end = (raw or "").find("{"), (raw or "").rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        segs = json.loads(raw[start : end + 1])["segments"]
        out = {k: 0.0 for k in keys}
        for seg in segs:
            share = float(seg["share"])
            if soft:
                d = {k: float(seg["dist"].get(k, 0.0)) for k in keys}
                total = sum(d.values())
                if total <= 0:
                    continue
                for k in keys:
                    out[k] += share * d[k] / total
            else:
                choice = str(seg["choice"]).strip().strip("()")
                if choice not in out:
                    continue
                out[choice] += share
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
        return None
    total = sum(out.values())
    return {k: v / total for k, v in out.items()} if total > 0 else None


ARMS = {
    "base": arm_base,
    "no_persona": arm_no_persona,
    "swap_persona": arm_swap_persona,
    "cot": arm_cot,
    "think": arm_think,
    "plural": arm_plural,
    "fewshot": arm_fewshot,
    "plural_fewshot": arm_plural_fewshot,
    "ensemble": arm_ensemble,
    "fs_k6": _fewshot_k(6),
    "fs_k12": _fewshot_k(12),
    "retr6": arm_retr6,
    "retr6_ent": arm_retr6_ent,
    "span6": arm_span6,
    "span6_ent": arm_span6_ent,
}
# hyper-parameter grids for the variant search (names encode the config)
for _k in (6, 12):
    for _pool in (False, True):
        ARMS[f"A_k{_k}{'_pool' if _pool else ''}"] = _stats_arm(_k, _pool, False)
ARMS["retr6_rev"] = arm_retr6_rev
ARMS["retr6_emb"] = arm_retr6_emb
ARMS["retr6_shape"] = arm_retr6_shape
ARMS["B_adaptive"] = _soft_segments_arm(_ADAPTIVE)
ARMS["B_dict"] = arm_B_dict
ARMS["B_agents"] = arm_B_agents
ARMS["B_hybrid3"] = _hybrid_arm(3)
ARMS["B_hybrid5"] = _hybrid_arm(5)
ARMS["B_agents_w"] = arm_B_agents_w
ARMS["Bdiag_n3_soft"] = _segments_arm(3, True)


def _only_datasets(base, datasets):
    def arm(row, ctx):
        if row["dataset_name"] not in datasets:
            return "", "", {"pipeline": lambda call: (None, 0, 0)}
        return base(row, ctx)

    return arm


# traced segments on the four Pop-only task datasets (mechanism check, eval)
ARMS["Bdiag_n3_soft_tasks"] = _only_datasets(
    _segments_arm(3, True), ("OSPsychMACH", "Choices13k", "NumberGame", "OSPsychMGKT")
)
ARMS["Bdiag_hybrid3"] = _hybrid_arm(3)
ARMS["Bdiag_agents_w"] = arm_B_agents_w
ARMS["P_topic5"] = _panel_arm(5, False, False)
ARMS["P_ground5"] = _panel_arm(5, True, False)
ARMS["P_groundall5"] = _panel_arm(5, True, True)
ARMS["retr6_rev2"] = _rev2(arm_retr6)
ARMS["B_n3_soft_rev2"] = _rev2(_segments_arm(3, True))
ARMS["retr6_vs3"] = arm_retr6_vs3
ARMS["P_groundall5_R"] = _on_reversed(_panel_arm(5, True, True))
ARMS["B_ground3"] = _grounded_segments_arm(3)
ARMS["B_ground3_rev2"] = _rev2(_grounded_segments_arm(3))
ARMS["B_n3_soft_t1x3"] = _sampled(_segments_arm(3, True), 3, 1.0)
def arm_C1_rev2(row, ctx):
    if not _composition(row, ctx):
        return "", "", {"pipeline": lambda call: (None, 0, 0)}
    return _rev2(arm_C1_comp_direct)(row, ctx)


ARMS["C1_comp_direct"] = arm_C1_rev2
ARMS["C2_comp_personas"] = arm_C2_comp_personas
ARMS["D0_retr6"] = _rev2(_d_arm("D0"))
ARMS["D1_same_topic"] = _rev2(_d_arm("D1"))
ARMS["D2_same_group"] = _rev2(_d_arm("D2"))
ARMS["D3_same_group_same_topic"] = _rev2(_d_arm("D3"))
ARMS["D4_other_groups_same_question"] = _rev2(arm_D4)
ARMS["P_cons5"] = _panel_arm(5, True, True, "consensus")
ARMS["P_adapt"] = _panel_arm(5, True, True, "adaptive")


# --------------------------------------------------------------------------- #
# LEAK CEILING (not a valid benchmark score): every other SimBench row that asks this
# identical question (country total, other subgroups, other countries) is shown.
# --------------------------------------------------------------------------- #

_LEAK_IDX: dict | None = None
_leak_lock = threading.Lock()


def _leak_index() -> dict:
    global _LEAK_IDX
    with _leak_lock:
        if _LEAK_IDX is None:
            idx = defaultdict(list)
            for split in ("Pop", "Grouped"):
                for _, r in load_split(split).iterrows():
                    idx[r["input_template"]].append(r)
            _LEAK_IDX = dict(idx)
    return _LEAK_IDX


def _leak_sources(row, allowed: tuple | None = None) -> list[tuple[str, str, float, dict]]:
    from human_sim.simbench_leak_ceiling import relation

    own_q = row.get("_orig_template", row["input_template"])
    own_persona, keys = _filled_persona(row), set(row.get("_orig_keys", row["human_answer"].keys()))
    out = []
    for s in _leak_index().get(own_q, []):
        if s["split"] == row["split"] and _filled_persona(s) == own_persona:
            continue
        if set(s["human_answer"]) != keys:
            continue
        if allowed is not None and relation(row, s) not in allowed:
            continue
        out.append((relation(row, s), _group_sentence(_filled_persona(s)) or s["dataset_name"],
                    float(s.get("group_size", 0) or 0), s["human_answer"]))
    order = {"same_group_other_wave": 0, "country_total": 1, "same_country_subgroups": 2, "disjoint_subgroup": 2,
             "other_countries": 3, "other_dataset": 4}
    caps = {"same_group_other_wave": 2, "country_total": 2, "same_country_subgroups": 10, "disjoint_subgroup": 10,
            "other_countries": 8, "other_dataset": 3}
    out.sort(key=lambda x: (order[x[0]], -x[2]))
    kept, seen = [], Counter()
    for x in out:
        if seen[x[0]] < caps[x[0]]:
            seen[x[0]] += 1
            kept.append(x)
    return kept


_LEAK_LABEL = {"same_group_other_wave": "your own group, another survey wave", "country_total": "your whole country",
               "same_country_subgroups": "another group in your country",
               "disjoint_subgroup": "another group in your country (no overlap with yours)", "other_countries": "another country",
               "other_dataset": "another survey"}


_NO_OVERLAP = ("disjoint_subgroup", "other_countries")


def arm_L_leak(row, ctx, allowed: tuple | None = None):
    src = _leak_sources(row, allowed)
    if not src:
        return "", "", {"pipeline": lambda call: (None, 0, 0)}
    keys = list(row["human_answer"].keys())
    mp = row.get("_rev_map")
    lines = []
    for rel, sentence, size, ans in src:
        tot = sum(ans.values()) or 1.0
        dist = {kk: round(100 * ans.get(mp[kk] if mp else kk, 0.0) / tot) for kk in keys}
        n = f", n={int(size)}" if size else ""
        lines.append(f"- [{_LEAK_LABEL[rel]}{n}] {sentence}: {json.dumps(dist)}")
    prefix = (
        "Real measured answer distributions to THIS exact question from related groups:\n"
        + "\n".join(lines)
        + "\n\nUse them as strong evidence. Your group may differ from these groups; adjust for how "
        "your group differs, but do not invent differences the evidence does not support.\n\n"
    )
    return SYSTEM_PREFIX + _filled_persona(row), prefix + _official_user(row["input_template"], keys), {}


ARMS["L_leak"] = _rev2(arm_L_leak)
# same question, but only populations that share no respondents with the target
ARMS["L_strict"] = _rev2(lambda row, ctx: arm_L_leak(row, ctx, _NO_OVERLAP))
ARMS["B_style"] = _soft_segments_arm(_RESPONSE_STYLE)
ARMS["A_k12_prof"] = _stats_arm(12, False, True)
ARMS["A_k12_pool_prof"] = _stats_arm(12, True, True)
for _n in (3, 5):
    for _soft in (False, True):
        ARMS[f"B_n{_n}_{'soft' if _soft else 'hard'}"] = _segments_arm(_n, _soft)


# --------------------------------------------------------------------------- #
# model calls
# --------------------------------------------------------------------------- #


def _is_throttle(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        m in text
        for m in (
            "429",
            "resource_exhausted",
            "resource exhausted",
            "quota",
            "rate limit",
            "too many requests",
            "503",
            "unavailable",
        )
    )


def _is_auth(exc: Exception) -> bool:
    text = str(exc).lower()
    return "unauthenticated" in text or "401" in text or "invalid authentication" in text


def _parse_dist(raw: str, keys: list[str]) -> dict[str, float] | None:
    matches = re.findall(r"\{[^{}]*\}", raw or "")
    for candidate in reversed(matches):
        try:
            data = json.loads(candidate)
            vals = {k: float(data[k]) for k in keys}
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
        total = sum(vals.values())
        if total > 0:
            return {k: v / total for k, v in vals.items()}
    return None


CLAUDE_REGION = "global"
NO_SAMPLING_PREFIXES = ("claude-sonnet-5", "claude-opus-5", "claude-opus-4-7", "claude-opus-4-8", "claude-fable")


def _call_claude(model: str, system: str, user: str, opts: dict) -> tuple[str, int, int]:
    """Claude on Vertex (rawPredict). Same auth as Gemini; JSON is requested in the prompt."""
    import requests

    host = (
        "aiplatform.googleapis.com"
        if CLAUDE_REGION == "global"
        else f"{CLAUDE_REGION}-aiplatform.googleapis.com"
    )
    url = (
        f"https://{host}/v1/projects/{GCP_PROJECT}/locations/{CLAUDE_REGION}"
        f"/publishers/anthropic/models/{model}:rawPredict"
    )
    body = {
        "anthropic_version": "vertex-2023-10-16",
        "max_tokens": opts.get("max_output_tokens", 512),
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    if model.startswith(NO_SAMPLING_PREFIXES):
        # newer models reject sampling parameters; keep thinking off where allowed
        if model.startswith("claude-sonnet-5-5"):
            body["thinking"] = {"type": "between_tools"}
    else:
        body["temperature"] = opts.get("temperature", 0.0)
    last: Exception | None = None
    for attempt in range(8):
        try:
            token = vertex_credentials().token
            resp = requests.post(
                url, headers={"Authorization": f"Bearer {token}"}, json=body, timeout=120
            )
            if resp.status_code == 401 and attempt == 0:
                invalidate_credentials()
                continue
            if resp.status_code in (429, 500, 503, 529):
                time.sleep(min(60.0, (2**attempt) * 0.5))
                continue
            resp.raise_for_status()
            data = resp.json()
            text = "".join(b.get("text", "") for b in data.get("content", []))
            usage = data.get("usage", {})
            return text.strip(), int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
        except Exception as exc:  # noqa: BLE001
            last = exc
            if _is_throttle(exc):
                time.sleep(min(60.0, (2**attempt) * 0.5))
                continue
            raise
    assert last is not None
    raise last


def _call(model: str, system: str, user: str, opts: dict) -> tuple[str, int, int]:
    if model.startswith("claude"):
        return _call_claude(model, system, user, opts)
    last: Exception | None = None
    for attempt in range(8):
        try:
            cfg_kwargs = {
                "system_instruction": system,
                "temperature": opts.get("temperature", 0.0),
                "max_output_tokens": opts.get("max_output_tokens", 512),
            }
            if opts.get("json_mime", True):
                cfg_kwargs["response_mime_type"] = "application/json"
            cfg = types.GenerateContentConfig(**cfg_kwargs)
            try:
                cfg.thinking_config = types.ThinkingConfig(
                    thinking_budget=opts.get("thinking_budget", 0)
                )
            except Exception:
                pass
            resp = _client().models.generate_content(
                model=model, contents=user, config=cfg
            )
            usage = getattr(resp, "usage_metadata", None)
            return (
                (resp.text or "").strip(),
                int(getattr(usage, "prompt_token_count", 0) or 0),
                int(getattr(usage, "candidates_token_count", 0) or 0),
            )
        except Exception as exc:  # noqa: BLE001
            last = exc
            if _is_auth(exc) and attempt == 0:
                invalidate_credentials()
                _thread_local.client = None
                continue
            if _is_throttle(exc):
                time.sleep(min(60.0, (2**attempt) * 0.5))
                continue
            raise
    assert last is not None
    raise last


def _cost_usd(model: str, prompt_tok: int, output_tok: int) -> float:
    price = PRICES.get(model, PRICES["gemini-2.5-flash"])
    return prompt_tok / 1e6 * price["in"] + output_tok / 1e6 * price["out"]


def run_arm(
    arm: str, sample: pd.DataFrame, ctx: dict, model: str, workers: int
) -> dict:
    build = ARMS[arm]
    lock = threading.Lock()
    stats = {"prompt_tok": 0, "output_tok": 0, "ok": 0, "fail": 0, "done": 0}
    rows_out: list[dict] = []
    t0 = time.time()
    n = len(sample)

    def handle(item) -> dict:
        idx, row = item
        keys = list(row["human_answer"].keys())
        system, user, opts = build(row, ctx)
        if opts.get("pipeline"):
            def call(sys_p, usr_p, extra):
                return _call(model, sys_p, usr_p, {**extra})

            out_p = opts["pipeline"](call)
            merged_p, pt_p, ot_p = out_p[:3]
            diag_p = out_p[3] if len(out_p) > 3 else None
            if merged_p is None:
                return {"i": int(idx), "ok": False, "raw": "pipeline failed", "pt": pt_p, "ot": ot_p}
            return {
                **({"segments": diag_p} if diag_p else {}),
                "i": int(idx),
                "ok": True,
                "dataset_name": row["dataset_name"],
                "split": row["split"],
                "llm_answer": merged_p,
                "human_answer": dict(row["human_answer"]),
                "n_samples_ok": 1,
                "pt": pt_p,
                "ot": ot_p,
            }
        n_samples = opts.get("samples", 1)
        calls = opts.get("prompts") or [(system, user)] * n_samples
        dists, pt_sum, ot_sum = [], 0, 0
        raw_last = ""
        seg_detail = None
        for call_system, call_user in calls:
            raw, pt, ot = _call(model, call_system, call_user, opts)
            pt_sum += pt
            ot_sum += ot
            raw_last = raw
            seg_mode = opts.get("segments")
            if seg_mode == "soft":
                seg_detail = _segments_detail(raw, keys)
            dist = (
                _parse_segments(raw, keys, seg_mode == "soft")
                if seg_mode
                else _parse_dist(raw, keys)
            )
            if dist is not None:
                dists.append(dist)
        if not dists:
            return {
                "i": int(idx),
                "ok": False,
                "raw": raw_last[:200],
                "pt": pt_sum,
                "ot": ot_sum,
            }
        merged = {k: sum(d[k] for d in dists) / len(dists) for k in keys}
        if opts.get("prompts") and len(dists) > 1:
            seg_detail = [{"share": 1.0, "dist": d} for d in dists]
        return {
            **({"segments": seg_detail} if seg_detail else {}),
            "i": int(idx),
            "ok": True,
            "dataset_name": row["dataset_name"],
            "split": row["split"],
            "llm_answer": merged,
            "human_answer": dict(row["human_answer"]),
            "n_samples_ok": len(dists),
            "pt": pt_sum,
            "ot": ot_sum,
        }

    print(f"[{arm}] n={n} workers={workers}")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(handle, item) for item in sample.iterrows()]
        for fut in as_completed(futures):
            try:
                result = fut.result()
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "error": str(exc)[:200], "pt": 0, "ot": 0}
            with lock:
                stats["prompt_tok"] += int(result.get("pt") or 0)
                stats["output_tok"] += int(result.get("ot") or 0)
                stats["done"] += 1
                stats["ok" if result.get("ok") else "fail"] += 1
                rows_out.append(result)
                if stats["done"] % 200 == 0 or stats["done"] == n:
                    cost = _cost_usd(model, stats["prompt_tok"], stats["output_tok"])
                    print(
                        f"[{arm}] {stats['done']}/{n} ok={stats['ok']} "
                        f"fail={stats['fail']} ~${cost:.3f}"
                    )

    rows_out.sort(key=lambda r: r.get("i", 10**9))
    return {
        "arm": arm,
        "model": model,
        "n": n,
        "ok": stats["ok"],
        "fail": stats["fail"],
        "prompt_tokens": stats["prompt_tok"],
        "output_tokens": stats["output_tok"],
        "estimated_cost_usd": round(
            _cost_usd(model, stats["prompt_tok"], stats["output_tok"]), 4
        ),
        "elapsed_s": round(time.time() - t0, 1),
        "rows": rows_out,
    }


# --------------------------------------------------------------------------- #
# scoring (official formula)
# --------------------------------------------------------------------------- #


def _norm(dist: dict) -> dict:
    total = sum(dist.values()) or 1.0
    return {k: v / total for k, v in dist.items()}


def tvd(p: dict, q: dict) -> float:
    keys = set(p) | set(q)
    return 0.5 * sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in keys)


def dataset_norms(sample: pd.DataFrame) -> dict[str, float]:
    """mean_j TVD(human_j, uniform_j) per dataset -- the official denominator."""
    acc = defaultdict(list)
    for _, row in sample.iterrows():
        human = _norm(row["human_answer"])
        uniform = {k: 1.0 / len(human) for k in human}
        acc[row["dataset_name"]].append(tvd(human, uniform))
    return {ds: sum(vals) / len(vals) for ds, vals in acc.items()}


def score_arm(
    result: dict, norms: dict[str, float], shrink: float = 0.0
) -> dict:
    """SimBench S; shrink>0 interpolates the prediction toward uniform."""
    per_split = defaultdict(list)
    per_dataset = defaultdict(list)
    all_scores, tvds = [], []
    for row in result["rows"]:
        if not row.get("ok"):
            continue
        ds = row["dataset_name"]
        norm = norms.get(ds)
        if not norm:
            continue
        human = _norm(row["human_answer"])
        pred = _norm(row["llm_answer"])
        if shrink:
            k = len(pred)
            pred = {
                key: (1 - shrink) * val + shrink / k for key, val in pred.items()
            }
        distance = tvd(human, pred)
        score = 100 * (1 - distance / norm)
        all_scores.append(score)
        tvds.append(distance)
        per_split[row.get("split", "?")].append(score)
        per_dataset[ds].append(score)

    def mean(values):
        return round(sum(values) / len(values), 2) if values else None

    return {
        "arm": result["arm"],
        "n_scored": len(all_scores),
        "S": mean(all_scores),
        "mean_TVD": round(sum(tvds) / len(tvds), 4) if tvds else None,
        "S_by_split": {k: mean(v) for k, v in sorted(per_split.items())},
        "S_by_dataset": {k: mean(v) for k, v in sorted(per_dataset.items())},
        "cost_usd": result.get("estimated_cost_usd"),
        "fail": result.get("fail"),
    }


# --------------------------------------------------------------------------- #
# cli
# --------------------------------------------------------------------------- #


def extended_pool(df: pd.DataFrame, per_dataset: int, seed: int, reserve: int, n_ext: int) -> pd.DataFrame:
    """Extra demo candidates drawn from rows outside the eval slice and reserve."""
    out = []
    for _, group in df.groupby("dataset_name"):
        shuffled = group.sample(frac=1.0, random_state=seed)
        out.append(shuffled.iloc[reserve + per_dataset : reserve + per_dataset + n_ext])
    return pd.concat(out).reset_index(drop=True)


def build_context(pop: pd.DataFrame, grouped: pd.DataFrame, pools: pd.DataFrame) -> dict:
    personas_by_dataset = defaultdict(set)
    for df in (pop, grouped):
        for _, row in df.iterrows():
            personas_by_dataset[row["dataset_name"]].add(_filled_persona(row))
    demos_by_dataset = defaultdict(list)
    if len(pools):
        for _, row in pools.iterrows():
            bucket = demos_by_dataset[row["dataset_name"]]
            if len(bucket) < 3:
                bucket.append(
                    {
                        "input_template": row["input_template"],
                        "human_answer": row["human_answer"],
                    }
                )
    return {
        "personas_by_dataset": {k: sorted(v) for k, v in personas_by_dataset.items()},
        "demos_by_dataset": dict(demos_by_dataset),
    }


DEV_POP, DEV_GROUPED = 10, 40  # cases per dataset in the held-out tuning set


def _demo_entry(row) -> dict:
    return {
        "input_template": row["input_template"],
        "human_answer": row["human_answer"],
        "h": _entropy(row["human_answer"]),
        "persona": _filled_persona(row),
    }


def _stepc_cells(grouped: pd.DataFrame, seed: int, n_groups: int = 150) -> pd.DataFrame:
    """Subgroup cells of divided questions (shared surveys) for the common-mode test:
    every single-attribute cell (>= 100 respondents) of up to n_groups question x country x
    attribute groups that have >= 3 cells and a divided size-weighted mixture."""
    keyed = defaultdict(list)
    for idx, r in grouped.iterrows():
        vm = r["group_prompt_variable_map"]
        other = [k for k in vm if k not in ("country", "cntry")]
        if len(other) == 1 and r["group_size"] >= 100 and len(r["human_answer"]) > 1:
            ck = next((str(vm[k]) for k in ("country", "cntry") if k in vm), "")
            keyed[(r["dataset_name"], ck, r["input_template"], other[0])].append(idx)
    groups = []
    for key, idxs in keyed.items():
        if len(idxs) < 3:
            continue
        rows = grouped.loc[idxs]
        keys = list(rows.iloc[0]["human_answer"].keys())
        P = np.array([[ha.get(k, 0.0) for k in keys] for ha in rows["human_answer"]], float)
        P = P / P.sum(axis=1, keepdims=True)
        w = rows["group_size"].to_numpy(float)
        mix = (w / w.sum()) @ P
        q = mix[mix > 0]
        if len(keys) > 1 and -(q * np.log(q)).sum() / np.log(len(keys)) >= 0.84:
            groups.append(key)
    random.Random(seed).shuffle(groups)
    chosen = [i for key in sorted(groups[:n_groups]) for i in keyed[key]]
    return grouped.loc[chosen].reset_index(drop=True)


def build_env(pop_n: int, grouped_n: int, seed: int, which: str = "eval", limit: int = 0):
    """(sample, norms, ctx). which='dev' is a tuning set disjoint from the eval sample."""
    pop_full = load_split("Pop")
    grouped_full = load_split("Grouped")
    pop_eval, pop_pool = stratified_sample(pop_full, pop_n, seed, reserve=3)
    grp_eval, grp_pool = stratified_sample(grouped_full, grouped_n, seed, reserve=3)
    pools = pd.concat([pop_pool, grp_pool]).reset_index(drop=True)
    if which == "stepc":
        sample = _stepc_cells(grouped_full, seed)
    elif which == "dev":
        parts = []
        for df, n_eval, n_dev in ((pop_full, pop_n, DEV_POP), (grouped_full, grouped_n, DEV_GROUPED)):
            for _, g in df.groupby("dataset_name"):
                sh = g.sample(frac=1.0, random_state=seed)
                parts.append(sh.iloc[3 + n_eval : 3 + n_eval + n_dev])
        sample = pd.concat(parts)
        sample = sample[sample["human_answer"].map(len) > 1].reset_index(drop=True)
    elif which == "full":
        sample = pd.concat([pop_full, grouped_full])
        sample = sample[sample["human_answer"].map(len) > 1].reset_index(drop=True)
    else:
        sample = pd.concat([pop_eval, grp_eval]).reset_index(drop=True)
    if limit:
        sample = sample.sample(n=limit, random_state=1)
    norms = dataset_norms(sample)
    ctx = build_context(pop_full, grouped_full, pools)
    ext: dict[str, list[dict]] = defaultdict(list)
    for df_full, per in ((pop_full, pop_n), (grouped_full, grouped_n)):
        n_ext = 40 if df_full is pop_full else 10**6
        for _, row in extended_pool(df_full, per, seed, 3, n_ext).iterrows():
            ext[f"{row['split']}|{row['dataset_name']}"].append(_demo_entry(row))
    # datasets with no spare rows fall back to the 3 reserve demos
    for pool_df in (pop_pool, grp_pool):
        for _, row in pool_df.iterrows():
            key = f"{row['split']}|{row['dataset_name']}"
            if len(ext[key]) < 6:
                ext[key].append(_demo_entry(row))
    ctx["ext_by_dataset"] = dict(ext)
    ctx["comp_index"] = _composition_index(grouped_full)
    return sample, norms, ctx



def build_archetypes(sample: pd.DataFrame, model: str, workers: int = 16) -> dict[str, list[str]]:
    """Five archetypes per distinct group persona, generated once and cached on disk."""
    path = OUT_DIR / f"archetypes_{model.replace('/', '_')}.json"
    cache = json.loads(path.read_text()) if path.exists() else {}
    personas = sorted({_filled_persona(r) for _, r in sample.iterrows()} - set(cache))
    if personas:
        print(f"[archetypes] generating for {len(personas)} personas")

        def gen(persona: str):
            user = (
                f"Here is a group of survey respondents:\n{persona}\n\n"
                "List 5 distinct archetypes of people within this group: types that would tend "
                "to answer survey questions differently from each other (differing values, "
                "knowledge, and response style such as engaged versus indifferent). Give each a "
                'short name and a one-sentence description. Output only valid JSON: '
                '{"archetypes": [{"name": "...", "description": "..."}, ...]}'
            )
            for _ in range(3):
                raw, _, _ = _call(model, "You are a careful survey researcher.", user, {"max_output_tokens": 700})
                try:
                    items = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])["archetypes"]
                    out = [f"{i['name']}: {i['description']}" for i in items][:5]
                    if len(out) >= 3:
                        return persona, out
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
            return persona, []

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for persona, out in pool.map(gen, personas):
                cache[persona] = out
        path.write_text(json.dumps(cache, indent=1))
    return cache


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--arms", default="base")
    p.add_argument("--model", default=MODEL)
    p.add_argument("--pop", type=int, default=25, help="cases per Pop dataset")
    p.add_argument("--grouped", type=int, default=100, help="cases per Grouped dataset")
    p.add_argument("--workers", type=int, default=64)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--score-only", action="store_true")
    p.add_argument("--limit", type=int, default=0, help="smoke test: random N cases, separate cache")
    p.add_argument("--shrink-sweep", action="store_true")
    p.add_argument("--set", default="eval", choices=["eval", "dev", "stepc", "full"], help="dev = held-out tuning set")
    args = p.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    sample, norms, ctx = build_env(args.pop, args.grouped, args.seed, args.set, args.limit)
    pop_eval = sample[sample["split"] == "Pop"]
    grp_eval = sample[sample["split"] == "Grouped"]

    print(
        f"sample n={len(sample)} "
        f"(Pop {len(pop_eval)} / Grouped {len(grp_eval)}) "
        f"datasets={len(norms)}"
    )
    if not args.limit and args.set == "eval":
        (OUT_DIR / "dataset_norms.json").write_text(json.dumps(norms, indent=2))

    arms = [a for a in args.arms.split(",") if a]
    if any(a.startswith(("B_dict", "B_agents", "Bdiag_agents")) for a in arms):
        ctx["archetypes"] = build_archetypes(sample, args.model, min(args.workers, 24))
    if any(a.startswith("D") and a[1:2].isdigit() for a in arms):
        pop_full_d, grouped_full_d = load_split("Pop"), load_split("Grouped")
        ctx["dpool"] = _build_dpool(pop_full_d, grouped_full_d, args.pop, args.grouped, args.seed)
        ctx["_grouped_by_q"] = _index_grouped_by_question(grouped_full_d)
        ctx["_target_stems"] = [(r["dataset_name"], _stem(r["input_template"])) for _, r in sample.iterrows()]
    if "retr6_shape" in arms:
        tag0 = f"p{args.pop}g{args.grouped}s{args.seed}" + (
            f"dev{DEV_POP}x{DEV_GROUPED}" if args.set == "dev" else ""
        )
        base_path = OUT_DIR / f"base_{args.model.replace('/', '_')}_{tag0}.json"
        ctx["first_pass"] = {
            r["i"]: sorted(r["llm_answer"].values(), reverse=True)
            for r in json.loads(base_path.read_text())["rows"]
            if r.get("ok")
        }
    summaries = []
    for arm in arms:
        if arm not in ARMS:
            raise SystemExit(f"unknown arm {arm}; choose from {sorted(ARMS)}")
        tag = f"p{args.pop}g{args.grouped}s{args.seed}" + (f"lim{args.limit}" if args.limit else "") + ({"dev": f"dev{DEV_POP}x{DEV_GROUPED}", "stepc": "stepc", "full": "full"}.get(args.set, ""))
        raw_path = OUT_DIR / f"{arm}_{args.model.replace('/', '_')}_{tag}.json"
        if args.score_only or raw_path.exists():
            if not raw_path.exists():
                print(f"[{arm}] no cached run, skipping")
                continue
            result = json.loads(raw_path.read_text())
            print(f"[{arm}] loaded cached run ({raw_path.name})")
        else:
            result = run_arm(arm, sample, ctx, args.model, args.workers)
            raw_path.write_text(json.dumps(result, indent=2))
        summary = score_arm(result, norms)
        if args.shrink_sweep:
            sweep = {
                f"{lam:.2f}": score_arm(result, norms, shrink=lam)["S"]
                for lam in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5)
            }
            summary["shrink_sweep_S"] = sweep
        summaries.append(summary)
        print(json.dumps({k: v for k, v in summary.items() if k != "S_by_dataset"}, indent=2))

    if summaries:
        if not args.limit and args.set == "eval":
            (OUT_DIR / "summary.json").write_text(json.dumps(summaries, indent=2))
        base = next((s for s in summaries if s["arm"] == "base"), None)
        print("\n=== SimBench S by arm ===")
        for s in sorted(summaries, key=lambda x: -(x["S"] or -999)):
            delta = (
                f"  ({s['S'] - base['S']:+.2f} vs base)"
                if base and s["S"] is not None and base["S"] is not None
                else ""
            )
            print(f"{s['arm']:<14} S={s['S']:<7} TVD={s['mean_TVD']:<7} n={s['n_scored']}{delta}")


if __name__ == "__main__":
    main()
