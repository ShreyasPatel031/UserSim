"""SimBench with UserSim population data: does GSS evidence improve group-level answer distributions over the base model?

Arms (registered into simbench_ablate.ARMS so prompts, model calls and scoring are identical to the existing base arm):
  pop_rag      base prompt + the 5 most similar GSS items with their overall US answer distributions (naive RAG)
  pop_harness  base prompt + similar GSS items (similarity >= 0.60) shown as US overall vs. this group's distribution,
               a sketch of how this group differs from the average US adult, and the spread instruction
Repository: GSS only. OpinionQA items are excluded because SimBench's own OpinionQA rows are in our repository.
Evidence is added only when the target population is the US or unstated; other countries get the base prompt.

Usage: python -m human_sim.simbench_pop            # runs both arms on the standard eval sample (p25 g100 seed 7)
       python -m human_sim.simbench_pop score      # paired comparison against the base arm
"""

from __future__ import annotations

import json
import sys

import numpy as np

from human_sim import mega_pipeline as M
from human_sim import people_repo as PR
from human_sim import simbench_ablate as A

US = {"", "united states", "usa", "us", "u.s.", "america", "the united states"}
_gss = None


def gss_index():
    global _gss
    if _gss is None:
        items, E = M.index()
        keep = [i for i, it in enumerate(items) if it["source"] == "GSS"]
        _gss = ([items[i] for i in keep], E[keep])
    return _gss


def question(row):
    return str(row["input_template"]).split("\n\nOptions:")[0].strip()[:400]


def group_profile(row):
    vm = row["group_prompt_variable_map"] if isinstance(row["group_prompt_variable_map"], dict) else {}
    prof = {}
    for k, v in vm.items():
        if k in PR.SB_KEY:
            prof[PR.SB_KEY[k]] = PR.SB_VAL.get(str(v), str(v))
    return prof


def applicable(row):
    vm = row["group_prompt_variable_map"] if isinstance(row["group_prompt_variable_map"], dict) else {}
    return A._country_of(vm).strip().lower() in US


def retrieve(row, k=5):
    items, E = gss_index()
    q = M.embed([question(row)])[0]
    q = q / np.linalg.norm(q)
    s = E @ q
    top = np.argsort(-s)[:k]
    return [(items[j], float(s[j])) for j in top]


def arm_pop_rag(row, ctx):
    system, user, kw = A.arm_base(row, ctx)
    if not applicable(row):
        return system, user, kw
    lines = ["Public survey data from US adults (General Social Survey) that may be relevant:"]
    for it, _ in retrieve(row):
        lines.append(f"- \"{it['text']}\": {M.fmt_dist(it['options'], it['overall'])}")
    return system, "\n".join(lines) + "\n\n" + user, kw


def arm_pop_harness(row, ctx):
    system, user, kw = A.arm_base(row, ctx)
    if not applicable(row):
        return system, user, kw
    prof = group_profile(row)
    lines = ["What US survey data (General Social Survey) says about related questions — all US adults vs. this group:"]
    n = 0
    for it, s in retrieve(row):
        if s < M.SIM_MIN:
            continue
        p, used = PR.conditional(it, prof)
        if p is None:
            continue
        n += 1
        grp = f"\n    this group ({', '.join(used)}): {M.fmt_dist(it['options'], p)}" if used else ""
        lines.append(f"- \"{it['text']}\"\n    all US adults: {M.fmt_dist(it['options'], it['overall'])}{grp}")
    if prof:
        sk = M.sketch(prof)
        if sk:
            lines.append("How this group differs from the average US adult:")
            lines += sk
    if n == 0 and not prof:
        return system, user, kw
    lines.append("Use this as evidence about how this group answers. Groups are not uniform: keep the real spread of answers, "
                 "including minority and strong answers, rather than putting everything on the most common option.")
    return system, "\n".join(lines) + "\n\n" + user, kw


A.ARMS["pop_rag"] = arm_pop_rag
A.ARMS["pop_harness"] = arm_pop_harness


def score():
    """Paired S per row: base vs pop_rag vs pop_harness, overall, US-applicable rows, and by dataset."""
    from human_sim import simbench_ablate as A_
    sample, _, _ = A_.build_env(25, 100, 7)
    files = {a: A_.OUT_DIR / f"{a}_gemini-2.5-flash_p25g100s7.json" for a in ("base", "pop_rag", "pop_harness")}
    preds = {a: {r["i"]: r for r in json.loads(f.read_text())["rows"] if r.get("ok")} for a, f in files.items()}
    common = set.intersection(*[set(p) for p in preds.values()])
    rows = []
    for i in sorted(common):
        row = sample.iloc[i]
        ha = row["human_answer"]
        keys = list(ha)
        h = np.array([ha[k] for k in keys], float)
        h /= h.sum()
        u = np.full(len(keys), 1 / len(keys))
        rec = {"i": i, "ds": row["dataset_name"], "us": applicable(row), "tvd_u": 0.5 * np.abs(h - u).sum()}
        for a in preds:
            g = np.array([float(preds[a][i]["llm_answer"].get(k, 0)) for k in keys])
            g = g / g.sum() if g.sum() > 0 else u
            rec[a] = 0.5 * np.abs(h - g).sum()
        rows.append(rec)
    import pandas as pd
    d = pd.DataFrame(rows)

    def S(df, a):  # same convention as SimBench: 100 * (1 - mean TVD / mean TVD of uniform), per dataset then averaged
        out = []
        for _, g in df.groupby("ds"):
            out.append(100 * (1 - g[a].mean() / g.tvd_u.mean()))
        return float(np.mean(out))

    rng = np.random.default_rng(0)

    def boot(df, a, b):
        diffs = []
        for _ in range(1000):
            s = df.sample(len(df), replace=True, random_state=int(rng.integers(1e9)))
            diffs.append(S(s, a) - S(s, b))
        return [round(float(S(df, a) - S(df, b)), 2), round(float(np.percentile(diffs, 2.5)), 2), round(float(np.percentile(diffs, 97.5)), 2)]
    res = {}
    for name, df in (("all_rows", d), ("us_applicable_rows", d[d.us])):
        res[name] = {"rows": int(len(df)), **{a: round(S(df, a), 2) for a in preds},
                     "rag_minus_base": boot(df, "pop_rag", "base"), "harness_minus_base": boot(df, "pop_harness", "base"),
                     "harness_minus_rag": boot(df, "pop_harness", "pop_rag")}
    res["by_dataset_us"] = {ds: {a: round(100 * (1 - g[a].mean() / g.tvd_u.mean()), 1) for a in preds} | {"rows": int(len(g))}
                            for ds, g in d[d.us].groupby("ds")}
    out = M.ROOT / "results" / "simbench_pop.json"
    out.write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "score":
        score()
    else:
        sys.argv = [sys.argv[0], "--arms", "pop_rag,pop_harness", "--model", "gemini-2.5-flash"]
        A.main()
