# HN user simulation: end-to-end plan

## Context

Goal: when someone posts (title, link, time), say how likely it is to make the day's top 30 / top 10, **before any
votes exist**. Today's at-posting model only uses the post itself (title, domain, author, hour): AUC 0.78, catches 22%
of a day's top 30. Everything stronger so far reads votes that already happened, which is not prediction.

The missing piece is the audience: who is on HN, what each person likes, who is around when a post goes up, and who
browses /new (the few hundred people whose first votes decide a post's fate). That is the user simulation.

Honest ceiling: HN outcomes have a large luck component (same content, different early exposure -> different fate;
MusicLab result). At-posting prediction will not reach the 80% that reading votes reaches. The realistic target is a
**calibrated probability** per post plus a good ranking among the day's ~1,000 posts (e.g. 35-45% of winners in the
model's top 30 at posting, from 22% now), and knowing *which* audience would like it.

## The simulated population

Two kinds of "twins", cheap to expensive:

1. **Vector twins (free, everyone).** Per person, from their public comments before the cut-off: a taste vector
   (mean title embedding of stories they engaged with, recency-weighted), activity rate, hour-of-day presence, and a
   "scout" share (comments within 60 min of posting = /new browser). Covers ~60k people active in the last 6 months.
   Already built: `embed.py` (Vertex text-embedding-005, 768-d, ~$1.2 measured when done), `audience.py` (running).
2. **LLM twins (Gemini on Vertex, a panel).** A persona prompt built from a person's own comments and favorites;
   asked "would you upvote / comment on this?" per post. Richer than a vector, but costs per (twin, post) call.
   Reuses `llm.py` (cached, cost-metered), `persona_vote.py` / `taylor_vs_ours.py` (ballot machinery).

How many are needed: the deciding votes come from a few hundred to a few thousand active scouts. Tally noise:
if winners get 2% of a panel's votes and losers 0.5%, a panel of 200 gives 4 vs 1 (std ~2, not separable); 1,000 gives
20 vs 5 (std ~4.5, separable). So: **vector twins for all ~60k; LLM twins for a panel of ~1,000 scouts**, scoring only
the ~100 posts/day the cheap model does not already rule out. Cost at Flash-Lite, ~1k tokens a call: 1,000 x 100 =
100k calls/day ~ $10/day for a backtest day. Pilot first (below). Approved LLM budget: $25 total (pilot ~$2 + a
~20-day backtest ~$20); measured cost reported with every result, stop at $25.

## Step 1: individual reliability (do this before any tally)

A twin is only useful if it predicts *its own person*. Test per person, on held-out time:
- Panel: the 3,000 most active early commenters (favorites being fetched now on hn-sim-1: `favs.py`, ~3 h).
- Build each twin from data before 2026-07-01. Hold out Jul-Oct: the stories the person engaged with (comments,
  favorites) vs matched stories they did not (same days, front page, same hour -> they plausibly saw them).
- Score: per-person AUC of "would engage"; report the distribution (median, share of people above 0.7) for
  vector twins vs LLM twins vs a no-person baseline (story popularity only). Also check the presence model: predicted
  active hours vs actual.
- Pilot size for LLM twins: 200 people x 40 stories = 8k Flash-Lite calls (~$1-2, measured, logged to spend).
- Gate: a twin type is "reliable" if median per-person AUC > 0.7 and it beats the popularity baseline. Only reliable
  twins go into the tally. If LLM twins are not better than vector twins, stop paying for them.

## Step 2: population tally -> probability

- For each new post: expected early votes = sum over twins of P(sees it at that hour) x P(likes it); separately for
  scouts (first 60 min) and the wider audience (front page). Features: `aud_*`, `scout_*`, `fans_*` in `audience.py`.
- Content prior with no people: outcomes of the 30 nearest past titles (`knn_*`).
- Calibrated classifier (LightGBM + isotonic on held-out days) -> P(top 30), P(top 10) at posting; also at 15/30/60 min
  for the "I just posted" check. Train Jul-Aug, test Sep-Oct 14 (per `per_post.py`), report AUC, avg precision,
  Brier, calibration table, winners caught in the model's top 30 / 100 of the day. Baseline to beat: AUC 0.783, 22%.
- Keep `score_live.py` scoring live forecasts daily; add the per-post forecast to `forecast_daily.py` on hn-sim-1.

## Step 3: product and long term

- Product: paste a draft post -> P(top 30 / top 10), which audience segments like it (named clusters of twins), best
  posting hour, and twin comments/objections (the original UserSim idea; `arms.py`/`judge.py` machinery).
- Keep learning: favorites (closest public thing to upvotes) for more people; live recorders already running
  (front page, pool, hourly list, GitHub stars); monthly retrain with time cut-offs so nothing from the future leaks.
- Research the hidden parts: HN moderation (penalties, second chance), and whether twins can be made better with
  more of a person's history (favorites vs comments only) - measured by the Step 1 test, not assumed.

## Files

- New: `audience.py` (built), `embed.py` (built), `twin_test.py` (Step 1), `twin_llm.py` (LLM panel), `calib.py`.
- Reuse: `llm.py` (Vertex, cost metering), `persona_vote.py`, `favs.py` / `favtaste.py`, `per_post.py`, `store.py`
  (spend table), `vm/submit.py` for VM jobs.
- Rules kept: Gemini on Vertex only, measured cost to the spend table, pilot ~20 items before any bigger job, ask
  before any job over $5, person-level data stays in the private bucket, aggregates only published.

## Verification

- Step 1 table: per-person AUC distribution per twin type vs baseline; the gate decides what goes further.
- Step 2 table: at-posting AUC / avg precision / Brier / calibration / winners-in-top-30 vs the 0.783 / 22% baseline,
  on Sep 1 - Oct 14 posts (44k), trained on Jul-Aug (62k).
- Live: `score_live.py` against settled lists from Nov 2.
- Spend: every Vertex call in the spend table; running total reported with results.
