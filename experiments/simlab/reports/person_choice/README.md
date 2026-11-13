# Person-day choice test on the grown store (orchestrator 01:56Z Nov 13)

Script: person_choice.py.
- People: 3,329 complete people with ≥ 20 dated upvotes (2026 launches with a clean score).
- Train: 60 days up to Oct 19 (279k pair rows). Test: 22 days, Oct 20 – Nov 10. 7,864 person-days, 20,536 voted launches.
- Upvote dates are the upvoted launch's day: the store holds no real upvote timestamps (page-1 reads are bounded / snapshot).
- Line-up = all of the day's launches with a clean 00:05 score.
- Metrics: top-3 hit = the voted launch is in the person's top 3; ranking accuracy = share of the other launches ranked below it. Day bootstrap.

| model | top-3 hit | ranking accuracy | Δ vs popularity (top-3 / ranking) |
|---|---|---|---|
| a popularity (clean 00:05 score) | 30.1 [24.8, 35.3] | 66.9 [64.5, 69.0] | |
| b + follows the hunter / first named maker (undated edges) | 31.0 | 68.6 | +0.9 [−0.8, 2.6] / **+1.6 [1.3, 2.0]** |
| c + backed this team before | 29.6 | 66.9 | −0.5 / 0.0 |
| d + co-vote CF (taste + neighbours' team backing) | 29.7 | 67.1 | −0.4 / +0.2 |
| e all | 30.8 | 68.7 | +0.7 [−1.3, 2.5] / **+1.8 [1.3, 2.4]** |

**Reading:**
- Neither CF (d) nor the full model (e) clearly beats popularity on top-3 hit. The only gain is about +2 points of ranking accuracy from follow edges, and those edges are undated (possible leak). So the launch-level aggregation was not run.
- These levels are not comparable with the old 57.5% / 0.834. Here every voted launch counts against the full day's line-up (about 30 launches; 2.6 votes per person-day), and people are restricted to ≥ 20 dated upvotes. The old test's line-up and person set differed.
