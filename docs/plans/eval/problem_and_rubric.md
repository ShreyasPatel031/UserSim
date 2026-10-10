# What UserSim predicts, and how candidate benchmarks are judged

Status: draft for the four branches (population distribution, initial preference, task-completion preference, overall choice). Scores are produced by `benchmark_rubric_scores.py` in this folder; edit the weights there, not here.

## Problem statement

Input: a new product (a startup with no brand to lean on), its competitors, optionally a target population, and optionally tasks.

| | We predict | Unit | Output |
|---|---|---|---|
| P1 | The distribution of answers real people give to questions about the product or category | population or segment x question | answer distribution, by segment, with reasons and segments that pass the interpretability tests |
| P2 | Initial perception and preference on first exposure (page, description, demo), before use | segment x product set x stimulus | preference shares across product and competitors, perception ratings (clarity, trust, value), reasons |
| P3 | Task outcomes and preference after attempting given tasks on the product and on competitors | segment x product set x task | completion and failure points per product, post-task preference shares, reasons |
| P4 (primary) | Overall choice: which product people would pick | segment x product set (x context) | choice shares by segment; ideally explained by P1-P3 |

Out of scope for now: network effects and brand effects (we target new startups).

A good benchmark for P4 is one where (a) real people (b) choose between competing products (c) without brand cues, (d) and we know who they are, (e) ideally after a first impression and a task, (f) with reasons.

## Rubric (0 absent, 1 partial, 2 strong)

| Criterion | Weight | What 2 means |
|---|---|---|
| real_humans | gate | outcomes come from real people, not model judges |
| competing_alts | 2 | people choose between real competing products or variants |
| brand_neutral | 2 | blind comparison, unknown makers, or variants of one brand |
| first_impr | 1.5 | a pre-use exposure is recorded (P2) |
| task_compl | 1.5 | people attempt tasks and outcome is recorded (P3) |
| overall_choice | 3 | an overall pick / adoption / commitment is recorded (P4) |
| who_attrs | 2 | person-level attributes with enough people per segment |
| why | 1 | reasons: multi-dimension ratings, rationales or free text |
| startup_realism | 2 | the products are digital products comparable to a startup's |
| no_contam | 1.5 | an LLM cannot already know the outcome (new, live, or individual-level) |
| evaluable | 1 | held-out splits, sample size, a measurable noise ceiling |
| license | 1 | public and publishable |
| mcp_arm | 1 | there is legitimate non-target evidence a tool-augmented model can use without leaking the answer |

Cells marked "?" in the script were not yet verified against the data and are scored 1.

## Scores (weights as above)

See `benchmark_rubric_scores.py` output (copied below at the time of writing).

```
score | benchmark | real_humans | competing_alts | brand_neutral | first_impr | task_compl | overall_choice | who_attrs | why | startup_realism | no_contam | evaluable | license | mcp_arm
78 | HUMAINE (Prolific) | 2 | 2 | 1 | 0 | 2 | 2 | 2 | 2 | 1 | 1 | 2 | 2 | 2
72 | PRISM (Kirk 2024) | 2 | 2 | 1 | 2 | 1 | 1 | 2 | 2 | 1 | 1 | 2 | 1 | 2
67 | Show HN (live) | 2 | 1 | 2 | 2 | 0 | 1 | 0 | 2 | 2 | 2 | 1 | 2 | 2
64 | WiserUI-Bench | 2 | 2 | 2 | 2 | 1 | 1 | 0 | 1 | 2 | 1 | 1 | 1 | 1
64 | G2/Capterra reviews | 2 | 2 | 1 | 0 | 1 | 2 | 1 | 2 | 2 | 1 | 1 | 0 | 1
63 | OPeRA shopping | 2 | 1 | 0 | 1 | 2 | 1 | 2 | 2 | 1 | 2 | 1 | 2 | 1
60 | Kickstarter | 2 | 1 | 2 | 2 | 0 | 2 | 0 | 0 | 1 | 1 | 2 | 1 | 2
56 | LabInTheWild web appeal | 2 | 1 | 1 | 2 | 0 | 0 | 2 | 0 | 2 | 2 | 2 | 0 | 2
55 | Upworthy A/B | 2 | 2 | 2 | 2 | 0 | 1 | 0 | 0 | 0 | 1 | 2 | 2 | 2
55 | Chatbot Arena votes | 2 | 2 | 2 | 0 | 1 | 2 | 0 | 0 | 1 | 0 | 2 | 1 | 1
54 | Product Hunt (live) | 2 | 1 | 1 | 2 | 0 | 1 | 0 | 1 | 2 | 2 | 1 | 0 | 2
49 | App store reviews | 2 | 1 | 1 | 0 | 1 | 1 | 0 | 2 | 2 | 1 | 1 | 1 | 1
46 | ShopCART | 2 | 1 | 0 | 0 | 2 | 1 | 1 | 0 | 1 | 2 | 2 | 0 | 1
41 | Twin-2K-500 pricing | 2 | 0 | 0 | 1 | 0 | 1 | 2 | 0 | 0 | 1 | 2 | 2 | 2
37 | Online-Mind2Web | 2 | 0 | 1 | 0 | 2 | 0 | 0 | 0 | 2 | 1 | 2 | 1 | 1
27 | SimBench | 2 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 1 | 2 | 1 | 2
```

Ranking is stable under equal weights, doubled startup realism, heavier contamination penalty, and ignoring person attributes: HUMAINE stays first; Show HN and PRISM stay in the top three.

## Conclusions

1. No public benchmark covers the full chain (first impression -> task -> overall choice) for the same people on startup-like products. The best scores are about 70-78/100. That chain has to be collected eventually (own panel).
2. Closest to P4: HUMAINE. Real people pick between competing software products after doing their own tasks, with demographics, goal achievement per conversation (P3) and reasons per dimension. Weak on startup realism (AI assistants, not startup apps) and contamination (LLMs know model reputations). Blind comparison to be verified.
3. PRISM adds what HUMAINE lacks: first-turn ratings of several models (P2) and rich individual profiles. Licence variant to verify.
4. Show HN (live) is the only high scorer with real startups and no contamination, but it is aggregate-only (no person attributes) and measures interest, not adoption.
5. Twin-2K-500 scores low for P2-P4 (branded groceries, no competitor choice) and stays as a P1 person-level testbed only. SimBench is P1 only.
6. Within HUMAINE / PRISM the same people give task-level scores and a choice, so the claim "P2/P3 predict P4" can be tested there and nowhere else in public data.
