# UserSim direction: fine-tuning and what data to collect

Date: 2026-10-08. Built from a research workflow: local repo evidence, four web sweeps with adversarial fact-checks (47 decision-critical claims checked: 37 confirmed, 10 corrected, 0 refuted), a quantitative analysis on our SimBench components, a synthesis and an independent critique. Raw outputs: `scratchpad/direction/` in the session (analysis scripts `q1.py`..`q4b.py`, `q*.json`).

Source tags: **[W#]** web source confirmed or corrected by the fact-check (corrected text used); **[U#]** not verified, always labelled; **[L#]** our repo or analysis; "judgment" = reasoning, not a sourced fact.

---

## 0. Bottom line

**Q1. Can we build a fine-tuned model that matches or beats frontier models?**
Not as a general simulator, and not this quarter. No published fine-tune beats current frontier models on held-out *instruments* across a broad benchmark. The best-documented 2026 attempt, OSim-8B (21.4M interactions), averages 64.6 against 64.8 to 65.5 for Gemini 3.1 Pro, GPT 5.5 and Claude Opus 4.7 [W5]. Fine-tunes do win in narrow settings: instruments seen in training with new people (Be.FM on BehaviorBench's distributional board [W2]), and step-level web behaviour trained on the same site's traces (Customer-R1 39.6% vs 7.3% prompted on OPeRA [W11]). Two fine-tunes are worth testing, both cheap: (e) narrow supervised predictors per use case trained on outcomes, and (c) an evidence-reading model, but only if prompted Sonnet given the same evidence leaves room.

**Q2. What data should we collect?**
The intersection of "data available", "can be evaluated" and "customers pay for it" is, in order:
1. **Message, headline and copy A/B outcomes** (Upworthy 32,487 randomized tests, CC BY [W14]; customers' own past tests).
2. **Concept and purchase-intent tests** (cheap to field on Prolific, measurable noise ceiling, a core synthetic-research purchase).
3. **Funnel drop-off distributions** (OPeRA and ShopCART public; our browser agents already produce the simulated side).

**The finding that should shape the product.** On SimBench, the human answer from a neighbouring population carries almost all the signal. Where a well-sampled same-question anchor exists, the anchor alone scores 77.6 and anchor plus model 77.5 to 78.0 [L2]. The model's value is (a) when there is no anchor, (b) shrinking *small* anchors (50 to 100 people), and (c) shifting an anchor to a different segment. So the product should be built around a cheap human anchor plus a model, with a public track record, not around persona prose.

**Product honesty.** `would_convert`, `segment_fit_score`, buyer picks and head-to-head winners have never been compared with human behaviour [L5]. Caveat or hide them until a study validates them.

---

## 1. Where we stand (corrected numbers)

A leak was found and fixed this week. The label prior counted answers to the *same question* from populations that overlap the target (the country total, other cuts of the same country), which breaks our overlap rule. Fix: commit `d104bc8`. Results regenerated in the follow-up commit.

| Number | What it is | Comparable to the SimBench leaderboard? |
|---|---|---|
| **41.46** | Haiku 4.5 with retrieval of similar solved questions (`retr6_rev2`), full 13,510 [L1] | No. Retrieval demos are other rows' human answers. Closest zero-shot arm: about 33 on the eval sample |
| **55.80** [55.08, 56.50] | No labels from the target dataset anywhere: evidence weights per source type transferred from the other 19 datasets [L2] | No (uses other rows' human answers), but the cleanest held-out number we have |
| **59.68** [59.10, 60.25] | Adds the small cognitive models (Choices13k, NumberGame, MoralMachine), cross-fitted on each dataset's own labels [L2] | No |
| **62.49** | Full pipeline after the leak fix: rule (59.89) plus 8 cross-validated tuning rounds, developed on the benchmark itself, so optimistic (was 62.86 before the fix) | No, and never to be placed next to the two rows above |
| 40.80 | Best published SimBench score (Claude 3.7 Sonnet; no 2026 models in the table). Centaur-70B 8.54, Minitaur-8B 14.50 [W1] | This is the leaderboard |

Where the +21 comes from (pre-fix decomposition, shares hold after it) [L2]: same-question answers from other populations about 69%, cognitive models trained on the instrument's labels about 19%, base rates and calibration about 12%.

---

## 2. Q1: fine-tuning

### 2.1 Why fine-tunes have not beaten frontier models

1. **Benchmarks like SimBench hold out instruments; fine-tunes learn instruments.** Small models match Centaur-70B on held-out *participants*, but on held-out *experiments* scale still wins, and 75.7% of what they learn sits in stimulus and feedback content [W8]. Be.FM's lead on BehaviorBench is on instruments it saw in training; on the one fully held-out game, Socrates-DPO is best [W3]. OSim's biggest wins are on tasks with native training splits [W5].
2. **On unseen questions, simulation tracks general capability.** SimBench scores rise log-linearly with model size and correlate r = 0.939 with MMLU-Pro [W1]. In our own harness the model tier alone (Haiku to Sonnet 5.5) is worth +12.5 on the eval sample [L1]. An 8 to 70B fine-tune starts below the frontier.
3. **Behavioural fine-tuning mostly fixes spread; our remaining error is order.** Behaviour FMs reproduce human spread better (Centaur SD 0.93 of human vs 0.53 to 0.70 for frontier models sampling one respondent at a time) [W3]. When frontier models write out the distribution instead, they win back about half of that gap [W4]. Our pipeline already writes out distributions, and on divided questions the residual error is option ranking (about 43%) and heights (about 42%) [L1]. Training to human data can also collapse spread (a distribution-shaped GRPO reward kept 0.21 of human dispersion) [W10].
4. **The answer to an unseen question is mostly not in any weights.** 69% of our lift is other populations' answers to this question. Across all datasets, labels from the target domain are worth about +6.7 (62.5 vs 55.8): +3.9 through cognitive models trained on them, +2.8 through in-domain tuning [L2].
5. **"Beats frontier" claims use weak baselines.** Socrates beats GPT-4o few-shot only 0.151 vs 0.161 Wasserstein, and GPT-4o is the only closed model compared [W6]. A GPT-4.1 fine-tuned on Twin-2K-500 did not significantly beat prompted GPT-4.1 [W7].

### 2.2 The options

| Option | What it is | Verdict | Cheapest decisive test |
|---|---|---|---|
| (a) General behaviour FM (Centaur, OSim, Simile's model) | Mid-train on millions of human responses | **Do not build.** Ties at best [W5]; wins only in-distribution. Compute is cheap (judgment: about $1k per 8B run), but data, licences and eval are not, and Simile has raised more than $300M for this [W29] | Run the public OSim-8B / OSim-4B (MIT) and Socrates-14B on SimBench and our backtests: one GPU, tens of dollars (judgment) |
| (b) Distribution-calibrated fine-tune (KL / TVD / GRPO losses) | Train to output human-like spread | **Not for us now.** Helps against open baselines; not shown against frontier; can collapse dispersion [W10] | Only if customers need respondent-level microdata |
| (c) Evidence-reading simulator | Train a model to read retrieved human answers (other groups, countries, past tests) and output the target distribution | **Plausible, unproven, small headroom.** Realistic headroom over one weight per source type is +1.1 (best fixed weight per dataset and source) to +2.7 (in-domain tuning), almost all on country-level, within-country-gap and other-country questions (5,146 questions); none on same-question subgroup questions [L2]. Simple learners on meta-features *lose* 0.65 [L2]. Closest published analogues (Evi-DA, Distribution Shift Alignment) report gains only against open baselines [U3] | Prompted Sonnet 5.5 *with the same evidence*, leave-one-dataset-out on those 5,146 questions, paired against the transferred hand rule. If Sonnet beats the rule by 1 or more, use prompted Sonnet and close (c). Only if not, pilot an 8B reader that must beat both by 1 or more with CI above 0 |
| (d) Per-customer calibration | Isotonic, tree or AIPW correction from model output to the customer's outcomes | **A layer, not a model.** It is how published single-domain tests recover real effects: Spotify brings a raw 39% effect recovery to within sampling error [W15]; AIPW with 50 to 300 humans cuts bias 93 to 99.6% [W22]. But effective-sample gains are modest (14% or less [W9]) and it fails with poor population overlap [W22]. In our data, calibration breaks even at about 25 labels (+0.6 [0.2, 1.1], still worse than no correction in 40% of draws) and levels off near +2 at 100 to 200 [L2] | Built into the product (section 4.5) |
| (e) Narrow supervised predictor per use case | Embeddings plus regression or GBM, or a small LoRA, trained on owned or public outcomes | **Test now.** Our cognitive models add +37 S on 1,416 questions [L2]. On Upworthy, embeddings plus regression (46.3%) about equal a LoRA 8B (46.9%), against GPT-4 two-shot 40.0% and random 33.0% (LOLA, unverified [U9]). Customer-R1 and Shop-R1 beat prompting 5x on OPeRA [W11] | Upworthy and OPeRA backtests, gated against prompted Sonnet 5.5 on held-out tests. Days, under $100 |

**Licence gate for any training.** SimBench is CC BY-NC-SA and contains WVS and other restricted surveys [U29]; BehaviorBench is CC BY-NC-ND [U29]. A commercial model cannot be trained on them. Commercially usable: Twin-2K-500 (CC BY) [W21], Upworthy (CC BY) [W14], Psych-101 train (Apache-2.0). Ask about SocSci210 and Pew.

**What would change the verdict on (a).** An open fine-tune beating Opus 5 / Gemini 3.1 Pro / GPT 5.5 on held-out instruments with intervals above zero, or us owning millions of predict-then-observe items.

---

## 3. Q2: the data intersection

### 3.1 Matrix

Scores 0 to 3. Data: 3 = public and licensable, or cheap at scale. Eval: 3 = held-out ground truth with a measurable noise ceiling. Value: 3 = UserSim's buyers (product, growth, marketing) pay for this today (partly judgment).

| # | Use case | Data | Eval | Value | Notes |
|---|---|---|---|---|---|
| 1 | Population attitude surveys | 3: Twin-2K CC BY [W21]; Pew ATP, GSS free (Pew forbids resale [U29]); Prolific representative samples [W34] | 3: retest ceiling 81.7% [W21]; wave-to-wave floor 2.3 to 12 TVD [W31] | 2: insights buyers; a $2B incumbent there [W29] | Accuracy today: frontier personas miss toplines by 12 to 20pp (Pew, Opus 4.6: 12.4pp, 28% of questions off by 15pp or more [U1, verified by the critic]; GPT-5.2 14.5pp [W24]; GPT-5 19.8pp on consumer questions [W25]). **Use as the free eval substrate** |
| 2 | Subgroup attitudes | 2 | 2: only 1.4% of divided-question disagreement is between groups [L1] | 2 | Haiku 4.5 / Sonnet 4.6 do not beat a demographic lookup on GSS [W26]; Pew subgroup error 13.6 to 16.1pp [U1]. Not picked |
| 3 | **Message / headline / copy A/B** | 3: Upworthy 32,487 tests, CC BY (7,004 flagged) [W14]; customers' past tests | 3: randomized outcomes with SE; Spotify's falsification test [W15][W16] | 3: core synthetic-research purchase; EY-Aaru alliance for message and offer testing (unverified [U30]) | **Picked.** Raw LLM recovers 39% of the effect; calibrated, within sampling error [W15]. Risks: 2013-15 news headlines likely in pretraining (add a memorization check); LLMs produce "significant" effects where humans find none in 68 to 83% of cases [U31], so winner calls need an abstain option; do not extend to visual creative [U32] |
| 4 | Landing-page / UI A/B | 1: WiserUI-Bench 300 pairs, non-commercial [W17] | 2: base rates dominate (76% variant wins) [W18] | 3 | Frontier VLMs 30 to 35% vs 25% random [W17]; judge kappa 0.14 [W18]. Customers' tests flow into row 3's ledger anyway |
| 5 | **Concept test / purchase intent** | 2: no public corpus; about $3 per 10-min Prolific respondent [W34] | 3: concept ranks against split-half and retest ceilings | 3: core synthetic-panel product; incumbents (Qualtrics, NIQ BASES) already sell it, so differentiation must be a published track record | **Picked.** SSR elicitation reaches about 90% of test-retest; direct Likert already about 80% on ranks, SSR's gain is mostly distribution shape; one vendor study, personal care only [W20] |
| 6 | Willingness to pay / pricing | 2: Twin-2K pricing tasks [W21] | 2: stated is not paid | 3 | LLM WTP differed from incentive-compatible BDM in 4 of 4 studies (unverified [U33]). Keep only as a backtest |
| 7 | Usability / task completion on live sites | 2: we already produce traces [L6] | 1: no public issue-recall benchmark; our judges are unaudited [L5] | 3: today's product | Simulated users too cooperative (agent success 77.8% vs 63.6% with people) [W19]; 6 actions per session vs 16 for humans [W28]. Fix evaluability with study #2 before claims |
| 8 | **Funnel drop-off / next action** | 2: OPeRA 692 sessions [W12]; ShopCART 31,865 sessions, no licence tag [W13] | 3: public test splits; our spec's split-half ceiling S 65.9 [L5] (never run) | 3 | **Picked for product fit.** Score aggregate distributions, not single next actions (prompted 7 to 22% [W12][W13]). Expect drop-off under-predicted: simulated non-buyers voice resistance half as often as real ones [U34]; Shopify's agents fell to chance without archetypes mined from the shop's own clickstream [W27] |
| 9 | Ratings and reviews | 2: Amazon Reviews'23, licence unclear [U18] | 2 | 1: customers already have their reviews | Not picked |
| 10 | Feature prioritization | 1: collectible as MaxDiff | 2: rank vs split-half (a design, not a benchmark) | 3 | Not picked yet; candidate for the weekly panel |
| 11 | Churn / retention reasons | 0 | 1 | 3 | Lives in customers' CRMs |
| 12 | Survey-experiment effects | 2: 70 experiments / 469 effects [W23]; SocSci210 2.9M responses [W6] | 3: effects with SE plus forecaster baselines [W23] | 2 | r = 0.85 but magnitudes about 2x too large; r = 0.39 on megastudies [W23]. Free predict-then-observe set; folds into row 3 |
| 13 | Qualitative reactions and objections | 2: UICrit CC BY | 2: human critiques 0.75 vs best LLM 0.54 (PerceptUI, unverified [U35]) | 3: what the MVP and interview vendors sell | Gap a buyer will ask about |
| 14 | B2B positioning, hard-to-reach audiences | 0 to 1 | 1 | 3 | Where synthetic research has the biggest cost edge; nothing to validate against |

### 3.2 The three picks and how they connect to what we learned on SimBench

| SimBench lever [L2] | Product equivalent |
|---|---|
| Same question answered by other populations (+14.7 of the 21) | The same stimulus rated by 50 to 100 real respondents (general population or a screened pool), plus a model that shrinks the small sample and shifts it to the target segment. Report ESS/N for every anchor-to-segment shift and abstain below 0.01 [W22] |
| Retrieval of similar solved items (+8 to 10) | The customer's past tests and our ledger of past stimuli with outcomes |
| Base rates (+2.5) | Category base rates: variant win rate, typical intent distribution per category |
| Per-domain calibration (+2 at 100 or more labels) | Per-customer calibration after 25 or more outcomes, switched on only if a half-split check passes (cuts bad switches at k=5 from 63% to 22%) [L2] |

---

## 4. Plan

All costs are proposals. Anything that spends money needs your approval.

### 4.1 Next two weeks

1. **Record.** Report the three-tier headline (55.80 / 59.68 / 62.49). Mark `results/fm_baselines/STATUS.md` and the targets in `docs/plans/beat_behavior_fms.md` stale (BehaviorBench v2 drops Be.FM from its main comparison; Centaur is 8.54) [W3].
2. **$0 simulation before any fielding.** Resample the same-question evidence on SimBench as n = 50 and n = 100 multinomial draws, blend with the logged Haiku and Sonnet predictions, compare with the anchor alone. This predicts whether "model + 50 humans" beats "50 humans" and sets study #1's threshold.
3. **Frontier check for option (c).** Sonnet 5.5 *with evidence in context* on the 5,146 country-level, within-country-gap and other-country questions, leave-one-dataset-out, batch API and caching. Pilot 200 questions to measure tokens first (judgment: tens of dollars for the pilot, low hundreds for the run).
4. **Public backtests, with gates:**
   - Upworthy: drop flagged tests; exploratory for development, confirmatory for evaluation, holdout untouched. Replicate Spotify's setup [W15]. Sell effect sizes only if the calibrated estimate is within 2 SE on the holdout and winner accuracy beats both the base rate and an embedding-plus-logistic baseline; otherwise sell "pre-screen only".
   - OPeRA cold start: run the LLM arms of the existing spec. GO if S beats counting (3.9) with CI above 0 and reaches half of the 65.9 ceiling (judgment).
   - Twin-2K pricing: our blend vs AIPW at n = 50 to 300.
   - Free predict-then-observe sets: Twin-2K's 19 mega-study studies [W7] and the 70-experiment archive [W23].
   - Run public OSim-8B / OSim-4B and Socrates-14B on the same backtests.
5. **Judge audit for $0.** Score our task-completion judge against Online-Mind2Web's human labels (300 tasks, 136 sites), then two people label 200 of our runs. Keep completion numbers only if judge-human kappa is 0.6 or more and at least 0.8 of human-human kappa.
6. **Product honesty patch.** Caveat or hide uncalibrated outputs; fix the comparison rubric imbalance (in-product runs score 7 to 10, demo-only rivals cap near 4 to 7) [L5]. Pause automated signups on competitor sites pending legal review.

### 4.2 Weeks 3 to 6: study #1 (concept and message, predict-then-observe)

| Item | Spec |
|---|---|
| Question | Can we rank and produce the distribution of human responses to real design-partner concepts and messages, alone and with a small human anchor? |
| Stimuli | About 60 from 3 design partners (concept cards plus headline or value-proposition sets), about 150 ratings each |
| Who | Prolific US representative sample, plus a **mandatory** screened arm of about 300 matching a partner's audience |
| Design | Each respondent rates about 10 stimuli on a 5-point likelihood scale plus forced choice within headline sets; randomize order and pre-register position as a covariate; 300 retested after 7 days. Turn on Prolific authenticity checks and report exclusions (an LLM respondent passed 99.8% of attention checks [U36]) |
| Frozen predictions | Haiku, Sonnet 5.5, SSR elicitation [W20], all hashed before fielding. After fielding: anchor-and-shift at n = 50 / 100 and calibration curves, cross-validated |
| Primary metric | Spearman pooled across partners with partner fixed effects, plus within-partner pairwise concordance; S on the 5-point distribution |
| Noise ceiling | Split-half (1,000 random splits) and test-retest |
| Power | Simulate before fielding using SSR's between-concept spread |
| **GO** (sell model-only scores) | rho / ceiling at least 0.7 with CI lower bound at least 0.5; S beats the partner-mean baseline with CI excluding 0 |
| **Conditional GO** (sell human-anchored only) | Model + 50 humans is at least as accurate as 75 or more humans (effective sample 1.5x or more, CI excluding 1.0x), threshold fixed by step 4.1.2 |
| **NO-GO** | Neither: reposition as human-research tooling plus agent-generated hypotheses |
| Cost | About $3.1k general sample plus about $0.9k screened arm plus VAT on fees [W34]; LLM spend under $100 |

In parallel: a design-partner A/B backtest (20 to 50 past tests each, aggregates only; gate on kappa CI above 0 and calibrated effect correlation above 0.3, pre-registered), and study #2 on usability issue recall (20 to 30 unmoderated sessions or a seeded-issue site; two coders; recall and precision of our cited findings with a defined band).

### 4.3 This quarter

1. **Owned ground-truth stream**, only after a GO or conditional GO: about 400 Prolific respondents a week on fresh stimuli, 20% retested, every item predicted first (about $8k for the remaining weeks).
2. **Productize** message-test and concept-test modes: calibrated distribution, winner probability, confidence with abstain, and an "add real respondents" button.
3. **Calibration ladder**: global per-source weights until 25 outcomes (best default, but worse than plain on OpinionQA and GlobalOpinionQA [L2]), then per-customer calibration behind the half-split check.
4. **Confidence model** that must beat simple baselines (prediction entropy, anchor-model disagreement) by 0.03 AUROC; Simile's fine-tuned head beat a probe by only 0.006 [W30]. Our own disagreement signal (model scores 6.8 where it disagrees most with evidence, 69.6 where they agree) is the starting feature [L1].
5. **Funnel pilot** on one partner flow with clickstream-derived personas, metric and threshold defined first.
6. **Fine-tune gate**: train (c) or (e) beyond pilots only if its gate in section 2.2 passed and a commercially usable training set exists.
7. **Consent**: upfront opt-in for cross-customer learning; counsel on retroactive terms and session replay [U15][U17].

### 4.4 Build list (predict-then-observe)

Our trace exhaust has no human signal; training on it distils Gemini into itself [L5].

| Component | Job |
|---|---|
| Prediction ledger | Immutable record before any outcome: claim type, predicted value, confidence, model and prompt hash, timestamp |
| Outcome import | CSV first (variant, exposures, conversions; survey results); later Optimizely / GrowthBook aggregates [U19][U20] |
| Claim review | Accept / reject / severity on every cited report claim, stored with the trace |
| Human-anchor button | Buys 50 to 100 real responses through a panel API |
| Track-record panel | Hits and misses on this account vs the base-rate baseline, in every report |
| Calibration service | The ladder above, with abstain |

### 4.5 Stop

1. SimBench bracket tuning and routing (late rounds gained 0.05 to 0.5 each).
2. Personas as an accuracy lever (invented personas cost 1.9; persona text cut OPeRA next-action accuracy 3.8pp) [L4][L5].
3. FM phases 1 to 5 in `beat_behavior_fms.md` (union corpus, scaling, chasing Be.FM): non-commercial licences, in-distribution wins, stale targets.
4. Presenting uncalibrated outputs as findings.
5. Placing any of our SimBench numbers next to a zero-shot leaderboard number.

### 4.6 Budget (proposal)

| Item | Cost |
|---|---|
| Sonnet evidence run and pilots | low hundreds (judgment) |
| Open-model backtests | tens of dollars of GPU (judgment) |
| Study #1 | about $4k plus VAT |
| Study #2 | about $1 to 2k (pricing unverified [U14]) |
| Weekly panel, if GO | about $8k |
| **Total** | **about $13 to 15k plus engineering**, which is the largest cost (2 to 3 weeks for calibration, ledger and import) |

For scale: one 1,000-person, 15-minute probability-panel survey costs $43,250 [W35].

---

## 5. What the field shows (2025-2026)

- **SimBench v4 (ICLR 2026, Apr 2026):** best 40.80 (Claude 3.7 Sonnet), no 2026 models; Centaur 8.54; instruction tuning helps low-entropy and hurts high-entropy questions (r = -0.942); thinking tokens do not help [W1].
- **BehaviorBench (data 17 Sep 2026; v2 7 Oct 2026):** Claude Opus 5 leads individual prediction (86.2); Be.FM-1.5-4B leads the distributional board (95.5) on instruments seen in training; v2 headline "Gemini 3.1 Pro and Claude Opus 5 lead" [W2][W3].
- **OdysSim (Sep 2026):** OSim-8B 64.6 vs frontier 64.8 to 65.5; weights public under MIT [W5].
- **Digital twins:** Twin-2K mega-study, r = 0.20 with the real person, barely above demographics-only, fine-tuning no help [W7]. Pew (30 Sep 2026): Opus 4.6 twins 12.4pp off, subgroups 13.6 to 16.1pp [U1].
- **Experiments (Nature, Jul 2026):** r = 0.85 on 469 effects, magnitudes about 2x too large, r = 0.39 on megastudies [W23].
- **A/B:** Spotify (Aug 2026) raw 39% effect recovery, calibrated within sampling error [W15]; WiserUI-Bench near chance [W17]; Squoosh judge kappa 0.14 [W18]; Shopify SimGym 77% directional with shop-specific archetypes [W27]; AgentA/B direction only (its p = 0.03 does not reproduce from its own counts) [W28].
- **Web behaviour:** Customer-R1 39.6% next action after SFT+RL [W11]; simulators too cooperative [W19].
- **Corrections beat fine-tuning under a fixed human budget** (ACL 2026) [W9]; AIPW 93 to 99.6% bias reduction with 50 to 300 humans [W22].
- **Market:** Simile $100M Series A (Feb 2026) and $200M+ at $2B (Jul 2026), fine-tunes Qwen3.5-27B, publishes a confidence model (AUROC 0.736) [W29][W30]; Aaru reports mean TVD 7.62 against a human floor of 2.3 to 12.0 and says its core model is not an LLM [W31]; Listen Labs $69M for AI-moderated research with real people [W33]; Qualtrics synthetic panels claim "12x more accurate" with no metric [U37]. Pattern: every vendor that publishes numbers anchors on human data plus calibration; none publishes a reproducible held-out comparison against current frontier models.

---

## 6. Open questions

- Whether SimBench findings carry over to product tasks is untested; study #1 is the first test.
- Sonnet 5.5 with evidence has never been run.
- Upworthy's 2013-15 news headlines may not represent SaaS copy.
- Stated intent is not purchase.
- B2B audiences may not be reachable through general panels.
- Our DPO adapter (`/opt/usersim_fm`) is not in this checkout; its "kill" compared two different accuracy definitions [L3].

---

## Sources

**Verified**
- W1 SimBench v4 — https://arxiv.org/html/2510.17516v4
- W2 BehaviorBench leaderboard — https://umich-foreseer.github.io/behaviorbench/
- W3 BehaviorBench v2 — https://arxiv.org/html/2606.24162v2
- W4 BehaviorBench verbalized-distribution data — https://umich-foreseer.github.io/behaviorbench/data_verbalized.js?v=1
- W5 OdysSim v2 — https://arxiv.org/html/2606.14199v2
- W6 Socrates — https://arxiv.org/html/2509.05830v2
- W7 Digital Twins as Funhouse Mirrors v5 — https://arxiv.org/html/2509.19088v5
- W8 Small Foundation Models of Human Cognition and Behaviour — https://arxiv.org/html/2608.05224v3
- W9 Valid Survey Simulations with Limited Human Data (ACL 2026) — https://aclanthology.org/2026.acl-long.498/
- W10 The Limits of Simulated Societies — https://arxiv.org/html/2609.25760
- W11 Customer-R1 — https://arxiv.org/html/2510.07230v2
- W12 OPeRA v7 — https://arxiv.org/html/2506.05606v7
- W13 ShopCART (ACL 2026) — https://aclanthology.org/2026.acl-long.2034.pdf
- W14 Upworthy Research Archive — https://pmc.ncbi.nlm.nih.gov/articles/PMC8329003/ · https://osf.io/jd64p/
- W15 Spotify, When Can LLMs Replace Humans in A/B Tests? — https://engineering.atspotify.com/2026/8/when-can-llms-replace-humans-in-a-b-tests/
- W16 Surrogacy framework for LLM A/B testing — https://arxiv.org/abs/2606.17165
- W17 WiserUI-Bench — https://arxiv.org/html/2505.05026v5
- W18 The Judge Knows When It Knows (Squoosh) — https://arxiv.org/html/2608.07517
- W19 Sim2Real gap in user simulation — https://arxiv.org/abs/2603.11245
- W20 Semantic similarity rating (PyMC Labs / Colgate) — https://arxiv.org/html/2510.08338v3
- W21 Twin-2K-500 — https://arxiv.org/html/2505.17479
- W22 When Can You Trust Your Synthetic Users? — https://arxiv.org/html/2609.13148
- W23 LLMs predict results of social science experiments (Nature 2026) — https://www.nature.com/articles/s41586-026-10742-x
- W24 Verasight Report IV — https://www.verasight.io/reports/synthetic-omnibus-survey
- W25 Verasight Report III — https://www.verasight.io/reports/coffee-llm
- W26 When Synthetic Users Fail — https://arxiv.org/html/2607.26348v2
- W27 SimGym (Shopify) — https://arxiv.org/html/2605.19219
- W28 AgentA/B v4 — https://arxiv.org/html/2504.09723v4
- W29 Simile Series B — https://www.simile.com/blog/series-b
- W30 Simile confidence model — https://www.simile.com/blog/confidence
- W31 Aaru, population simulation at the replication floor — https://aaru.com/publications/population-simulation-at-the-replication-floor-summary
- W33 Listen Labs Series B — https://pear.vc/listen-labs-series-b/
- W34 Prolific pricing — https://researcher-help.prolific.com/en/articles/445239-what-is-your-pricing
- W35 USC UAS pricing — https://uasdata.usc.edu/page/UAS+Pricing

**Unverified (labelled where used)**
- U1 Pew, Can AI Stand In for Human Survey-Takers? (fetched by the critic) — https://www.pewresearch.org/data-labs/2026/09/30/can-ai-stand-in-for-human-survey-takers-not-really/
- U3 Evi-DA — https://aclanthology.org/2026.findings-acl.1026/ ; Distribution Shift Alignment — https://arxiv.org/abs/2510.21977
- U9 LOLA — https://arxiv.org/abs/2406.02611
- U14 Maze pricing — https://help.maze.co/hc/en-us/articles/26550136250899
- U15 FTC on terms changes — https://www.ftc.gov/policy/advocacy-research/tech-at-ftc/2024/02/ai-other-companies-quietly-changing-your-terms-service-could-be-unfair-or-deceptive
- U17 Session replay (Mikulsky v. Bloomingdale's) — https://www.duanemorris.com/alerts/us_court_appeals_reversal_expands_potential_liability_companies_using_session_replay_0625.html
- U18 Amazon Reviews'23 — https://amazon-reviews-2023.github.io/
- U19 / U20 Optimizely export, GrowthBook — https://docs.optimizely.com/experimentation-strategy/data-docs/experimentation-events-export · https://docs.growthbook.io/overview
- U29 Licence pages — https://huggingface.co/datasets/pitehu/SimBench · https://huggingface.co/datasets/befm/BehaviorBench
- U30 EY-Aaru alliance — https://www.ey.com/en_gl/newsroom/2026/09/ey-announces-alliance-with-aaru-to-help-organizations-drive-growth-with-greater-confidence-through-behavioral-simulation
- U31 Cui et al., Nature Computational Science 2025 — https://www.nature.com/articles/s43588-025-00840-7
- U32 Tsai & Lai, Seeing Is Not Perceiving — https://arxiv.org/abs/2609.25677
- U33 Oetzel & Maiberger, LLM WTP vs BDM — https://doi.org/10.1057/s41270-026-00542-7
- U34 Simulated Customers Never Walk Away — https://arxiv.org/abs/2606.20708
- U35 PerceptUI — https://arxiv.org/abs/2606.05697
- U36 Westwood, PNAS 2025 — https://www.pnas.org/doi/10.1073/pnas.2518075122
- U37 Qualtrics synthetic research — https://www.qualtrics.com/articles/strategy-research/synthetic-research-breakthrough/

**Local**
- L1 `docs/experiments/simbench_closeout_62_86.md`, `simbench_mass_and_levers_results.md`, `simbench_all_results.md`, `results/simbench_ablate/*.json`
- L2 Direction analysis (data-need curves, leave-one-dataset-out transfer, gain decomposition, leak retune)
- L3 `results/fm_baselines/`, `results/socrates_dpo/DECISION.json`, `docs/plans/beat_behavior_fms.md`
- L4 `docs/experiments/persona_panel_status.md`
- L5 `results/summary*.json`, `results/probe_history_persona_paired.json`, `results/endpoint_audit.json`, `docs/experiments/opera_coldstart_prior.md`
- L6 `mvp/*.py`, `reports/kolanut-27557f9c/README.md`
