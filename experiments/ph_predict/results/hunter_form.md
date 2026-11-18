# Hunter-history FORM inside arm 2 (orchestrator 15:21Z Nov 14; held data; CLOSED, no gain)

Not run before (research log): E5's first-time-hunter score (Nov 13, no increment), E5's team track record (Nov 13, coverage gate, no
test), E5's false-favourites second stage (Nov 12, existing hunter inputs, null). New here: the form of the hunter record.
Features (hunter_form.py, as-of days <= d-2, 11,968 launches, 43.5% with an earlier hunt; min days since last hunt = 2): last hunt (days
since, rank, log-votes, rel), trend over the last 3, best rank and top-3/top-10 counts, record within the launch's topics, same weekday,
short-list-day share, empirical-Bayes shrunk hunter effect. Not built (not held as-of): hunter-is-maker (maker ids redacted), line-up position.
Selection on 2025 only (hunter_select.py; month-forward Mar-Dec 2025, 204 days >= 10 ranked, 5 seeds), top 3 / 5 / 10:
base 52.8 / 61.7 / 79.3; all 52.8 / 62.3 / 79.2; eb 52.8 / 62.2 / 79.1; last_trend 51.5 / 61.9 / 79.1; record 51.5 / 61.4 / 79.3;
context 53.4 / 61.4 / 79.1 -> chosen: context (hf_topic_rel, hf_topic_n, hf_wd_rel, hf_wd_n, hf_short_share).
Single pre-registered test on 2026 (JOINT harness, block on 2025 + 2026 rows, 10 seeds pooled, baseline = arm 2 with the same 10 seeds):

| cut | arm 2 | + hunter context | diff top 3 / 5 / 10 |
|---|---|---|---|
| >= 10 ranked, 183 d (PRIMARY top 3) | 57.7 / 65.2 / 76.8 | 57.0 / 64.9 / 76.9 | -0.7 [-2.4, +0.9] / -0.3 [-1.4, +0.8] / +0.1 [-0.5, +0.7] |
| all 214 | 60.6 / 68.3 / 75.7 | 59.7 / 68.0 / 75.7 | -0.9 [-2.5, +0.6] / -0.3 / +0.0 |
| last 90 of 183 | 58.1 / 66.7 / 77.7 | 56.7 / 66.0 / 77.7 | -1.5 [-3.7, +0.4] / -0.7 / +0.0 |

Decision (rule 5): no gain; closed. On 2025 no group beat the base by more than +0.7 top 3 either: arm 2's existing hunter inputs
(hist_hunter_n / rel / top5 + percentile) already carry what the form adds.
