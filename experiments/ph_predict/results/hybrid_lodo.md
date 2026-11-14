# 03:45 hybrid: out-of-sample check of the slots-6-10 ridge (12 days Nov 2-13, 03:00 recorder read, top 10)

Days: 12. Hidden rank alone 73.3; slots 6-10 by the 00:05 prior 74.2; LODO hybrid (alpha chosen inside each fold from [0.3, 1.0, 3.0, 10.0, 30.0]) 77.5; L2O hybrid (alpha 3, all 66 pairs) 77.5.
LODO hybrid - hidden: +4.2 [+0.0, +8.3]; L2O hybrid - hidden: +4.2 [+0.0, +8.4]; slots6-by-prior - hidden: +0.8 [-4.2, +5.8]; LODO hybrid - slots6-by-prior: +3.3 [-0.8, +7.5].
Permutation (slots-6+ labels shuffled within day, LODO refit, 200 draws): observed gain +4.17, permutation mean +1.33, 95th pct +3.37, one-sided p = 0.055.
Alphas chosen per fold: [0.3, 10.0, 30.0] ([0.3, 0.3, 0.3, 30.0, 0.3, 0.3, 30.0, 30.0, 10.0, 0.3, 30.0, 0.3]).
Per day (hidden / LODO / L2O / prior): 11-02 90/90/90/90; 11-03 90/90/90/90; 11-04 90/90/90/90; 11-05 80/90/90/80; 11-06 30/40/39/40; 11-07 70/60/60/70; 11-08 60/80/80/80; 11-09 80/90/90/80; 11-10 80/80/80/60; 11-11 80/90/90/80; 11-12 50/50/51/50; 11-13 80/80/80/80
