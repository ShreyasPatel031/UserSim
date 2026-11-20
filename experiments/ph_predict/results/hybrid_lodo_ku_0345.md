# 03:45 hybrid: out-of-sample check of the slots-6-10 ridge (12 days Nov 2-13, 03:00 recorder read, top 10)

Days: 4. Hidden rank alone 87.5; slots 6-10 by the 00:05 prior 72.5; LODO hybrid (alpha chosen inside each fold from [0.3, 1.0, 3.0, 10.0, 30.0]) 82.5; L2O hybrid (alpha 3, all 66 pairs) 85.8.
LODO hybrid - hidden: -5.0 [-10.0, +0.0]; L2O hybrid - hidden: -1.7 [-7.5, +2.5]; slots6-by-prior - hidden: -15.0 [-20.0, -10.0]; LODO hybrid - slots6-by-prior: +10.0 [+10.0, +10.0].
Permutation (slots-6+ labels shuffled within day, LODO refit, 200 draws): observed gain -5.00, permutation mean -1.93, 95th pct +2.50, one-sided p = 0.955.
Alphas chosen per fold: [0.3, 30.0] ([0.3, 0.3, 0.3, 30.0]).
Per day (hidden / LODO / L2O / prior): 11-16 80/80/80/70; 11-17 100/90/90/80; 11-18 80/80/80/70; 11-19 90/80/93/70
