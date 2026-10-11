# Research report: Customer digital twins, synthetic users and how they are validated (as of 2026-10-11)

**How to read this.** I ran about 25 web searches and read primary sources where I could. **[VENDOR]** means a company's own claim, with no independent check. **[INDEP]** means a peer-reviewed paper or a preprint whose method you can inspect, by authors outside the vendor. **[UNVERIFIED]** means I saw it only in secondary coverage and could not confirm it in a primary source. I read the full text of only one paper, Park et al. 2024 (pdftotext). Every other figure comes from arXiv abstract pages or secondary coverage, and I mark the secondary-only ones.

**Bottom line**
- **Vendors.** Every vendor accuracy number I found is self-reported or funded by the vendor. None has released a benchmark from customer data. Of the commercial players, only Simile, through Gallup, is having its method checked independently, and those results are not out yet.
- **Academic work.** The best-grounded paradigm is the interview-based twin scored against people's own test-retest consistency (Park et al.). The critical work agrees across studies: aggregate results look fine, individual-level signal is weak, and the honest way to use twins is to calibrate them against a small human sample (Peng/Gui et al.; Hullman et al.; Tigre and Souto; Wang et al.).
- **The gap.** Nobody has an open, standard pipeline that turns a company's own interviews plus behavioral data into twins and scores them against held-out future behavior. Both an open-source pipeline and a benchmark built from public data are open to build.

---

## 1. Companies and products

| Company | What goes in | What comes out | Validation published | Public data or benchmark |
|---|---|---|---|---|
| **Simile** (Park, Bernstein, Liang; Stanford spinout) | About 2-hour AI-led interviews plus survey items (the Gallup Panel: about 1,000 members interviewed from fall 2025) | "Agent banks" that answer new questions at the individual and population level; aims at "a foundation model that predicts human behavior" | **[VENDOR]** Customers reportedly include CVS, Wealthfront, Deloitte and Gallup. Funding: $100M Series A (Feb 2026, Index); $200M Series B at $2B (Jul 2026, Greenoaks). **[INDEP, pending]** Gallup is validating it at the respondent, survey and population levels. It plans to test how accuracy decays with distance from interview topics, how much each added source of information helps, subgroup patterns, robustness across question formats, and decay when agents are not updated. Gallup has published no numbers yet: it says early results were "close enough… to justify further exploration," especially for questions near the interview topics. I found **no public "confidence model" paper from Simile**. | Park et al. agent bank: aggregate responses are open, individual data is restricted. https://news.gallup.com/opinion/methodology/709373/gallup-begins-research-simulated-responses.aspx ; https://baincapitalventures.com/insight/the-human-layer-of-ai-why-we-re-continuing-to-invest-in-simile/ ; https://runtimewire.com/article/simile-raises-200m-series-b-2b-valuation |
| **Aaru** | Proprietary population agents; it does not describe ingesting customer data | Simulated polls and studies | **[VENDOR]** Says it recreated EY's Global Wealth Research Report overnight, "highly correlated," and "more accurate where it diverged." No method or independent audit. | None. https://aaru.com/ |
| **Artificial Societies** (societies.io) | Persona networks, partly from social-graph data | Simulated audience reactions | **[VENDOR]** "86% prediction accuracy vs real-world surveys" (Jan 2026 supporter update); no method given. **[Possibly affiliated]** "Artificial Societies Benchmark" (Chidichimo, Jung, Wallis, He; arXiv 2609.30030): 11 tests across internal, construct and external validity, 20 human sources, 9 LLMs, and a scorecard instead of one score. It finds over-consistent answers, compressed scales and distorted relationships between traits; richer profiles help some models and hurt others. I could not confirm the authors' affiliation. | Benchmark framework. https://societies.io/publications/supporter-updates/reach-update-january-2026 ; https://arxiv.org/abs/2609.30030 |
| **Electric Twin** | Population-level synthetic audiences | Survey and poll answers | **Vendor-funded study:** a pre-registered LSE/NYU study (press coverage, 20 Jul 2026) compared Electric Twin with 7 online sample providers on 7,755 UK respondents and found answers "within the same range" for most questions. **It was funded by Electric Twin, and both authors hold shares and advisory or founding roles.** **[VENDOR]** 95.5% on 1−MAE and 92% on "NDAM"; elsewhere "95–96% accuracy, 10,000× faster." I could not find the paper or a DOI. $14M raised (Feb 2026). | https://itbrief.co.uk/story/ai-synthetic-audience-matches-human-polling-in-study ; https://parsers.vc/news/260216-electric-twin-secures-14m-for-ai-audience/ |
| **Evidenza** (ex-LinkedIn B2B Institute) | Synthetic B2B executive personas; runs as a managed service only (Aug 2026) | Brand and strategy survey answers | **[VENDOR/client anecdote]** EY's CMO ran EY's brand questionnaire through it against a fresh human sample and reported a "95% correlation" (via Marketing Week / Adweek). No method published. | None. https://marketingweek.com/ritson-synthetic-data-strategy |
| **Expected Parrot** | User-defined agent personas (any traits, which can include your own data) | Surveys and interviews run on LLM agents; the same survey can go to humans | No validation study found. Its value is infrastructure: **EDSL is open source** (Python, PyPI), with cached, reproducible runs. | https://pypi.org/project/edsl |
| **Synthetic Users** | LLM-generated personas, not grounded in customer data by default | Interview transcripts and reports | **[INDEP critique]** NN/g reran 3 of its own studies with Synthetic Users and ChatGPT and found them "too shallow," sycophantic, and claiming to complete courses that real users abandon. I saw this only in secondary coverage; the original NN/g article is "Synthetic Users: If, When, and How to Use AI-Generated 'Research'". | https://radar.zurb.com/article/nielsen-norman-synthetic-users-were-too-shallow-to-be-useful-against-three-real-studies ; https://measuringu.com/review-of-experiments-with-synthetic-users/ |
| **Qualtrics Edge Audiences** | A model trained on "millions" of Qualtrics survey responses | Synthetic panel answers | **[VENDOR]** A 4-step validation (generalization, data shape, diversity, transferability), with no numbers released. **[UNVERIFIED]** A vendor blog claims fine-tuned models deviate 0.07 SD from humans, versus 0.87–0.88 SD for GPT-5/Gemini. | https://www.qualtrics.com/strategy/audiences ; https://www.qualtrics.com/en-gb/events/synthetic-data-2026/ |
| **Toluna HarmonAIze Personas** | Anonymized first-party panel data (19.4M US; 79M global); one persona per real individual | Persona answers, starting with claims testing | **[VENDOR]** Claims individual-level personas raise accuracy; no numbers. | https://www.research-live.com/article/news/toluna-releases-synthetic-personas-in-us/id/5135503 |
| **Kantar** | GPT-4 synthetic sample | Likert and verbatim answers | Published a side-by-side of synthetic vs human answers (Likert and verbatims). I did not retrieve its headline results. | https://www.kantar.com/uki/inspiration/analytics/what-is-synthetic-sample-and-is-it-all-its-cracked-up-to-be |
| **Ipsos (persona bots), NielsenIQ BASES** | — | — | **UNVERIFIED.** I found no published validation within the search budget. | — |
| **Listen Labs / Outset / Conveo** | **Real** participants via AI-moderated interviews (video, audio, text). Listen Labs: $69M Series B, Jan 2026 (secondary source). | Themes, personas and reports from real interviews; Listen Labs has a knowledge base that builds up across studies | Not twin vendors. Outset documents synthetic participants only for testing interview guides (a competitor's characterization). These products **generate the qualitative data twins need**. | https://getversive.com/help/conveo-vs-listen-labs-vs-strella |
| **Delve AI** | Web analytics, CRM, reviews, survey transcripts, transactions (must be anonymized) | Personas and "synthetic user testing" | **[VENDOR]** No numbers; its own blog says to take responses "with a grain of salt." | https://www.delve.ai/blog/synthetic-user-testing |
| **Uxia / Blok** | Prototypes plus target persona definitions; Blok is described as an "agentic behavior simulator" | Usability feedback | None found. Uxia raised €1M pre-seed (late 2025). Blok: UNVERIFIED. | https://www.cyberclick.net/numericalblogen/how-uxia-and-synthetic-users-are-redefining-the-user-experience ; https://germanupa.de/sites/default/files/2026-04/gc_upa_tutorium_synthetic_users-jens_jacobsen.pdf |
| **Dovetail, Condens, Maze, UserTesting; Viewpoints AI; Sybill-like CRM twins** | — | — | **UNVERIFIED.** I found no 2026 announcements of synthetic-twin features. | — |
| **Shopify SimGym** (industry research) | Per-shop buyer profiles and intents from production clickstream; behavioral archetypes; cohort-weighted sessions | Simulated A/B outcomes on live storefronts | **[INDEP-ish, from the company's own researchers]** The arXiv abstract claims "state of the art alignment" with real UI-change outcomes. **[UNVERIFIED]** 77% directional agreement with add-to-cart shifts (secondary source). | https://arxiv.org/abs/2602.01443 |
| **Amazon Agent A/B** | Structured personas browsing live Amazon.com | A 1,000-agent between-subjects test of filter panel designs | Agent purchase direction matched a parallel human experiment (CHI EA '26). | https://arxiv.org/html/2504.09723v4 |
| **Data-driven persona A/B** (Benomar, Łajewska, Perelli, Mansour; arXiv 2609.01038, affiliation not listed on the page) | Anonymized behavioral data: activity patterns, engagement signals, inferred demographics | Predicted A/B outcomes | **[INDEP-ish]** Across 40 real A/B tests, the best configuration got the direction right 0.75–0.90 of the time, depending on the metric. | https://arxiv.org/abs/2609.01038 |

**Takeaway:** Vendors almost always report "correlation" or "1−MAE" against aggregate survey toplines. Those metrics look high almost by construction (see section 2 on midpoint baselines), and no vendor reports results on held-out future behavior.

---

## 2. Published validations against real outcomes

### Strong primary results [INDEP]

**Park et al., "Generative Agent Simulations of 1,000 People"** (arXiv 2411.10109; Stanford, with Google DeepMind collaborators). I read the full text.
- **Setup:** 1,052 US adults each did a 2-hour voice interview with an AI interviewer. Each person's answers were scored against their own retest 2 weeks later.
- **Accuracy:**
  - GSS (General Social Survey): normalized accuracy **0.85** (raw 68.85% ÷ 81.25% self-consistency).
  - Big Five: normalized correlation **0.80**.
  - Economic games: normalized correlation **0.66**.
- **Baselines (GSS / Big Five):** demographics-only agents 0.71 / 0.55; persona-paragraph agents 0.70 / 0.75.
- **Composite baseline:** agents built from the person's own GSS, Big Five and game answers, with same-category items excluded, scored 0.76 / 0.64 / 0.31. Interviews beat them.
- **Ablations:**
  - Removing **80% of the transcript** (96 of 120 minutes) still gave **0.79** on the GSS.
  - **Bullet-point summaries** of the interview gave **0.83**. Content, not wording style, carries most of the signal.
- **Experiments:** agents replicated the same 4 of 5 experiments that humans did. Effect sizes correlated **r=0.98** with the human results (humans' internal consistency 0.99).
- **Bias:** interview agents narrowed the subgroup accuracy gap (Demographic Parity Difference). For political ideology on the GSS it fell from 12.35% to 7.85%; for race from 3.33% to 2.08%.
- **Method:** "expert reflection," where the model writes reflections on the transcript as a psychologist, a behavioral economist, a political scientist and a demographer, then predicts with the transcript plus those reflections.
- **Access:** two tiers, with aggregate responses open and individual data restricted. Code: https://github.com/joonspk-research/generative_agent. My search notes suggest a newer published version exists (listed June 2026); check its figures.

**Toubia et al., Twin-2K-500** (arXiv 2505.17479; Columbia).
- **Data:** 2,058 US participants, 4 waves, more than 500 items, with a retest wave. CC-BY on Hugging Face.
- **Results [secondary summary]:** about 71.7% individual accuracy, about 87.7% of test-retest. Twins reproduced 6 of 10 classic effects; outcome bias and base-rate neglect failed.

**Peng, Gui, Brucks et al. (23 authors), "Digital Twins as Funhouse Mirrors"** (arXiv 2509.19088 v5, Apr 2026). This is the key critique of the mega-study.
- **Setup:** 19 pre-registered studies, 164 outcomes, with twins built from each person's 500+ Twin-2K-500 answers.
- **Result:** twin-human correlation averages only **r≈0.20**, and twins are only modestly better than a homogeneous base LLM.
- **Five distortions:** too little individuation, stereotyping, representation bias, ideological bias, hyper-rationality.
- **Data:** released as the Hugging Face dataset `LLM-Digital-Twin/Twin-2K-500-Mega-Study`.
- **[UNVERIFIED secondary]** Attributed to Netzer and Sambandam 2026: 1−MAE/range is about 0.75 with the full record, 0.73 with no individual information, and 0.75 with demographics only. In other words, near-midpoint guessing scores about the same. https://blog.pebblous.ai/report/llm-survey-twin-validation-gap/en/

**Hewitt, Ashokkumar, Ghezae, Willer** (Stanford): GPT-4 predicting the results of 70 preregistered US survey experiments.
- **Correlation:** predicted vs actual treatment effects r=0.85, and **r=0.90 on studies unpublished at the time**. That matches or beats expert forecasters.
- **Bias:** effect sizes are systematically overestimated. A third-party vignette suggests shrinking them by about 0.56.
- **Counts differ by version:** 476 effects / 105k participants in one, 469 / 119k in another. https://www.gsb.stanford.edu/faculty-research/publications/large-language-models-can-predict-results-social-science-experiments

**Maier et al. (PyMC Labs and Colgate-Palmolive), "semantic similarity rating" (SSR)** (arXiv 2510.08338).
- **Setup:** 57 personal-care concept surveys, 9,300 human responses.
- **Method:** collect a free-text reaction, embed it, and compare it with 5 reference statements (one per Likert point) to get a probability distribution over ratings.
- **Result:** about 90% of human test-retest reliability; distribution similarity (KS) above 0.85.
- **[UNVERIFIED]** Direct Likert scoring reached about 80%, and a trained ML model about 65%.
- **Scope:** purchase *intent*, not purchases; gender and regional patterns transfer less well than age and income. This is the best industry concept-testing validation I found.

**Brand, Israeli, Ngwe**, "Using GPT/LLMs for Market Research" (HBS/Microsoft; MSI working paper).
- Off-the-shelf willingness-to-pay estimates are often wrong in magnitude or even in sign.
- Fine-tuning on category conjoint data recovers sign and rough magnitude.
- Heterogeneity across groups is poorly captured (as characterized by arXiv 2606.04592).
- https://www.msi.org/working-paper/using-llms-for-market-research-2/

**Arora, Chakraborty, Nishimura**, "AI–Human Hybrids for Marketing Research" (Journal of Marketing 89(2), 2025; AMA/MSI Root Award).
- Benchmarked against a Fortune 500 food company's real studies.
- LLM interviews produced richer qualitative answers, and LLM theming matched human experts while missing some themes.
- Hybrid human-AI workflows beat AI-only or human-only. I did not find quantitative metrics.

**Industry A/B work.** Amazon Agent A/B, Shopify SimGym, and the 40-test persona A/B paper (2609.01038), all in the table above. Directional agreement runs about 0.75–0.90. This is the closest analogue to deciding A/B direction from behavioral twins.

### Calibration and statistical-validity frameworks [INDEP]
- **Hullman, Broska, Sun, Shaw**, "This human study did not involve human subjects" (arXiv 2602.15785, Feb 2026). Heuristic interchangeability (prompting, fine-tuning) gives no inferential guarantees. Statistical calibration with a small human sample preserves validity and cuts cost.
- **Tigre and Souto**, "When Can You Trust Your Synthetic Users?" (arXiv 2609.13148).
  - Splits panel bias into covariate shift and concept shift, with a Trust / Correct / Abandon decision rule.
  - A doubly robust AIPW estimator needs only 50–300 human respondents.
  - Results: on ANES (American National Election Studies), naive bias fell 92.9–99.6%; on Twin-2K-500 pricing (172,884 paired responses), bias fell 83–94%.
  - Context it reports: toplines are within about 4 points, but subgroup errors run 10–30 points.
- **Wang, Hunt, Tang, Joseph**, "When Can LLM Digital Twins Reduce Human Measurement?" (arXiv 2609.07987, Sep 2026).
  - Proposes "statistical substitutability," built on prediction-powered inference, with four dimensions: aggregate fidelity, paired respondent-level signal, how well a small human sample recovers the estimate, and stability across populations.
  - Finds behavioral fidelity is neither necessary nor sufficient for twins to reduce human data collection.
  - Better models and richer profiles do not reliably cut the human data needed.
- **Pew Research Center**, "silicon samples" methodology (30 Sep 2026): replicated 3 American Trends Panel waves using AI respondents matched to the original participants. I did not retrieve the results. https://www.pewresearch.org/data-labs/2026/09/30/methodology-silicon-samples.md
- **Other 2026 results (secondary or abstract level):**
  - NIM Marketing Intelligence Review: answers beat chance individually but are too positive toward familiar brands and show compressed variance.
  - Cross-survey transfer (arXiv 2607.03091): about 52% individual accuracy on Taiwanese election data [UNVERIFIED].
  - A replicability paper: silicon samples are internally reproducible but externally invalid.
  - **There is no formal meta-analysis yet.** The closest is an ASA 2026 paper using a mixed-effects meta-analytic framework.

### Critiques
- **NN/g:** sycophancy and shallowness; use synthetic users to rehearse interview guides, never as a replacement for participants (secondary coverage).
- **"LLMs do not simulate human psychology":** arXiv 2508.06950.
- **"Funhouse Mirrors":** above.
- **MeasuringU review:** factor structure is right but item means are off.

---

## 3. Methods for building a twin from a company's qualitative data
1. **Interview-to-agent pipeline (Park):** transcript, then expert reflections from 4 disciplines, then predict with the transcript plus reflections. Interviews beat survey composites even when surveys are semantically closer to the test items.
2. **Summary vs raw transcript:**
   - Park: summaries cost little (0.83 vs 0.85).
   - Ye, Deng, Candogan, "Beyond Raw Transcripts" (arXiv 2608.20344): *structure* matters more than volume.
     - A fixed Background / Decision procedure / Evaluation schema gives +1.91 points on Twin-2K-500 but no gain across 13 heterogeneous studies.
     - An LLM that iteratively proposes **task-specific** persona structures recovers about +1.91 points across the heterogeneous studies.
   - Implication: keep raw transcripts retrievable, and generate task-conditioned structured views at query time.
3. **How much data per person:** the 80% ablation suggests about 24 minutes of interview keeps most of the value (0.79 vs 0.85). Twin-2K-500's 500+ items still give weak individuation (r≈0.20), so more survey items do not equal a better twin.
4. **Combining qualitative and behavioral data:** SimGym and the 40-test persona A/B paper build personas from clickstream and engagement data. OPeRA (below) pairs persona surveys with browser actions and in-the-moment rationales. **I found no published study that combines interviews with behavioral logs for the same people and measures what each adds.** That is a clear gap.
5. **Contradictions and updating over time:** no published method. Gallup plans to measure decay when agents are not updated. Park's "memory stream" (recency, importance and relevance retrieval, from Generative Agents 2023) is the obvious basis. Treat contradictions as dated evidence, not as noise.
6. **Segment vs individual twins:**
   - Individual twins (Park, Toluna) reduce subgroup bias compared with demographic personas.
   - Most decisions are made at segment level, where calibration (AIPW, prediction-powered inference) is the honest approach.
   - Report both levels; Tigre and Souto found full-sample estimates could be trusted while subgroup targeting needed correction.
7. **Privacy and consent:**
   - Park uses two-tier access, with individual data restricted.
   - Delve requires anonymized inputs.
   - Toluna uses anonymized panel data.
   - The Anthropic Interviewer dataset is released with explicit consent for public release.
   - Implications for an open stack: consent scopes per source, PII redaction before indexing, re-identification risk (a twin can leak its source), and twin deletion when a source person withdraws.
8. **Elicitation format:** ask for free text and map it to a scale (SSR) instead of asking for a direct Likert score. Expect hyper-rationality, positivity and variance compression, and correct for them.

---

## 4. Ideal evaluation design for "a company's own twins"
- **Holdout axes, all reported separately:**
  - **(a) New questions** about the same people, stratified by semantic distance from the interview topics (Gallup's plan).
  - **(b) New concepts or stimuli**, which is the decision use case.
  - **(c) Future behavior:** a time-split, building twins at time T and predicting purchase, churn or adoption after T. Nobody publishes this well; the closest is an unrefereed seminar claim of 83% future-purchase accuracy for 306 Amazon customer twins [UNVERIFIED].
  - **(d) New people:** whether the agent-building pipeline generalizes, not just the individual agents.
  - **(e) A new population or market** (Wang et al.'s stability dimension).
- **Ceilings and baselines:**
  - Normalize by test-retest wherever retest data exists (Park; Twin-2K-500).
  - Always report baselines: base LLM with no persona, demographics-only, midpoint or majority guess, and a non-LLM model fit on the same features.
  - The midpoint baseline matters because 1−MAE on bounded scales is inflated.
- **Individual-level metrics:**
  - Accuracy and correlation, with correlation computed **within item, across people**; this is the individuation that Funhouse Mirrors shows is weak.
  - Variance ratio (synthetic SD ÷ human SD).
  - Subgroup gaps (Demographic Parity Difference).
- **Decision metrics:**
  - Rank order of concepts (Spearman or Kendall correlation; top-1 / top-k hit rate).
  - A/B direction accuracy and sign agreement.
  - Effect-size correlation plus calibration slope, given the systematic overestimation in Hewitt et al.
  - Directional accuracy as a function of the true effect size: small effects are where twins fail.
- **Inferential usefulness:** how many human respondents twins save at fixed precision, via prediction-powered inference or AIPW (Wang et al.; Tigre and Souto). Report "effective human sample size added."
- **Leakage controls:**
  - Remove items of the same category from the persona (Park removed about 4%).
  - Use concepts dated after the model's training cutoff, or unpublished ones (Hewitt's unpublished-study r=0.90 check).
  - Pre-register predictions before real outcomes arrive.
- **A benchmark that mimics company data from public data:** join per-person qualitative text, structured survey answers and behavioral traces for the same people. Hold out (i) unseen questions, (ii) later waves or actions, (iii) unseen people. Score with the metrics above against a test-retest ceiling. Where no single dataset has all three, use within-dataset proxies; for example, use OPeRA's persona surveys and early sessions to predict later actions.

---

## Gaps an open-source infrastructure could fill
1. **An open pipeline from a company's data to twins:** connectors for transcripts, research repositories, CRM, tickets and analytics events; consent-scoped storage and PII redaction; task-conditioned persona structures over retrievable raw evidence. Today this exists only in pieces: Park's generative_agent repo (interview only) and EDSL (survey orchestration, no data grounding).
2. **A standard evaluation harness:** test-retest normalization, the baselines listed above, individuation and variance metrics, decision metrics (rank order, A/B direction), and a calibration module (prediction-powered inference / AIPW) that reports human samples saved. Vendors report incomparable 1−MAE or correlation numbers; a neutral scorecard (in the spirit of the Artificial Societies Benchmark) is missing.
3. **Future-behavior holdouts:** almost nothing published predicts real downstream behavior from twins built earlier.
4. **Fusing qualitative and behavioral data, with an ablation of what each adds per person.** Unstudied.
5. **Twin lifecycle:** updating, contradiction handling, drift monitoring and decay curves (Gallup plans to measure decay; no tooling exists).
6. **Governance:** deletion and withdrawal, re-identification and leakage tests on twins, and audit logs of which evidence produced each prediction.
7. **Confidence and abstention:** a per-query signal of when a twin should not be trusted, based on topic distance and calibration error. Simile reportedly has one but has published nothing.

## Public datasets that best mimic "a company with interviews and behavior predicting outcomes"
- **Park et al. agent bank (Stanford; restricted access):** 1,052 two-hour interviews, GSS, Big Five, economic games, experiments, and a 2-week retest. The closest match for interviews predicting held-out answers with a test-retest ceiling. Individual data needs an access application.
- **Twin-2K-500 and Twin-2K-500-Mega-Study** (Hugging Face `LLM-Digital-Twin`, CC-BY): open, with retest, 19 follow-on studies (new concepts or stimuli) and pricing tasks. Rich in surveys, poor in qualitative data.
- **OPeRA** (arXiv 2506.05606, ACL 2026): persona survey, browser observations, fine-grained web actions, and in-the-moment rationales from real shoppers. The best open link between persona or qualitative data and behavior, and suits next-action and time-split holdouts. The abstract shows no interviews.
- **Anthropic Interviewer** (Hugging Face `Anthropic/AnthropicInterviewer`, CC-BY): 1,250 consented AI-led interview transcripts (workforce, creatives, scientists). Realistic interview-shaped text but no behavior or outcome labels, so use it for pipeline and PII stress tests and qualitative-only tasks.
- **Supporting sources:**
  - Hewitt et al. archive of 70 experiments: new-concept treatment-effect prediction, aggregate only.
  - ANES and GSS panel waves: time-split attitude change.
  - Shopify/Amazon A/B papers: method templates only; their data is not public.
- **Recommended composite benchmark:** Park bank (if access is granted) or Twin-2K-500 for individual answers with a retest ceiling; the Mega-Study for rank order and direction on new concepts; OPeRA for future behavior from persona plus history; Anthropic Interviewer for messy real transcripts in ingestion and PII tests.

**Main open items:** the original NN/g article, Kantar's headline numbers, Ipsos and NIQ validations, Qualtrics' 0.07 SD figure, the Netzer and Sambandam numbers, the Electric Twin paper's venue, and SimGym's 77% figure.
