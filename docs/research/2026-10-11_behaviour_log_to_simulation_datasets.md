# Report: Public benchmarks for building customer simulators from behavior history and predicting held-out behavior

Date: 2026-10-11. I ran about 22 searches and fetches, reading primary sources (arXiv HTML pages, Hugging Face cards) wherever I could.
- **VERIFIED** means I read the item in a primary source during this session.
- **UNVERIFIED** means it comes from my prior knowledge or a secondary snippet and should be checked.
- **Fit** is a 0–3 score for this use case: per-user history as source, a held-out future or intervention response for the same user, and outcomes that matter for product decisions.

---

## Headline findings

1. **No public dataset fully matches the use case.** No public dataset I found gives, for the same users, a multi-session behavior history plus a later response to a randomized product change.
   - The closest partial matches are listed below.

   | Dataset | What it gives | What it lacks |
   |---|---|---|
   | OPeRA | About 10 sessions per user over 4 weeks, plus survey and interview persona | Users are few (51) and there is no intervention |
   | ConvApparel | Randomized good vs. bad recommender, with satisfaction outcomes | Each conversation is single-session, with no prior history |
   | X5 RetailHero and Hillstrom | Purchase history plus a randomized marketing treatment and outcome | Tabular data, not clickstream |
   | KuaiRand | Long histories plus randomly exposed items | No product-change intervention |
   | Twin-2K-500 | Rich persona plus held-out retest answers | Survey data, not behavior |

   AlignUSER's test against 55 real A/B tests is the best example of the "would the simulator predict the A/B result" protocol, but those A/B tests are **proprietary**.

2. **Fine-tuning and RL beat prompting by a wide margin on step-level action prediction.**
   - On Amazon-internal Shop-CART, Lu et al. report exact action accuracy of 11.9% prompted vs. 17.3% fine-tuned. Shop-R1 reaches 27.7%.
   - On OPeRA, the best prompted model (GPT-4.1) scores about 21.5%. SFT+RL methods reach about 38–40%.
   - **Caveat:** RL-trained simulators can become under-active (Shop-R1 and Customer-R1 show low click-through and conversion in the RecVerse comparison). Prompted simulators are over-active. Neither group matches real funnel rates.

3. **The same failure modes appear in every domain.**
   - Over-engagement and over-conversion (prompted shoppers buy instead of leaving).
   - Over-cooperation (τ-bench simulated users push agent success to 77.8% vs. 63.6% with real humans).
   - Simulated non-buyers never walk away.
   - Positivity bias.
   - Persona homogenization (low diversity).
   - Precision collapse when few items are actually liked.
   - Long context stops helping at around 32K tokens.

4. **Metrics: population-level realism does not predict decision fidelity.** Three 2026 papers reach this conclusion.
   - "Simulated Customers Never Walk Away": fixing the marginal statistics left the buyer vs. non-buyer contrast error unchanged (the "marginal-realism trap").
   - CUE: fidelity and mimicry metrics do not pick the best simulator for outcomes, and adding a persona can make outcome agreement worse.
   - Sim2Real Gap: higher general model capability does not imply a more faithful simulator.

   The metrics that bear on product decisions are:
   - outcome calibration (simulated vs. real success or conversion rates);
   - outcome-conditioned contrast (do simulated buyers and non-buyers differ the way real ones do);
   - counterfactual or A/B direction agreement (ConvApparel's good vs. bad recommender test; AlignUSER's Spearman correlation across 55 A/B tests; Agent4Rec's recommender ranking).

---

## 1. Web and e-commerce session datasets for LLM user simulators

### OPeRA (NEU-HAI) — VERIFIED
- **Citation:** Wang et al., "OPeRA: A Dataset of Observation, Persona, Rationale, and Action for Evaluating LLMs on Human Online Shopping Behavior Simulation". arXiv 2506.05606, ACL 2026. https://arxiv.org/abs/2506.05606 . Data: https://huggingface.co/datasets/NEU-HAI/OPeRA
- **Users and sessions:**
  - 51 users contributed sessions (84 were recruited).
  - About 4 weeks of real Amazon shopping per user.
  - Full version: 692 sessions and 28,904 action-observation pairs (about 13.6 sessions per user).
  - Filtered version: 527 sessions and 5,856 pairs.
- **Source behavior:**
  - Actions (click, scroll, input, navigate, tab), each with a timestamp.
  - Page observations (HTML, plus screenshots in the vision-language variants).
  - Rationales collected in the moment (207 annotated in the filtered set).
- **Persona data:**
  - Survey: demographics, shopping preferences, Big Five, MBTI, Consumer Styles Inventory.
  - Optional interview of about 20 minutes, with raw transcript and LLM summary.
- **Persistent user ID:** Yes. Session IDs encode user ID, start time and end time, so cross-session history for the same user can be built.
- **Split:**
  - The paper's test set is 15 randomly sampled users and 90 of their sessions (a new-user split, not a future-time split).
  - The Hugging Face data ships train and test splits.
- **Outcomes:** Session outcome (purchase or not), next action, rationale.
- **Licence:** CC-BY-4.0 tag on Hugging Face, but the card also says "intended for research purposes only". Commercial use is ambiguous; get legal review.
- **Best zero-shot results** (with persona and rationale):

  | Model | Exact action accuracy |
  |---|---|
  | GPT-4.1 | 21.5% |
  | DeepSeek-R1 | 14.8% |
  | Claude-3.7 | 10.8% |
  | Llama-3.3 | 8.3% |

- **Does the persona help?** Mixed. Removing it did not hurt exact accuracy (GPT-4.1 scored 22.06% without it). It did improve action-type and click-type F1. It hurt outcome F1 for GPT-4.1 (58.5 without vs. 47.5 with). Removing the rationale hurt consistently.
- **Paper inconsistencies:** 21.51 vs. 22.06 for the same GPT-4.1 figure; 992 vs. 902 test actions.
- **Fit: 3.** It is the only public set with repeated sessions per user plus survey and interview persona plus purchase outcomes. It is small (51 users) and has no intervention. You could build a future-session split yourself from the timestamps.

### Customer-R1 — VERIFIED
- **Citation:** Wang, Lu, Zhang, Huang, D. Wang. arXiv 2510.07230, NeurIPS 2025 (workshop or main track not confirmed). https://arxiv.org/abs/2510.07230
- **Data:** OPeRA-filtered (49 users). The split method is not described.
- **Method:** Persona block prepended to every step, then SFT followed by GRPO, with a reward for action correctness that is weighted by difficulty.
- **Results on Qwen2.5-7B:**

  | Setting | Exact accuracy | Macro-F1 |
  |---|---|---|
  | Zero-shot | 7.3% | — |
  | RL only | 24.7% | — |
  | SFT | 35.1% | — |
  | SFT+RL (Customer-R1) | 39.6% | 78.5 |

- **Persona ablation:**
  - Removing the persona gives 37.8% accuracy and Macro-F1 66.7.
  - Shuffling personas across users gives 28.9% accuracy and Macro-F1 38.9. This is strong evidence that user-specific conditioning matters once the model is trained.
- **Failure modes:**
  - RL alone reward-hacks: it almost never predicts input or terminate (0 of 40 terminate actions).
  - Bias toward frequent actions.
  - The reward ignores satisfaction and effort.

### Lu et al., "Can LLM Agents Simulate Multi-Turn Human Behavior? Evidence from Real Online Customer Behavior Data" — VERIFIED
- **Citation:** arXiv 2503.20749, ACL 2026. Amazon and Northeastern. https://arxiv.org/abs/2503.20749
- **Data:** 3,526 users, 31,865 sessions, 230,965 actions (4,432 purchases). The paper says "we are unable to release the dataset". **Not public.**
- **History used:** Within-session only; no cross-session user history.
- **Split:** Held-out test sessions not seen in training. Whether the split is by user or by time is not stated.
- **Results:**

  | Approach | Action accuracy | Purchase F1 |
  |---|---|---|
  | Best prompted (DeepSeek-R1) | 11.86% | 20.0 |
  | Qwen2.5-7B SFT | 16.67% | 26.9 |
  | Qwen2.5-7B SFT + synthesized reasoning | 17.26% | 33.86 |
  | Llama-3.2-3B SFT + reasoning | 15.77% | 33.99 |

- **Failure modes:** Prompted models over-purchase or keep sessions going where humans would leave; they overuse filters; they do not refine queries the way humans do.
- **Fit: 1.** Valuable methodology, but no access to the data.

### Shop-R1 — VERIFIED
- **Citation:** Zhang et al. arXiv 2507.17842, ICLR 2026. https://arxiv.org/abs/2507.17842
- **Data:** "Shop-CART" is in-house (52,137 sessions; 176,949 train / 1,879 test examples); not public. Appendix results on OPeRA.
- **Method:** Two-stage reward.
  - Rationale reward based on the model's own confidence (no rationale labels needed).
  - Tiered action reward: action type first, then sub-action details, scaled by difficulty, designed to resist reward hacking.
- **Results:**

  | Data | Zero-shot | SFT | Best |
  |---|---|---|---|
  | Shop-CART (Qwen-2.5-3B) | 0.32% | 16.76% | 27.72% (Shop-R1) |
  | OPeRA (Qwen2.5-VL-3B) | 6.41% | 20.23% | 38.44% (SFT+RL / Shop-R1) |

  On Shop-CART, plain SFT+RL with a binary reward scored 16.55%.

### RecVerse and the USB benchmark — VERIFIED (partly)
- **Citation:** "Towards Faithful Simulation of Human Shopping Behavior". arXiv 2608.20707 (Aug 2026). https://arxiv.org/abs/2608.20707
- **Data:** Homepage recommendation feed of an East Asian mobile e-commerce marketplace.
  - 5,222 users, 5,274 trajectories (about one per user), 69,842 actions.
  - GUI screenshots (pixel-level) plus action annotations.
  - Per-user profile and history summaries: on average 356 historical clicks and 10.4 purchases per user, supplied as context.
- **Split:** Not described.
- **Licence and release:** The paper says the benchmark is "released"; I did not find a licence or URL (UNVERIFIED).
- **Metrics:**
  - Behavioral fidelity against real users: ATL, CTR, ACR, CVR, IPVR.
  - Intent consistency: item-level and category-level hit rate and F1.
- **Results:**
  - RecVerse-GUI+RL reaches intent F1 7.19 vs. 4.27 for the STA baseline.
  - Its CVR is 4.87 vs. 13.54 for real users, so it still under-converts.
  - In human evaluation, annotators preferred real users over RecVerse 74% of the time, vs. 98% over STA.
- **Over- vs. under-activity:**
  - Prompted RecAgent and Agent4Rec over-interact (RecAgent ACR 80 vs. 16 real).
  - Shop-R1 and Customer-R1 under-interact.
- **Baselines named in the paper** (I did not verify these primary papers):
  - "A/B Agent" (Zhang et al. 2026a): prompted GUI vision-language model.
  - "STA / See-Think-Act" (Zhang et al. 2025a): imitation learning plus RL with step-level rewards.
- **Fit: 2.** Real users with history and conversion, but one trajectory per user and no intervention.

### WebShop human trajectories — UNVERIFIED (prior knowledge)
- **Citation:** Yao et al. 2022, NeurIPS, arXiv 2207.01206.
- **What it is:** About 12k crowdsourced instructions and about 1.6k human demonstrations on a simulated store.
- **Human performance:** MTurk workers score about 82 on average with about 50% success; experts reach about 60% success.
- **Licence:** MIT for the code (likely).
- **Fit: 0–1.** The tasks are instructed, not organic, and there is no per-user history.

### Mind2Web — UNVERIFIED
- **Citation:** Deng et al., NeurIPS 2023 D&B.
- **What it is:** 2,350 tasks with crowdworker action sequences on 137 sites. Licence CC BY 4.0 (likely).
- **Fit: 0.** Task-centric, with no user identity.

### Amazon-M2 — VERIFIED (licence only)
- **Citation:** Jin et al., NeurIPS 2023 D&B. arXiv 2307.09688. KDD Cup 2023.
- **What it is:** Millions of sessions across 6 locales. The task is next-item prediction from previous items in the session.
- **Licence:** Apache 2.0, per the paper.
- **Persistent user IDs:** I could not confirm any (likely session-only; UNVERIFIED).
- **Fit: 1.**

### RetailRocket — UNVERIFIED
- **What it is:** Kaggle dataset, about 2.76M view, add-to-cart and transaction events over 4.5 months, with a visitorid that allows cross-session history. Licence CC BY-NC-SA 4.0 (likely).
- **Fit: 1–2.** Has per-visitor history and purchases, but no intervention and is non-commercial.

---

## 2. Recommender and media behavior used for LLM user simulation

### Agent4Rec — VERIFIED
- **Citation:** Zhang et al., "On Generative Agents in Recommendation". SIGIR 2024, arXiv 2310.10108. https://arxiv.org/abs/2310.10108
- **Setup:** 1,000 agents initialized from MovieLens-1M, Amazon-Book and Steam histories. The persona is summarized from history (activity, conformity, diversity, taste). The simulator uses gpt-3.5-turbo.
- **Fidelity protocol and results:**
  - **Held-out preference discrimination.** Agents classify interacted vs. non-interacted items.

    | MovieLens ratio (liked : not liked) | Accuracy | Precision | F1 |
    |---|---|---|---|
    | 1:1 | 0.69 | 0.69 | 0.70 |
    | 1:9 | 0.62 | 0.21 | 0.32 |

    Precision collapses as liked items become rarer because agents pick a roughly fixed number of items.
  - **Rating distribution.** Matches the mode at 4, but agents give too few 1–2 ratings.
  - **"Would the simulator prefer the better recommender?"** Satisfaction scores rank the systems correctly overall (Random 2.93 < Most popular 3.42 < MF 3.80 / MultVAE 3.75 / LightGCN 3.85). The paper overstates LightGCN's lead.
  - It also replicates a filter-bubble effect.
- **Other failures:** Hallucinated items; the diversity trait has little behavioral effect.

### SimUSER — VERIFIED (abstract level)
- **Citation:** Bougie & Watanabe, ACL 2025 Industry Track. arXiv 2504.12722. https://aclanthology.org/2025.acl-industry.5
- **Method:** Self-consistent personas built from historical data, plus memory (episodic and knowledge-graph), perception (including thumbnails) and a "brain" module.
- **Results:** Claims closer micro- and macro-level alignment with real users than prior work. Offline A/B results were used to tune recommender parameters and improved real engagement. I did not find its own correlation number.

### AlignUSER — VERIFIED
- **Citation:** Bougie et al. arXiv 2601.00930, ACL 2026. https://arxiv.org/abs/2601.00930
- **Method** (on Qwen3-8B):
  - Train a world model that predicts the next page state.
  - Counterfactual reflection: sample 3 alternative actions, simulate them, then train the model on reasoning that explains why the human's action was better, together with the human action.
  - AlignUSER+ adds graph memory and causal validation of tentative actions.
- **Datasets:** MovieLens-1M, Steam, AmazonBook, OPeRA, plus **55 proprietary historical A/B tests** from a food recommendation platform.
- **Results:**

  | Metric | SimUSER | AlignUSER+ |
  |---|---|---|
  | Rating RMSE, MovieLens | 0.502 | 0.429 |
  | Purchase-rate gap on OPeRA (pts) | 9.9 | 2.1 |

  RecAgent's OPeRA purchase-rate gap is 16.3 points. Thought–action consistency on OPeRA rises from 64% to 89%. Spearman correlation with real A/B outcomes across the 55 tests is highest for AlignUSER+, but the values appear only in a figure.
- **Caveat:** Human-likeness is judged by GPT-4o, not humans.
- **Relevance:** This is the most directly relevant published protocol for "predict A/B outcomes", but the A/B data cannot be reproduced.

### RecAgent / USimAgent / iEvaLM — partly VERIFIED
- **RecAgent** (Wang et al. 2023): UNVERIFIED detail. In the RecVerse comparison it over-interacts.
- **USimAgent** (Zhang et al., SIGIR 2024; arXiv 2403.09142). VERIFIED: search-session simulator that issues queries, clicks and stops.
  - Better than prior methods at query generation.
  - Comparable to traditional click and stop models, which beat it when trained on enough data.
  - Code and data: github.com/Meow-E/USimAgent.
- **iEvaLM** (Wang et al., EMNLP 2023): LLM user simulator for conversational recommendation on ReDial and OpenDialKG. UNVERIFIED this session.

### Datasets — UNVERIFIED (well known; licences need checking)

| Dataset | Contents | Licence | Fit |
|---|---|---|---|
| MovieLens-1M | 6,040 users with timestamped ratings | Research-only; commercial use needs permission | 1 |
| Amazon Reviews 2023 (McAuley) | Per-user review histories | Research use | 1 |
| Yelp Open Dataset | Per-user history | Restrictive terms, non-commercial | 1 |
| MIND news | 1M users, impression logs with click and no-click | Microsoft Research licence, non-commercial | 1–2 |
| Steam, Goodreads (UCSD) | Per-user histories | Research use | 1 |

These support future-time splits of per-user ratings or clicks. MIND is the best of them for click-through-rate-style held-out targets.

### OmniBehavior — VERIFIED
- **Citation:** arXiv 2604.08362. https://arxiv.org/abs/2604.08362
- **Data:** Kuaishou logs from Sep–Nov 2025 for 200 representative users (chosen by clustering).
  - Interleaved video, live-stream, ads, e-commerce and search traces across 22 action types.
  - About 8.1k actions per user on average.
  - 6,000 prediction tasks covering binary actions, watch duration, and customer-service reply text.
- **Results:** All models are prompted only. The best overall score is 44.55 (Claude-Opus-4.5). Binary F1 is at or below 40%.
- **Failures:** Hyper-activity (40–60% overshoot of positive rates); positivity or utopian bias; persona homogenization; no gain from context beyond about 32K tokens; little help from RAG.
- **Release:** "After data audit" (not yet released, UNVERIFIED).
- **Fit: 2 once released.** Long per-user history, but no clear future-time split.

---

## 3. User-level experiment, uplift and churn datasets (for "predict response to an intervention")

| Dataset | Users | History | Intervention / target | Licence | Fit |
|---|---|---|---|---|---|
| **X5 RetailHero** (scikit-uplift `fetch_x5`) — VERIFIED structure | About 200k clients in train (UNVERIFIED count) | Full purchase transaction history before the communication (purchases.csv), plus a client table | treatment_flg (SMS communication), target = purchase afterwards. The docs do not state randomization; it was an RCT-style hackathon (UNVERIFIED) | Hackathon terms, unclear | **2.** Per-user transaction history plus a treatment response; the closest public analog to "simulate customer, predict response to campaign" |
| **Hillstrom MineThatData Email** — UNVERIFIED | 64,000 customers | 12-month summary only (recency, spend, men's/women's buyer, newbie, channel) | Randomized: men's email / women's email / no email. Outcomes: visit, conversion, spend over 2 weeks | Freely distributed by Kevin Hillstrom | **2.** True RCT, but the history is only summary features |
| **Criteo Uplift v2.1** — VERIFIED size and design | 13.9M rows from incrementality RCTs | 12 anonymized dense features; no behavior sequences | Treatment (ad exposure); visit and conversion | CC BY-NC-SA 4.0 (UNVERIFIED) | **1.** No interpretable history |
| **KuaiRand** (Gao et al., CIKM 2022, arXiv 2208.08696) — VERIFIED design | About 27k users in KuaiRand-27K; 1K and Pure subsets (UNVERIFIED counts) | Full sequential logs | Random videos inserted into normal feeds for 2 weeks, with 12 feedback signals | Open on Zenodo (likely CC BY-SA 4.0, UNVERIFIED) | **2.** Randomized exposure gives unbiased per-user responses to "new content" |
| **ConvApparel** (Google, EACL 2026, arXiv 2602.16938) — VERIFIED | Over 4,146 conversations, about 15k turns, from paid raters | No prior history | **Randomized good vs. deliberately bad recommender**, post-session survey, turn-level satisfaction and frustration labels | CC BY-SA 4.0 (paper) vs. CC-BY-4.0 (Hugging Face README); check | **2–3.** Best public counterfactual test of whether the simulator shifts outcomes in the right direction under a product change; data-driven simulators beat prompted ones on it |
| **KKBox churn** (WSDM Cup 2018, Kaggle) — UNVERIFIED | About 1M+ members | Transactions and daily listening logs | Churn in the next month (future-time) | Kaggle competition terms, non-commercial | **2** for churn prediction from history; no intervention |
| Telco churn (IBM/Kaggle) — UNVERIFIED | About 7k customers | Static attributes only | Churn label | — | **0–1** |
| Upworthy Research Archive | — | — | Aggregate headline A/B tests only, no user-level data | — | **0** for user-level work; could test population-level "which variant wins" |

I found no public user-level product A/B test logs that pair rich behavior history with the treatment arm.

---

## 4. Usability and UX behavior datasets

- **UXtweak / Kuric et al.** — VERIFIED that the papers exist; **no public dataset found.**
  - Kuric et al. publish studies on mouse dynamics and on GPT-4 follow-up questions in unmoderated tests (IJHCI 2025, 60 participants).
  - The data is not deposited publicly as far as I could find. Contact the authors.
- **Think-Aloud Usability Assessment of a Regional Atlas** (Popelka, Mendeley Data 2023) — VERIFIED.
  - Audio, transcripts, ELAN files and a results summary, in Czech. Small.
  - **Fit: 1.**
- **Synthetic Cognitive Walkthrough** (arXiv 2512.03568, CHI '26) — VERIFIED abstract.
  - LLMs completed more tasks with more efficient paths than humans, but flagged fewer failure points.
  - This is evidence of over-competence in usability simulation.
- **UXAgent** (arXiv 2502.12561 / 2504.09407, CHI EA '25) — VERIFIED.
  - LLM persona agents run web usability studies.
  - Evaluated only by a heuristic review from 5 UX researchers; no comparison against human ground truth.
- **HICSS-59, "Towards Simulating User Behavior for Automating Usability Tests"** — VERIFIED snippet.
  - Agents often failed to recognize task completion and overshot the goal.
- **Rico** (Deka et al., UIST 2017; 72k UIs with crowdworker interaction traces; CC BY 4.0) and **AndroidControl** (Li et al. 2024; about 15k human demonstrations; Apache 2.0) — UNVERIFIED.
  - Task demonstrations without user identity or think-aloud.
  - **Fit: 0–1.**
- **Gap:** I found no public think-aloud corpus that has task outcomes and repeated sessions per participant.

---

## 5. Conversation logs as user source data

- **WildChat-4.8M** (AllenAI) — VERIFIED.
  - Licence: ODC-BY.
  - Per-user fields: `hashed_ip` plus request headers (accept-language, user-agent) and timestamps from Apr 2023 to May 2024.
  - This allows per-user histories with a future-time split (approximate identity, since it is IP-based).
  - **Fit: 1–2** for conversational user modeling; no product outcomes.
- **LMSYS-Chat-1M** — UNVERIFIED.
  - Custom LMSYS licence agreement.
  - No stable user ID as far as I know, so per-user histories are not possible. **Fit: 0–1.**
- **UserLM-8b** (Microsoft / Georgia Tech, "Flipping the Dialogue", arXiv 2510.06552) — VERIFIED.
  - Full fine-tune of Llama-3.1-8B base on filtered WildChat-1M, conditioned on a "task intent".
  - 60–70% lower perplexity than baselines on WildChat and PRISM.
  - More diverse first turns and better termination detection than prompted assistants.
  - When users were simulated by UserLM, GPT-4o's task performance dropped from 74.6% to 57.4%, i.e., it is less over-cooperative.
  - Model licence MIT; training data and scripts not released.
- **"Lost in Simulation"** (arXiv 2601.17087, ICLR/ACL 2026) — VERIFIED abstract.
  - τ-bench retail with human participants in the US, India, Kenya and Nigeria.
  - Agent success varies by up to 9 points depending on which LLM plays the user.
  - Simulators underestimate success on hard tasks and overestimate it on moderate ones.
  - AAVE speakers get worse success and calibration, compounding with age.
- **"Mind the Sim2Real Gap in User Simulation for Agentic Tasks"** (Zhou et al., arXiv 2603.11245, COLM 2026) — VERIFIED.
  - 451 participants and 165 τ-bench tasks; 31 simulators evaluated.
  - Agent success is 63.6% with humans vs. up to 77.8% with general LLM simulators ("easy mode"). Specialized user-simulation models fall below the human baseline because of weak role-play.
  - Defines a User-Sim Index covering communication style, information pattern, clarification, error reaction, and outcome calibration (ECE). Best simulator: DeepSeek-V3.1 at 76.0, vs. 92.7 for agreement between human annotators.
  - Capability (Chatbot Arena Elo) does not predict fidelity.
  - Data release not stated.
- **CUE, Calibrated User Embeddings** (Kantharuban & Mueller, arXiv 2610.02460, Oct 2026) — VERIFIED.
  - Encodes real sessions into embeddings, samples new ones, and decodes them into persona commands for any LLM.
  - Evaluated on 483 human τ²-bench episodes, SimulatorArena and PRISM.
  - Key result: fidelity and mimicry metrics disagree with each other and do not pick the best simulator for outcomes. Adding a persona can make outcome agreement worse.
- **"Simulated Customers Never Walk Away"** (L. Chen, arXiv 2606.20708) — VERIFIED.
  - 2,790 production sales-agent conversations, 793 ending in verified payment. Private data.
  - Persona prompts built from real customer profiles.
  - Simulated non-buyers resist 13.5% of the time vs. 25.1% for real non-buyers.
  - After a pitch, simulated customers deliberate 75% of the time vs. 45% for real ones.
  - Telling the simulator it may disengage fixed the population-level marginals but not the buyer vs. non-buyer contrast.
  - Pressure tactics are over-rewarded by simulators.
- **Customer-support datasets with real CSAT or resolution labels:** I found none verified.
  - ABCD (Chen et al., NAACL 2021) has action and outcome labels but is collected via role-play (UNVERIFIED).
  - USS (Sun et al., SIGIR 2021) has turn-level satisfaction labels on MultiWOZ, SGD, ReDial, CCPE and JDDC, where JDDC is real e-commerce customer service (UNVERIFIED).
  - The Hugging Face "customer_qa_dataset" with CSAT fields looks synthetic; avoid it.
- **Adjacent, survey-based: Twin-2K-500** (Toubia et al., arXiv 2505.17479, Marketing Science) — VERIFIED.
  - 2,058 US participants, 4 survey waves, more than 500 questions.
  - Wave 4 retest gives a held-out target and a test–retest ceiling.
  - Persona text, summary and JSON are provided on Hugging Face (LLM-Digital-Twin org).
  - **Fit: 2** for the persona-to-held-out-response protocol, but it covers attitudes, not product behavior.

---

## Methodology synthesis

### How behavior history gets compressed into a simulator
1. **Persona summary from history or survey, prepended to prompts.**
   - Used by Agent4Rec, SimUSER, OPeRA, Customer-R1, Chen 2026.
   - Helps little zero-shot and is sometimes noise (OPeRA, Customer-R1 zero-shot). It becomes important after training: shuffling personas cuts Customer-R1 accuracy from 39.6% to 28.9%.
2. **Retrieval or memory over past actions.**
   - Episodic and graph memory (SimUSER, AlignUSER+), multi-level memory with visual fragments (RecVerse), RAG and summarization (OmniBehavior).
   - Returns flatten beyond moderate length (about 32K tokens; RecVerse also saw degradation with more memory).
3. **SFT on real traces, often with synthesized rationales.**
   - Consistent large gains over prompting (Lu et al.; OPeRA appendix in Shop-R1).
   - Synthetic rationales are capped by the model that generated them.
4. **RL with action or session rewards.**
   - Customer-R1 and Shop-R1 use GRPO with tiered and difficulty-weighted rewards; STA uses step rewards; RecVerse uses trajectory-level RL.
   - SFT followed by RL works best. RL alone reward-hacks toward frequent actions.
5. **World model plus counterfactual reflection.**
   - AlignUSER: the best reported purchase-rate calibration on OPeRA and A/B correlation.
6. **Purpose-trained user language models and user embeddings.**
   - UserLM (fine-tune on WildChat in the user role); CUE (embed real sessions, decode to personas).

### Failure modes to test for explicitly
- Over-conversion and over-engagement in prompted simulators (Lu et al.; RecVerse; OmniBehavior: 40–60% overshoot).
- Under-activity in RL-trained simulators (RecVerse critique of Shop-R1 and Customer-R1).
- Over-cooperation and "easy mode", with too little frustration or abandonment (Sim2Real Gap, UserLM, Chen 2026).
- Low diversity and persona homogenization (OmniBehavior; Agent4Rec diversity trait).
- Positivity bias (too few 1–2 ratings; overly polite support replies).
- Picking a fixed number of items, so precision collapses when positives are rare (Agent4Rec).
- Miscalibration that varies by task difficulty and by user demographic or dialect (Lost in Simulation).
- Over-competence in usability tasks (Synthetic Cognitive Walkthrough; HICSS-59).

### Evaluation metrics that predict usefulness for product decisions
Strongest to weakest:
1. **Counterfactual or A/B direction and magnitude agreement.**
   - Rank correlation between simulated and real lift across many past experiments (AlignUSER, Spearman over 55 tests).
   - Correct ordering of good vs. bad variants (ConvApparel; Agent4Rec recommender ranking).
   - This is the metric to build an internal benchmark around, using the company's own past A/B tests.
2. **Outcome calibration:** simulated vs. real conversion, task-success and churn rates, per segment (Sim2Real ECE; OPeRA purchase-rate gap).
3. **Outcome-conditioned contrast:** do simulated eventual non-buyers or churners behave differently from eventual buyers the way real ones do (Chen 2026). This catches cases where marginal realism looks fine but decisions are wrong.
4. **Step-level next-action accuracy and F1 on held-out sessions.** Useful for training signal, but weakly linked to decisions; accuracy is 20–40% even at the state of the art.
5. **Distributional and human-likeness judgements** (LLM-judged believability, rating histograms). The weakest predictors: CUE, Chen 2026 and Sim2Real all show they can diverge from outcome fidelity.

### Recommended evaluation design for your infrastructure
Since no public benchmark covers history plus intervention for the same users:
- Use **OPeRA** with a future-session split per user.
- Use **X5 / Hillstrom / KuaiRand** for response to randomized treatment.
- Use **ConvApparel** for counterfactual direction.
- Use **τ-bench human studies** (Sim2Real / Lost in Simulation) for over-cooperation.
- Then build a private benchmark from customers' own historical A/B tests: score the simulator on predicting lift sign and rank across experiments, plus segment-level outcome calibration.

---

## Key URLs
- OPeRA: https://arxiv.org/abs/2506.05606 ; https://huggingface.co/datasets/NEU-HAI/OPeRA
- Lu et al.: https://arxiv.org/abs/2503.20749
- Customer-R1: https://arxiv.org/abs/2510.07230
- Shop-R1: https://arxiv.org/abs/2507.17842
- RecVerse/USB: https://arxiv.org/abs/2608.20707
- AlignUSER: https://arxiv.org/abs/2601.00930
- SimUSER: https://aclanthology.org/2025.acl-industry.5
- Agent4Rec: https://arxiv.org/abs/2310.10108
- USimAgent: https://arxiv.org/abs/2403.09142
- OmniBehavior: https://arxiv.org/abs/2604.08362
- Simulated Customers Never Walk Away: https://arxiv.org/abs/2606.20708
- CUE: https://arxiv.org/abs/2610.02460
- ConvApparel: https://arxiv.org/abs/2602.16938 ; https://huggingface.co/datasets/google/ConvApparel
- Lost in Simulation: https://arxiv.org/abs/2601.17087
- Mind the Sim2Real Gap: https://arxiv.org/abs/2603.11245
- UserLM: https://arxiv.org/abs/2510.06552 ; https://huggingface.co/microsoft/UserLM-8b
- WildChat-4.8M: https://huggingface.co/datasets/allenai/WildChat-4.8M
- Twin-2K-500: https://arxiv.org/abs/2505.17479
- Amazon-M2: https://arxiv.org/abs/2307.09688
- KuaiRand: https://arxiv.org/abs/2208.08696
- Criteo uplift: https://arxiv.org/abs/2111.10106
- X5 RetailHero: https://www.uplift-modeling.com/en/latest/api/datasets/fetch_x5.html
- UXAgent: https://arxiv.org/abs/2502.12561
- Synthetic Cognitive Walkthrough: https://arxiv.org/abs/2512.03568
- Think-aloud atlas: https://data.mendeley.com/datasets/y6f9ykp4dt
- Also surfaced but not read: UserProxyBench (arXiv 2609.38043), SimBench (arXiv 2510.17516), RealUserSim (arXiv 2605.20204), "Beyond Action Imitation: decision-aware user simulator for online advertising" (arXiv 2607.26893).

No repo files were modified.