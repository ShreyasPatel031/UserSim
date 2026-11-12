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

## Reading

**Best leave-one-day-out recipe:** a weighted mean of rank positions, chosen on every held-out day.
- 01:00 read: w_api = 0.5 → 66.7 / 66.7 / 78.3, vs API alone 72.2 / 56.7 / 68.3 and LM 38.9 / 60.0 / 76.7.
- 02:00 read: w_api = 0.75 → 72.2 / 76.7 / 80.0.
- 03:00 read (also used at 04:00): w_api = 0.75 → 83.3 / 80.0 / 80.0.

It keeps top-10 at or above the LM, and keeps most of the API's top-3 gain from 02:00 on. The slot rules (top k from the API, the rest from the LM) are unstable leave-one-day-out, and the LM-top-5 floor changes little.

**Comment ridge as a third voter** (5 days): it helps top 5 at 01:00 (equal vote: 73.3 / 72.0 / 76.0) but not at 02:00 or 03:00, where the two-way API/LM mean is as good or better. Not adopted.

Note: the "any (no ridge)" family was scored on the 5 ridge days by a code slip; the per-family rows above it are the clean 6-day ones.

**Live:** from Nov 12 every P file carries pred_rank_best (w_api 0.5 at P1, 0.75 at P2–P4) next to the other ranks. It is scored forward, with the 6-day replay numbers shown as REPLAY in NORTH_STAR.md.

**Nov 8, the day the API rank loses** (Saturday, line-up of 17):
- Pre-reveal, the hourly API rank had launches 1306739 and 1302760 at #1 and #2 from 01:00 to 04:00. They finished #3 and #4.
- The eventual #1 (1298958, 288 votes) sat at #9–15 before the reveal, jumped to #4 at 05:00 and #2–3 by midday, and won late in the day.
- The eventual #2 (1301987) was #5–8 pre-reveal and #1 at 05:00.
- So two launches that built their votes after the reveal (morning US traffic) overtook the early-hours leaders. The LM, built on pre-launch facts, had them right.
- A weekend line-up is small and its early-hours voters are a thin, unrepresentative slice. That is when an early-vote order is least reliable, and why the blend keeps an LM weight.
