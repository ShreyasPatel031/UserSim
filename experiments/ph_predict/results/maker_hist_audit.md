# Audit: hist_maker_n ("maker has no earlier launch"), backtest build vs live 00:05 path

## How it is computed (features.add_history)
- Source: the stored day files (data/days/<d>.json; history_retrain.build adds the 2025 history). Each launch's maker ids
  come from its `makers` list; history = earlier days only (today's results are added after the whole day is featurised).
- hist_maker_n = sum over the launch's maker ids of each maker's earlier launches. Never NaN: no makers or no earlier launches -> 0.
- Placeholder makers: hidden makers come back as id "0" ([REDACTED]); features.py KEEPS "0", so every hidden maker is
  one pooled fake maker with thousands of "earlier launches" (hence the huge values, max 236,800 in the build).
  hist_maker_n == 0 therefore means "every maker is named AND new", and depends on whether the makers were named in the read.
- Backtest rows use the stored day file (read after close); the live 00:05 path uses data/today/<d>.json (read at 00:05).

## Same nights, Oct 25 - Nov 13 (17 nights, 421 launches with truth, 51 finished top 3)
| | top 3 | others |
|---|---|---|
| any placeholder maker at 00:05 | 68.6% | 27.6% |
| any placeholder maker in stored rows | 60.8% | 30.5% |
| placeholder at 00:05, named in stored rows | 9.8% | 0.3% |
| hist_maker_n == 0 at 00:05 | 23.5% | 59.7% |
| hist_maker_n == 0 in stored rows | 33.3% | 56.8% |
| hist_maker_n differs, stored vs 00:05 | 19.6% | 5.7% |
| maker count differs, stored vs 00:05 | 7.8% | 4.1% |
| mean extra makers in stored rows | +0.14 | +0.05 |

Winners' makers are named after close far more often (9.8% vs 0.3%): the same leak as the earlier visible-maker count.
Stored rows make winners look like "first-time makers" more often (33% vs 23.5% at 00:05).

## Effect on the published model
Arm 2 (h25_live / forecast.py clean_nosite) drops every hist_maker*, ph_maker*, x_maker*, hist_dayrank_hist_maker* input
and the ID set (ph_n_makers_new, ph_maker_has_headline, x_any_verified, ph_self_hunted) in training and serving; cols.json
confirms none is an arm-2 input. So the hist_maker_n fill does not change the published order and there is no arm-2 delta to
report. Still leaking into arm 2: the kept total maker count (ph_n_makers, ph_dayrank_ph_n_makers), which stored rows raise
for winners (+0.14 vs +0.05). Fix candidate: drop or freeze ph_n_makers to the 00:05 value (needs 00:05 reads for training rows,
held only from Oct 25) - a separate retrain test.

## Correction to shaky1
The shaky flag used "first" (hist_maker_n == 0) and "self_hunted": both need named makers. Refit without them
(shaky1_nomaker.json): 2026 test swap - arm 2 = +0.5 [-3.8, +4.9] (was +1.6 [-4.3, +7.6]); demote -3.1 [-4.7, -1.4]. Verdict unchanged: no swap.
