# Hidden-window early votes from REAL pulls (orchestrator 09:34Z Nov 13): too few people by accident; a targeted re-read is needed

Script: hidden_real.py. It uses the merged store (61,468 complete people). A person counts for a night if their full pull (fetched_at of the upvotes tab = run finish) fell between 00:30 and 04:00 PT on a launch day.

| night | people pulled 00:30 – 04:00 PT | their upvotes on that day's launches | hidden read used |
|---|---|---|---|
| Nov 5 | 798 | – (no clean rows that day) | none held |
| Nov 8 | 14 | – | |
| Nov 9 | 1,569 | **0** | 01:00 |
| Nov 10 | 523 | **0** | none at the median pull time (00:50) |
| Nov 11 | 2,358 | **25** | 02:00 |

- With 0 / 0 / 25 early votes there is no signal to test.
- Nov 11 Spearman of the early count with final rank is 0.09; partial correlation beyond clean is −0.12 and beyond the hidden rank −0.24, both noise.
- Top 3 / 5 / 10 gain over clean or the hidden rank: 0.0 (leave-day-out, 2–3 days).

**Why it is so small.** People we hold complete cast about 2,250 held votes a day (Nov 2 – 8), about 37 per 1,000 people per day. Correction (09:40Z, from vote_snapshots Nov 8 – 12): 57–66% of a day's final votes are already cast by the 04:00 PT reveal, not a third. A random 2,358 people therefore yields about 50 early votes by 04:00, or fewer for pulls finishing around 02:30. Nov 11 shows 25, about half that, which is consistent with the erratic pull timing.

Same-day vote rates by pull time are also erratic, from 0 to 205 per 1,000 people. Run-finish time is probably not when the upvote list was read for long or resumed pulls, so even the accidental sample is noisy.

**What a deliberate nightly re-read needs.** Voting is concentrated. Ranking people by the previous week's votes (Oct 25 – Nov 1), the share of the next week's held votes they cast is:

| re-read set | share of held votes | votes per day |
|---|---|---|
| top 1,000 most active | 68% | about 1,540 |
| top 2,000 most active | 80% | about 1,810 |

Panel written (bucket only): raw/_cursor/hidden_window/panel_20261113.txt. It holds the 2,000 most active complete people by votes on Oct 30 – Nov 12 launches, 1,000 of them tier 1. Expected early votes by 04:00 PT (62% of the day's votes):

| week | tier 1 | tier 1 + 2 |
|---|---|---|
| unseeded Oct 1 – 24 | 49% of held votes, about 530 per night | 61%, about 650 per night |
| seeded Oct 29 – Nov 4 | 59%, about 850 per night | 75%, about 1,080 per night |

A re-read finishing around 03:00 PT sees somewhat less. That is the real-data test of the hidden window; the accidental sample (about 25 a night) cannot answer it.

Caveat: Nov 2 – 8 overlaps the week the pool was seeded from, so the concentration figures are optimistic.
