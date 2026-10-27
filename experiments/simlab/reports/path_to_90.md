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

## 5. Concrete plan to 90% (draft, finalised after the scroll)

1. **Fix measurement:** full upvote histories for everyone in the test set (scroll, DataImpulse ~$0.001–0.003 per person). If labels are the gap, this alone moves measured hit a lot.
2. **Better popularity ordering** (bucket A, up to 24 points): the launch-level model is the lever. The person model inherits its errors.
3. **Dated relationships** (bucket B, 8 points):
   - Snapshot follow lists going forward so follows can be dated (they can't be dated from past pages).
   - Build the co-commenting and reply graph from comment threads.
4. **Taste** (bucket C, 5 points): personas built from the person's own comments, and collaborative filtering.
5. **The remaining ~10–15%** has no public pre-launch signal. It would need launch-day data: who the team pings and posts to, and the intraday page order.
