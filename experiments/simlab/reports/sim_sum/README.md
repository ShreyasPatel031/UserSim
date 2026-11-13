# Summed LLM person-simulation as a launch signal (orchestrator 04:41Z Nov 13): null, no shadow line

Script: sim_sum.py, using the fixed prompt in pilot/prompts.json.

**Setup.**
- 14 days, Oct 26 – Nov 11; 354 launches with a clean_v3_nosite score.
- Per day, 1,000 complete people sampled in proportion to their upvotes in the prior 30 days. Sampling does not condition on voting that day.
- That gives 14,000 cards (12,891 valid answers) from gemini-2.5-flash-lite.
- Cost $2.53; median latency 1.0 s.

**Leak checks.**
- 0 of 14,000 cards contain an upvote dated on or after the day.
- The line-up and history show names and taglines only.
- Caveats: upvote dates are the upvoted launch's day, and follows are undated snapshots taken Nov 10.

**Results.** Leave-day-out on top of clean_v3_nosite. Clean scores 64.3 / 70.0 / 76.4 on top 3/5/10. The table shows 1,000 people; 100 and 300 give the same numbers to within ±0.02.

| score | gain top 3 / 5 / 10 | within-day Spearman (clean 0.61) | partial beyond clean |
|---|---|---|---|
| SUM of p | −2.4 [−9.5, +4.8] / −1.4 [−4.3, 0.0] / 0.0 [−2.9, +2.9] | 0.40 [0.31, 0.50] | +0.15 [+0.04, +0.27] |
| SUM over non-followers | 0.0 [0.0, 0.0] / +1.4 [0.0, +4.3] / −0.7 [−2.1, 0.0] | −0.06 | −0.04 [−0.17, +0.09] |
| mean within-person rank | −2.4 / −1.4 / −0.7 | 0.39 | +0.13 [+0.04, +0.24] |

**Why the partial correlation is not a simulation signal:**
1. It does not grow with the number of people: 100, 300 and 1,000 give the same values.
2. It vanishes once people who follow the team are removed: −0.04.
3. The raw count of sampled people who follow the team, with no LLM, has a partial of **+0.44 [+0.33, +0.55]** beyond clean. That is three times the LLM sum.

So the LLM mostly re-reads the [follows team] flag. Follows are a Nov 10 snapshot, and people often follow a maker after upvoting, so the follow count is itself likely leaky at 00:05. It needs dated follows before it can be used.

**Verdict.** No top-k gain. The person-simulation signal is explained by follows, so no shadow line.
