"""Benchmark Fit Board: how well each candidate benchmark measures UserSim's four prediction targets.

Single source of truth for the scores. Running this file writes:
  docs/plans/eval/benchmarks.json   (the data)
  docs/benchmark_fit_board.html     (interactive board: weights, filters, ranking by stage)

Stage fit (0-3):  0 none, 1 weak proxy, 2 partial, 3 direct measurement of that target.
Quality (0-2):    0 absent, 1 partial, 2 strong.
"?" in `unverified` lists cells scored from papers or summaries that have not yet been checked against the data itself.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

STAGES = {
    "P1": "Population answer distributions: what real people (and which segments) say about a product or category",
    "P2": "Initial perception and preference on first exposure, before use, across product and competitors",
    "P3": "Task outcomes and preference after attempting given tasks on the product and competitors",
    "P4": "Overall choice: which product people pick (primary target; brand and network effects excluded)",
}

QUALITY = {
    "competing_alts": ("Competing alternatives", "People choose between real competing products or variants", 2),
    "brand_neutral": ("Brand-neutral", "Blind comparison, unknown makers, or variants of one brand", 2),
    "who_attrs": ("Who they are", "Person-level attributes with enough people per segment", 2),
    "startup_realism": ("Startup realism", "Products are digital products comparable to a startup's", 2),
    "no_contam": ("Not memorized", "A language model cannot already know the outcome", 1.5),
    "why": ("Reasons", "Multi-dimension ratings, rationales or free text", 1),
    "evaluable": ("Evaluable", "Held-out splits, sample size, measurable noise ceiling", 1),
    "license": ("Publishable", "Public and publishable licence or terms", 1),
    "mcp_arm": ("Fair MCP arm", "Non-target evidence exists that a tool-augmented model may use without leaking the answer", 1),
}

STATUS = {
    "available": "Available now: public download",
    "restricted": "Restricted: on request, data deal, or non-commercial terms",
    "proposed": "Proposed: needs a pipeline or new data collection",
}

B = [
    dict(name="HUMAINE", org="Prolific, 2026", status="available", url="https://huggingface.co/datasets/ProlificAI/humaine-evaluation-dataset",
         license="MIT", adapter=False,
         P={"P1": (1, "Rating distributions (goal achievement, engagement 1-5) by demographic group; not questionnaire answers"),
            "P2": (0, "No pre-use exposure is recorded"),
            "P3": (3, "People do their own tasks with two AI assistants; goal achievement scored per conversation, then they compare"),
            "P4": (3, "Overall winner between competing products, per person, with age, ethnicity, politics, country")},
         Q=dict(competing_alts=2, brand_neutral=1, who_attrs=2, startup_realism=1, no_contam=1, why=2, evaluable=2, license=2, mcp_arm=2),
         unverified=["brand_neutral: whether models were anonymous to participants"],
         note="23k+ people, 22 demographic groups, US/UK. Products are AI assistants, not startup apps; models' reputations are known to LLMs."),
    dict(name="PRISM", org="Kirk et al., NeurIPS 2024", status="available", url="https://huggingface.co/datasets/HannahRoseKirk/prism-alignment",
         license="CC (variant to verify)", adapter=False,
         P={"P1": (2, "Profile survey of 1,500 people (75 countries) with stated preferences about AI: category-level answer distributions by segment"),
            "P2": (3, "First-turn ratings of several models before choosing which to continue with"),
            "P3": (1, "Multi-turn conversations, but no task-completion score"),
            "P4": (1, "Per-conversation choice; no overall adoption decision")},
         Q=dict(competing_alts=2, brand_neutral=1, who_attrs=2, startup_realism=1, no_contam=1, why=2, evaluable=2, license=1, mcp_arm=2),
         unverified=["brand_neutral: anonymity of models", "license: exact CC variant"],
         note="8,011 conversations with 21 LLMs; rich individual profiles; skews young, white, educated."),
    dict(name="Chatbot Arena votes", org="LMArena", status="available", url="https://huggingface.co/lmarena-ai",
         license="varies by release (verify)", adapter=False,
         P={"P1": (0, "No questionnaire"), "P2": (0, "No pre-use stage"),
            "P3": (1, "Own prompts, usually single turn; no completion score"),
            "P4": (2, "Blind pairwise votes between competing products")},
         Q=dict(competing_alts=2, brand_neutral=2, who_attrs=0, startup_realism=1, no_contam=0, why=0, evaluable=2, license=1, mcp_arm=1),
         unverified=["license per release"], note="Huge volume, no demographics; leaderboard widely published, so outcomes are known to LLMs."),
    dict(name="Twin-2K-500", org="Toubia et al., 2025", status="available", url="https://huggingface.co/datasets/LLM-Digital-Twin/Twin-2K-500",
         license="CC BY 4.0", adapter=True,
         P={"P1": (3, "500 questions per person, 2,058 people, retest wave: person-level answer distributions"),
            "P2": (1, "Product description plus price, then buy or not"),
            "P3": (0, "No tasks"),
            "P4": (1, "Buy yes/no at a price; no choice against a competitor")},
         Q=dict(competing_alts=0, brand_neutral=0, who_attrs=2, startup_realism=0, no_contam=1, why=0, evaluable=2, license=2, mcp_arm=2),
         unverified=[], note="Products are branded groceries (Land O Lakes, Tylenol). Adapter run: reasons pass, segments fail stability."),
    dict(name="SimBench", org="Hu et al., ICLR 2026", status="available", url="https://arxiv.org/abs/2510.17516",
         license="CC BY-NC-SA", adapter=True,
         P={"P1": (3, "20 datasets of real group answer distributions"), "P2": (0, ""), "P3": (0, ""), "P4": (0, "")},
         Q=dict(competing_alts=0, brand_neutral=1, who_attrs=1, startup_realism=0, no_contam=1, why=0, evaluable=2, license=1, mcp_arm=2),
         unverified=[], note="Group level only; median 1-5 groups per question, so reasons and segments cannot be estimated. Our harness: 41.5 plain vs 55.8 with no target labels."),
    dict(name="Pew ATP tech adoption", org="Pew Research Center", status="restricted", url="https://www.pewresearch.org/american-trends-panel-datasets/",
         license="Free account; no resale or redistribution", adapter=False,
         P={"P1": (3, "Person-level survey answers with full demographics, ~10k per wave"),
            "P2": (0, ""), "P3": (0, ""),
            "P4": (1, "Which platforms people actually use (big brands)")},
         Q=dict(competing_alts=1, brand_neutral=0, who_attrs=2, startup_realism=1, no_contam=1, why=1, evaluable=2, license=1, mcp_arm=2),
         unverified=["which waves carry product-adoption items"], note="Download requires a Pew account."),
    dict(name="OPeRA", org="Wang et al., ACL 2026", status="available", url="https://huggingface.co/datasets/NEU-HAI/OPeRA",
         license="CC BY 4.0", adapter=False,
         P={"P1": (1, "Persona surveys of 51 shoppers"), "P2": (1, "Search results seen before choosing"),
            "P3": (3, "Real shopping sessions: every action, purchase or abandon, with a rationale per step"),
            "P4": (1, "Purchase among products found")},
         Q=dict(competing_alts=1, brand_neutral=0, who_attrs=2, startup_realism=1, no_contam=2, why=2, evaluable=1, license=2, mcp_arm=1),
         unverified=[], note="Small (51 people, 692 sessions). Branded Amazon products."),
    dict(name="ShopCART", org="Lu et al., ACL 2026", status="restricted", url="https://huggingface.co/datasets/NEU-HAI/ShopCART",
         license="none stated", adapter=False,
         P={"P1": (0, ""), "P2": (0, ""), "P3": (2, "31,865 Amazon sessions with actions and outcomes"), "P4": (1, "Purchase or not")},
         Q=dict(competing_alts=1, brand_neutral=0, who_attrs=1, startup_realism=1, no_contam=2, why=0, evaluable=2, license=0, mcp_arm=1),
         unverified=[], note="No licence tag, so treat as restricted."),
    dict(name="Online-Mind2Web", org="OSU, 2025", status="available", url="https://huggingface.co/datasets/osunlp/Online-Mind2Web",
         license="research", adapter=False,
         P={"P1": (0, ""), "P2": (0, ""), "P3": (2, "Human task completion paths on real websites; no preference"), "P4": (0, "")},
         Q=dict(competing_alts=0, brand_neutral=1, who_attrs=0, startup_realism=2, no_contam=1, why=0, evaluable=2, license=1, mcp_arm=1),
         unverified=[], note="Useful for task mechanics (branch 3), not for preference."),
    dict(name="Upworthy A/B archive", org="Matias et al., 2021", status="available", url="https://osf.io/jd64p/",
         license="CC BY 4.0", adapter=False,
         P={"P1": (0, ""), "P2": (2, "Headline variant clicks: first impression of a message"), "P3": (0, ""), "P4": (1, "A click is a micro-choice")},
         Q=dict(competing_alts=2, brand_neutral=2, who_attrs=0, startup_realism=0, no_contam=1, why=0, evaluable=2, license=2, mcp_arm=2),
         unverified=[], note="32,487 randomized tests, aggregate clicks, news headlines 2013-15."),
    dict(name="WiserUI-Bench", org="Jeon et al., ACL 2026", status="restricted", url="https://github.com/jeochris/wiserui-bench",
         license="CC BY-NC-SA", adapter=False,
         P={"P1": (0, ""), "P2": (3, "Real UI A/B pairs with the winning variant from live tests"), "P3": (1, "Conversions involve interacting"),
            "P4": (1, "Variant that converted better")},
         Q=dict(competing_alts=2, brand_neutral=2, who_attrs=0, startup_realism=2, no_contam=1, why=1, evaluable=1, license=1, mcp_arm=1),
         unverified=[], note="300 pairs; non-commercial licence; expert rationales."),
    dict(name="Show HN (live)", org="Hacker News API", status="proposed", url="https://github.com/HackerNews/API",
         license="public API", adapter=False,
         P={"P1": (0, ""), "P2": (3, "Landing page first impression, captured at submission"),
            "P3": (1, "Some comments come from people who tried the product"),
            "P4": (1, "Upvotes measure interest, not adoption")},
         Q=dict(competing_alts=1, brand_neutral=2, who_attrs=0, startup_realism=2, no_contam=2, why=2, evaluable=1, license=2, mcp_arm=2),
         unverified=[], note="Real startups, live so nothing to memorize; one audience, aggregate only. Needs the forecasting pipeline."),
    dict(name="Product Hunt (live)", org="Product Hunt API", status="restricted", url="https://api.producthunt.com/v2/docs",
         license="non-commercial by default", adapter=False,
         P={"P1": (0, ""), "P2": (2, "Launch page"), "P3": (1, "Reviews from users"), "P4": (2, "Daily ranking among the day's launches")},
         Q=dict(competing_alts=2, brand_neutral=1, who_attrs=0, startup_realism=2, no_contam=2, why=1, evaluable=1, license=0, mcp_arm=2),
         unverified=[], note="Needs permission; rankings carry campaign noise."),
    dict(name="Kickstarter", org="ICPSR 38050 / webrobots", status="restricted", url="https://www.icpsr.umich.edu/web/ICPSR/studies/38050",
         license="public file lacks page text; text file restricted", adapter=False,
         P={"P1": (0, ""), "P2": (2, "Campaign page"), "P3": (0, ""), "P4": (3, "Backing with real money, among new unknown products")},
         Q=dict(competing_alts=1, brand_neutral=2, who_attrs=0, startup_realism=1, no_contam=1, why=0, evaluable=2, license=1, mcp_arm=2),
         unverified=["text access terms"], note="610k projects 2009-2023; mostly physical and creative products."),
    dict(name="LabInTheWild web appeal", org="Reinecke & Gajos", status="restricted", url="https://www.www1.labinthewild.org/data/index.php",
         license="data on request", adapter=False,
         P={"P1": (2, "Appeal rating distributions by demographic and country"), "P2": (3, "First impression of website screenshots"),
            "P3": (0, ""), "P4": (0, "")},
         Q=dict(competing_alts=1, brand_neutral=1, who_attrs=2, startup_realism=2, no_contam=2, why=0, evaluable=2, license=0, mcp_arm=2),
         unverified=["dataset contents and terms"], note="40k+ people rated website screenshots 1-9."),
    dict(name="G2 / Capterra reviews", org="Review platforms", status="restricted", url="https://www.g2.com/",
         license="no scraping; needs a data deal", adapter=False,
         P={"P1": (1, "Rating distributions"), "P2": (0, ""), "P3": (2, "Post-use ease of use, setup, support"),
            "P4": (3, "Alternatives considered and switched from, ratings against competitors")},
         Q=dict(competing_alts=2, brand_neutral=1, who_attrs=1, startup_realism=2, no_contam=1, why=2, evaluable=1, license=0, mcp_arm=1),
         unverified=[], note="Closest to B2B software competitor choice, but not usable without a licence."),
    dict(name="App store reviews", org="Google Play / App Store", status="restricted", url="https://www.kaggle.com/search?q=app+reviews",
         license="varies", adapter=False,
         P={"P1": (1, "Star distributions"), "P2": (0, ""), "P3": (2, "Complaints about using the app"), "P4": (1, "Rating as a weak proxy for choice")},
         Q=dict(competing_alts=1, brand_neutral=1, who_attrs=0, startup_realism=2, no_contam=1, why=2, evaluable=1, license=1, mcp_arm=1),
         unverified=[], note="No demographics."),
    dict(name="UserSim own panel (target design)", org="Prolific panel + live products", status="proposed", url="",
         license="ours", adapter=False,
         P={"P1": (3, "Profile survey of the same people"), "P2": (3, "First impression of product and competitors' pages"),
            "P3": (3, "The same people attempt the same tasks on each product"), "P4": (3, "Then choose")},
         Q=dict(competing_alts=2, brand_neutral=2, who_attrs=2, startup_realism=2, no_contam=2, why=2, evaluable=2, license=2, mcp_arm=2),
         unverified=[], note="Not collected. Shown as the reference: the only design that links P1-P4 for the same people. Cost about $3-4k for 1,000 profiles plus each study."),
]


def build():
    data = {"stages": STAGES, "quality": {k: {"label": a, "desc": b, "weight": w} for k, (a, b, w) in QUALITY.items()},
            "status": STATUS,
            "benchmarks": [dict(b, P={k: {"score": s, "why": n} for k, (s, n) in b["P"].items()}) for b in B]}
    (HERE / "benchmarks.json").write_text(json.dumps(data, indent=1))
    tpl = (HERE / "benchmark_board.template.html").read_text()
    (ROOT / "docs" / "benchmark_fit_board.html").write_text(tpl.replace("__DATA__", json.dumps(data)))
    print("wrote", len(B), "benchmarks")


if __name__ == "__main__":
    build()
