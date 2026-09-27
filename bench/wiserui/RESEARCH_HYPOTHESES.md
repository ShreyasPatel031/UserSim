# WiserUI-Bench: research round and ranked harness hypotheses (2026-09-27, 7:17–7:50 AM PT)

**Scope.** Research only: no paid model calls and no benchmark runs. The work was:
- a literature and web review;
- a zero-cost offline analysis of the saved judgments (`research_offline.py`);
- a scrape of the public source pages behind the 252 pairs, for reported uplift and publish dates (VWO / GoodUI, curl, free);
- a ranked list of **harness** hypotheses. Per Shreyas at 7:24 AM PT, the goal is a harness that lifts cheap models over their own plain baseline first (3.8 Flash, GPT-6 Luna/Sol, 2.5 Flash), then gets tried on 3.1 Pro and Opus 5.5.

Set: the 252 clean pairs (dev 75 / held-out 177). CA = right in both presentation orders (chance 25%). **OI** = order-invariant accuracy. OI takes one pick per pair from both orders; when the two orders disagree (a "flip") the pair counts 0.5, the expected value of a coin flip.

Reproduce: `python bench/wiserui/research_offline.py --json out.json [--src-info src_info.json]`.
- `src_info.json` holds the scraped uplift and dates. It is not committed (dataset metadata stays out of git, per `README.md`).
- To rebuild it: curl each item's `source` URL, then parse the VWO `<title>` "…by N%" and `datePublished`, and the GoodUI "Leak #N from X | Mon D, YYYY".

---

## 0. TL;DR

1. **Position bias is still the largest fixable error, even on frontier models.**
   - Flip rates (the two orders disagree):

     | model | flip rate |
     |---|---|
     | Opus 5.5 | 17% |
     | 3.8 Flash | 23% |
     | 3.1 Pro | 26% |
     | Sol | 27% |
     | Luna | 38% |
     | Sonnet 5 | 42% |
     | 2.5 Flash | 57% |

   - Almost every flip is "picks the second image in both orders".
   - A harness that answers from both orders at once (swap-aggregate) makes the output order-invariant. Its CA then equals its accuracy. Measured offline at $0 extra:

     | model | plain CA | swap-aggregate CA |
     |---|---|---|
     | 3.8 Flash | 54.4 | 65.9 |
     | Sol | 44.4 | 58.1 |
     | Luna | 36.5 | 55.6 |
     | 2.5 Flash | 25.8 | 54.4 |
     | 3.1 Pro | 57.9 | 70.8 |
     | Opus 5.5 | 66.7 | 75.4 |

   - **Caveat:** for weak models this is mostly coin flips (their OI is 54–58, barely above chance). Real skill gains must show up in **OI**, not only CA. Always report both.
2. **Ensembling the saved plain judgments does not help. Routing only the flips to a stronger model does.**
   - Majority votes lose to the best member:
     - Opus + Pro + 3.8 Flash vote: −8.3 CA vs Opus [−13.5, −3.2].
     - Pro + 3.8 Flash + Sol vote: −2.4 vs Pro.
   - The models are highly correlated: 77–80% per-order pick agreement among Opus, Pro and 3.8 Flash.
   - On the cheap models' flip pairs, other Geminis carry **no tie-break signal**: on Pro's 65 flips, 3.8 Flash is 19 right / 19 wrong. Opus does carry signal: 37 right / 12 wrong on Pro's flips, 33 / 11 on 3.8 Flash's.
   - Flip-escalation cascades, offline:

     | cascade | expected CA | $/pair | reference |
     |---|---|---|---|
     | Luna → 3.8 Flash | 61.1 | 0.0033 | 3.8 Flash plain: 54.4 CA at $0.0072 |
     | 3.8 Flash → Opus | 70.2 | 0.0201 | |
     | 3.1 Pro → Opus | 75.8 | 0.0337 | Opus swap-aggregate: 75.4 at $0.0562 |

3. **Where strong models fail is structured, and it looks like a shared "the change wins" prior, not a lack of capacity.**
   - GoodUI leaks where the company **kept the control** (the variant was rejected, n=41): every model is near chance.

     | model | OI, control kept | OI, variant won (n=61) |
     |---|---|---|
     | Opus | 57.3 | 77.9 |
     | 3.1 Pro | 53.7 | 80.3 |
     | 3.8 Flash | 56.1 | 71.3 |

     Pro's CA gap between the two groups is significant (43.9 vs 68.9, Fisher p = 0.015).
   - VWO success stories are ~all variant wins.
   - This matches an independent 2026 study (Squoosh, arXiv 2608.07517): judges agree with each other at κ 0.74–0.88 but agree with outcomes at only ~0.2, and 15 CRO experts were at chance.
4. **Label noise concentrates in the inferred labels.**
   - 16 pairs are confidently wrong (both orders pick the loser) for Opus, Pro and 3.8 Flash alike. 14 are GoodUI leaks (inferred winners), and 11 of those are "control kept" leaks.
   - Leak vs VWO rate: 14/102 vs 2/131, Fisher p = 3e-4.
   - Realistic observable ceiling: about **80–85% OI / order-invariant CA** (section 4). Opus is already at 75.
5. **Contamination vs capability for Opus.** The evidence leans toward capability plus a shared prior, not memorized outcomes.
   - Opus's gain over Pro is fewer flips (17.5% vs 25.8%). Its confidently-wrong rate is the same (15.9% vs 16.3%).
   - Opus stays near chance on "control kept" leaks. Those outcomes are public (the GoodUI titles literally say "rejects"), so a model that memorized them should ace them.
   - Accuracy does not vary with publish year. But all items predate every model's cutoff, and GoodUI's public leak index ends at #112 (Mar 2025), so a date-split test is not possible inside this benchmark. Probe designs are in section 3.6.
6. **The data question: more of the same data will not help.**
   - Training data does not help (our SFT, PerceptUI's fine-tune at 44.3, and LOLA on 12k Upworthy tests all give marginal gains). WiserUI is CC BY-NC-SA, so it cannot train a commercial model anyway.
   - What we need is evaluation data that separates skill from priors: control-won and flat tests with significance statistics, post-cutoff tests, and above all partner or customer A/B history. That last one is also the only real moat for UserSim.

---

## 1. Literature and web review

### 1.1 Predicting A/B outcomes from UI screenshots

| work | setup | reported result | model gen | transfers to 2026 strong models? |
|---|---|---|---|---|
| **WiserUI-Bench / G-FOCUS** (Jeon et al., arXiv 2505.05026, ACL 2026) | 300 A/B pairs (GoodUI leaks, VWO, abtest.design); CA | GPT-4o zero-shot 24.7 → G-FOCUS 43.3; Claude 3.5 Sonnet 45.1; MAD best baseline 30.7 | 2024 | **No.** On our data G-FOCUS lifted 2.5 Flash 25.8 → 42.9 (mostly less position bias) but *hurt* 3.1 Pro on dev (68.0 → 50.7): flip-second doubled, 12 → 24 of 75 |
| **PerceptUI** (Bougie et al., Woven by Toyota, arXiv 2606.05697) | Qwen-VL + QLoRA "contrastive reflection" distillation + reflective prompt evolution | WiserUI CA 44.3 (vs GPT-5 zero-shot 31.1, Opus 4.6 zero-shot 26.4, GPT-5 MAD 40.6); UIClip/BetterApp 75.1 → 79.3; on UXcar, personas help only with the *real participant profile* (shuffled persona = no persona: 52.1 vs 52.2; real profile 62.2) | 2025–26 | Its 44.3 is below plain 3.1 Pro (57.9) and Opus 5.5 (66.7). The distillation recipe is for small open models |
| **SimAB** (Rieder et al., Adobe/ETH, arXiv 2603.01024, CC BY-NC-ND) | GPT-5 persona agents vote on screenshots, counterbalanced order, confidence-sequence stopping | 67% on 45 historical tests (30/45), 83% on high-confidence; single fixed persona −10 pp; extreme diversity no better. Order bias without counterbalancing: 749 vs 126 votes; with it, balanced | GPT-5 | 67% is a pooled, order-counterbalanced accuracy, i.e. our **OI**. Plain 3.1 Pro OI is 71.0, Opus 75.4. No plain zero-shot baseline was reported, so the persona gain vs a plain judge is unknown |
| **Squoosh "The Judge Knows When It Knows"** (arXiv 2608.07517, Jun 2026) | 330 real CRO-agency tests, Gemini 3 Flash 16–20-vote counterbalanced panel, pre-registered | Unconditional κ 0.14 (sig-only labels 0.11, CI spans 0). 44% of catalog labels come from non-significant tests. **3.1 Pro ≡ Flash** (Δκ −0.04, TOST). Prompt redesigns, GEPA prompt optimisation, stimulus fidelity, change-type priors and persona priors all null. Vote-margin gate ≥ 0.6: 49% coverage, κ 0.31 (did not replicate at unanimity on a 33-call held-out set). Judges agree with each other κ 0.74–0.88 vs ~0.2 with truth; 16 votes ≈ 2 effective votes. 15 experts at chance vs truth (48.5%) but inter-rater κ 0.53 | Gemini 3 | **Directly relevant.** Warns that curated catalogs carry a variant-win prior that judges share. Their only surviving lever was calibrated abstention |
| **Agent A/B** (Wang et al., arXiv 2504.09723) | 1,000 persona LLM agents browse live Amazon, between-subjects | Reduced filter panel: 414 vs 403 purchases, same direction as a 2M-user human test | 2025 | One test only; direction-only validation. Browsing agents are about $1/eval (Squoosh's number) |
| **UXAgent** (Lu et al., CHI 2025 LBW, arXiv 2502.12561) | Persona agents for usability-study piloting | Qualitative heuristic evaluation only; no outcome prediction | 2025 | Not a predictor of A/B outcomes |
| **MLLM as a UI Judge** (arXiv 2510.08783) | 30 interfaces, Likert and pairwise vs human ratings | Within ±1 on a 7-pt scale >75% of the time; pairwise works only when the human preference gap is large | 2024–25 | Perception, not conversion |
| **LOLA** (Ye, Yoganarasimhan, Zheng, arXiv 2406.02611) | 17,681 Upworthy headline tests (text) | GPT-4 prompt 38–40% vs 33% random (multi-arm); embeddings + linear 46.3%; LoRA Llama-3-8B 46.9%; fine-tuned GPT-4o 48.8%. **Humans ≈ random.** Value came from using the LLM as a bandit prior | 2024 | Training on ~12k real tests gives only a few points. Evidence that training data is not the lever |
| **Spotify Engineering** (Aug 2026, "When can LLMs replace humans in A/B tests?") | gpt-4o-mini CTR predictions on Upworthy | Raw predictions recover 39% of the treatment effect; calibration on historical tests recovers it only under surrogacy/comparability assumptions | 2026 | Calibration needs in-distribution history, which argues for partner data |
| **Ashokkumar, Hewitt et al., Nature (Jul 2026)** | 70 survey experiments + 15 megastudies | GPT-4 predicted effects correlate strongly (≈ pooled human forecasters) even post-cutoff; effects overestimated ~2x; weaker on field megastudies; **averaging many prompts improves accuracy** | GPT-4 | Prompt-ensembling helps for effect *magnitudes* in text. Our screenshot judges are much more correlated |
| **GoodUI / GuessTheTest guess data** (goodui.org blog 2022) | 70,149 crowd guesses on GuessTheTest tests | Crowd ~59% directional (per-test 13–94%); Kohavi class ~48% on a 3-way question (chance 33%); Kohavi's 200+ practitioners 2.3/8 | humans | Human anchor: near chance to ~59% |

### 1.2 LLM-as-judge: position bias, test-time scaling, self-consistency, debate

- **Swap and aggregate is standard.** Zheng et al. 2023 (MT-Bench, arXiv 2306.05685) count inconsistent swaps as ties. Wang et al. 2023 ("LLMs are not fair evaluators", arXiv 2305.17926) use balanced position calibration and multiple-evidence calibration. PORTIA (arXiv 2310.01432) splits and merges the candidates. Permutation self-consistency (Tang et al., arXiv 2310.07712) marginalises over orders. **Transfer:** mechanical and model-agnostic. Our offline numbers show it holds on 2026 models (TL;DR 1).
- **Position bias is worst when quality is close.** Shi et al. 2024/25 ("Judging the Judges", arXiv 2406.07791; 15 judges, 150k instances) find bias grows as the quality gap shrinks. MLLM-as-a-Judge (Chen et al., ICML 2024, arXiv 2402.04788) finds the same in MLLMs. This fits our data: flips are the uncertain pairs, and other models are at chance on them.
- **Judgment distribution beats greedy picks.** "Improving LLM-as-a-Judge Inference with the Judgment Distribution" (EMNLP Findings 2025):
  - the mean of the judgment distribution beats the greedy mode;
  - CoT can collapse the distribution and worsen position bias;
  - small judges do better pointwise.

  This supports a graded tie-break (H1) and warns against "think harder" (H6).
- **More thinking is not a reliable lever.** "Increasing the Thinking Budget is Not All You Need" (arXiv 2512.19585) finds budget scaling alone gives weak gains. Squoosh found Pro ≡ Flash. Our G-FOCUS (more structured reasoning) hurt Pro.
- **Self-consistency and juries: small gains with correlated samples.** Self-consistency: Wang et al., arXiv 2203.11171. Juries: Verga et al., arXiv 2404.18796. Squoosh measured n_eff ≈ 2 of 16. Our own 3-vote evaluator at T1 on 2.5 Flash gave nothing.
- **Debate helps mainly weak judges.** Multi-agent debate (Du et al., arXiv 2305.14325; Khan et al., arXiv 2402.06782) mostly helps weak judges on verifiable questions. WiserUI's MAD (R1) was GPT-4o's best baseline (30.7). PerceptUI reports GPT-5 MAD 40.6 vs zero-shot 31.1, mostly from better order balance.
- **Calibration and abstention.** "Trust or Escalate" (Jung et al., ICLR 2025, arXiv 2407.18370) does cascaded selective evaluation with a guaranteed agreement rate, starting cheap and escalating when unconfident. Cascades also: FrugalGPT (Chen et al., arXiv 2305.05176). Squoosh found vote-margin gating was the only lever that survived.

### 1.3 Persona simulation: does it predict real behaviour?

- **For:**
  - Park et al. 2024 (arXiv 2411.10109): interview-grounded agents of 1,000 real people replicate GSS answers at 85% of the people's own test-retest consistency.
  - PerceptUI: the real participant profile helps rating prediction.
  - SimAB: diverse personas beat a single fixed persona by 10 pp.
- **Against / limits:**
  - Hu & Collier 2024 ("Quantifying the persona effect", arXiv 2402.10811): persona variables explain little variance (<10%) in subjective annotations.
  - PerceptUI: shuffled or generic personas ≈ no persona.
  - Gui & Toubia 2023 (arXiv 2312.15524): a causal-inference critique of LLM simulation.
  - Squoosh: persona priors were null.
  - Our 2.5 Flash runs: G-FOCUS + 6 personas vs G-FOCUS gave dCA −3.2, dOI +0.4.
- **Verdict:** personas help when grounded in *real* individual data and the target is individual responses. For aggregate A/B winners without audience data, the evidence for gains over a plain strong judge is weak. The defensible value is explanation and segment insight, not accuracy.

### 1.4 UI reward models, critique data and other datasets

| dataset | size | label type | license / access | useful for |
|---|---|---|---|---|
| WiserUI-Bench | 300 pairs (252 clean here) | real A/B winner + expert rationale; ~1/3 inferred (GoodUI leaks) | **CC BY-NC-SA 4.0**, images fetched from source | eval only; **cannot train a commercial model** |
| GoodUI tests / patterns | 630+ experiments, per-pattern repeatability and median effect; includes losers and flat tests | real, many with stats | paid membership, proprietary | eval with a control-won / flat mix; licensing needed |
| GoodUI leaks | 112 leaks (index ends Mar 2025) | inferred from implement vs reject | public pages, copyrighted | already in WiserUI; no post-cutoff supply |
| GuessTheTest | hundreds of tests + 70k crowd guesses (a per-test human baseline) | real, submitted by companies | paid, proprietary | eval + human-difficulty covariate |
| VWO / Optimizely / abtest.design case studies | hundreds | winner-only marketing (VWO 72/73 identifiable = variant wins); median reported uplift **33%** in our 131 VWO pairs | copyrighted | little: all variant wins, likely inflated uplifts (winner's curse) |
| Upworthy Research Archive (Matias et al., Sci. Data 2021) | 32,487 tests (17,681 headline) | real CTR, large n | open (CC BY 4.0) | text-only calibration research; not UI |
| CreativeRanking (Alibaba, arXiv 2102.04033) / CreativePair (Creative4U, arXiv 2508.12628) | 1.7M ad creatives with CTR / 8,879 labelled pairs | real CTR / relative CTR | Tianchi research terms / check | visual-persuasion pretraining; domain shift |
| UIClip JitterWeb + BetterApp (Wu et al., UIST 2024, arXiv 2404.12500) | 2.3M synthetic-defect pairs + human-rated app pairs | design quality, not conversion | model MIT; data on HF (check the terms) | a design-quality prior; zero-shot LVLMs near chance on BetterApp |
| UICrit (Duan et al., UIST 2024; google-research-datasets/uicrit) | 1,000 Rico screens, 11,344 critiques + ratings | expert critique | CC BY 4.0 | critique grounding, not outcome |
| WebUI (Wu et al., CHI 2023, arXiv 2301.13280), Rico | 400k web / 72k mobile screens | none (structure) | research | retrieval / grounding only |
| Squoosh CRO-agency catalog | 546 tests (337 decisive, 76% variant wins), per-arm counts | real, recomputable significance | private | shows what we would want |

---

## 2. Model generation and transfer: why the weak-model tricks failed on strong models

- **G-FOCUS, few-shot, goal / diff / page text, crops, 3-vote and SFT were all tested on 2.5 Flash.** 2.5 Flash's main failure is a 57% flip rate: it picks the second image 81% of the time (SA 81.3 vs FA 27.4). It also gets ~258 image tokens per image in 2-image Vertex calls (600 input tokens per call, vs ~2,250 for 3.8 Flash and ~2,300 for Opus).
  - G-FOCUS mainly fixed the bias: CA +17, but OI only +4 (55.8 → 59.9).
  - Strong models have less bias to fix, so the scaffolding adds noise. On Pro it doubled flip-second, 12 → 24 on dev.
- **Rule for the new harness:** separate bias removal (mechanical, transfers) from skill (OI, rarely moved by prompting). Score every arm on both CA and OI.

---

## 3. Offline analysis of the saved judgments ($0)

Runs used: plain vanilla judgments for Opus 5.5, Sonnet 5, 3.1 Pro, 3.8 Flash, GPT-6 Sol and Luna, Sonnet 4.6, gpt-5-mini, gpt-4.1-mini, gpt-4o and 2.5 Flash, plus our G-FOCUS T0 on 2.5 Flash (all 252). Opus and Sonnet 5 ran without temperature control (thinking on), so their run-to-run noise is unmeasured.

### 3.1 CA, OI and failure modes (all 252 pairs)

| model | CA | OI (flip = 0.5) | both right | **flip (picks 2nd both orders)** | flip (1st) | confidently wrong | $/pair |
|---|---|---|---|---|---|---|---|
| Opus 5.5 | 66.7 | 75.4 | 66.7 | 16.3 | 1.2 | 15.9 | 0.0562 |
| 3.1 Pro | 57.9 | 70.8 | 57.9 | 22.6 | 3.2 | 16.3 | 0.0192 |
| 3.8 Flash | 54.4 | 65.9 | 54.4 | 20.6 | 2.4 | 22.6 | 0.0072 |
| GPT-6 Sol | 44.4 | 58.1 | 44.4 | 22.6 | 4.8 | 28.2 | 0.0115 |
| G-FOCUS 2.5 Flash (ours) | 42.9 | 59.9 | 42.9 | 25.4 | 8.7 | 23.0 | 0.0110 |
| Sonnet 5 | 37.3 | 58.1 | 37.3 | 38.9 | 2.8 | 21.0 | 0.0258 |
| GPT-6 Luna | 36.5 | 55.6 | 36.5 | 35.7 | 2.4 | 25.4 | 0.0006 |
| 2.5 Flash plain | 25.8 | 54.4 | 25.8 | 55.6 | 1.6 | 17.1 | 0.0030 |

Notes on the table:
- OI here is recomputed from binary picks, so 2.5 Flash reads 54.4 (the 55.8 in the reports counts its unparsed answers differently).
- The confidently-wrong rate is **flat at ~16% for the three best models**. Opus beats Pro by flipping less, not by being wrong less often.

**Dev vs held-out warning.**
- Pro: dev 68.0 vs held-out 53.7 CA (OI 77.3 vs 68.1).
- 3.8 Flash: 61.3 vs 51.4.
- Opus: 66.7 on both.

Dev is easy for the Geminis, so a dev-only win can be split luck. Power on 75 pairs: SE(dCA) ≈ 5 pts, so the minimum detectable effect is ≈ 15 pts at 80% power. On 252 pairs it is ≈ 8 pts. Zero-shot harness arms have nothing fitted to dev, so **use dev as a smoke test and decide on all 252**, with the threshold written down before the run.

### 3.2 Where strong models fail (CA)

| slice | n | Opus | Pro | 3.8 Flash | Sonnet 5 |
|---|---|---|---|---|---|
| source: VWO (reported) | 131 | 66.4 | 55.0 | 55.0 | 42.0 |
| source: GoodUI leak (inferred) | 102 | 64.7 | 58.8 | 55.9 | 32.4 |
| source: abtest.design | 19 | 78.9 | 73.7 | 42.1 | 31.6 |
| **leak, control kept (variant rejected)** | 41 | **53.7** (OI 57.3) | **43.9** (OI 53.7) | 51.2 (OI 56.1) | 39.0 |
| leak, variant won | 61 | 72.1 (OI 77.9) | 68.9 (OI 80.3) | 59.0 (OI 71.3) | 27.9 |
| VWO, variant won (from filenames) | 85 | 64.7 | 57.6 | 54.1 | 44.7 |
| 1 element changed | 178 | 65.2 | 62.4 | 57.3 | 38.2 |
| 2 elements | 45 | 71.1 | 46.7 | 48.9 | 35.6 |
| 3+ elements | 29 | 69.0 | 48.3 | 44.8 | 34.5 |
| law: Hick's Law (fewer choices won) | 57 | **50.9** | **40.4** | 38.6 | 31.6 |
| law: Von Restorff | 109 | 75.2 | 64.2 | 55.0 | 38.5 |
| attribute: Color | 47 | 87.2 | 70.2 | 61.7 | 44.7 |
| attribute: Position | 49 | 55.1 | 49.0 | 42.9 | 40.8 |
| element: Link | 12 | 58.3 | 16.7 | 25.0 | 8.3 |
| element: Tile | 27 | 48.1 | 51.9 | 37.0 | 25.9 |
| page: homepage | 50 | 64.0 | 50.0 | 46.0 | 26.0 |
| page: landing | 38 | 57.9 | 50.0 | 50.0 | 28.9 |
| platform: mobile | 27 | 74.1 | 55.6 | 55.6 | 33.3 |

Reading the table:
- **Removal / simplification wins (Hick's Law) are the systematic blind spot.** Twenty of the 26 pairs that Pro and 3.8 Flash both get confidently wrong have "remove / reduce / simplify" rationales: Airbnb, Netflix and Etsy removing elements. Models prefer the version with more information or features.
- **"Control kept" leaks sit at chance for every model.** This is the shared-prior signature: models reward "the version that looks like a deliberate optimisation". It is also the least reliable label class, since rejection is inferred and could be for non-metric reasons.
- Pro is weak on multi-element changes (46–48); Opus is not (69–71).
- **Reported effect size does not predict difficulty.** VWO uplift bins (<10%, 10–25%, 25–50%, ≥50%) give Opus 76.2 / 53.3 / 77.5 / 60.0 and Pro 66.7 / 46.7 / 62.5 / 47.5. That is consistent with inflated, winner's-curse uplifts; the median reported VWO uplift is 33%, while Kohavi-style real effects are mostly a few %.
- Publish-year bins show no gradient: Opus 65.2 for ≤2017, 65.3 for 2018–21, 64.1 for 2022–25. All are pre-cutoff.

### 3.3 Agreement, oracles and votes from the saved picks

| set | oracle: ≥1 model right in both orders | per-order majority CA | pooled-vote order-invariant CA (tie = coin) |
|---|---|---|---|
| Opus + Pro | 77.0 | 66.7 (tie → Opus) | — |
| Opus + Pro + 3.8 Flash | 80.2 | **58.3** (−8.3 vs Opus, CI [−13.5, −3.2]) | 73.8 (< Opus alone 75.4) |
| Pro + 3.8 Flash | 66.3 | — | 68.8 (< Pro alone 70.8) |
| Pro + 3.8 Flash + Sol | 70.6 | 55.6 (−2.4 vs Pro, CI [−6.7, +2.0]) | — |
| all 12 systems | 89.3 | 42.1 | — |

- Per-order pick agreement: Opus~Pro 76.8%, Opus~3.8 Flash 77.4%, Pro~3.8 Flash 79.6%.
- The oracle gap (~80%) is not reachable by voting. The models share both their errors and their position bias. **Do not build a vote-of-models harness.**

### 3.4 Order-invariant (swap-aggregate) and cascades, offline

A flip goes to the next model in the chain, else a coin (expected 0.5). The answer comes from both orders, so CA = accuracy.

| system | CA (expected) | $/pair | vs its plain CA |
|---|---|---|---|
| 2.5 Flash swap-aggregate | 54.4 | 0.0030 | +28.6 |
| Luna swap-aggregate | 55.6 | 0.0006 | +19.1 |
| Sol swap-aggregate | 58.1 | 0.0115 | +13.7 |
| 3.8 Flash swap-aggregate | 65.9 | 0.0072 | +11.5 |
| Pro swap-aggregate | 70.8 | 0.0192 | +12.9 |
| Opus swap-aggregate | 75.4 | 0.0562 | +8.7 |
| Luna → 3.8 Flash on flips (38% escalated) | 61.1 | 0.0033 | +24.6 vs Luna, +6.7 vs 3.8 Flash plain CA |
| Luna → Pro | 61.7 | 0.0079 | |
| 3.8 Flash → Pro (23%) | 66.9 | 0.0116 | +1.0 vs 3.8 Flash swap-aggregate |
| 3.8 Flash → Opus (23%) | 70.2 | 0.0201 | +4.3 vs 3.8 Flash swap-aggregate |
| Pro → Opus (26%) | 75.8 | 0.0337 | ≈ Opus swap-aggregate at 60% of the cost |
| Opus → Pro | 76.6 | 0.0754 | |

Tie-break signal on 3.8 Flash's 58 flips, right / wrong (the rest also flipped):

| other model | right | wrong |
|---|---|---|
| Luna | 14 | 16 |
| Sol | 13 | 19 |
| 2.5 Flash | 8 | 13 |
| Pro | 18 | 13 |
| **Opus** | **33** | **11** |

Only Opus resolves the cheap models' flips.

### 3.5 Selective prediction (abstain unless models are order-consistent and agree)

| gate | dev coverage / acc | held-out coverage / acc | all 252 |
|---|---|---|---|
| 3.8 Flash consistent | 82.7% / 74.2 | 74.6% / 68.9 | 77% / ~70 |
| Opus consistent | 80.0% / 83.3 | 83.6% / 79.7 | 82.5% / 80.8 (its flips: 38.6) |
| Pro + 3.8 Flash consistent & agree | 65.3% / 85.7 | 52.5% / 79.6 | 56.3% / 83.1 |
| Opus + Pro consistent & agree | 61.3% / 89.1 | 52.5% / 84.9 | 55.2% / 86.3 |

The gate transfers from dev to held-out with a 4–6 pt accuracy drop. This is the product claim Squoosh found defensible ("we call about half of tests, at about 85%"), but it has the same variant-prior caveat.

### 3.6 Contamination: evidence so far and probe designs

**Evidence so far (weak, and against memorisation):**
- No publish-year gradient.
- Opus is at chance on "control kept" leaks even though their outcomes are public text.
- Opus's gain is fewer flips, not fewer confident errors.
- GPT-6 Sol (Apr 2026 cutoff) did not jump.

**Probes, cheapest first. All are small, but they are paid calls, so they are not run here.**
1. **Text-only recall** (~$1 on Opus, ~$0.3 on Pro). Give "GoodUI leak #N from {company}, {page type}: {neutral description of the two variants from `ui_change`}. Which version was kept?" with no images. Above-chance accuracy, especially on "control kept" leaks, means memorised outcomes.
2. **Variant-identification probe** (3.8 Flash on 252 ≈ $1.8; Opus on 102 leaks ≈ $5.7). "Which screenshot is the original and which the new variant?", scored against the filename roles (GoodUI `_afull` = control, confirmed on the pages; VWO `Control` / `Variation`). If variant ID is ≥ 75% and the pick ≈ "pick the variant", then CA mostly measures the prior (Squoosh's shared-prior account), not outcome prediction.
3. **Semantics-preserving perturbation** (MM-Detect, arXiv 2411.03823; semantic-perturbation contamination detection, ICLR 2026). Apply a JPEG re-encode, a ±5% rescale, a slight hue shift and re-rendered brand text to 60 pairs (Opus ≈ $3.4). A significant drop means pixel memorisation.
4. **Fresh post-cutoff tests: the only decisive probe.** GoodUI's public leak index stops at #112 (Mar 2025), so the fresh tests must come from GuessTheTest, a paid GoodUI export or partner data.

---

## 4. The data question and the realistic ceiling

**Do we need more data? Yes, but for evaluation, not training.**
- **Training data is not the lever for frontier models.**
  - Our SFT on 177 pairs matched the untuned model (34.7 = 34.7).
  - PerceptUI's distilled fine-tune reaches 44.3, far below plain 3.1 Pro.
  - LOLA's 12k real Upworthy tests buy about 7 pts over GPT-4 prompting in a text domain.
  - WiserUI's NC license bars commercial training anyway.
- **What is missing is evaluation data that separates skill from priors:**
  1. control-won and flat tests (real base rates are ~10–33% variant wins at mature orgs, per Kohavi & Thomke 2017; not the ~100% of VWO stories);
  2. per-arm counts, so significance can be recomputed (Squoosh: 44% of curated labels are non-significant);
  3. post-cutoff tests for contamination;
  4. partner or customer A/B history with screenshots. This last one is the only proprietary, defensible asset: it calibrates confidence to *that* customer's traffic (Spotify's comparability condition) and becomes a retrieval corpus.
- **Retrieval of analogous tests has weak support.** Squoosh's change-type priors scored κ 0.015, and our few-shot runs were null. Build the corpus for eval and calibration first; retrieval is a later experiment.

**Realistic ceiling.**
- Inferred labels are about 1/3 of the set (GoodUI leaks are 102/252 here). If 20–30% of leak labels and 5–15% of VWO labels are wrong direction, the overall label-flip rate is ε ≈ 10–20%. That is consistent with:
  - Berman et al. 2018: Optimizely false discovery rate ≈ 33–42% among significant results;
  - Kohavi et al.'s "Intuition Busters" (KDD 2022) on false-positive risk;
  - our 16 pairs confidently wrong for all top-3 models, concentrated in leaks (p = 3e-4).
- A perfect predictor then scores 80–90% observed.
- Opus is already at 75.4 order-invariant, and at 86% on the ~55% of pairs where Opus and Pro agree.
- So the headroom is ~5–10 pts for frontier models. For cheap models it is ~10–20 pts on OI; 3.8 Flash's OI is 65.9.
- Humans are near chance on real tests (Squoosh experts 48.5%; Kohavi practitioners 29%; GuessTheTest crowd 59%). A benchmark on which models reach 75% is either easier than real CRO backlogs (a curated, detectable variant prior) or partly contaminated. Section 3.6 is how to tell which.

---

## 5. Ranked harness hypotheses (cheap models first, then Pro / Opus)

Measured cost per plain pair (2 calls, one per order):

| model | $/pair |
|---|---|
| Luna | 0.0006 |
| 2.5 Flash | 0.0030 |
| 3.8 Flash | 0.0072 |
| Sol | 0.0115 |
| 3.1 Pro | 0.0192 |
| Opus 5.5 | 0.0562 |

"Dev test" = the smallest run that can falsify. Where 75 pairs cannot resolve the effect, the test uses all 252 at zero-shot, with the threshold fixed in advance.

### H1: Swap-aggregate judge with a graded confidence tie-break (order-invariant harness). **Rank 1.**
- **Change:** keep the 2 calls per pair. Each call outputs P(first is more effective) on 0–100, or 1–10 ratings for both. The harness averages across orders, correcting for position (p_ab + (1 − p_ba)) / 2, and emits one pick used for both presentations.
- **Rationale:**
  - Position bias is 21–56% of pairs for cheap models (section 3.1).
  - Swap-aggregate is standard (Zheng 2023; Wang 2023; PORTIA; Tang 2024; SimAB counterbalancing).
  - The judgment-distribution paper (EMNLP Findings 2025) finds that the distribution mean beats the greedy pick.
  - Own evidence (confounded by prompt differences): on 2.5 Flash, rating-based aggregation gave OI 61.1 (S2-strict) and 63.1 (G-FOCUS + personas), vs 55.8 for binary vanilla picks. Graded scores resolve flips better than a coin.
- **Predicted effect:**
  - Swap-aggregate part: system CA +11 to +29 on every cheap model. This is near-certain and already measured offline.
  - Graded tie-break: OI +0 to +3 on 3.8 Flash / Sol (flips resolved at 55–60% instead of 50%). Perhaps +3 to +6 on Luna / 2.5 Flash, where flips are 38–57% of pairs.
  - On Pro / Opus: CA +9 to +13 from swap-aggregate; OI +0 to +2.
  - Uncertainty: graded outputs can collapse to 50/50 or stay biased; CoT can amplify bias.
- **Cost:** same calls; about +10% output tokens. 3.8 Flash ≈ $0.008/pair; Luna ≈ $0.0007.
- **Smallest test:**
  - Luna on all 252: ≈ $0.2, can run on dev first for $0.05.
  - 3.8 Flash on all 252: ≈ $2.0.
  - Primary metric: accuracy on each model's own flip pairs (n ≈ 58 for 3.8 Flash, 96 for Luna). Secondary: OI vs the plain OI above.
- **Drop if** flip-pair accuracy ≤ 52% on both models: the coin version keeps the CA gain for free, so stop investing in the tie-break. Then escalate to H2 instead.
- **Honesty rule:** the paper's CA is per-call. Report "single-call CA" (paper-comparable) next to "system CA" (order-invariant).

### H2: Flip-escalation cascade (route only order-inconsistent pairs up a model tier). **Rank 2.**
- **Change:** run the cheap model in both orders. If it is order-consistent, answer. If it flips (23% of pairs for 3.8 Flash, 38% for Luna), send the pair to a stronger model's swap-aggregate judge. With H1, "flip" becomes "low |p − 0.5|", which gives a tunable threshold.
- **Rationale:**
  - FrugalGPT; Trust-or-Escalate (ICLR 2025).
  - Offline: only Opus has tie-break signal on the cheap flips (33/11 on 3.8 Flash's).
  - The Luna → 3.8 Flash route works because Luna's flips are mostly easy pairs (3.8 Flash is 48 right / 20 wrong on them).
- **Predicted effect** (from the offline table; in-sample, so expect ±3 on rerun):
  - Luna → 3.8 Flash: 61.1 CA at $0.0033 (+6.7 over plain 3.8 Flash at 46% of its cost).
  - 3.8 Flash → Opus: 70.2 at $0.0201 (≈ Pro swap-aggregate at about the same cost).
  - Pro → Opus: 75.8 at $0.0337 (≈ Opus at 60% of the cost).
  - Cheap → Pro routes add ~1 pt (Pro has no signal on the Flash flips).
- **Cost:** as in the table. Opus has no T0, so its repeatability is unknown.
- **Smallest test:**
  - Rerun 3.8 Flash on dev ($0.54) to confirm its flip set is stable at T0.
  - Rerun Opus on the union of 3.8 Flash's and Pro's flip pairs on 252, twice (~110 pairs × 2 × $0.056 ≈ $12), or on dev only (~30 pairs × 2 ≈ $3.4) as a smoke test.
- **Drop if** Opus's committed accuracy on the rerun flips is < 65% (the offline value is 75%), or its run-to-run agreement on them is < 80%.

### H3: Benchmark-validity gate: variant-prior + contamination probes (diagnostic; run before trusting any H1/H2 gain on Pro / Opus). **Rank 3.**
- **Hypothesis to falsify:** strong-model CA is mostly (a) less position bias plus (b) a shared "the deliberate change wins" prior, not memorised outcomes.
- **Evidence:**
  - Every model is at chance on "control kept" leaks.
  - Squoosh: inter-judge κ 0.74–0.88 vs truth ~0.2; experts are the same.
  - VWO items are ~all variant wins.
- **Predicted:**
  - variant-ID accuracy ≥ 75% for 3.8 Flash (70% subjective confidence);
  - text-only recall near chance (60% confidence);
  - the perturbation drop < 5 pts.
- **Cost:** 3.8 Flash variant-ID on 252 ≈ $1.8; Opus recall on 102 leaks ≈ $1; perturbation on 60 pairs with Opus ≈ $3.4. Total ≈ $6.
- **Smallest test:** the variant-ID probe on dev for 3.8 Flash ($0.54).
- **What changes:** if the prior is confirmed, prefer harness changes that raise accuracy on the 41 "control kept" leaks (report that slice separately as the "anti-prior" metric), and do not market CA as outcome prediction. If recall is high for Opus, report Opus-level CA as contaminated.

### H4: Calibrated abstention as a harness output (confident-call-or-abstain). **Rank 4, product metric; does not raise forced-choice CA.**
- **Change:** emit a call only when order-consistent (and, with H1, |p − 0.5| ≥ τ); otherwise abstain or escalate (H2). Report accuracy at coverage.
- **Evidence:** Squoosh (the only lever that survived); Trust-or-Escalate; section 3.5 offline. 3.8 Flash consistent-only: 68.9% on held-out at 75% coverage, vs 64.1 forced OI. Opus + Pro agreement: 84.9% on held-out at 52% coverage.
- **Predicted:** committed accuracy +4 to +8 over forced OI at 60–80% coverage for cheap models. τ is set on dev and confirmed on held-out.
- **Cost:** $0 extra, on top of H1.
- **Smallest test:** fix τ on the dev H1 outputs and confirm on held-out 177 (no new calls beyond H1).
- **Drop if** held-out committed accuracy is < forced OI + 3 at ≥ 50% coverage.

### H5: Persona-panel harness on a cheap strong model (proprietary / defensible). **Rank 5; low odds, stated honestly.**
- **Change:** 6 generated visitor personas × short-pick × both orders on 3.8 Flash, pooled with graded confidences (H1 aggregation), optionally with the audience from page context.
- **Evidence:**
  - For: SimAB (+10 pp vs a single persona; 67% ≈ plain OI); PerceptUI (real profiles help).
  - Against: Hu & Collier (persona variance <10%); PerceptUI (shuffled / generic personas ≈ none); Squoosh (persona priors null); our 2.5 Flash runs (personas dOI +0.4). Note that our G-FOCUS + personas OI of 63.1 came mostly from rating aggregation, which is H1.
- **Predicted:** OI +0 ± 3 over H1-only 3.8 Flash. P(≥ +3 OI) ≈ 15%.
- **Cost:** 12 calls + planner ≈ $0.045/pair on 3.8 Flash. 252 pairs ≈ $11; dev ≈ $3.4.
- **Smallest test:** 252 at zero-shot. Dev is too small to detect < 15 pts.
- **Drop if** dOI vs H1-only 3.8 Flash is < +3 on 252, or the "control kept" slice does not improve.
- **Keep regardless:** personas as the *explanation / segment* layer (the UserSim UX), not as the accuracy lever.

### H6: Test-time compute knob (thinking_level high / reasoning effort up) on the cheap model. **Rank 6; low odds.**
- **Evidence against:** arXiv 2512.19585; Squoosh (Pro ≡ Flash); CoT can worsen position bias (judgment distribution); G-FOCUS on Pro. Opus (adaptive thinking) is best, but that is confounded with model size.
- **Predicted:** OI 0 ± 4; flips may rise.
- **Cost:** 3.8 Flash thinking high ≈ 2–3x output tokens → ≈ $0.015/pair; 252 ≈ $4. Sol at medium reasoning ≈ $0.02/pair; 252 ≈ $5.
- **Smallest test:** 252 pairs, compared with H1 aggregation.
- **Drop if** dOI < +3.

### Explicitly not recommended (evidence says no)
- Model-vote ensembles of plain judgments (section 3.3: −8.3 vs Opus).
- G-FOCUS on strong models.
- Few-shot, goal, diff list, page text, crops: all null or harmful on 2.5 Flash; Squoosh found prompt redesign and GEPA null.
- SFT on WiserUI (null, and the NC license).
- Browsing persona agents for this benchmark (~$1/eval with only direction-level validation).

### Suggested order (≈ $20 total, all small)
1. H1 on Luna (dev $0.05, then 252 at $0.2) and on 3.8 Flash (252, $2).
2. H3 variant-ID on dev ($0.54), then the full probes (~$6).
3. H2 Opus flip rerun (dev $3.4, or 252 $12).
4. H4 computed from the H1 outputs ($0).
5. Only then H5 ($11) and H6 ($4).
6. Carry the winning harness to Pro / Opus (H1 on Pro 252 ≈ $5; on Opus ≈ $15).

---

## 6. Sources
- Jeon et al., WiserUI-Bench / G-FOCUS, arXiv 2505.05026, ACL 2026 (github.com/jeochris/wiserui-bench, CC BY-NC-SA 4.0)
- Bougie et al., PerceptUI, arXiv 2606.05697
- Rieder et al., SimAB, arXiv 2603.01024
- Dooskin et al. (Squoosh), The Judge Knows When It Knows, arXiv 2608.07517
- Wang et al., Agent A/B, arXiv 2504.09723; Lu et al., UXAgent, arXiv 2502.12561 / 2504.09407
- MLLM as a UI Judge, arXiv 2510.08783
- Ye, Yoganarasimhan, Zheng, LOLA, arXiv 2406.02611; Matias et al., Upworthy Research Archive, Sci. Data 2021
- Spotify Engineering, "When Can LLMs Replace Humans in A/B Tests?", Aug 2026
- Ashokkumar, Hewitt et al., "LLMs can predict the results of social science experiments", Nature, Jul 2026
- Linowski, "What 70,149 Guesses Tell Us About Predicting A/B Tests", GoodUI blog, Nov 2022; goodui.org/tests (630+ experiments)
- Berman et al., "p-Hacking and False Discovery in A/B Testing", 2018; Kohavi, Deng, Vermeer, "A/B Testing Intuition Busters", KDD 2022; Kohavi & Thomke, HBR 2017
- Zheng et al., arXiv 2306.05685; Wang et al., arXiv 2305.17926; Li et al. (PORTIA), arXiv 2310.01432; Tang et al., arXiv 2310.07712; Shi et al., arXiv 2406.07791; Chen et al. (MLLM-as-a-Judge), arXiv 2402.04788
- "Improving LLM-as-a-Judge Inference with the Judgment Distribution", EMNLP Findings 2025; "Increasing the Thinking Budget is Not All You Need", arXiv 2512.19585; Whitehouse et al. (J1), arXiv 2505.10320
- Wang et al. (self-consistency), arXiv 2203.11171; Verga et al. (juries), arXiv 2404.18796; Du et al., arXiv 2305.14325; Khan et al., arXiv 2402.06782
- Jung et al. (Trust or Escalate), arXiv 2407.18370, ICLR 2025; Chen et al. (FrugalGPT), arXiv 2305.05176
- Park et al., arXiv 2411.10109; Hu & Collier, arXiv 2402.10811; Gui & Toubia, arXiv 2312.15524
- Wu et al. (UIClip), arXiv 2404.12500; Duan et al. (UICrit), UIST 2024, github.com/google-research-datasets/uicrit (CC BY 4.0); Wu et al. (WebUI), arXiv 2301.13280
- CreativeRanking, arXiv 2102.04033; Creative4U / CreativePair, arXiv 2508.12628
- MM-Detect, arXiv 2411.03823; multi-modal semantic perturbation contamination detection, ICLR 2026
