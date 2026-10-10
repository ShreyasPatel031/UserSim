# UserSim literature sweep: data selection, retrieval, calibration and infrastructure for LLM human simulation with little or no target data

Date: 2026-10-10. Sources are 2023-2026 primary sources. **Opened** means I read the page, PDF or HTML myself. **UNVERIFIED** means I only saw search-result or abstract text. I did not re-research the facts in the brief (SimBench 41→56; calibration breaking even at 25 labels and +2 at 100; Spotify; AIPW with 50-300 humans; Krsteski). Nothing was written to the repository; scratch files are in the session scratchpad only.

---

## 0. Bottom line

1. **Retrieved human evidence matters more than training, in published work as in ours.**
   - Evi-DA (Findings ACL 2026): removing the retrieved survey evidence nearly doubles error on new domains (JSD 0.23 → 0.44).
   - The untrained version (retrieval plus a two-step prompt, no RL) already scores 0.24 against 0.23 trained.
   - Meister et al. (NAACL 2025): showing the group's answer distributions on 5 similar questions beats persona descriptions.
   - Park et al. (2024/2026): agents built from surveys or interviews reach 82-86% of test-retest accuracy, against 74% from demographics alone.
   - Every one of these reports gains against open models of 32B or less. None compares against a frontier model.
2. **Pairing each human with a simulated twin (PPI, AIPW, DSL) mostly buys validity, not precision.**
   - Effective sample size rises only 13-14% (Broska et al., Krsteski et al., both as reported by Hullman et al. 2026).
   - Uniform PPI++ cuts error (MSE) by only 1.5-3.6%. The best weight on the LLM is zero for 26 of 68 and 40 of 133 questions (Ye & Yoganarasimhan 2026).
   - The gain is about 1/(1−ρ²), where ρ is the person-level correlation between simulated and real answers. Doubling the sample needs ρ ≥ 0.71, far above the person-level fit we already know about.
   - Large savings (over 50-90%) appear only where the predictor is trained on the same population, or in conjoint tasks where LLM output is used as a feature.
   - So our accuracy lever is population-level: evidence, anchors and shrinkage. PPI and AIPW are the validity wrapper around it.
3. **With no customer data, we can still give honest uncertainty, but it is wide.**
   - Tan & Zrnic (2026) widen intervals using only past tasks that have human data. These intervals cover 97% of 2020 ANES tasks, against 3% for naive intervals. The median width is 29.8 points on a 0-100 scale.
   - Huang, Wu & Wang (ICML 2025; revised 2026): GPT-4o is worth about 58 human respondents on OpinionQA, and 20 or fewer on maths questions.
   - This is the formal version of UserSim's promise to work without customer data. The model is worth tens of respondents, not hundreds.
4. **Spend humans where the simulator is least reliable.**
   - Allocating humans by predicted difficulty cuts error 10.5-11.4% at equal budget, against 1.5-3.6% for uniform allocation. That captures 61-79% of the best achievable gain.
   - Difficulty predicted from question text reaches Spearman 0.48-0.73.
   - Simile's error predictor from text embeddings reaches AUROC 0.686, against 0.730 for the hidden-state probe.
   - **Learn to predict error, not to learn mixing weights.** This fits our own failed transfer of per-question weights.
5. **Fine-tuned simulators carry over to new populations better than to new questions, and licences block most training data.**
   - Cao et al.: unseen questions score 0.78 against 0.88-0.89 for unseen countries (1−JSD).
   - DSA's gains shrink for new populations and with large training sets.
   - Brand et al.: fine-tuning on prior human results predicts new features within a product category, but not new categories.
   - Licences (HF API, checked today): SubPOP, GlobalOpinionQA, PersonaHub and SimBench are CC BY-NC-SA; BehaviorBench is NC-ND. WVS is free only for "non-profit purposes".
6. **No existing tool does what UserSim's harness would.**
   - Simulators (EDSL, TinyTroupe, Concordia) generate answers. Statistics libraries (ppi_py, mixedsubjects) correct them. Benchmarks score them. MCP servers (Althing, Minds) serve personas.
   - None combines: retrieval of licensed human evidence, calibrated distributions, intervals with and without target data, reliability scores with abstention, human-budget planning, and a prediction ledger.

---

## 1. PPI, PPI++, AIPW and doubly robust estimators, and how they are used with LLM respondents

| # | Source (date, venue / id) | Claim | Key numbers | Opened | What it means for UserSim |
|---|---|---|---|---|---|
| 1.1 | Angelopoulos et al., *Prediction-Powered Inference* (arXiv 2301.09633 v4, Nov 2023; Science 2023, UNVERIFIED: journal page returned 403) | Valid intervals for means, quantiles and GLM coefficients from a small labelled set plus ML predictions; no assumption about the model | Qualitative | arxiv.org/abs/2301.09633 | Foundation. Assumes the labelled sample is random from the target population |
| 1.2 | Angelopoulos, Duchi, Zrnic, *PPI++* (2311.01453 v2, Mar 2024) | Power-tuned PPI "always improve[s] on classical intervals" (asymptotically) | Qualitative | arxiv.org/abs/2311.01453 | Use PPI++ or weighted variants only, never plain PPI |
| 1.3 | Gronsbell et al., *Another look at inference after prediction* (2411.19908 v6, 19 Dec 2025) | Plain PPI can be *less* efficient than using the labels alone. Chen-Chen weighting fixes this | UK Biobank, weak predictor (R² 0.5): PPI relative efficiency 0.52, CC 1.28. Strong predictor (R² 0.8): PPI 1.39, CC 1.68. PPI helps only if ρ > ½·σŶ/σY | arxiv.org/html/2411.19908v6 | Ship CC or PPI++ weighting. Plain PPI hurts exactly where our person-level ρ is low |
| 1.4 | Hullman, Broska, Sun, Shaw, *This human study did not involve human subjects* (2602.15785, 17 Feb 2026) | Heuristic validation cannot rule out bias; statistical calibration is needed for confirmatory claims | Effective sample +13% (Broska et al.: 10,000 humans + 100,000 LLM predictions → at most 11,275); up to +14% (Krsteski et al.). Few studies check training-data leakage | arxiv.org/html/2602.15785v1 | Sell the small human sample as bias removal and validity, not as a precision multiplier |
| 1.5 | Broska, Howes, van Loon, *Mixed Subjects Design* (Sociol. Methods & Res. 54(3), 2025, DOI 10.1177/00491241251326865) | Treat LLM predictions as potentially informative observations; includes a power analysis for human vs LLM budget | +13% effective sample (via 1.4) | UNVERIFIED (IDEAS page seen only in search results) | Its power analysis is a template for our "how many humans" calculator |
| 1.6 | Ye & Yoganarasimhan, *Rectification Difficulty and Optimal Sample Allocation in LLM-Augmented Surveys* (2604.17267 v2, 9 Jul 2026) | Per-question "rectification difficulty" = Var(Y)(1−ρ²). Allocate humans by n_q ∝ √(w_q·A_q/c_q) (importance × difficulty ÷ cost). A meta-learner predicts difficulty with no pilot data | Twin-2K-500 (68 questions, GPT-4o) / CCES 2024 (133 questions, Gemini 2.5 Flash): uniform PPI++ MSE −3.6% / −1.5%; meta-learned allocation −11.4% / −10.5%; oracle −14.5% / −17.1% (captures 78.6% / 61.3%); meta-learner Spearman 0.73 / 0.48; LLM weight zero on 26/68 and 40/133 questions | arxiv.org/abs/2604.17267 and arxiv.org/html/2604.17267 | Most of the gain comes from *where* humans go. Needs a minimum per question at low budgets |
| 1.7 | Huang, Wu, Wang, *How Many Human Survey Respondents is a LLM Worth?* (2502.17773 v6, 24 Aug 2026; ICML 2025 prelim.) | Picks how many simulated responses to generate so that intervals cover human values, using past questions with human data. Guarantee is averaged over questions | 8 LLMs. OpinionQA (385 questions): GPT-4o ≈ 58 effective humans, the most of the 8. EEDI maths: about 20 or fewer. Simulating too many respondents gives overconfident intervals | arxiv.org/html/2502.17773 | A per-domain "worth N humans" number we can report. Recalibrate on every model or prompt change |
| 1.8 | Tan & Zrnic, *Valid Inference with Synthetic Data via Task Exchangeability* (2606.13629 v2, 21 Aug 2026) | **Zero target human data.** Widen the synthetic interval by the gaps seen on past tasks; point estimate = synthetic value + average past bias | ANES 2016→2020 (33 tasks): 97% coverage vs 3% naive, median width 29.8. Pew ATP 48 cells: 48/48 covered vs 0. Arena (280,737 comparisons): 100% vs 19% | arxiv.org/html/2606.13629v2 | The core of a "no customer data" mode. Wide when bias varies across tasks. Coverage is over tasks, not per task. Needs α₃ ≥ 2/(T+1), so enough past tasks |
| 1.9 | Emmenegger, Stahler, Podimata, *PPI Across Many Tasks* (2605.29249, 28 May 2026) | Fit a monotone (isotonic) recalibration on other tasks' labels, then correct within the task. A straight-line recalibration gives no gain over PPI++; nonlinearity is required | 72 tasks × 40 labels (14,400 Prolific annotations). With very few labels, power tuning undercovers, so they fixed λ = 1 | arxiv.org/html/2605.29249 | Pooling labels across tasks only pays if the model-to-truth map is nonlinear. Test that before building it |
| 1.10 | Byun et al., *Valid Inference with Imperfect Synthetic Data* (2508.06635 v2, 8 Oct 2025) | Hyperparameter-free GMM estimator adding moments from synthetic and proxy data | Lowest MSE on 8/8 tasks; MSE −50%+ and effective sample up to +50% when labels are scarce (text-annotation tasks, not survey simulation) | arxiv.org/html/2508.06635v2 | Asymptotic only. Shows the gain depends on how well synthetic and real residuals correlate |
| 1.11 | Zrnic & Candès, *Active Statistical Inference* (ICML 2024; 2403.03208 v3 Apr 2026) | Label where the model is uncertain; still valid for any model | Pew 2020 (XGBoost trained on the same survey): >85% / >70% labels saved vs classical, about 25% vs uniform PPI. ACS census: about 80% vs classical, >60% vs uniform | arxiv.org/abs/2403.03208v2 and arxiv.org/html/2403.03208v1 | Mix with uniform sampling (τ, default 0.5) or variance blows up when the uncertainty model is overconfident. Big savings come from a predictor trained in-population |
| 1.12 | Gligorić et al., *Confidence-Driven Inference* (NAACL 2025; 2408.15204) | Use LLM confidence to choose which items humans label | >25% fewer human annotations on 3 social-science text tasks | arxiv.org/abs/2408.15204 | Simulator confidence can choose which respondents or questions to buy |
| 1.13 | Wang, Zhang, Zhang, *LLMs for Market Research: A Data-augmentation Approach* (2412.19363 v3, 17 Apr 2026) | Debiased combination of LLM and human conjoint data | 24.9-79.8% of data saved; naive pooling saves nothing (vaccine and sports-car conjoint) | arxiv.org/abs/2412.19363 | Directly relevant to P4 (choice). Never pool LLM answers naively |
| 1.14 | Lu, Wang, Zhang, Zhang, *Generative Augmented Inference* (2604.14575 v3, 22 Jul 2026) | Use LLM outputs as *features* with a flexible link to human labels (orthogonal moments), not as stand-in labels | Conjoint: half the error and >75% fewer human labels; health insurance: >90% of labels saved (abstract only) | arxiv.org/abs/2604.14575 | Treat LLM output as a feature for P2-P4 preference estimation |
| 1.15 | Fisch et al., *StratPPI* (NeurIPS 2024; 2406.04291 v2) | Stratified PPI gives tighter intervals when the automatic rater's accuracy varies by stratum | No numbers on the abstract page | arxiv.org/abs/2406.04291 | Stratify by segment and question type |
| 1.16 | UNVERIFIED (search results only) | Bayesian PPI (Hofer et al. 2405.06034); DSL (Egami et al., NeurIPS 2023, 2306.04746: LLM labels 80-90% accurate still bias regressions; doubly robust with known sampling probabilities); Predictions as Surrogates (Ji, Lei, Zrnic 2501.09731, recalibrated PPI never worse than labels alone); Cost-optimal active evaluation (Angelopoulos et al. 2506.07949) | — | — | Background only |

**How many real labels are needed.**
- **Valid intervals:** any n in theory, but guarantees are asymptotic. With very small n, power tuning undercovers (1.9).
- **Bias removal:** 100 responses bring bias under 5% (Krsteski, known); 50-300 cut bias 93-99% (known).
- **Precision gain:** effective sample ≈ n/(1−ρ²), with the formula from 1.6. This gives about +4% at ρ = 0.2, +14% at ρ = 0.35, and 2× only at ρ ≥ 0.71.
- **No target labels:** you need instead tens of *past tasks* with paired human and synthetic data (1.7, 1.8). Tan & Zrnic's ANES case used only 33.

**Failure modes.**

| Failure | Evidence | Guard |
|---|---|---|
| Low person-level correlation gives no precision gain | 1.4, 1.6 (zero LLM weight on 30-40% of questions) | Use population-level anchors and shrinkage for accuracy |
| Plain PPI worse than classical | 1.3 (relative efficiency 0.52) | CC or PPI++ weighting |
| Small-n undercoverage | 1.9, 1.10, 1.11 | Fix λ = 1 at very small n; bootstrap |
| Labelled sample not representative | DSL (1.16), GAI extension (1.14), W22 overlap (known) | Known sampling probabilities; report ESS/N; abstain |
| Past tasks not relevant to the new one | 1.8 (penalty grows with how different the tasks are) | Weight past tasks by relevance; check coverage on fresh tasks |
| Coverage averaged over tasks, not per task | 1.7, 1.8 | Report as a portfolio guarantee, not per question |
| Overconfident uncertainty model | 1.11 | Mix in uniform sampling |
| Too many simulated respondents | 1.7 | Calibrate the simulated sample size |
| Model or prompt drift | 1.7 (calibration is for a fixed LLM plus prompt) | Recalibrate for each version, recorded in the ledger |

---

## 2. Retrieving related human data as priors, and transfer across datasets

| # | Source (date, venue / id) | What it does | Key numbers | Opened | What it means for UserSim |
|---|---|---|---|---|---|
| 2.1 | Pham, Qu, Li, Haffari, **Evi-DA** (Findings ACL 2026, pp. 20514-28) | Retrieves related WVS items with their answer distributions **for the same group**. Predicts a value signature per option, then the distribution. GRPO training | 6 open backbones (Qwen3 8/14/32B, Ministral 8/14B, Llama3-8B); 7 baselines; **no closed frontier models**. In-domain (GlobalOpinionQA Pew portion, 2,203 questions, WVS items removed as duplicates): JSD 0.16 vs 0.18 best baseline (Modular Pluralism), 0.29 log-probabilities. Out-of-domain (200 questions from 2025 Pew and YouGov, domains absent from WVS): 0.23 vs 0.29 / 0.39. Untrained pipeline 0.24. Ablations out-of-domain: no evidence 0.44, no value step 0.40. Retrieval depth K: big gains from 1 to 10, negligible beyond. Stronger encoders than BERT: negligible. Minimum-sample filter called "critical". Vietnam 0.31 vs US 0.12 after training | aclanthology.org/2026.findings-acl.1026 (+PDF) | Retrieval design to copy: same segment, related (not identical) items, K≈10, minimum support, cheap encoder. RL adds only about 0.01-0.02 JSD. Test the two-step "option profile" prompt |
| 2.2 | Huang, Li, Shao, **Distribution Shift Alignment (DSA)** (2510.21977 v2, 17 Apr 2026; ACL 2026 Findings UNVERIFIED) | Two-stage fine-tune: fit each subgroup's distribution, then learn one-attribute shifts between subgroup pairs (≥10 respondents each) | ESS11, ESS9, WVS, CGSS, CFPS; Qwen3-4B/32B, Llama3-8B. Wasserstein distance 0.106 vs 0.121 best fine-tuned baseline vs 0.135 "training set as answer" (Qwen3-4B). Beats the training data on 93.9-98.8% of backgrounds. "Saves 53.5-69.1%" of data, but the formula is not stated | arxiv.org/abs/2510.21977 and arxiv.org/html/2510.21977v2 | One-attribute shift is a segment-transfer prior for P4 by segment. Gains are largest for mid-size surveys and smaller for new populations; assumes independent attributes |
| 2.3 | Suh et al., **SubPOP** (ACL 2025; 2502.16761) | Fine-tune on subgroup answer distributions (Pew ATP, 3,229 questions); evaluate on GSS (a different survey family) | Wasserstein distance −32-46% on OpinionQA and −39-42% on GSS vs best baseline; unseen subgroups +43-45%; 25% of the data gives 72-78% of the gain; human floor 0.031-0.033 vs 0.094-0.121 after fine-tuning. Duplicates removed at embedding cosine 0.87 plus manual check. Data licence CC BY-NC-SA | arxiv.org/html/2502.16761v2 | Transfer across survey families exists, but the dataset is non-commercial. Reuse its 0.87 dedup rule |
| 2.4 | Cao et al., *Specializing LLMs to Simulate Survey Response Distributions* (NAACL 2025; 2502.07068) | KL fine-tune on WVS country distributions | Llama3-8B-Instruct 1−JSD 0.613 → 0.823. Unseen country, seen question 0.88-0.89; **unseen questions 0.78**; unseen survey (Pew) 0.617 → 0.767. No dedup described | arxiv.org/html/2502.07068v2 | New questions are the hard case, which is exactly where retrieval helps |
| 2.5 | Meister, Guestrin, Hashimoto, *Benchmarking Distributional Alignment* (NAACL 2025; 2411.05403) | Compares how the model is steered and how it outputs the distribution | Asking the model to write out the distribution is best (total variation about 0.20-0.23 for Opus, GPT-4 and Llama-70B) vs GPT-4 log-probabilities 0.550 (worse than uniform, 0.363) and 0.273 after temperature scaling. Human "guess others" baseline 0.25. Few-shot with the group's distributions on 5 similar questions helps every model except GPT-3.5 and reduces stereotyping. Non-political topics are harder | arxiv.org/html/2411.05403v1 | Confirms written-out distributions plus evidence examples. Persona prose is the weakest kind of steering |
| 2.6 | Park et al., *LLM Agents Grounded in Self-Reports* (2411.10109 v3, 28 Jun 2026) | Agents for 1,052 people built from interviews, surveys or demographics | Held-out GSS items, as % of the person's own test-retest: interview 83%, survey 82%, both 86%, demographics only 74% | arxiv.org/abs/2411.10109 | Prior answers beat demographics. Combining sources adds little |
| 2.7 | Hu & Collier, *Quantifying the Persona Effect* (ACL 2024; 2402.10811) | Persona variables explain little of what people answer | <10% of variance; a 70B model with persona prompting captures 81% of what a regression on persona variables achieves | UNVERIFIED (abstract via search) | Demographics-only personas have a low ceiling |
| 2.8 | Zhao, Dang, Grover, **GPO** (ICLR 2024; 2310.11523) | A transformer that learns from a few examples, trained across many groups, predicts a group's preferences | Beats in-context steering and fine-tuning (no numbers on the abstract page) | arxiv.org/abs/2310.11523 | Learning across groups is feasible in principle; no evidence against frontier models |
| 2.9 | Kim & Lee, *AI-Augmented Surveys* (2305.09620 v4, 19 May 2026) | Question, respondent and period embeddings on GSS 1972-2021 | Filling in past years works well; predicting never-asked questions is "modest" (no numbers on the page) | arxiv.org/abs/2305.09620 | Same pattern as ours: known questions are easy, new ones hard |
| 2.10 | Ku et al., *Silicon Sampling via Cross-Survey Transfer* (2607.03091, 3 Jul 2026) | Given a person's answers to some questions, predict other questions (Taiwan TEDS 2024) | Zero-shot 27-120B models about 52%, within 6pp of a random forest trained in-population; 67% (partisanship) to 23% (sovereignty) | arxiv.org/abs/2607.03091 | Reliability varies by topic, so per-topic reliability is a feature |
| 2.11 | Amini, *Survey Transfer Learning* (2501.06577 v2, Nov 2025) | Non-LLM network pretrained on CES 2020, fine-tuned on ANES 2020 | Up to 93% accuracy; reported to beat LLMs on sensitive items (abstract only) | arxiv.org/abs/2501.06577 | A cheap tabular baseline every LLM arm must beat |
| 2.12 | Brand, Israeli, Ngwe, *Using LLMs for Market Research* (MSI working paper, 12 Nov 2025) | GPT-3.5 conjoint willingness to pay | Fine-tuning on prior human results gives accurate willingness to pay for *new features in the same category*; may not extrapolate to unrelated categories; segment differences may need separate models (no numbers on the page) | msi.org/working-paper/using-llms-for-market-research-2/ | Customer data has value within a category. Do not promise transfer across categories |
| 2.13 | SurveyPilot (Pham et al., ACL 2025, 2025.acl-long.221) | Gathers opinions from Reddit and X and aggregates them | Inside Evi-DA's tables: JSD 0.23 in-domain and 0.33 out-of-domain, worse than survey evidence (0.16 / 0.23) | Numbers opened via the Evi-DA PDF; SurveyPilot's own claims UNVERIFIED | Social-media opinions are a weaker prior than survey distributions |

**Which external data helps most, ranked:**
1. The same question answered by neighbouring populations (our own +14.7).
2. The same population on related questions: Evi-DA (−48% JSD), Meister, SubPOP.
3. Prior self-reports from the same people: 82-86% vs 74% (2.6).
4. Prior human results in the same product category: 2.12, and the Spotify calibration we already know.
5. Social-media opinions: 2.13.
6. Synthetic personas: no accuracy evidence. Nemotron-Personas is CC BY; PersonaHub is NC.

**Learning across surveys that works** targets error size (1.6), monotone recalibration maps (1.9) and gap distributions (1.8). None of it learns per-question evidence weights, which matches our negative result.

---

## 3. Choosing which humans or questions to collect, and confidence in simulated answers

| # | Source | Mechanism | Key numbers | Opened | What it means for UserSim |
|---|---|---|---|---|---|
| 3.1 | Ye & Yoganarasimhan 2026 (1.6) | Allocate humans across questions by the square-root rule on predicted difficulty | −10.5 to −11.4% MSE vs −1.5 to −3.6% uniform | see 1.6 | Default rule for the human-budget planner |
| 3.2 | Active inference (1.11), confidence-driven inference (1.12) | Sample respondents or items with probability rising with model uncertainty | About 25% vs uniform (Pew); >25% fewer annotations | see above | Choose *which respondents* within a question |
| 3.3 | Wang, Wu, Zeevi, *Adaptive Querying with AI Persona Priors* (ICML 2026; 2605.00696 v2, 30 May 2026) | Dictionary of 2,058 Twin-2K-500 personas, each with GPT-5-mini answer distributions; closed-form posterior; greedy choice of the next question | WorldValuesBench (91 questions, 88,459 users), log loss at 5 questions: greedy 1.019 vs random 1.033 vs best adaptive-test baseline 1.074. From 15 questions on, a fixed set wins (0.977 at 20). Adds new items immediately by prompting | arxiv.org/abs/2605.00696 and HTML v2 | Short adaptive screener to place a customer's respondents into segments. Gains are small and only at small budgets |
| 3.4 | Simile confidence model (blog, about Sep 2026) | Predicts TVD error per question | About 8,600 held-out questions. AUROC for TVD < 0.16: basic features 0.566, embedding regression 0.686, probe 0.730, fine-tuned head 0.736 (not significantly better than the probe), stock fine-tune 0.720. "High" bucket meets 0.16 95% of the time vs 38% for "Low". No abstain or routing to humans described | simile.com/blog/confidence | An embedding regression gets most of the way. Add our features (evidence support, disagreement between sources) |
| 3.5 | Huang et al. (1.7), Tan & Zrnic (1.8) | Calibrated simulation size and intervals widened by past gaps | see above | see above | The closest published analogues of conformal prediction |
| 3.6 | Conformal prediction applied to simulated answer distributions | Searched; no paper found applying split-conformal prediction sets to survey distributions | General caveats: exchangeability and coverage averaged over cases (e.g. arXiv 2609.04445: coverage 90% → 74% under multi-agent peer pressure; UNVERIFIED) | search only | A gap UserSim could publish into |
| 3.7 | Angelopoulos et al., cost-optimal active evaluation (2506.07949, Jun 2025) | Split a budget between a cheap weak rater and an expensive strong one | Cold-start uncertainty is hard; a fixed sampling rate already helps | UNVERIFIED (search) | Supports a fixed human fraction as the fallback |

---

## 4. Curating data for training simulators: what transfers, leakage and licences

**What transfers:**
- Survey distributions carry over across survey families: SubPOP, Pew → GSS, −39-42% Wasserstein distance.
- They carry over to new countries, much less to new questions: Cao, 0.88 vs 0.78.
- Shift learning works within the training population: DSA.
- Retrieved evidence carries over to new domains: Evi-DA, 2025 questions.
- Behavioural corpora: OdysSim (2606.14199 v2, opened) uses 62 datasets, about 10B tokens and 21.4M interactions. Each specialist model is best on its own task family, with perplexity elsewhere 1.5-2.7× worse. A 90:10 mix with generic chat data costs little. **No published ablation says which source type (surveys, experiments, reviews, logs) transfers best.**
- Product data: helps within a category only (2.12).

**Leakage controls seen in the literature:**
- SubPOP: embedding cosine 0.87 plus manual check, and survey waves excluded.
- Evi-DA: duplicated WVS items removed from the test set; new-domain questions released in 2025.
- OdysSim: MinHash dedup and persona-disjoint splits.
- Cao: none described.
- Hullman: few studies test for memorisation. I found no study that measures the drop between questions fielded before and after a model's training cutoff.

**Licences** (HF API and terms pages, checked 2026-10-10):

| Source | Licence or terms | Commercial training? |
|---|---|---|
| Twin-2K-500 | CC BY 4.0 | Yes |
| Psych-101 | Apache-2.0 | Yes |
| Nemotron-Personas (USA, JP, KR, FR, IN, SV) | CC BY 4.0 (synthetic; sample rows show inconsistencies; source of census grounding not visible) | Yes, as scaffolding |
| Upworthy | CC BY (known) | Yes |
| SubPOP (jjssuh/subpop), GlobalOpinionQA, PersonaHub, SimBench | CC BY-NC-SA 4.0 | No |
| BehaviorBench | CC BY-NC-ND 4.0 | No |
| WVS | "available without restrictions, provided... used for non-profit purposes"; no redistribution | No; even internal use by a for-profit is doubtful. Ask WVSA |
| Pew (non-ATP datasets) | Royalty-free licence to access, copy and reproduce; redistribution limited to excerpts (terms effective 25 May 2018) | Internal use plausible; ATP has its own login-gated terms (UNVERIFIED) |
| GSS | Terms page does not address commercial use | Ask gss@norc.org (UNVERIFIED) |
| ANES | "solely for research or statistical purposes" (search snippet, UNVERIFIED) | Doubtful |
| ESS | "freely accessible"; conditions page not read (UNVERIFIED) | Ask |
| SocSci210, Amazon Reviews'23 | No licence on the HF card | Ask |
| OpinionQA mirror (timchen0618) | Tagged MIT, but Pew's terms still apply (judgment) | No reliance |

---

## 5. Open-source infrastructure and how UserSim can position its harness

| Tool | Type | Provides | Lacks | Licence / activity | Opened |
|---|---|---|---|---|---|
| Expected Parrot **EDSL** | Simulation DSL | Typed questions, skip logic, trait-based agents, scenarios, many models, automatic caching, remote runs (Coop), "Humanize" web surveys, Prolific launch | No calibration, weighting, statistical correction, evidence retrieval or MCP (README says "validate with real human data") | MIT; PyPI 1.0.9 (6 Oct 2026); 503 stars | github.com/expectedparrot/edsl, docs.expectedparrot.com |
| **TinyTroupe** (Microsoft) | Persona simulation | TinyPerson/TinyWorld, persona factory, extraction, an empirical validator (t-test or KS against real data, added in v0.6.0) | No calibration or MCP; "research and simulation only" | MIT; v0.7.0 (28 Mar 2026); 7.6k stars | github.com/microsoft/TinyTroupe |
| Concordia / OASIS / AgentSociety | Agent-based simulation | Social and environment simulation | No survey calibration | Apache-2.0; PyPI 2.4.0 (Mar 2026) / 0.2.5 (Dec 2025) / 1.5.7 (Mar 2026) | PyPI JSON |
| **ppi_py** | Statistics | PPI, PPI++, cross-PPI, bootstrap; mean, median, OLS, logistic; a mixed-subjects example | No LLM or survey integration, no retrieval | MIT; 301 stars; PyPI 0.2.3 (Dec 2024) | github.com/aangelopoulos/ppi_py |
| mixedsubjects (R) | Statistics | 7 treatment-effect estimators, variance, budget-optimal design | Same as ppi_py | UNVERIFIED (CRAN r-universe, search only) | — |
| **SynthBench** | Benchmark | 9 survey datasets (GSS and NTIA public; others gated); a similarity score (SPS); claims a 3-model ensemble beats single models by 5-7 SPS | No statistical correction; 0 stars | MIT | github.com/DataViking-Tech/SynthBench |
| **Althing** | Panel CLI plus **MCP** (12 tools: run_panel, quick_poll, persona packs...) | 15 packs, about 339 personas; `--calibrate-against` *compares* a run with a human distribution | No correction, intervals or retrieval; 2 stars | MIT | github.com/DataViking-Tech/Althing |
| **Minds MCP** | Hosted MCP (32 tools, including recalibrate_audience) | Synthetic audiences and studies | Closed implementation; no published validation | Docs-only repo, MIT | github.com/minds-ai-co/minds-mcp |
| Research code: Evi-DA, SurveyPilot, SubPOP, AlignSurvey (AAAI 2026; 44K interviews plus 400K survey records, UNVERIFIED) | Papers | Reproducible baselines | Research licences | — | linked in the papers |

**Positioning.** EDSL is the natural front end to build on: MIT licence, caching, Prolific integration. ppi_py supplies the estimators. UserSim's harness fills the missing middle layer:
- a licence-aware registry of human evidence, with retrieval;
- calibrated distribution prediction;
- intervals without target data (task exchangeability) and with target data (PPI++ / CC / AIPW);
- predicted reliability with abstention;
- a human-budget planner;
- a pre-registered prediction ledger.

Exposed over MCP, this has no open equivalent.

---

## 6. Recommended predictability-harness architecture, in order of expected lift

| Order | Component | Evidence for the lift | Expected lift (judgment where marked) |
|---|---|---|---|
| 0 | **Data registry and leakage guard** (prerequisite): licence tier, provenance, timestamps relative to model cutoffs, population-overlap rule (our leak fix), embedding dedup at 0.87 | 2.3, 2.1, section 4 | Protects every number; no lift |
| 1 | **Evidence retrieval**: (a) same question, neighbouring segments; (b) same segment, related questions (K≈10, minimum support N, cheap encoder); (c) the customer's past tests and ledger stimuli | Ours +14.7 S; Evi-DA 0.44 → 0.23 JSD; Meister few-shot | Largest by far |
| 2 | **Distribution reader**: frontier LLM writes out the distribution, optionally through a two-step "option profile"; fixed weights per source type; optional 2-3 model ensemble | Meister (writing out beats log-probabilities); Evi-DA without value step 0.40 vs 0.23; SynthBench ensemble claim | Moderate; two-step and ensemble are untested on frontier models |
| 3 | **Calibration across past tasks, no target data**: spread and temperature per source type; bias correction per task family; task-exchangeability intervals; a "worth N humans" number per domain | 1.8 (coverage 3% → 97%); 1.7; Meister temperature scaling (0.55 → 0.27 for log-probabilities) | Small accuracy gain; large gain in honesty and coverage |
| 4 | **Reliability model and abstain**: predicts error from question embedding, evidence support, disagreement between sources, entropy | 3.4 (AUROC 0.69-0.74); 1.6 (Spearman 0.48-0.73) | Enables abstention and routing |
| 5 | **Human-acquisition planner**: square-root allocation by predicted difficulty, uncertainty sampling mixed with uniform, a per-question minimum | 1.6 (−10-11% MSE at equal budget); 1.11 / 1.12 (≥25% labels saved) | About 10-25% budget efficiency |
| 6 | **Small-data rectification and validity wrapper**: anchor shrinkage at population level (accuracy) plus CC / PPI++ / AIPW intervals (validity); per-customer calibration ladder (≥25 labels); isotonic recalibration across tasks if nonlinear | Known AIPW 93-99% bias cut; 1.3, 1.9 | Bias removal; +13-14% effective sample from twin pairing |
| 7 | **Ledger and backtests**: pre-registered predictions, outcome import, rolling coverage, monthly fresh public questions | Hullman (leakage, pre-registration) | Builds the past-task bank that steps 3-5 need |
| 8 | **Optional fine-tuned evidence reader**, on commercial-licence data only (Twin-2K, Psych-101, Upworthy) | 2.2-2.4 (gains only vs open baselines) | Last; gated by E1 below |

**By stage.** P1 (answer distributions) uses steps 1-3 and 6. P2 (first-impression preference) and P4 (overall choice) add the customer's past tests (1c), the LLM-as-feature estimators (1.13, 1.14) and DSA-style segment shifts (2.2). P3 (preference after attempting tasks) has almost no literature; it needs human anchors plus our agent traces.

---

## 7. Next experiments

| ID | Tag | Experiment | Metric and success threshold |
|---|---|---|---|
| F1 | FREE | Task-exchangeability intervals (Tan & Zrnic) on SimBench, leaving one dataset out, around the 55.8 pipeline; add average past bias per source type to the point estimate | Coverage within ±3pp of nominal 80/90% across held-out datasets; report median width; point correction ≥ +0.5 S |
| F2 | FREE | Evi-DA retrieval sweep: K ∈ {1,3,5,10,20,40}; same vs other segment; minimum support N ∈ {0,30,100}; small vs large encoder | ≥ +1 S, or equal S with ≥50% fewer tokens; expect saturation near K = 10 |
| F3 | FREE | Two-step "option profile" prompt (which segment picks each option) vs direct, on divided questions | ≥ +1 S on divided questions (our residual error is ordering and heights) |
| F4 | FREE | Spread calibration (one temperature per source type) fitted on the other datasets | Ratio of predicted to human SD within 0.9-1.1, and ≥ +0.5 S |
| F5 | FREE | Error predictor, leaving one dataset out (embedding, evidence support, disagreement between sources, entropy) | AUROC ≥ 0.72 for "error below threshold", ≥ +0.03 over entropy or disagreement alone, Spearman ≥ 0.5 |
| F6 | FREE | Budget-allocation simulation on SimBench, Twin-2K-500 and CCES-like data: uniform vs square-root on F5 predictions vs oracle | ≥ 8% lower MSE than uniform, ≥ 50% of the oracle gain |
| F7 | FREE | Rectifier bake-off on Twin-2K-500 (CC BY): classical, PPI++, CC, AIPW, empirical-Bayes population shrinkage; n ∈ {25, 50, 100, 200}; 1,000 resamples | MSE, coverage ≥ nominal −2pp, effective sample; pick the default (expect ≤1.15× from twin pairing) |
| F8 | FREE | Leakage audit: 0.87 embedding dedup of eval items against the evidence bank; compare with public 2026 poll toplines released after model cutoffs | Drop after cutoff ≤ 2 S; otherwise re-baseline the headline numbers |
| F9 | FREE | Persona-prior adaptive screener (Twin-2K dictionary) for assigning segments with ≤5 questions | ≥ 0.01 lower log loss at 5 questions vs random (paper: 0.014) |
| F10 | FREE | Licence registry and gate in code | 100% of sources tagged; NC sources blocked from commercial training paths |
| E1 | EXPERIMENTAL | Frontier model with Evi-DA-style evidence in context, on Evi-DA's 200 out-of-domain 2025 Pew/YouGov questions (WVS evidence for research only; check terms first) | JSD ≤ 0.16 beats the best trained ≤32B model (0.16-0.23), which closes the "train an evidence reader" option |
| E2 | EXPERIMENTAL | Monthly pre-registered predictions on newly released public polls (Pew, Gallup, YouGov, AP-NORC), feeding the past-task bank | Coverage within ±5pp of nominal over 3 months; stable TVD; a public track record |
| E3 | EXPERIMENTAL | 3-model ensemble of written-out distributions on the evidence pipeline | ≥ +1 S, CI above 0, at ≤3× cost |
| I1 | INCREMENTAL | About 600 Prolific respondents a month on fresh concept and message questions, randomised between uniform and planner allocation (step 5) | ≥10% lower MSE at equal spend; model + n humans ≥ 1.5× effective sample |
| I2 | INCREMENTAL | Segment-shift study: anchor in segment A plus the model, predicting segment B (DSA-style), against a direct n = 50 sample from B | Shifted anchor beats model alone by ≥30% TVD and matches or beats n = 50 direct |

**Highest-leverage next steps:**
1. F1 and F5 together give the honest "no customer data" mode and the confidence layer.
2. F2 and F3 squeeze the evidence layer that drives most of the lift.
3. E1 settles whether any fine-tune is worth doing.
4. F6, F7 and then I1 settle how to spend human money.
5. F8 and F10 protect the claims.

---

## 8. Unverified or open

- Science venue for PPI (journal page returned 403).
- Mixed-subjects journal page and R package; Bayesian PPI, DSL and Predictions-as-Surrogates details; cost-optimal active evaluation (search results only).
- DSA's ACL acceptance; AlignSurvey figures and licence.
- HuMCal (Leng et al.; SSRN returned 403).
- Hu & Collier figures (abstract seen only via search results).
- Commercial terms for Pew ATP, GSS, ANES and ESS.
- Nemotron's census grounding.
- SynthBench's ensemble claim (in its own README; not independently checked).
- GPO and Kim & Lee figures (not on the abstract pages).
- No source found that measures accuracy before vs after a model's training cutoff for surveys.
- No source found that applies conformal prediction sets to simulated answer distributions.

## Sources (opened unless marked)

aclanthology.org/2026.findings-acl.1026 (+.pdf) · arxiv.org/abs/2510.21977 · arxiv.org/html/2510.21977v2 · arxiv.org/abs/2301.09633 · arxiv.org/abs/2311.01453 · arxiv.org/html/2411.19908v6 · arxiv.org/html/2602.15785v1 · arxiv.org/abs/2604.17267 · arxiv.org/html/2604.17267 · arxiv.org/html/2502.17773 · arxiv.org/html/2606.13629v2 · arxiv.org/html/2605.29249 · arxiv.org/html/2508.06635v2 · arxiv.org/abs/2403.03208v2 · arxiv.org/html/2403.03208v1 · arxiv.org/abs/2408.15204 · arxiv.org/abs/2406.04291 · arxiv.org/abs/2412.19363 · arxiv.org/abs/2604.14575 · arxiv.org/html/2502.16761v2 · arxiv.org/html/2502.07068v2 · arxiv.org/html/2411.05403v1 · arxiv.org/abs/2305.09620 · arxiv.org/abs/2411.10109 · arxiv.org/abs/2310.11523 · arxiv.org/abs/2607.03091 · arxiv.org/abs/2501.06577 · arxiv.org/abs/2605.00696 · arxiv.org/html/2605.00696v2 · arxiv.org/abs/2609.10280 · arxiv.org/html/2606.14199v2 · msi.org/working-paper/using-llms-for-market-research-2/ · simile.com/blog/confidence · worldvaluessurvey.org/AJDownloadLicense.jsp · pewresearch.org/terms-and-conditions/ · gss.norc.org/terms-and-conditions · europeansocialsurvey.org/data-portal · huggingface.co/api/datasets (licence queries) · huggingface.co/datasets/nvidia/Nemotron-Personas-USA · pypi.org/pypi/{edsl, tinytroupe, gdm-concordia, camel-oasis, agentsociety, ppi-python}/json · github.com/expectedparrot/edsl · docs.expectedparrot.com · github.com/microsoft/TinyTroupe · github.com/aangelopoulos/ppi_py · github.com/DataViking-Tech/SynthBench · github.com/DataViking-Tech/Althing · github.com/minds-ai-co/minds-mcp.

Search results only (UNVERIFIED): ideas.repec.org/a/sae/somere/v54y2025i3p1074-1109.html · cran.r-universe.dev/mixedsubjects · arxiv.org/abs/2405.06034 · arxiv.org/abs/2306.04746 · arxiv.org/abs/2501.09731 · arxiv.org/abs/2506.07949 · aclanthology.org/2024.acl-long.554 · aclanthology.org/2025.acl-long.221 · arxiv.org/abs/2511.07871 · electionstudies.org/data-center/ · arxiv.org/abs/2609.04445.