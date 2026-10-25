# Product Hunt top lists: what predicts them (Oct 25, 2026)

Backtest on **7,696 featured launches (Oct 1, 2025 – Oct 24, 2026)**, scored on **April – October 2026**. Every
month was predicted by a model trained only on earlier months, using nothing from the launch's own votes, comments or
ranks. Full tables: [`out/report.md`](out/report.md); numbers: [`out/metrics.json`](out/metrics.json).

## 1. How accurately we predict the lists (recall@k, headline model)

Recall@k = share of PH's real top k that we put in our top k. Random picking in brackets.

| List | top 3 | top 5 | top 10 | lists scored |
|---|---|---|---|---|
| Yesterday's (daily) | **0.60** (0.17) | **0.66** (0.24) | **0.70** (0.34) | 111–200 days |
| Last week's | **0.42** (0.02) | **0.54** (0.03) | **0.54** (0.07) | 28 weeks |
| Last month's | **0.11** (0.01) | **0.20** (0.01) | **0.33** (0.01) | 6 months |

- 95% intervals: day@5 0.63–0.68, week@10 0.50–0.58, month@10 0.23–0.45 (only 6 months, so wide).
- Rank correlation with the real daily order: 0.64.
- Stable over time: daily top 5 between 0.62 and 0.74 every month from May (April 0.55).
- More history helps a little: extending training data back from March 2026 to October 2025 moved day@5
  0.64 → 0.66, week@10 0.51 → 0.54, month@10 0.28 → 0.33, rank correlation 0.61 → 0.64 (earlier run kept in
  `out_apr_oct_v1/`).
- Adding makers' and hunter's **follower counts** lifts month@10 to 0.40 and day@10 to 0.73. Those counts are
  today's, so they may include followers won by the launch. Re-checking yesterday's makers 2 hours apart showed
  0–5 new followers each (even for #1), so the leak looks small, but growth during launch day itself was not
  measured. The headline model leaves them out.

**Topic lists** (ranking inside one topic): Developer Tools day@3 0.71 (random 0.35), AI day@5 0.73 (0.34),
AI week@10 0.59 (0.13), Productivity week@10 0.68 (0.21), Open Source week@5 0.72 (0.24), Developer Tools
month@10 0.55 (0.05). Mac apps are the weakest (week@10 0.37 vs random 0.32).

**Today's homepage lists, predicted out of sample:**
- Yesterday (Oct 24, 14 launches): #1 zCAD AI right; 2 of the top 3, 4 of the top 5, 8 of the top 10.
- Last week (Oct 12–18, 203 launches): #1 Pancake right; 4 of the top 5, 5 of the top 10.
- Last month (September, 708 launches): 1 of the top 3, 2 of the top 5, 6 of the top 10.

## 2. Which sources carry the signal

| Source | Alone: day@5 / week@10 | Full model without it: day@5 / week@10 |
|---|---|---|
| **People** (team size, hunter account age, self-hunt) | 0.54 / **0.39** | 0.61 / **0.39** (biggest loss) |
| **History** (hunter's and makers' earlier PH launches, topic and look-alike track record) | **0.58** / 0.30 | **0.59** / 0.41 |
| Launch listing (field size that day, weekday, links, media, topics) | 0.43 / 0.19 | 0.64 / 0.55 |
| Website (Apify crawl) | 0.39 / 0.19 | 0.66 / 0.56 |
| LLM read of listing + site (Gemini) | 0.38 / 0.12 | 0.65 / 0.55 |
| Hacker News before launch | 0.36 / 0.10 | 0.66 / 0.55 |
| Domain age | 0.33 / 0.14 | 0.65 / 0.54 |
| GitHub stars before launch | no coverage (see limits) | — |
| (random) | 0.24 / 0.07 | full model: 0.66 / 0.54 |

**Who launches it beats what it is.** People + history explain most of the ranking. The website and the LLM's
judgment of the product beat random on their own, but add about nothing once you know the team and the hunter.

## 3. Which factors matter (inside the same week; Spearman with log votes)

- Self-hunted **−0.41**: self-hunted launches reach the daily top 5 11% of the time, others 38%
- Hunter account age **+0.40**; hunter's earlier top-10 rate **+0.36**; hunter's number of earlier hunts **+0.35**
- Team size (makers listed) **+0.36**: 4+ makers reach the daily top 5 53% of the time, 2–3 makers 34%, solo 13%
- Gemini's "established team" score **+0.28**; hunter has Twitter linked **+0.28**
- More featured launches that day **−0.30** (votes are split; matters for week and month lists)

## 4. How it changes by product type

- **Developer tools** (40% of launches) and **AI** (29%): hunter and team dominate (self-hunted −0.47 and hunter
  age +0.44 for Developer; hunter's earlier hunts +0.44 for AI). Gemini's "established team" score also counts
  for Developer (+0.33).
- **Design**: the product itself matters most here. Gemini's top-5 odds **+0.37**, demo appeal +0.25, domain age
  +0.23.
- **Marketing & Sales**: hunter track record (+0.33) and repeat makers (+0.24).
- **Productivity and Consumer**: crowding that day matters most (−0.33 / −0.28); people signals are weaker.

## 5. What this means for UserSim

PH votes mostly measure **distribution** (who hunts, team size, track record), not product quality. A simulator
that judges the product (like the LLM/website features here) adds about 1 point on top.

The product signal is real but small. `residual.py` fits a "who launched it" model (launch + people + history),
takes what it can't explain (actual minus predicted log votes, out of sample, de-meaned by week), and checks
whether judging the product predicts that leftover (Spearman, 4,878 launches):

| | Gemini top-5 odds | broad appeal | novelty | demo appeal |
|---|---|---|---|---|
| All types | +0.10 | +0.08 | +0.06 | +0.05 |
| Developer | +0.12 | +0.10 | | |
| Productivity | +0.10 | | +0.14 | +0.08 |
| Consumer | | | +0.19 | |
| Design | +0.09 | +0.10 | | +0.13 |

At this sample size these are not chance, but they are too weak to move the top-k lists (adding product features
to the network model: day@5 0.64 → 0.65, week@10 0.56 → 0.52, both noise).

**Proposed UserSim eval:** predict the residual, i.e. which launches do better or worse than their team and hunter
predict. A simulator that actually uses the product should beat Gemini's +0.10 on it. `residual.py` computes the
target for every launch; Developer and Productivity tools, where the signal is clearest, are the place to start.

## 6. Live test and how to check it

`out/live_2026-10-25.csv` ranks today's 13 featured launches, saved at 4:30 AM PT (before results);
`out/live_2026-10-25_v2.csv` is the final model's ranking, saved at 5:51 AM PT. After midnight PT run
`python experiments/ph_predict/score_live.py 2026-10-25` (add `_v2` for the second). Predicted top 3 (v2): Llama
Windows, Moli by Lexmount, Openstatus Incident Management.

## Limits

- Websites are crawled today, not on launch day (PH mentions are stripped). Maker lists and account ages come
  from the API today.
- Monthly results rest on 6 months; weekly on 28 weeks.
- Not used: LinkedIn (blocks this container) and X (needs paid API); no personal logins were used.
- GitHub signal has no coverage. The 938 launches with a GitHub link were resolved (880 repos), but
  stars-before-launch needs the GitHub API, which this cloud session can only call for its own repo. Run
  `external.py` with a normal GitHub token to fill it (`cache/web_github/` holds the repo URLs).
- PH's API hides other users' launch histories (`madePosts` / `submittedPosts` come back empty), so track records
  are built from the launches collected here (Oct 2025 onward).
- Cost: Apify $6.23 (website + GitHub link crawl), Gemini a few cents, PH API and other sources free.
