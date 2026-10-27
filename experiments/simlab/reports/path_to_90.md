# Path to 90% top-3 hit (person level) — interim, Oct 27 08:40 UTC

**Bottom line so far:**
- 90% looks **reachable in principle from public data**. On the October holdout, perfect use of the signals we can see would give 95% (93% without the undated follow lists).
- Today's model gets 57.5%, or 51% without follows.
- The gap is mostly three things, in order:
  1. predicting the exact order of the day's top launches
  2. knowing each person's ties to launch teams
  3. measuring people's real picks completely (our labels miss many upvotes)

## 1. Where the misses are (8,761 Oct person-days, current best model)

| If this were perfect… | Top-3 hit (follows used) | Without follows |
|---|---|---|
| Today | 57.5% | 51.1% |
| + which of the day's top-5 launches they pick | 81.9% | 77.4% |
| + picks from teams they're connected to | **90.0%** | 86.2% |
| + picks matching their taste | 95.1% | 92.8% |

Missed person-days with no detectable public signal: 11.6% (14.6% without follows).

## 2. What drives each bucket

- **Popular picks** are the biggest bucket (24 points).
  - Inside the day's real top 5, ordering by final rank alone picks the person's choice 82.9% of the time; random would be 65%.
  - All personal signals together reach 84.4%.
  - So this bucket is **mostly about predicting the exact order of the leaders**, a launch-level problem, not taste.
  - With perfect final popularity, the person model reaches 60.1% without follows, or 65.5% with them.
- **Connected picks** (8 points): follows, past backing, co-commenting, the team supporting the person.
  - New relationship sources pulled tonight are rare: team member follows the person 6%, person hunted for the team 8%, X mention 1% of person-days. Together they add ~0.
- **Taste picks** (5 points): personas with the person's own comments are the best taste signal (+0.02–0.03 ranking accuracy).
  - Full LinkedIn, activity text and collections add nothing over comments on the screening sample.

## 3. Measurement: labels are incomplete

Current model by how completely we see the person's upvotes:

| People | Person-days | Picks/day | Top-3 hit | Ranking accuracy |
|---|---|---|---|---|
| ≤ 8 upvotes in total (labels complete) | 1,331 | 1.15 | **73.2%** | 0.894 |
| 9–50 upvotes | 2,305 | 1.31 | 61.0% | 0.856 |
| 51+ upvotes (labels very incomplete) | 4,658 | 1.54 | 51.3% | 0.805 |

The browser scroll of full histories for the screening sample is running. It will show how much of the heavy-user gap is missing labels and how much is real behaviour.

## 3b. Complete histories, same predictions (321 heavy users already scrolled, 994 Oct person-days)
- Picks per day: 1.42 with the visible labels, **1.81 with the full history**.
- Top-3 hit with the same predictions: 50.3% → **54.1%**. Ranking accuracy: 0.809 → 0.810.
- So missing labels explain about 4 points for heavy users. The rest of their gap is real behaviour: they upvote broadly.

## 3c. Tonight's best person model (full Oct holdout, 8,761 person-days)

| Model | Top-3 hit | Ranking accuracy | Without follows: hit | Without follows: accuracy |
|---|---|---|---|---|
| Popularity + relationships + simple taste | 53.0% | 0.803 | 45.2% | 0.774 |
| + personas | 57.5% | 0.833 | 51.0% | 0.805 |
| **+ collaborative filtering on teams** | **58.7%** | 0.834 | **51.7%** | 0.806 |
| + embedding interactions | 57.7% | 0.832 | 51.3% | 0.807 |

## 4. Data value measured tonight (screening sample, 1,579 people)

| Source | Coverage | Gain | Cost |
|---|---|---|---|
| Own comment text | 83% | **+0.02–0.03 ranking accuracy** (best) | free (already have) |
| Products built + reviews | 27–35% | +0.01 among those who have it | free |
| Collaborative filtering on teams (people like you backed this team) | all | **+1.3–2.1 points top-3 hit** | free (compute) |
| Full LinkedIn | 41% | ~0 | $0.004 / profile (Apify) |
| Activity text, collections | 98% / 20% | ~0 over comments | ~$0.0003 / page (DataImpulse) |
| Followers / hunted / X mentions as ties | 6% / 8% / 1% of person-days | ~0 | ~$0.0003 / page |
| X posts | 17% | ~0 | free |

## 5. Measured levers (full Oct holdout unless noted)

| Lever | Data needed | Measured gain, top-3 hit | Cost | Before launch? |
|---|---|---|---|---|
| Personas from own comments | comments (have) | +5.8 pts (45.2 → 51.0 without follows) | ~$1 Gemini per 17k person-days | yes |
| Collaborative filtering on teams | upvote histories (have) | +0.7–1.2 pts | free | yes |
| Upvote reciprocity (team upvoted the person's launch) | upvote lists of makers and people | +0.8–1.1 pts at today's 5% coverage | first pages ~$0.0003 each | yes |
| Deeper upvote histories (scroll) | full ~6-month lists | +2.2 pts with follows, +2.7 without (58.5 → 60.7; 51.8 → 54.5), on 3,448 heavy users. Almost all from better labels; ranking accuracy +0.002 | ~$0.003 / person | yes |
| Follow lists | follows (undated) | +6.9 pts, partly leakage until dated | ~$0.0003 / page; dating needs weekly snapshots | if dated |
| Early read: comments in the first 3 h | launch-day comments | **+4.3–5.3 pts** | ~$0.0003 / page | no (3 h in) |
| Perfect final popularity (upper bound) | n/a | +7–8 pts | n/a | no |
| Full LinkedIn, activity text, collections, X | pulled tonight | ~0 | $0.004 / profile LinkedIn | yes |

## 5b. Full histories, measured (Oct 27, `v2_compare.json`)
- Same 8,315 Oct person-days, same model.
- With follows: 58.5% → **60.7%**. Without follows: 51.8% → **54.5%**. This is the new baseline to beat.
- Scoring the old predictions against the fuller labels already gives 60.9% / 54.9%. So the gain is measurement, not new signal.
- The holdout is now complete except 66 people Cloudflare blocked.

## 6. Plan to reach 90% (person level)

**Honest projection with everything above:**
- About **63%** today with follows and an early read.
- About **68–72%** after full histories, the reciprocity graph and dated follows.
- The oracle says public signals contain enough to reach about 90–93%. But even perfect popularity only adds 7–8 points, because the model can't yet pick *which* of the day's leaders each person chooses. Inside the top 5, personal signals add only 1.5 points over rank order.

**What closes the last ~20 points:**
1. **What each person actually sees, and when.** Their visit time (from comment timestamps) and the homepage order at that moment.
   - Start collecting now: homepage snapshots every 15 minutes (~100 pages a day, ~$0.03/day via DataImpulse).
   - Needs ~4–6 weeks before it can be tested.
   - This is an early read, not pre-launch.
2. **Complete relationship graph, dated.**
   - Deep upvote histories for all ~14k people and makers (≤ $42 DataImpulse, ~1 day with 4 browsers).
   - Weekly follow-list snapshots to date follows (~$5/week).
   - Reply graph from comment threads (free, have).
3. **A person-level choice model trained on all of it.** The tree ranker plus comment personas tonight; a fine-tuned model once the data is complete. Fine-tuning price is not confirmed; get a quote first.
4. **Measure on complete labels only.** Report hit separately for people with complete histories: today 73% for people with ≤ 8 upvotes.

**Decision for the founder:**
- Strictly before launch, the realistic ceiling is about 70–75%.
- **90% needs the launch-day view:** visit time and page order, plus early comments. Collecting that starts now and needs several weeks of data before it can be tested.
