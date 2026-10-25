"""Turn out/metrics.json into out/report.md (tables for recall@k, sources, factors, product types, current lists).

    python experiments/ph_predict/report.py
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"
CELLS = [f"{p}@{k}" for p in ("day", "week", "month") for k in (3, 5, 10)]


def cell(r: dict, key: str, with_random: bool = True) -> str:
    v = r.get(key)
    if not v:
        return "–"
    return f"{v['recall']:.2f} ({v['random']:.2f})" if with_random else f"{v['recall']:.2f}"


def table(rows: dict[str, dict], keys: list[str], with_random: bool = False) -> list[str]:
    L = ["| | " + " | ".join(keys) + " |", "|---" * (len(keys) + 1) + "|"]
    for name, r in rows.items():
        L.append(f"| {name} | " + " | ".join(cell(r, k, with_random) for k in keys) + " |")
    return L


def main() -> None:
    m = json.loads((OUT / "metrics.json").read_text())
    L = ["# Product Hunt top-list prediction: backtest", "",
         f"{m['n_launches']} featured launches, {m['days'][0]} to {m['days'][1]}. Each test month is predicted by a "
         f"model trained only on earlier months (test months: {', '.join(m['test_months'])}). No votes, comments or "
         "ranks of the launch itself are used as inputs.", "",
         "Recall@k = share of PH's actual top k that we put in our top k. In brackets: what random picking gets.", "",
         "Data coverage (share of launches with each signal): " + ", ".join(
             f"{k.replace('_', ' ')} {v:.0%}" for k, v in m.get("coverage", {}).items()) + ".", "",
         "## Overall lists", ""]
    L += table({"model (headline: no follower counts)": m["full"],
                "model + today's follower counts (may leak)": m["full_with_followers"]}, CELLS, with_random=True)
    L += ["", "95% confidence intervals (bootstrap over lists) and number of lists, headline model: " + "; ".join(
        f"{k} {v['ci95'][0]:.2f}-{v['ci95'][1]:.2f} (n={v['lists']})" for k, v in m["full"].items()) + ".", "",
          "Week and month results rest on few lists, so differences of a few points between rows below are noise.", "",
          f"Mean Spearman correlation with the daily order: {m['spearman_day']}", "",
          "Per test month (model trained on earlier months only; June's model only had March to learn from):", "",
          "| month | day@3 | day@5 | day@10 | week@5 | week@10 |", "|---|---|---|---|---|---|"]
    L += [f"| {mo} | " + " | ".join(f"{r.get(k, float('nan')):.2f}" for k in ("day@3", "day@5", "day@10", "week@5", "week@10"))
          + " |" for mo, r in m.get("by_month", {}).items()]
    L += ["", "## Baselines (no model)", ""]
    L += table(m["baselines"], CELLS)
    L += ["", "## Which sources predict: each source alone, and all sources minus one", ""]
    keys = ["day@5", "day@10", "week@10", "month@10"]
    L += ["Each source alone:", ""] + table(m["only"], keys)
    L += ["", "All sources minus one (a drop below the full model = that source adds information):", ""]
    L += table({"(full model)": m["full"], **{f"without {g}": r for g, r in m["without"].items()}}, keys)
    imp = m["importance"]
    L += ["", "## Which factors matter (mean |SHAP| on held-out launches)", "", "Share of the model's attribution by source:", "",
          "| source | share |", "|---|---|"] + [f"| {g} | {v:.0%} |" for g, v in imp["group_share"].items()]
    L += ["", "Top 20 features:", "", "| feature | mean |SHAP| |", "|---|---|"]
    L += [f"| {k} | {v:.4f} |" for k, v in list(imp["top_features"].items())[:20]]
    L += ["", "## How it changes by product type", "",
          "Each source alone, ranking one type's launches against each other within each week (week recall@5; "
          "random in brackets):", ""]
    obf = m["only_by_family"]
    srcs2 = list(m["only"].keys())
    L += ["| type | " + " | ".join(srcs2) + " |", "|---" * (len(srcs2) + 1) + "|"]
    for f, r in obf.items():
        rnd = next((v["random"] for v in r.values() if v), None)
        L.append(f"| {f} " + (f"(random {rnd:.2f}) " if rnd is not None else "") + "| " +
                 " | ".join(f"{r[g]['recall']:.2f}" if r.get(g) else "–" for g in srcs2) + " |")
    L += ["", "Factors that go with more votes inside the same week (Spearman, launches de-meaned by week):", ""]
    for f, r in m["factors_by_family"].items():
        L.append(f"- **{f}** (n={r['n']}): " + ", ".join(f"{k} {v:+.2f}" for k, v in list(r["top"].items())[:8]))
    L += ["", "SHAP share by source within each type (one shared model, so shares barely differ) "
          f"(launches per type: {imp['family_counts']}):", ""]
    fams = imp["group_share_by_family"]
    srcs = list(imp["group_share"].keys())
    L += ["| type | " + " | ".join(srcs) + " |", "|---" * (len(srcs) + 1) + "|"]
    L += [f"| {f} | " + " | ".join(f"{v.get(s, 0):.0%}" for s in srcs) + " |" for f, v in fams.items()]
    L += ["", "Top features per type:", ""]
    for f, feats in imp["top_features_by_family"].items():
        L.append(f"- **{f}**: " + ", ".join(list(feats)[:6]))
    L += ["", "## Topic lists (the model's score ranked inside each topic)", ""]
    L += table(m["topics"], ["day@3", "day@5", "week@5", "week@10", "month@10"], with_random=True)
    L += ["", "## The lists on PH's homepage now", ""]
    for label, r in m.get("current_lists", {}).items():
        L += [f"### {label.replace('_', ' ')} ({r['period']}, {r['n_launches']} launches)", "",
              f"recall@3 {r['recall@3']:.2f}, recall@5 {r['recall@5']:.2f}, recall@10 {r['recall@10']:.2f}", "",
              "| # | actual | predicted |", "|---|---|---|"]
        L += [f"| {i + 1} | {a} | {p} |" for i, (a, p) in enumerate(zip(r["actual_top10"], r["predicted_top10"]))]
        L.append("")
    (OUT / "report.md").write_text("\n".join(L) + "\n")
    print("\n".join(L[:30]))


if __name__ == "__main__":
    main()
