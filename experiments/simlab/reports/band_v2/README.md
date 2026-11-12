# Page band v2: page facts + retrieval + topic prior stacked on the d_both band WITH the LLM read (orchestrator 08:47Z Nov 12)

Script: experiments/simlab/band_facts.py.
- Train: 2,248 page reads of launches up to Aug 31.
- Test: the band_settle 856 = 726 held Sep–Oct reads + 130 fresh Oct 27 – Nov 10 reads.
- Raw HTML: held pages from the Oct 25 live fetch; fresh pages re-fetched Nov 12 from the same URLs (130/130).
- Metric: Spearman of the score with −rank. The gain is a paired launch bootstrap vs B0 (the d_both band, i.e. the v1 recipe).
- Export rule: the gain must clear 0 on the 856 and keep its sign on the fresh 130.

| variant | 856 Spearman | 856 gain vs B0 | held 726 gain | fresh 130 gain | no-PH-mention 647 gain |
|---|---|---|---|---|---|
| B0 (d_both, LLM read) | 0.278 | – | (0.257) | (0.403) | (0.204) |
| **run 1, primary** (sklearn retrieval, the orchestrator's exact recipe) | 0.328 | **+0.048 [+0.003, +0.095]** | +0.056 [+0.004, +0.107] | +0.015 [−0.098, +0.126] | +0.045 [−0.013, +0.106] |
| run 1, without testimonial / logo words | 0.327 | +0.047 [+0.002, +0.093] | +0.054 | +0.014 | +0.043 |
| **run 2, primary** (retrieval in the band's own pure-python TF-IDF, servable on the site) | 0.324 | **+0.045 [−0.000, +0.090]** | +0.048 [−0.003, +0.099] | +0.028 [−0.081, +0.138] | +0.041 [−0.017, +0.101] |
| run 2, without testimonial / logo words | 0.322 | +0.043 [−0.002, +0.088] | +0.045 | +0.030 | +0.039 |
| B0 + facts (no testimonial) | 0.318 | +0.040 [−0.009, +0.085] | +0.042 | +0.018 | +0.035 |
| B0 + retrieval (run 1 / run 2) | 0.290 / 0.281 | +0.012 / +0.002 | | | |
| B0 + topic prior | 0.279 | +0.000 | | | |

- Facts carry the gain, about +0.04. Retrieval adds +0.00 to +0.01 and the topic prior adds 0: the read's topics are already inside B0.
- With the LLM read inside B0, the gain is smaller than on the orchestrator's LLM-free rebuild (+0.061).
- Testimonial / logo words change nothing: the gain is the same without them. Their rate falls with time since launch rather than rising: 19% train, 14% Sep, 10% Oct, 7% fresh.

**Verdict: not exported.**
- The pre-registered primary passes by 0.003 with the orchestrator's sklearn retrieval.
- The servable version sits at −0.000.
- Retrieval itself is worth about zero, so pass vs fail is decided by an implementation detail of a near-null block. That is not a robust gain.
- The facts-only stack (+0.040 [−0.009, +0.085]) does not clear zero either.
- More fresh pages would settle it.
- band_facts_export.py and band_v2_score.py (a pure-python reference scorer for the bundle) are ready and committed but not run.

## Controls (standing rule): best constant and category mean, same sets

| set | constant band (training p10–p90) | category mean (topic prior) | B0 (live v1 recipe) | B0 − category | stack S (run 2) |
|---|---|---|---|---|---|
| 856 | ρ 0 · coverage 79.0% · width 30 | ρ 0.152 · 78.3% · 32.0 | ρ 0.278 · 83.3% · 31.6 | +0.127 [+0.060, +0.195] | 0.324 |
| held 726 | 0 · 78.8% · 30 | 0.138 · 78.0% · 32.1 | 0.257 · 83.1% · 31.6 | +0.119 [+0.045, +0.195] | 0.305 |
| fresh 130 | 0 · 80.0% · 30 | 0.253 · 80.0% · 31.5 | 0.403 · 84.6% · 31.4 | +0.151 [+0.004, +0.297] | 0.432 |
| no PH mention 647 | – | 0.119 | 0.204 | +0.085 [+0.003, +0.165] | 0.246 |

- The live band beats the category mean on every set, with the interval above 0.
- It has 4–5 points more coverage than the constant band at about the same width (31.6 vs 30 ranks).
- The constant's coverage is close (79% vs 83%), because a p10–p90 band over all ranks covers about 80% by construction. Ranking (ρ) is the claim the constant cannot make.
