# 03:45 hybrid: out-of-sample check of the slots-6-10 ridge (12 days Nov 2-13, 03:00 recorder read, top 10)

Days: 8. Hidden rank alone 87.5; slots 6-10 by the 00:05 prior 72.5; LODO hybrid (alpha chosen inside each fold from [0.3, 1.0, 3.0, 10.0, 30.0]) 85.0; L2O hybrid (alpha 3, all 66 pairs) 84.6.
LODO hybrid - hidden: -2.5 [-6.2, +0.0]; L2O hybrid - hidden: -2.9 [-6.4, +0.0]; slots6-by-prior - hidden: -15.0 [-21.2, -8.8]; LODO hybrid - slots6-by-prior: +12.5 [+7.5, +16.2].
Permutation (slots-6+ labels shuffled within day, LODO refit, 200 draws): observed gain -2.50, permutation mean -3.02, 95th pct +0.00, one-sided p = 0.532.
Alphas chosen per fold: [0.3] ([0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3]).
Per day (hidden / LODO / L2O / prior): 11-16 80/80/80/70; 11-17 100/90/90/80; 11-18 80/80/80/70; 11-19 90/90/90/70; 11-20 100/90/87/70; 11-21 80/80/80/70; 11-22 90/90/90/70; 11-23 80/80/80/80
