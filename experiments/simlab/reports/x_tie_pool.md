# Pre-launch X ties as a person-model input (Nov 2, 2026; Grok Bot, on the covered October launches)

Code: `simlab/x_tie_pool.py`; data `reports/x_tie_pool.json` (counts and rates only). Runs without a VM.

**Question.** A pool person is X-tied to a launch if their X account replied to or quoted one of the team's posts, with
the reply / quote dated before 00:00 PT on launch day (posts from the 30 days before; reposts have no time and are
dropped). Does that tie (1) predict the person's vote, and (2) make the simulated pool's votes more accurate?
**Rule fixed before the run:** (2) counts if the within-day Spearman gain against the real pool votes has a 95%
interval above 0. The pool simulation is `pna_` (page-free, all earlier months); the X-tied conversion rate is fitted
forward only, on earlier covered days.

**Coverage** (gate `raw/x/prelaunch_wip/dm_gate.json`, Oct 1–25): 71 covered launches; 16 of them have X-tied pool people
(190 in all, about 12 per launch).

| Person level (16 launches) | Value |
|---|---|
| X-tied people's vote rate on their launch | 22.5% [8.6, 39.5] |
| Same people on the same day's other launches | 1.65% [0.73, 2.75] |
| Difference | **+20.9 points [+6.7, +38.0]** (rate ratio 13.7) |

| Pool level (8 days with ≥ 3 covered launches, 65 launches) | Simulation | + X-tied people × forward rate | Gain |
|---|---|---|---|
| Within-day Spearman with real pool votes | 0.307 [−0.175, 0.734] | 0.307 [−0.171, 0.733] | 0.000 [0.000, 0.000] |
| Pool top 3 | 79.2 | 79.2 | 0.0 |
| Final top 3 among covered launches | 87.5 | 87.5 | 0.0 |

Forward-fitted conversion of X-tied people: 1.6% (Oct 7) rising to 10.1% (Oct 24) as covered days accumulate.

**Verdict.** The tie is real at person level: an X-tied pool person is about 14× likelier to vote for that launch. It
does not change the simulated pool's ranking: about 12 tied people per launch at a few percent conversion add about one
expected vote, against tens from the rest of the pool. By the rule it does not improve the pool simulation at today's
coverage. Its value, if any, is outside the pool: the X engagers who are not Product Hunt pool people (the launch-level
test in `x_prelaunch_e1.py`, which waits for 10 full days).
