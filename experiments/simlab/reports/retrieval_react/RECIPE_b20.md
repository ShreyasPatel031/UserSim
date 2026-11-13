# Recipe: retrieval-condensed concerns / questions ("b20") for the page path. Sent to the orchestrator; not sent to the website agent.
1. Query text: `f"{name}. {tagline}. {page_excerpt[:800]}"`. Embed with gemini-embedding-001, SEMANTIC_SIMILARITY, 256 dimensions, L2-normalised. This is the same call ranked() already makes.
2. Take the 20 nearest rows of reactions_retrieval_v1 by cosine, keeping only rows with `day < today` and `slug_stem != the target's stem`.
3. For each neighbour, keep up to 4 themes:
   - concerns: themes whose prefix is objection / question / feature request;
   - questions: themes whose prefix is question.

   Strip the prefix and list the themes as `[i] point`, capped at 6,000 characters.
4. Call gemini-2.5-flash once per kind, at temperature 0 with 600 max tokens, using the prompt below. `{what}` is "concerns, objections or feature requests" or "questions to the makers".
```
A new product is launching on Product Hunt today.
Product: {name} - {tagline}
{page_excerpt[:1500]}
Real users raised these points in the launch comments of the 20 most similar EARLIER launches (one line per point, launch number first):
{points}
Using these real points as evidence of what this audience asks about, write the 3 {what} most likely to be raised about THIS product,
most likely first, each reworded for this product. Return JSON {"items": ["...", "...", "..."]}
```
5. Show the 3 items in order. The first item is the "first question". If the call fails or returns no items, fall back to the current ranked() output.

Evidence (70 launches, page path, strict pro judge):
- Questions p@3: 27.0 vs 19.1 deployed, +7.8 [+2.0, +14.2].
- Concerns p@3: +5.8 [−0.0, +12.1].
- Top-1 hit is not distinguishable: questions +7.4 [−4.4, +19.1].

Cost is about $0.002 per launch, no more than ranked().
