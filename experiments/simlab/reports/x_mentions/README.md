# X pre-launch mentions by held people (orchestrator 02:00Z Nov 13; x_mentions.py)

Data:
- Grok Bot X rollout: 56 drops, 4,574 people, 60,369 posts / replies / quotes / reposts since Aug 1. Capped at the 25 newest per person; 2,037 people truncated. Parse OK.
- Launches: 1,224, Oct 1 – Nov 10.
- Patterns: product name (≥ 5 characters or two words), domain (178 launches with a held URL), maker / hunter X handle known at 00:05 (56 launches; the handle file covers only Oct 26 on).
- A person counts for a launch only if their fetched posts reach back past the 7-day window (median 3,314 such people per launch).

**Coverage:**
- Launches with ≥ 1 pre-launch mention: **8.8%** (108). Matched by name 87, handle 21, domain 1.
- Launch day before 03:00: 2.9%.
- Name matches can be false positives for generic names.

**Launch scoring** (leave-day-out, 41 days):
- Baseline: the clean 00:05 score (honest_preds_v2). th_n_pre is not held across the whole window.
- Pre-launch mentions: top 3 / 5 / 10 52.8 / 65.9 / 73.4 → 55.3 / 65.9 / 74.6. Gain **+2.4 [−1.6, 6.5]** / 0.0 / +1.2 [−0.5, 2.9]. The weight chosen was 0.25 on every day.
- Launch-day mentions before 03:00: 0.0 (weight 0).
- Late climbers (finished ≥ 5 places above the clean rank, 310) are LESS often mentioned:
  - day mentions: 1.9% vs 3.3%;
  - pre-launch mentions: 7.1% vs 9.4%.

**Person side** (does mentioning a launch / its team before launch predict that person's upvote? store upvotes):
- Vote rate 1.22% (329 mentioner pairs) vs 0.13% base: lift **9.5×**.
- Real but tiny in absolute count: 329 pairs, about 4 votes.

**Verdict:**
- Coverage clears 5%, but the launch-level gain does not clear zero, and the mentions do not flag late climbers.
- The person-level lift is large, but on too few pairs to move a launch's rank.
