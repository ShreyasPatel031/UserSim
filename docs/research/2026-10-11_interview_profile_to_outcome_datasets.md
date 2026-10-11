# Report: public benchmarks for building digital twins of individual customers

I used about 22 searches and fetches. Where possible I read the primary page: arXiv PDFs extracted to text, GitHub READMEs, and Hugging Face dataset cards and API metadata. Claims I could not check on a primary page are marked UNVERIFIED. Today is 2026-10-11.

## Bottom line
- **Only two public resources truly fit "the same people, rich source data, held-out outcomes":**
  - **Twin-2K-500** (survey histories, open).
  - **Twin-2K-500 Mega-Study** (19 new studies run on the same panel, open, Apache-2.0).
- **Park et al.'s 1,052 interview agents remain closed.** The interview transcripts and the individual-level agent bank are still not released as of the paper's v3 (Jun 2026). It is still the only large dataset that pairs interviews with outcomes and a retest wave.
- **No public dataset yet pairs real interviews or free text with held-out outcomes, a retest wave, and permissive licensing.** That is the gap.
- **Headline caution from the Mega-Study:** twins built from more than 500 answers per person correlate only r ≈ 0.20 with individuals on new outcomes. Individual-level accuracy is no better than demographics-only personas (0.748 vs 0.746). The twins are also under-dispersed in 94% of outcomes.

---

## 1. Park et al., "Generative Agent Simulations of 1,000 People"
- **Citation:** arXiv:2411.10109. v1 was 15 Nov 2024; v3 (28 Jun 2026) is retitled "LLM Agents Grounded in Self-Reports Enable General-Purpose Simulation of Individuals". Authors: Park, Zou, Kamphorst, Egan, Shaw, Hill, Cai, Morris, Liang, Willer, Bernstein. https://arxiv.org/abs/2411.10109
- **Participants:** 1,052 US adults, quota-matched by Bovitz.
- **Source data per person:** a 2-hour voice interview run by an AI interviewer (GPT-4o, Whisper, TTS) using the American Voices Project protocol. Wave 1 also included 177 GSS core items plus 6 numeric items, the BFI-44, and 5 incentivised economic games (dictator, trust in both roles, public goods, prisoner's dilemma).
- **Held-out outcomes:**
  - Wave 2, about two weeks later, repeated everything except the interview. This gives each person's own test-retest ceiling.
  - Five experiments from a large replication effort.
  - 27 GSS items that near-duplicated interview questions were removed after a screen of 54,694 item pairs.
- **Metric:** normalized accuracy = agent accuracy / the participant's own wave 1 vs wave 2 consistency. Correlations are normalized the same way.
- **Results (v3, GPT-4o):**

| Agent built from | GSS (normalized accuracy) | Big Five (normalized correlation) | Economic games (normalized correlation) |
|---|---|---|---|
| Interview only | 0.83 (raw 65.7%) | 0.80 | 0.66 |
| Survey only | 0.82 | 0.65 | 0.38 |
| Interview + survey | **0.86** | 0.77 | 0.49 |
| Demographics only | 0.74 | 0.61 | 0.48 |
| Persona paragraph (self-written) | 0.71 | 0.75 | 0.57 |

- **Notes on these results:**
  - Economic-game differences between agent types are not significant (ANOVA p = 0.16). The per-person normalized correlations are very noisy (std about 2.8).
  - Experiment effect sizes from agents correlate r = 0.91–0.99 with human effect sizes, but agent effects are inflated. With only 5 studies the test is underpowered.
  - v1 reported 0.85 on the GSS for interview agents and that 4 of 5 experiments replicated (the 0.85 is echoed by the Mega-Study paper; the 4-of-5 is only from secondary pages). The numbers changed between versions, so cite v3.
- **Ablations:**
  - Randomly dropping 80% of the transcript (about 24 of 120 minutes kept) still gives 0.79 on the GSS and 0.73 on the Big Five.
  - Replacing the transcript with a bullet summary gives 0.81 on the GSS and 0.70 on the Big Five.
  - The authors say gains asymptote once the model has enough construct-relevant evidence. Results were stable across OpenAI model tiers and a year of updates. No open-weight models were tested.
- **Access (verified):**
  - Paper: "open access to aggregated responses to the fixed survey instruments" plus code (https://osf.io/t6g7k, https://github.com/joonspk-research/generative_agent).
  - genagents README (https://github.com/joonspk-research/genagents, MIT licence): the 1,000-person interview bank is "not publicly available at the moment". It is planned as a restricted API with open aggregated responses on fixed tasks, and individual responses on open tasks only after request and review. The only interview agent released is one sample agent based on an author. The README also ships a separate bank of more than 3,000 synthetic GSS-demographic agents.
  - Consent text: data may be shared with researchers "strictly for academic purposes", and removal requests are honoured for 25 years. **Commercial use: no.** The Mega-Study authors also state the data "are not publicly available".
  - No confirmation was found that the restricted API has opened.
- **Follow-ups:** Simile, a startup based on this work, reportedly raised $100M (cited in the Mega-Study). I found no open-weight replication or public release of the bank.
- **Fit: 3/3 on design, 0/3 on availability.** It is the exact design we need (interviews, same-person held-out answers, retest ceiling), but we cannot obtain it. Use it as the methods template.

## 2. Twin-2K-500 and the Mega-Study

### Twin-2K-500
- **Citation:** Toubia, Gui, Peng et al., arXiv:2505.17479 (May 2025). Marketing Science 44(6):1446–1455, doi:10.1287/mksc.2025.0262.
- **Data:** https://huggingface.co/datasets/LLM-Digital-Twin/Twin-2K-500 under **CC BY 4.0** (verified, so commercial use is allowed with attribution). Code: github.com/tianyipeng-lab/Digital-Twin-Simulation.
- **Participants:** 2,058 US adults, about 2.4 hours each over 4 waves.
- **Source data per person:** about 500 questions, about 128K characters per person:
  - demographics (14)
  - personality (279 items, 19 scales)
  - cognitive measures (85)
  - economic preferences (34)
  - heuristics-and-biases experiments (48)
  - a pricing study (40 buy/no-buy decisions on real products with prices)
- **Formats provided:** `persona_text`, `persona_summary`, `persona_json`, and wave 1–3-only versions.
- **Held-out outcomes:** wave 4 repeats the heuristics-and-biases and other items, giving a retest. The dataset includes `wave4_Q_wave4_A` (ground truth) and `wave4_Q_wave1_3_A` (retest baseline). The split is new answers to repeated questions, not genuinely new questions.
- **Results (as quoted in the Mega-Study paper):** twin accuracy about 72% (GPT-4.1-mini text persona 71.72%), about 88% relative to retest. Twins replicated about half of the experimental effects, and no demographics-only baseline was reported. The original paper's fine-tuning details are UNVERIFIED, since I read only its abstract.
- **Fit: 2/3.** Real, open, commercially usable, same-person retest. But the source data is structured survey answers, not interviews or free text, and the held-out items overlap with the training items.

### Mega-Study
- **Citation:** Peng, Gui, Brucks, … Toubia (23 authors, Columbia, Yale, Yeshiva), "Digital Twins are/as Funhouse Mirrors: Five (Key/Systematic) Distortions", arXiv:2509.19088. v1 was 23 Sep 2025; v5 was 19 Apr 2026. The early title was "A Mega-Study of Digital Twins Reveals Strengths, Weaknesses and Opportunities…". Science Advances publication on 2 Sep 2026 is UNVERIFIED (secondary source only).
- **Data (verified):**
  - https://huggingface.co/datasets/LLM-Digital-Twin/Twin-2K-500-Mega-Study: **Apache-2.0**, not gated, parquet, last modified 2026-01-18.
  - Code: https://github.com/TianyiPeng/Twin-2K-500-Mega-Study (Apache-2.0).
  - Join it to Twin-2K-500 by Twin ID. Prolific IDs are withheld, so nobody else can run new studies on the panel.
  - Pre-registrations: researchbox.org/4145.
- **Design:** 19 new pre-registered studies with 164 outcomes. N = 13,506 participant-study responses from 1,784 unique Twin-2K-500 participants. The studies used new stimuli, and twins answered exactly the same questions as their humans. **The split is new studies and new questions for the same people**, which is closest to our use case.
- **The 19 studies:**
  1. Accuracy nudges for misinformation
  2. Affective primes
  3. Consumer minimalism scale
  4. Context effects
  5. Default effects
  6. Digital certificates (NFT) for luxury consumption
  7. Knowledge of fees and surcharges
  8. Heterogeneous story beliefs
  9. Hiring algorithms
  10. Idea evaluation (creativity ratings, human vs AI source)
  11. Infotainment news sharing
  12. Measures of creativity
  13. Obedient twins
  14. Privacy preferences in online ad targeting
  15. Preferences for redistribution
  16. Promiscuous (bipartisan) donors
  17. Quantitative intuition
  18. Targeting fairness (ad campaigns)
  19. User behaviour with recommender systems (Netflix, TikTok usage)
- **Studies relevant to product and marketing:** 3, 4, 5, 6, 7, 10, 11, 14, 18, 19.
- **Metrics:** individual accuracy = 1 − MAD/range, plus the cross-person correlation for each outcome (Fisher-z averaged), Glass's Δ on means, and the ratio of standard deviations.
- **Headline results (GPT-4.1, temperature 0.7, full persona):**
  - Individual accuracy 0.748, against random 0.629, empty persona 0.734 and demographics-only 0.746 (difference from demographics-only not significant, p = 0.37).
  - Correlation 0.197, against demographics-only 0.145, empty 0.080 and random 0.001. It was positive for 157 of 164 outcomes and significant for 97.
  - Best configuration was GPT-4.1 at temperature 0: r = 0.232, accuracy 0.752. GPT-5, DeepSeek, Gemini-3 Pro and a GPT-4.1 fine-tuned on Twin-2K-500 were not better. **Centaur as base model was worse than GPT.**
  - A roughly 13K-character summary performed about the same as the full 128K-character persona.
  - Aggregate level: means differ by 0.35 SD on average, which is roughly the error of using a 10-person human sample. Means differed significantly for 105 of 164 outcomes (64%).
- **Five distortions found:**
  1. **Insufficient individuation.** Twin SD was lower than human SD for 154 of 164 outcomes. Full-persona twins sit closer to empty-persona twins (MAD 0.175) than to their humans (0.252).
  2. **Stereotyping.** Full-persona answers are closest to demographics-only answers (MAD 0.132).
  3. **Representation bias.** Twins are more accurate for richer, more educated, politically moderate people.
  4. **Ideological bias.** Twins are "pro-human" and "pro-technology": more trusting, more accepting of algorithmic hiring, see ad targeting as less intrusive, and under-report Netflix and TikTok use.
  5. **Hyper-rationality.** Twins show perfect knowledge and give normative answers.
- **Where twins did better or worse:**
  - Better: the cognitive domain, human-technology interaction outcomes, and outcomes on rating scales.
  - Worse: socially desirable, political or valenced outcomes, and questions whose wording varied across participants.
  - Experts failed to predict how well the twins would do.
- **Fit: 3/3 on design, 2/3 on source type.** Same people, new studies, includes marketing outcomes, open and commercial-friendly. But the source data is structured survey answers, not interviews.

### Twin-2K follow-ups (2026)
- **Ye, Deng & Candogan, "Beyond Raw Transcripts: Structured Persona Extraction…"** (arXiv:2608.20344, Jun 2026). A consumer-behaviour schema (Background / Decision procedure / Evaluation) adds +1.91 percentage points on Twin-2K-500. On 13 heterogeneous sub-studies the fixed schema does no better than raw text; an LLM-discovered structure adds +1.91 points. No data release is stated.
- **ExploraTwin** (Venkat, Qiu, Peng, Gui, Toubia; arXiv:2608.20539, Aug 2026). An open-access, non-profit platform for running surveys and panels on Twin-2K twins, using a "CroissantTwin" data format.
- **Wang, Hunt, Tang & Joseph, "When Can LLM Digital Twins Reduce Human Measurement?"** (arXiv:2609.07987, Sep 2026). Twins can match average effects while carrying little paired signal about individuals. "Behavioral fidelity is neither necessary nor sufficient for statistical substitutability." The datasets are not named on the abstract page, but secondary snippets say Twin-2K-based.

## 3. Other datasets

| Dataset | Who / when / link | People | Source data per person | Held-out outcomes / split | Ceiling | Licence / access | Best result, and which approach won | Fit (0–3) |
|---|---|---|---|---|---|---|---|---|
| **SocSci210 / Socrates** | Kolluri, Wu, Park, Bernstein; EMNLP 2025; arXiv:2509.05830; HF socratesft/SocSci210 | 400,491 people in 210 TESS experiments (2.9M responses) | Demographic persona plus the stimulus; no free text | Three splits: unseen participants, held-out tasks (75/25), unseen studies | None stated | HF, not gated; licence not shown on card (UNVERIFIED) | Fine-tuned Socrates-Qwen-14B: +26% (v1) / +36% (EMNLP) distributional alignment over its base model, and +13% / +15% over GPT-4o on unseen studies. Fine-tuning won. | 1: great for predicting new studies, but no rich per-person data |
| **AlignSurvey** | Lin et al.; AAAI 2026; arXiv:2511.07871 | 44K interview dialogues (mostly public video platforms) plus 411K survey records (ATP, ESS R11, CSS, CGSS) | Interviews and surveys **apparently not linked to the same people** | 4 tasks: social role, interview, stance, survey response | None | HF PiLabZJU/AlignSurvey_Datasets says "undergoing ethical review and will be published soon" (only a README, Nov 2025); non-commercial | Fine-tuned SurveyLM (7–8B): about +10–20 points over GPT-4o few-shot, e.g. stance 57.1% vs 42.7%. Fine-tuning won. | 0–1 |
| **Anthropic Interviewer** | Anthropic, Dec 2025; HF Anthropic/AnthropicInterviewer | 1,250 (1,000 workforce, 125 creatives, 125 scientists) | One 10–15 minute AI-run interview transcript each | **No held-out outcomes** | – | HF metadata says MIT; README reportedly says data CC-BY (conflicting, UNVERIFIED which applies); consented for public release | – | 1: realistic interview text, but nothing to predict. Usable only for self-supervised held-out answers within a transcript |
| **Psych-101 / Centaur** | Binz et al.; HF marcelbinz/Psych-101; Nature 2025 (journal details UNVERIFIED) | 60,092 people, 160 experiments, 10.7M choices | Trial-by-trial choices as text | Held-out participants and held-out experiments (UNVERIFIED in detail) | – | Apache-2.0 (verified) | Centaur (Llama-3.1-70B, QLoRA) beats cognitive models (UNVERIFIED), but it underperformed GPT-4.1 as a twin base in the Mega-Study (verified) | 1: mostly one experiment per person |
| **PRISM** | Kirk et al.; arXiv:2404.16019; NeurIPS 2024 D&B (UNVERIFIED) | 1,500 surveyed; 1,396 had conversations | Survey with stated preferences, a **free-text self-description**, and demographics | 8,011 conversations and 68,371 rated LLM responses; can hold out conversations for each user | None | HF card says "cc" with research/education terms (exact CC variant, likely BY-NC, UNVERIFIED) | Not a twin benchmark | 2: profile plus free text plus many choices per person; the choices are about LLM outputs, not products |
| **OpinionQA / ATP** | Santurkar et al. 2023, arXiv:2303.17548; SubPOP arXiv:2502.16761 | Over 80K ATP respondents | Demographics and ideology; per-respondent ATP microdata is available from Pew | Hold out questions within a wave; same panelists recur across ATP waves (wave linking UNVERIFIED) | No retest | Pew registration and terms of use (commercial use UNVERIFIED) | Mostly distribution-level; fine-tuning on SubPOP helps distributions | 1–2: real panel histories with new waves, but no free text |
| **LaMP / LongLaMP** | Salemi et al. 2023, arXiv:2304.11406; LongLaMP arXiv:2407.11016 (details from memory) | Thousands of users (public reviews, emails, tweets and so on) | A history of the user's own documents | User-based and time-based splits; predict that user's next rating, label or text | – | Mixed upstream licences (UNVERIFIED) | Retrieval over the user profile plus prompting or fine-tuning beat no-profile baselines | 1: personalization of text, not survey or choice prediction |
| **PersonaGym** | arXiv:2407.18416 (from memory) | Synthetic personas | – | – | – | – | – | 0: not real people |
| **DICES** | Aroyo et al. 2023, NeurIPS D&B (from memory) | Hundreds of raters (DICES-350 and DICES-990) | Demographics only | Rater-level safety ratings | – | CC-BY-4.0 (UNVERIFIED) | – | 0–1 |
| **Human Behavior Atlas** | MIT; ICLR 2026; arXiv:2510.04899 | Over 100K multimodal samples | – | Behaviour *understanding* (affect, pathology) | – | GitHub | OmniSapiens-7B | 0: not individual simulation |
| **BehaviorChain** | Li et al.; ACL Findings 2025; arXiv:2502.14642 | 1,001 personas from fiction and biographies | Persona profile plus history | 15,846 behaviours in chains | – | GitHub O-L1RU1/BehaviorChain | Frontier LLMs struggle | 0: not real customers |
| **TwinVoice** | arXiv:2510.25536; ACL Findings 2026 | Real social-media and dialogue users | Posts and multi-session dialogues | Opinion consistency, memory, style | Human baseline | UNVERIFIED | LLMs well below the human baseline | 1 |
| **Community governance life histories** | Chen et al. (Renmin); arXiv:2605.23783 (May 2026) | 92 residents | **2-hour semi-structured life-history interviews** (1.2M characters total) | Fidelity to each resident's governance views | None stated | Release unclear | curriculum-LoRA per person matches the best long-context prompting at about 10x lower per-call cost | 2: interview design matches, but N is tiny and availability unclear |
| **InterviewSim** | Li et al. (Salesforce); COLM 2026; arXiv:2602.20294 | 1,000 public figures, 23K transcripts, about 11.5 hours each | Interviews | Held-out interview Q&A (content, facts, personality) | – | Release not stated | Retrieval preserves personality alignment; longer chronological context improves facts | 1: celebrities answering open questions, no choices |
| **Adaptive interviewing for moral decisions** | Su et al.; arXiv:2605.29458 | Not stated | Core-10 answers vs full interview vs summary | Moral-dilemma decisions | – | No release | Follow-up-grounded predictions 45.5% vs 39.3% | 1 |
| **SSR purchase intent** | Maier et al. (PyMC Labs and Colgate); arXiv:2510.08338 (Oct 2025) | 57 product surveys, 9,300 responses | Demographics only | Purchase-intent Likert ratings | Test-retest | **Proprietary, not released** | Free-text answers mapped to Likert by embedding similarity reach 90% of retest reliability, vs about 80% for direct numeric answers | 1: aggregate-level only; useful as an elicitation method |
| **SimBench** | ICLR 2026 | 20 datasets | – | Group-level | – | – | – | 0–1 |

I found no public customer-interview or market-research dataset that links rich per-person text to later outcomes. The proprietary industry results (SSR, Simile) cannot be audited.

## 4. Methodology lessons

**How interviews become agents (Park v3):**
- The **full transcript goes into the prompt** together with "expert reflections".
- For each person, GPT-4o writes up to 20 notes from each of four expert personas: psychologist, behavioral economist, political scientist, demographer. These are generated once and stored.
- At query time the model picks the most relevant expert, appends that expert's notes to the transcript, and reasons step by step.
- The memory-stream and retrieval architecture is in the genagents code (`remember()`, `reflect()`), but the headline results use full context plus reflections.
- Park's analysis finds two mechanisms: "direct retrieval" of facts stated somewhere in the transcript, and "inference" from them (e.g. a student is unlikely to have a supervisor).

**How much source data is needed:**
- Park: 20% of a 2-hour interview gives 0.79, versus 0.83 for the whole interview. A summary gives 0.81. Interview plus survey adds only +0.03.
- Mega-Study: a 13K-character summary performs like the full 128K characters. More than 500 items per person bought only about +0.05 in correlation over demographics.
- Conclusion: returns diminish fast. *Construct relevance* matters more than volume.

**Normalization of scores:**
- Park: accuracy divided by each person's own 2-week retest accuracy.
- Twin-2K: accuracy relative to the wave-4 retest.
- Mega-Study: accuracy as 1 − MAD/range against a random baseline (0.629!). It also argues for the **cross-person correlation for each outcome**, which shows whether twins can sort people; Park computes correlation across questions within a person, which inflates it.
- Always report empty-persona and demographics-only baselines, the SD ratio, and Glass's Δ.
- Wang et al. 2026 add "statistical substitutability": how many human labels a twin actually saves.

**Prompting vs retrieval vs fine-tuning:**
- For held-out answers by the same people, frontier-model prompting with full context or a summary won in Park and the Mega-Study. Per-panel fine-tuning (GPT-4.1 on Twin-2K) and Centaur did not help.
- Fine-tuning wins for population-level or new-study distribution prediction (Socrates, SurveyLM), and as a cheaper route in the governance study (curriculum-LoRA).
- Temperature 0 was best in the Mega-Study.
- Structured persona extraction gives small gains (about +2 percentage points).

**Typical failure modes:**
- Under-dispersion and shrinkage toward the base model.
- Demographic stereotyping.
- Positivity and social-desirability bias: twins are pro-social, pro-human and pro-technology.
- Hyper-rationality and perfect knowledge.
- Weak performance on political and valenced items.
- Inflated experimental effect sizes (Park).
- Accuracy skewed toward educated and affluent people (the Mega-Study's representation bias). Park, by contrast, reports *smaller* racial and ideological accuracy gaps for self-report-grounded agents.
- Inter-item correlations stronger than in human data, i.e. over-consistency (Park v3 limitations).
- Leakage risk when evaluation items resemble published studies or the source questions.

**Implications for our design:**
- Evaluate on **new questions and new studies for the same people**, not on repeated items.
- Collect a retest wave to get the ceiling.
- Report cross-person correlation and SD ratio against a demographics-only baseline.
- Elicit free text and map it to scales, as SSR does.

## Key URLs
- https://arxiv.org/abs/2411.10109
- https://github.com/joonspk-research/genagents
- https://arxiv.org/abs/2505.17479
- https://huggingface.co/datasets/LLM-Digital-Twin/Twin-2K-500
- https://arxiv.org/abs/2509.19088
- https://huggingface.co/datasets/LLM-Digital-Twin/Twin-2K-500-Mega-Study
- https://github.com/TianyiPeng/Twin-2K-500-Mega-Study
- https://arxiv.org/abs/2509.05830
- https://arxiv.org/abs/2511.07871
- https://huggingface.co/datasets/Anthropic/AnthropicInterviewer
- https://huggingface.co/datasets/marcelbinz/Psych-101
- https://huggingface.co/datasets/HannahRoseKirk/prism-alignment
- https://arxiv.org/abs/2608.20344
- https://arxiv.org/abs/2608.20539
- https://arxiv.org/abs/2609.07987
- https://arxiv.org/abs/2605.23783
- https://arxiv.org/abs/2602.20294
- https://arxiv.org/abs/2605.29458
- https://arxiv.org/abs/2510.08338
- https://arxiv.org/abs/2510.25536
- https://arxiv.org/abs/2502.14642
- https://arxiv.org/abs/2510.04899
