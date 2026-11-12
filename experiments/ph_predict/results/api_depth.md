# Pre-reveal API rank: keeping depth (6 days, hourly reads; n = 6, no intervals)

## 1:00 PT read

| candidate | top 3 | top 5 | top 10 |
|---|---|---|---|
| api | 72.2 | 56.7 | 68.3 |
| floor5 | 72.2 | 56.7 | 71.7 |
| lm | 38.9 | 60.0 | 76.7 |
| slots_1 | 61.1 | 60.0 | 76.7 |
| slots_2 | 61.1 | 63.3 | 76.7 |
| slots_3 | 72.2 | 56.7 | 81.7 |
| slots_4 | 72.2 | 53.3 | 78.3 |
| slots_5 | 72.2 | 56.7 | 80.0 |
| vote3_eq | 73.3 | 72.0 | 76.0 |
| vote3_w | 66.7 | 72.0 | 78.0 |
| wmean_0.25 | 55.6 | 70.0 | 76.7 |
| wmean_0.5 | 66.7 | 66.7 | 78.3 |
| wmean_0.75 | 66.7 | 63.3 | 76.7 |

Leave-one-day-out choice (choose on 5 days, score the 6th):

| family | top 3 / 5 / 10 | picks per held-out day |
|---|---|---|
| slots (6 days) | 66.7 / 46.7 / 78.3 | slots_5, slots_3, slots_3, slots_5, slots_2, slots_3 |
| wmean (6 days) | 66.7 / 66.7 / 78.3 | wmean_0.5, wmean_0.5, wmean_0.5, wmean_0.5, wmean_0.5, wmean_0.5 |
| any (no ridge) (5 days) | 53.3 / 64.0 / 76.0 | wmean_0.5, wmean_0.5, slots_1, wmean_0.5, wmean_0.5 |
| any (with ridge, 5 days) (5 days) | 66.7 / 72.0 / 76.0 | vote3_eq, vote3_eq, vote3_eq, vote3_w, vote3_eq |

## 2:00 PT read

| candidate | top 3 | top 5 | top 10 |
|---|---|---|---|
| api | 66.7 | 70.0 | 80.0 |
| floor5 | 66.7 | 70.0 | 80.0 |
| lm | 38.9 | 60.0 | 76.7 |
| slots_1 | 61.1 | 60.0 | 76.7 |
| slots_2 | 66.7 | 66.7 | 76.7 |
| slots_3 | 66.7 | 60.0 | 78.3 |
| slots_4 | 66.7 | 70.0 | 81.7 |
| slots_5 | 66.7 | 70.0 | 81.7 |
| vote3_eq | 60.0 | 76.0 | 80.0 |
| vote3_w | 60.0 | 80.0 | 84.0 |
| wmean_0.25 | 61.1 | 70.0 | 81.7 |
| wmean_0.5 | 61.1 | 73.3 | 83.3 |
| wmean_0.75 | 72.2 | 76.7 | 80.0 |

Leave-one-day-out choice (choose on 5 days, score the 6th):

| family | top 3 / 5 / 10 | picks per held-out day |
|---|---|---|
| slots (6 days) | 61.1 / 53.3 / 78.3 | slots_5, slots_2, slots_4, slots_5, slots_2, slots_4 |
| wmean (6 days) | 72.2 / 76.7 / 80.0 | wmean_0.75, wmean_0.75, wmean_0.75, wmean_0.75, wmean_0.75, wmean_0.75 |
| any (no ridge) (5 days) | 66.7 / 72.0 / 78.0 | wmean_0.75, wmean_0.5, wmean_0.75, wmean_0.75, wmean_0.75 |
| any (with ridge, 5 days) (5 days) | 66.7 / 76.0 / 80.0 | wmean_0.75, vote3_w, wmean_0.75, wmean_0.75, wmean_0.75 |

## 3:00 PT read

| candidate | top 3 | top 5 | top 10 |
|---|---|---|---|
| api | 72.2 | 76.7 | 81.7 |
| floor5 | 72.2 | 76.7 | 83.3 |
| lm | 38.9 | 60.0 | 76.7 |
| slots_1 | 50.0 | 60.0 | 76.7 |
| slots_2 | 61.1 | 66.7 | 76.7 |
| slots_3 | 72.2 | 63.3 | 78.3 |
| slots_4 | 72.2 | 70.0 | 80.0 |
| slots_5 | 72.2 | 76.7 | 81.7 |
| vote3_eq | 60.0 | 72.0 | 80.0 |
| vote3_w | 73.3 | 76.0 | 84.0 |
| wmean_0.25 | 61.1 | 70.0 | 81.7 |
| wmean_0.5 | 77.8 | 70.0 | 85.0 |
| wmean_0.75 | 83.3 | 80.0 | 80.0 |

Leave-one-day-out choice (choose on 5 days, score the 6th):

| family | top 3 / 5 / 10 | picks per held-out day |
|---|---|---|
| slots (6 days) | 72.2 / 76.7 / 81.7 | slots_5, slots_5, slots_5, slots_5, slots_5, slots_5 |
| wmean (6 days) | 83.3 / 80.0 / 80.0 | wmean_0.75, wmean_0.75, wmean_0.75, wmean_0.75, wmean_0.75, wmean_0.75 |
| any (no ridge) (5 days) | 80.0 / 76.0 / 80.0 | wmean_0.5, wmean_0.75, wmean_0.75, wmean_0.75, wmean_0.75 |
| any (with ridge, 5 days) (5 days) | 80.0 / 76.0 / 80.0 | wmean_0.5, wmean_0.75, wmean_0.75, wmean_0.75, wmean_0.75 |

Per-day rows: results/api_depth.json (rows).
