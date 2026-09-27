# Harness lift on the cheapest current model per frontier lab (WiserUI-Bench, 252 pairs), 2026-09-27, 7:50–8:15 AM PT

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
