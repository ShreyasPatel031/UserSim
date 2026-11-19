# 03:45 hybrid: out-of-sample check of the slots-6-10 ridge (12 days Nov 2-13, 03:00 recorder read, top 10)

Days: 3. Hidden rank alone 86.7; slots 6-10 by the 00:05 prior 73.3; LODO hybrid (alpha chosen inside each fold from [0.3, 1.0, 3.0, 10.0, 30.0]) 83.3; L2O hybrid (alpha 3, all 66 pairs) 83.3.
LODO hybrid - hidden: -3.3 [-10.0, +0.0]; L2O hybrid - hidden: -3.3 [-10.0, +0.0]; slots6-by-prior - hidden: -13.3 [-20.0, -10.0]; LODO hybrid - slots6-by-prior: +10.0 [+10.0, +10.0].
Permutation (slots-6+ labels shuffled within day, LODO refit, 200 draws): observed gain -3.33, permutation mean -3.30, 95th pct +0.00, one-sided p = 0.771.
Alphas chosen per fold: [0.3, 3.0, 30.0] ([30.0, 3.0, 0.3]).
Per day (hidden / LODO / L2O / prior): 11-16 80/80/80/70; 11-17 100/90/90/80; 11-18 80/80/80/70
