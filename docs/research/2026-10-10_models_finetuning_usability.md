# UserSim literature sweep: P2/P3 models, fine-tuning, usability simulation and cheap ground truth (2026-10-10)

**Tags:** [V] = I read the numbers in the primary paper or page. [P] = I opened the primary page but it only gave the abstract or summary (or I read it through a secondary summary page). [U] = unverified: search snippet only, secondary coverage, conflicting sources, or numbers only in a figure. Every URL in the Sources list was opened on 2026-10-10 unless it is marked [U]. No files were written to the repository.

## Summary
1. **On held-out items, fine-tuning wins.** The known result that fine-tuned behavior models lose to frontier models is about *held-out instruments*. When the instrument stays fixed and the items are new (new UIs, pages or headlines), small supervised models trained on human labels beat zero-shot frontier models:
   - UIClip (151M-parameter CLIP): 75.1% vs GPT-4V 51.6% on designer pairs from held-out URLs.
   - DesignSense (InternVL3-8B): 4-way accuracy 0.519 vs 0.385 for the best proprietary model.
   - PerceptUI (Qwen3-VL-8B, QLoRA) on LabintheWild, vs GPT-5.5 zero-shot: MAE 0.88 vs 1.22, JS 0.092 vs 0.150, Spearman ρ 0.66 vs 0.43.
   - LOLA (Llama-3-8B, LoRA, about $3): 46.9% vs GPT-4 at 38–40% on held-out Upworthy tests (random is 33%).
   UserSim controls its own instruments, so this is the biggest P2 lever. The gain shrinks to about 2.5 points when predicting individuals whose agreement with each other is low (DesignPref: 60.2% vs GPT-5 57.7%; designers agree with each other 62% of the time).
2. **Predicting the winner from screenshots is still near chance on real A/B tests.**
   - WiserUI-Bench consistent accuracy is 15.6–34.6% against a 25% random baseline.
   - Squoosh: κ = 0.14 on 330 conversion-optimisation tests. Fifteen human experts scored 48.5%.
   - On subjective UI factors, MLLMs agree with human pairwise preference about 60% of the time overall, but 90–93% when the human score gap is large.
   - Position bias is severe: GPT-5 is right 33.9% of the time when the winner is shown first and 89.8% when it is shown second.
   So P2 verdicts must be calibrated, aware of the human gap, allowed to abstain, and always run in both presentation orders.
3. **Prompted "respondents" give distributions of the wrong shape.**
   - Too flat for preference tests: entropy 0.93 vs 0.86 for humans.
   - Collapsed when a single persona is used: entropy 0.02 for first clicks and 0.28 for preferences.
   - Too central with direct Likert ratings: KS-similarity 0.26.
   Fixes with evidence:
   - Semantic-similarity rating (SSR): KS-similarity 0.88, and 90% of human test-retest reliability.
   - Population personas instead of single personas.
   - Pairwise question format: directional accuracy rises from 0.40 to 0.75.
   - Nonlinear calibration: raw LLM effects recover only 39% of the human effect; random-forest or boosted-tree calibration brings this within sampling error.
   Persona detail does not help: generic personas matched detailed ones in two UXtweak studies covering 5,504 humans.
4. **For P3, prompted agents are over-active (over-cooperative).**
   - Add-to-cart rate 80% vs 16% for real users, and conversion 64% vs 13.5% (RecAgent).
   - Simulated users ask about twice as many questions and are about twice as polite as humans on τ-bench.

   Training on human traces fixes the action mix:
   - OPeRA next-action exact match rises from 9.5% (prompted Claude 3.5) to 44.6% (Qwen2.5-VL-3B, SFT+RL with screenshots).
   - Purchase-rate gap falls from 9.9–16.3 points to 2.5 (AlignUSER).
   - Human judges pick the real trajectory in 74% of pairs for RecVerse, vs 98% for the STA baseline.
   - UserLM-8b scores 80 on naturalness vs 3 for GPT-4o.

   Step-level RL over-corrects into passivity: conversion of 0.6–2% vs 13.5% for real users.
5. **Directional A/B prediction works only with data-driven personas, pairwise questions and calibration.** Directional accuracy was 0.75–0.90 on 40 Amazon visual-design tests. Across 67 marketing tests the sign matched 70% of the time, but magnitudes were overshot until a pre-period calibration cut squared error about 77 times.
6. **Ground truth is cheap for P2 and dearer for P3.**
   - On Prolific (42.8% corporate fee, $12/hour recommended), $200/month buys about 70 ten-minute sessions. That is about 1,750 first-impression ratings (assumed 25 pages per session), or about 46 fifteen-minute task sessions.
   - $2,000/month buys about 700 ten-minute or about 470 fifteen-minute sessions.
   - Simple attention checks are no longer a sufficient defence: one LLM agent reportedly passed 99.8% of them [U].

---

## 1. P2: first impressions and visual appeal

| Source (date, venue/id) | Human data | Method | Key numbers | Held-out unit | Implication for UserSim | Tag |
|---|---|---|---|---|---|---|
| Reinecke & Gajos, "Quantifying Visual Preferences Around the World" (CHI 2014) | 39,975 volunteers from 179 countries; 430 sites; 2.4M ratings; 500 ms exposure; 1–9 scale | Mixed model of colorfulness and complexity × demographics | Conditional R² 0.47 but marginal R² only 0.07. Rate-rerate SD 0.7. Women prefer more colorful sites; more education lowers the colorfulness preference; Russians prefer lower complexity | Explanatory only | Demographics move the preference *peak* but explain little variance; most variance is site- and person-specific. Segment claims need per-segment validation. The 500 ms protocol is a cheap human instrument | [V] |
| WildLab "Bias tools" page | Dataset grown to over 60k people and 3.6M ratings; Augury predicts appeal per demographic group | — | Claims up to 37% conversion lift (vendor) | — | No public download found; the link line on the page is commented out. Ask the authors | [P] |
| Miniukovich & Figl, Data in Brief 2023 (PMC10823051); IJHCS 2023 companion | About 3,150 homepages (banking ~1,030, shopping ~1,060, university ~1,056); 2,822 MTurk workers in 3,319 sessions; 7-point ratings of prototypicality, aesthetics, perceived usability and trust; rich demographics including domain familiarity | Dataset | 83 pages per session including 12 duplicates. Quality control: rate-rerate, recognition test, VPN, bot-like demographics | — | Best free P2 training and evaluation set, with segments. On Harvard Dataverse; dataset licence not stated | [V] |
| Luera et al., "MLLM as a UI Judge" (arXiv 2510.08783, Oct 2025) | 30 UIs; 500 MTurk workers; 15,000 responses (9,296 kept); 9 factors; cost $2,250 | Zero-shot Claude 3.5 Sonnet, GPT-4o, Llama-3.2-11B | Overall MAE 0.51–0.54. Within-factor r ranges from −0.29 to 0.85 (best "Interesting"; Ease of Use and Comfort near zero). Pairwise accuracy 60.0 / 59.6 / 53.0%; 90–93% at large human gaps; chance on close pairs | Items | Screenshots predict "interesting" and "aesthetic" but not ease of use. Do not sell perceived usability from static pages; give verdicts that depend on the gap | [V] (paper has internal inconsistencies) |
| PerceptUI (Bougie et al., arXiv 2606.05697, Jun 2026) | WiserUI, BetterApp, WebDevJudge, UICrit, LabintheWild, "LabintheWild-UX", and UXCar (~500 people, proprietary) | Qwen3-VL-8B QLoRA. Distils "contrastive reflection" rationales from GPT-5.5, then evolves prompts | LabintheWild (Acc / MAE / JS / ρ): 43.5 / 0.88 / 0.092 / 0.658 vs GPT-5.5 zero-shot 29.5 / 1.22 / 0.150 / 0.429. LabintheWild-UX ρ 0.70 vs 0.48 for Claude Opus 4.6. BetterApp 79.3% (UIClip 75.1, GPT-5 55.4). WiserUI consistent accuracy 44.3 vs GPT-5 31.1. Cost per UI (5 questions × 20 personas): $0.07–0.25 vs $1.05–1.20 with a frontier model; one-time cost about $200–500 | Splits are at example level. An interface-disjoint split is not reported. Unseen questions and personas: 57–60% on UXCar | Strongest recent evidence that a cheap 8B student beats frontier models on perception instruments. Replicate with site-disjoint splits before trusting it. Red flag: removing the reflection step drops results *below* the majority-class baseline | [V] numbers; [U] new-product generalization |
| WiserUI-Bench (Yonsei authors; arXiv 2505.05026 v4, Jan 2026; ACL 2026 listing) | 300 real A/B pairs from VWO success stories, GoodUI and abtest.design; 684 expert rationales | Zero-shot models plus reasoning strategies | Consistent accuracy (random 25%): InternVL-2.5-38B 34.6, GPT-4o 30.1, Claude 3.5 24.2, o1 15.6. Multi-agent debate lifts GPT-4o to 39.0. No fine-tuning and no human baseline | — | A stress test only. Labels come from vendor success stories, so there is selection bias | [V] |
| UIClip (Wu et al., arXiv 2404.12500, 2024; UIST 2024 [U]) | 2.3M synthetic jittered web screenshots, plus 892 pairs rated by 12 designers (Krippendorff's α 0.37) | CLIP B/32 (151M) with contrastive and pairwise objectives | 75.1% vs GPT-4V 51.6% and LLaVA 54.6% | URL split | Cheap synthetic "degraded vs original" pairs teach design quality. Weights are public (MIT) | [V] |
| DesignPref (arXiv 2511.20513, Nov 2025) and "Efficient Personalization of Generative UIs" (arXiv 2604.09876, Apr 2026) | 20 designers × 600 pairs (12k labels); α ≈ 0.25; designers agree pairwise 62% of the time | Personalised UIClip head, GPT-5 with retrieval, onboarding retrieval | Personalised UIClip 60.2% vs GPT-5 zero-shot 57.7%. Retrieval model 61–62% vs GPT-5.2 59.1%. Adding examples to GPT-5.2's prompt made it worse | Screen-disjoint; leave-one-designer-out | The ceiling for predicting individuals is low. Target segment and population distributions instead | [V] / [P] |
| DesignSense-10k (arXiv 2602.23438, Feb 2026) | 10,235 layout pairs (~80% MTurk); human agreement 81% on the binary task | Fine-tuned InternVL3-8B | 4-way accuracy 0.519 vs 0.385 (o3 few-shot); macro-F1 0.456 vs 0.295; 72.2% binary on an out-of-distribution set | Held-out test plus out-of-distribution set | About 9k crowd pairs are enough for an 8B judge to beat frontier models on design preference | [V] |
| WebDevJudge (arXiv 2510.18560, ICLR 2026) | 654 WebDev-Arena pairs with rubric labels | LLM and MLLM judges, plus an agentic judge | Best pairwise 70.3% (GPT-4.1) vs humans 84.6%. Pairwise beats single-score rating by more than 8 points. The agentic judge is not better overall | — | Prefer pairwise formats. Judging by interacting with the page is not yet reliable | [V] |
| Kuric et al., "Distorted Perspectives of LLM-Simulated Preferences" (arXiv 2605.18311, May 2026) | 29 UXtweak preference tests; 2,073 people | GPT-4.1 and GPT-5.2 with persona variants | First-choice agreement 53% (GPT-4.1) and 65% (GPT-5.2, difference not significant). Distribution differs from humans in 38–46% of tasks; JS 0.17. Entropy 0.93 vs 0.86. Single persona: 91% of tasks differ. Generic personas ≈ detailed personas | Items | Use population personas plus calibration. Don't spend on persona detail | [V] |
| UXBench / UI-UX (arXiv 2606.13192, CVPR 2026 Findings) | 2,000 UX-diagnosis question–answer items | RL on Qwen3-VL-4B-Thinking | 0.796 vs 0.655 for Claude 4.5 Sonnet | Not reported | A small model trained with RL beats frontier models on expert UX-issue labels. This is diagnosis, not perception | [P] |
| UICrit (arXiv 2407.08850, UIST 2024) and public repo | Public CSV: 1,000 RICO mobile UIs; 11,344 critiques; 3 raters per screen; aesthetics and usability 1–10, learnability and efficiency 1–5; CC BY 4.0 | Few-shot and visual prompting | +55% in LLM feedback quality | — | Free mobile-UI ratings and critiques | [V] |
| Leiva, Shiripour & Oulasvirta, UAIS 2022/23 | CNN on 418 pages with 771k scores; predicts appeal per cohort (gender, age, education) | — | Accuracy not verified | — | Prior art for segment-conditioned appeal models | [U] |

**What this means for P2:**
- **Harness**
  - Render pages at fixed viewports: Reinecke used 1024×768; Miniukovich & Figl used 1440 px full pages with auto-scroll. Add a mobile viewport.
  - Output a rating *distribution* per instrument (appeal, trust, clarity, prototypicality) rather than a point score.
  - Run every pairwise comparison in both orders and report consistent accuracy.
  - Report the predicted gap and abstain when it is small.
- **Data:** Combine Miniukovich & Figl, UICrit, the UIClip/BetterApp release and WiserUI into a benchmark split by site.
- **Fine-tuning:** Start with frozen-embedding heads (UIClip or SigLIP plus a linear layer), then move to an 8B VLM with QLoRA and soft-label (distribution) losses.

## 2. P3: task completion and usability simulation

| Source | Key numbers | Implication | Tag |
|---|---|---|---|
| UXAgent (arXiv 2504.09407; CHI EA 2025) | Qualitative only: 5 UX researchers found the simulated behavior "not entirely realistic" | No fidelity evidence | [U] (search summary only) |
| UXCascade (arXiv 2601.15777; UIST 2026 per Adobe) | Aggregates and visualises persona-agent runs; tested with 8 UX professionals; no fidelity numbers | Useful UI pattern for reports, not validation | [U] |
| Kuric et al., "What Would GPT Click" (arXiv 2605.18302, May 2026) | 12 first-click studies, 3,431 people, 45 tasks. GPT-4.1's top hotspot matches the human top choice in 71% of tasks, but the distribution differs in 53%; JS 0.48; 5.4 vs 9.0 unique hotspots; entropy 0.43 vs 0.61. GPT-5.2 reasoning brought no gain. Likert follow-ups skew positive | Agents find the obvious path but miss the long tail of human mis-clicks. The modal click is usable; the distribution is not | [V] |
| Griesbach et al., HICSS 2026 | GPT-4o agents complete information-search tasks but fail to recognise when they are done and overshoot. They flag issues that humans overlook | Score success with external checks, never the agent's own report | [P] |
| Zhong et al., "Synthetic Heuristic Evaluation" (arXiv 2507.02306) | An MLLM found 73% and 77% of issues on two apps, vs 57% and 63% for 5 expert evaluators | A cheap expert-inspection mode; not a model of user behavior | [P] |
| Seshadri et al., "Lost in Simulation" (arXiv 2601.17087, Jan 2026) | τ-bench retail, about 40 humans per group. US humans succeed 45.2% of the time. Simulated users ask questions in 18.8% of turns vs 9.8%, and are polite in 39.2% vs 19.9%. Agent success varies from 67.0% to 75.9% depending on which LLM plays the user. Simulation underestimates the hardest tasks and overestimates moderate ones. AAVE speakers 39.4% vs SAE 50.6% | Calibrate success *by difficulty band*. Report results across more than one simulator model | [V] |
| Naous et al., UserLM (arXiv 2510.06552, ICLR 2026; HF microsoft/UserLM-8b, MIT) | Trained on 344k WildChat conversations from the Llama3-8B *base* model. Naturalness 80.2 vs GPT-4o 3.3 (humans about 90.2). Conversation-ending F1 63.5 vs 1.4. First-turn diversity 94.6 vs 74.4. Training took 227 hours on 4 A6000s. GPT-4o's task success falls from 74.6% to 57.4% when facing UserLM. "Better assistants make worse simulators" | Train user models on human turns starting from base models. Ready to use for conversational products and demos | [V] |
| Lu et al., "Can LLM Agents Simulate Multi-Turn Human Behavior?" (arXiv 2503.20749 v4; ACL 2026 [U]) | 31,865 sessions, 230,965 actions. Prompted models: 8.2–11.9% next-action accuracy; Qwen2.5-7B SFT 17.3%. Outcome F1 33.9 vs 20.0. Claude 3.5 does a single search per session and over-purchases | Evidence that prompted agents over-convert | [V] |
| Shop-R1 (arXiv 2507.17842 v2; ICLR 2026 [U]) | Shop-CART, about 52k proprietary sessions. Qwen2.5-3B exact match 27.7% vs SFT 16.8% vs zero-shot 0.3%. Hierarchical and difficulty-scaled rewards are required; the 0.5B model reward-hacks by always predicting "terminate" | Shape rewards per action type | [V] |
| See, Think, Act (arXiv 2510.19245, Oct 2025) | On OPeRA, Qwen2.5-VL-3B with SFT+RL on text and screenshots: 44.6% exact match, vs 24.2% for SFT and 9.5% for Claude 3.5. Screenshots add 3.9–6.1 points | Include screenshots in the observation | [V] |
| AlignUSER (arXiv 2601.00930; ACL 2026 [U]) | Qwen3-8B with a learned world model and counterfactual "lessons". OPeRA action accuracy 51.5% vs GPT-4.1 21.5%. Purchase-rate gap 2.5 points vs 9.9–16.3 for prompted agents. Pages per session 5.1 vs 5.3 for humans. Highest Spearman correlation with 55 real A/B tests | Best published action-mix fidelity | [V]; correlation value only in a figure [U] |
| RecVerse (Tang et al., arXiv 2608.20707, Aug 2026) | USB: 5,274 real GUI trajectories (Alibaba; release link not found). Qwen3.5-2B with session-level RL that matches action-type counts to real users. Add-to-cart rate: real 15.9 vs RecAgent 80.1 vs RecVerse 20.0. Conversion: real 13.5, RecAgent 64.3, Shop-R1 2.0, Customer-R1 0.6, RecVerse 4.9. Humans picked the real trajectory in 74% of pairs vs 98% for the STA baseline (κ 0.83) | Session-level reward that matches the human action distribution is the best current fix | [V] |

**What made simulated users less cooperative or more human-like:**

| Lever | Effect | Caveat |
|---|---|---|
| Train on real human turns or traces, starting from a base model rather than an instruction-tuned one (UserLM) | Naturalness 3 → 80; conversation-ending F1 1 → 64 | Conversation only |
| SFT on human web actions, then RL with hierarchical rewards (Shop-R1, See-Think-Act; Customer-R1 is already known) | Exact next-action match 0.3–9.5% → 28–45% | Shopping data only. Step-level RL under-converts |
| Session-level reward that matches human action-type counts (RecVerse) | Humans pick real 98% → 74%; add-to-cart 80% → 20% (humans 16%) | Needs human session statistics for each site type |
| World model plus counterfactual "lessons" compared against human choices (AlignUSER) | Purchase-rate gap 10–16 → 2.5 points | Some datasets are proprietary |
| Screenshots in the observation | +3.9 to +6.1 points | — |
| Data-driven behavioral personas (A/B setting) | Directional accuracy 0.45 → 0.75 | — |
| Prompting the user to be "less polite" | Mixed: helps some groups, hurts others | — |
| Reasoning mode, temperature, top-p, persona detail | Not significant (two Kuric studies) | — |

**What this means for P3:**
- **Harness**
  - Log the action-type mix, actions per session, searches, back and scroll events, and abandonment.
  - Compare these against human reference statistics. OPeRA covers shopping; AgentA/B's known 16 human actions vs 6 agent actions per session is another reference.
  - Add a trace-similarity metric. FlowEval's dynamic-time-warping approach reportedly correlates with expert judgments [P].
  - Score success with ground-truth checks.
- **Model**
  - Keep the frontier model for perceiving novel UIs, since it wins out of distribution.
  - Add a small behavior prior trained on human traces as a critic or regulariser over termination, abandonment and the action mix.

## 3. Fine-tuning and calibration on held-out products

| Study | Instrument | Training labels | Model / cost | Held-out unit | Fine-tuned | Best zero-shot frontier | Gap |
|---|---|---|---|---|---|---|---|
| UIClip | Designer pairwise quality | 618 pairs + 2.3M synthetic | CLIP B/32 | URL | 75.1% | GPT-4V 51.6% | +23.5 |
| DesignSense | Layout preference, 4-way | 8,735 pairs | InternVL3-8B | Test set + out-of-distribution set | 51.9% | o3 38.5% | +13.4 |
| UI-UX / UXBench | UX diagnosis question–answer | Not reported | Qwen3-VL-4B, RL | Not reported | 79.6% | Claude 4.5 Sonnet 65.5% | +14.1 |
| PerceptUI | LabintheWild ratings | Not reported | Qwen3-VL-8B QLoRA; $50–200 fine-tuning + $150–300 rationales | Example (not site) | ρ 0.658, JS 0.092 | GPT-5.5: ρ 0.429, JS 0.150 | +0.23 ρ |
| LOLA (arXiv 2406.02611; Marketing Science 44(5) 2025) | Best Upworthy headline among k | 12,376 tests | Llama-3-8B LoRA, about $3 on one A100 | Test ID | 46.9% (fine-tuned GPT-4o 48.8%; embeddings + linear 46.3%) | GPT-4: 37.9–40.0% (random 33.0%) | +7 to +9 |
| DesignPref | One designer's pairwise choice | 360 per designer | UIClip, last layer only | Screen | 60.2% | GPT-5 57.7% | +2.5 |
| See-Think-Act | OPeRA next action | 8.2k actions | Qwen2.5-VL-3B, SFT+RL | Held-out actions (in-distribution) | 44.6% | Claude 3.5 9.5% | +35 |

Patterns:
1. None of these tests a *new instrument*; each fixes the question and varies the item. That is consistent with the known held-out-instrument failure, and it is exactly UserSim's case: fixed P2/P3 instruments applied to new products.
2. Cheap heads compete with full fine-tuning. Embeddings plus a linear layer (46.3%) nearly match LoRA (46.9%) in LOLA, and DesignPref unfroze only the last layer. Start with frozen-embedding heads.
3. A secondary summary claimed LOLA reached "82–84%". This is **false**: the published abstract says the methods are only "marginally higher than random", and humans were at chance on significant headline pairs (45–52%).
4. The ceiling is human agreement: 62% pairwise agreement among designers (DesignPref), α 0.37 (UIClip), and 84.6% for humans on WebDevJudge. Always report a noise ceiling.

**Calibration and statistics (applies to P1–P4):**

| Source | Finding | Tag |
|---|---|---|
| Persson, Schultzberg & Ankargren, Spotify (arXiv 2606.17165, Jun 2026), plus Spotify Engineering blog (Aug 2026) | Raw gpt-4o-mini predictions recover only 39% of the human treatment effect on Upworthy. OLS calibration fails the falsification test (3.8 standard errors off). Random-forest and boosted-tree calibration land within sampling error. Average several LLM draws per unit | [V] |
| Hut & Masoero (arXiv 2608.02345, workshop paper) | 67 marketing tests: sign matches 70% of the time, but magnitudes are overshot. A two-phase pre-period calibration cuts squared error about 77 times. A within-subject design (each agent sees both arms) cuts standard error about 2.4 times | [P] |
| Benomar et al., Amazon (arXiv 2609.01038, EMNLP 2026 Industry) | 40 visual-design A/B tests; Claude Sonnet 4.5; 935 personas. Pairwise rating question: 0.75 / 0.80 directional accuracy (CTR / subscriptions), vs 0.40 / 0.40 for independent yes/no questions. No persona: 0.45 / 0.65. Personas built from *open* e-commerce data (0.70 / 0.90) do about as well as proprietary data (0.75 / 0.80). Subsampling to 100–500 personas costs no accuracy | [V] |
| Benomar et al. (arXiv 2609.24629, COLM workshop) | Prediction-powered inference (GPPI) needs up to 30% fewer human samples. Confidence-interval coverage fails with heavy-tailed outcomes | [V] |
| Dooskin, Squoosh (arXiv 2608.07517, Jul 2026) | Gemini 3 Flash judge panel: κ 0.14 on 330 tests. Abstaining unless confident: covers 49% of tests at κ 0.31, but this was exploratory and not confirmed on held-out data. Gemini 3.1 Pro is no better than Flash at 2.8 times the cost. Experts: 48.5% accuracy, though they agree with each other at κ 0.53 (a shared prior, not knowledge of outcomes) | [V] |
| Maier et al., semantic-similarity rating (arXiv 2510.08338, Oct 2025) | 57 surveys, 9,300 people. SSR reaches 90% of human test-retest correlation with KS-similarity 0.88; direct Likert gets 0.26. Without demographics, correlation falls from about 92% to about 50%. Gender and region effects are not reproduced | [V] |

## 4. Running cheap, reliable real studies

**Sample sizes**

| Goal | Rule | Source |
|---|---|---|
| Finding usability problems | Share found = 1−(1−L)^n with L ≈ 0.31, so 5 users find about 85%. Better to run 3 rounds of 5; test 3–4 users per distinct group | Nielsen 2000 [V] |
| Problems affecting 10% of users, found with 85% probability | n ≈ 18 | My calculation |
| Completion or conversion rate | 40 users for ±15% at 95% confidence; 21 for ±20%; 28 for ±15% at 90% | Budiu & Moran, NN/g 2021 [V] |
| Time on task or satisfaction | 47 users for ±15% at 95% confidence | Same [V] |
| Adaptive design | Start with 20–25, add users if the margins are too wide | Same [V] |
| Pairwise preference | n = 35–40 gives a ±15–16 point interval, so only splits of 65/35 or wider are decisive; a 55/45 split needs about 380 | My calculation |

**Platforms (2026)**

| Platform | Price | Tag |
|---|---|---|
| Prolific | Pay at least $8/hour, $12/hour recommended. Service fee 42.8% corporate, 33.3% academic or non-profit. No subscription. A 10-minute session costs about $2.86 and a 15-minute session about $4.28 (assumes the fee applies to rewards only) | [V] |
| Userbrain | Starter $49/month (3 testers), Plus $249/month (10), Flex $1,100/year (30); extra testers $45 each on Flex only. Screen and audio recordings; targeting by country, age, gender, language and device, plus screeners | [V] |
| Lyssna | Free plan (15 self-recruited responses); Growth $166/month (5 in-depth studies, live-website testing). Five-second, preference, first-click and prototype tests. Panel is pay-per-use but the rate is not on the page | [V] / panel rate [U] |
| Maze | The official page shows no prices; aggregators say about $75–99/month for Starter. Panel cost unknown | [U] |
| UserTesting | Not checked | [U] |
| MTurk (reference point) | Luera et al.: $2,250 for 15,000 ratings with 38% discarded, so about $0.24 per usable rating | [V] |

**Quality control**
- **Duplicates and rate-rerate:** include 10–15% duplicate items and exclude raters whose two ratings differ by more than 2 points on a 9-point scale (Reinecke; Miniukovich & Figl used 12 duplicates in 83 pages) [V].
- **Recognition test:** 10 seen and 10 unseen thumbnails [V].
- **Speeders:** a minimum time, for example excluding responses under 45 seconds [V].
- **Fraud signals:** VPN use, bot-like demographics (such as a default age of 25), repeated restarts, odd window sizes [V].
- **Prolific authenticity checks:**
  - These are behavioral: copy-paste and tab-switching for LLM use, and scripted behavior for bots. They run on Qualtrics, LimeSurvey, Pavlovia and AI Task Builder [V].
  - Vendor accuracy claims of 98.7% precision (LLM check) and 100% (bot check) [U].
- **Attention checks are not enough:** Westwood (PNAS 2025) reports an agent passing 99.8% of 6,000 attention checks [U].
- **P3 success:** verify it with answer questions or telemetry, never self-report.

## 5. Free assets usable now
- **Miniukovich & Figl 2023:** Harvard Dataverse DOIs 10.7910/DVN/9FKSQI, XOI0HI and Z7KLIH.
- **UICrit:** github.com/google-research-datasets/uicrit (CC BY 4.0; archived in Jan 2026).
- **UIClip weights:** huggingface biglab/uiclip_* (MIT).
- **WiserUI-Bench:** authors say it is on GitHub [U].
- **WebDevJudge:** github.com/lcy2723/WebDevJudge [U].
- **OPeRA:** huggingface NEU-HAI/OPeRA (CC BY 4.0; 692 sessions, 51 users, 28,904 action–observation pairs) [V via HF API].
- **UserLM-8b:** HF microsoft/UserLM-8b (MIT) [V].
- **Upworthy Research Archive:** for building the calibration stack.
- **LabintheWild visual-appeal data:** request from the authors [U].
- **DesignPref, DesignSense, the MLLM-UI-judge data, and USB:** release status [U].

---

## (a) Highest-lever directions, ranked

| Rank | Lever | Targets | Evidence | Cost | Confidence |
|---|---|---|---|---|---|
| 1 | Fixed-instrument supervised heads (frozen-embedding head, then 8B QLoRA with distribution loss) trained on human ratings and evaluated on held-out sites | P2 | +13 to +24 points pairwise (UIClip, DesignSense); +0.23 ρ (PerceptUI); +7–9 points (LOLA) | Free | High for population-level targets, low for individuals |
| 2 | Elicitation and calibration layer: SSR, pairwise within-subject format, averaging multiple draws, nonlinear calibration, GPPI for reported intervals | P2, P3 (also P1, P4) | KS-similarity 0.26 → 0.88; directional accuracy 0.40 → 0.75; effect recovery 39% → about 100%; squared error ÷77; up to 30% fewer humans | Free to build; needs some human data | High |
| 3 | Own clean panel on post-cutoff startup pages, with quality control. The only valid test of "new startup, no brand", and the training data for levers 1 and 2 | P2, P3 | Section 4 | Experimental / incremental | High |
| 4 | Behavior prior trained on human traces (OPeRA; USB if released) with session-level distribution reward, used as a critic over frontier agents | P3 | 9.5% → 44.6%; purchase gap 10–16 → 2.5 points; humans pick real 98% → 74% | Free (compute) | Medium: shopping-only data, transfer to other products unknown |
| 5 | Gap-aware, abstaining verdicts with counterbalanced order | P2, P3 | 50% → 90%+ agreement by human gap; position bias 34% vs 90% | Free | Medium-high |
| 6 | Behavioral and population personas instead of rich demographic backstories; demographics only for validated segment effects (age, income, education) | P2–P4 | No persona 0.45 vs data-driven 0.75; generic ≈ detailed persona | Free | Medium |
| 7 | (Low lever) Reasoning mode, sampling settings, bigger models for P2 judgments | — | Not significant (Kuric); Pro ≈ Flash (Squoosh) | — | Don't prioritise |

## (b) Next experiments

**Free (compute, fine-tuning on public data, and model calls only)**
1. **F1 – Build P2-Bench v0.**
   - Data: Miniukovich & Figl, UICrit, BetterApp test pairs, WiserUI, split by site or screen.
   - Metrics: Spearman ρ of per-page means, MAE, JS divergence of rating histograms, pairwise accuracy binned by human gap, and a split-half noise ceiling.
   - Baselines: frontier direct Likert, frontier with SSR, frontier pairwise, UIClip.
2. **F2 – Fine-tune on P2-Bench.** Frozen embedding plus linear head, then Qwen3-VL-8B QLoRA with soft-label KL or earth-mover loss.
   - Success: at least +0.10 ρ and at least 30% lower JS than the best frontier baseline on held-out sites; at least 80% of the noise ceiling; holds when training on Miniukovich & Figl and testing on UICrit.
3. **F3 – Segment fidelity** on Miniukovich & Figl demographics.
   - Metric: correlation between predicted and observed per-page differences between segments.
   - Success: r ≥ 0.4 for age and education. If r < 0.2, stop reporting segment-level P2 without human calibration.
4. **F4 – Cooperativeness audit of current UserSim agents.** Compare actions per session, searches, conversion and terminate rates, and action-type JS against OPeRA human statistics.
   - Success: every statistic within ±25% of human and JS ≤ 0.10.
5. **F5 – Behavior prior on OPeRA.** SFT then GRPO on Qwen2.5-VL-3B or Qwen3-VL-4B, with hierarchical step rewards plus a session-level action-count reward.
   - Success on held-out users: exact match ≥ 40%, conversion gap ≤ 3 points, session-length gap ≤ 15%.
   - Then use it as a critic on a non-shopping signup flow, and check that actions per session move toward human levels with no loss in completion-rate correlation.
6. **F6 – Calibration stack on Upworthy (17,681 tests).** Persson-style falsification, random-forest or boosted-tree calibration, and GPPI. Also an ablation of pairwise vs independent question format.
   - Success: at least 90% of the human effect recovered on held-out tests, at least 93% coverage of nominal 95% intervals, and at least 20% effective-sample-size gain.
7. **F7 – UserLM-8b as the user simulator** for chat or AI-demo products.
   - Metrics: naturalness and conversation-ending F1 vs prompted GPT-4o, and the gap to τ-bench human success of 45.2%.

**Experimental (about $200/month)**
1. **E1 – Monthly first-impression panel on Prolific.**
   - Design: about 70 ten-minute sessions (about $2.86 each). Each rater sees about 25 post-cutoff startup and competitor pages at 500 ms or 5 s exposure, rates them on 4 items, and makes 5 pairwise choices in both orders.
   - Quality control: duplicates and a recognition test.
   - Yield: about 1,750 ratings (about 35 per page across about 50 pages).
   - Success after 3 months: ρ ≥ 0.6 on appeal and trust, JS ≤ 0.10, and at least 80% pairwise accuracy on pairs where the human gap is at least 15 points, with no more than 50% abstention.
2. **E2 – Every third month, a P3 pair study.**
   - Design: about 46 fifteen-minute sessions, within-subject. The same task on the startup product and a competitor in counterbalanced order, with answer-verified success, time, the Single Ease Question, and post-use preference. That gives n ≈ 46 per product (about ±15%).
   - Success over 6 pairs: completion-rate MAE ≤ 15 points; task-difficulty ρ ≥ 0.5; preference direction correct on pairs decided by at least 20 points.
3. **E3 – Quality-control baseline.**
   - Success: exclusions ≤ 15%; split-half ρ of page means ≥ 0.8 with 30 or more raters.
   - Use the result to set noise ceilings for E1 and E2.

**Incremental (about $2,000/month)**
1. **I1 – P2 at scale ($750, about 260 sessions, about 6,500 ratings a month).**
   - Design: about 160 pages a month at about 40 ratings each, or segment months with about 30 raters per segment per page.
   - After 3–6 months, train UserSim's own head on 500+ clean pages.
   - Success: at least +0.10 ρ over frontier models by segment, and segment-difference r ≥ 0.4.
2. **I2 – P3 benchmark ($1,000, about 233 within-subject sessions).**
   - Design: about 5 product pairs a month at n ≈ 46 per product. Report GPPI-combined intervals.
   - Success: calibration error of predicted success probability ≤ 0.10; direction correct in at least 80% of decisive pairs; effective-sample-size gain from GPPI ≥ 20%.
3. **I3 – Think-aloud recordings ($249, Userbrain Plus, 10 per month).**
   - Metric: problem-level recall and precision of agent rationales against problems found by at least 2 humans.
   - Success: recall ≥ 60%, precision ≥ 50%.

## Caveats and unverified items
- **Mostly single 2026 preprints.** Several report numbers that contradict themselves: MLLM-UI-judge, UIClip mean reciprocal rank, Kuric's chi-square values, the data-driven persona paper (0.70 vs 0.75), and See-Think-Act (13.06 vs 19.92).
- **PerceptUI:** no site-disjoint split is reported.
- **AlignUSER:** the A/B correlation value is only in a figure.
- **RecVerse's USB dataset:** no release link found.
- **OPeRA numbers aren't comparable across papers,** because they use different filtered subsets and metric definitions.
- **Human-trace training data is almost all e-commerce.** Transfer to SaaS or onboarding tasks is untested.
- **Older public P2 sites may be in frontier training data.** Post-cutoff startup pages are the clean test set.
- **Venues taken from search listings only:** the ACL 2026 venues (Lu et al., AlignUSER, OPeRA, WiserUI), ICLR 2026 for Shop-R1, UIST 2024 for UIClip, and UIST 2026 for UXCascade.
- **Not verified:** Westwood's 99.8%, Prolific's accuracy claims, Maze and Lyssna panel prices, UserTesting pricing, and Leiva et al.'s accuracy.

## Other notes
- **Prompt injection:** the arXiv HTML for WiserUI-Bench contained instructions aimed at LLM readers, which I ignored. UserSim's browsing agents will meet injected text on competitor sites, so the harness should treat all page text as untrusted.
- **Name collision:** a NeurIPS 2026 workshop is called "UserSim" (Paris, 12 Dec 2026; organisers from NVIDIA, Stavanger/DeepMind, UNSW, Mercor and UCI/Cohere). It plans an open, census-conditioned baseline simulator and a community calibration exercise, so it could be a partner, a competitor, or a source of SEO confusion.

## Sources (opened 2026-10-10 unless marked [U])
**P2: first impressions and UI perception**
- PerceptUI, arXiv 2606.05697 (2026): https://arxiv.org/abs/2606.05697 and https://arxiv.org/html/2606.05697
- MLLM as a UI Judge, arXiv 2510.08783 (2025): https://arxiv.org/html/2510.08783v1
- WiserUI-Bench, arXiv 2505.05026 v4 (2026): https://arxiv.org/html/2505.05026v4
- UXBench / UI-UX, arXiv 2606.13192 (2026): https://arxiv.org/abs/2606.13192
- FlowEval, Apple ML Research (2026): https://machinelearning.apple.com/research/floweval-ui-evaluation
- UIClip, arXiv 2404.12500 (2024): https://arxiv.org/html/2404.12500
- Reinecke & Gajos, CHI 2014: https://kgajos.seas.harvard.edu/papers/reinecke14visual.pdf
- WildLab bias tools page: https://wildlab.cs.washington.edu/Project_BiasTools.html
- Miniukovich & Figl, Data in Brief 2023: https://pmc.ncbi.nlm.nih.gov/articles/PMC10823051/
- UICrit, arXiv 2407.08850 (2024): https://arxiv.org/abs/2407.08850 and https://github.com/google-research-datasets/uicrit
- DesignPref, arXiv 2511.20513 (2025): https://arxiv.org/html/2511.20513v1
- Efficient Personalization of Generative UIs, arXiv 2604.09876 (2026), via secondary summary: https://www.emergentmind.com/papers/2604.09876
- DesignSense, arXiv 2602.23438 (2026): https://arxiv.org/html/2602.23438v1
- WebDevJudge, arXiv 2510.18560 (ICLR 2026): https://arxiv.org/html/2510.18560v2
- Kuric et al., arXiv 2605.18311 (2026): https://arxiv.org/html/2605.18311

**P3: task and usability simulation, human-trace training**
- Kuric et al., arXiv 2605.18302 (2026): https://arxiv.org/html/2605.18302
- Zhong et al., arXiv 2507.02306 (2025): https://arxiv.org/abs/2507.02306
- Griesbach et al., HICSS 2026: https://scholarspace.manoa.hawaii.edu/items/efcf5ebc-496b-496e-b892-d8e38a554ca8
- Lost in Simulation, arXiv 2601.17087 (2026): https://arxiv.org/html/2601.17087v1
- UserLM, arXiv 2510.06552 (ICLR 2026): https://arxiv.org/html/2510.06552v2
- See, Think, Act, arXiv 2510.19245 (2025): https://arxiv.org/html/2510.19245
- Shop-R1, arXiv 2507.17842 (2025/26): https://arxiv.org/html/2507.17842v2
- Lu et al., arXiv 2503.20749: https://arxiv.org/html/2503.20749v4
- RecVerse, arXiv 2608.20707 (2026): https://arxiv.org/html/2608.20707
- AlignUSER, arXiv 2601.00930 (2026): https://arxiv.org/html/2601.00930v1
- PersonaTrail, arXiv 2607.20482 (abstract only): https://arxiv.org/abs/2607.20482

**A/B prediction, fine-tuning and calibration**
- Data-driven persona agents, arXiv 2609.01038 (2026): https://arxiv.org/html/2609.01038
- Hut & Masoero, arXiv 2608.02345 (2026): https://arxiv.org/abs/2608.02345
- Squoosh, arXiv 2608.07517 (2026): https://arxiv.org/html/2608.07517
- Persson et al., arXiv 2606.17165 (2026): https://arxiv.org/abs/2606.17165
- Spotify Engineering blog (Aug 2026): https://engineering.atspotify.com/2026/8/when-can-llms-replace-humans-in-a-b-tests/
- Augmented hypothesis testing, arXiv 2609.24629 (2026): https://arxiv.org/html/2609.24629
- LOLA, arXiv 2406.02611 / Marketing Science 2025: https://arxiv.org/html/2406.02611v3 and https://ideas.repec.org/a/inm/ormksc/v44y2025i5p995-1016.html
- Semantic-similarity rating, arXiv 2510.08338 (2025): https://arxiv.org/html/2510.08338

**Real studies: sample sizes, platforms, quality control**
- NN/g quantitative sample sizes (2021): https://www.nngroup.com/articles/summary-quant-sample-sizes/
- NN/g five users (2000): https://www.nngroup.com/articles/why-you-only-need-to-test-with-5-users/
- Prolific pricing: https://www.prolific.com/pricing
- Prolific authenticity checks: https://researcher-help.prolific.com/en/articles/445144-what-are-authenticity-checks
- Userbrain pricing: https://www.userbrain.com/pricing
- Lyssna pricing: https://www.lyssna.com/pricing/
- Maze pricing (no prices shown): https://maze.co/pricing/

**Community and datasets**
- UserSim @ NeurIPS 2026 workshop: https://usersim-workshop.github.io/
- Hugging Face API checks: https://huggingface.co/api/datasets/NEU-HAI/OPeRA, and the microsoft/UserLM-8b and biglab/uiclip model listings

**[U] Search results only, not opened**
- UXAgent: arXiv 2504.09407
- UXCascade: Adobe Research page, arXiv 2601.15777
- Customer-R1: arXiv 2510.07230
- Westwood PNAS 2025 coverage: 404media and research-live
- Prolific authenticity-check accuracy posts
- Maze pricing aggregators (cleverx, stackscored, vendr)
- Leiva et al., UAIS (DOI 10.1007/s10209-022-00910-x)
- Mind the Sim2Real Gap: arXiv 2603.11245
- ACL 2026 and ICLR 2026 venue listings