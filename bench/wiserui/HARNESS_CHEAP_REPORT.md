# Harness lift on the cheapest current model per frontier lab (WiserUI-Bench, 252 pairs), 2026-09-27

Three rounds against one hard $5 cap. Round 1 ran 7:50–8:15 AM PT, round 2 ran 8:23–8:45, and round 3 (Sonnet 5)
ran 8:49–8:57.

**Total spend: $4.89 of $5.** Round 1 cost $2.20, round 2 $0.83 and round 3 $1.86. The remaining $0.11 is below one
Sonnet pair's worst-case reservation, so the capped run stopped there.

## Round 3 (8:49 AM PT): Anthropic = Claude Sonnet 5, H1 on a random subset

**Haiku: no Haiku ID works in this project.** All probes were free 5-token calls.

| ID | Model Garden entry | rawPredict |
|---|---|---|
| `claude-haiku` | 404 | 404 |
| `claude-3-haiku@20240307` | 404 | 404 |
| `claude-3-5-haiku@20241022` | 404 | 404 |
| `claude-haiku-4-5@20251001` (round 2) | GA, version 20251001 | 404 everywhere; `us` / `eu` 429 with quota 0 |

rawPredict was tried in global, us, us-east5, us-central1, europe-west1, europe-west4 and asia-southeast1.

- The `anthropic-claude-haiku` entry in Cloud Quotas (global 9,000 rpm; us / eu 4,500) is a **family-level quota
  dimension**, not a callable model.
- Model Garden publishes only `claude-haiku-4-5` for Haiku.
- The project needs Model Garden access to `claude-haiku-4-5` (round 2, step 1). The quota is already there.

**Sonnet 5 run** (`claude-sonnet-5`, global with spillover to us / us-east5 / europe-west1). Settings match the saved plain
run: default sampling (Claude 5 has no temperature control), 1568 px, max_tokens 2048.

The thinking headroom was set to 2048 (`MVP_CLAUDE5_THINK_HEADROOM`). That only changes the worst-case reservation:
- the largest observed output was 1,928 tokens in 504 plain calls and 1,200 in the smoke test;
- so the headroom never binds.

- **Smoke test:** 4 pairs, $0.088, i.e. $0.022/pair.
  - Every answer parsed.
  - 3 of the 8 calls answered with only the probability line: 11 output tokens and no analysis.
- **Run:** pairs in the fixed random order `fullset/anthropic_order.txt` (sha256 seed "hc-anthropic", ≈ 30% dev in every
  prefix), capped at the budget.
  - **n = 79 pairs**, an exact prefix of that order: **27 dev + 52 held-out**.
  - $1.865, 0 errors, 08:50:47–08:54:59 PT.

| model | arm | n | CA | single-call CA | OI | dOI vs plain [95% CI] | McNemar p (up/down) | dCA vs plain [95% CI] | p | flip-pair acc (n) | ties | per-call flip rate | $/pair |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Sonnet 5 | plain (saved `van_sonnet5`, same 79 pairs) | 79 | 48.1 | 48.1 | 64.6 | (ref) | | | | 50.0 (26) | | 32.9 | 0.0258 |
| Sonnet 5 | **H1** graded both-order | 79 | 67.7 | 41.8 | **67.7** | **+3.2 [−4.4, +10.8]** | 0.57 (16/12) | +19.6 [+9.5, +29.7] | 0.0015 | 61.5 (26) | 7 | 39.2 | **0.0236** |

- **This subset is easier than average for plain Sonnet** (OI 64.6 here vs 58.1 on all 252). Only the paired delta is
  comparable across models.
- **Same pattern as the other labs.** A large CA gain (+19.6, p = 0.0015) comes from answering once for both orders. The
  OI lift is small and not significant (+3.2, p = 0.57, n = 79; a paired SE of ~4 points).
- **The graded tie-break does resolve flips better than a coin:** 61.5% on plain Sonnet's 26 flip pairs.
- **Per-call position bias did not drop** (flip rate 39% vs plain 33%). Sonnet often gives about 25–35 when the winner is
  shown first and about 60–70 when it is shown second.
- **H1 costs 9% less than plain.** Some answers are just the number, so there is less output.

**H4 abstention on Sonnet: fails.**

| threshold | dev coverage / acc | held-out coverage / committed acc | held-out forced acc | committed − forced |
|---|---|---|---|---|
| τ = 5, picked on the subset's 27 dev pairs | 63.0% / 82.4 | 73.1% (38/52) / 65.8 | 64.4 | +1.4 |
| τ = 20, the 3.8 Flash-style threshold | 40.7% / 81.8 | 40.4% (21/52) / 66.7 | 64.4 | +2.3 |

- Both fail the bar (≥ +3 at ≥ 50% coverage).
- Sonnet's high-confidence calls are *less* accurate on held-out: 60.0 at τ = 25 and 50.0 at τ = 30, with small n.
- The plain order-consistency gate does as well: 67.6% at 71% coverage.
- Held-out curve (τ: coverage / committed accuracy): 0: 100% / 64.4; 10: 65.4% / 64.7; 15: 61.5% / 68.8; 20: 40.4% / 66.7.

**Router with Sonnet 5 H1:** `router_sim.py --extra sonnet5_h1=hc_sonnet5_h1:graded`, scored on the same 79 pairs; output in
`fullset/router_sim_sonnet5_subset.json`.
- Sonnet 5 H1 appears only as a last-stage tie-breaker for 3.8 Flash H1's uncertain pairs (about 5–14% of pairs reach it).
- On held-out it gives 75.0 at $0.0097/pair, but **3.8 Flash H1 alone is also 75.0 on these 52 held-out pairs**. So it adds
  nothing measurable.
- The dev-picked choices here are badly overfit: dev 81–89 vs held-out 70–75 on 27 / 52 pairs.
- Conclusion: Sonnet 5 does not belong in the router at its price. Opus 5.5 remains the only escalation target with
  signal on the cheap models' uncertain pairs.

**Per-lab verdict (all three labs now measured).**

| lab / model | n | dOI of H1 vs plain [95% CI], p | dCA, p | H4 abstention (held-out) | H1 $/pair |
|---|---|---|---|---|---|
| Google, Gemini 3.8 Flash | 252 | +3.4 [−0.4, +7.1], 0.14 | +14.9, 8e-10 | **passes**: 77.8% at 51% coverage (forced 66.7) | 0.0075 |
| OpenAI, GPT-6 Luna | 252 | +1.6 [−2.6, +6.0], 0.35 | +20.6, 1e-13 | fails (+2.2) | 0.0006 |
| Anthropic, Claude Sonnet 5 (Haiku not accessible) | 79 | +3.2 [−4.4, +10.8], 0.57 | +19.6, 0.0015 | fails (+1.4 / +2.3) | 0.0236 |

- **Across all three labs, the harness buys a large, certain CA gain** by removing position flips.
- **The skill gain is modest (+1.6 to +3.4 OI) and not significant for any model** at these n.
- **Only 3.8 Flash's graded confidence is useful for abstaining.**

## Round 2 (8:23 AM PT): Haiku access diagnosis, harness iterations, router proposal

### Step 1. Haiku: root cause (free diagnosis; nothing enabled, no quota requested)

Checked with `bench/wiserui/claude_access.py`, which is free to rerun.

| check | finding |
|---|---|
| Model Garden listing (`v1beta1/publishers/anthropic/models`, listAllVersions) | `claude-haiku-4-5`, version **20251001**, GA. There is no newer Haiku. So the ID `claude-haiku-4-5@20251001` is correct (`claude-haiku-4-5` resolves to the same model). |
| Cloud Quotas API (quotaInfos, aiplatform.googleapis.com) | Haiku 4.5 **has quota**: **global 10,000 rpm** (10M input / 1M output TPM), **us-east5 3,000 rpm**, **europe-west1 3,600 rpm**. The `us` and `eu` multi-region Haiku 4.5 quotas have **no value, i.e. 0**. |
| rawPredict and streamRawPredict, `anthropic_version: vertex-2023-10-16`, v1 and v1beta1, SDK and REST; global, us-east5, europe-west1, us-east1, europe-west4, asia-southeast1, us-central1 | **404 "Publisher model … was not found or your project does not have access to it"** in every region, including the three that have quota. The same request to `claude-sonnet-5` returns 200 on global and on `us`. |
| `us` / `eu` multi-region | 429 `us_multi_region_…requests_per_base_model` (base model anthropic-claude-haiku-4-5). This is **not burst**: it repeated at 0, 10 and 30 s, and that quota is 0. |
| Last check, 08:41 PT | unchanged |

**Root cause.** The endpoint, ID and region are all correct, and quota exists. What's missing is **project access to Haiku 4.5**:
- In every region with quota, the API answers "your project does not have access".
- The console shows default quotas for every published model whether or not it has been enabled, so seeing quota does
  not prove access.
- The most likely fix is the Model Garden **Enable** step (partner terms) for Claude Haiku 4.5 **in
  project-amer-scs-sandbox**. Check the console project selector: the ADC account can see 20 projects, so it may have been
  enabled in a different one.
- The `us` / `eu` multi-region endpoints would also need their own Haiku quota. This is not needed if global works.

**Code fix (`mvp/e2e_ui_run.py`).**
- No ID or region change was needed. The default `CLAUDE_VERTEX_LOCATIONS` (global, us-east5, europe-west1) are exactly
  where Haiku 4.5 has quota, so `llm_generate(model="claude-haiku-4-5@20251001")` works as soon as access is granted.
- Changed: when a Claude model returns 404 in **every** location, the call now fails fast with a clear "not found / no
  project access" error. Before, it retried 8 times with backoff.

**Haiku runs (step 2): not run, $0.** The plan is ready at the end of this section.

### Step 3. Harness iterations (cumulative, one variable at a time; tuned on dev, reported on 252)

**Order.**
- Luna first, because it is nearly free.
- Haiku: unavailable.
- Flash: only the single best variant, and only if it generalized. None did (below).

**Keep rule, fixed before the runs:** keep a change if dev OI is at least +2 points over the current best.

Luna, dev (75 pairs; dev is at chance for plain Luna, OI 50.0):

| step | variant (cumulative on the current best) | dev OI | dev per-call flip rate | decision | $ spent |
|---|---|---|---|---|---|
| base | H1 graded both-order | 51.3 | 41.3% | — | (round 1) |
| (a) | + failure-modes preamble (the change doesn't always win / original often kept; Hick's law; more content isn't better; order is random; judge conversion, not polish) | 49.3 | **25.3%** | drop (−2.0) | 0.051 |
| (b) | + 2 dev-only solved examples (screenshots at 768 px, real outcome, 1-sentence position-free rationale, winner position balanced, leave-one-out) | 57.3 | 37.3% | (+6.0) | 0.086 |
| (b) | + **4** dev-only solved examples | **62.0** | 41.3% | **keep** (+10.7) | 0.113 |
| (c1) | fs4 + 1–7 scale instead of 0–100 | 57.3 | 36.0% | drop (−4.7) | 0.112 |
| (c2) | fs4 + reasoning effort "low" (vs none) | 60.7 | 34.7% | drop (−1.3) | 0.131 |
| (c3) | confidence threshold sweep | see H4 | | $0 | 0 |
| (c) Flash | thinking level "minimal" (cheaper) | — | — | not supported: 400 "Thinking level is unsupported: THINKING_LEVEL_MINIMAL", $0. "low" is the floor. | 0 |

**The dev winner does not generalize.** Luna H1 + 4 shots on all 252 ($0.37):

| model | arm | n | CA | single-call CA | OI | dOI vs plain [95% CI] | McNemar p | dOI vs H1 [95% CI] | p | held-out (177) forced acc | $/pair |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Luna | plain | 252 | 36.5 | 36.5 | 55.6 | (ref) | | | | 57.9 | 0.0006 |
| Luna | H1 | 252 | 57.1 | 42.9 | 57.1 | +1.6 [−2.6, +6.0] | 0.35 | (ref) | | 59.6 | 0.0006 |
| Luna | H1 + debias (round 1) | 252 | 58.1 | 44.0 | 58.1 | +2.6 [−2.2, +7.5] | 0.29 | +1.0 [−4.2, +6.2] | 1.0 | 61.0 | 0.0006 |
| Luna | **H1 + 4 dev shots** | 252 | 59.5 | 35.3 | 59.5 | +4.0 [−1.2, +9.3] | 0.31 | +2.4 [−3.0, +7.7] | 0.27 | **58.5 (< H1's 59.6)** | 0.0015 |

- The whole +2.4 over H1 comes from dev, where the examples come from: +10.7 on dev, −1.1 on held-out.
- This is the overfitting warned about in the brief. Dev examples share the dev distribution, and 75 dev pairs cannot
  resolve a gain under ~15 points.
- H4 on fs4 also fails. The dev-picked τ is 0, and at 45% held-out coverage the committed accuracy is 63.3.
- Few-shot also costs 2.5× on Luna. On 3.8 Flash it would cost **$0.019/pair** (measured: 11.3k input tokens per call in
  a 4-pair smoke test, $0.078), i.e. $4.8 on 252.
- So it was **not run on Flash**. No other variant passed on Luna either, so no Flash iteration was paid for.

**Best harness per model** (judged on OI over all 252 and on held-out):

| model | best harness | OI (252) | dOI vs plain [95% CI], p | abstention (held-out) | $/pair |
|---|---|---|---|---|---|
| Gemini 3.8 Flash | **H1 graded both-order + H4 (τ = 20)** | 69.2 | +3.4 [−0.4, +7.1], p = 0.14 | **77.8% at 50.8% coverage** (forced 66.7) | 0.0075 |
| GPT-6 Luna | **H1** (debias and few-shot not significant; few-shot fails held-out) | 57.1 | +1.6 [−2.6, +6.0], p = 0.35 | no useful gate (+2.2, fails) | 0.0006 |
| Claude Haiku 4.5 | not measurable (no project access) | — | — | — | — |

### Step 4. ROI router proposal (offline simulation, $0, no build)

`router_sim.py` cascades the saved judgments. Stage models:
- Luna H1 and 3.8 Flash H1, graded: they escalate when |p(A) − 50| < τ.
- Plain runs of Luna, 3.8 Flash, Sol, 3.1 Pro, Sonnet 5 and Opus 5.5: they escalate on a flip.

Accuracy is order-invariant (OI). Cost is the metered cost of every stage a pair visits. The plot is
`fullset/router_frontier.png`.

n = 252 pairs (dev 75, held-out 177); 530 cascades

Single systems (order-invariant accuracy = OI):

| system | acc all | acc held-out | $/pair |
|---|---|---|---|
| luna | 55.6 | 57.9 | 0.0006 |
| luna_h1 | 57.1 | 59.6 | 0.0006 |
| flash | 65.9 | 64.1 | 0.0072 |
| flash_h1 | 69.2 | 66.7 | 0.0075 |
| sol | 58.1 | 57.1 | 0.0115 |
| pro | 70.8 | 68.1 | 0.0192 |
| sonnet5 | 58.1 | 57.1 | 0.0258 |
| opus | 75.4 | 74.9 | 0.0562 |

In-sample Pareto frontier (all 252; taus chosen on the same pairs, optimistic):

| cascade | acc all | $/pair | share reaching each stage |
|---|---|---|---|
| luna | 55.6 | 0.0006 | 100.0 |
| luna_h1 | 57.1 | 0.0006 | 100.0 |
| luna -> luna_h1 | 57.9 | 0.0008 | 100.0 / 38.1 |
| luna -> luna_h1(tau5) -> flash_h1 | 59.3 | 0.0016 | 100.0 / 38.1 / 11.1 |
| luna -> luna_h1(tau10) -> flash_h1 | 61.9 | 0.0021 | 100.0 / 38.1 / 17.5 |
| luna_h1(tau10) -> flash_h1 | 62.3 | 0.0025 | 100.0 / 25.0 |
| luna_h1(tau15) -> flash_h1 | 62.7 | 0.0032 | 100.0 / 34.9 |
| luna_h1(tau20) -> flash_h1 | 63.5 | 0.0040 | 100.0 / 44.0 |
| luna_h1(tau25) -> flash | 64.5 | 0.0049 | 100.0 / 59.5 |
| luna_h1(tau25) -> flash_h1 | 66.3 | 0.0051 | 100.0 / 59.5 |
| luna_h1(tau25) -> flash_h1(tau5) -> pro | 66.5 | 0.0067 | 100.0 / 59.5 / 8.3 |
| luna_h1(tau25) -> flash_h1(tau10) -> pro | 67.1 | 0.0074 | 100.0 / 59.5 / 12.3 |
| luna_h1(tau35) -> flash_h1 | 67.5 | 0.0075 | 100.0 / 91.3 |
| flash_h1 | 69.2 | 0.0075 | 100.0 |
| flash_h1(tau5) -> pro | 69.6 | 0.0104 | 100.0 / 13.1 |
| flash_h1(tau10) -> pro | 70.0 | 0.0114 | 100.0 / 18.7 |
| flash_h1(tau15) -> pro | 70.6 | 0.0131 | 100.0 / 27.8 |
| flash_h1(tau20) -> pro | 71.0 | 0.0159 | 100.0 / 42.5 |
| flash_h1(tau10) -> pro -> opus | 71.8 | 0.0164 | 100.0 / 18.7 / 9.1 |
| flash_h1(tau10) -> opus | 72.2 | 0.0179 | 100.0 / 18.7 |
| flash_h1(tau15) -> pro -> opus | 72.8 | 0.0203 | 100.0 / 27.8 / 12.7 |
| flash_h1(tau20) -> pro -> opus | 74.4 | 0.0259 | 100.0 / 42.5 / 17.5 |
| flash_h1(tau25) -> pro -> opus | 75.8 | 0.0306 | 100.0 / 57.1 / 20.6 |
| flash_h1(tau30) -> pro -> opus | 76.0 | 0.0340 | 100.0 / 68.7 / 22.6 |

Honest: cascade + taus picked on dev (max dev acc with dev $/pair <= budget), scored on held-out; vs the best single system under the same budget picked the same way:

| budget $/pair | picked on dev | dev acc | held-out acc | held-out $/pair | best single (dev-picked) | its held-out acc | its $/pair |
|---|---|---|---|---|---|---|---|
| 0.001 | luna_h1 | 51.3 | 59.6 | 0.0006 | luna_h1 | 59.6 | 0.0006 |
| 0.002 | luna_h1(tau5) -> flash_h1 | 54.0 | 61.3 | 0.0017 | luna_h1 | 59.6 | 0.0006 |
| 0.004 | luna_h1(tau15) -> flash_h1 | 63.3 | 62.4 | 0.0029 | luna_h1 | 59.6 | 0.0006 |
| 0.008 | flash_h1 | 75.3 | 66.7 | 0.0076 | flash_h1 | 66.7 | 0.0076 |
| 0.012 | flash_h1(tau5) -> pro | 76.0 | 66.9 | 0.0106 | flash_h1 | 66.7 | 0.0076 |
| 0.020 | flash_h1(tau10) -> opus | 78.7 | 69.5 | 0.0175 | pro | 68.1 | 0.0193 |
| 0.030 | flash_h1(tau25) -> pro -> opus | 80.7 | 73.7 | 0.0317 | pro | 68.1 | 0.0193 |
| 0.060 | flash_h1(tau25) -> pro -> opus | 80.7 | 73.7 | 0.0317 | pro | 68.1 | 0.0193 |


**Recommended path (not built).**
1. **Default: 3.8 Flash H1 plus the H4 gate.**
   - 69.2 OI (66.7 on held-out) at $0.0075/pair.
   - As a product, "confident call or abstain": 77.8% on held-out at 51% coverage.
2. **Budget tier: Luna H1 → 3.8 Flash H1** when |p − 50| < 15 (dev-picked).
   - 62.4 on held-out at $0.0029/pair: 38% of Flash's cost for −4.3 points.
   - Worth it only where cost dominates (bulk screening).
3. **Quality tier: 3.8 Flash H1 → 3.1 Pro → Opus 5.5** (τ = 25, dev-picked).
   - **73.7 on held-out at $0.032/pair**, vs Opus alone at 74.9 for $0.056. That is 57% of the cost for −1.2 points.
   - 3.8 Flash H1 (τ = 10) → Opus gives 69.5 at $0.0175, which beats 3.1 Pro alone (68.1 at $0.019).
   - Escalation only works toward Opus. The cheap models' uncertain pairs are near-coin for Pro (RESEARCH_HYPOTHESES.md
     §3.4).
4. **Next paid step, when a router is worth building:** run H1 (graded) on Pro and Opus for the escalated pairs only.
   Their plain flips are coin flips here, so the frontier above is a lower bound for those stages. Also run Haiku H1 to
   see whether it can replace Luna as the cheap first stage.

**Caveats.**
- The frontier is in-sample: taus and chains are picked on the same 252 pairs. The dev-picked, held-out rows are the
  honest numbers, and they are 2–7 points lower.
- There are 530 configurations but only 75 dev pairs, so the choice itself is noisy.
- Held-out and all-252 accuracies are on different pair sets. Luna does better on held-out than on dev, so at the cheapest
  budget the held-out curve sits above the in-sample frontier.
- Opus and Sonnet 5 ran without temperature control, so their rerun noise is unmeasured.
- The same variant-prior and label-noise caveats as RESEARCH_HYPOTHESES.md apply.
- Costs are list prices. Latency of sequential escalation is not modelled (about +1 call round-trip for 20–60% of pairs).

**What a learned router would need.**
- **Features that are available cheaply at stage 1:**
  - the graded margin and the per-call flip;
  - page type, platform and source;
  - the kind of difference: element and attribute of the change. The product can get this from the difference list, and
    it matters: Hick's-law / removal and multi-element changes are where the cheap models fail, RESEARCH_HYPOTHESES.md
    §3.2.
- **Validation:** grouped cross-validation by company or site, because the same company shows up in several pairs. It
  should be pre-registered, with a held-out test set that is never used for thresholds.
- **Data:** 252 labelled pairs support at most a 1–2-parameter threshold cascade. A router with 5+ features needs roughly
  1–2k labelled A/B outcomes, preferably with:
  - control-won and flat tests;
  - per-arm counts;
  - post-cutoff dates.

  These are the evaluation-data needs already listed in RESEARCH_HYPOTHESES.md §4. Partner or customer A/B history is the
  realistic source.

### Haiku plan (ready once access is granted; the $1.97 was spent on Sonnet 5 in round 3, so it needs new budget)

```bash
python3 bench/wiserui/claude_access.py          # must show "claude-haiku-4-5@20251001 global: 200 OK"
R=/workspace/bench/wiserui/results I=@bench/wiserui/fullset/anthropic_order.txt   # fixed random order, ~30% dev per prefix
python3 bench/wiserui/run_bench.py --stream vanilla --model claude-haiku-4-5@20251001 --indices 102,258,156,42 --out $R/hc_haiku_plain --max-cost 0.1   # smoke: measure tokens
# then both arms in parallel with equal caps (~$0.95 each => ~100 pairs at the estimated $0.018/pair for plain + H1):
python3 bench/wiserui/run_bench.py --stream vanilla --model claude-haiku-4-5@20251001 --indices $I --out $R/hc_haiku_plain --concurrency 16 --max-cost 0.95 &
python3 bench/wiserui/run_bench.py --stream h1      --model claude-haiku-4-5@20251001 --indices $I --out $R/hc_haiku_h1    --concurrency 16 --max-cost 0.95 &
python3 bench/wiserui/harness_cheap.py haiku=$R/hc_haiku_plain,h1=$R/hc_haiku_h1
```

**Round 2 spend and time.**
- Spend: $0.83 on Luna dev iterations, the Luna fs4 run on 252, and the Flash fs4 smoke test. The 3.8 Flash "minimal"
  probe and the Haiku probes were free.
- Paid calls ran 08:27:57–08:40:51 PT (13 min, mostly sequential dev steps).
- Round 2 code: `claude_access.py`, `router_sim.py`, the step-3 flags, the e2e_ui_run fail-fast, and 2 new tests. 30 tests
  pass.

---

# Round 1 (7:50 AM PT)

## Round 1 report

**Question.** How much does a *harness* lift the cheapest current SOTA model from each lab over its own plain baseline, when
the model is held fixed? The arms come from `RESEARCH_HYPOTHESES.md` (commit 4d7d454) and are cumulative:
- **H1**: graded both-order;
- **H4**: abstention on top of H1, $0 extra;
- one extra cheap arm: **H1 + debias**.

Budget: a hard $5 total cap, approved 7:50 AM PT. Opus is excluded.

## TL;DR

| lab / model | arm | n | CA | OI | dOI vs plain [95% CI] | McNemar p (up/down) | $/pair |
|---|---|---|---|---|---|---|---|
| Google **Gemini 3.8 Flash** | plain (saved `van_g38flash`) | 252 | 54.4 | 65.9 | (ref) | | 0.0072 |
| | **H1** graded both-order | 252 | 69.2 | **69.2** | **+3.4 [−0.4, +7.1]** | 0.14 (40/27) | 0.0075 |
| OpenAI **GPT-6 Luna** | plain (saved `van_gpt6luna`) | 252 | 36.5 | 55.6 | (ref) | | 0.0006 |
| | **H1** | 252 | 57.1 | 57.1 | +1.6 [−2.6, +6.0] | 0.35 (52/42) | 0.0006 |
| | **H1 + debias** | 252 | 58.1 | 58.1 | +2.6 [−2.2, +7.5] | 0.29 (60/48) | 0.0006 |
| Anthropic **Claude Haiku 4.5** | not run: unavailable in the project (see below) | 0 | — | — | — | — | — |

1. **H1 lift is real but small on OI and not significant.** The large CA gains (+14.9 on 3.8 Flash, +20.6 on Luna, both
   p < 1e-9) are almost all the mechanical swap-aggregate effect: one answer for both orders turns flips into coin flips.
   Judged on OI:
   - 3.8 Flash: +3.4, p = 0.14. The CI just crosses 0.
   - Luna: +1.6, p = 0.35.

   The graded tie-break does carry some signal. On each model's own plain flip pairs, H1 is right 56.0% (3.8 Flash, n = 58)
   and 56.2% (Luna, n = 96), vs 50% for a coin. Both beat the research doc's drop threshold of ≤ 52%.
2. **H4 abstention is the real product lever, and only on 3.8 Flash.**
   - 3.8 Flash: τ = 20 points of |p(A) − 50|, fixed on dev. Held-out committed accuracy is **77.8% at 50.8% coverage** vs
     66.7% forced, so **+11.1**. That passes the research doc's "forced + 3 at ≥ 50% coverage" bar.
   - At matched ~75% coverage (τ = 15: 71.0% at 74.0%), it beats the $0 plain order-consistency gate (68.9% at 74.6%) by
     about +2.
   - Luna: +2.2 at 69.5% coverage, which fails the bar. Its plain order-consistency gate is as good (62.7% at 62%).
3. **Debias instruction (third arm) on Luna: +1.0 OI over H1 [−4.2, +6.2], p = 1.0. No effect.** It was not run on 3.8
   Flash, to keep the budget for the Anthropic arm (see Spend).
4. **Anthropic: no measurement.**
   - Claude Haiku 4.5 is still not callable at 08:12 PT, 19 minutes after the 7:53 "enabled" note:
     - 404 "not found or no access" on global, us-east5, europe-west1 and us-central1;
     - 429 "Quota exceeded … `us_multi_region_online_prediction_requests_per_base_model` / `eu_multi_region…`, base model
       anthropic-claude-haiku-4-5" on the `us` and `eu` multi-region endpoints.
   - Per the 7:53 instruction ("Haiku instead of Sonnet 5"), Sonnet 5 was not run. The remaining **$2.80 is left unspent
     for Haiku**; see "Next" for the ready-to-run commands.
   - Nothing was enabled and no quota was requested.
5. **Spend: $2.20 of the $5 cap.** 3.8 Flash H1 $1.886, Luna H1 $0.158, Luna H1 + debias $0.156; the Haiku probes were not
   billed. Wall time of the paid runs: 07:54:09–07:58:25 PT (4.3 min, three runs in parallel).

**Verdict per lab.**
- **Google (3.8 Flash):** the harness helps. Forced-choice gain is a modest +3.4 OI (p = 0.14; the n needed to confirm it
  is roughly 2.5× larger). Its graded confidence gives a strong selective-prediction curve (≈ 78–82% at 30–50% coverage on
  held-out). H1 + H4 is worth keeping.
- **OpenAI (Luna):** no real skill lift. OI is still ~57–58. The harness mainly removes Luna's position bias (the CA
  jump). Its confidence is poorly calibrated (dev committed accuracy 51–61% at any τ).
- **Anthropic:** unmeasured (model not available).

---

## Setup

- **Models and settings: identical to each model's saved plain run.** Temperature 0, max_tokens 2048, screenshots fit to
  1568 px, same bytes.
  - 3.8 Flash: thinking_level low, global endpoint.
  - Luna: `reasoning_effort=none`.

  The only change is the prompt's final instruction.
- **Plain** = the saved vanilla runs (WiserUI paper zero-shot prompt, "More effective: First/Second"), reused at $0.
- **H1** (`run_bench.py --stream h1`; `PairFlags(short_pick, vanilla, graded)`):
  - The same vanilla prompt text, but each call ends with "P(First more effective): <0-100>" (0 = surely Second,
    50 = cannot tell).
  - The harness maps both orders to p(A) = mean(p_ab, 100 − p_ba) / 100 and emits **one answer used for both
    presentations**, plus `confidence` = |p(A) − 0.5| · 2.
  - Exact ties (p(A) = 0.5, e.g. the same P(First) in both orders, which is pure position bias) count 0.5. There were 11
    such pairs on 3.8 Flash and 10 on Luna.
- **H1 + debias** (`--stream h1_debias`): adds three lines:
  - "the order of the screenshots is random, do not favour first/second";
  - "more content/options is not automatically better; removing distractions, reducing choices and simplifying often
    wins";
  - "judge the likely conversion effect, not polish or feature-richness".

  This targets the two failure modes in `RESEARCH_HYPOTHESES.md`: second-position bias and the Hick's-law blind spot.
- **H4** (`PairFlags.abstain_margin`, curves in `harness_cheap.py`): commit only when |p(A) − 50| ≥ τ.
  - Rule fixed before the runs: on dev (75), take the τ in {0, 5, …, 45} with the highest committed accuracy subject to
    ≥ 50% dev coverage.
  - Check that τ on held-out (177).
  - Drop rule: held-out committed accuracy < forced + 3 at ≥ 50% coverage.
- **Scoring** (`harness_cheap.py`):
  - CA: strict, both orders.
  - OI: order-free; a flip counts 0.5, and H1 ties count 0.5.
  - Single-call CA: each call's own pick, paper-comparable: 3.8 Flash 57.9, Luna 42.9, Luna + debias 44.0.
  - Paired vs plain on all 252: 10k bootstrap CI, and an exact McNemar in sign-test form (pairs where the arm scores higher
    / lower; identical to McNemar for 0/1 scores, and it handles OI's 0.5s).
- **Cost** is metered from provider usage at list price.
  - Estimates from measured smoke tokens (4 pairs) before the full runs: 3.8 Flash $0.0082/pair (actual $0.0075), Luna
    $0.00076/pair (actual $0.0006).
  - H1 costs about +4% over plain on 3.8 Flash (slightly more output) and the same on Luna.

## Full results (all 252 pairs)

| model | arm | n | CA | single-call CA | OI | dOI vs plain [95% CI] | McNemar p (up/down) | dCA vs plain [95% CI] | p | flip-pair acc (n) | ties | per-call flip rate | unparsed | $/pair |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 3.8 Flash | plain | 252 | 54.4 | 54.4 | 65.9 | (reference) | | | | 50.0 (58) | | 23.0 | | 0.0072 |
| 3.8 Flash | h1 | 252 | 69.2 | 57.9 | 69.2 | +3.4 [−0.4, +7.1] | 0.14 (40/27) | +14.9 [+10.3, +19.6] | 8.2e-10 | 56.0 (58) | 11 | 21.0 | 0 | 0.0075 |
| Luna | plain | 252 | 36.5 | 36.5 | 55.6 | (reference) | | | | 50.0 (96) | | 38.1 | | 0.0006 |
| Luna | h1 | 252 | 57.1 | 42.9 | 57.1 | +1.6 [−2.6, +6.0] | 0.35 (52/42) | +20.6 [+15.3, +26.2] | 1.4e-13 | 56.2 (96) | 10 | 27.8 | 3 | 0.0006 |
| Luna | h1_debias | 252 | 58.1 | 44.0 | 58.1 | +2.6 [−2.2, +7.5] | 0.29 (60/48) | +21.6 [+15.9, +27.6] | 2e-11 | 56.8 (96) | 15 | 25.8 | 0 | 0.0006 |

How to read the columns:
- **Per-call flip rate** is how often the two graded calls name the same *position*.
  - Graded output alone cuts it only a little: 3.8 Flash 23 → 21%, Luna 38 → 28%, Luna + debias 26%.
  - So the gain comes from averaging the probabilities, not from calls that are less biased.
- **Luna + debias vs Luna H1** (paired): dOI +1.0 [−4.2, +6.2], p = 1.0.

## H4 abstention (τ fixed on dev, checked on held-out)

| model | arm | τ (dev) | dev cov / acc | held-out cov / committed acc | held-out forced acc | committed − forced | plain order-consistent gate, held-out cov / acc | plain OI held-out |
|---|---|---|---|---|---|---|---|---|
| 3.8 Flash | h1 | 20 | 56.0% / 85.7 | 50.8% (90/177) / **77.8** | 66.7 | **+11.1** (passes) | 74.6% / 68.9 | 64.1 |
| Luna | h1 | 15 | 54.7% / 58.5 | 69.5% (123/177) / 61.8 | 59.6 | +2.2 (fails) | 62.1% / 62.7 | 57.9 |
| Luna | h1_debias | 20 | 54.7% / 53.7 | 57.1% (101/177) / 63.4 | 61.0 | +2.3 (fails) | 62.1% / 62.7 | 57.9 |

Coverage / committed accuracy by τ (points of |p(A) − 50|):

| τ | 3.8 Flash dev | 3.8 Flash held-out | 3.8 Flash all | Luna dev | Luna held-out | Luna all |
|---|---|---|---|---|---|---|
| 0 | 100% / 75.3 | 100% / 66.7 | 100% / 69.2 | 100% / 51.3 | 100% / 59.6 | 100% / 57.1 |
| 5 | 82.7% / 82.3 | 85.9% / 69.1 | 84.9% / 72.9 | 80.0% / 51.7 | 84.2% / 59.7 | 82.9% / 57.4 |
| 10 | 74.7% / 83.9 | 79.1% / 71.4 | 77.8% / 75.0 | 61.3% / 56.5 | 78.0% / 61.6 | 73.0% / 60.3 |
| 15 | 68.0% / 84.3 | 74.0% / 71.0 | 72.2% / 74.7 | 54.7% / 58.5 | 69.5% / 61.8 | 65.1% / 61.0 |
| 20 | 56.0% / 85.7 | 50.8% / 77.8 | 52.4% / 80.3 | 48.0% / 61.1 | 57.6% / 62.7 | 54.8% / 62.3 |
| 25 | 42.7% / 90.6 | 42.9% / 78.9 | 42.9% / 82.4 | 34.7% / 65.4 | 42.9% / 63.2 | 40.5% / 63.7 |
| 30 | 32.0% / 91.7 | 31.1% / 81.8 | 31.3% / 84.8 | 18.7% / 64.3 | 19.2% / 64.7 | 19.0% / 64.6 |
| 35 | 16.0% / 100 | 21.5% / 84.2 | 19.8% / 88.0 | 10.7% / 62.5 | 7.9% / 64.3 | 8.7% / 63.6 |
| 40 | 4.0% / 100 | 6.8% / 91.7 | 6.0% / 93.3 | 4.0% / 66.7 | 4.0% / 85.7 | 4.0% / 80.0 |

Luna + debias curve (held-out): 100% / 61.0 → 72.9% / 64.3 (τ 10) → 43.5% / 67.5 (τ 25) → 24.9% / 68.2 (τ 30).

Caveats:
- Dev is easy for the Geminis (dev forced 75.3 vs held-out 66.7), so 3.8 Flash's dev accuracies overstate. The held-out
  numbers are the claim.
- The same variant-prior caveat as `RESEARCH_HYPOTHESES.md` 3.5 applies to all committed accuracies.

## Anthropic model: what was tried

| time (PT) | model ID | endpoints | result |
|---|---|---|---|
| 07:51 | `claude-haiku-4-5@20251001`, `claude-haiku-4-5` | global / us | 404 / 429 quota (`us_multi_region_online_prediction_requests_per_base_model`, base model anthropic-claude-haiku-4-5) |
| 07:53 → 08:13 (after the "enabled" note; 13 probes) | `claude-haiku-4-5@20251001` | global, us (+ us-east5, europe-west1, us-central1, eu once) | global and all regions 404; us / eu 429 quota |

- Every probe was a 5-token "Say OK". None was billed.
- Likely causes: Model Garden enablement has not reached the global or regional endpoints, and the multi-region quota for
  Haiku is 0. A quota increase is a GCP change, so it was not requested.
- Sonnet 5 fallback: an H1-only run (plain on 252 is saved) was costed at $0.026/pair, so ≈ 100 pairs for the remaining
  budget. It was not run, because the 7:53 instruction replaced Sonnet 5 with Haiku.

## Next (ready to run once Haiku answers)

Estimate (not measured; Sonnet 5's ~2,300 input tokens at Haiku's $1/$5, no thinking): ~$0.009/pair per arm, so
plain + H1 ≈ $0.018/pair. With $2.80 left that is **≈ 150 pairs** of the fixed random order
`fullset/anthropic_order.txt`, which has ~30% dev in every prefix.

Run a 4-pair smoke test first to measure tokens. Then run both arms in parallel with equal caps (about $1.35 each), and
score on the intersection:

```bash
export CLAUDE_VERTEX_LOCATIONS=global,us,eu,us-east5,europe-west1 R=/workspace/bench/wiserui/results I=@bench/wiserui/fullset/anthropic_order.txt
python3 bench/wiserui/run_bench.py --stream vanilla --model claude-haiku-4-5@20251001 --indices $I --out $R/hc_haiku_plain --concurrency 16 --max-cost 1.35 &
python3 bench/wiserui/run_bench.py --stream h1      --model claude-haiku-4-5@20251001 --indices $I --out $R/hc_haiku_h1    --concurrency 16 --max-cost 1.35 &
python3 bench/wiserui/harness_cheap.py haiku=$R/hc_haiku_plain,h1=$R/hc_haiku_h1
```

## Reproduce

```bash
R=/workspace/bench/wiserui/results I=@bench/wiserui/fullset/final_indices_main.txt
python3 bench/wiserui/run_bench.py --stream h1 --model gemini-3.8-flash --indices $I --out $R/hc_flash_h1 --concurrency 32 --max-cost 2.35
OPENAI_REASONING_EFFORT=none python3 bench/wiserui/run_bench.py --stream h1 --model gpt-6-luna --indices $I --out $R/hc_luna_h1 --concurrency 32 --max-cost 0.30
OPENAI_REASONING_EFFORT=none python3 bench/wiserui/run_bench.py --stream h1_debias --model gpt-6-luna --indices $I --out $R/hc_luna_h1d --concurrency 32 --max-cost 0.28
python3 bench/wiserui/harness_cheap.py flash=$R/van_g38flash,h1=$R/hc_flash_h1 luna=$R/van_gpt6luna,h1=$R/hc_luna_h1,h1_debias=$R/hc_luna_h1d
python3 bench/wiserui/spend.py $R/hc_* --cap 5
```

## Code

- **`mvp/pairwise.py`:**
  - `PairFlags.graded` and `abstain_margin`, reusing `debias` for the graded prompt;
  - `GRADED_PROMPT` / `GRADED_DEBIAS` / `graded_prompt`, `parse_graded` (last "P(First more effective): N", tolerant of
    markdown and %);
  - `graded_answer` (the order-invariant p(A), winner, confidence, abstain), `short_call_tag`;
  - `compare_pair_short` returns the harness answer in `orders` for both presentations, keeps the per-call view in
    `call_orders`, and returns `p_a` / `confidence` / `abstain`. The product path is `compare_pair(..., PairFlags(short_pick=True, vanilla=True, graded=True, model=...))`.
    Any provider works via `default_call` → `llm_generate`.
- **`mvp/e2e_ui_run.py`:** `think_headroom(model)`, the thinking/reasoning output headroom that `llm_generate` adds.
  - Defaults are unchanged: Gemini 3 8192, Claude 5 8192, OpenAI reasoning 4096.
  - It is env-tunable and is now shared with the budget reservation.
- **`bench/wiserui/run_bench.py`:**
  - streams `h1` and `h1_debias`;
  - the worst-case reservation uses the per-model headroom (tighter, still a hard cap);
  - judgments rows carry `p_a`, `confidence` and `call_p_first`.
- **`bench/wiserui/harness_cheap.py`** (scoring and H4) and **`bench/wiserui/spend.py`** (total across ledgers).
- **Tests:** `mvp/test_pairwise.py`, with 6 new tests: parse; one answer for both orders under position bias; a
  pure-bias tie abstains; swap symmetry, a single parsed order and the abstain margin; the debias prompt and cache tag;
  headroom. 28 passed.
