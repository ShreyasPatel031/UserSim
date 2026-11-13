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

**Why it is so small.** People we hold complete cast about 2,250 held votes a day (Nov 2 – 8), about 37 per 1,000 people per day, and roughly a third of a day's votes fall before 04:00 PT. A random 2,358 people therefore yields about 20–30 early votes, which is what Nov 11 shows.

Same-day vote rates by pull time are also erratic, from 0 to 205 per 1,000 people. Run-finish time is probably not when the upvote list was read for long or resumed pulls, so even the accidental sample is noisy.

**What a deliberate nightly re-read needs.** Voting is concentrated. Ranking people by the previous week's votes (Oct 25 – Nov 1), the share of the next week's held votes they cast is:

| re-read set | share of held votes | votes per day |
|---|---|---|
| top 1,000 most active | 68% | about 1,540 |
| top 2,000 most active | 80% | about 1,810 |

A re-read of the 1,000–2,000 most active complete people between about 02:30 and 03:30 PT would see roughly a third of those votes. That is about 500–600 early votes a night, about 15 per launch, against about 25 a night from the accidental pulls. That is the real-data test of the hidden window; the accidental sample cannot answer it.

Caveat: Nov 2 – 8 overlaps the week the pool was seeded from, so the concentration figures are optimistic.
