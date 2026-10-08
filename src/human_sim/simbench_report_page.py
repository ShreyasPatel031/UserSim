"""Builds docs/simbench_strategy_map.html from the full-benchmark components (no model calls).

Reads results/simbench_ablate/{fullrule_components,tuned_predictions,newsources_full,cogmodels_report}.pkl|json and fills
docs/simbench_strategy_map.template.html. Every number on the page is computed here or copied from a named report; the
examples are chosen by rule (median-gain question of a bracket, or the single worst regression)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from human_sim import simbench_ablate as A
from human_sim import simbench_mass_levers as M
from human_sim import simbench_tune as T

DOCS = Path(__file__).resolve().parents[2] / "docs"

SRC = {
    "decomposition": ("Two-way decomposition", "Shared surveys. The same question answered by other countries and by non-overlapping groups, plus how the target group usually differs from average."),
    "other countries, identical question": ("Other countries, same question", "Single-country datasets (TISP, GlobalOpinionQA, OSPsych, ConspiracyCorr, MoralMachine). Other countries' answers to the identical question plus this country's usual offset."),
    "country-level decomposition + model": ("Country level + model", "Whole-country question with no sibling groups. Other countries' answer plus the country's offset on related questions, blended with the model."),
    "same-group-abroad decomposition + model": ("Same group abroad + model", "Subgroup with no disjoint group at home. The same group in other countries plus its offset on related questions, blended with the model."),
    "plain (no decomposition)": ("Model, calibrated", "Sharp questions with no evidence to borrow. The model's answer with a per-dataset exponent and calibration."),
    "plain + label prior (no decomposition)": ("Model + answer-label base rates", "Shallow questions with no evidence to borrow. The model's answer mixed with base rates of the same answer labels from other questions."),
    "plain (other datasets)": ("Model, calibrated (other datasets)", "ChaosNLI, DICES, Jester, WisdomOfCrowds and others. The model's answer with per-dataset calibration and, for ChaosNLI, text cues."),
    "cognitive model (Choices13k)": ("Gamble model", "Prospect-theory features of the two gambles in a cross-fitted logistic model, blended with boosted trees."),
    "cognitive model (NumberGame)": ("Number-game model", "Bayesian size-principle concept learning plus ratings of other targets shown with the same numbers."),
    "cognitive model (MoralMachine)": ("Moral scenario model", "Counts of each character type that dies under each option, in a cross-fitted logistic model."),
}

STEPS = [
    ("Plain model", "Haiku 4.5 with retrieval of similar solved questions", 41.46, "start"),
    ("Two-way decomposition", "Other groups and countries, shared surveys", 50.15, "new"),
    ("Other-country answers", "Single-country datasets (TISP, OSPsych, GlobalOpinionQA...)", 52.69, "new"),
    ("Base rates and cognitive models", "Answer-label prior; prospect theory; Bayesian number game", 57.57, "new"),
    ("Country total and same group abroad", "Decomposition for rows with no sibling groups", 58.29, "new"),
    ("Moral scenario model", "Also: no within-country gap in OpinionQA", 60.01, "new"),
    ("Label-prior leak fix", "Prior no longer sees the same question from overlapping groups", 59.89, "fix"),
    ("Round 1", "Same group abroad, country level, GlobalOpinionQA, TISP", 60.30, "tune"),
    ("Round 2", "Boosted gamble model, Jester, DICES, per-dataset calibration", 61.36, "tune"),
    ("Round 3", "Decomposition exponent and weight, per survey", 61.62, "tune"),
    ("Round 4", "Country offsets for single-country sets, richer gamble and number features", 62.16, "tune"),
    ("Round 5", "Answer-position correction", 62.27, "tune"),
    ("Round 6", "Offsets from same-scale related questions", 62.32, "tune"),
    ("Round 7", "ChaosNLI text cues", 62.40, "tune"),
    ("Round 8", "Number game: rule versus interval generalization", 62.49, "tune"),
]

WEAK = [
    ("LatinoBarometro · same group abroad", 414, "35.6", "Only 14 distinct questions. The best single other country, chosen with hindsight, reaches 46.6. El Salvador alone scores −20.7 because it answers unlike its neighbors, and the strongest evidence, other El Salvador subgroups, is excluded by the overlap rule."),
    ("ESS · answer-label base rates", 110, "36.3", "42 questions were never asked in another country. For the other 68, a plain average of other countries scores 28.9 against 35.7 before the leak fix; the best group abroad would reach 74.5, but only with hindsight."),
    ("ISSP · same group abroad", 185, "38.0", "The best of five offset variants gained +1.4 with an interval touching zero (0.0 to 2.9), so it was not kept."),
    ("GlobalOpinionQA · model", 418, "42.2", "Each question was asked in about three countries. Averages over the ten most similar questions scored 29.0 against the model's 45.2 on the 341 questions they covered."),
    ("ISSP · answer-label base rates", 479, "43.5", "Base rates and position corrections each moved it by less than 1 point, below the keep bar."),
    ("Choices13k · gamble model", 500, "45.5", "Rose from 39.2 over four rounds. Probability weighting variants and context effects between the two gambles are untested."),
]


def tvd(a, b):
    return 0.5 * float(np.abs(np.asarray(a) - np.asarray(b)).sum())


def build():
    comps = pd.read_pickle(T.COMP)
    tuned = pd.read_pickle(T.TUNED)
    ns = pd.read_pickle(M.OUT / "newsources_full.pkl")
    N = len(comps)
    cur = lambda c: tuned.get(c["qid"], c["final"])  # noqa: E731
    df = pd.DataFrame([dict(ds=c["dataset"], src=c["source"], split=c["split"], top=float(c["h"].max()), plain=T.S(c, c["plain"]), tuned=T.S(c, cur(c))) for c in comps])
    df["g"] = df.tuned - df.plain

    byds = df.groupby("ds").agg(n=("plain", "size"), plain=("plain", "mean"), tuned=("tuned", "mean")).sort_values("n", ascending=False).reset_index()
    rule = pd.DataFrame([dict(src=c["source"], rule=T.S(c, c["final"])) for c in comps])
    bs = df.groupby("src").agg(n=("plain", "size"), plain=("plain", "mean"), tuned=("tuned", "mean"), win=("g", lambda x: (x > 0).mean()), harm10=("g", lambda x: (x < -10).mean()))
    bs["rule"] = rule.groupby("src").rule.mean()
    bs["pts_rule"] = (bs.rule - bs.plain) * bs.n / N
    bs["pts_tune"] = (bs.tuned - bs.rule) * bs.n / N
    bs = bs.sort_values("pts_rule", ascending=False).reset_index()

    df["bin"] = pd.cut(df.top, [0, 0.4, 0.55, 0.7, 0.85, 1.01], labels=["<40%", "40–55%", "55–70%", "70–85%", ">85%"])
    bins = df.groupby("bin", observed=True).agg(n=("g", "size"), plain=("plain", "mean"), tuned=("tuned", "mean")).reset_index()
    bins["bin"] = bins.bin.astype(str)

    rows = []
    for c in comps:
        tool = next(((k, c[k]) for k in ("dd3", "dd2", "xd", "others") if c.get(k) is not None), None)
        if tool is None:
            continue
        rows.append(dict(src=c["source"], dis=tvd(T.norm(c["plain"]), T.norm(tool[1])), Sp=T.S(c, c["plain"]), St=T.S(c, tool[1]), Sf=T.S(c, cur(c))))
    dd = pd.DataFrame(rows)
    dd["bin"] = pd.qcut(dd.dis, 4, labels=["agree most", "agree", "disagree", "disagree most"])
    dis = dd.groupby("bin", observed=True).agg(n=("Sp", "size"), dis=("dis", "mean"), plain=("Sp", "mean"), tool=("St", "mean"), final=("Sf", "mean")).reset_index()
    dis["bin"] = dis.bin.astype(str)
    sga = dd[dd.src == "same-group-abroad decomposition + model"]
    hi = sga[sga.dis >= sga.dis.median()]

    sample, _, _ = A.build_env(25, 100, 7, "full")
    M.EVAL_ARMS = M.DEV_ARMS = {"plain": ("retr6_rev2", M.HAIKU)}
    Q = {q["qid"]: q for q in M.load("full")}
    gain = lambda c: T.S(c, cur(c)) - T.S(c, c["plain"])  # noqa: E731

    def pick(cs, how):
        cs = sorted(cs, key=lambda c: (gain(c), c["qid"]))
        return cs[len(cs) // 2] if how == "median" else cs[0]

    def card(c, label, tool_key, tool_name, note):
        q = Q[c["qid"]]
        r = sample.loc[q["i"]]
        tool = c.get(tool_key) if c.get(tool_key) is not None else ns.get(c["qid"], {}).get(tool_key)
        v = lambda x: [round(float(t), 4) for t in T.norm(x)]  # noqa: E731
        real, plain, final, tl = [round(float(t), 4) for t in c["h"]], v(c["plain"]), v(cur(c)), v(tool)
        facts = [note,
                 f"Distance to the real answer (TVD): model {tvd(real, plain):.2f}, {tool_name.lower()} {tvd(real, tl):.2f}, final {tvd(real, final):.2f}.",
                 f"Model and {tool_name.lower()} disagree by {tvd(plain, tl):.2f} TVD."]
        return dict(label=label, group=dict(r.group_prompt_variable_map), question=r.input_template.split("Options:")[0].strip()[-400:], options=[q["texts"].get(k, k) for k in c["keys"]],
                    real=real, plain=plain, tool=tl, final=final, S_plain=round(T.S(c, c["plain"]), 1), S_final=round(T.S(c, cur(c)), 1), facts=facts)

    ex = [
        card(pick([c for c in comps if c["source"] == "decomposition" and c["dataset"] == "ESS" and c.get("dd3") is not None], "median"),
             "Median gain · ESS · two-way decomposition", "dd3", "Decomposition", "Evidence: the same question in other countries, shifted by how this age band differs from average."),
        card(pick([c for c in comps if c["source"] == "other countries, identical question" and c["dataset"] == "TISP" and ns.get(c["qid"], {}).get("others_dd") is not None], "median"),
             "Median gain · TISP · other countries plus offset", "others_dd", "Offset tool", "Evidence: other countries' answers to the identical question, then this country's usual gap on related questions."),
        card(pick([c for c in comps if c["source"] == "cognitive model (Choices13k)"], "median"),
             "Median gain · Choices13k · gamble model", "c13_v2", "Gamble model", "Evidence: payoffs and probabilities of the two machines. Machine A pays $26 for sure; Machine B is a 75/25 gamble."),
        card(pick([c for c in comps if c["source"] == "same-group-abroad decomposition + model" and c["dataset"] == "LatinoBarometro"], "worst"),
             "Worst regression · LatinoBarometro · same group abroad", "xd", "Same-group tool", "Evidence: the same age band in other countries, plus its offset. It was far from the real answer, and the model had been close."),
    ]
    ex[3]["facts"].append(f"Across this source's high-disagreement half the model scores {hi.Sp.mean():.1f}, the evidence alone {hi.St.mean():.1f} and the final {hi.Sf.mean():.1f}, so this is a source where the blend, not either part, carries the score.")

    rep = json.loads((M.OUT / "cogmodels_report.json").read_text())
    names = ["expected-value gap", "scaled expected-value gap", "payoff spread gap", "chance-of-loss gap", "prospect-theory value gap", "certainty gap", "worst-outcome gap", "best-outcome gap"]
    coef = rep["Choices13k"]["coef"]
    topf = [names[i] for i in np.argsort(-np.abs(coef))[:2]]

    signals = [
        ("Which source served each question", "Ten sources serve the 13,510 questions. The gamble, number-game and moral models and same-group-abroad each score 10+ points below the plain model on 20–25% of their questions; two-way decomposition does so on 6%.", "Gate or replace the risky sources one bracket at a time, as the tuning rounds did, and spend the next effort where the loss rate is highest."),
        ("Model–evidence disagreement", f"Across {int(dis.n.sum()):,} questions with an evidence source, the model scores {dis.plain.iloc[0]:.1f} where the two agree most and {dis.plain.iloc[-1]:.1f} where they disagree most. The evidence alone holds at {dis.tool.iloc[0]:.1f} and {dis.tool.iloc[-1]:.1f}.", "Route by disagreement per source, tested out of sample, and send only the high-disagreement questions to a stronger model run."),
        ("Segments with named members", "Botswana job-seekers on internet use: three clusters, the rural one (37% of respondents) predicts 79% never online, the city one 37% every day. Real answer for the target group: 49% never.", "Check whether clusters line up with real attributes, then use segment membership to pick persona text or retrieved examples."),
        ("Country and group offsets", "One Afrobarometer record lists the country's gap to other countries on related questions: −7 points on one option, −6 on another, mean −6.", "Learn offsets per question family, flag countries whose offsets swing between related questions, and pass stable ones into the prompt."),
        ("Hindsight bounds", "LatinoBarometro same-group-abroad: the best single other country reaches 46.6 against 36.2 for our prediction (before the leak fix), and El Salvador's best is −1.9 even with that choice.", "Know when to stop tuning. Past a bound, only new data or a changed rule can move the bracket."),
        ("Readable model weights", f"The Choices13k logistic model puts its largest weights on the {topf[0]} and the {topf[1]}.", "Add the feature humans plausibly use next (probability weighting, regret between gambles) and read whether its weight moves.")]

    data = dict(
        N=N, plain=float(df.plain.mean()), tuned=float(df.tuned.mean()),
        split={"Pop": int((df.split == "Pop").sum()), "Grouped": int((df.split == "Grouped").sum())},
        byds=byds.to_dict("records"), bysrc=bs.to_dict("records"),
        srcinfo={k: {"name": v[0], "evidence": v[1]} for k, v in SRC.items()},
        steps=[dict(name=n, detail=d, score=s, kind=k) for n, d, s, k in STEPS],
        bins=bins.to_dict("records"), dis=dis.to_dict("records"),
        weak=[dict(name=a, n=b, score=c, why=d) for a, b, c, d in WEAK], examples=ex, signals=signals)
    assert abs(STEPS[-1][2] - data["tuned"]) < 0.01, "step list is out of date"
    tpl = (DOCS / "simbench_strategy_map.template.html").read_text()
    (DOCS / "simbench_strategy_map.html").write_text(tpl.replace("__DATA__", json.dumps(data, default=float)))
    print("wrote", DOCS / "simbench_strategy_map.html", f"{len(tpl) / 1e3:.0f} KB template, full {data['tuned']:.2f}")


if __name__ == "__main__":
    build()
