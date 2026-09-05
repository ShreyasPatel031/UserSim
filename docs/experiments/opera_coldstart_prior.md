# Spec: OPeRA funnel cold-start prior

**Status:** locked for implementation. Do not run LLM arms until §4–§6 freezes exist on disk.  
**Claim is pre-registered.** Discovering a different crossover after the plot and rewriting §1 is a failed run.

---

## 1. Claim (locked)

> On OPeRA funnel next-action-type prediction, a prompted LLM’s prior is worth **roughly 3–5 real sessions** of counting data per `(state × prev)` bucket — measured against **counting + shrinkage**, not raw counting — and is **not** worth 8+.

| Regime | Expected winner |
|---|---|
| `k ∈ {0, 2, 3}` | Best LLM arm beats `count@k + shrinkage` |
| `k = 5` | Roughly tied with `count@k + shrinkage` |
| `k ∈ {8, 12}` | `count@k + shrinkage` wins |

If the LLM never beats shrinkage at `k ≤ 3`, the claim fails.  
If the LLM still wins at `k ≥ 8`, the prior is stronger than claimed — that is a **new** claim and needs a new spec, not a retrofit of this one.

**Not the claim:** “worth 8 users,” “beats the half-A frequency table / noise ceiling (~66),” or “same-bucket demos help.”

Reference points that define the competitor (same split protocol as the feasibility check):

| k | S(`count@k`) | S(`count@k + shrinkage`) |
|---|---|---|
| 2 | ~8 | **~23.5** |
| 3 | ~21 | **~32.2** |
| 5 | ~35 | **~40.2** |
| 8 | ~46 | **~46.3** |
| 12 | ~53 | ~50.5 |
| all | ~65 | ~57 |

An LLM at ~42 only sits above that shrinkage column for `k ≲ 5`. The window is narrow; that is why the framing is locked before the run.

---

## 2. Why the original design is dead (record)

Verified independently (no LLM):

| Estimator | Author | Critique |
|---|---|---|
| Global marginal | 3.9 ± 1.7 | 5.6 ± 0.9 |
| Half-A per-bucket frequency table | 65.9 ± 2.8 | 65.1 ± 1.7 |
| Mean TVD(half-A, half-B) | 0.199 | 0.221 |

Best SimBench-style LLM config we have is ~42. The conditional frequency table already sits on the measurable noise ceiling. So:

1. Global marginal is a straw baseline once you condition on funnel structure.
2. Same-bucket “same-family demos” are leakage (the demo *is* the answer).
3. Competing with the full half-A table is not a cold-start question.
4. Shrinkage on the **counting** table is a different object from isotonic on **LLM** outputs — the latter may still be tried on LLM arms only (§6.1); it does not rescue an in-distribution design that cannot beat ~66.

---

## 3. Task

For each eligible bucket, predict a **distribution over next action types** (percentages summing to 100). Score against the held-out human half with the SimBench formula:

\[
S = 100 \cdot \left(1 - \frac{\mathrm{TVD}(\hat{p},\, p_B)}{\mathrm{mean}_j\,\mathrm{TVD}(p_j,\, \mathrm{Uniform})}\right)
\]

Denominator: mean TVD-to-uniform over the scored headline buckets in that split (same convention as our SimBench ablations).  
Unit of evaluation: one bucket’s distribution — not top-1 step accuracy.

---

## 4. Vocabulary (decided in this spec)

### 4.1 How a row gets a label

```text
if gold_action.type == "terminate":
    label = terminate
elif gold_action.type != "click":
    label = gold_action.type          # search, type_and_submit, …
else:
    label = click_type                # may be empty only if data is corrupt
```

Blank `click_type` is **not** unlabeled junk: it marks non-click rows that are already typed by `gold_action.type`. Real junk mass is only:

| Source | n | share |
|---|---|---|
| `click_type = other` | 449 | 7.7% |
| `click_type = page_related` | 198 | 3.4% |
| **Total junk** | **647** | **~11%** |

### 4.2 Headline simplex (what primary S uses)

| Rule | Classes |
|---|---|
| Keep | Every non-junk label produced by §4.1 **except** `terminate` |
| Collapse | `other` ∪ `page_related` → **`other_ui`** |
| **Exclude** | **`terminate`** |

After exclusion, renormalize each bucket’s empirical distribution over the remaining classes before TVD / S.

Exact enum is frozen in `vocab_freeze.json` from a full-data `value_counts` dump (see §4.4). Expected headline set is on the order of:

`search`, `type_and_submit` *(or merged — freeze decides)*, `product_link`, `product_option`, `review`, `filter`, `suggested_term`, `quantity`, `purchase`, `nav_bar`, `cart_side_bar`, `cart_page_select`, `other_ui`, …

If `type_and_submit` and `search` are both present in the dump, **keep them separate** unless a freeze note merges them with a one-line rationale. Do not silently drop either.

### 4.3 Terminate — side metric only

- Count: **208 / 5856 = 3.6%**.
- Allowed as a **previous-action** label when forming the bucket key (§5).
- **Never** a mass in the headline prediction simplex.
- Report a **separate** binary head `{terminate, ¬terminate}` (TVD or PR), with an explicit **truncation caveat**: session end can reflect logging horizon / task stop, not only abandonment.
- Binary metrics must not be mixed into the primary S(k) plot.

### 4.4 Freeze

Before any scored arm:

1. Dump full-data label counts under §4.1.
2. Write `vocab_freeze.json`: `{headline_classes, collapse_map, exclude, counts, sha256}`.
3. Hash into the run manifest. Changing vocab after the first scored arm invalidates the run.

---

## 5. Bucketing (exact, locked)

**Primary key for every arm and every bootstrap:**

```text
bucket = (funnel_state, prev_label)
```

| Field | Definition |
|---|---|
| `funnel_state` | Coarse page family of the **current** observation at the decision point (e.g. `home` / `results` / `pdp` / `cart` / …). Extracted from the `Current observation` HTML/title/name-prefix of that step — **not** from the gold action being predicted. Exact extractor code is pinned in the freeze. |
| `prev_label` | §4.1 label of the previous step in-session, or `START` if `step_index` is first. May be `terminate` even though terminate is excluded from the *predicted* headline simplex. |

**Eligibility (literal):**

- ≥ **30** actions in the bucket on full data (before the session split)
- ≥ **15** distinct sessions

Author verification at these thresholds:

| Scheme | Eligible buckets |
|---|---|
| `state × depth` | 10 |
| **`state × prev` (this spec)** | **23** |
| `prev` only | 13 |

**Use the 23 `state × prev` buckets.** Do not cite 37 (that was an alternate `prev × depth` proxy and does not match the author’s check).

### 5.1 Freeze gate

`bucket_manifest.json` must list exactly **23** eligible keys under the pinned extractor + §4 vocab + thresholds above.  
If `len(eligible) ≠ 23`, **stop** — reconcile the `funnel_state` extractor against the author’s verification before any LLM call. Do not proceed with “close enough.”

Also record per-bucket `{n_actions, n_sessions}` and coverage (actions in eligible buckets / 5856).

---

## 6. Arms

Backbone: Gemini 2.5 Flash unless the run manifest pins another. Temperature 0. No training.

| ID | Name | Predicts from | Forbidden |
|---|---|---|---|
| A0 | Global marginal | Pooled half-A headline frequencies (all buckets) | Per-bucket counts |
| A1 | `count@k` | Raw frequencies from **k** half-A sessions **in-bucket** | Other buckets; LLM |
| A2 | `count@k + shrinkage` | A1 shrunk toward A0 (§6.1) | LLM; tuning on half-B |
| A3 | LLM zero-shot | Bucket descriptor (`state`, `prev`) + schema of headline classes | Any in-bucket counts |
| A4 | LLM + `k` sessions | A3 + the same k-session histogram given to A1 (as numbers) | Counts beyond those k sessions in-bucket |
| A5 | LLM + disjoint demos | A3 + demos from buckets with **key ≠ eval key** (same `state` *or* same `prev` allowed, never both) | Same-bucket demos |

`k ∈ {0, 2, 3, 5, 8, 12}`. For `k = 0`, skip A1/A2/A4.

### 6.1 Shrinkage (the honest low-k competitor)

A2 is the baseline that matters at low k — **not** raw A1.

Freeze **one** formula in `shrinkage_freeze.json` before the run, e.g.

\[
\hat{p} = (1-\lambda)\,p_{A,k} + \lambda\,p_{\mathrm{global}}
\]

with \(\lambda\) (or Dirichlet strength) chosen so the feasibility reference points are approximately recovered on the same protocol (~23 / 32 / 40 / 46 at k = 2 / 3 / 5 / 8).  
Do **not** retune \(\lambda\) after seeing LLM scores. Do **not** fit on half-B.

**Isotonic / other recalibration:** optional, **LLM arms only** (A3–A5), fit on half-A (nested folds or held-out buckets), never half-B. Report as a sensitivity column — primary story is raw A3/A4 vs A2.

### 6.2 Leakage rules

- Half-B is eval-only: no counts, demos, or calibration.
- A5: `demo.bucket ≠ eval.bucket` under the §5 key.
- A4 may show the k-session histogram for the eval bucket; it may not show the full half-A histogram for that bucket.

---

## 7. Splits and scoring

1. Session-level 50/50 split → half-A / half-B. Prefer stratification by `funnel_state` when cells allow.
2. Repeat **R = 20** random splits for A0–A2 (free).
3. For LLM arms, use the **predeclared** compute cap in §11 (pinned in the manifest before the first API call).
4. Per split × bucket × arm × k: predict \(\hat{p}\), score S on half-B’s **headline** distribution.
5. Skip bucket×split cells with too little half-B mass (freeze a minimum, e.g. ≥ 8 actions); log skip rate.
6. **Primary report:** mean S ± split SE, per arm × k, macro-averaged over the 23 buckets.
7. **Primary figure:** S(k) for A1, A2, A3, A4 (A0 horizontal reference; A5 optional overlay).
8. **Side table:** terminate binary metrics (§4.3) only.
9. Always print mean TVD(half-A, half-B) under the frozen vocab so the ~0.20 ceiling stays visible without becoming the target.

---

## 8. Success / failure (pre-registered)

**Success (claim supported)** — all three:

1. ∃ k ∈ {2, 3} such that A3 or A4 beats A2 with split-bootstrap 95% CI on ΔS excluding 0; **and**
2. At k = 8, A2 ≥ best LLM arm (point estimate); **and**
3. Crossover k\* (where A2 overtakes the best LLM arm on the primary plot) lands in **[3, 5]**.

**Failure (publish as failure — do not retrofit §1):**

| Result | Meaning |
|---|---|
| LLM never beats A2 at k ≤ 3 | No usable cold-start prior on this task |
| LLM wins at k ≥ 8 | Prior stronger than claimed → new spec |
| A5 ≫ A3 only under a broken demo filter | Leakage — fix filter, no claim |
| `vocab` / `bucket` / `shrinkage` hash drifts mid-run | Run invalid |
| Freeze gate yields ≠ 23 buckets | Do not run |

---

## 9. Will not do in this run

- Compete with the full half-A frequency table (~66) as a cold-start baseline  
- Treat global marginal as the primary baseline  
- Feed same-bucket demos  
- Put `terminate` in the headline simplex  
- Treat blank `click_type` as ~25% junk  
- Quote any bucket count other than **23** for `state × prev` at §5 thresholds  
- Change “~3–5 users vs shrinkage” after seeing the plot  

---

## 10. Deliverables

1. `vocab_freeze.json`, `shrinkage_freeze.json`, `bucket_manifest.json` (23 keys + counts)  
2. Predictions + S matrices under `results/opera_coldstart/<run_id>/`  
3. Primary S(k) figure + terminate side table  
4. One-page note: crossover k\*, CI, and one sentence: §1 claim **supported** or **failed**

---

## 11. Cost / scope guardrail

| Block | Scope |
|---|---|
| A0–A2 | All 23 buckets × 20 splits × all k — local, free |
| A3–A5 | Pin **before** API use, one of: (a) 23 buckets × 5 splits × all k, or (b) 8 stratified buckets × 20 splits × all k |

State a USD ceiling in the manifest; stop when hit. Prefer (a) if the budget allows — bucket coverage matters more than split count for the crossover read.

---

## 12. Abstract (one sentence)

We test whether a prompted LLM supplies a cold-start prior for OPeRA funnel action-type distributions over **23 `(state × prev)` buckets**, against **counting-plus-shrinkage** at k ∈ {2,3,5,8,12}, under an **~11% junk** vocabulary that collapses `other`/`page_related` into `other_ui` and reports **`terminate` (3.6%) on a separate truncated-sensitive line** — pre-registering that the prior is worth about **three to five** real sessions of data, not eight.
