# Arm 3 vs simple public baselines (go/no-go for a public forecast record)

Run 2026-11-19/20 by an orchestrator subagent. Script: `bench.py`. Outputs:
- `result.json`
- `per_day_backtest.jsonl`
- `per_day_live.jsonl`
- `llm_cache/` (ids and scores only)

Arm 3 uses the frozen predictions parquet (ph-ops-agent c3a9f91c), 20 seeds, warehouse truth. It was not refit.

## Decision rule, fixed before the run
GO only if arm 3 beats every available baseline by at least 5 top-3 points, with the interval clear of zero.

## Backtest: 2026 Apr–Oct, n = 183 days
May 10 has no truth. Arm 3 scores 56.3 / 66.3 / 77.6 (daily top 3 / 5 / 10).

| Baseline | Its score (top 3 / 5 / 10) | Arm 3 lead, top 3 [95% CI] | Arm 3 lead, top 5 | Arm 3 lead, top 10 |
|---|---|---|---|---|
| B2: track record (hunter + last-listed maker, earlier days only) | 39.7 / 56.2 / 71.7 | +16.6 [+12.0, +21.1] | +10.2 | +5.9 |
| B4: Gemini, from name + tagline only (~$0.47) | 20.8 / 33.9 / 55.5 | +35.5 [+31.0, +39.9] | +32.5 | +22.1 |
| Random order | 14.3 / 23.8 / 47.5 | +42.0 | | |

Two baselines could not be scored on backtest days:
- B1, Product Hunt's 00:05 order: reads start Nov 2.
- B3, followers: no dated counts on backtest days.

**Verdict: GO, but only against B2 and B4.**

## Live nights: n = 13 (Nov 3–18)
The published line was a different model on most of these nights; arm 3 ran only from Nov 17. Top-3 lead of the published line:

| Over | Lead [95% CI] |
|---|---|
| B1 (near random at 00:05) | +35.9 [+23.1, +48.7] |
| B3 | +23.1 [+5.1, +38.5] |
| B2 | +10.3 [−7.7, +30.8], not clear of zero |

## 03:45 PT, Product Hunt's hidden order (API `dailyRank`) vs B1: n = 10
Top 3: 76.7 vs 13.3, a lead of +63.3 [+46.7, +80.0].

Product Hunt's own pre-reveal ranking beats every midnight forecast, arm 3 included.

## Leaks avoided
- B2 uses only the hunter and the last-listed maker, because makers are named after the day closes. Using all makers changes top 3 by only +1.1.
- Track record uses only earlier days.
- B3 uses only follower reads at or before 00:15 PT.
- The hidden-window order comes from `dailyRank`, not the list position.
- Gemini flagged 0.03% of launches as known.

## Caveats
- Arm 3's backtest uses re-read data, which reads about 3.5 top-3 points high.
- The baselines that could be scored are weak.

The defensible claim is "beats the track record baseline by about 16 top-3 points over 183 days". It is not "beats Product Hunt".
