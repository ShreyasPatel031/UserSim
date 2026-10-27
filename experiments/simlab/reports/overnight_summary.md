# Overnight summary (Oct 26–27)

Person-level top-3 hit = the person's real upvote is in our top 3 for them, on days they were active. Train Sep, test Oct, 8,761 Oct person-days.

## Scores before and after

| Model | Top-3 hit | Ranking accuracy | Without follows: hit / accuracy |
|---|---|---|---|
| Start of night (popularity + relationships + simple taste + 4 personas) | 57.5% | 0.833 | 51.0% / 0.805 |
| + collaborative filtering on teams | 58.7% | 0.834 | 51.7% / 0.806 |
| + upvote reciprocity (team upvoted the person's launch) | 59.5% | 0.835 | 52.8% |
| + early read: comments in the first 3 h (not pre-launch) | 63.0% | 0.841 | 57.0% |

Pre-launch gain tonight: **+2.0 points** (57.5 → 59.5). With a 3-hour early read: +5.5 points.

**Full upvote histories (Oct 27 morning).**
- What was pulled: complete histories for 2,562 heavy users (1,747 holdout + 815 sample people). Dated upvotes in the data went from 77k to 220k.
- Scored on the same 8,315 Oct person-days, same model (popularity + relationships + simple taste + personas + collaborative filtering):

| Data | Top-3 hit | Ranking accuracy | Without follows: hit / accuracy |
|---|---|---|---|
| Before (page-1 histories) | 58.5% | 0.834 | 51.8% / 0.807 |
| Same predictions, full labels | 60.7% | 0.833 | 54.7% / 0.809 |
| Full histories used for features and labels | 60.5% | 0.836 | 53.8% / 0.809 |

- Full histories add **2–3 points**, almost all from measuring picks more completely (1.41 → 1.64 picks per day). More past backing data barely changes ranking accuracy.
- So deeper histories are worth it for honest scoring, not as a new signal.
- Source: `v2_compare.py` → `v2_compare.json`.

## Spend by provider (caps: GCP $50, DataImpulse $30, Apify $30 — raised Oct 27)

| Provider | Spent | What |
|---|---|---|
| Apify | $3.04 | LinkedIn: pilot $0.06, then 744 profiles |
| DataImpulse | ~$9.0 (counted bytes; **account traffic ran out at ~09:47**: proxy returns `407 TRAFFIC_EXHAUSTED`) | profile pages $1.64, follow re-check $0.11, maker upvote pages $0.41, sample scroll $2.51, holdout scroll $5.46 |
| GCP | ~$1–3 Gemini + $3.8 scraper machine | persona variants; temporary 16-core machine for the scroll (deleted; idle ~6 h because a restart delayed deletion) |
| Free | $0 | X posts, GitHub |

## What is worth paying for on the full backtest

| Worth it | Not worth it (≈0 gain over own comments) |
|---|---|
| Personas from the person's own comments (~$1 Gemini per 17k person-days) | Full LinkedIn |
| Collaborative filtering on teams (free) | Activity text, collections |
| Deep upvote histories (~$0.003 / person): +2–3 pts, mostly better labels | X posts, GitHub |
| Maker upvote lists for reciprocity (~$0.0003 / page) | Followers / hunted as ties (too rare) |
| Homepage snapshots every 15 min, from today (~$0.03 / day) | Retrieval, ensembles, two-tower embeddings, ranker vs trees |

## Leakage notes
- Follow lists are undated (read today), so they may include follows made after the test day. Every result is shown without them; the honest number is the "without follows" column.
- Followers lists and LinkedIn are also undated; neither adds anything, so leakage there doesn't change conclusions.
- Collaborative filtering uses only events before Sep 1. Reciprocity uses upvotes dated before the day.
- Persona cards use only comments, reviews and picks dated before the day.
- Early read excludes the person's own comments, but it uses launch-day data, so it is not a pre-launch number.
- Labels are incomplete for heavy users (page 1 of upvotes only). The full scroll shows this costs about 4 points of measured hit.

## Can we reach 90%?
Full plan: [path_to_90.md](path_to_90.md).
- Perfect use of public signals would give 90–93% (oracle). Today's model gets 52.8% without follows.
- Strictly before launch, the realistic ceiling is about 70–75%.
- 90% needs the launch-day view: when each person visits, what the homepage shows at that moment, plus early comments.
- Start now:
  1. Homepage snapshots every 15 minutes.
  2. Deep histories for all ~14k people (≤ $42, ask first).
  3. Weekly follow snapshots to date follows.
