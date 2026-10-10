# What predicts preference between competing AI/software products, overall and by segment, and which external public data helps
UserSim literature and data sweep, 2026-10-10. I opened every URL in the Sources list on 2026-10-10 unless it is marked "search-only". "Unverified" means I could not confirm it from a primary page I opened. I wrote no files to the repo; scratch scripts are in the session scratchpad only.

## 0. Bottom line

1. **Which model it is gives the strongest predictable signal, and that signal has a ceiling.**
   - On HUMAINE overall_winner decisive votes, a Bradley-Terry fit on model identity alone, inside HUMAINE, reaches **0.625–0.640** held-out accuracy (my 2-fold CV). This is a ceiling reference only, not an allowed prediction.
   - Prolific's own predictors that use conversation content stop at about **66%**. Sentence embeddings reach about **59%**. Adding a side-by-side LLM judge moves accuracy about **1 point** [S2].
   - On Chatbot Arena pairs, the best judges reach **68.6%**, and a "longer answer wins" rule alone gets **59.8%** [S23].
2. **Demographics add almost nothing per vote, but they do move segment rankings.**
   - Inside HUMAINE, held-out votes with an age-specific BT versus one pooled BT: accuracy **0.6416 vs 0.6405**, log loss **0.6345 vs 0.6339**. A politics-specific BT is worse (0.6347).
   - Other sources agree:
     - Prolific: age, country, education and ethnicity explain about 1% of judgment style [S2].
     - Persona variables explain under 10% of annotation variance [S12].
     - Fine-tuning with demographics does not help [S13].
     - Demographic prompting does about as well as the default judge on PRISM [S14].
     - Demographic prompting was the worst condition in PRISM-X [S15].
   - Even so, the paper reports mean absolute rank shifts of **±2.8** across age groups, ±1.5 across politics and ±1.3 across ethnicity [S1].
   - In my check, Spearman between the 18–34 and 55+ rankings is **0.906**, against a split-half noise ceiling of **0.951**.
3. **The larger error comes from moving between platforms and their user populations.**
   - LMArena text scores (2026-10-08 snapshot) versus HUMAINE:
     - Spearman **0.735** with raw scores and **0.637** with style-controlled scores.
     - Decisive-vote accuracy **0.585 / 0.568**, against a model-only ceiling of 0.625 on the same votes.
     - So raw Arena captures about **68%** of the achievable model-level signal with nothing fitted on HUMAINE.
   - The misses are systematic:
     - HUMAINE ranks these much higher than Arena does: magistral-medium-2506 (+32 rank positions), deepseek-v3-0324 (+18), mistral-large-3 (+17), olmo-3.1-32b (+14).
     - HUMAINE ranks these much lower: gpt-5 (−20), claude-opus-4.5 (−20), kimi-k2 (−17), o3 (−15), o1 (−14).
   - Other transfer gaps point the same way. PRISM found GPT models ranked significantly worse than on Chatbot Arena [S7]. HUMAINE's #1, gemini-2.5-pro, is 13th on HELM [S1].
4. **Style effects do not transfer as they are.**
   - Arena and SEAL users reward length. On SEAL, an answer 2,000 tokens shorter wins 20% of the time and one 2,000 tokens longer wins 67% [S30]. On PPE, the verbosity-only baseline scores 59.8% [S23].
   - HUMAINE does not reward length: odds ratio 0.94 pooled and 0.96 within model.
   - What HUMAINE rewards is substance [S2]. Within-model odds ratios:

     | Feature | Within-model odds ratio |
     |---|---|
     | Goal achievement (substance) | 1.28 |
     | Engagement | 1.31 |
     | Grounding in the user's situation | 1.21 |
     | Sycophancy | 1.12 |

   - Yet raw Arena transfers better than style-controlled Arena. Something style control removes is valued by HUMAINE users; that is an open question.
5. **Personalization only pays when you have some history for each person.**
   - LoRe on PRISM goes from **62.5%** (one global BT) to **71.0%** with about 4 examples per user [S16].
   - In PRISM-X, the personally fine-tuned model was picked first 31.8% of the time against 25% chance, while putting demographic details in the prompt did worse than the base model [S15].
   - LLM-simulated users reproduce aggregate rankings (r = 0.98–0.99) but not individuals (Kendall τ 0.11–0.22 against human self-consistency of 0.57) [S15]. This supports UserSim aiming at segments and aggregates rather than single users.
6. **Outside LLMs, public evidence is thin and mostly negative for zero-shot LLM prediction.**
   - UI A/B winners: LLMs are near chance once position bias is controlled; the best consistent accuracy is 34.6% against 25% chance [S36].
   - Upworthy headline winners: barely above random [S37].
   - Raw LLM predictions recover only 39% of the human A/B treatment effect. Flexible calibration on real data fixes it [S38].
   - One positive result: aggregate purchase intent for product concepts reaches 90% of human test-retest reliability [S39].
   - I found **no** public study that predicts head-to-head choice between competing apps from reviews or metadata and checks it against real choices.

## 1. HUMAINE (arXiv 2603.04409, ICLR 2026)

| Topic | Finding (key numbers) | Src |
|---|---|---|
| Protocol | Participants pick their own topic. Each message goes to two models shown side by side as "Model A" and "Model B", anonymised and randomised. Minimum 3 turns, median 6. Recruited on Prolific at £9/hr; models called via OpenRouter with default settings. | S1, S3 |
| Scale (paper) | 23,404 participants, 28 models, 22 strata. Strata: age 18–34 / 35–54 / 55+ in both countries; US and UK ethnicity (4 groups each); US politics (3); UK politics (5). 1,848–2,636 comparisons per stratum, 119,890 multi-dimensional judgments, post-stratified to census. Gender, education and income were not modelled. | S1 |
| Pair sampling | TrueSkill matchmaking picks the most uncertain matchup, run separately in each stratum. So the mix of model pairs differs by segment, which confounds raw segment comparisons. | S1, S3 |
| Ranking model | Hierarchical Bradley-Terry-Davidson (BTD). Advantage η = (θᵢ,ₖ − θⱼ,ₖ) + α(Δuᵢ − Δuⱼ). Demographic offsets for age, ethnicity and politics are scaled by 1/√3. Each metric has its own tie propensity νₖ. Heterogeneity prior τ ~ Exp(12). Score = expected points against all opponents. | S1 |
| Anonymity | Described as "anonymised". Identity leakage (models naming themselves, recognisable style) is not discussed. VibeCheck identifies models from style with 80% accuracy [S28], so "blind-ish" is the right word and brand effects can leak in. | S1, S28 |
| Tie rates (paper) | Trust/Ethics/Safety 65%, Overall 10%. Core Task rises from 32% (age 18–34) to 39% (55+). Communication 17–20%. Overall ties rise from 9.7% (18–34) to 12.5% (55+). | S1 |
| Tie rates (checked on local CSV) | 51,456 comparisons × 5 metrics, 45 models. Overall 11.2%, Communication 18.9%, Fluidity 31.6%, Core Task 37.9%, Trust 66.3%. | local data |
| Demographic disagreement | Age is the main axis. Mean absolute rank shift ±2.8 (age), ±1.3 (ethnicity), ±1.5 (politics). magistral-medium-2506 is 1st (US) / 2nd (UK) among 18–34s but 5th / 10th among 55+. gemini-2.5-pro rises with age. Interaction effects 0.9–8.5 pp. 47% of three-way cells have fewer than 100 observations. No share-of-variance figure is given. | S1 |
| Task mix | Information seeking 71.5%, personal advice 10.5%, project planning 2.7%, technical assistance 2.4%. Health 12.9%, sports 8.8%, technology 8.1%. Task complexity, goal achievement and engagement scores are labels from an LLM judge (GPT-4.1), not from users. Mean goal achievement 4.32. | S1 |
| Prediction baselines | **None in the paper**: no held-out metrics and no Arena correlation. | S1 |
| Prolific "State of HUMAINE" (11 Jun 2026; not peer-reviewed) | Scale: 51 models, 116,536 conversations, 50,769 decisive votes, 23,707 people. Predicting the pick from conversation features hits a ~66% wall (tuning moves it under 0.5 pt); embeddings ~59%; side-by-side LLM judge moves it ~1 pt; holding out raters gives the same ~66%. One factor explains 65% of variance across the five ratings. Rater types: "Sweep" 42% (all sub-dimensions agree), "Focus" 41% (choice rests on a few dimensions), "Flip" 17% (a dimension contradicts the pick). A rater's history raises AUC for "commits vs ties" from 0.56 to 0.65–0.70. The "~1%" is how much of **judgment style** demographics explain (statistic not named; Cramér's V ≈ 0.05), not who wins. | S2 |
| Dataset versions | Sep 2025: 27 models, 41,934 conversations [S3]. Paper: 28 models. Local CSV: 45 models. Jun 2026: 51 models. The public CSV has **no conversation text and no timestamps**, so the 66% result cannot be reproduced from public data. | S3, S5 |
| Noise | Review "comments" on citations.prolific.com (for example "78% had income above $75k") look like template placeholders. Unreliable and unverified. | S6 |

**What this means for the evaluation harness:**
- Score decisive-vote accuracy and three-way log loss (A / B / tie), per dimension, and report results as a fraction of the ceiling: (acc − 0.5) / (ceiling − 0.5).
- Compare segments only on shared pairs or through BT strengths, because of the per-stratum matchmaking.
- For the Trust dimension, predict the tie distribution rather than a winner.

## 2. Demographic preference datasets: how much do demographics explain?

| Source | Protocol / data | Key numbers | Licence | Value for UserSim |
|---|---|---|---|---|
| PRISM, Kirk et al. 2024, NeurIPS D&B, arXiv 2404.16019 [S7] | 1,500 people from 75 countries, census-representative UK and US samples. 8,011 conversations with 21 LLMs, collected Nov–Dec 2023. First turn: up to 4 models rated 1–100; the top one is locked in, and later turns compare two samples from that same model. | Text features explain R² = 0.06 of scores. palm-2 drops 4 places for US users; llama-7b drops 7 in Asia; mistral-7b gains 7 in Africa. GPT models rank significantly worse than on Chatbot Arena. The best US model gets only 45% mean choice. Whether models were anonymous to participants: unverified. | CC-BY-4.0 for human text; **CC-BY-NC-4.0 for model responses** | The only public dataset with individual profiles, first-impression ratings across models (P2) and a final choice: lets us test whether first impressions predict choice (P2→P4) by segment. |
| Community Alignment, Zhang et al. 2025, arXiv 2507.09650 (ICLR 2026, search-only) [S8, S9] | Survey of 15,000 nationally representative YouGov respondents in US, France, Italy, Brazil, India. Each prompt shows 3 curated value variants plus a default Llama response. Dataset: >200k comparisons (Table 2: 192,137; v1.1 adds 41k) from >3,500 annotators; multi-turn; 63–66% non-English. | Preferences vary widely within each country. 21 LLMs show "monoculture", matching only 41% of human preference scores. Deliberately diverse candidate responses lift fine-tuned win rates from about 0.51 to 0.70–0.96. Annotator fields: age, gender, education, politics, ethnicity, country. | CC-BY-4.0 | Segment-specific style and value preferences. Not product choice: all candidates come from one model. |
| DICES, Aroyo et al. 2023, arXiv 2306.11247 [S10] | DICES-990: 990 conversations, 173 raters, 60–70 ratings each (US/India, by gender). DICES-350: 350 conversations, 123 raters who each rated all (gender × 5 race/ethnicity groups). | Safety ratings only. Demographic effect sizes not extracted (unverified). | CC-BY-4.0 | Low; HUMAINE's Trust dimension is 65% ties anyway. |
| OpinionQA, Santurkar et al. 2023, arXiv 2303.17548 [S11] | 60 US demographic groups, Pew survey questions. | Model–human gap is about the size of the Democrat–Republican climate divide. Ages 65+ and widowed are least reflected. Some RLHF models lean left. | — | Population answer distributions (P1) only. |
| Hu & Collier, ACL 2024, arXiv 2402.10811 [S12] | Subjective NLP annotation datasets. | Persona variables explain **under 10%** of variance. A zero-shot 70B model with persona prompting captures 81% of what a persona-only regression achieves. | — | Sets a ceiling on demographic conditioning. |
| Orlikowski et al., arXiv 2502.20897 (ACL 2025, search-only) [S13] | 5 tasks with standardised sociodemographics. | Fine-tuning with demographics does not significantly help; the gains come from learning each annotator's behaviour. | CC-BY | Same conclusion. |
| SynthesizeMe, Ryan et al., ACL 2025, arXiv 2506.05598 [S14] | Benchmark of 131 Arena users / 1,338 pairs and 723 PRISM users / 16,705 pairs, filtered to pairs where LLM judges disagree. | Demographic prompting vs default judge on PRISM: +3.30 (3B), +1.26 (8B), −0.46 (70B), all within the ±1.24 confidence interval. A plain fine-tuned reward model (not personalized) beats every personalization method: PRISM 61.7–64.3%, Arena 68.3–71.5%. | — | Demographic prompting is not a lever. |
| PRISM-X, Kirk et al., arXiv 2605.13307 (13 May 2026) [S15] | 530 PRISM participants re-recruited about 2 years later; blind 4-way comparisons. Also GPT-4o simulators conditioned on each participant's profile. | Personalised fine-tune (P-DPO with a learned per-user prompt embedding) picked first 31.8%, pooled DPO 28.5%, base 22.0%, user context injected into the prompt 17.7% (chance 25%). Demographics-only prompting rated 52 vs a GPT-written preference summary 59 vs personalised fine-tune 65. Simulators: aggregate r = 0.99 / 0.98, but individual τ = 0.22 / 0.11 vs human self-consistency 0.57. | — | Aggregate simulation works; individual simulation does not. |
| SEAL Showdown tech report, Scale AI, Sep 2025 [S30] | Blind comparison inside a live chat app: the model you are using versus a sampled opponent; 4 answer options; identities revealed after the vote. | Users: median age 31, 58.2% aged 18–34, 88.6% with a college degree. Rankings can be segmented by country, education, age and language. **Raw data is not shared** with outside parties. | — | Segment leaderboards would be valuable, but scale.com/showdown now redirects with no Showdown page visible (availability unverified). |

## 3. Predicting Arena and human preference: judges, benchmarks, reward models, metadata, transfer

| Source | Claim / numbers | Src |
|---|---|---|
| MT-Bench + Arena, Zheng et al., NeurIPS 2023 D&B, arXiv 2306.05685 | GPT-4 as judge agrees with humans over 80% of the time, the same as human–human agreement. Released 3K expert votes and 30K conversations. | S20 |
| Chatbot Arena, Chiang et al. 2024, arXiv 2403.04132 | Crowd vs experts agree 72.8–83.1%. Crowd vs GPT-4 judge 75.6%. Expert vs expert 79.4–89.8%. About 240K votes, 90K users, 50 models (as of 2024-01-21). Conversations mentioning model names are filtered out. GPT-4 vs Llama-2-70b win rate ranges from 96.7% to 53.3% depending on topic. | S21 |
| Arena-Hard-Auto, arXiv 2406.11939 | Against the top 20 Arena models: Spearman 93.2%, Kendall 80.0%, agreement 90.9%, separability 87.4%. With style control on both sides: 98.6%. Costs about $20. | S22 |
| Length-controlled AlpacaEval, COLM 2024, arXiv 2404.04475 | Spearman with Arena rises from 0.94 to 0.98 after length control. | S24 |
| WildBench, arXiv 2406.04770 | Pearson with Arena: WB-Reward 0.98, WB-Score 0.95, ArenaHard 0.91, AlpacaEval LC 0.89. | S25 |
| MixEval, NeurIPS 2024, arXiv 2406.06565 | Rank correlation with Arena 0.96 (MixEval-Hard). By comparison GSM8K 0.78, MATH 0.50, MBPP 0.28. | S26 |
| PPE (Preference Proxy Evaluations), arXiv 2410.14872 (venue unverified) | 16,038 Arena pairs, 20 models, 6,120 raters. Best accuracy 68.59% (ensemble of LLM judges), GPT-4o judge 67.71%, Athene-RM-70B 66.56%, most reward models 56–63%, **verbosity-only 59.81%**. Accuracy correlates 77% (Pearson) with how the model does after RLHF. | S23 |
| Prompt-to-Leaderboard (P2L), arXiv 2502.14855 | An LLM outputs Bradley-Terry coefficients for each prompt. Trained on up to 1.5M Arena pairs over 130 models. A router built on it reached #1 on Arena in Jan 2025 (score 1389 vs 1364). Open checkpoint: lmarena-ai/p2l-7b-bt-01132025. No tests on other populations. | S27 |
| VibeCheck, arXiv 2410.12851 (ICLR 2025, search-only) | Style traits ("vibes") predict model identity with 80% accuracy and user preference with 61%. | S28 |
| LMSYS style control blog (2024-08-29) | Style coefficients: length 0.249, lists 0.031, headers 0.024, bold 0.019. Example: grok-2-mini drops from 6th to 18th under style control. | S29 |
| SEAL Showdown | Length strongly drives wins (see §0). "Thinking" model variants show no consistent advantage on everyday prompts and drop once loading time is controlled. o3 and o4-mini are penalised for not using Markdown. | S30 |
| The Leaderboard Illusion, arXiv 2504.20879 | Meta tested 27 private variants before Llama-4. Google received 19.2% and OpenAI 20.4% of Arena data; 83 open-weight models shared 29.7%. Arena data gives up to 112% relative gains on the Arena distribution. | S31 |
| Ameli et al., ICLR 2025, arXiv 2412.18407 (App. F) | Regressing model score on training compute: R² 0.59 (27 models). Dataset size: 0.50 (24). Parameter count: 0.15 (31). | S32 |
| Diverging Preferences, arXiv 2410.14632 (ICML 2025, search-only) | Over 30% of examples in MultiPref and HelpSteer2 show genuine annotator disagreement. Standard (Bradley-Terry) reward models and LLM judges cannot tell these apart from consensus cases. | S19 |
| Transfer across populations | PRISM vs Arena: GPT models significantly worse in PRISM [S7]. HUMAINE vs HELM: gemini-2.5-pro 1st vs 13th [S1]. HUMAINE vs Arena: my check in §6. | — |

**Takeaway:** benchmarks track Arena very closely (rank correlation 0.93–0.98), but Arena tracks HUMAINE only at about 0.64–0.74. The transfer gap is the main problem. Per-vote ceilings across datasets sit around 0.60–0.69.

## 4. Personalized and pluralistic reward models (2024–2026)

| Method / paper | Data | Result vs a single population model |
|---|---|---|
| LoRe (low-rank reward basis), arXiv 2504.14439 [S16] | PRISM, 643 seen + 643 unseen users, about 3.9 examples each, frozen 4096-dim reward-model embeddings, 20 splits | Global BT 64.0 / 61.0 / 62.5 (seen / unseen / overall); VPL 64.6 / 58.2 / 61.4; PAL 70.8 / 59.0 / 64.9; **LoRe 71.0 / 71.0 / 71.0**. On Reddit TLDR, unseen users: BT 60.0 → LoRe 66.2. |
| PAL, arXiv 2406.08469 [S17]; VPL, arXiv 2408.10075 [S18] | Summary, Pick-a-Pic, Persona; pluralistic data | The arXiv pages give no numbers. Venues (ICLR 2025 / NeurIPS 2024) are unverified. Their PRISM numbers above come from the LoRe paper. |
| SynthesizeMe [S14] | Chatbot Arena + PRISM | Personas induced from a user's past interactions give up to +4.4% (Arena) and +3.41% (PRISM) for an LLM judge. Still below a plain fine-tuned reward model. |
| PRISM-X [S15] | Live re-test with humans | Personalised fine-tune > pooled DPO > base > prompting. The gap between personalised and pooled is small (+1.46 rating points; $0.10/week willingness to pay, marginal significance). |
| Community Alignment, diverse candidate sampling [S8] | Value dimensions | Win rate rises from about 0.51 to 0.70–0.96 when candidate responses are deliberately diverse. Lesson: you can only learn heterogeneous preferences if the candidates differ. |

**Implication:** personalization gains need a few judgments per person or per segment. Demographic labels alone do not deliver them.

## 5. Preference between competing software/products outside LLMs

| Source | Data / protocol | Numbers | Implication |
|---|---|---|---|
| WiserUI-Bench, arXiv 2505.05026 v4 (Jan 2026) [S36] | 300 real UI pairs whose winners come from industry A/B tests | Best average accuracy 60.11% (GPT-4o) vs 50% chance. Best order-consistent accuracy 34.56% vs 25% chance. Huge position bias: o1 scores 16.56% when the winner is shown first and 97.78% when it is second. | Zero-shot prediction of which UI wins is near chance. |
| LOLA, arXiv 2406.02611 [S37] | 17,681 Upworthy headline A/B tests | Prompting does poorly; embeddings and fine-tuned Llama-3-8B are only marginally above random. Search-only: v1 abstract said "≤65%". | Pure LLM prediction of winners is weak. |
| Spotify Engineering, 13 Aug 2026 (+ arXiv 2606.17165, not opened) [S38] | Upworthy archive; gpt-4o-mini simulating users | Raw predictions recover 39% of the human treatment effect. Linear (OLS) calibration fails (3.8 standard errors off). Random forest / gradient-boosted calibration lands within sampling error. Refit whenever the model version changes. Least justified for genuinely new UI, pricing or features. | Use LLM outputs as calibrated stand-in measurements, not as the answer. |
| Maier et al., arXiv 2510.08338 [S39] | 57 personal-care concept surveys, 9,300 human responses | Semantic-similarity rating reaches 90% of human test-retest reliability; distribution similarity (KS) above 0.85. | First-impression (P2) concept tests at the aggregate level are feasible. |
| Copilot Arena, arXiv 2502.09328 (ICML 2025, search-only) | In-IDE votes: 4.5M suggestions, 10 models, 11k+ pairwise votes | Rankings differ from static benchmarks; consistent across programming languages but vary by task type. | Context-specific arenas matter. |
| LLM-Cure, arXiv 2409.15724 (search-only, unverified) | 1,056,739 reviews of 70 Android apps | Mines competitor reviews to suggest features; does **not** predict user choice. | Gap: nothing published validates choice prediction from reviews. |

## 6. FREE check run today: LMArena as a predictor of HUMAINE

**Method:**
- Predictor: LMArena `leaderboard-dataset` text ratings from the 2026-10-08 snapshot, CC-BY-4.0 [S33].
- 43 of 45 HUMAINE models matched; command-r7b and mistral-nemo are missing.
- Some matches are approximate: gpt-5 → gpt-5-high, kimi-k2.5 → instant, minimax-m2.1 → preview.
- HUMAINE overall_winner is used **only as the target**. Nothing is fitted on it: predictions are pure rank order plus the standard fixed Elo formula. In-HUMAINE fits appear below only as ceilings.

| Predictor (45,573 votes, 40,343 decisive) | Spearman vs HUMAINE BT | Decisive-vote accuracy | Log loss (coin flip = 0.6931) |
|---|---|---|---|
| Arena raw (overall) | **0.735** | **0.585** | 0.6730 |
| Arena style-controlled (overall) | 0.637 | 0.568 | 0.6789 |
| Arena style-controlled, multi_turn / creative_writing / english categories | 0.666 / 0.669 / 0.654 | 0.571 / 0.579 / 0.569 | 0.677–0.678 |
| Ceiling: model-only BT fit inside HUMAINE, 2-fold CV | split-half Spearman 0.951 | 0.625 | — |

**Domain-matched Arena categories** (style-controlled), using HUMAINE's domain label only to choose the category:
- Pooled accuracy rises from 0.564 to **0.572**.
- Creative arts: 0.567 → 0.591. Health: 0.550 → 0.560. Science: 0.548 → 0.538 (worse).

**By segment (style-controlled Spearman):**

| Segment | Spearman |
|---|---|
| Age 18–34 | 0.563 |
| Age 35–54 | 0.668 |
| Age 55+ | 0.635 |
| US | 0.563 |
| UK | 0.686 |

- Raw Arena accuracy by age: 0.575 / 0.589 / 0.600. Treat with caution, because matchmaking ran separately in each stratum, so pair mixes differ.

**Segment modelling ceiling inside HUMAINE** (all 45 models, 2-fold CV, accuracy / log loss):

| Model | Accuracy | Log loss |
|---|---|---|
| Pooled | 0.6405 | 0.6339 |
| Age-specific | 0.6416 | 0.6345 |
| Age, 50/50 shrunk toward pooled | 0.6413 | 0.6337 |
| Country-specific | 0.6405 | 0.6343 |
| Politics-specific | 0.6347 | 0.6387 |

## 7. Conclusions

### (a) External public data most likely to improve HUMAINE-style prediction, ranked

| # | Source | Why it helps | Segment value | Caveats |
|---|---|---|---|---|
| 1 | LMArena `leaderboard-dataset` [S33] | Daily history; raw and style-controlled; 29 categories (multi_turn, english, creative_writing, coding, expert, industry_* that map to HUMAINE domains). Covers 43/45 models. Already reaches ρ 0.735 / acc 0.585 with no fitting. | Low directly (no demographics). | Arena's user base differs from HUMAINE's; ratings drift over time; private-testing distortions [S31]. |
| 2 | LMArena vote-level data: arena-human-preference-140k (Apr–Jul 2025, 53 models, conversation text + style metadata) [S34], plus search / webdev / P2L checkpoint | Learn which models win for which prompts and how much style matters, then reweight toward a HUMAINE-like population (remove the length reward). | Low–medium. | Model outputs fall under each provider's terms. |
| 3 | PRISM [S7] | Individual profiles, first-impression ratings and choice; census-representative UK/US. Use for age/segment offsets on model families and styles, for tie behaviour, and for the P2→P4 link. | **Highest available.** | Models are from 2023, so transfer must go through features or model families; **NC licence on model responses**. |
| 4 | Community Alignment [S9] | Large and rich in demographics (age, gender, education, politics, ethnicity, country); CC-BY-4.0. Gives segment-specific style and value preferences that can be mapped onto models' style traits. | Medium. | Not a product choice (one generator). |
| 5 | Model metadata: release date, price, latency, reasoning flag, compute (Epoch, OpenRouter, Artificial Analysis; not opened today) | Compute explains R² 0.59 of an Arena-derived score [S32]. The biggest Arena→HUMAINE misses are reasoning-heavy models, which fits SEAL's findings on thinking variants and latency. | Low. | Effect on HUMAINE unverified. |
| 6 | Arena-predictive benchmarks (Arena-Hard-Auto, length-controlled AlpacaEval, WildBench, MixEval) | Cold start for models not yet on Arena. | Low. | They proxy Arena, not HUMAINE. |
| 7 | Copilot, WebDev and Search Arenas | Priors for technical subsets (about 2–4% of HUMAINE). | Low. | Narrow. |
| 8 | DICES, OpinionQA, GlobalOpinionQA | Population answer distributions (P1) and safety. | Low for P3/P4. | — |
| 9 | SEAL Showdown segment leaderboards | Would be the best external age/education segment signal. | High if accessible. | No raw data; page availability unverified. |
| 10 | Non-LLM: Upworthy archive, WiserUI-Bench | Calibrating first-impression and A/B predictions for startup products. | — | Zero-shot LLMs near chance; need calibration. |

**Rule note:** for overall predictions, take the task/domain mix from external usage data, not from HUMAINE's marginal mix. Using HUMAINE's domain label to pick the query condition is fine (§6).

### (b) Most promising methods
1. **Hierarchical BTD built on external priors.** Model strengths come from Arena (raw, blended with the matched category, matched in time). Each metric gets a tie propensity, and ties grow with age. Demographic offsets are small and heavily shrunk toward the pooled estimate. This mirrors HUMAINE's own model, so outputs line up with its leaderboard.
2. **Platform as a population.** Estimate each platform's style weights (length, Markdown, latency, reasoning) on Arena, SEAL and PRISM, then extrapolate to a general-public, Prolific-like population. Arena's length reward is the clearest thing to remove.
3. **Substance-feature preference model.** Score goal achievement, engagement, grounding, sycophancy and length with an LLM judge on conversations we generate ourselves; learn population weights from external data.
4. **Prompt-conditional strengths (P2L)** for domain- and task-level P3 predictions.
5. **Calibrated stand-in measurements** (Spotify approach): flexible calibration of LLM-simulated outputs against a small real panel, refit whenever the model changes.
6. **Few-shot low-rank personalization (LoRe)** only once pilot judgments exist for a segment. Do not use demographic persona prompting as the main lever.

### (c) Next experiments
In every row, HUMAINE is used only as the evaluation target.

| ID | Tier | Experiment | Metric / expected outcome |
|---|---|---|---|
| F1 | FREE | Lock in the Arena prior. Blend raw and style-controlled with fixed weights; use time-matched ratings from the `full` history (for example, rating 60 days after each model's debut). | Decisive accuracy above 0.585 toward the 0.625 ceiling; three-way log loss. |
| F2 | FREE | Domain-conditional prior: shrinkage blend of overall and matched category, with the mapping fixed in advance. | Currently +0.8 pt pooled; aim for +1–2 pt. |
| F3 | FREE | Reasoning/latency adjustment: flag thinking models from model cards; derive the penalty from SEAL/Arena raw-vs-controlled gaps, not from HUMAINE. | Should shrink the gpt-5 / o3 / o1 / opus-4.5 misses. |
| F4 | FREE | Segment offsets from PRISM (age × model family/style) and Community Alignment (age × style). | Segment Spearman and rank-shift error vs the ±2.8 age shifts; no-offset baseline; ceiling = pooled. |
| F5 | FREE | Tie model per dimension and age, from PRISM near-ties and Arena tie / both-bad rates. | Per-dimension three-way log loss; target tie rates 11% / 19% / 32% / 38% / 66%. |
| F6 | FREE | Run the open P2L-7B on externally sourced prompts per domain (WildChat / Arena prompts). | Domain-level ranking agreement. |
| F7 | FREE (API spend, roughly $100–300 rough estimate) | Generate multi-turn conversations for the 45 models via OpenRouter; pairwise LLM judge with and without persona conditioning. | Expect aggregate ranking agreement but conditioning gains of ≤1 pt [S2, S15]. |
| F8 | FREE | PRISM P2→P4: do first-turn ratings predict lock-in/choice by segment? | Transfer function to test at model level on HUMAINE. |
| X1 | EXPERIMENTAL (~$200/mo) | Small Prolific pilot (about 60–80 people/month; price is an estimate) replicating blind side-by-side with first-impression and post-task items. | Calibration data for the Arena→general-public shift; real P2→P4 data. |
| X2 | EXPERIMENTAL | Metadata and review feeds for non-LLM startup competitors (pricing unverified). | First attempt at choice prediction from reviews. |
| I1 | INCREMENTAL (~$2,000/mo) | Monthly stratified panel (about 600–800 people) on startup-like product pairs measuring P2, P3 and P4. Train calibrated stand-ins and few-shot segment personalization. | The core proprietary dataset beyond HUMAINE. |

**Roadmap implications:**
- **Harness:**
  - Add decisive-vote accuracy, three-way log loss with per-dimension tie calibration, and segment-ranking Spearman.
  - Show ceilings alongside: model-only ~0.625–0.64, content features ~0.66, split-half 0.951, age cross-agreement 0.906.
  - Add a leakage guard that blocks HUMAINE-derived weights or mixes.
- **Data:** ingest the LMArena leaderboard daily, arena-human-preference-140k, PRISM (check the NC licence), Community Alignment, and a table of model metadata.
- **Fine-tuning:** deprioritise reward models conditioned on demographics. Prioritise a population-specific preference model with substance features, trained on labels with the length bias removed, plus low-rank personalization for pilot segments.

**Highest leverage:** F1 + F3 (external prior plus reasoning/latency fix), then F4 / F8 (PRISM-based segment offsets and P2→P4), then X1 → I1 (our own calibration panel).

## 8. Unverified or caveated
- Venues I did not confirm on a page I opened:
  - PPE: ICLR 2025.
  - PAL: ICLR 2025.
  - VPL: NeurIPS 2024.
  - Chatbot Arena: ICML 2024.
  - VibeCheck: ICLR 2025.
  - Community Alignment: ICLR 2026.
  - Copilot Arena: ICML 2025.
  - Orlikowski: ACL 2025.
  - Diverging Preferences: ICML 2025.
  - DICES: NeurIPS 2023.
  - OpinionQA: ICML 2023.
- PRISM model anonymity.
- DICES demographic effect sizes.
- LOLA's "≤65%" figure.
- LLM-Cure details.
- SEAL Showdown current availability.
- Prolific review-comment claims.
- The statistic behind State of HUMAINE's "~1%".
- Kaggle "LMSYS Chatbot Arena Human Preference" competition scores (not checked).
- Panel and API costs are rough estimates.
- Some model-name matches in §6 are approximate.

## 9. Sources (all opened 2026-10-10 unless marked)
- S1 Petrova, Gordon, Blindow. "Unpacking Human Preference for LLMs: Demographically Aware Evaluation with the HUMAINE Framework". arXiv 2603.04409, v1 3 Feb 2026, ICLR 2026. https://arxiv.org/abs/2603.04409 ; https://arxiv.org/html/2603.04409v1 (OpenReview https://openreview.net/forum?id=kVaE2kYjtV was blocked by a captcha)
- S2 Prolific. "The State of HUMAINE", 11 Jun 2026. https://www.prolific.com/resources/state-of-humaine-june-2026 ; https://labs.prolific.com/posts/state-of-humaine
- S3 Prolific Labs. HUMAINE framework blog, 16 Sep 2025. https://labs.prolific.com/posts/humaine-framework ; https://labs.prolific.com/posts/humaine
- S5 HUMAINE dataset card (MIT licence; local copy at data/humaine/README.md). https://huggingface.co/datasets/ProlificAI/humaine-evaluation-dataset
- S6 https://citations.prolific.com/paper/unpacking-human-preference-for-llms-demographically-aware-evaluation-with-the-humaine-framework
- S7 Kirk et al. "The PRISM Alignment Dataset". NeurIPS 2024 D&B, arXiv 2404.16019. https://arxiv.org/abs/2404.16019 ; https://arxiv.org/html/2404.16019
- S8 Zhang, Milli et al. "Cultivating Pluralism in Algorithmic Monoculture: The Community Alignment Dataset". arXiv 2507.09650. https://arxiv.org/html/2507.09650v2
- S9 Community Alignment dataset card. https://huggingface.co/datasets/facebook/community-alignment-dataset
- S10 Aroyo et al. "DICES Dataset". arXiv 2306.11247, 2023. https://arxiv.org/abs/2306.11247 ; https://github.com/google-research-datasets/dices-dataset
- S11 Santurkar et al. "Whose Opinions Do Language Models Reflect?" arXiv 2303.17548, 2023. https://arxiv.org/abs/2303.17548
- S12 Hu & Collier. "Quantifying the Persona Effect in LLM Simulations". ACL 2024, arXiv 2402.10811. https://arxiv.org/abs/2402.10811
- S13 Orlikowski et al. "Beyond Demographics". arXiv 2502.20897, 2025. https://arxiv.org/abs/2502.20897
- S14 Ryan et al. "SynthesizeMe!". ACL 2025, arXiv 2506.05598. https://arxiv.org/html/2506.05598v1
- S15 Kirk et al. "PRISM-X". arXiv 2605.13307, 13 May 2026. https://arxiv.org/html/2605.13307
- S16 Bose et al. "LoRe: Personalizing LLMs via Low-Rank Reward Modeling". arXiv 2504.14439, 2025. https://arxiv.org/html/2504.14439v1
- S17 Chen et al. "PAL". arXiv 2406.08469, 2024. https://arxiv.org/abs/2406.08469
- S18 Poddar et al. "Personalizing RLHF with Variational Preference Learning". arXiv 2408.10075, 2024. https://arxiv.org/abs/2408.10075
- S19 Zhang et al. "Diverging Preferences". arXiv 2410.14632 (search-only). https://arxiv.org/abs/2410.14632v2
- S20 Zheng et al. "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena". NeurIPS 2023, arXiv 2306.05685. https://arxiv.org/abs/2306.05685
- S21 Chiang et al. "Chatbot Arena". arXiv 2403.04132, 2024. https://arxiv.org/abs/2403.04132 ; https://arxiv.org/html/2403.04132
- S22 Li et al. "Arena-Hard and BenchBuilder". arXiv 2406.11939, 2024. https://arxiv.org/html/2406.11939v2
- S23 Frick et al. "How to Evaluate Reward Models for RLHF" (PPE). arXiv 2410.14872, 2024. https://arxiv.org/html/2410.14872v2
- S24 Dubois et al. "Length-Controlled AlpacaEval". COLM 2024, arXiv 2404.04475. https://arxiv.org/abs/2404.04475
- S25 Lin et al. "WildBench". arXiv 2406.04770, 2024. https://arxiv.org/abs/2406.04770
- S26 Ni et al. "MixEval". NeurIPS 2024, arXiv 2406.06565. https://arxiv.org/abs/2406.06565 ; https://arxiv.org/html/2406.06565
- S27 Frick et al. "Prompt-to-Leaderboard". arXiv 2502.14855, 2025. https://arxiv.org/html/2502.14855v2
- S28 Dunlap et al. "VibeCheck". arXiv 2410.12851. https://arxiv.org/abs/2410.12851
- S29 LMSYS. "Does style matter?", 29 Aug 2024. https://lmsys.org/blog/2024-08-28-style-control/
- S30 Scale AI. SEAL Showdown Technical Report, Sep 2025. https://static.scale.com/uploads/654197dc94d34f66c0f5184e/SEAL_Showdown_Tech_Report.pdf
- S31 Singh et al. "The Leaderboard Illusion". arXiv 2504.20879, 2025. https://arxiv.org/abs/2504.20879
- S32 Ameli et al. "A Statistical Framework for Ranking LLM-Based Chatbots". ICLR 2025, arXiv 2412.18407. https://arxiv.org/html/2412.18407v2
- S33 LMArena leaderboard-dataset (CC-BY-4.0; snapshot 2026-10-08). https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset
- S34 LMArena arena-human-preference-140k. https://huggingface.co/datasets/lmarena-ai/arena-human-preference-140k
- S35 Chi et al. "Copilot Arena". arXiv 2502.09328 (search-only).
- S36 Jeon et al. "Do MLLMs Capture How Interfaces Guide User Behavior?" (WiserUI-Bench). arXiv 2505.05026 v4, Jan 2026. https://arxiv.org/html/2505.05026v4
- S37 Ye, Yoganarasimhan, Zheng. "LOLA". arXiv 2406.02611. https://arxiv.org/abs/2406.02611
- S38 Ankargren, Persson, Schultzberg. "When Can LLMs Replace Humans in A/B Tests?" Spotify Engineering, 13 Aug 2026. https://engineering.atspotify.com/2026/8/when-can-llms-replace-humans-in-a-b-tests/
- S39 Maier et al. "LLMs Reproduce Human Purchase Intent via Semantic Similarity Elicitation of Likert Ratings". arXiv 2510.08338, 2025. https://arxiv.org/abs/2510.08338
- S40 LLM-Cure, arXiv 2409.15724 / https://doi.org/10.1145/3744644 (search-only)
