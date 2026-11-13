# Retrieval "who it resonates with" as a voter segment mix (orchestrator 02:36Z Nov 13): fails, no recipe

Script: who_mix.py. It uses who_learn's people and segments: 12 site-index segments, with each person's segment taken from upvotes dated before the launch day.

**Test launches.** 212 of the 477 Sep 1 – Nov 10 page-read launches have 30 or more held voters (coverage 44%; median 77 voters).

**What the predicted mix is compared against:**
- **RETR20:** the similarity-weighted mix of the 20 nearest earlier launches' real held voters.
- **GLOBAL:** all earlier held voters. Its top 2 is the best constant list.
- **TOPIC:** earlier launches that share the target's first topic.

**Metrics.**
- Jensen-Shannon divergence vs the real mix, ×100; lower is better.
- Top-2 over-indexed hit, %: overlap of the predicted top 2 with the real top 2, scored as a share of 2.

Each cell is RETR20 minus the control.

| | JSD − GLOBAL | JSD − TOPIC | top-2 hit − GLOBAL | top-2 hit − TOPIC |
|---|---|---|---|---|
| PH, all 212 | −0.32 [−0.63, −0.05] | −0.22 [−0.41, −0.01] | −26.9 [−32.6, −21.0] | −0.2 [−4.3, +4.0] |
| PH, Sep (96) | +0.01 [−0.35, +0.40] | −0.11 [−0.39, +0.16] | −26.0 | +0.5 |
| PH, Oct–Nov (116) | −0.60 [−1.04, −0.17] | −0.30 [−0.62, −0.01] | −27.6 | −0.9 |
| page, all 212 | +0.08 [−0.23, +0.37] | +0.18 [−0.05, +0.41] | −30.7 [−35.6, −25.5] | −4.0 [−8.3, 0.0] |
| page, Sep | +0.35 [−0.01, +0.73] | +0.23 | −30.7 | −4.2 |
| page, Oct–Nov | −0.14 [−0.56, +0.28] | +0.15 | −30.6 | −3.9 |

Top-2 hit levels: GLOBAL 44%, RETR20 14–17%, TOPIC 18%. JSD levels are about 7.5–7.9 for all three.

On the thin third (top-1 cosine in the bottom third), page-path JSD is worse than GLOBAL: +0.44 [+0.02, +0.84].

**Verdict.** Retrieval loses badly to the constant on top-2 segments, on both paths and in both months.

The divergence gain on the PH path is small, about 4% of the level, and does not replicate in September. The page path has no gain. This does not meet the bar of beating both constants with a positive interval in two months, so no recipe is written and the card stays withdrawn.
