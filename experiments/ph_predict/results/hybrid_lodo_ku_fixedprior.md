# 03:45 hybrid: out-of-sample check of the slots-6-10 ridge (12 days Nov 2-13, 03:00 recorder read, top 10)
CLEAN_PRIOR = results/today_replay_fixed.parquet:clean_nosite; prior source per day: ['CLEAN_PRIOR results/today_replay_fixed.parquet:clean_nosite', 'month-fold clean_nosite stand-in']

Days: 12. Hidden rank alone 71.7; slots 6-10 by the 00:05 prior 75.0; LODO hybrid (alpha chosen inside each fold from [0.3, 1.0, 3.0, 10.0, 30.0]) 78.3; L2O hybrid (alpha 3, all 66 pairs) 78.3.
LODO hybrid - hidden: +6.7 [+1.7, +11.7]; L2O hybrid - hidden: +6.7 [+1.7, +11.5]; slots6-by-prior - hidden: +3.3 [-0.8, +7.5]; LODO hybrid - slots6-by-prior: +3.3 [-0.8, +7.5].
Permutation (slots-6+ labels shuffled within day, LODO refit, 200 draws): observed gain +6.67, permutation mean +3.57, 95th pct +5.83, one-sided p = 0.040.
Alphas chosen per fold: [0.3, 30.0] ([0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 30.0, 0.3, 0.3, 0.3, 0.3, 0.3]).
Per day (hidden / LODO / L2O / prior): 11-02 90/90/90/90; 11-03 90/100/99/90; 11-04 80/90/90/80; 11-05 70/90/90/80; 11-06 30/40/39/40; 11-07 70/60/60/70; 11-08 60/80/80/80; 11-09 80/90/90/80; 11-10 80/80/80/70; 11-11 80/90/90/80; 11-12 50/50/52/50; 11-13 80/80/80/90
