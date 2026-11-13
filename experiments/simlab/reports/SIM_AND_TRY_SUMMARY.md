# Simulations and the /try endpoint: where things stand (E5, Nov 13 2026, ~19:30Z)

Counts only. Intervals are 95% bootstrap (launch- or day-level, as stated). All tests are out of sample: inputs dated before the launch, and no Product Hunt requests from this session. Reports live under `experiments/simlab/reports/` on `claude/person-model-v2`.

---

## 1. The /try endpoint (paste a URL or a description, get a launch read)

### 1.1 What it runs (site code: `mvp/ph_site/try_sim.py` on `claude/ph-website`)
- **step_page:** `safe_fetch` fetches the URL, then gemini-2.5-flash-lite reads the page (READ_PROMPT).
- **step_reactions:** member types plus `reactions_retrieval_v1` grounding, then gemini-2.5-flash writes "what users will say".
- **step_asks:** ranked concerns and questions. Concerns now use the b20 retrieval recipe (adopted on /try, commit 22db840).
- **step_launch:** the rank band from `launch_band.json`. Pasted text uses the PH band; a URL uses the page band.

### 1.2 End to end, through the site's own code (`try_e2e/`; 57 launches, Oct 25–Nov 10)
- Fetch skip rate: 24.6%, of which 9 pages had no readable text (JavaScript or login) and 5 fetches failed (for example HTTP 403). Skips are highest for rank-1 launches (44%).
- Reaction themes, page read vs the pasted PH description, same launches:
  - recall 47.8 vs 50.7, paired −2.9 [−9.5, +3.6];
  - precision 51.9 vs 53.9.
- Band coverage of the true rank: page 76.7%, PH description 80.7%.
- Band Spearman with final rank: page 0.31, PH description 0.65.
- Latency, median / p90: page read 2.8 / 4.0 s; reactions 6.2 / 7.3 s.
- Cost: about $0.0013 of Gemini per request; the page read is about $0.00004.

### 1.3 Rank band
- Accuracy by input (`try_stability/`, 60 launches; Spearman of band percentile with final rank):

  | Input | Spearman with final rank |
  |---|---|
  | Pasted real PH description | 0.535 [0.31, 0.70] |
  | 2-sentence paraphrase | 0.38 |
  | Page read | 0.33–0.39 |
  | Long marketing copy | 0.29 |
  | Hero text | 0.32 (fails checks on 26 of 60) |

- Stability:
  - Rerunning the same URL moves the band by about 7–8 percentile points, Spearman 0.92. A different product moves it by 38 points.
  - At temperature 0 the band is identical on reruns.
- Corrected coverage claim: the earlier "0.59" was in-sample. Out of sample it is 0.35 / 0.42.
- Forward test (`forward_sim/`): on Nov 11, 84.6% [69, 96] of real ranks fell inside the 10th–90th band (n = 26), Spearman 0.29. The pasted band on Nov 12 reached 91.9%, Spearman 0.52.
- Band v2 (page facts plus retrieval plus topic): not exported. The gain over the current band was +0.045 [−0.000, +0.090] for the servable version, which does not clear zero.

### 1.4 What users will say (reactions)
- Same-point precision from the earlier site backtest: about 0.23 point precision (`reactions_eval`).
- Forward, Nov 11 (pasted text, 6 judged launches): precision 69 [44, 92], recall 58 [44, 78]. This judge pool is more lenient than the backtest's, and n is tiny.

### 1.5 Concerns and questions (ranked top 3)
- Input matters most (`page_path/`, 70 launches), p@3:

  | Input | Concerns | Questions |
  |---|---|---|
  | Pasted PH description | 37.1 | 37.1 |
  | Raw page excerpt | 29.5 | 31.4 |
  | Page-read summary | 25.2 | 29.5 |
  | Constant list | 24.3 | 22.4 |
  | Real-vs-real ceiling | 32–35 | 32–35 |

  Only the pasted description beats the constant list with an interval above zero: +12.9 for concerns and +14.8 for questions.
- Retrieval recipe b20 (`retrieval_react/RECIPE_b20_concerns.md`):
  - It uses the 20 nearest earlier launches' real comment points and condenses them to a top 3 with flash.
  - Replicated on 170 launches. Top-3 concerns go from 25% to 37% from a description and from 17% to 25% from a page.
  - The page-questions gain did not replicate, so only concerns ship.
- Thin-neighbour fallback (`thin_check/`):
  - 31% of targets fall below the page threshold 0.886.
  - Large launches are NOT more often thin: 25% of the largest quartile against 41% of the smallest.
  - On the thin third the common list is best (p@3 17.0, against 9.2 for b20 and 5.9 for the deployed ranked list).
  - Keep 0.886, then fall back to the common list.

### 1.6 Product wording that holds
- "Paste your launch description for concerns and questions. A URL alone gives the rank band and topic-level reactions."
- "Similar launches finished like this." Never "you will finish like this": a band built from the neighbours did not sharpen the forecast.

---

## 2. People-side simulations (who backs a launch, and why)

### 2.1 The forecast is unchanged: clean_nosite stays the ranking
- Top-3/5/10 on 15 days (Oct 25–Nov 11): 64.4 / 70.7 / 76.0.

### 2.2 Who-backs-it (expected backers from people we hold; `who_backs/`)
- Pair model: P(person upvotes launch) from activity, topic taste, team ties and co-upvote factors, trained on prior days.
- Leak rules:
  - history uses only launches dated before the day;
  - follows are undated, so every test runs with and without them;
  - a placebo row ranks by held team count, averaged over 200 tie draws.
- Results:

  | Model | Top-3 | vs clean | vs placebo (30.3) | R-precision |
  |---|---|---|---|---|
  | Standalone FULL (logistic) | 40.0 | −24.4 [−44, −4] | about +10 | 26.1% [25.1, 27.1] |
  | 60 training days | 40.0 | −24.4 | | |
  | Hybrid (count × choice) | 55.6 | −8.9 [−27, +7] | +26.4 [+10, +42] | 22.5% |
  | Choice with clean prior | 55.6 | −8.9 [−24, 0] | +26.4 [+17, +36] | 9.2% |

  R-precision is recall when the list is as long as the launch's real held-voter count.
- Two-input version (expected backers plus pre-launch commenters; 7 days): −9.5 [−33, +14] vs clean. That is not "not worse" (the mean must be within 1.5 points).
- Calibration: expected backers come to about 0.56–0.67 of displayed votes. Held voters come to about 0.50 of displayed votes.
- Why recall is capped (miss anatomy of FULL):
  - 47% of missed backers vote on 5 or more launches that day;
  - 42% had a signal but were ranked far down (median 412 places);
  - 8% were dormant;
  - 3% had no tie at all.
- The top of every list is the heaviest accounts (99.9% in the 1,000 most active), and 76% of them voted for something else.
- Single-vote people are almost unnameable: recall@N 8.5% for them, against 54.5% for 5+ voters.
- Per-person picks (11,649 voter person-days): 46.9% of a person's picks are in our top 3 for them.
  - The clean order for everyone already gives 43.4%, so the personal part is +3.5 [+2.8, +4.1].
  - The oracle using final ranks gives 57.1%.
- Variants that did not help: 30 or 60 training days, weekday rate, a dated team tie, richer person cards (headline, bio, badges, reviews; flash-lite), a softmax choice model, and a count model.
- Website wording (accepted):
  - "people we hold who are most likely to back it; about 1 in 4 of those who did were on our list of the same length (15 days)";
  - "about 47% of someone's picks are in our top 3 for them, mostly because people back the favourites; personal taste adds about 3.5 points."

### 2.3 Backer mix per launch ("who it resonates with"; `who_backs/who_mix2.json`, 291 launches)
- The predicted share by segment (age, activity tier, maker, topic cluster) is worse on absolute error than both the day-average and the topic-average baseline, in all 5 families.
- But it ranks launches better on relative skew. Spearman across launches: age 0.22 vs 0.14, activity tier 0.18 vs 0.11, topic 0.12 vs about 0.
- Re-centred and shrunk versions (`mix_eval.json`):
  - both remove the bias, tying the day baseline (differences −0.02 to +0.03 share points);
  - both beat the topic baseline on age, activity tier and maker;
  - neither beats BOTH baselines in any family, so the pass bar fails;
  - the relative-only wording stands.
- Forecast value: the predicted "skews to accounts under 30 days" deviation correlates with how far the launch beat its clean-forecast rank, Spearman +0.17 [+0.04, +0.30] (348 launches).
  - The placebo (held team count) gives +0.06 [−0.04, +0.17], or +0.11 [+0.02, +0.20] on launches with 20+ held backers.
  - The other deviations are about 0.
  - Weak, and possibly selection-driven; not a forecast input.
- Fallback card wording (accepted): relative statements only, such as "skews younger than a typical launch (rank correlation 0.2, 291 launches)".

### 2.4 Voter harness (summing held people's expected votes into the forecast)
- Top-3 gain 0.0 over clean, on the merged store, the official store and the lossless store (14:35Z), with and without follows. The hidden-window part also gives 0.0.

### 2.5 Earlier person / launch LLM baselines
- Vertex person sim: below popularity (top-3 hit 36 vs 50).
- Decisions API pilot (run by the orchestrator, $0.36):
  - person level worse than popularity;
  - launch probabilities no better as features;
  - pairwise 57.9% vs the clean order's 65.9%;
  - judge 87% agreement with pro (usable as a cheap pre-filter).
- The Nov 13 forward answers are scored tomorrow at 09:30Z.

---

## 3. Account quality and vote counting (explanation, not forecast inputs)
- Exact join dates (all 65,740 complete people) and over-covered launches (store upvoters > displayed votes):
  - fewer brand-new accounts (<30 d: −3.2 pts);
  - more accounts aged 1–12 months (<365 d: +6.2 pts; top-3 +8.7);
  - clusters of accounts created together, ph_user_id within 50 ids: +4.9 pts [+3.6, +6.1] above chance.
- Count weights: accounts 30–365 days old count at about 0.48 in the displayed total; out-of-fold MAE improves by 3.65 votes.
- Young or created-together early commenters predict FEWER final votes beyond clean: partial r −0.15 to −0.18 (1,398 launches).
  - As forecast inputs at 00:05, 00:30, 01:00 and 02:00 they add no robust top-3 gain.
  - Live coverage is near zero (0–17% of commenters held by 01:00).
- Wording: neutral ("accounts 1–12 months old"), never fraud language, groups of 20 or more only.

---

## 4. The "why" file (live, promoted at 13:20Z)
- Written nightly by PH ops' routine to `results/web/why/<day>_0005.json` and `<day>_after.json`, plus `try_neighbours_v1.json` weekly. A shadow copy goes to `why_shadow/` until Nov 20.
- Forecast items (inputs known before 00:00 PT): hunter_followers, held_backers, follow_ties(_active), audience_tiers, expected_held_votes, team_profile, team_reviews_written.
- After-the-fact items: young_upvoters, created_together, young_early_commenters (shown only with 20+).
- Every item carries its measured strength, n and interval. Descriptive items say they did not improve the forecast.
- The website renderer is built (8b1b0e3) and goes live with its follow-up PR.

## 5. Open / scheduled
- Decisions API Nov 13 forward scoring: 09:30Z Nov 14. X-buzz scoring for Nov 13 after final ranks. The X-buzz backfill for Nov 9–12 and the 2025 comment pull have not landed.
- Team-profile forward test (badges, streak and similar, pulled by 01:00 PT): read the partials at about 9 scored days.
- Daily /try forward test (`forward_sim.py`) runs as PH ops' morning job; paired intervals after 7 scored days.
