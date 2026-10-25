# Product Hunt top lists: what predicts them (Oct 25, 2026)

Backtest on **5,554 featured launches (Apr 1 – Oct 24, 2026)**. Every month was predicted by a model trained only
on earlier months, using nothing from the launch's own votes, comments or ranks. Full tables: [`out/report.md`](out/report.md).

## 1. How accurately we predict the lists (recall@k, headline model)

Recall@k = share of PH's real top k that we put in our top k. Random picking in brackets.

| List | top 3 | top 5 | top 10 | lists scored |
|---|---|---|---|---|
| Yesterday's (daily) | **0.60** (0.17) | **0.64** (0.24) | **0.69** (0.34) | 111–200 days |
| Last week's | **0.41** (0.02) | **0.52** (0.03) | **0.51** (0.07) | 28 weeks |
| Last month's | **0.17** (0.01) | **0.27** (0.01) | **0.28** (0.01) | 6 months |

- 95% intervals: day@5 0.61–0.67, week@10 0.47–0.55, month@10 0.20–0.37 (only 6 months, so wide).
- Stable over time: daily top 5 between 0.61 and 0.71 every month from May (April 0.50: little history yet).
- Adding makers' and hunter's **follower counts** lifts month@10 to 0.42 and day@10 to 0.73. Those counts are
  today's, so they may include followers won by the launch; re-checking yesterday's makers 2 hours apart showed
  0–5 new followers each (even for #1), so the leak looks small, but launch-day growth itself was not measured.

**Topic lists** (ranking inside one topic): Developer Tools day@3 0.70 (random 0.35), AI day@3 0.66 (0.26),
Productivity week@10 0.70 (0.21), Open Source week@5 0.72 (0.24), AI month@10 0.38 (0.03). Mac apps are the
weak spot (day@5 0.40 vs random 0.50).

**Today's homepage lists, predicted out of sample:**
- Yesterday (Oct 24): top 3 exactly right (zCAD AI, myPip, 1Password for Agents); 4 of the top 5; 7 of the top 10.
- Last week (Oct 12–18): #1 Pancake right; 2 of the top 3, 4 of the top 5, 5 of the top 10.
- Last month (September, 708 launches): 1 of the top 3, 2 of the top 5, 4 of the top 10.

## 2. Which sources carry the signal

| Source | Alone: day@5 / week@10 | Full model without it: day@5 / week@10 |
|---|---|---|
| **People** (team size, hunter account age, self-hunt) | 0.56 / 0.37 | 0.60 / **0.33** (biggest loss) |
| **History** (hunter's and makers' earlier PH launches, topic and look-alike track record) | **0.58** / 0.25 | **0.58** / 0.42 |
| Launch listing (field size that day, weekday, links, media, topics) | 0.43 / 0.19 | 0.63 / 0.53 |
| Website (Apify crawl) | 0.38 / 0.19 | 0.64 / 0.53 |
| LLM read of listing + site (Gemini) | 0.40 / 0.12 | 0.63 / 0.53 |
| Hacker News before launch | 0.35 / 0.09 | 0.64 / 0.51 |
| Domain age | 0.34 / 0.12 | 0.64 / 0.51 |
| GitHub stars before launch | 0.24 / 0.05 (no coverage) | 0.63 / 0.52 |
| (random) | 0.24 / 0.07 | full model: 0.64 / 0.51 |

**Who launches it beats what it is.** People + history explain most of the ranking. The website and the LLM's
judgment of the product beat random on their own, but add about nothing once you know the team and the hunter.

## 3. Which factors matter (inside the same week; Spearman with log votes)

- Hunter's earlier top-10 rate **+0.43**; self-hunted **−0.43**; hunter account age **+0.40**; hunter's number of
  earlier hunts **+0.33**
- Team size (makers listed) **+0.36**: 4+ makers reach the daily top 5 51% of the time, 2–3 makers 29%, solo 10%
- Self-hunted launches reach the daily top 5 7% of the time; launches hunted by someone else 34%
- Makers who launched before **+0.30**; Gemini's "established team" score **+0.28**
- More featured launches that day **−0.32** (votes are split; matters for week and month lists)

## 4. How it changes by product type

- **AI and Developer tools** (70% of launches): hunter and team dominate (hunter account age +0.45, self-hunted
  −0.47 for Developer). People alone gets AI week@5 to 0.47 vs 0.12 random.
- **Design**: the product itself matters most here. Gemini's top-5 odds **+0.41**, demo appeal +0.28, Twitter
  link +0.27.
- **Consumer and Marketing & Sales**: repeat makers (+0.28 to +0.30) and media count matter more.
- **Productivity**: crowding that day (−0.32) and hunter track record (+0.31); people barely beat random here.

## 5. What this means for UserSim

PH votes mostly measure **distribution** (who hunts, team size, track record), not product quality. A simulator
that judges the product (like the LLM/website features here) adds about 1 point on top. To use PH as an eval for
UserSim, score the simulator on the part the network doesn't explain: the residual of this model, or comparisons
between launches with similar hunter/team profiles. Design tools are where product judgment already shows up.

## 6. Live test and how to check it

`out/live_2026-10-25.csv` ranks today's 13 featured launches, saved at 4:30 AM PT (before results). After midnight
PT run `python experiments/ph_predict/score_live.py 2026-10-25`. Predicted top 3: Llama Windows, Openstatus
Incident Management, Moli by Lexmount.

## Limits

- Websites are crawled today, not on launch day (PH mentions are stripped). Maker lists and account ages come
  from the API today.
- Track records only see Mar–Oct 2026; longer history would likely help (April, with the least history, was weakest).
- Monthly results rest on 6 months.
- Not used: LinkedIn (blocks this container) and X (needs paid API); no personal logins were used.
- GitHub signal had no coverage: PH's website link rarely points to GitHub, and resolving the separate GitHub links
  was out of time.
- Cost: Apify $4.42 (website crawl), Gemini a few cents, PH API and other sources free.
