"""Benchmark Fit Board: how well each candidate benchmark measures UserSim's four prediction targets.

Single source of truth for the scores. Running this file writes:
  docs/plans/eval/benchmarks.json   (the data)
  docs/benchmark_fit_board.html     (interactive board: weights, filters, ranking by stage)

Stage fit (0-3):  0 absent, 1 present but predictable from product reputation alone, 2 people-dependent (aggregate),
                  3 people-dependent by segment or person with held-out outcomes.
Quality (0-2):    0 absent, 1 partial, 2 strong.
"?" in `unverified` lists cells scored from papers or summaries that have not yet been checked against the data itself.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

STAGES = {
    "P1": "What real people would answer about the product or category: answer distributions by segment, with reasons",
    "P2": "First impression and preference from the page or demo, before use: shares across product and competitors, perception ratings, reasons",
    "P3": "Preference after attempting given tasks: who completes, where they fail, post-task preference, why",
    "P4": "Which product people would choose overall (primary): choice shares by segment, explained by P1-P3",
}

# Stage scale (0-3): 0 absent; 1 present but predictable from product reputation alone (or a weak proxy);
# 2 depends on people at the aggregate level; 3 depends on people by segment or person, with held-out outcomes.
QUALITY = {
    "unknown_products": ("Unknown products", "Products or stimuli a model cannot know the outcome for ('no brand to lean on')", 2),
    "competitors": ("Competitors in one judgement", "People judge or choose between alternatives, so shares across products can be scored", 2),
    "headroom": ("Harness headroom", "A bare frontier model sits well below the noise ceiling, so harness gains are visible", 2),
    "public_arm": ("Fair public-data arm", "Outside public evidence exists that a harness may use without leaking the answer", 2),
    "target_pop": ("Target population", "Segment attributes, or each person's own source data (history, interviews, behaviour)", 1.5),
    "heldout_same": ("Held-out outcomes, same people", "New questions, studies or later behaviour for the same people or segments", 1.5),
    "reasons": ("Reasons", "Multi-dimension ratings, rationales or free text", 1),
    "tasks": ("Tasks with outcomes", "Given tasks with completion and failure points (P3)", 1),
    "baseline": ("Accepted baseline", "A published bare-model or standard baseline, so others accept the comparison", 1),
    "power": ("Statistical power", "Enough people, items or studies to detect a +1-2 point gain", 1),
    "digital": ("Digital-product realism", "Digital products comparable to a startup's", 0.5),
    "license": ("Publishable", "Licence or terms allow publishing results", 0.5),
}

STATUS = {
    "available": "Available now: public download",
    "restricted": "Restricted: on request, data deal, or non-commercial terms",
    "proposed": "Proposed: needs a pipeline or new data collection",
}

Q = lambda **k: k
B = [
    dict(name="Twin-2K-500 Mega-Study", org="Peng, Gui, Toubia et al., 2025-26", status="available", url="https://huggingface.co/datasets/LLM-Digital-Twin/Twin-2K-500-Mega-Study",
         license="Apache-2.0", adapter=False,
         P={"P1": (3, "19 new pre-registered studies, 164 outcomes, answered by the same 1,784 Twin-2K people: person-level, held out"),
            "P2": (2, "Some studies rate new stimuli before use (idea evaluation, NFT luxury goods, ad targeting)"),
            "P3": (0, "No tasks"),
            "P4": (1, "Context and default-effect choices; not products against competitors")},
         Q=Q(unknown_products=1, competitors=1, headroom=2, public_arm=2, target_pop=2, heldout_same=2, reasons=0, tasks=0, baseline=2, power=2, digital=1, license=2),
         unverified=[], note="Published bar: twins correlate r = 0.20-0.23 with individuals and are no more accurate than demographics-only personas (0.748 vs 0.746). Answers too uniform on 154 of 164 outcomes."),
    dict(name="Twin-2K-500", org="Toubia et al., 2025", status="available", url="https://huggingface.co/datasets/LLM-Digital-Twin/Twin-2K-500",
         license="CC BY 4.0", adapter=True,
         P={"P1": (3, "500+ answers per person, 2,058 people, retest wave: person-level distributions with a ceiling"),
            "P2": (1, "Product description plus price, then buy or not"),
            "P3": (0, "No tasks"),
            "P4": (1, "Buy yes/no at a price; no competitor")},
         Q=Q(unknown_products=0, competitors=0, headroom=1, public_arm=2, target_pop=2, heldout_same=2, reasons=0, tasks=0, baseline=2, power=2, digital=0, license=2),
         unverified=[], note="Branded groceries. Our adapter: reasons axes beat demographics (TVD 0.480 vs 0.490; group-gap correlation 0.44 vs 0.10); segments unstable."),
    dict(name="PRISM", org="Kirk et al., NeurIPS 2024", status="available", url="https://huggingface.co/datasets/HannahRoseKirk/prism-alignment",
         license="CC BY 4.0 text; CC BY-NC 4.0 model responses", adapter=False,
         P={"P1": (2, "Profile survey of 1,500 people with stated preferences about AI, by segment"),
            "P2": (3, "First-turn ratings of up to 4 models before choosing; several conversations per person (LoRe: 62.5% -> 71.0% with about 4 examples per user)"),
            "P3": (1, "Multi-turn conversations, no task-completion score"),
            "P4": (1, "Per-conversation choice; no overall adoption decision")},
         Q=Q(unknown_products=1, competitors=2, headroom=1, public_arm=2, target_pop=2, heldout_same=2, reasons=2, tasks=0, baseline=1, power=2, digital=1, license=1),
         unverified=["unknown_products: whether models were anonymous to participants"], note="The only public set linking profiles, free-text self-descriptions, first impressions and choice for the same people."),
    dict(name="OPeRA", org="Wang et al., ACL 2026", status="available", url="https://huggingface.co/datasets/NEU-HAI/OPeRA",
         license="CC BY 4.0, 'research purposes only'", adapter=False,
         P={"P1": (1, "Persona surveys and optional 20-minute interviews of 51 shoppers"),
            "P2": (1, "Search results seen before choosing"),
            "P3": (3, "About 13 real sessions per person over 4 weeks: every action, purchase or abandon, rationale per step; later sessions can be held out"),
            "P4": (2, "Purchase among products found")},
         Q=Q(unknown_products=0, competitors=1, headroom=2, public_arm=1, target_pop=2, heldout_same=2, reasons=2, tasks=1, baseline=2, power=0, digital=2, license=1),
         unverified=[], note="The only open set with interview, survey and behaviour for the same people. Prompted GPT-4.1 21.5% next action; SFT+RL about 38-40%."),
    dict(name="SimBench", org="Hu et al., ICLR 2026", status="available", url="https://arxiv.org/abs/2510.17516",
         license="CC BY-NC-SA", adapter=True,
         P={"P1": (3, "20 datasets of real group answer distributions; held-out questions per group"), "P2": (0, ""), "P3": (0, ""), "P4": (0, "")},
         Q=Q(unknown_products=1, competitors=0, headroom=2, public_arm=2, target_pop=1, heldout_same=1, reasons=0, tasks=0, baseline=2, power=2, digital=0, license=1),
         unverified=[], note="Our strongest proof that harness + public data beats the bare model: 41.5 -> 55.8 with no target labels. Group level only."),
    dict(name="Pew ATP tech adoption", org="Pew Research Center", status="restricted", url="https://www.pewresearch.org/american-trends-panel-datasets/",
         license="Free account; no resale or redistribution", adapter=False,
         P={"P1": (3, "Person-level answers with demographics; the same panelists across waves"),
            "P2": (0, ""), "P3": (0, ""),
            "P4": (1, "Which platforms people use (big brands)")},
         Q=Q(unknown_products=1, competitors=1, headroom=1, public_arm=2, target_pop=2, heldout_same=2, reasons=1, tasks=0, baseline=1, power=2, digital=1, license=1),
         unverified=["which waves carry product-adoption items"], note="Download requires a Pew account."),
    dict(name="Community Alignment", org="Meta, 2025", status="available", url="https://huggingface.co/datasets/facebook/community-alignment-dataset",
         license="CC BY 4.0", adapter=False,
         P={"P1": (2, "Survey of 15k nationally representative people in 5 countries"),
            "P2": (2, "Preferences among response variants, with annotator demographics"),
            "P3": (0, ""), "P4": (1, "Choice among variants of one model, not products")},
         Q=Q(unknown_products=1, competitors=2, headroom=1, public_arm=1, target_pop=2, heldout_same=1, reasons=1, tasks=0, baseline=1, power=2, digital=1, license=2),
         unverified=[], note="Over 200k comparisons from 3,500 annotators."),
    dict(name="HUMAINE", org="Prolific, 2026", status="available", url="https://huggingface.co/datasets/ProlificAI/humaine-evaluation-dataset",
         license="MIT", adapter=True,
         P={"P1": (0, "Goal and engagement scores are labels from a GPT-4.1 judge, not answers from people"),
            "P2": (0, "No pre-use exposure"),
            "P3": (1, "Post-use comparison after people's own tasks, but no human completion labels"),
            "P4": (1, "Choice shares by segment exist, but the LMArena ratings alone predict them as well as our best model (45.9 vs 45.8); per-vote age effects are nil. Tie rates are people-dependent")},
         Q=Q(unknown_products=0, competitors=2, headroom=2, public_arm=2, target_pop=1, heldout_same=0, reasons=2, tasks=1, baseline=1, power=2, digital=2, license=2),
         unverified=[], note="Products are famous AI models with public leaderboards. Our run: Gemini 23.2 -> 39.5 with arena ratings; ceiling 71.8. Useful for tie/indifference behaviour and pilot-calibration tests."),
    dict(name="Miniukovich & Figl homepages", org="Data in Brief, 2023", status="available", url="https://pmc.ncbi.nlm.nih.gov/articles/PMC10823051/",
         license="Harvard Dataverse; licence not stated", adapter=False,
         P={"P1": (2, "Rating distributions by demographic and domain familiarity"),
            "P2": (3, "About 3,150 homepages rated by 2,822 people on aesthetics, trust, usability and prototypicality, with rate-rerate duplicates"),
            "P3": (0, "Static pages"), "P4": (0, "")},
         Q=Q(unknown_products=1, competitors=1, headroom=1, public_arm=1, target_pop=2, heldout_same=1, reasons=0, tasks=0, baseline=0, power=2, digital=2, license=1),
         unverified=["licence"], note="Best free first-impression set with segments (banking, shopping, university sites)."),
    dict(name="LabInTheWild web appeal", org="Reinecke & Gajos", status="restricted", url="https://www.www1.labinthewild.org/data/index.php",
         license="data on request", adapter=False,
         P={"P1": (2, "Appeal distributions by demographic and country"), "P2": (3, "500 ms first impressions of website screenshots, 40k+ people"),
            "P3": (0, ""), "P4": (0, "")},
         Q=Q(unknown_products=1, competitors=1, headroom=1, public_arm=1, target_pop=2, heldout_same=1, reasons=0, tasks=0, baseline=1, power=2, digital=2, license=0),
         unverified=["dataset contents and terms"], note="Demographics move the preference peak but explain little variance."),
    dict(name="Upworthy A/B archive", org="Matias et al., 2021", status="available", url="https://osf.io/jd64p/",
         license="CC BY 4.0", adapter=False,
         P={"P1": (0, ""), "P2": (2, "Click shares across headline variants: first impression of a message, aggregate"), "P3": (0, ""), "P4": (1, "A click is a micro-choice")},
         Q=Q(unknown_products=1, competitors=2, headroom=2, public_arm=2, target_pop=0, heldout_same=0, reasons=0, tasks=0, baseline=2, power=2, digital=1, license=2),
         unverified=[], note="32,487 randomized tests. Raw LLMs recover 39% of the effect; tree calibration closes it (Spotify)."),
    dict(name="WiserUI-Bench", org="Jeon et al., ACL 2026", status="restricted", url="https://github.com/jeochris/wiserui-bench",
         license="CC BY-NC-SA", adapter=False,
         P={"P1": (0, ""), "P2": (2, "Real UI A/B pairs with the winning variant"), "P3": (1, "Conversions involve interacting"), "P4": (1, "Variant that converted better")},
         Q=Q(unknown_products=1, competitors=2, headroom=2, public_arm=1, target_pop=0, heldout_same=0, reasons=1, tasks=0, baseline=2, power=1, digital=2, license=1),
         unverified=[], note="300 pairs; frontier models near chance once order is controlled."),
    dict(name="ConvApparel", org="Google, EACL 2026", status="available", url="https://huggingface.co/datasets/google/ConvApparel",
         license="CC BY 4.0 / BY-SA (check)", adapter=False,
         P={"P1": (0, ""), "P2": (1, "First turns with each recommender"),
            "P3": (2, "Shopping task with a randomized good or bad recommender; turn-level satisfaction and frustration, post-session survey"),
            "P4": (1, "Which assistant served better, by condition")},
         Q=Q(unknown_products=1, competitors=2, headroom=1, public_arm=1, target_pop=0, heldout_same=0, reasons=1, tasks=2, baseline=1, power=2, digital=2, license=2),
         unverified=[], note="Best public test of whether a simulator moves in the right direction under a product change."),
    dict(name="Hillstrom / X5 uplift", org="MineThatData; X5 RetailHero", status="available", url="https://www.uplift-modeling.com/en/latest/api/datasets/fetch_x5.html",
         license="free distribution / hackathon terms", adapter=False,
         P={"P1": (0, ""), "P2": (1, "Response to a marketing message"), "P3": (0, ""),
            "P4": (2, "Purchase after a randomized campaign, per customer with purchase history")},
         Q=Q(unknown_products=1, competitors=1, headroom=1, public_arm=1, target_pop=2, heldout_same=2, reasons=0, tasks=0, baseline=2, power=2, digital=1, license=1),
         unverified=["X5 randomization"], note="Customer history plus a randomized intervention; tabular, not clickstream."),
    dict(name="Park et al. 1,000 interviews", org="Stanford, 2024-26", status="restricted", url="https://arxiv.org/abs/2411.10109",
         license="academic use by application", adapter=False,
         P={"P1": (3, "2-hour interviews, then new survey answers two weeks later, scored against each person's retest"),
            "P2": (0, ""), "P3": (0, ""), "P4": (0, "Economic games, not product choice")},
         Q=Q(unknown_products=1, competitors=0, headroom=1, public_arm=2, target_pop=2, heldout_same=2, reasons=2, tasks=0, baseline=2, power=2, digital=0, license=0),
         unverified=["whether the restricted API has opened"], note="The exact interview-to-twin design: 0.83-0.86 of retest vs 0.74 for demographics. Methods template; apply for research access."),
    dict(name="Chatbot Arena votes", org="LMArena", status="available", url="https://huggingface.co/lmarena-ai",
         license="CC BY 4.0 (releases vary)", adapter=False,
         P={"P1": (0, "No questionnaire"), "P2": (1, "Blind first-turn votes, largely predictable from model quality"),
            "P3": (1, "Own prompts, usually single turn"), "P4": (1, "Blind pairwise votes between famous products")},
         Q=Q(unknown_products=1, competitors=2, headroom=1, public_arm=1, target_pop=0, heldout_same=0, reasons=0, tasks=0, baseline=2, power=2, digital=2, license=1),
         unverified=[], note="Huge volume, no demographics."),
    dict(name="Kickstarter", org="ICPSR 38050 / webrobots", status="restricted", url="https://www.icpsr.umich.edu/web/ICPSR/studies/38050",
         license="public file lacks page text; text file restricted", adapter=False,
         P={"P1": (0, ""), "P2": (2, "Campaign page, aggregate response"), "P3": (0, ""), "P4": (2, "Backing with real money among new, unknown products")},
         Q=Q(unknown_products=1, competitors=1, headroom=1, public_arm=1, target_pop=0, heldout_same=0, reasons=0, tasks=0, baseline=1, power=2, digital=0, license=1),
         unverified=["text access terms"], note="610k projects 2009-2023; mostly physical and creative products."),
    dict(name="Show HN (live)", org="Hacker News API", status="proposed", url="https://github.com/HackerNews/API",
         license="public API", adapter=False,
         P={"P1": (0, ""), "P2": (2, "Landing-page first impression of real new startups, aggregate"),
            "P3": (1, "Some comments come from people who tried the product"), "P4": (1, "Upvotes measure interest, not adoption")},
         Q=Q(unknown_products=2, competitors=1, headroom=1, public_arm=1, target_pop=0, heldout_same=0, reasons=2, tasks=0, baseline=0, power=1, digital=2, license=2),
         unverified=[], note="Live, so nothing to memorize; needs the forecasting pipeline."),
    dict(name="Product Hunt (live)", org="Product Hunt API", status="restricted", url="https://api.producthunt.com/v2/docs",
         license="non-commercial by default (open benchmark only)", adapter=False,
         P={"P1": (0, ""), "P2": (2, "Launch page"), "P3": (1, "Reviews"), "P4": (2, "Daily ranking among the day's launches")},
         Q=Q(unknown_products=2, competitors=2, headroom=1, public_arm=1, target_pop=0, heldout_same=0, reasons=1, tasks=0, baseline=0, power=1, digital=2, license=0),
         unverified=[], note="Campaign noise in rankings."),
    dict(name="G2 / Capterra reviews", org="Review platforms", status="restricted", url="https://www.g2.com/",
         license="no scraping; needs a data deal", adapter=False,
         P={"P1": (1, "Rating distributions"), "P2": (0, ""), "P3": (2, "Post-use ease of use, setup, support"),
            "P4": (2, "Alternatives considered and switched from")},
         Q=Q(unknown_products=1, competitors=2, headroom=1, public_arm=1, target_pop=1, heldout_same=0, reasons=2, tasks=0, baseline=0, power=2, digital=2, license=0),
         unverified=[], note="Closest to B2B software choice, but not usable without a licence."),
    dict(name="App store reviews", org="Google Play / App Store", status="restricted", url="https://www.kaggle.com/search?q=app+reviews",
         license="varies", adapter=False,
         P={"P1": (1, "Star distributions"), "P2": (0, ""), "P3": (1, "Complaints about using the app"), "P4": (1, "Rating as a weak proxy for choice")},
         Q=Q(unknown_products=1, competitors=1, headroom=1, public_arm=1, target_pop=0, heldout_same=0, reasons=2, tasks=0, baseline=0, power=2, digital=2, license=1),
         unverified=[], note="No demographics."),
    dict(name="ShopCART", org="Lu et al., ACL 2026", status="restricted", url="https://arxiv.org/abs/2503.20749",
         license="not released", adapter=False,
         P={"P1": (0, ""), "P2": (0, ""), "P3": (2, "31,865 Amazon sessions with actions and outcomes"), "P4": (1, "Purchase or not")},
         Q=Q(unknown_products=0, competitors=1, headroom=2, public_arm=1, target_pop=0, heldout_same=0, reasons=0, tasks=1, baseline=2, power=2, digital=2, license=0),
         unverified=[], note="Authors say they cannot release the data."),
    dict(name="Online-Mind2Web", org="OSU, 2025", status="available", url="https://huggingface.co/datasets/osunlp/Online-Mind2Web",
         license="research", adapter=False,
         P={"P1": (0, ""), "P2": (0, ""), "P3": (1, "Task completion on real websites; no preference"), "P4": (0, "")},
         Q=Q(unknown_products=1, competitors=0, headroom=1, public_arm=1, target_pop=0, heldout_same=0, reasons=0, tasks=2, baseline=1, power=1, digital=2, license=1),
         unverified=[], note="Task mechanics (branch 3), not preference."),
    dict(name="Anthropic Interviewer", org="Anthropic, 2025", status="available", url="https://huggingface.co/datasets/Anthropic/AnthropicInterviewer",
         license="CC BY / MIT (check)", adapter=False,
         P={"P1": (1, "1,250 interview transcripts about AI at work; no structured held-out outcomes"), "P2": (0, ""), "P3": (0, ""), "P4": (0, "")},
         Q=Q(unknown_products=1, competitors=0, headroom=0, public_arm=1, target_pop=2, heldout_same=0, reasons=2, tasks=0, baseline=0, power=1, digital=1, license=2),
         unverified=[], note="Realistic interview text for testing ingestion and PII handling; nothing to predict."),
    dict(name="UserSim own panel (target design)", org="Prolific panel + live products", status="proposed", url="",
         license="ours", adapter=False,
         P={"P1": (3, "Profile survey of the same people"), "P2": (3, "First impression of product and competitors' pages"),
            "P3": (3, "The same people attempt the same tasks on each product"), "P4": (3, "Then choose")},
         Q=Q(unknown_products=2, competitors=2, headroom=2, public_arm=2, target_pop=2, heldout_same=2, reasons=2, tasks=2, baseline=1, power=1, digital=2, license=2),
         unverified=[], note="Not collected. The only design that links P1-P4 for the same people on unknown products."),
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
