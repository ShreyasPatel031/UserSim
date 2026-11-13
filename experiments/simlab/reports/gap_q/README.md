# Gap-based page questions (orchestrator 04:02Z Nov 13): null, no recipe

Script: gap_q.py.

**Data.** The pooled 170 launches, page path only (163 judged). The dev / confirmation split was fixed before the run (sha1 of the key), and nothing was tuned.

**Question types.**
- 14 types.
- Base rates come from the v1 bank's 5,801 real questions on 2,820 launches dated ≤ Aug 31.
- Each question was classified by flash-lite. Embedding cosine could not separate the types (every question scored 0.81–0.88), so a first, embedding-based attempt was discarded before any judging.
- Only 24% of the bank's questions fit a type. The rest are product-specific.
- Base rates (share of launches): accuracy 10.2%, privacy 7.1%, limits 4.3%, pricing 4.0%, integrations 3.2%, platforms 3.2%, competitor 2.6%, models 2.3%, self-host 2.1%, language 1.8%, roadmap 1.5%, API 1.1%, onboarding 1.1%, team 0.7%.

**Method.** A flash call marks each type as ANSWERED / PARTLY / ABSENT on the page and writes one product-specific question per type.
- Score = base rate × (1 if absent / 0.4 if partly / 0.05 if answered).
- GAP = the top 3 types by score.
- GAPDEP = the top 2 of GAP plus deployed's first question.

**Results.** Strict pro judge, % [95% CI], paired.

| confirmation half (93) | p@3 | recall | top-1 |
|---|---|---|---|
| GAP / GAPDEP / deployed / constant / b20 | 9.3 / 13.6 / 15.8 / 9.3 / 18.6 | 12.7 / 17.2 / 18.5 / 9.1 / 21.9 | 14.0 / 14.0 / 19.4 / 8.6 / 24.7 |
| GAP − deployed | −6.5 [−10.8, −2.2] | −5.7 [−12.5, +0.9] | −5.4 [−14.0, +4.3] |
| GAPDEP − deployed | −2.2 [−5.0, +0.7] | −1.3 [−6.1, +3.6] | −5.4 [−15.1, +4.3] |
| GAP − constant | 0.0 [−5.0, +5.0] | +3.6 [−2.3, +9.5] | +5.4 [−4.3, +15.1] |

All 163 launches give the same picture: GAP − deployed p@3 = −6.7 [−10.2, −3.3]; GAPDEP − deployed = −2.2 [−4.7, +0.4]. The dev half agrees.

**Verdict.** Generic question types, even when gated by what the page leaves out, are no better than the constant list. They lose to deployed. The real questions are mostly product-specific (76% fit no type).

Pages leave most types ABSENT (54–95% of pages, except pricing at 24% and onboarding at 15%), so the gap mark barely discriminates.

For reference, b20 minus deployed on page questions in this pool: +2.7 [−1.0, +6.5] over all 163 (it again does not reach a positive interval).

Cost: about $0.7 for the judge, with small flash and flash-lite costs on top.
