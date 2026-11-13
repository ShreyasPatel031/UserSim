# Retrieval (kNN-20) rank band for /try (orchestrator 02:32Z Nov 13): null, no recipe

Script: band_knn.py.

**Prediction:** the similarity-weighted mean of the 20 nearest earlier launches' final within-day rank percentile.
- Embedding: gemini-embedding-001, 256 dimensions.
- Neighbours are dated strictly before the target day. Excluded: the same stem (after dropping a trailing "-N"), the same name, and any shared named maker or poster.

**Test set:** band_v2's 856 launches (726 held Sep–Oct page reads and 130 fresh).
- Page path: deployed = B0.
- PH path: deployed = the product-only ridge, month-forward. The live launch_band.json is partly in-sample on these months, which is where the 0.59 comes from.

Pooled Spearman with true rank [95% CI]; Δ is paired launch bootstrap vs deployed.

| | deployed | kNN-20 | blend | kNN − dep | blend − dep |
|---|---|---|---|---|---|
| page, all 856 | 0.278 | 0.200 | 0.273 | −0.079 [−0.145, −0.011] | −0.005 [−0.039, +0.026] |
| page, fresh 130 | 0.403 | 0.251 | 0.372 | −0.152 [−0.311, +0.006] | −0.031 [−0.110, +0.049] |
| page, thin (cos < 0.884) | 0.206 | 0.130 | 0.203 | −0.075 | −0.002 [−0.068, +0.064] |
| PH, all 856 | 0.353 | 0.284 | 0.370 | −0.069 [−0.131, −0.008] | +0.017 [−0.017, +0.050] |
| PH, fresh 130 | 0.417 | 0.251 | 0.388 | −0.166 [−0.332, −0.009] | −0.029 [−0.113, +0.058] |
| PH, not thin | 0.323 | 0.298 | 0.363 | −0.025 | +0.039 [−0.002, +0.076] |
| PH, thin (cos < 0.899) | 0.406 | 0.255 | 0.387 | −0.151 [−0.259, −0.041] | −0.019 |

The blend is the mean of within-set ranks.

**Calibration** (80% band, cross-fit Sep ↔ Oct + fresh): coverage is 75–77% for all three, and widths are 72–75% of the day. No difference.

**Verdict:**
- kNN alone is worse than deployed.
- The blend is indistinguishable from deployed. Its PH-path gain on non-thin launches, +0.039 [−0.002, +0.076], is borderline and does not hold on the fresh set.
- This repeats band_v2's retr30 finding (+0.002 to +0.012). No recipe is written.
