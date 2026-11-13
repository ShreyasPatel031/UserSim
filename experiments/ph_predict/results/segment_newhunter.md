# Segment model: new-hunter launches (214 days Apr-Oct; segment 56.8% of launches, 15.5% of top 3, 34.2% of top 10; LightGBM, 5 seeds, LODO)

## (a) within-segment AUC (pooled test-day segment launches)

| score | AUC final top 10 | AUC final top 3 |
|---|---|---|
| clean_nosite | 0.812 | 0.886 |
| clean + th_n_pre (base) | 0.640 | 0.775 |
| segment model (target top 10) | 0.838 | 0.873 |
| segment model (target top 3) | 0.814 | 0.888 |

Within-day AUC (mean over days with both classes in the segment): base top10 0.718 (n 178) top3 0.775 (n 83); seg10 top10 0.700 (n 178) top3 0.812 (n 83); seg3 top10 0.695 (n 178) top3 0.770 (n 83)

## (b) plug-in: z(base) + w * z(segment logit) on segment launches; w tuned on Apr-Jul, confirmed on Aug-Oct

| target | w (tuned) | tune: base t3/t5/t10 -> blend | confirm: base t3/t5/t10 | confirm: blend t3/t5/t10 | confirm diff (95%) | new-hunter top-3 winners caught (confirm) |
|---|---|---|---|---|---|---|
| seg10 | 0.1 | 61.5/68.5/73.9 -> 62.0/69.2/74.1 | 58.0/68.9/77.1 | 58.3/68.5/76.6 | +0.4 [+0.0, +1.1] / -0.4 [-1.5, +0.7] / -0.4 [-1.1, +0.2] | 6 -> 8 of 41 |
| seg10 all w (tune days, t3/t5/t10) | 0.0: 61.5/68.5/73.9; 0.1: 62.0/69.2/74.1; 0.2: 62.0/68.9/73.8; 0.3: 61.7/68.2/73.7; 0.5: 59.6/67.7/73.4; 0.75: 58.2/66.1/73.4; 1.0: 55.7/64.3/72.9 | | | | | |
| seg3 | 0.2 | 61.5/68.5/73.9 -> 61.7/68.7/74.1 | 58.0/68.9/77.1 | 58.3/69.6/76.3 | +0.4 [+0.0, +1.1] / +0.7 [-0.7, +2.0] / -0.8 [-1.7, +0.2] | 6 -> 10 of 41 |
| seg3 all w (tune days, t3/t5/t10) | 0.0: 61.5/68.5/73.9; 0.1: 61.7/68.5/73.9; 0.2: 61.7/68.7/74.1; 0.3: 61.5/68.0/73.9; 0.5: 60.9/66.7/73.6; 0.75: 58.2/66.7/73.0; 1.0: 54.9/64.8/72.1 | | | | | |

Calibration: new-hunter top-3 winners' position in the base ranking: median 7, share at 4-10 64.6%, share beyond 10 23.2% (n 99)
