# Pre-reveal API rank: keeping depth (7 days, hourly reads; n = 7, no intervals)

## 1:00 PT read

| candidate | top 3 | top 5 | top 10 |
|---|---|---|---|
| api | 71.4 | 57.1 | 70.0 |
| floor5 | 71.4 | 57.1 | 75.7 |
| lm | 47.6 | 60.0 | 77.1 |
| slots_1 | 66.7 | 60.0 | 77.1 |
| slots_2 | 66.7 | 62.9 | 77.1 |
| slots_3 | 71.4 | 57.1 | 81.4 |
| slots_4 | 71.4 | 54.3 | 78.6 |
| slots_5 | 71.4 | 57.1 | 80.0 |
| vote3_eq | 73.3 | 72.0 | 76.0 |
| vote3_w | 66.7 | 72.0 | 78.0 |
| wmean_0.25 | 61.9 | 71.4 | 78.6 |
| wmean_0.5 | 71.4 | 68.6 | 78.6 |
| wmean_0.75 | 71.4 | 62.9 | 77.1 |

Leave-one-day-out choice (choose on 5 days, score the 6th):

| family | top 3 / 5 / 10 | picks per held-out day |
|---|---|---|
| slots (7 days) | 57.1 / 48.6 / 77.1 | slots_5, slots_2, slots_1, slots_5, slots_2, slots_3, slots_3 |
| wmean (7 days) | 71.4 / 68.6 / 78.6 | wmean_0.5, wmean_0.5, wmean_0.5, wmean_0.5, wmean_0.5, wmean_0.5, wmean_0.5 |
| any (no ridge) (5 days) | 53.3 / 64.0 / 76.0 | wmean_0.5, wmean_0.5, slots_1, wmean_0.5, wmean_0.5 |
| any (with ridge, 5 days) (5 days) | 66.7 / 72.0 / 76.0 | vote3_eq, vote3_eq, vote3_eq, vote3_w, vote3_eq |

## 2:00 PT read

| candidate | top 3 | top 5 | top 10 |
|---|---|---|---|
| api | 71.4 | 68.6 | 78.6 |
| floor5 | 71.4 | 68.6 | 81.4 |
| lm | 47.6 | 60.0 | 77.1 |
| slots_1 | 66.7 | 60.0 | 77.1 |
| slots_2 | 71.4 | 65.7 | 77.1 |
| slots_3 | 71.4 | 60.0 | 78.6 |
| slots_4 | 71.4 | 68.6 | 81.4 |
| slots_5 | 71.4 | 68.6 | 81.4 |
| vote3_eq | 60.0 | 76.0 | 80.0 |
| vote3_w | 60.0 | 80.0 | 84.0 |
| wmean_0.25 | 66.7 | 71.4 | 82.9 |
| wmean_0.5 | 66.7 | 74.3 | 82.9 |
| wmean_0.75 | 76.2 | 77.1 | 80.0 |

Leave-one-day-out choice (choose on 5 days, score the 6th):

| family | top 3 / 5 / 10 | picks per held-out day |
|---|---|---|
| slots (7 days) | 66.7 / 54.3 / 78.6 | slots_5, slots_2, slots_4, slots_5, slots_2, slots_4, slots_4 |
| wmean (7 days) | 76.2 / 77.1 / 80.0 | wmean_0.75, wmean_0.75, wmean_0.75, wmean_0.75, wmean_0.75, wmean_0.75, wmean_0.75 |
| any (no ridge) (5 days) | 66.7 / 72.0 / 78.0 | wmean_0.75, wmean_0.5, wmean_0.75, wmean_0.75, wmean_0.75 |
| any (with ridge, 5 days) (5 days) | 66.7 / 76.0 / 80.0 | wmean_0.75, vote3_w, wmean_0.75, wmean_0.75, wmean_0.75 |

## 3:00 PT read

| candidate | top 3 | top 5 | top 10 |
|---|---|---|---|
| api | 76.2 | 77.1 | 81.4 |
| floor5 | 76.2 | 77.1 | 85.7 |
| lm | 47.6 | 60.0 | 77.1 |
| slots_1 | 57.1 | 60.0 | 77.1 |
| slots_2 | 66.7 | 65.7 | 77.1 |
| slots_3 | 76.2 | 62.9 | 78.6 |
| slots_4 | 76.2 | 68.6 | 80.0 |
| slots_5 | 76.2 | 77.1 | 81.4 |
| vote3_eq | 60.0 | 72.0 | 80.0 |
| vote3_w | 73.3 | 76.0 | 84.0 |
| wmean_0.25 | 66.7 | 68.6 | 82.9 |
| wmean_0.5 | 81.0 | 71.4 | 85.7 |
| wmean_0.75 | 85.7 | 80.0 | 81.4 |

Leave-one-day-out choice (choose on 5 days, score the 6th):

| family | top 3 / 5 / 10 | picks per held-out day |
|---|---|---|
| slots (7 days) | 76.2 / 77.1 / 81.4 | slots_5, slots_5, slots_5, slots_5, slots_5, slots_5, slots_5 |
| wmean (7 days) | 85.7 / 80.0 / 81.4 | wmean_0.75, wmean_0.75, wmean_0.75, wmean_0.75, wmean_0.75, wmean_0.75, wmean_0.75 |
| any (no ridge) (5 days) | 80.0 / 76.0 / 80.0 | wmean_0.5, wmean_0.75, wmean_0.75, wmean_0.75, wmean_0.75 |
| any (with ridge, 5 days) (5 days) | 80.0 / 76.0 / 80.0 | wmean_0.5, wmean_0.75, wmean_0.75, wmean_0.75, wmean_0.75 |

## 4:00 PT read

| candidate | top 3 | top 5 | top 10 |
|---|---|---|---|
| api | 76.2 | 77.1 | 81.4 |
| floor5 | 76.2 | 77.1 | 85.7 |
| lm | 47.6 | 60.0 | 77.1 |
| slots_1 | 57.1 | 60.0 | 77.1 |
| slots_2 | 66.7 | 65.7 | 77.1 |
| slots_3 | 76.2 | 62.9 | 78.6 |
| slots_4 | 76.2 | 68.6 | 80.0 |
| slots_5 | 76.2 | 77.1 | 81.4 |
| vote3_eq | 66.7 | 73.3 | 83.3 |
| vote3_w | 77.8 | 76.7 | 85.0 |
| wmean_0.25 | 66.7 | 68.6 | 82.9 |
| wmean_0.5 | 81.0 | 71.4 | 85.7 |
| wmean_0.75 | 85.7 | 80.0 | 81.4 |

Leave-one-day-out choice (choose on 5 days, score the 6th):

| family | top 3 / 5 / 10 | picks per held-out day |
|---|---|---|
| slots (7 days) | 76.2 / 77.1 / 81.4 | slots_5, slots_5, slots_5, slots_5, slots_5, slots_5, slots_5 |
| wmean (7 days) | 85.7 / 80.0 / 81.4 | wmean_0.75, wmean_0.75, wmean_0.75, wmean_0.75, wmean_0.75, wmean_0.75, wmean_0.75 |
| any (no ridge) (6 days) | 83.3 / 76.7 / 81.7 | wmean_0.5, wmean_0.75, wmean_0.75, wmean_0.75, wmean_0.75, wmean_0.75 |
| any (with ridge, 5 days) (6 days) | 83.3 / 76.7 / 81.7 | wmean_0.5, wmean_0.75, wmean_0.75, wmean_0.75, wmean_0.75, wmean_0.75 |

Per-day rows: results/api_depth.json (rows).
