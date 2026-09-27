## Per pair and per product study (2 rival pairs x 6 personas x both orders; planner excluded)

Token counts are measured on gemini-2.5-flash (thinking off, 2 images/call at ~258 tokens each). 'as measured' re-prices the same tokens; '+adj' adds 500 thinking tokens/call for models that cannot turn thinking off, and Gemini 3 default image tokens (1120/image instead of 258).

| arm | calls/pair | in/pair | out/pair | model | $/pair as measured | $/pair +adj | $/study as measured | $/study +adj | $/study +adj, batch/flex |
|---|---|---|---|---|---|---|---|---|---|
| S2strict | 14.0 | 12,349 | 1,565 | gemini-2.5-flash | 0.0076 | 0.0076 | 0.015 | 0.015 | 0.008 |
| S2strict | 14.0 | 12,349 | 1,565 | gemini-2.5-pro | 0.0311 | 0.1011 | 0.062 | 0.202 | 0.101 |
| S2strict | 14.0 | 12,349 | 1,565 | gemini-3.8-flash intro (to 2026-12-31) | 0.0151 | 0.0595 | 0.030 | 0.119 | 0.059 |
| S2strict | 14.0 | 12,349 | 1,565 | gemini-3.8-flash (from 2027-01-01) | 0.0303 | 0.1190 | 0.061 | 0.238 | 0.119 |
| S2strict | 14.0 | 12,349 | 1,565 | gemini-3.1-pro-preview | 0.0435 | 0.1757 | 0.087 | 0.351 | 0.176 |
| GFOCUS | 10.0 | 10,892 | 3,205 | gemini-2.5-flash | 0.0113 | 0.0113 | 0.023 | 0.023 | 0.011 |
| GFOCUS | 10.0 | 10,892 | 3,205 | gemini-2.5-pro | 0.0457 | 0.0958 | 0.091 | 0.192 | 0.096 |
| GFOCUS | 10.0 | 10,892 | 3,205 | gemini-3.8-flash intro (to 2026-12-31) | 0.0202 | 0.0519 | 0.040 | 0.104 | 0.052 |
| GFOCUS | 10.0 | 10,892 | 3,205 | gemini-3.8-flash (from 2027-01-01) | 0.0404 | 0.1039 | 0.081 | 0.208 | 0.104 |
| GFOCUS | 10.0 | 10,892 | 3,205 | gemini-3.1-pro-preview | 0.0602 | 0.1550 | 0.120 | 0.310 | 0.155 |
| GFOCUS_personas | 40.1 | 51,911 | 15,464 | gemini-2.5-flash | 0.0542 | 0.0542 | 0.108 | 0.108 | 0.054 |
| GFOCUS_personas | 40.1 | 51,911 | 15,464 | gemini-2.5-pro | 0.2195 | 0.4201 | 0.439 | 0.840 | 0.420 |
| GFOCUS_personas | 40.1 | 51,911 | 15,464 | gemini-3.8-flash intro (to 2026-12-31) | 0.0969 | 0.2240 | 0.194 | 0.448 | 0.224 |
| GFOCUS_personas | 40.1 | 51,911 | 15,464 | gemini-3.8-flash (from 2027-01-01) | 0.1938 | 0.4480 | 0.388 | 0.896 | 0.448 |
| GFOCUS_personas | 40.1 | 51,911 | 15,464 | gemini-3.1-pro-preview | 0.2894 | 0.6684 | 0.579 | 1.337 | 0.668 |

## Supervised fine-tuning cost (training tokens = dataset tokens x epochs; 3 epochs)

| example type | tokens/example | examples | gemini-2.5-flash ($5.0/1M) | gemini-3.5-flash ($10.0/1M) | gemini-3.1-flash-lite ($3.0/1M) | gemini-2.5-pro ($25.0/1M) |
|---|---|---|---|---|---|---|
| verdict-only (S2 judge call: 2 images + persona prompt -> ratings) | 987 | 1,000 | $14.81 | $29.62 | $8.89 | $74.06 |
| verdict-only (S2 judge call: 2 images + persona prompt -> ratings) | 987 | 5,000 | $74.06 | $148.11 | $44.43 | $370.28 |
| verdict-only (S2 judge call: 2 images + persona prompt -> ratings) | 987 | 20,000 | $296.22 | $592.45 | $177.73 | $1,481.11 |
| one-call G-FOCUS distill (2 images + goal/diffs -> ranked reasons + verdict) | 1,753 | 1,000 | $26.30 | $52.59 | $15.78 | $131.48 |
| one-call G-FOCUS distill (2 images + goal/diffs -> ranked reasons + verdict) | 1,753 | 5,000 | $131.48 | $262.97 | $78.89 | $657.42 |
| one-call G-FOCUS distill (2 images + goal/diffs -> ranked reasons + verdict) | 1,753 | 20,000 | $525.94 | $1,051.87 | $315.56 | $2,629.68 |
| full G-FOCUS chain, all 5 stages as examples (per order) | 7,049 | 1,000 | $105.73 | $211.46 | $63.44 | $528.65 |
| full G-FOCUS chain, all 5 stages as examples (per order) | 7,049 | 5,000 | $528.65 | $1,057.30 | $317.19 | $2,643.26 |
| full G-FOCUS chain, all 5 stages as examples (per order) | 7,049 | 20,000 | $2,114.61 | $4,229.22 | $1,268.77 | $10,573.05 |
