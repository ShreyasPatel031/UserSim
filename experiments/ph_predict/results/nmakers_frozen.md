# How much the ph_n_makers leak inflates arm 2 (nmakers_frozen.py @ 77210e44)

The same trained arm-2 models (month-forward, 5 seeds) score the test rows twice: with the stored ph_n_makers and its day rank
(as in the backtest), and with the 00:05 values (len(makers) in data/today; day rank recomputed within the day).
Nights with a 00:05 read and truth: 17 (Oct 25 - Nov 13; there are no 00:05 files for Nov 5-7). 421 launches have a 00:05 read;
the maker count differs on 19 of them.

| | top 3 | top 5 | top 10 |
|---|---|---|---|
| stored | 58.8 | 69.4 | 74.1 |
| 00:05 values | 56.9 | 68.2 | 74.1 |
| frozen - stored [95%] | -2.0 [-5.9, 0.0] | -1.2 [-3.5, 0.0] | 0.0 [0.0, 0.0] |

The whole difference comes from one night (Nov 12: stored 1/3, 2/5, 2/5 vs 00:05 0/3, 1/5, 2/5). The inflation is not clear of noise,
so no corrected headline is stated; the published backtest stands, with this caveat.
Forward shadow: the 00:05-frozen line is re-scored nightly at 13:23 PT by a scheduled task in the PH ops session (read-only VM run,
no pipeline change); results/nmakers_frozen.json.
