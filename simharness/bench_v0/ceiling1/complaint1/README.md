# COMPLAINT-1 (Nov 25 2026): which real complaints the panels miss, and two arms to catch more

Code: `simharness/complaint1.py`. Numbers: `complaint1.json`. Same 22 launches, 8 resamples, stored half-B themes and
complaints as CEILING-2, equal-size subsamples (half A's count), E5's JUDGE / CJ (Gemini 2.5 Flash, temperature 0).
Spend $1.58 of $3 (2,164 calls, from usage_metadata). Launch-bootstrap intervals; arm differences paired by launch.

## Diagnosis: complaints by kind (one Gemini call per 40 complaints puts each half-B complaint in one kind)

| Kind | Complaints | Share | Caught by half A (ceiling) | Caught by deployed | Deployed - ceiling (points) |
|---|---|---|---|---|---|
| unclear value / use case / other | 495 | 63% | 35.8% | 24.2% | -8.2 [-17.9, +1.9] |
| setup friction / integration | 99 | 13% | 41.4% | 30.3% | -4.1 [-20.1, +15.8] |
| trust / privacy / security | 59 | 8% | 28.8% | 39.0% | +7.0 [-13.2, +25.6] |
| bugs / reliability / performance | 47 | 6% | 42.6% | 23.4% | **-34.5 [-64.3, -4.6]** |
| pricing | 46 | 6% | 21.7% | 8.7% | **-16.6 [-37.5, -0.6]** |
| already exists / differentiation | 41 | 5% | 24.4% | 24.4% | -2.5 [-27.2, +19.7] |

The clear misses are bugs / reliability / performance (people who tried the product report it breaking) and pricing.
The panels already match or beat humans on trust / privacy. Most complaints fall in the broad "unclear value / other"
kind, where the gap (-8) is not clear.

## Arms (equal size, fraction of the half-A ceiling; paired difference vs deployed)

| Arm | Complaint recall | Ratio of means | vs deployed | Precision | vs deployed | Theme recall | vs deployed |
|---|---|---|---|---|---|---|---|
| ceiling (half A) | 33.6 [24.9, 42.8] | 1 | | 49.0 | | 61.6 | |
| deployed | 24.3 [18.1, 31.1] | 0.72 | | 60.4 | | 56.8 | |
| control (persona regenerated, same prompt) | 24.6 | 0.73 | +0.2 [-3.2, +4.0] | 60.4 | +0.0 | 56.4 | -0.4 |
| (a) + "what would stop you using this" line | 21.8 [16.0, 27.6] | 0.65 | -2.6 [-6.5, +1.5] (vs control -2.8 [-7.2, +1.5]) | 52.5 | **-7.9 [-13.9, -1.9]** | 55.9 | -0.9 |
| (b) person-built from mostly-critical commenters | 24.4 [18.9, 30.3] | 0.73 | +0.1 [-2.5, +2.7] | 59.9 | -0.5 | 55.6 | -1.3 |

Neither arm closes the gap. (a) makes the concerns more specific but they are the wrong specifics: precision falls 8
points and complaint recall does not rise. (b) changes nothing measurable; at equal size only about 2 of the ~8
subsampled items come from the 15 person-built comments, so this test has little power for (b).

## Read with care
- Leak rules held: prompts use the 00:05 line-up / persona cards and held histories before the day only; nothing from
  half B. The one launch whose deployed panel had the maker's comment was not given it in arm (b).
- "Mostly critical" = at least 3 earlier comments and at least half with a critique marker (word list in the code);
  about 440 held people per day qualify.
- The deployed ratio here (0.72) differs from CEILING-2's (0.77) only by judge noise on a re-run.
- Implication: the missing complaints are mostly about using the product (it breaks, it is slow, it costs too much),
  which a panel reading only the launch page cannot know. A better test is a panel that has used the product (PU-1),
  or comments built from people who later reviewed similar products.
