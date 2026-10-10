# UserSim roadmap: predictability infrastructure (October 2026)

UserSim is infrastructure that makes a startup's users predictable, even before the startup has any user data. It combines our model, data priors, and a harness for selecting, curating and calibrating data. The benchmarks below are how we measure progress. This plan covers three spending stages: FREE (no paid data), Experimental (about $200 a month) and Incremental (about $2,000 a month).

Companion pages:
- [Data Lever Board](https://claude.ai/artifact/JivwNQo6CWShstVeUpWCVr): which data moves which benchmark, measured.
- [Benchmark Fit Board](https://claude.ai/artifact/LMKkv22QUcrCTR9bmRKAiw): which benchmarks measure P1-P4.
- [SimBench Strategy Map](https://claude.ai/artifact/BCDV1zvdmajxxuBe56goQc).

Source files:
- `docs/plans/eval/data_board.py`
- `results/humaine/*.json`
- `docs/plans/usersim_direction_2026-10.md`

## 1. The answer in brief

1. **Real answers from real people carry the prediction.** The model's job is to read that evidence and spread it to new cases, not to know the answer.
   - On SimBench, other populations' answers to the same question supply about 69% of our lift: 41.5 → 55.8 with no labels from the target dataset.
   - On HUMAINE, a simulated pilot of 50 people from the target population adds +8.1 S on overall choice and +55 S on the four reasons, on top of the best zero-data model. A 400-person pilot adds +14.1 and +65.
2. **Public data about the same products from a different crowd is the best zero-data lever, and it hits a ceiling.**
   - LMArena ratings lift Gemini 2.5 Flash on HUMAINE overall choice from 23.2 to 39.5.
   - The share of pairs with a clear winner that Gemini calls right rises from 52.7% to 84.3%.
   - What remains is a mismatch between the two populations. Arena voters and HUMAINE's UK/US panel rank models differently: Spearman 0.735, worst on reasoning-heavy models.
3. **The biggest single error is how often people say "no difference", and no public dataset carries that number.**
   - HUMAINE tie rates by dimension:

     | Dimension | Tie rate |
     |---|---|
     | Overall | 11% |
     | Communication style | 19% |
     | Fluidity | 32% |
     | Core task | 38% |
     | Trust | 66% |

   - Gemini predicts about 20% ties everywhere, so it scores below zero on reasons.
   - Outside tie rates and SimBench-fitted calibration each help one dimension and hurt another.
   - A 50-person pilot recovers almost all of what knowing the true tie rate is worth: 45.2 vs 45.4.
4. **The literature points the same way:**
   - Retrieved human evidence beats fine-tuning on new questions.
   - Elicitation format and nonlinear calibration fix most of the distortion in simulated distributions.
   - Small supervised heads beat frontier models only on a fixed instrument with new items. That is our P2 and P3 situation, not P1.
   - Demographic personas add little.
   - No open tool combines an evidence registry, calibrated distributions, honest intervals with or without customer data, abstention, a human-budget planner and a forecast ledger. That combination is the product.
5. **Therefore:**
   - **FREE:** build the harness and a pre-registered, reproducible result on four benchmarks.
   - **Experimental ($200 a month):** buy the cheapest real data that our measurements say pays most per dollar, starting with small pilots in the target population and first-impression panels.
   - **Incremental ($2,000 a month):** scale whichever arm proves out into a linked panel and a calibration bank that compounds with every study.

## 2. Where we stand (measured, no in-dataset tuning)

**SimBench (P1)**
- 41.46 → 55.80 [55.08, 56.50] with no labels from the target dataset (leave one dataset out).
- 59.68 [59.10, 60.25] with small cognitive models, cross-fitted on each dataset.
- 62.49 after tuning on the benchmark itself. This number is optimistic and is never shown next to the first two.
- Calibration labels from the target population break even at about 25 labels and level off near +2 S at 100-200.
- Gemini 2.5 Flash zero-shot scores 33.2 on the evaluation sample.

**Twin-2K-500 (P1, person level; 40 pricing items held out as a block)**
- Reasons axes built from a person's other answers beat demographics:

  | Predictor | TVD |
  |---|---|
  | Anchor | 0.4905 |
  | Best demographic attribute | 0.4895 |
  | Reasons axes | 0.4802 |

- Axes predict group gaps far better than attributes: correlation 0.44 vs 0.10.
- Segments are not stable (ARI 0.39).
- Lesson: profiles explain who differs and why. They barely move population numbers.

**HUMAINE (P4 overall choice plus four reasons; 4,355 product-pair × segment cells; ceiling 71.8)**

The ladder is published on the Data Lever Board.

| Step | Track | Overall S | Reasons S |
|---|---|---|---|
| Gemini 2.5 Flash, product names only | zero-data | 23.2 | −23.2 |
| + OpenRouter listing (description, date, price) | zero-data | 22.6 | −24.7 |
| + LMArena ratings in the prompt | zero-data | 39.5 | −29.6 |
| + arena tie share (pre-registered 27.5%) | zero-data | 20.8 | −2.6 |
| + arena "tie" share (15.9%) + SimBench temperature | zero-data, post hoc | 44.4 | −29.9 |
| + 50-person pilot: tie share and confidence | pilot | 45.2 | 23.5 |
| + 50-person pilot as evidence (arena prior updated by pilot votes) | pilot | 47.6 | 25.7 |
| + 400-person pilot as evidence | pilot | 53.6 | 35.4 |
| Yardstick: Bradley-Terry on all other HUMAINE pairs | in-dataset | 66.9 | — |

**Diagnostics** (these use HUMAINE answers, so they only show where the gap is):
- Knowing the true tie share takes Gemini + arena to 45.4 overall and 28.0 on reasons.
- Knowing who wins each cell takes it to 72.6 overall.
- So on overall choice, *who wins* is the remaining lever. On reasons, *how often people see no difference* is the lever.

**HUMAINE goal-achievement score (P3)**
- Gemini scores 26.9 against a ceiling of 89.8.
- Arena ratings make it worse (14.6): the model is too pessimistic, with a mean predicted score of 3.4-3.6 against a real 4.3.
- Caveat: these labels come from a GPT-4.1 judge, not from users (HUMAINE paper, arXiv 2603.04409). We treat P3 on HUMAINE as a weak signal.

**What the tests say about data, across benchmarks:**

| Data | Lever | Measured effect | Verdict |
|---|---|---|---|
| Pilot from the target population | calibration + evidence | SimBench +2 (100-200 labels); HUMAINE +8.1 overall / +55 reasons (50 people), +14.1 / +65 (400) | Strongest; most value by 50-100 people, evidence keeps paying beyond |
| Same question, other populations | evidence | SimBench +14.3 | Core of P1 |
| Public ratings of the same products by another crowd | context | HUMAINE +16.3 overall, −6.4 reasons | Best zero-data lever for P4; needs tie calibration |
| Outside tie rates (arena votes) | prior | +3.1 or −18.8 overall depending on mapping | Protocol-specific; one rate cannot serve all dimensions |
| Calibration fitted on another benchmark | calibration | HUMAINE −1.9 overall, +10.8 reasons | Transfers only between similar answer formats |
| A person's earlier answers | profiles | Twin-2K TVD −0.0103 vs anchor; gap correlation 0.44 | Explains differences; small population effect |
| Product listings and metadata | context | HUMAINE −0.6 | No help for known products |
| Demographics alone | profiles | Twin-2K TVD −0.0010 | Weak |

## 3. What published work says (highest-lever findings)

Full notes, with every source and what was verified, are in three research reports. The main points:

- **Evidence over weights.**
  - Evi-DA (Findings ACL 2026): removing retrieved survey evidence nearly doubles error on new domains (JSD 0.23 → 0.44), and the untrained pipeline scores nearly as well as the trained one.
  - Meister et al. (NAACL 2025, arXiv 2411.05403): written-out distributions beat log-probabilities, and showing the group's answers on similar questions helps every strong model.
  - Park et al. (arXiv 2411.10109): agents built from a person's survey or interview answers reach 82-86% of test-retest accuracy, against 74% from demographics.
- **Elicitation and calibration fix the shape.**
  - Pairwise questions lift directional A/B accuracy from 0.40 to 0.75 (Amazon, arXiv 2609.01038).
  - Semantic-similarity rating raises the KS similarity of Likert distributions from 0.26 to 0.88 (arXiv 2510.08338).
  - Raw LLM answers recover only 39% of the human A/B effect. Tree-based calibration brings it within sampling error, while linear calibration fails (Spotify, arXiv 2606.17165).
- **Honest uncertainty without customer data.**
  - Task-exchangeability intervals widen the synthetic interval by the gaps seen on past tasks: 97% coverage on ANES against 3% for naive intervals (Tan & Zrnic, arXiv 2606.13629).
  - GPT-4o is worth about 58 human respondents on OpinionQA (Huang et al., arXiv 2502.17773).
- **Spend humans where the simulator is weakest.** Allocating labels by predicted difficulty cuts error 10.5-11.4% at equal budget, against 1.5-3.6% for uniform PPI++ (Ye & Yoganarasimhan, arXiv 2604.17267).
- **Pairing humans with simulated twins** (PPI, AIPW) mainly buys validity: effective sample rises about 13-14% (Hullman et al., arXiv 2602.15785).
- **Fine-tuning wins on a fixed instrument with new items** (P2 and P3), not on new questions:

  | Model | Task | Fine-tuned | Best frontier baseline |
  |---|---|---|---|
  | UIClip (arXiv 2404.12500) | Designer pairwise quality | 75.1% | GPT-4V 51.6% |
  | DesignSense (arXiv 2602.23438) | Layout preference, 4-way | 0.519 | 0.385 |
  | LOLA (arXiv 2406.02611) | Held-out Upworthy tests | 46.9% | GPT-4 38-40% (random 33%) |

- **Prompted agents over-cooperate, and human traces fix them.**
  - Add-to-cart rate: 80% for prompted agents against 16% for real users.
  - Training on OPeRA traces lifts next-action accuracy from 9.5% to 44.6% (arXiv 2510.19245).
  - Session-level rewards bring the action mix close to humans (RecVerse, arXiv 2608.20707).
  - UserLM-8b (MIT licence) ends conversations the way people do (arXiv 2510.06552).
- **Demographics add little per decision. Aggregates work; individuals do not.**
  - PRISM-X (arXiv 2605.13307): aggregate r = 0.98-0.99; individual τ = 0.11-0.22, against human self-consistency of 0.57.
  - On HUMAINE, an age-specific model does not beat a pooled one per vote.
  - Generic personas match detailed ones (Kuric et al., arXiv 2605.18311).
- **Zero-shot prediction of A/B winners is near chance.**
  - WiserUI-Bench consistent accuracy: 34.6% against 25% random.
  - Squoosh: κ = 0.14 on 330 tests.
  - So verdicts must depend on the size of the predicted gap, run in both presentation orders, and be allowed to abstain.
- **Positioning.**
  - Simulators (EDSL, TinyTroupe) generate answers but do not correct them.
  - Statistics libraries (ppi_py) correct them but do not retrieve evidence.
  - Persona MCP servers (Althing, Minds) serve personas with no validation.
  - The missing middle layer is ours.
  - Note: a NeurIPS 2026 workshop is also called "UserSim" (12 Dec 2026). It could be a partner, and it creates a naming conflict.

## 4. The infrastructure we are building

One harness, exposed as an open-source library and an MCP server. Each component has a benchmark that measures it.

| # | Component | What it does | Measured by | Stage |
|---|---|---|---|---|
| 0 | Data registry, leakage guard, licence gate | Provenance, dates relative to model cutoffs, population-overlap rule, dedup, NC data blocked from commercial paths | Every benchmark (prerequisite) | FREE |
| 1 | Evidence retrieval | Same question from neighbouring segments; same segment on related questions; public ratings of the same products; the customer's past tests | SimBench, HUMAINE, PRISM | FREE |
| 2 | Distribution reader | Frontier model writes out distributions; pairwise in both orders; predicted gap and abstain | All | FREE |
| 3 | Protocol priors and calibration bank | Tie and neutral share, spread and scale use per answer format; learned from public pairwise and survey data, then updated by pilots | HUMAINE reasons, SimBench | FREE → Experimental |
| 4 | Reliability model | Predicts error from evidence support, disagreement between sources, entropy and embeddings; routes or abstains | SimBench (leave one dataset out), HUMAINE | FREE |
| 5 | Small-data rectification | A pilot used as calibration and as evidence; PPI++ or AIPW intervals; zero-data task-exchangeability intervals | HUMAINE pilot track, Twin-2K | FREE → Experimental |
| 6 | Human-budget planner | How many people, which questions, which segments; square-root allocation by predicted difficulty | Simulated on Twin-2K and SimBench, then live | Experimental |
| 7 | Forecast ledger | Every prediction pre-registered with a timestamp; outcomes imported; rolling coverage | Show HN live, monthly polls | FREE onward |
| 8 | Fixed-instrument heads | P2 appeal and trust head; P3 behaviour critic trained on human traces | P2-Bench, OPeRA | FREE (public data) → Incremental (own data) |

**The flywheel:**
1. Every study a customer or we run lands in the ledger.
2. Its outcomes feed the calibration bank (component 3) and the evidence index (component 1).
3. Better priors mean fewer labels for the next customer.

The metric for the flywheel is **labels needed to reach a target S, falling month over month**.

## 5. Benchmarks as markers

| Benchmark | Stage | Now | FREE exit target | Experimental target |
|---|---|---|---|---|
| SimBench, zero target labels | P1 | 55.8 | ≥ 57 with intervals covering within ±3 pt of nominal | Monthly fresh polls tracked |
| Twin-2K-500, held-out blocks | P1 | axes −0.0103 TVD vs anchor | Rectifier bake-off picks a default; segments stable (ARI ≥ 0.6) or dropped | — |
| HUMAINE overall, zero-data, pre-registered | P4 | 39.5 | ≥ 45 with no post hoc choices | — |
| HUMAINE reasons, zero-data | P4 | −29.6 | ≥ 0 | — |
| HUMAINE + 50-person pilot | P4 | 47.6 / 25.7 | ≥ 50 / ≥ 30 | Replicated on our own protocol |
| PRISM (first impression → choice) | P2, P4 | not run | Baseline and pilot curve | — |
| P2-Bench v0 (public rated screenshots, split by site) | P2 | not built | Head ≥ +0.10 ρ over frontier | Own panel replaces public data |
| Upworthy | P2 | not run | ≥ 90% of the human effect recovered | — |
| OPeRA | P3 | not run | Action mix within ±25% of humans | — |
| Live Show HN forecasts | P2, P4 | not run | One scored round, beats base rate | Monthly rounds |

## 6. Stage 1: FREE (now, until results are consistent and publishable)

**Rule:** no paid data. GCP, model calls, fine-tuning and training are free. Every number is pre-registered before it is scored and reproducible with one command.

Work, in order of leverage:

| ID | Work | Why | Done when |
|---|---|---|---|
| F1 | Harness core: registry, leakage guard, licence gate, three tracks (zero-data / pilot / in-dataset), ledger | Every claim depends on it | Every result file carries track, sources and timestamp; NC sources cannot reach commercial code paths |
| F2 | HUMAINE zero-data, pre-registered | Remove the post hoc tie choice; fix reasons | Single re-score of four fixed changes, against the 39.5 / −29.6 baseline. Target: reasons ≥ 0, overall ≥ 45 |
| F3 | Pilot curve as a product feature ("how many of your users do you need") | The strongest lever we measured | Curves for SimBench, Twin-2K and HUMAINE with the same code path; published |
| F4 | Zero-data intervals (task exchangeability) | Honest uncertainty before any customer data | Coverage within ±3 pt of nominal 80/90% across held-out SimBench datasets |
| F5 | Reliability model | Abstain where we would be wrong; drives the planner | AUROC ≥ 0.72 for "error below threshold", leaving one dataset out |
| F6 | P2-Bench v0 from public rated screenshots (Miniukovich & Figl, UICrit, BetterApp, WiserUI), split by site | P2 is weighted 2.5 and has no measured result yet | Frontier zero-shot vs pairwise vs frozen-embedding head vs QLoRA 8B |
| F7 | Upworthy calibration stack (Spotify replication) | Calibration for A/B predictions | ≥ 90% effect recovery on held-out tests; interval coverage ≥ 93% |
| F8 | P3 cooperativeness audit against OPeRA, then a small behaviour critic | Our agents likely over-convert | Action mix within ±25% of humans |
| F9 | Live ledger: weekly Show HN forecasts (open); Product Hunt as an open benchmark only | The only test that cannot be memorised | Four scored weekly rounds |
| F10 | Paper and release: "Predicting users with little or no data: four benchmarks, three tracks", plus the open-source harness and MCP | Publishable before paying | arXiv draft; one command reproduces each table |

F2 makes four fixed changes:
1. An arena prior blending raw and category ratings with weights set in advance.
2. Per-dimension tie priors from outside pairwise data (HelpSteer equal-rating shares, MT-Bench, PRISM near-ties).
3. A reasoning-model and latency adjustment derived from SEAL and arena data.
4. Segment offsets from PRISM and Community Alignment.

**Exit gate** (all must hold before spending on data):
1. The zero-data harness beats the plain model with CI above zero on at least 3 benchmarks, pre-registered.
2. Pilot curves exist on at least 2 benchmarks.
3. Zero-data intervals have measured coverage.
4. One live forecasting round has been scored.
5. Every table reproduces from the repository.

## 7. Stage 2: Experimental (about $200 a month)

**Goal:** find which paid data gives the largest gain per dollar. Each arm is pre-registered with a scale-or-kill rule.

**Costs** (Prolific, 2026):
- Participants are paid $12/hour (the recommended rate), and Prolific adds a 42.8% corporate fee.
- A 10-minute session costs about $2.86; a 15-minute session about $4.28.
- A HUMAINE-style comparison takes about 10-15 minutes, so 50 cost $140-215. That is one month of this stage.

| Arm | What we buy | Monthly cost | Tests | Scale if |
|---|---|---|---|---|
| X1 Pilot calibration on our own protocol | 50-70 blind side-by-side sessions on startup-like product pairs | ≈ $200 | Does the HUMAINE pilot curve replicate outside HUMAINE? | ≥ +5 S over zero-data at 50 people, CI above zero |
| X2 First-impression panel | ≈ 70 ten-minute sessions: ≈ 1,750 ratings of post-cutoff startup pages (500 ms and 5 s exposure), 4 items, pairwise in both orders | ≈ $200 | Zero-data P2 vs a real panel; seeds the P2 head | ρ ≥ 0.6 on appeal and trust after 3 months |
| X3 Task pair study | ≈ 46 fifteen-minute within-subject sessions every third month: same task on the startup and a competitor, verified success, ease, preference | ≈ $200 per quarter | P3 calibration by difficulty band | Completion-rate error ≤ 15 pt |
| X4 Segment shift | Anchor in segment A, predict segment B, against a direct sample of 50 | ≈ $200 once | Can one cheap segment calibrate another? | Shifted anchor matches the direct sample |

**Order:** X1 first, because it is the lever we measured. Then X2 and X1 alternate monthly, and X3 runs every quarter.

**Decision after three months:** compute ΔS per $100, with CIs, for every arm, and graduate the best one or two.

**Quality control on every study:**
- 10-15% duplicate items with a rate-rerate exclusion rule.
- A recognition test.
- Minimum time on task.
- Prolific authenticity checks. Plain attention checks are not enough, because LLM agents pass them.

## 8. Stage 3: Incremental (about $2,000 a month)

**Goal:** compounding. Spend only on directions that passed Stage 2.

| Item | Monthly | Produces |
|---|---|---|
| I1 Linked panel: the same people answer a profile survey (P1), see first impressions (P2), attempt tasks (P3) and then choose (P4) | ≈ $750-1,000 | The proprietary dataset no one else has; segment offsets with real stability tests |
| I2 P2 at scale (≈ 260 sessions, ≈ 6,500 ratings) | ≈ $750 | Training data for our own P2 head (target +0.10 ρ over frontier by segment) |
| I3 P3 benchmark (≈ 5 product pairs × ≈ 46 people) | ≈ $1,000 (alternates with I2) | Calibration of predicted success and post-use preference |
| I4 Budget-planner trial: uniform vs difficulty-based allocation, randomised | inside I1-I3 | ≥ 10% lower error at equal spend |
| I5 Customer calibration ladder: consented A/B logs and outcomes, switched on after 25 outcomes and a half-split check | free per customer | The flywheel's main input |

## 9. Research directions, ranked by lever

| Area | Highest-lever next step | Evidence | Stage |
|---|---|---|---|
| Data | Target-population pilots (calibration and evidence); then a linked panel | Our HUMAINE pilot curve; SimBench calibration | Experimental → Incremental |
| Data (free) | Public ratings of the same products by another crowd; per-format tie and neutral priors from public pairwise data; fresh post-cutoff polls | +16.3 (arena); tie diagnostics; Tan & Zrnic | FREE |
| Harness | Evidence retrieval sweep; protocol priors; reliability model with abstention; zero-data intervals; planner | Evi-DA; Meister; Simile confidence AUROC 0.69-0.74; Ye & Yoganarasimhan | FREE |
| Elicitation | Pairwise in both orders; semantic-similarity rating for Likert; gap-aware verdicts | Amazon 0.40 → 0.75; SSR 0.26 → 0.88; WiserUI position bias | FREE |
| Fine-tuning | Only for fixed instruments with new items: P2 head (frozen embedding, then QLoRA 8B with a distribution loss) and P3 behaviour critic (OPeRA SFT + session reward). Not for P1 new questions | UIClip, DesignSense, PerceptUI, LOLA; See-Think-Act, RecVerse | FREE (public data) |
| Model research | Learn the platform shift (style, length, latency, reasoning) between crowds so public ratings transfer to a target population | Arena → HUMAINE ρ 0.735; reasoning models are the biggest misses | FREE |
| Usability studies | Verified-success task studies with pre-use first impressions; think-aloud for reasons (Userbrain, about $249 a month for 10) | NN/g sample sizes; Lost in Simulation | Experimental → Incremental |

## 10. Risks and guards

- **Leakage and memorisation.**
  - Benchmark rows never tune a method.
  - HUMAINE products are known to models. Claims about unknown startups need post-cutoff products: Show HN, our own panel.
- **Post hoc choices.** H4/H8 on the Data Lever Board include a choice made after scoring. F2 re-runs them pre-registered.
- **HUMAINE caveats.**
  - Goal-achievement labels come from an LLM judge.
  - Matchmaking ran separately in each stratum, so segments are compared only on shared pairs.
  - Model identity can leak through style ("blind-ish").
- **Licences.**
  - Non-commercial data (SimBench, PRISM model responses, WVS, Product Hunt) stays in the research track and the open benchmark.
  - Twin-2K, Upworthy, OPeRA, LMArena and Community Alignment are CC BY.
- **Panel fraud.** Authenticity checks, duplicates and recognition tests on every paid study.
- **Naming.** The NeurIPS 2026 "UserSim" workshop overlaps our name. Decide whether to partner or rename before release.

## Sources

- **Our results:** `results/humaine/scores.json`, `results/humaine/transfer.json`, `results/popadapt/cards_twin.json`, `docs/plans/usersim_direction_2026-10.md`.
- **Research reports (2026-10-10):** three literature sweeps, with sources opened and unverified items marked:
  - `docs/research/2026-10-10_preference_prediction_by_segment.md`
  - `docs/research/2026-10-10_data_curation_calibration.md`
  - `docs/research/2026-10-10_models_finetuning_usability.md`
- **Key papers:** HUMAINE 2603.04409; Evi-DA (Findings ACL 2026); Meister et al. 2411.05403; Park et al. 2411.10109; Tan & Zrnic 2606.13629; Huang et al. 2502.17773; Ye & Yoganarasimhan 2604.17267; Hullman et al. 2602.15785; Spotify 2606.17165; Amazon persona A/B 2609.01038; SSR 2510.08338; UIClip 2404.12500; DesignSense 2602.23438; LOLA 2406.02611; See-Think-Act 2510.19245; RecVerse 2608.20707; UserLM 2510.06552; PRISM 2404.16019; PRISM-X 2605.13307; Kuric et al. 2605.18311; WiserUI-Bench 2505.05026.
