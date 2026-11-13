# Page-read path under the same-point standard (orchestrator 12:44Z Nov 12)

Script: page_path.py.
- Launches: 70 = 44 fresh page reads (Oct 27 – Nov 10) + 26 held Sep–Oct page reads (fetched Oct 25, flagged late), each with ≥ 5 real comments.
- Ranked concerns / questions (try_fixes.ranked, retrieval strictly earlier) from three inputs on the same launches.
- Adjudicator: gemini-2.5-pro at temperature 0, seeing the real comments, top-3 items pooled per launch.
- About $0.5 for the adjudicator plus flash generation.

| top-3 same-point precision (p@3) [95%] | concerns | questions |
|---|---|---|
| (a) page read summary (current site) | 25.2 [19.5, 31.4] | 29.5 [22.9, 36.2] |
| (b) raw page excerpt | 29.5 [23.8, 35.2] | 31.4 [24.3, 38.6] |
| (c) pasted PH description (reference) | **37.1 [31.0, 44.3]** | **37.1 [30.5, 43.8]** |
| constant list | 24.3 [17.1, 31.4] | 22.4 [15.7, 29.5] |
| category points | 5.8 | 5.8 |
| **ceiling: real vs real split-half** (35 launches with ≥ 10 comments) | 32.4 [21.0, 44.3] | 34.8 [23.5, 45.6] |

| paired difference vs the constant list (p@3) | concerns | questions |
|---|---|---|
| (a) page read summary | +1.0 [−6.7, +8.1] | +7.1 [−1.4, +15.7] |
| (b) raw excerpt | +5.2 [−3.3, +13.3] | +9.0 [−1.0, +19.0] |
| (c) PH description | **+12.9 [+4.3, +21.0]** | **+14.8 [+8.1, +21.0]** |
| raw minus read summary | +4.3 [−1.9, +10.0] | +1.9 [−5.2, +9.5] |

hit@3 (at least one of three matches): read 59 / 59; raw 66 / 60; PH 76 / 71; constant 46 / 44.

Fresh-only (44) p@3, a / b / c / constant:
- concerns 31.1 / 31.1 / 36.4 / 24.2;
- questions 32.6 / 34.8 / 37.1 / 23.5.

**Verdict:**
- No page-read input beats the constant list with the interval above zero.
- The pasted launch description does, for both lists, and reaches the real-vs-real ceiling. That ceiling is set with half of the comments, so it is a floor for the true ceiling.
- Product statement: "Paste your launch description for concerns and questions; a URL alone gives the rank band and topic-level reactions only."

**Note on levels:** p@3 here is higher than in same_point.py (PH concerns 37 vs 13). That run pooled 30–60 items per adjudicator call; this one pools about 20 top-3 items. The adjudicator's strictness depends on pool size, so compare within a run, not across runs.

## (e) Drafted launch post (page_path_draft.py; about $0.45 adjudicator + flash)

Setup: one flash call writes the maker's launch post from the raw page excerpt, with no invented facts. All arms are re-adjudicated together in a new run on the same 70 launches.

| p@3 [95%] | concerns | questions |
|---|---|---|
| (a) read summary | 21.9 | 26.7 |
| (b) raw excerpt | 30.5 | 28.6 |
| (c) real PH description | 32.9 | 37.1 |
| **(e) drafted launch post** | **25.2** | **23.8** |
| constant | 22.9 | 21.9 |

| paired difference | concerns | questions |
|---|---|---|
| (e) − constant | +2.4 [−5.2, +10.0] | +1.9 [−7.1, +11.4] |
| (e) − raw | −5.2 [−11.9, +1.0] | −4.8 [−11.4, +1.9] |
| (e) − real description | −7.6 [−15.7, −0.0] | −13.3 [−22.4, −5.2] |
| (c) − constant | +10.0 [+1.4, +18.1] | +15.2 [+8.6, +21.9] |

**Verdict:**
- A drafted post does not close the gap. It is no better than the constant list and slightly worse than the raw page text.
- What helps is information the maker writes and the page lacks, not framing.
- The paste path (the real launch description) stays the only validated route for concerns and questions.

## Top-1 vs list; by comment volume (page_path_positions.py; no new calls; two adjudicated runs, 70 launches)

Only the top 3 were adjudicated, so there is no p@5. Run 1 / run 2 are the two independent adjudications of the same lists.

**Top item (p@1 = hit@1)**, paired vs the constant list's first item:

| input | concern p@1 | Δ vs constant | question p@1 | Δ vs constant |
|---|---|---|---|---|
| PH description | 41.4 / 34.3 | **+21.4 [7.1, 35.7] / +18.6 [4.3, 32.9]** | 48.6 / 50.0 | **+25.7 [12.9, 40.0] / +28.6 [14.3, 41.5]** |
| raw page excerpt | 32.9 / 40.0 | +12.9 [−2.9, 28.6] / **+24.3 [10.0, 38.6]** | 41.4 / 41.4 | **+18.6 [2.9, 34.3] / +20.0 [5.7, 34.3]** |
| page read summary | 32.9 / 25.7 | +12.9 [1.4, 24.3] / +10.0 [−2.9, 22.9] | 38.6 / 34.3 | +15.7 [1.4, 30.0] / +12.9 [−2.9, 28.6] |
| constant list (first item) | 20.0 / 15.7 | | 22.9 / 21.4 | |

**Precision by position** (1 / 2 / 3, run 1):
- PH concerns 41 / 34 / 36; PH questions 49 / 33 / 30.
- Raw-page questions 41 / 27 / 26.
- Position 1 minus positions 2–3, paired:
  - Questions: +17.1 [3.6, 31.4] (PH), +15.0 [4.3, 25.7] (raw), replicated in run 2 (+19.3 / +19.3).
  - Concerns: +6.4 [−6.4, 19.3] (PH), not significant.

**p@3 by number of real comments** (run 1: PH / raw / constant):

| comments | concerns | questions |
|---|---|---|
| 5–9 (35) | 31.4 / 22.9 / **9.5** | 25.7 / 23.8 / **12.4** |
| 10–19 (23) | 40.6 / 34.8 / 40.6 | 40.6 / 40.6 / 24.6 |
| 20+ (12) | 47.2 / 38.9 / 36.1 | 63.9 / 36.1 / 47.2 |

**Reading:**
- The single top item is the strongest claim. From a pasted description, the top question matches a real comment about 1 time in 2 and the top concern about 1 in 3 to 2 in 5, vs about 1 in 5 for a generic item.
- Even from the raw page text, the top question beats the constant in both runs (41% vs 21–23%).
- Questions are well ordered (item 1 clearly best); concerns are not.
- The lists' advantage over the constant is clearest on quieter launches (5–9 comments), where generic items rarely match. On busier launches, generic concerns hit about as often.

## Raising the page path's top-1 (page_top1.py; one new adjudicated run, 70 launches, about $0.6)

Setup:
- 68 of 70 launches had pricing / FAQ / docs text in the stored HTML.
- Self-consistency used 5 flash-lite samples at temperature 0.7, then a flash pick.

| p@1 [95%] | question | concern |
|---|---|---|
| (a) current raw-excerpt recipe | **42.9 [31.4, 54.3]** | **44.3 [32.9, 55.7]** |
| (b) + page answers (pricing / FAQ / docs) | 44.3 (vs a +1.4 [−11.4, +12.9]) | 37.1 (−7.1 [−21.4, +7.1]) |
| (c) self-consistency | 31.4 (−11.4 [−25.7, +2.9]) | 30.0 (−14.3 [−30.0, 0.0]) |
| (d) b + c | 25.7 (−17.1 [−31.4, −2.9]) | 37.1 (−7.1) |
| constant first item | 20.0 | 17.1 |
| (a) − constant | +22.9 [+7.1, +38.6] | +27.1 [+12.9, +41.4] |

**Verdict:**
- Nothing beats (a). The current recipe stays.
- In this run the top concern from the raw page also clears the constant (+27.1), and so does the top question (+22.9).

## Where the URL's "most likely question" works (page_top1_cells.py; no new calls)

Setup: raw-page top-1 question, the mean of 3 adjudications per launch; generic = the constant first question, same runs.

Overall: hit 41.9 [32.4, 52.4], generic 21.4, difference +20.5 [7.1, 34.3] (70 launches).

| cell | n | hit | generic | hit − generic |
|---|---|---|---|---|
| productivity | 24 | 48.6 | 16.7 | **+31.9 [9.7, 54.2]** |
| consumer / other | 27 | 39.5 | 28.4 | +11.1 [−11.1, 33.3] |
| dev tools | 15 | 28.9 | 17.8 | +11.1 [−15.6, 35.6] |
| AI / agents (first PH topic) | 4 | 66.7 | 16.7 | +50.0 [−25, 100] |
| comments 5–9 | 35 | 35.2 | 16.2 | **+19.0 [1.0, 35.3]** |
| comments 10–19 | 23 | 55.1 | 21.7 | **+33.3 [8.7, 56.5]** |
| comments 20+ | 12 | 36.1 | 36.1 | 0.0 [−36.1, 36.1] |
| final rank #1–5 | 35 | 54.3 | 23.8 | **+30.5 [9.5, 51.4]** |
| rank 6–15 | 29 | 31.0 | 16.1 | +14.9 [−3.4, 33.4] |
| rank 16+ | 6 | 22.2 | 33.3 | −11.1 |
| price: freemium | 10 | 60.0 | 10.0 | **+50.0 [13.3, 80.1]** |
| price: unknown (fresh reads did not record it) | 55 | 37.0 | 20.6 | +16.4 [1.2, 30.9] |
| price: free / paid | 2 / 3 | | | too few |

**Reading:**
- The cells are small, and the differences between groups overlap (e.g. productivity +32 vs consumer +11).
- No split is clearly supported. Rank is not known before launch in any case.
- The busiest launches (20+ comments) show no edge over a generic question.
- No "works best for" note was sent.

## Pasted description: length and content (paste_length.py; no new calls)

Setup:
- Top-1 from the real PH description, mean of 2 adjudications; generic = the constant first item.
- PH descriptions are short: median 66 words, none above 100. The 100–200 and 200+ bins are empty.

| bin | n | question hit / generic / diff | concern hit / generic / diff |
|---|---|---|---|
| all | 70 | 49.3 / 22.1 / **+27.1 [15.0, 40.0]** | 37.9 / 17.9 / **+20.0 [6.4, 34.3]** |
| < 40 words | 16 | 46.9 / 37.5 / +9.4 [−12.5, 34.4] | 34.4 / 34.4 / 0.0 [−34.5, 31.2] |
| 40–100 words | 54 | 50.0 / 17.6 / **+32.4 [18.5, 47.2]** | 38.9 / 13.0 / **+25.9 [13.0, 39.8]** |
| names pricing (yes / no) | 27 / 43 | +27.8 / +26.7 | +24.1 / +17.4 |
| names integrations (yes / no) | 21 / 49 | +9.5 [−14, 33] / +34.7 [21, 48] | +7.1 / +25.5 |
| names a target user (yes / no) | 9 / 61 | +33.3 / +26.2 | +5.6 / +22.1 |

**Reading:**
- Below about 40 words, the top question / concern is no better than a generic one; at 40–100 words it clearly is.
- The model's own hit rate is similar in both bins (47 vs 50). The difference is that generic items also hit on short-description launches (37.5% vs 17.6%), so this is a property of those launches, not proof that more words cause hits.
- Naming pricing, integrations or a target user does not help. Integrations, if anything, comes with a lower edge.

## Two-step page path for REACTIONS (page_react2.py; 70 launches; about $0.44 adjudicator + flash)

Setup: every list comes from the deployed step_reactions; scored as same-point precision (gemini-2.5-pro reading the real comments, pooled).

| list | precision [95%] |
|---|---|
| page read (current URL path) | 23.1 [18.1, 28.6] |
| two-step: flash 120–200-word description from the page, then the description path | 25.5 [20.0, 31.2] |
| real PH description (pasted path) | **37.4 [32.1, 42.9]** |
| generic 6 comments | 27.9 [22.1, 33.3] |

| paired | Δ precision |
|---|---|
| two-step − page | +2.4 [−1.9, +6.7] |
| two-step − generic | −2.4 [−9.5, +5.2] |
| page − generic | −4.8 [−11.7, +1.9] |
| real description − generic | **+9.5 [+3.6, +15.5]** |
| two-step − real description | −11.9 [−18.1, −6.0] |

**Verdict:**
- The two-step does not raise page-based reactions above the generic list.
- Only the maker's real description does, for reactions as for concerns and questions.
