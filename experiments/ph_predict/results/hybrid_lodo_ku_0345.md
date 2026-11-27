# 03:45 hybrid: out-of-sample check of the slots-6-10 ridge (12 days Nov 2-13, 03:00 recorder read, top 10)

Days: 11. Hidden rank alone 86.4; slots 6-10 by the 00:05 prior 69.1; LODO hybrid (alpha chosen inside each fold from [0.3, 1.0, 3.0, 10.0, 30.0]) 84.5; L2O hybrid (alpha 3, all 66 pairs) 84.5.
LODO hybrid - hidden: -1.8 [-5.5, +1.8]; L2O hybrid - hidden: -1.9 [-5.5, +1.8]; slots6-by-prior - hidden: -17.3 [-24.5, -10.0]; LODO hybrid - slots6-by-prior: +15.5 [+10.0, +20.9].
Permutation (slots-6+ labels shuffled within day, LODO refit, 200 draws): observed gain -1.82, permutation mean -2.90, 95th pct -0.91, one-sided p = 0.398.
Alphas chosen per fold: [0.3] ([0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3]).
Per day (hidden / LODO / L2O / prior): 11-16 80/80/80/70; 11-17 100/90/90/80; 11-18 80/80/80/70; 11-19 90/90/90/70; 11-20 100/90/89/70; 11-21 80/80/80/70; 11-22 90/90/90/70; 11-23 80/80/80/80; 11-24 70/80/80/70; 11-25 90/80/80/50; 11-26 90/90/90/60
