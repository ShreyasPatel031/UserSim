# Comparison with competitors: with vs without (Oct 31, 2026)

**Question:** does comparing each launch with its competitors make the simulation and the launch model more accurate?
**Answer:** no. Each comparison does predict whether a launch beats the reach you'd expect from its team, and video
gaps predict it best. But neither model gets more accurate, because the comparison mostly repeats what the page
scores already say.

## Setup
- **Competitors:** a launch's 5 nearest earlier Product Hunt launches by meaning (name, tagline and description
  embeddings), each launched at least 2 days before it so their final votes were known on launch day.
- **Comparison (`cmp_features.py`):** for each Gemini page score and each score from Gemini watching the video,
  the launch's score minus its competitors' average. A launch that scores 4.5 while its competitors average 4.8
  gets a gap of −0.3.
- **Competitors' outcomes:** the competitors' log votes (mean and max), how close they are in meaning, and the share
  of competitors the launch beats on Gemini's top-5 chance.
- **Inputs:** every page input is the final version: real images for all launches, website text from the real
  Product Hunt link for 72% of launches, and watched videos for 88–97% of launches that have one. The coverage
  check passed for every month.
- **Tests:** out of sample. Each month is predicted by a model trained only on earlier months.

## 1. Does each comparison predict beating expected reach? (Mar–Oct)
Correlation, within day, between the gap and how much a launch beat the votes its fixed inputs predict
(`cmp_eff.py`, 95% interval):

| Better than its competitors on | Correlation | 95% interval |
|---|---|---|
| Video production | +0.088 | +0.048 to +0.126 |
| Video shows the problem | +0.081 | +0.043 to +0.119 |
| Video hook | +0.073 | +0.034 to +0.113 |
| Video pacing | +0.063 | +0.018 to +0.104 |
| Video clarity | +0.061 | +0.020 to +0.099 |
| Video call to action | +0.055 | +0.014 to +0.094 |
| Audience breadth (page) | +0.055 | +0.018 to +0.093 |
| Gemini's top-5 chance | +0.042 | +0.004 to +0.077 |
| Wow (page) | +0.039 | +0.004 to +0.076 |
| Website, with real sites | +0.019 | −0.015 to +0.054 (not significant) |
| Competitors' own votes | −0.008 | −0.047 to +0.031 (none) |

## 2. With vs without, simulation (Jul–Oct, `newsim_eval.py` STAGE5 CMP_SMALL)
The two comparison groups were fixed before testing, not chosen from results: the video gaps, and a summary (top-5
gap, share beaten, competitors' votes, closeness).

| | First-time teams: higher of 2 / winner of 3 | Repeat teams: higher of 2 / winner of 3 | Daily top 3 / 5 / 10 |
|---|---|---|---|
| Simulation, without | 68.7 / 64.7 | 77.4 / 67.9 | 60.3 / 70.9 / 79.7 |
| + video vs competitors | 68.3 / 65.5 | 77.3 / 66.5 | 60.9 / 70.2 / 79.5 |
| + summary vs competitors | 68.8 / 66.2 | 77.2 / 67.6 | 60.9 / 70.5 / 79.9 |
| + both | 68.7 / 64.7 | 76.9 / 67.1 | 61.2 / 70.5 / 80.3 |
| Launch model (reference) | 68.4 / 66.7 | 79.5 / 68.7 | 65.8 / 72.9 / 80.8 |

All 78 comparison inputs at once give daily top 3 / 5 / 10 of 60.6 / 70.9 / 80.1 (run of Oct 31, 02:00 UTC, before
the real websites).

## 3. With vs without, launch model (Mar–Oct, `ctrl.py`, 5 seeds; comparison added as page inputs with `CMP=1`)

| | Daily top 3 / 5 / 10 |
|---|---|
| Fixed + page, without | 62.3 / 69.0 / 78.4 |
| Fixed + page, with | 62.2 / 69.7 / 78.6 |
| All inputs, without | 63.7 / 70.3 / 79.6 |
| All inputs, with | 62.3 / 70.9 / 79.7 |

## 4. Verdict
- **No accuracy gain:** every change in sections 2 and 3 is within ±1.5 points, which is the run-to-run noise.
  The video gaps, the strongest competitor signal, overlap the watched-video scores that are already inputs.
- **Worth showing a maker:** the comparison has measured validity. "Your video shows the problem better than your 5
  closest competitors'" predicts beating expected reach (+0.081), so a launch report can rank a page against its
  competitors element by element, and say which gaps matter.
- **Per person:** whether someone already used a competitor (upvoted or commented on one of the 5 nearest) adds +1
  point of top-3 hit at the person level (49.0 → 50.0, AUC 0.697 → 0.699, better in 4 of 6 months).

## Also from this run: real websites (Product Hunt's own link) vs name-based guesses
| | Guessed websites | Real websites |
|---|---|---|
| Launch model, fixed + page, top 3 / 5 / 10 | 62.3 / 69.0 / 78.4 | 61.2 / 69.8 / 78.6 |
| Launch model, all inputs | 63.7 / 70.3 / 79.6 | 62.3 / 70.7 / 79.2 |
| Website score vs beating expected reach | +0.039 (significant) | +0.020 (not significant) |
| Simulation, best, daily top 3 / 5 / 10 | 61.2 / 70.2 / 80.1 | 60.3 / 70.9 / 79.7 |

Real websites don't change accuracy. The website's own effect gets smaller once the site is the real one. That
suggests the guessed-site score partly measured something else, such as a product having a domain that matches
its name. The real-site text is also today's version of the site, not the site as it was on launch day.
