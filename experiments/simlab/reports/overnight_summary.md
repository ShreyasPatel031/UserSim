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

## Spend by provider (caps: GCP $50, DataImpulse $20, Apify $10)

| Provider | Spent | What |
|---|---|---|
| Apify | $3.04 | LinkedIn: pilot $0.06, then 744 profiles |
| DataImpulse | ~$2.2 + scroll (~$1.2 so far, ~$2.9 at the end) | profile pages $1.64, follow re-check $0.11, maker upvote pages $0.41, full-history scroll for 1,008 people |
| GCP (Gemini) | ~$1–3 | persona variants on the screening sample |
| Free | $0 | X posts, GitHub |

## What is worth paying for on the full backtest

| Worth it | Not worth it (≈0 gain over own comments) |
|---|---|
| Personas from the person's own comments (~$1 Gemini per 17k person-days) | Full LinkedIn |
| Collaborative filtering on teams (free) | Activity text, collections |
| Deep upvote histories for everyone (≤ $0.003 / person): fixes labels, 3.2× more ties | X posts, GitHub |
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
