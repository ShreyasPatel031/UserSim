# CONTENT-LABELS-1 (Nov 25 2026): a "same point" content measure for Task C

**Result:** the judge agrees with blind hand labels (kappa 0.93 [0.74, 1.00] on 60 pairs), so `same_point` is the Task C
content metric (`TaskC.score(..., content_judge=ContentJudge(project))`, `simharness/content_judge.py`). It ranks the
arms differently from the embedding match: a different person's real comment on the same launch makes the same
point as the person's real comment more often than any simulated arm does.

## Setup
- **Rows:** 150 Task C rows from the 1,450 test + forward rows with a second commenter (PERSON-VOICE-1 set; rows
  with all four candidates), each scored in 4 arms = 600 (real comment, candidate) pairs:
  - Gemini Flash with history;
  - tuned Qwen 2.5 7B;
  - the person's own last comment;
  - a different person's real comment on the same launch (the negative).
- **Judge:** Claude Opus 5.5 on Vertex AI (reachable from this project; adaptive thinking at low effort), frozen prompt
  `same-point-v1`. It sees the launch name and tagline plus both comments, @handles removed. 12 pairs per call; 3 runs,
  each with its own batch composition and order; label = majority of the 3. Runs were unanimous on 95% of pairs.
- **Hand check:** 60 pairs (15 per arm), labelled blind to the arm and the judge. Agreement 98.3% (59 of 60), kappa
  0.93. The one disagreement: the judge counted "patterns come only from my own data" as the same point as "rating mood
  myself instead of guessing from step counts"; I did not.

## Results (150 rows per arm, same rows; [row-bootstrap 95%], day-bootstrap in results.json)

| Arm | same point | embedding match (cosine >= 0.7497) | mean cosine |
|---|---|---|---|
| different person, same launch (negative) | **20.0 [14.0, 26.7]** | 28.7 [22.0, 36.0] | 0.676 |
| Gemini Flash + history | 12.0 [7.3, 17.3] | **38.0 [30.0, 45.3]** | 0.708 |
| tuned Qwen | 8.0 [4.0, 12.7] | 22.0 [15.3, 29.3] | 0.677 |
| own last comment | 3.3 [0.7, 6.7] | 15.3 [10.0, 21.3] | 0.654 |

Paired, same point:
- Flash − tuned: +4.0 [−1.3, +10.0], not clear.
- Flash − own last comment: +8.7 [+4.0, +14.0].
- Flash − other person on the same launch: −8.0 [−16.0, −0.7].
- tuned − other person: −12.0 [−19.3, −4.7].

**The two measures rank the arms differently.**
- **Same point:** other person > Flash > tuned > own last.
- **Embedding:** Flash > other person > tuned > own last. The embedding gives Flash +9.3 over a real second commenter,
  where same point gives it −8.0: it rewards restating the product.
- **Generic "congrats" matches:** a large share of the matches for own last comment (80%) and tuned Qwen (53%) are
  generic congratulations matched to a generic real comment. For Flash (11%) and the other person (10%) the matches are
  specific points.

**Reading.** Person-built comments say the person's kind of thing (person match), but they rarely say what the person
actually said about this launch. A random real commenter on the same launch does that more often. The content gap to
close is about 8 points to a second real commenter.

## Cost
$2.20 of the $4: judging $2.18 (Opus 5.5 at $4 / $20 per 1M tokens, measured usage); smoke test of the flag $0.02.

Private files (pairs, judge runs, labels, hand labels): `gs://.../simharness/bench_v0/content_labels1/wip/`.
