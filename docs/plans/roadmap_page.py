"""Build docs/roadmap.html from docs/plans/roadmap_2026-10.md (the source of truth) plus a stage timeline.

Usage: python docs/plans/roadmap_page.py   (needs markdown-it-py)
The HUMAINE ladder numbers are read from results/humaine/*.json so the page cannot drift from the results."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

from markdown_it import MarkdownIt

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MD = HERE / "roadmap_2026-10.md"
TPL = HERE / "roadmap.template.html"
OUT = ROOT / "docs" / "roadmap.html"

STAGES = [
    dict(key="free", tier="FREE", budget="$0 on data", when="Now",
         goal="Consistent, pre-registered, publishable results on four benchmarks before paying for any data.",
         items=["Harness core: registry, leakage guard, licence gate, three tracks, ledger",
                "HUMAINE zero-data re-run with four fixed changes (tie priors, arena blend, reasoning adjustment, segment offsets)",
                "Pilot curve as a product feature: how many of your users you need",
                "Zero-data intervals, reliability model, P2-Bench v0, Upworthy calibration, OPeRA audit, live Show HN ledger"],
         gate="Beats the plain model with CI above zero on 3+ benchmarks · pilot curves on 2 · interval coverage measured · one live round scored · one command per table"),
    dict(key="exp", tier="EXPERIMENTAL", budget="≈ $200 a month", when="After the FREE gate",
         goal="Find which paid data pays most per dollar, one pre-registered arm at a time.",
         items=["X1 pilot calibration on our own protocol (50-70 blind side-by-side sessions)",
                "X2 first-impression panel: ≈ 1,750 ratings of post-cutoff startup pages",
                "X3 task pair study every quarter (≈ 46 verified sessions)",
                "X4 segment shift: can one cheap segment calibrate another?"],
         gate="After 3 months: ΔS per $100 with CIs for every arm; graduate the best one or two"),
    dict(key="inc", tier="INCREMENTAL", budget="≈ $2,000 a month", when="Once a direction proves out",
         goal="Compounding: every study makes the next customer cheaper to predict.",
         items=["Linked panel: the same people through P1 profile, P2 first impression, P3 tasks, P4 choice",
                "P2 at scale (≈ 6,500 ratings a month) to train our own head; P3 benchmark of ≈ 5 pairs a month",
                "Randomised budget-planner trial; customer calibration ladder"],
         gate="Labels needed to reach a target S fall month over month"),
]


def ladder():
    sc = json.loads((ROOT / "results/humaine/scores.json").read_text())
    tr = json.loads((ROOT / "results/humaine/transfer.json").read_text())
    p4 = sc["p4"]
    steps = [
        ("Model alone", p4["gemini_plain"]["overall_winner"]["S"], "zero"),
        ("+ public ratings", p4["gemini_arena"]["overall_winner"]["S"], "zero"),
        ("+ 50-person pilot", tr["pilot_evidence"]["results"]["50"]["evidence"], "pilot"),
        ("+ 400-person pilot", tr["pilot_evidence"]["results"]["400"]["evidence"], "pilot"),
        ("In-dataset yardstick", p4["ref_bt_leave_pair_out"]["overall_winner"]["S"], "indata"),
    ]
    ceil = p4["gemini_plain"]["overall_winner"]["ceiling"]
    rows = "".join(
        f'<div class="lad-row"><span class="lad-name">{html.escape(n)}</span>'
        f'<span class="lad-track"><i class="lad-{k}" style="width:{v / 80 * 100:.1f}%"></i>'
        f'<span class="lad-ceil" style="left:{ceil / 80 * 100:.1f}%"></span></span>'
        f'<span class="lad-v">{v:.1f}</span></div>' for n, v, k in steps)
    return (f'<figure class="ladder"><figcaption>HUMAINE overall choice, S (0 = uniform guess; line = ceiling {ceil:.1f}). '
            f'Gemini 2.5 Flash; pilots are simulated from the target population and removed before scoring.</figcaption>{rows}</figure>')


def timeline():
    cols = []
    for s in STAGES:
        items = "".join(f"<li>{html.escape(i)}</li>" for i in s["items"])
        cols.append(f'<section class="stage st-{s["key"]}"><header><span class="tier">{s["tier"]}</span>'
                    f'<span class="budget">{html.escape(s["budget"])}</span><span class="when">{html.escape(s["when"])}</span></header>'
                    f'<p class="goal">{html.escape(s["goal"])}</p><ul>{items}</ul>'
                    f'<p class="gate"><b>Exit gate</b> {html.escape(s["gate"])}</p></section>')
    return '<div class="timeline">' + "".join(cols) + "</div>"


def build():
    src = MD.read_text()
    title_line, body = src.split("\n", 1)
    title = title_line.lstrip("# ").strip()
    paras = body.strip().split("\n\n")
    lede, rest = paras[0], "\n\n".join(paras[1:])
    md = MarkdownIt("commonmark").enable("table")
    h = md.render(rest)

    def wrap(m):
        t = m.group(0)
        wide = t.count("<th") >= 4
        return f'<div class="tw"><table class="{"wide" if wide else "narrow"}">' + t[len("<table>"):] + "</div>"
    h = re.sub(r"<table>.*?</table>", wrap, h, flags=re.S)
    h = re.sub(r'<a href="(https?://[^"]+)">', r'<a href="\1" target="_blank" rel="noopener">', h)
    h = re.sub(r"<h2>(\d+)\. ", r'<h2><span class="num">\1</span> ', h)
    # insert the visual blocks after the first section's heading block
    marker = '<h2><span class="num">2</span>'
    h = h.replace(marker, timeline() + ladder() + marker, 1)
    lede_html = md.render(lede)
    name, _, sub = title.partition(":")
    page = (TPL.read_text().replace("__TITLE__", html.escape(name.strip())).replace("__SUB__", html.escape(sub.strip()))
            .replace("__LEDE__", lede_html).replace("__BODY__", h))
    OUT.write_text(page)
    print("wrote", OUT, len(page), "bytes")


if __name__ == "__main__":
    build()
