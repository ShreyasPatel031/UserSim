# 03:45 hybrid: out-of-sample check of the slots-6-10 ridge (12 days Nov 2-13, 03:00 recorder read, top 10)

Days: 5. Hidden rank alone 90.0; slots 6-10 by the 00:05 prior 72.0; LODO hybrid (alpha chosen inside each fold from [0.3, 1.0, 3.0, 10.0, 30.0]) 84.0; L2O hybrid (alpha 3, all 66 pairs) 84.5.
LODO hybrid - hidden: -6.0 [-14.0, +0.0]; L2O hybrid - hidden: -5.5 [-12.5, +0.0]; slots6-by-prior - hidden: -18.0 [-24.0, -12.0]; LODO hybrid - slots6-by-prior: +12.0 [+10.0, +16.0].
Permutation (slots-6+ labels shuffled within day, LODO refit, 200 draws): observed gain -6.00, permutation mean -4.72, 95th pct +0.00, one-sided p = 0.856.
Alphas chosen per fold: [0.3, 30.0] ([0.3, 30.0, 0.3, 0.3, 0.3]).
Per day (hidden / LODO / L2O / prior): 11-16 80/80/80/70; 11-17 100/90/90/80; 11-18 80/80/80/70; 11-19 90/90/90/70; 11-20 100/80/82/70
