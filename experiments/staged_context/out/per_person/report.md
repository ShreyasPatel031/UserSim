# Per-person pilot: predicting one reviewer's ease-of-use rating (new-product framing)

90 Capterra reviewers of Freshsales, Zoho CRM and Pipedrive (30 each, balanced 30/30/30 across ratings 1-3 / 4 / 5).
Each prediction sees the reviewer's role, industry, company size, time using the product and a neutral task;
no target-product reviews are ever shown. One replicate, gemini-2.5-flash (thinking budget 1024).
Ratings are taken from the data, so no judge is involved.

| Setup | Error (MAE) ↓ | Ranks people (Spearman) ↑ | Spots unhappy (AUC, ≤3) ↑ | Avg guess (real 3.88) |
| --- | --- | --- | --- | --- |
| P0 name only | 0.995 | 0.02 | 0.53 | 3.41 |
| P1 + website | 0.915 | 0.06 | 0.55 | 3.52 |
| P2 + website + O*NET | 0.941 | 0.05 | 0.57 | 3.50 |
| P3 + website + O*NET + competitor reviews | 0.912 | 0.07 | 0.56 | 3.55 |
| P4 + website + competitor reviews | 0.920 | 0.09 | 0.57 | 3.56 |
| No AI: always 5 | 1.122 | — | 0.50 | 5.00 |
| No AI: competitor-review average | 0.944 | — | 0.50 | 4.47 |
| **No AI: attribute averages from 63 other products** | **0.913** | **0.30** | **0.71** | 4.44 |

- Adding data cut error vs P0 by 0.05-0.08 (paired bootstrap CIs exclude 0), mostly by nudging the average guess up
  toward the truth, not by telling people apart.
- No AI setup ranked reviewers meaningfully (Spearman ≤ 0.09; per product it flips sign).
- The no-AI attribute model ranks people consistently across all three products (Spearman 0.22-0.37, AUC 0.71-0.72),
  mostly via tenure: longer users rate higher. The AI's guess is flat across tenure.
- Caveats: 90 people, one replicate; balanced sampling means MAE is not comparable with the natural-distribution runs.
