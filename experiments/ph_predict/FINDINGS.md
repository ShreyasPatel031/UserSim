# Product Hunt top lists: what predicts them (updated Oct 25, 2026, afternoon)

Backtest on **7,696 featured launches (Oct 1, 2025 – Oct 24, 2026)**, scored on **June – October 2026**. Every
month is predicted by a model trained only on earlier months. A launch's own votes and ranks are never inputs.
Full tables: [`out/report.md`](out/report.md); numbers: [`out/metrics.json`](out/metrics.json).

## 1. Accuracy (recall@k; random in brackets)

Recall@k = share of PH's real top k that we put in our top k.

| Model | day@3 | day@5 | day@10 | week@5 | week@10 | month@10 |
|---|---|---|---|---|---|---|
| **Pre-launch** (listing, team, hunter, track records) | **0.66** | 0.68 | 0.72 | 0.58 | 0.58 | 0.38 |
| Pre-launch + every other pre-launch source | 0.62 | 0.69 | 0.72 | 0.59 | 0.51 | 0.33 |
| **First 4 hours** (pre-launch + PH comments, X, HN from launch to +4 h) | 0.65 | **0.70** | **0.76** | **0.65** | **0.61** | **0.50** |
| First 4 hours + today's follower counts (may leak) | 0.67 | 0.72 | 0.78 | 0.64 | 0.61 | 0.53 |
| (random) | (0.18) | (0.25) | (0.36) | (0.04) | (0.07) | (0.02) |

- 95% intervals, first-4-hours model: day@5 0.67–0.73, day@10 0.74–0.79, week@10 0.56–0.67, month@10 0.38–0.60
  (only 4 complete months).
- Rank correlation with the real daily order: 0.68.
- Stable by month: daily top 5 between 0.67 and 0.73 in every test month.
- **Adding sources in bulk hurts.** Website text, Gemini's read, HN history, domain age, same-product history and YC
  each beat random alone, but together they lower weekly top 10 from 0.58 to 0.51: dozens of weak features let
  the model fit noise. The pre-launch headline uses only listing + people + track record.

**Today's homepage lists (first-4-hours model, out of sample):** yesterday (Oct 24) top 3 exactly right, 4 of 5,
8 of 10; last week (Oct 12–18) #1 right, 3 of 5, 5 of 10; last month (September, 708 launches) 3 of 5, 6 of 10.

## 2. Which sources carry the signal

| Source | Alone: day@5 / week@10 | First-4-hours model without it: day@5 / week@10 |
|---|---|---|
| **Early PH comments** (first 1–4 h: count, distinct commenters, time to first and 20th comment) | 0.58 / **0.46** | 0.67 / **0.56** (biggest loss) |
| **Track record** (hunter's and makers' earlier launches, topic, look-alikes) | **0.62** / 0.31 | 0.68 / 0.55 |
| **People** (team size, hunter account age, self-hunt) | 0.58 / 0.41 | 0.71 / 0.57 |
| Listing (field size that day, weekday, links, media, topics) | 0.45 / 0.20 | 0.71 / 0.64 |
| X posts linking the domain, −24 h to +4 h | 0.35 / 0.12 | 0.71 / **0.65** (better without) |
| HN stories in first 4 h | 0.26 / 0.09 | 0.70 / 0.63 |
| Website, Gemini, HN history, domain age, same-product history, YC, GitHub | 0.26–0.41 / 0.10–0.20 | not in the headline model |
| (random) | 0.25 / 0.07 | full: 0.70 / 0.61 |

**Who launches it, then how fast PH users engage, decides the lists. What the product is barely matters.**
X buzz (12,371 tweets) and same-day HN add nothing on top; the best simple combination is pre-launch + early PH
comments.

## 3. Factors (Spearman with log votes, inside the same week)

- Comments in the first 4 hours **+0.49**; distinct commenters in the first 2 hours **+0.43**
- Self-hunted **−0.41** (top-5 rate 11% vs 38%); hunter account age **+0.40**; hunter's earlier top-10 rate **+0.36**
- Team size **+0.36** (4+ makers: 53% reach the daily top 5; solo: 13%)
- More featured launches that day **−0.30**

By product type: Developer and AI tools follow the hunter and team most; Design is where Gemini's read of the
product matters most (+0.37); Productivity and Consumer depend most on how crowded the day is.

## 4. What this means for UserSim

The product signal is real but small: after removing what "who launched it" explains, Gemini's read still
correlates +0.08 with the leftover votes (3,152 launches, June–October; +0.12 for Developer tools, demo appeal
+0.23 for Design), too weak to move top-k lists. That leftover is the right target for a product simulator
(`residual.py`).

## 5. Why not 90%

The ceiling is the data, not the model (ranking objective, tuning, more trees: no gain). What is still missing:

| Missing signal | Why it isn't here | What unblocks it |
|---|---|---|
| **Upvotes in the first hours** (what PH ranks on) | API exposes no vote timestamps; archived homepage snapshots are ~1 a day at random times | Record PH's leaderboard every 30 min from 00:01 PT, going forward (needs the VM job below) |
| More than 20 comments per launch | API returns at most 20 per post per query; full history ~100 points per launch | Paginate only launches that hit 20 in their first 4 h |
| Follower counts at launch time | Only today's counts exist | Record at 00:01 PT going forward |
| Website traffic history (Ahrefs / DataForSEO) | Reading those keys from Secret Manager was blocked in this session | Add `AHREFS_API_TOKEN` or `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD` as environment variables |
| Reddit | Reddit blocks Apify's IPs; API keys needed | Add `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` |
| GitHub stars before launch | This session's GitHub token only covers this repo | Add a normal read-only `GITHUB_TOKEN` (880 repos already resolved) |
| LinkedIn | Blocks this container | VM + residential, but only today's counts |
| A daily live collector | SSH to `usersim-grokbot-web` over IAP connects but the service account is refused ("Permission denied (publickey)") | Grant it OS Login (`roles/compute.osAdminLogin`), or I ship the job by merging to `main` (deploys automatically) |

Expect intraday upvote snapshots to matter most: with PH's own early leaderboard, daily lists a few hours in should
reach well above 0.8; monthly top 10 out of ~700 launches stays hardest.

## 6. Live test

`out/live_2026-10-25.csv` (4:30 AM PT) and `out/live_2026-10-25_v2.csv` (5:51 AM PT) rank today's 13 launches
before results. After midnight PT: `python experiments/ph_predict/score_live.py 2026-10-25 [_v2]`.

## Limits

- Websites are crawled today, not on launch day (PH mentions stripped). Maker lists and account ages are today's.
- Monthly results rest on 4 months; weekly on 20 weeks.
- Early PH comment data reaches back to March 22, 2026 so far (collection continues), so the first-4-hours model
  had 2–7 months of training data per test month.
- No personal logins were used.
- Cost so far: Apify about $11 (website and GitHub-link crawl $6.23, X search about $5), Gemini a few cents, PH API
  free.
