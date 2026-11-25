# POINT-1 (Nov 25 2026): can a person-built comment make the person's actual point?

**Result: yes, and the main lever is what the model sees about the launch, not the prompt.** Every arm saw the same
launch page block: name, tagline and description from the 00:05 line-up, topics, and the maker's first comment when it
was posted in the day's first hour. With it, the current prompt (A0) makes the person's point on 25.3% of rows. That
is above the other-commenter bar (15.9 on these rows; +9.5 [+4.5, +14.4]). In CONTENT-LABELS-1, Flash on the same
kind of rows was at 12.0, when the prompt had no maker comment and test-day items had no description.

The new prompts do not help: A1 (react to one specific thing) is -3.4 [-8.6, +1.9] and A2 (point-kind profile, then
write) is -3.7 [-7.7, +0.6] against A0. Claude Opus 5.5 on the A2 prompt (A3) is best: +7.1 [+1.3, +13.3] over A0 on
141 paired rows, with person match unchanged (+0.7 [-7.1, +9.7]).

## Arms (296 rows: 147 from CONTENT-LABELS-1 + 149 new, test + forward days, paired; day-bootstrap 95%)

| Arm | n | same point | generic share of hits | person match (own_vs_other) | length / real |
|---|---|---|---|---|---|
| A0 current prompt, Flash | 296 | 25.3 [19.8, 30.2] | 12% | 60.8 [55.2, 65.9] | 1.34 |
| A1 "one specific thing", Flash | 296 | 22.0 [18.4, 26.3] | 8% | 60.8 [57.0, 64.9] | 1.26 |
| A2 point-kind profile, Flash | 295 | 21.7 [17.5, 26.0] | 11% | 61.4 [56.0, 66.7] | 1.19 |
| A3 A2 prompt, Claude Opus 5.5 | 141 | **31.9 [25.9, 38.0]** | 2% | 60.3 [52.9, 67.4] | 1.51 |
| another real commenter (reference) | 296 | 15.9 [10.6, 21.0] | 13% | n/a | 1.01 |

Paired (same point):
- A1 - A0: -3.4 [-8.6, +1.9]
- A2 - A0: -3.7 [-7.7, +0.6]
- A3 - A0: **+7.1 [+1.3, +13.3]** (141 rows)
- A3 - A2: +11.4 [+4.8, +20.3]
- Against the reference: A0 +9.5 [+4.5, +14.4], A1 +6.1, A2 +5.8, A3 +14.9 [+7.6, +23.7]

Person match does not move between arms (all within about 1 point).

**Why the launch page matters.** Rows whose launch had a maker comment (202 of 296): A0 30.7%, A3 41.6%, reference
19.3%. Without one: A0 13.8%, reference 8.5%. Real commenters often answer the maker's question or react to a detail
in the maker's post, so a model that sees the post can make the same point. The comparison with CONTENT-LABELS-1's
12.0 is indicative only: different rows, input and judge run count. A paired A0-without-maker-comment arm was not run
for budget.

## Judge
The content_judge (same-point-v1, Claude Opus 5.5, majority) ran 2 runs, not 3: the third run would have pushed
spend past the $6 cap. Pairs split 1-1 are counted as "not the same point": 20 for A0, 9 for A1, 12 for A2, 8 for A3,
8 for the reference. Counting them as "same point" instead gives A0 32.1, A1 25.0, A2 25.8, A3 37.6, reference 18.6.
The ordering and the conclusions are unchanged.

## Leak checks
- 0 history lines dated on or after the row's day.
- The launch block holds no other person's comment: the real comment and the reference comment appear in 0 blocks.
- The maker's comment is a top-level comment by a maker or the hunter (ids from the 00:05 line-up), posted within the
  day's first hour.
- Note for deployment: at 00:05 some maker comments are not posted yet. The nightly panel should read the line-up's
  description and the maker's first comment when it runs, and record whether the comment was there.

## Decision input (rule: beats A0 with the interval clear and does not lose person match)
- **A3 (Opus 5.5) qualifies:** +7.1 [+1.3, +13.3] over A0, person match +0.7 [-7.1, +9.7].
- **A1 and A2 (Flash) do not.**
- **Cost:** Opus 5.5 is $0.012 per comment (measured) against about $0.0004 for Flash. The deployed panel of 15
  comments x ~40 launches would cost about $7 a day instead of $0.25.
- **The cheaper, larger change:** give the deployed Flash prompt (A0) the launch page with the maker's first comment.
  That is input, not prompt, and on these rows it takes Flash from below to above the other-commenter bar.

## Spend
$5.93 of $6: Flash generation $0.80, Opus generation $1.67 (141 rows), judging $3.46 (2 runs x 1,324 pairs).

Code: `simharness/run_point1.py`. Private (rows, generations, labels): `gs://.../simharness/bench_v0/point1/wip/`.
