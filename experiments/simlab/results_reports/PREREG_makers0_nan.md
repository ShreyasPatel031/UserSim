# Pre-registration: arm 2 with ph_n_makers = 0 -> missing (orchestrator 23:44Z Nov 14), written before any run
Change: where the launch's maker list is empty (ph_n_makers == 0), set ph_n_makers = NaN and recompute ph_dayrank_ph_n_makers within the day
on non-missing launches only (pandas rank: the empty-list launch gets NaN). Everything else identical to arm 2 (deployed column set:
TW.prep cols minus ID_COLS / llm_site / ph_month; TW.P0 params; 5 seeds 0-4 averaged; rows sorted by (day, id); month-forward,
train = rows of earlier months from 2025-01-01).
Years: 2025 test months 2025-03..2025-12 (truth = dailyRank in the history data); then 2026 test months 2026-04..2026-10, scored ONCE
on results/web/truth_daily.json (first warehouse part after close, rank <= k, >= 10 ranked, unranked picks = misses).
Metric: top 3 / 5 / 10 hits, paired (fix - arm 2) per day, DAY-bootstrap 95% intervals (2000).
Also reported: n days, n launches, n launches with 0 makers, and for those launches the change in predicted within-day rank.
DECISION RULE: adopt for the next bundle if, in BOTH years, top 3, top 5 and top 10 are all "not worse beyond noise" = the lower end of
the 95% interval of (fix - arm 2) is above -1.0 points (removes a wrong reading at equal accuracy). If any of the six lower bounds is
<= -1.0, do not adopt. A clear gain (an interval entirely above 0 at top 3 in both years) qualifies for a deploy under the rule.
