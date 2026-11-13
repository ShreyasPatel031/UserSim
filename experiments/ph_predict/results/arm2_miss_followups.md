# Arm-2 miss follow-ups A-D (orchestrator 20:24Z Nov 13)

Same 214-day walk-forward as deployed arm 2 (60.7 / 68.4 / 75.7), paired 95% bootstrap over days; all days and last 107.

## A. Redacted makers share id "0" (data bug)
- 6,817 maker slots carry id "0" (33% of 2026 launches have at least one). Any join on maker id pooled them: hist_maker_n averaged 3,415 on those launches vs 0.3 otherwise.
- Deployed inputs: NOT affected. arm 2 and clean_nosite train on 40 inputs (TW.prep minus ID_COLS; list checked on the VM). ID_COLS already drops hist_maker_n / rel_max / top5,
  hist_dayrank_hist_maker_rel_max and the maker-profile inputs. Remaining maker-related inputs: ph_n_makers (total count incl. redacted, by design), ph_dayrank_ph_n_makers.
  busy_same_day / busy_7d group by hunter. No hunter placeholder ids.
- Affected but not model inputs: features.add_history (hist_maker_*), commenters.py (cm_maker_comm, cm_maker_comm_active30, cm_overlap*). The pre-Nov-12 model used hist_maker_*.
- Fixed in code (skip "0" / "" / None); no retrain change because none of these are inputs. Not deployed to the VM (pipeline code; no effect on published lines).

## B. Visible (non-redacted) maker count: leaky in training rows
- 00:05 reads vs final reads, same launch (16 days, 401 launches, Oct 25-Nov 12; visible_makers_check.py): visible count unchanged for 96.5% overall,
  but for the day's #1 it changes on 25% of days (+0.88 makers on average): the API names the winner's makers after the fact. Ranks 2-3 / 4-10 / 11+: 3% / 5% / 2% change, mean change ~0 or negative.
- Final reads (= every training row): #1 shows 3.96 visible makers vs 0.93 / 0.90 / 0.95 for ranks 2-3 / 4-10 / 11+, while total makers are 4.26 / 3.49 / 2.38 / 1.46.
  The "wrong picks 0.89 vs right picks 2.46" gap is mostly this leak.
- Redaction as observed: API v2 returns most makers with id "0" and no username; ~1 maker per launch is visible at 00:05; after the day closes the #1's makers are named.
- A leak-free test needs the count from 00:05 reads only; those exist for 16 days. At 00:05 the eventual #1 already had 1.94 visible vs ~1.0 for the rest (16 launches; too few to test).
  Not testable on 214 days. Recommendation: record it nightly (already in the 00:05 files) and test at ~60 days.

## C. Second-stage re-ranker on arm 2's top 10 (rerank_top10.py)
Month-forward ridge on earlier months' top-10 sets, target z(log votes) within the set; April keeps arm 2's order. Top 10 unchanged by construction.

| variant | days | top 3 | top 5 | diff top 3 | diff top 5 |
|---|---|---|---|---|---|
| score + first-time hunter (+ x score) + th_n_pre + pitch + brand>=2 | all | 60.3 | 69.5 | -0.5 [-2.2, +1.2] | +1.1 [-0.2, +2.3] |
| same | last 107 | 59.2 | 69.9 | +0.3 [-2.2, +2.8] | +2.6 [+0.6, +4.7] |
| + hunter history | all | 60.6 | 69.6 | -0.2 [-2.0, +1.9] | +1.2 [-0.2, +2.6] |
| + hunter history | last 107 | 59.8 | 69.7 | +0.9 [-2.2, +4.0] | +2.4 [+0.2, +4.5] |
| + self-hunted x first-time (LEAKY: self-hunted needs named makers) | all | 60.6 | 69.4 | -0.2 [-1.9, +1.4] | +1.0 [-0.3, +2.3] |

Does not qualify (top-3 interval spans 0). Last-month weights: arm-2 score 0.44, th_n_pre 0.22, brand>=2 0.09, pitch 0.06, first-time hunter 0.03 (+0.03 interaction):
once the arm-2 score is in, first-time hunter adds almost nothing. Self-hunted is in ID_COLS for the same leak as B (it needs the makers named).

## Side result: arm 2 with the 00:30 comment inputs inside (lc_comments run)
vs deployed arm 2: +3.1 [+0.9, +5.5] / +0.9 [-0.5, +2.3] / +0.7 [-0.1, +1.4] (last 107: +4.0 [+1.2, +7.2]). But at 00:30 the published line is mrep,
and vs mrep it is +0.8 [-1.6, +3.2] / -0.3 / +0.5: no deploy at 00:30.
