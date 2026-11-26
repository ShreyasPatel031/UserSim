# 03:45 hybrid: out-of-sample check of the slots-6-10 ridge (12 days Nov 2-13, 03:00 recorder read, top 10)

Days: 10. Hidden rank alone 86.0; slots 6-10 by the 00:05 prior 70.0; LODO hybrid (alpha chosen inside each fold from [0.3, 1.0, 3.0, 10.0, 30.0]) 84.0; L2O hybrid (alpha 3, all 66 pairs) 83.9.
LODO hybrid - hidden: -2.0 [-6.0, +2.0]; L2O hybrid - hidden: -2.1 [-6.1, +2.0]; slots6-by-prior - hidden: -16.0 [-24.0, -9.0]; LODO hybrid - slots6-by-prior: +14.0 [+9.0, +19.0].
Permutation (slots-6+ labels shuffled within day, LODO refit, 200 draws): observed gain -2.00, permutation mean -2.33, 95th pct -0.95, one-sided p = 0.547.
Alphas chosen per fold: [0.3] ([0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3]).
Per day (hidden / LODO / L2O / prior): 11-16 80/80/80/70; 11-17 100/90/90/80; 11-18 80/80/80/70; 11-19 90/90/90/70; 11-20 100/90/89/70; 11-21 80/80/80/70; 11-22 90/90/90/70; 11-23 80/80/80/80; 11-24 70/80/80/70; 11-25 90/80/80/50
