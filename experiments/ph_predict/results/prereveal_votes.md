# Per-launch vote estimates at 03:45 PT vs the current rank-slot method (prereveal_votes.py @ db42c357)

Data: 12 days (Nov 2 - Nov 13) with a 03:45 recorder read, 378 launches. 184 launches have a weekly-rank bracket (posts_ts days,
not Mondays); 375 have votes at the 04:00 reveal. Methods: B0 = current (00:05 expected votes sorted, handed out by hidden slot);
M1 = LODO ridge on log hidden position, log comments, 00:05 prior, weekly bracket; Mw = weekly bracket where present, else B0.
80% range from each method's own LODO log errors. Means over days; paired vs B0, day bootstrap 95%.

| truth | method | median abs % error | within-day Spearman | inside range |
|---|---|---|---|---|
| final votes | B0 (current) | 16.5 | 0.810 | 77.5% |
| final votes | M1 | 14.1 | 0.834 | 78.1% |
| final votes | Mw | 27.2 | 0.790 | 76.3% |
| reveal votes | B0 (current) | 37.5 | 0.940 | 78.3% |
| reveal votes | M1 | 39.9 | 0.890 | 80.8% |
| reveal votes | Mw | 25.2 | 0.922 | 74.0% |

Paired vs B0:
- final, M1: error -2.4 [-4.7, +0.3], Spearman +0.024 [-0.012, +0.074], in range +0.6 [-3.1, +4.8]
- final, Mw: error +10.7 [+3.5, +18.6] (worse)
- reveal, M1: error +2.3 [-2.9, +7.8], Spearman -0.050 [-0.079, -0.027] (worse)
- reveal, Mw: error -12.4 [-22.7, -2.5] (better at the reveal, worse on final)

PRIMARY (M1 - B0, error vs final): -2.4 [-4.7, +0.3], not clear of 0, so M1 does not win and no writer change is staged.
All-days M1 fit: log pos -0.30, log comments +0.11, prior +0.39, weekly bracket ~0 (it measures 03:45-level votes, not final ones).

Why the 03:45 votes "do not change": the writer keeps the 00:05 vote levels and only re-orders the names by the hidden 03:45 order,
so slot k always shows the k-th 00:05 level. The hidden order is already the best 03:45 ranking (Spearman 0.94 with the reveal).
Using the per-launch fit instead would change each number but would not make them measurably closer to the final votes.
Suggested site label: "Vote figures at 03:45 are the 00:05 model's levels placed in today's hidden order; typically within 17% of the
final count, with about 4 in 5 launches inside the shown range."
