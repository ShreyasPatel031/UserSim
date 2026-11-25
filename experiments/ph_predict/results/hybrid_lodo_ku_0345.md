# 03:45 hybrid: out-of-sample check of the slots-6-10 ridge (12 days Nov 2-13, 03:00 recorder read, top 10)

Days: 9. Hidden rank alone 85.6; slots 6-10 by the 00:05 prior 72.2; LODO hybrid (alpha chosen inside each fold from [0.3, 1.0, 3.0, 10.0, 30.0]) 84.4; L2O hybrid (alpha 3, all 66 pairs) 84.3.
LODO hybrid - hidden: -1.1 [-4.4, +2.2]; L2O hybrid - hidden: -1.2 [-4.9, +2.2]; slots6-by-prior - hidden: -13.3 [-20.0, -7.8]; LODO hybrid - slots6-by-prior: +12.2 [+7.8, +16.7].
Permutation (slots-6+ labels shuffled within day, LODO refit, 200 draws): observed gain -1.11, permutation mean -1.37, 95th pct +1.11, one-sided p = 0.627.
Alphas chosen per fold: [0.3] ([0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3]).
Per day (hidden / LODO / L2O / prior): 11-16 80/80/80/70; 11-17 100/90/90/80; 11-18 80/80/80/70; 11-19 90/90/90/70; 11-20 100/90/89/70; 11-21 80/80/80/70; 11-22 90/90/90/70; 11-23 80/80/80/80; 11-24 70/80/80/70
