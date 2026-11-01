# UserSim on Product Hunt: project history (Oct 25 – Nov 1, 2026)

Goal: Atelier ([atelier-sim.com](https://atelier-sim.com/)), open-source user simulation. Product Hunt is the proof of
concept: predict each day's top 3/5/10 before launch from simulated users, and say who will care about a product and
why. Every number below is out of sample: each month is predicted by a model trained only on earlier months. Daily
top-k = share of the real top k in the predicted top k. **A change under about ±3.5 points on daily top 3 is noise.**
Numbers come from `ph_predict/results/REPORT.md`, `simlab/reports/overnight_summary.md`, `path_to_90.md`,
`overnight_1030.md` and `competitor_comparison.md`.

Two models are tracked throughout:
- **Launch model.** One gradient-boosted model per launch: hunter and maker audience, track record, page, text and
  so on.
- **Simulation.** A person model scores every pool person (about 7–16k people) on every launch that day. The launch
  score is built only from those simulated choices, plus audience size.

## 1. Start (Oct 25): the launch model
Backtest Mar–Oct, 5,758 launches, 238 days. Random is 20 / 32 / 48.

| | Daily top 3 / 5 / 10 |
|---|---|
| Launch model, all sources | 60 / 69 / 77 |
| Product Hunt audience and metadata only | 57 / 67 / 76 |
| Gemini reading the pitch | 25 / 42 / 59 |
| Same, Jul–Oct (more history to learn from) | 63 / 72 / 81 |

**Finding:** votes mostly measure distribution, meaning the hunter's and makers' reach. Reading the product barely
helps. X audience, Hacker News, domain age and commenter networks each changed the result by 1 point or less.

## 2. People-level simulation (Oct 25–27)
- **Data:** about 19k Product Hunt people, with dated upvotes and comments, follows, profiles, stacks, reviews and
  Gemini personas. Full upvote histories were pulled for about 3,400 heavy users.
- **Person level (Sep train, Oct test)** measures whether a person's real pick is in our top 3 for them:
  - popularity + relationships + simple taste + personas: **57.5%**
  - collaborative filtering on teams: +1.2
  - reciprocity: +0.8
  - full histories: **60.7%**
  - This number includes popularity. Later person-level numbers below exclude it, so they are lower.
- **Oracle:** if we knew our pool's *real* votes, the daily top 3 would be about **91%**. So the people carry the
  answer; the hard part is predicting their votes.

## 3. Page-aware simulation (Oct 28–31)

Simulation-only daily top 3, in order:

| Step | Daily top 3 | Move |
|---|---|---|
| Person simulation alone (Apr–Oct) | 38.5 | — |
| + page and per-person taste for page traits | 39.6 | +1.1 |
| + reach × page conversion (Jun–Oct) | 46.7 | +3.1 vs no page |
| + outside reach: makers' and hunter's PH followers, X followers | 58.3 (Jul–Oct; 52.9 before) | **+5.4, the biggest single gain** |
| + full audience, standing in the day's line-up, page | 60.6 | +2.3 |
| Page inputs fixed: real images, real websites from PH links (72%), watched videos (88–97%); coverage gate | 60.3 / 70.9 / 79.7 | 0 |
| + competitor gaps on validated lists | 61.5 / 71.0 / 80.2 | +1.2 (noise) |
| + **tie strength** (Nov 1) | **62.6 / 71.2 / 79.7** | +2.3, paired 95% CI −0.3 to +4.9 |

- **First-time teams** (53% of launches, Atelier's target): the simulation now matches the launch model. Picking the
  higher of 2 is 68.8 vs 68.4; picking the winner of 3 is 66.4 vs 66.7.
- **Launch model over the same period:** 65.8 / 72.9 / 80.8 (Jul–Oct). Mar–Oct with real websites it is
  62.3 / 70.7 / 79.2. A ranking objective and a settings sweep got 64.4 at best: noise.

## 4. What helped and what didn't

**Helped (measured):**
- **Outside reach:** +5.4 on simulation daily top 3, and +7 on pairs among first-time teams.
- **Tie strength** (Nov 1):
  - Inputs: ties to the makers and to the hunter counted separately, recency, comments, share of the person's history.
  - Person-level top-3 hit **54.2 vs 50.4**, better in 6 of 6 months.
  - The hunter tie alone separates picks from non-picks better than the maker tie (AUC 0.65 vs 0.59).
- **Per-person taste for page traits:** person top-3 hit 47.0 → 48.8, 6 of 6 months.
- **Real page inputs:** they made the measurements trustworthy. Guessed websites were right only 8–48% of the time.

**Didn't help (within noise):**
- Choice-style aggregation (+0.2).
- Gemini personas at launch level (top 5 +3.4, on 24 days only).
- Listwise Gemini picker (28.0 vs 50.1 for the person model).
- Upworthy headline scorer on taglines (correlation 0.016).
- Herding.
- Larger pool: flat above 50% of the pool.
- Presence from comment hours: −0.3 person-level.
- Vector twins: −1.1 person-level.
- Hunter and competitor ties as counts (as opposed to tie strength).
- GitHub (0.6% of voters found) and public X replies (1.1%, makers' side 0.2%).

## 5. North stars

**Competitor grounding increasing predictive value**
- **Partly met.** Competitor lists named by Gemini match real users' alternatives about twice as well as meaning
  similarity: 28.6% vs 12–14% in the top 5, 43% vs 21–23% with at least one hit.
- Against the right competitors, nearly every page element's gap predicts beating expected reach. The strongest:
  video shows the problem +0.083, top-5 chance +0.071.
- **Accuracy didn't move:** +1.2 on the simulation, nothing on the launch model, and nothing on top of tie strength.
- **Picking the most-voted of 3 competitors:**

  | Window | Simulation | Launch model | Random |
  |---|---|---|---|
  | Same day | 59.7 | 73.9 | 33.3 |
  | Same week | 62.3 | 72.3 | 33.3 |
  | Same month | 63.9 | 73.1 | 33.3 |

**90% on top 3/5/10**
- **Not met.** Best pre-launch:
  - simulation 62.6 / 71.2 / 79.7
  - launch model 65.8 / 72.9 / 80.8
- So the gap is about 27 / 18 / 10 points to the simulation's best and 24 / 17 / 9 to the launch model's.

## 6. Biggest blockers
1. **Who the makers reach on launch day is invisible before launch.** Breakdown of real picks
   (`rel_split.py`, Jul–Oct):

   | Pick type | Share of picks | In the person model's top 3 |
   |---|---|---|
   | Tied to the team before the day | 63% | 44% |
   | Follow (Product Hunt) | 7% | 18% |
   | No visible tie | 30% | 10% |

   - A line-up holds a median of 9 tied launches per person.
   - Tie strength fixed part of this. The rest needs the makers' off-Product Hunt audience (X, Slack, email).
2. **Thin profiles.** Before Sep 1, the median active person had 4 dated actions. 54% had fewer than 5; 30% had an X
   handle.
3. **Live data hygiene.** On Oct 31, live paging repeated 2 launches and missed 2. This is fixed: stable order, Pacific
   offset after DST, plus a leaderboard cross-check. Nov 1 ran late because the machine stayed on.
4. **Permissions.** VM restarts and deploys were often blocked, which cost hours.

## 7. Next 3 steps
1. **Launch-day forecast from the hourly vote snapshots.** Snapshots started Oct 31. On Oct 31, the hour-7 ranking
   already matched the final top 3. That is one day, so not proof. About 14 clean days are needed; then votes at
   hours 1/2/4 plus the pre-launch score, scored the same way. This is a separate claim, made during launch day, and is
   labelled as such.
2. **Makers' audience from X via Grok Bot.**
   - Engagement with launch posts first, then makers' followers.
   - A go/no-go sample first: about 200 voter–maker pairs and 200 non-voter pairs.
   - Scale up only if voters follow the maker at 3× or more the non-voter rate, covering at least 10% of untied
     voters.
3. **Tie strength into the daily pipeline**, and its extension:
   - each hunter's and maker's turnout rate, meaning the share of past backers who come back;
   - reply threads between the person and the team.

   This is aimed at the 30% of untied picks and at first-time teams. Use the leaderboard cross-check every day.
