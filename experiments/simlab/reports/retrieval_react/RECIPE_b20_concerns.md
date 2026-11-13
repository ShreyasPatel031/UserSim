# Final recipe: retrieval-condensed concerns ("b20") for /try. Sent to the orchestrator only; not sent to the website agent.
Evidence: retrieval_rep.json. 170 launches (first 70 plus a fresh 100), strict gemini-2.5-pro same-point judge, paired 95% intervals.

## Scope (only what replicated)
| path | concerns | questions |
|---|---|---|
| pasted PH description | **b20** | **b20** |
| page read (URL) | **b20** | stays on deployed ranked() |

## Steps
1. **Query.** `f"{name}. {tagline}. {text[:800]}"`. `text` is the pasted description, or the raw page excerpt on the page path. Embed with gemini-embedding-001, SEMANTIC_SIMILARITY, 256 dimensions, L2-normalised.
2. **Neighbours.** Rank the reactions_retrieval_v1 rows by cosine. Keep a row only if all of these hold:
   - `day < today`;
   - its stem, with any trailing `-N` removed, differs from the target's stem with `-N` removed (this drops the same product's earlier launches);
   - it shares no named maker with the target, when the user gave makers. The bundle holds no makers today; add a hashed maker list per row if you want this check. Results were unchanged without it: excluding all flagged targets gave concerns page +7.4 [+2.8, +12.0].

   Take the first 20 rows that pass.
3. **Thin-neighbour rule.** Let s1 be the cosine of the nearest kept neighbour.
   - PH path: if s1 < **0.898**, use the current method (deployed ranked()).
   - Page path: if s1 < **0.886**, show the generic constant list. In that third, both b20 and deployed fall below the constant: concerns p@3 9.4 / 6.3 vs 16.4; questions 6.7 / 7.3 vs 12.1.

   The thresholds are the bottom-third cut of the 170 eval launches for each path.
4. **Points.** For each neighbour, keep up to 4 themes whose prefix is:
   - concerns: objection / question / feature request;
   - questions: question.

   Strip the prefix and list them as `[i] point`, capped at 6,000 characters.
5. **Condense.** One gemini-2.5-flash call per kind, at temperature 0 with 600 max tokens. `{what}` is "concerns, objections or feature requests" or "questions to the makers"; `{text}` is the text from step 1, cut to 1,500 characters.
```
A new product is launching on Product Hunt today.
Product: {name} - {tagline}
{text}
Real users raised these points in the launch comments of the 20 most similar EARLIER launches (one line per point, launch number first):
{points}
Using these real points as evidence of what this audience asks about, write the 3 {what} most likely to be raised about THIS product,
most likely first, each reworded for this product. Return JSON {"items": ["...", "...", "..."]}
```
6. **Show** the 3 items in order. If the call fails or returns no items, fall back to the current method.
7. **Cost:** about $0.001 per kind per launch.

## Numbers to display (pooled 170, % [95% CI], b20 vs deployed)
| | top-3 precision | recall of real top-3 points | top-1 hit |
|---|---|---|---|
| concerns, pasted description | 37.2 vs 24.8: +12.4 [+7.9, +17.1] | 37.2 vs 23.7: +13.5 [+8.1, +18.9] | 41.5 vs 26.8: +14.6 [+6.1, +23.8] |
| concerns, page read | 24.6 vs 17.1: +7.5 [+3.0, +12.0] | 24.0 vs 17.5: +6.5 [+0.9, +12.1] | 27.4 vs 20.7: +6.7 [−1.8, +14.6] |
| questions, pasted description | 29.9 vs 25.0: +4.9 [+0.6, +9.3] | 32.3 vs 24.4: +7.9 [+2.6, +13.1] | 35.4 vs 29.9: +5.5 [−3.1, +13.4] |

For context, the generic constant list scores concerns p@3 16.5 and questions 10.6.

## Wording limits
- Allowed: "About 1 in 3 of these concerns (about 1 in 4 from a page read) matched a point real commenters raised on comparable launches."
- Allowed: "based on what real users raised on similar earlier launches".
- Not allowed: "predicts what users will say", or any accuracy figure for page-path questions.
- Not allowed: a top-1 claim on the page path, because its interval includes 0.
- Thin-neighbour launches get no retrieval claim. Show "few similar past launches; showing common concerns" with the constant list on the page path.
- The judge is strict: same specific point, gemini-2.5-pro at temperature 0. Item labels agree 92–94% across two item orders.
- The eval launches are Jan–Nov 2026 Product Hunt launches. The fresh 100 used late page reads, fetched 1–4 weeks after launch.
