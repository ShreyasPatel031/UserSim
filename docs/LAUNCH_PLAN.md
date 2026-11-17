# Six-month launch plan: 4 Product Hunt launches, two months apart (UserSim as its own customer)

**Part 1. The plan**

Written Nov 17 2026 for a maker with 0 followers and no launches. This one file holds everything, with nothing removed: Part 1 is the plan with its method, evidence and
superseded numbers; Part 2 is the feedback chain behind each product; Part 3 is the first competitor run.

**How to read the labels.** [MODEL] = output of the midnight forecast model (arm 2) on 56 real line-ups, Sep 21 – Nov 15
2026. [REAL] = outcomes of real launches. [JUDGMENT] = my call, not measured. Intervals are 95%, bootstrapped over days.

## The four launches

| # | Date | Product | Job and user | Different under Product Hunt's rule because | Day and reason | P(top 5) this launch [MODEL, row A] | At least one top 5 by now: raw / scaled |
|---|---|---|---|---|---|---|---|
| 1 | **Sat Dec 5 2026** | Launch Simulator (/try) | A maker sees how one page will land before posting | First launch | Saturday: rank and record | 17.6 [10.7, 24.3] | 18 / 13 |
| 2 | **Sat Feb 6 2027** | Competitor Radar | A founder with named competitors gets a standing daily and weekly watch: what launched, how it landed, what real users asked and complained about, where their own backers are moving | A different use case and moment: /try is used once before a launch on your own page; Radar is used every week after it, on competitors' products | Saturday: rank and record | 27.5 [19.0, 35.7] | 35 / 27 |
| 3 | **Sat Apr 10 2027** | User Testing, end to end | A product team has simulated users do real tasks on its product and on two competitors, and gets a side-by-side report ending in named fixes | A different use case and user: it operates the product itself in a browser, for product teams after launch | Saturday, or Tuesday if a hunter with a record posts it | 31.6 [21.7, 40.8] | 49 / 39 |
| 4 | **Tue Jun 15 2027** if a hunter with a record posts it, else **Sat Jun 12** | Market Simulator (moonshot) | A founder proposes a change (feature, price, positioning, launch) and sees who adopts, who switches and who is lost, by group | A different use case: products 1–3 describe what is; this one answers "what if" | Weekday for traffic only with a hunter; Saturday otherwise | Sat 34.2 [23.6, 44.6]; Tue–Thu 13.8 [10.4, 17.6] | Sat 60 / 49; Tue–Thu 51 / 41 |

- **The products changed on Nov 17 (Shreyas): Radar, User Testing and the Market Simulator replace the Daily Forecast,
  the Persona Panel and the Launch Pack.** The odds did not: they depend on hunter, team, day and record, not on which
  product it is, and the model is flat above a pitch score of about 75 (Radar 75, User Testing 69, Simulator 82 [MODEL]).
  User Testing's 69 is below that line; its pitch needs work before April.
- **Row A** is the launch you can set yourself: you post it, 1 maker, 9 images plus video, pitch score 86 (measured for
  /try), founder posts on the day. No press, no team reach, no hunter. Its exact profile has only **12 real launches**
  in 2026 (1 of 12 in the top 5, 5 of 12 in the top 10), so the 17.6% rests on the model, checked against a thin real sample.
- **"At least one top 5 by now"** carries the real record of each earlier launch into the next one, over every way each
  launch can finish (56 record states). Run: `counterfactual_arm2_4launch.py`. Intervals: launch 1 [11, 24], launch 2
  [24, 46], launch 3 [35, 62], launch 4 on a Saturday [45, 73]. All [MODEL].
- **Scaled** multiplies each top-5 chance by 3.7 / 4.9, because the model gave real zero-record launches 4.9% and 3.7%
  happened (n 945) [REAL]. Scaled intervals: [9, 18], [19, 37], [28, 51], [37, 62].
- **The largest lever stays outside row A.** If an active hunter with a median record posts each launch, the per-launch
  chance on a Saturday is 56.9% and on Tue–Thu 24.2%, and the chance of at least one top 5 after 1 / 2 / 3 / 4 launches is
  57 / 81 / 92 / 97% [MODEL]. Three makers with real reach lift row A to 30.2% on a Saturday [MODEL].
- **Seasonal caveat.** The line-ups are from Sep–Nov. December, February, April and June may differ. Each launch reruns
  the odds on the latest 8 weeks in week 7 of its cycle.

### Product Hunt's rule (checked on the live help page, Nov 17)
- Wait **at least two months** between posts for the same product or from the same company. Products that share a root
  domain fall under the same gap.
- Each post needs a significant update: a new app, or a redesign with new functionality, or something that serves "a
  substantially different use case or user". New UI and pricing changes do not count.
- Sooner than two months needs a relaunch request, reviewed by their team. Approval does not guarantee a homepage feature.
- The page also says several products due in a short time are "best" combined into one post. Our launches are 63 days
  apart, each for a different user or job, so this does not apply; it is the reason not to go faster.
- My earlier "six months" came from an older copy of the page and was wrong.
- Source: https://help.producthunt.com/en/articles/484934-can-i-relaunch-my-product

### Branch table: what each launch looks like after the earlier ones [MODEL, row A]

| Going into | Earlier top-5 finishes | Saturday P(top 5) | Tue–Thu P(top 5) |
|---|---|---|---|
| Launch 2 | 0 of 1 (82% likely) | 16–27 by how close launch 1 came | 10.6 expected over all branches (any day: 7–19) |
| Launch 2 | 1 of 1 | 53–68 | any day: 30–62 |
| Launch 3 | 0 of 2 | 20.9 (range 15.7–26.8) | 4.5 |
| Launch 3 | 1 of 2 | 43.5 (38.2–54.2) | 18.8 |
| Launch 3 | 2 of 2 | 62.7 (53.3–68.3) | 40.0 |
| Launch 4 | 0 of 3 | 21.3 (17.6–26.8) | 4.2 |
| Launch 4 | 1 of 3 | 36.5 (24.5–54.2) | 15.9 |
| Launch 4 | 2 of 3 | 55.9 (44.0–62.7) | 25.6 |
| Launch 4 | 3 of 3 | 61.5 (53.3–68.3) | 41.6 |

A launch outside the top 5 never lowers the next one below the no-record level. [REAL] check: hunters with 1–3 prior
launches all in the top 5 reach the top 5 42.9% of the time (n 184); with none in the top 5, 9.9% (n 684).

## The chain: each product is built from the feedback on the one before

Full tables, competitors and pitch versions: **Part 2 of this file** (E5, Nov 17; Gemini $1.52). This is the summary.

**What "feedback" is today.** None of our products has launched, so there is no real feedback on them. The chain uses,
in this order: real comments on competitors doing the same job [REAL, thin: most themes rest on 1–5 people], then the
persona panel on our own page [MODEL]. **On Dec 6 the real comments on launch 1 replace stage 1 and the chain is rerun.**

| Product | Built from the feedback on | The three themes that shaped it | Real commenters / panel |
|---|---|---|---|
| 1. Launch Simulator (/try) | Its competitors (67 real commenters on 4 launches) and the panel | How is accuracy quantified? How does it compare with real user testing? Is the rank right for unusual or crowded products? | 4 real, all four groups / 2 real / panel only |
| 2. Competitor Radar | Product 1 | "Simulated reactions may not reflect real feedback", so Radar uses real comments only. "How is accuracy quantified?", so Radar shows each rival's finish against its forecast. "Can it identify customer objections?", so Radar lists what users complained about on rivals | 2 real + all four groups (16 lines) / 4 real / 1 real |
| 3. User Testing, end to end | Product 2 (56 real commenters on 8 launches, and the panel) | "It does nothing for my own product", so it runs tasks on your product. "Can it suggest actions?", so the report ends in named fixes. Signal-to-noise, so every finding links to its log | 0 real, all four groups (21 lines) / 2 real / 2 real |
| 4. Market Simulator | Product 3 (93 real commenters on 8 launches, and the panel) | "Can it test a specific element or scenario?", so you propose a specific change. "Simulated users may not reflect real behaviour", so every prediction is scored in public. "Can it refine personas?", so custom segments | **13 real, the best-supported theme in the chain** / 2 real + three groups / 3 real |

### What each launch claims, and what must be true to ship [JUDGMENT, with the measured state]

| Launch | World-class claim | Test before launch day | State today | Held back for later |
|---|---|---|---|---|
| 1 /try, Dec 5 | The only launch rehearsal checked against real launches every day | Nightly score of its predicted questions against real comments, 30+ days, on the page | Forward figures from 11 launches only | Real competitor comments (2); task runs and version comparison (3); "what if" (4) |
| 2 Radar, Feb 6 | The only competitor watch built from what real users said, counted by distinct people, with its tagging scored in public | Agreement of the automatic theme tags with 300 hand-labelled comments; every featured launch in a tracked space in the digest within 24 hours, 14 days running | **Neither number exists yet** | Named fixes and task runs (3); "what if we changed X" (4); other platforms |
| 3 User Testing, Apr 10 | The only user test that runs the same tasks on you and your competitors, and shows how often its findings match what real users later said | Share of real complaint themes its runs find, on 30+ products, published whatever it is; a run completes on 9 of 10 arbitrary sites | **Weak: 24% [9, 38] on 11 launches [REAL].** The claim cannot be made yet | Price, positioning, competitor responses (4); API |
| 4 Market Simulator, Jun 12/15 | The only market simulator whose every prediction is scored in public afterwards | One scored claim: predicted share of backers by voter group against the real share, 30 days of public record | 89,027 complete people; a person's real pick is in our top 3 about 57% of the time; 25–29% of backers named in advance | Markets beyond Product Hunt; answers about individuals |

### Launch 1 specifics (Dec 5)
- **Three things to beat [JUDGMENT from the competitor run].** A one-input, instant answer (HuntOMeter, Chaos Simulator).
  A headline accuracy number (Articos claims 86%; ours has none above the fold). Output worth sharing: nobody shares a
  rank range of 4 to 41.
- **Added from real comments:** a confidence score on each predicted theme; our own forecast for our own launch, published
  in advance and scored afterwards.
- **Ship gate (go or no-go Dec 2).** "Free to try, no signup" is true, and the run limits are raised for launch day (today
  150 runs a day in total, 3 an hour per address). The accuracy number is current, with its day count. The "what this
  uses and what it ignores" block and the plain-language sentence are live. 5–10 real makers have used it.
- **Cut-line.** First to go: visual polish, then the plain-language summary. Never cut: the accuracy block and the run limits.
- **Fallback.** Outside the top 10 (about 50% likely): launch 2 keeps its date; the model gives it the same odds as no
  record. Not featured: collect the comments and file a relaunch request with the fixes.
- **Launch 1's real comments become the first Radar report** and replace stage 1 of the chain.

### Warnings from the run
1. **Withdrawn: "our own panel never picks our products" carries no information.** The forced choice was then scored on
   889 real launches over 30 days [REAL]: its ordering has no relation to real rank (0.03 [−0.02, 0.09] for mean place;
   0.17 for pick share, against 0.62 for the forecast model), it adds nothing to the forecast model, and it does not find
   a group's real backers better than chance (7.9% against 8.4% random). A launch is picked by 14% of its panel on
   average, so "never picked" is the normal case. The forced choice does not go into User Testing as a score. The panel's
   measured value stays what it was: which themes come up (recall 61%, precision 52%). For a pre-launch number, use the
   forecast model.
2. **The moonshot's main objection.** The Market Simulator has the best pitch score (82); the panel's top reason not to
   use it is "too niche, complex or abstract" (24 lines, all four groups). Its core
   input, testing a specific scenario, has the best real support in the chain (13 commenters).
3. **War Game mode has no real-comment support.** The 13 commenters who asked about competitors meant the tool against
   its alternatives. It stays out of June's scope unless product 3's real comments ask for it.
4. **Product 3 cannot make its claim today** (24% of real complaints found). Its build starts with that number, not with
   features; if it is still under 40% at the week-4 check, launch 3 ships as a narrower product or moves a week at a time.
5. **Radar's "does nothing for my product" objection comes from the panel only**; no real commenter said it.

## The loop for each two-month cycle

| Weeks | Work | Output |
|---|---|---|
| 1 | Collect every real comment, question and complaint from the last launch. Score the panel's and /try's predictions against them. | Real themes; precision and recall of our own predictions, published |
| 1–2 | Competitor run: 5–8 closest competitors through the pitch scorer, /try and the panel, with their real finish | The competitor table and the three things to beat |
| 2 | Fix the world-class claim and its test | One sentence and its test |
| 2–6 | Build, with a check against the claim in week 4 | Working product |
| 7 | Pitch versions through the scorer; the page through /try and the panel; 5–10 real users from the last launch's audience | Chosen pitch, fixed page, open questions |
| 7 | Rerun the odds on the latest 8 weeks with the real record so far, Saturday and weekday | P(top 5) and P(top 10) with intervals |
| 8 | Go or no-go on the Wednesday, then launch | A dated decision |

Launch 1 has under three weeks, so its cycle is compressed: competitor run now (E5), page fixes and real-user test by
Dec 1, odds rerun and go or no-go on Dec 2.

## Plan-level items

- **Dates.** Dec 5 2026, Feb 6 2027, Apr 10 2027, Jun 12 or 15 2027: 63, 63 and 63 or 66 days apart.
- **Capacity [JUDGMENT].** One maker shipping a best-in-class product every two months is the binding constraint. Each
  launch has a cut-line above. The date moves only when the world-class test fails, and then by one week at a time.
- **Hunter outreach, for every launch.** Starts now and runs through all four cycles. Approach hunters who have posted
  analytics or maker tools; show them the product run on a launch they hunted; ask only whether they would post it. One
  two-week window per launch, closing at the go or no-go. Never ask for votes.
- **Makers with reach.** Only people who really worked on the launch and will post about it themselves. Today that is one
  person, so row A is the plan and row C is upside. Each cycle names who joins by week 6.
- **Success beyond rank [JUDGMENT, targets not forecasts].**

  | Launch | Users in the first 7 days | Emails | Paid prospects |
  |---|---|---|---|
  | 1 /try | 500 runs | 100 for the Radar waitlist | 10 conversations with makers who ran it |
  | 2 Radar | 200 tracked spaces set up | 300 digest subscribers | 20 teams on a paid trial |
  | 3 User Testing | 100 completed test runs | 300 | 20 paying teams |
  | 4 Market Simulator | 200 scenarios run | 500 | 10 design partners |

- **Stop rule after launch 2.** Change the sequence or the product if, after Feb 6, both launches finished outside the top
  10 **and** /try has under 50 runs a week. Then launch 3 becomes whichever product real users asked for most. If rank missed but usage met its targets, keep the sequence and put the effort into the hunter. If the
  panel's recall against our own launches' real comments is under 50%, launch 3's claim is rewritten before it is built.

## Still open
- The two Radar tests and User Testing's complaint figure have to be built and measured; see the claims table.
- Rerun the chain on Dec 6 with launch 1's real comments.
- Page fixes need Shreyas's word to the website agent.

---

# Method and evidence

Runs: `experiments/launch_plan/counterfactual_arm2.py` (one change at a time), `counterfactual_arm2_review.py` (review reruns),
`counterfactual_arm2_4launch.py` (four launches). All on the pipeline server, read-only.

## Method
- **Model.** The published midnight model (arm 2, LightGBM, 5 seeds), trained on all days before Sep 21 2026.
- **Test days.** Each test launch is dropped into every real line-up from Sep 21 to Nov 15 2026 (56 days, 8 of each weekday).
- **Rank and probability.** The predicted rank is turned into P(top 3/5/10) using how often the model's predicted rank landed
  in the real top 3/5/10 on those same days. For example, predicted #1 lands in the real top 5 82% of the time, and predicted
  #7 only 32%. On these days the model hits 60.7% of the top 3.
- **Interval.** The 95% interval on P(top 5) is a bootstrap over days.
- **Not causal.** This is what the model predicts for a launch with these traits. "Team of 5" partly stands for "a company
  that has 5 people who bring their own networks". Changing the number on the form does not buy that.

## The base case: you, today
Self-hunted, account 60 days old, 1 maker, 6 images plus video, a median pitch, no launch-day posts, AI topic:
**median predicted rank 25. P(top 5) 2.3% [1.6, 3.3]. P(top 10) 11.6%.**

## One change at a time, from the base case

| Change | Median rank | P(top 3) | P(top 5) [95%] | P(top 10) |
|---|---|---|---|---|
| Base | 25.5 | 0.6 | 2.3 [1.6, 3.3] | 11.6 |
| **Posted by an active hunter (median record: 66 launches, 47% top 5)** | **10** | **6.9** | **17.6 [14.1, 21.2]** | **47.1** |
| Posted by a top-10% hunter (508 launches, 77% top 5) | 9 | 8.3 | 21.7 [18.2, 25.5] | 53.0 |
| Team of 5 makers on the page | 12 | 3.7 | 10.3 [7.6, 12.9] | 33.5 |
| Team of 3 | 16 | 1.9 | 5.3 [3.7, 7.4] | 21.8 |
| Pitch score 85 (Gemini read of the tagline and description; VM model) | 15.5 | 2.1 | 6.0 [4.3, 8.0] | 23.6 |
| Pitch score 75 (VM model) | 16 | 1.9 | 5.4 [3.8, 7.3] | 21.3 |
| Founder posts plus organic coverage (1 press, 1 HN, 1 Reddit) | 16 | 2.0 | 5.6 [3.9, 7.4] | 22.1 |
| Founder posts only (3 posts on launch day) | 20 | 0.9 | 3.2 [2.3, 4.4] | 15.1 |
| Your own account 3 years old instead of 60 days | 21 | 0.8 | 3.0 [2.0, 4.2] | 13.9 |
| Company X account | 23 | 0.7 | 2.5 | 12.7 |
| 9 media + video vs 3 media, no video | 24.5 vs 27 | ≈ | 2.4 vs 2.2 | 12.0 vs 10.7 |
| Topic: AI vs AI+dev vs non-AI | 25.5 / 26.5 / 23.5 | ≈ | 2.3 / 2.2 / 2.4 | — |

**Levers, biggest first:**
1. The hunter's track record.
2. Team size.
3. Pitch quality.
4. Launch-day reach (founder posts plus organic coverage).

Media count, topic and having a company X account barely matter.

## Review reruns (Nov 17, 04:10Z): settable-only row, launch-2 branches, real small-record hunters, weekday causes

Reruns: `experiments/launch_plan/counterfactual_arm2_review.py` and `.out`. Same model and the same 56 days as before.

### What changed
1. **The first launch is a 1-in-6 shot at the top 5, not 1-in-3.** The old "everything you control" row counted organic
   coverage, a team of 3 and a company X account as settings. Splitting them out (pitch 86 is the measured /try score):

   | First launch | All days: P(top 5) [95%] | Saturday: P(top 5) | Saturday: P(top 10) | Tue–Thu: P(top 5) |
   |---|---|---|---|---|
   | **A. Settings you can set**: self-hunt, 1 maker, 9 media + video, pitch 86, founder posts | 7.7 [5.7, 10.3] | **17.6 [10.7, 24.4]** | 50.5 [40.7, 61.6] | 3.0 [2.5, 3.6] |
   | B. A + organic coverage lands (1 press, 1 HN, 1 Reddit) | 12.2 [9.4, 15.2] | 25.0 [16.8, 34.8] | 59.6 | 4.6 |
   | C. A + 3 makers who bring real reach | 19.6 [15.8, 23.5] | 30.2 [19.9, 41.3] | 63.5 | 11.8 |
   | D. Everything goes right (old stacked row) | 32.0 [26.9, 37.3] | 52.5 [45.3, 59.4] | 79.9 | 18.5 |

   **Plan on row A.** Rows B to D are upside, not settings.

2. **The second launch, with every branch of the first.** Launch 1 is row A on a Saturday. Launch 2 is row A again, with the
   real record of launch 1 fed in.

   | Launch 1 finished | Chance of that | Launch 2 on a Saturday: P(top 5) | Launch 2 on any day |
   |---|---|---|---|
   | Rank 1–3 | 6% | 68.3 [63.4, 71.4] | 61.8 |
   | Rank 4–5 | 11% | 52.9 [40.4, 61.6] | 30.1 |
   | Rank 6–10 | 33% | 26.8 [18.8, 36.2] | 19.1 |
   | Rank 11–20 | 35% | 17.6 [10.6, 25.4] | 8.3 |
   | Rank 21+ | 15% | 15.7 [8.4, 23.6] | 7.1 |
   | **Expected (weighted)** | | **27.5** | 17.4 |

   The number to plan around for launch 2 is **27.5%**, not 58.8%. A launch 1 outside the top 5 does not hurt launch 2
   compared with having no record (17.6% either way on a Saturday); a top-5 finish roughly triples it.

3. **Real hunters with 1–3 prior launches (2026, real outcomes, not the model).**

   | Hunter's record going in | n | Actual top 5 | Actual top 10 |
   |---|---|---|---|
   | 0 prior launches | 3,805 | 8.4% | 26.0% |
   | 1 prior | 642 | 16.0% | 36.8% |
   | 2–3 prior | 316 | 18.4% | 41.5% |
   | 51+ prior | 1,949 | 50.0% | 73.4% |
   | 1–3 prior, **all in the top 5** | 184 | 42.9% | 65.8% |
   | 1–3 prior, none in the top 5 | 684 | 9.9% | 29.7% |
   | 1–3 prior, all top 5, account 2 years old or less | 36 | 38.9% | 63.9% |
   | 1–3 prior, none top 5, account 2 years old or less | 307 | 6.5% | 24.4% |

   - The data is not thin (958 launches by hunters with 1–3 prior), so steps 2–4 are not pure extrapolation.
   - The effect is real but smaller than the old table said: about **40%** top 5 after an all-top-5 record, not 60–75%.
   - On the 56 test days the model says 32.9% for the all-top-5 group against 29.3% actual (n 41), so it is roughly
     calibrated there.
   - "After 2 launches you are at the level of an active hunter" was wrong. An active hunter (51+ launches) is at 50%.
   - History starts in Jan 2025, so some "1 prior" hunters are older accounts with unseen earlier launches; the
     2-year-old-account rows remove most of them.

4. **Real launches that look like the plan (2026, hunter with 0 record).**

   | Profile | n | Actual top 5 | Actual top 10 |
   |---|---|---|---|
   | All 0-record launches | 3,142 | 6.9% | 22.8% |
   | 0-record, on a weekend | 423 | 19.9% | — |
   | Pitch 75+ | 251 | 16.7% | 42.2% |
   | Pitch 75+, weekend | 51 | 29.4% | — |
   | Pitch 75+, 1 maker, founder posts, no coverage (row A) | 12 | 8.3% | 41.7% |
   | Pitch 75+, founder posts, coverage 3+ (row B) | 36 | 25.0% | 44.4% |
   | Pitch 75+, 3+ makers, founder posts, coverage 3+ (row D) | 7 | 71.4% | 100% |

   - Row A's exact profile is rare (12 launches); its model number of 7.7% matches the 8.3% seen.
   - Row D has 7 real cases. It is out of the usual range and should not be planned on.
   - Calibration on all real 0-record launches in the test days: model 4.9%, actual 3.7% (n 945). The model is slightly
     kind to newcomers.

5. **Why weekends win. It is not the number of launches.** Monday has 23 launches like Saturday, and checks out (18–27 on
   the 8 Mondays), yet row A gets 5.7% [3.8, 8.4] on Monday and 17.6% on Saturday.

   | Day | Launches | Row A: P(top 5) [95%] | Launches with 3+ makers | Strong hunters (50%+ top 5) | Votes at rank 5 | All votes that day |
   |---|---|---|---|---|---|---|
   | Mon | 23 | 5.7 [3.8, 8.4] | 6.4 | 5.9 | 188 | 3,314 |
   | Tue | 36 | 3.1 [2.4, 4.2] | 7.6 | 6.4 | 207 | 4,204 |
   | Wed | 34 | 3.1 [2.1, 4.2] | 8.9 | 7.0 | 190 | 4,031 |
   | Thu | 34 | 2.8 [2.1, 3.8] | 8.9 | 7.8 | 199 | 3,991 |
   | Fri | 36 | 3.8 [2.8, 4.5] | 5.1 | 5.9 | 168 | 3,855 |
   | **Sat** | 22 | **17.6 [10.7, 24.4]** | 2.8 | 4.5 | 150 | 2,620 |
   | **Sun** | 19 | **18.1 [14.1, 21.8]** | 3.5 | 5.6 | 155 | 2,472 |

   - Weekends have a **weaker line-up**: a third as many team launches and fewer strong hunters. Monday is small but as
     strong as a weekday.
   - It is not the model's weekday input: forcing that input to each value on the same line-ups moves row A only between
     6.5% and 10.9%, and Saturday's value is among the lowest.
   - Real data agrees: 0-record launches reach the top 5 19.9% of the time on weekends against 6.9% overall.
   - **The cost:** a Saturday has about 62% of a Tuesday's votes (2,620 against 4,204), and rank 5 gets 150 votes against 207.


## Pitch versions and their measured scores (E5)

Three tagline and description versions were written for each product. Every claim in them is a number we have already published; "free, no signup" in /try version 1 must be true on launch day or be cut.

Each version was scored with the deployed pitch prompt (Gemini 2.5 Flash, the same listwise prompt that produces the model's `llm_pitch` input). The version was placed in the real line-up of 14 days (2 of each weekday, Sep 18 – Nov 12) and scored alongside that day's real launches. The interval is a bootstrap over the 14 days. The run made 210 calls: 15 versions × 14 days. The 15 are the 12 versions shown here plus 3 versions of the API pitch, which was scored in the same run and is not in this plan. 208 of the 210 returned; the 12 versions shown account for 168 of the calls. Cost for all 210: $0.73. As a check, the real launches in the same calls averaged 55.5, against 55.4 for their stored scores.

| Product | Version | Tagline | Pitch score [95%] | Share of that day's real launches it outscores |
|---|---|---|---|---|
| Launch Simulator (/try) | **1** | **Paste your URL, see how your launch would land** | **86 [83, 89]** | 99% |
|  | 2 | Rehearse your Product Hunt launch before launch day | 84 [80, 88] | 99% |
|  | 3 | Know the questions your launch will get, in advance | 80 [77, 85] | 96% |
| Forecast board | 1 | Tomorrow's Product Hunt top 5, predicted at 12:05am | 86 [83, 89] | 99% |
|  | 2 | A public scoreboard for Product Hunt predictions | 85 [82, 89] | 99% |
|  | **3** | **See where today's launches will land, free** | **88 [86, 90]** | 100% |
| Persona panel | 1 | A panel of 24 Product Hunt voter personas for your launch | 72 [66, 78] | 84% |
|  | **2** | **Hear from your launch audience before they exist** | **75 [71, 79]** | 88% |
|  | 3 | Which Product Hunt voters will back you, and why | 72 [66, 77] | 84% |
| Launch Pack | 1 | Pre-launch audit, launch-day read and post-mortem | 35 [29, 40] | 8% |
|  | **2** | **Everything we know about your launch, before and after** | **80 [75, 85]** | 95% |
|  | 3 | Launch on Product Hunt with the data on your side | 67 [56, 77] | 72% |

Best version of each, with its description:

- **Launch Simulator (/try), version 1.** *Paste your URL, see how your launch would land.* Paste a product URL before you launch. You get the questions and concerns Product Hunt users are most likely to raise, simulated reactions, and an expected rank band. Built on 81,000 real Product Hunt voter profiles. Free to try, no signup.
- **Forecast board, version 3.** *See where today's launches will land, free.* Launching soon or just curious? This free board ranks today's Product Hunt launches by predicted finish, using only what is public at 12:05am PT. It updates again at 3:45am, and yesterday's forecast is graded against the real result.
- **Persona panel, version 2.** *Hear from your launch audience before they exist.* We grouped 81,000 real Product Hunt voters by what they upvote, then built a panel that answers as those groups would. See who is drawn to your product, who is not, and what each group would say about it. Simulated, and labelled as such.
- **Launch Pack, version 2.** *Everything we know about your launch, before and after.* For one launch you get three reports: what to fix on your page before launch, a launch-day forecast with our published accuracy, and an honest post-mortem of what happened and why. Built on real Product Hunt voting data, with every number sourced.

What the scores say:
- **/try and the Forecast board score 80–88 in every version.** The wording matters little for them.
- **The persona panel scores lowest (72–75).** The judge finds "a panel of personas" less concrete than "paste your URL" or "today's predicted ranking".
- **The Launch Pack swings the most: 35 to 80.** Version 1 leads with "a paid package" and a list of three reports, and scores 35. Version 2 leads with what the founder gets and scores 80. Do not open with the price or the word "package".
- **One accuracy definition.** Panel version 1 quotes "63% of the themes on 276 past launches". That is theme recall from an earlier back-test. The current figure, used everywhere else in this document, is 61% recall and 52% precision on 167 launches. Whichever pitch is used on launch day must quote the figure shown on the site that day.
- **Caution.** The judge is a language model scoring products about Product Hunt for a Product Hunt audience. It may favour them. Scores at the 96th–100th percentile of real line-ups are probably too kind. Because the rank model is flat above 75, this does not change the trajectory.

### Does the pitch judge favour Product Hunt tools? (real launches)

Stored scores from the same prompt, for the 14 third-party launch or Product Hunt tools in our 2026 data, against where they really finished:

| Group | n | Mean pitch score | Reached top 5 |
|---|---|---|---|
| Third-party launch / Product Hunt tools | 14 | 57 (range 25–80) | 7 of 14 |
| All 2026 launches | 6,890 | 56 | — |
| Our four best versions | 4 | 82 (75–88) | not launched |

- **The judge does not favour the category.** Real launch tools average 57, the same as all launches.
- **Within the category the score tracks the finish.** Rank correlation between score and day rank is −0.75 across the 14 (higher score, better rank). The three that scored 80 finished 3rd, 4th and 4th. The three that scored 25–35 finished 9th, 15th and 19th.
- **The closest real match to our Forecast board scored 30 and finished 15th of 18**: a Product Hunt analytics extension, hunted by an account with 1 prior launch. A Product Hunt prediction benchmark scored 80 and finished 3rd of 41, posted by a hunter with 279 prior launches.
- **Our own scores (75–88) are above every real third-party tool in the category (maximum 80).** We wrote those pitches knowing what the judge rewards, so treat them as "at least 75", not as 86–88. The model is flat above 75, so the trajectory does not depend on the difference.

- **A second check disagrees on how well the score tracks the finish.** When 22 competitors with a real launch were re-scored on the same 14 line-ups as ours, the score had no relation to their real day rank (rank correlation −0.13, p = 0.55), and some tools scored far above their stored score (one from 30 to 73). A score given outside the product's own launch day is noisy by about ±15 points. So the judge is not biased towards the category, but our 75–88 should not be read as a forecast.

Per-competitor scores, on the same 14 line-ups as ours, are in Part 3 of this file.

## Persona panel and /try band on each best version (E5)

**Persona panel.** The live panel prompt, with 24 personas per product. A new maker has no team history, so the personas were built from the people who backed same-topic launches in the 30 days before Nov 12 (5,726 people for /try, the board and the panel, whose topics include Artificial Intelligence; 2,495 people for the Launch Pack, whose topics are Marketing, SaaS and Artificial Intelligence in that order and matched a narrower set of launches; its personas therefore stand for about 100 people each, not about 230). Each persona stands for at least 20 people; no individual is shown. One Gemini call per product; cost $0.04.

**/try band.** The deployed /try code, with the pitch text pasted in. /try knows nothing about the hunter, team or day, so it assumes the population median for each. Its band is therefore not comparable to the table above, which sets those inputs explicitly.

| Product (best version) | /try percentile among similar launches | /try likely rank band (median) | /try share reaching top 3 / top 10 | Panel interest: high / medium (of 24) |
|---|---|---|---|---|
| Launch Simulator (/try) | 35 | 4–41 (15) | 7% / 33% | 21 / 3 |
| Forecast board | 58 | 3–38 (13) | 13% / 41% | 20 / 4 |
| Persona panel | 64 | 2–34 (12) | 17% / 45% | 21 / 3 |
| Launch Pack | 27 | 4–43 (17) | 7% / 27% | 23 / 1 |

The /try bands are wide (roughly rank 3 to 40) and differ little between products. From the text alone, /try places the panel and board pitches a little above the /try and Launch Pack pitches, which is the reverse of the Gemini pitch scores. Neither signal separates the four products reliably, and **neither drives the launch order**. The order (/try, board, panel, Launch Pack) is a product judgment: which is easiest to try on the spot, and which needs the others' track record first. On both signals the four products are within noise of each other.

The panel rates nearly every persona "high" interest for all four products. That is not informative: the panel is known to be agreeable, and it has measured value for *which themes come up* (theme recall 61% and theme precision 52% on 167 held-out launches; recall is the share of themes real commenters raised that the panel predicted, precision is the share of predicted themes that real commenters raised), not for how much people like something. Read the concerns and questions below, not the interest levels.

### Main concerns and questions by voter group

| Voter group (people behind the personas) | Launch Simulator (/try) | Forecast board | Persona panel | Launch Pack |
|---|---|---|---|---|
| **Tech innovators** (about 3,700; 16 of 24 personas; developer and Mac-tool fans) | How accurate are the simulated reactions, especially for niche or novel products? Does it account for the hunter? How fresh are the 81,000 profiles? Can I compare two versions of my description? Is there an API? | Which public inputs carry the most weight? What is the margin of error? What about launches that surge late in the day? Can the forecast be gamed or become self-fulfilling? Show the historical record. | How were 81,000 people grouped, and are the simulated answers representative? How is it validated after a launch? Is the original users' privacy protected? Can I export the comments or define my own segments? | How specific is "what to fix": actionable or general? How accurate is the launch-day forecast, with examples? What is in the post-mortem? Can reports be exported? |
| **Launch veterans** (about 650) | Does it handle products close to existing ones, and day or time of launch? Can I see reactions split by audience segment? | How is yesterday's forecast graded? Does it account for how many launches there are that day? Which factors drive a prediction? | What is the confidence level of the simulated reactions? Can I compare two descriptions side by side? | Does it account for the maker's own network? Are the fixes specific enough to act on today? |
| **Product launchers** (about 440) | Does it look at screenshots and video, or only text? Does it account for the hunter? Will it suggest improvements? | Does product quality count, when only public data is used? Could the forecast create a bandwagon? How accurate is it for the top 3? | Are responses specific to my product, not generic? Can I test headlines and calls to action? | Does it account for my existing community? Will it help turn visitors into users? |
| **Curious observers** (about 680; medium interest) | Is the feedback understandable if I am not technical? Does it work for an early, unpolished product? | Is it readable for someone who is not launching? Does it cover all launches or only the top? | Is there a free tier? Is it understandable without marketing knowledge? | Is it usable by a non-marketer? |

The single question /try itself predicted for each page was the same theme: how accurate is it (the rank band, the simulated reactions, the forecast).

### What to fix on each page before launch

Across all four products and all four groups, the first question is **"how accurate is this, and how do you know?"** That is the one thing every page must answer above the fold.

1. **Put the measured accuracy next to every claim, with its limits.**
   - Forecast board: the 184-day record (3.3 of 5 top-5 picks correct) and yesterday's graded result, visible without scrolling. State the typical miss in ranks.
   - /try: say plainly that the rank band is wide and is based on the page text only; show the checked share of predicted themes that real commenters raised.
   - Panel: show theme recall and precision (61% and 52% on 167 launches) and say what they are not (it does not predict individual votes or how much people will like the product).
2. **Say what the model does not see.** Three of four groups ask about the hunter, the maker's network, late surges and images or video. Add one short "what this uses and what it ignores" block to each page. For /try, say that it reads text only, and that the hunter and team are assumed typical.
3. **Answer the "gaming" and "self-fulfilling" worry on the Forecast board.** State that the forecast is published after launches are live, uses only public inputs, and that we do not help anyone collect votes.
4. **Answer the privacy question on the panel page.** State that personas are groups of 20 or more people built from public voting history, and that no individual is shown or sold.
5. **Add version comparison to /try, or say it is coming.** "Can I test two descriptions against each other?" came from three groups and for three products. It is the most requested feature and is cheap to build on what exists.
6. **Launch Pack: show a sample report.** Every group asks how specific the "what to fix" advice is. A real, redacted sample of the three reports answers it. Lead with what the founder gets, not with "paid package" (pitch score 80 against 35).
7. **State the price and the free tier on every page.** Cost and "is there a free tier" came up for the panel, and for the API in a separate run.
8. **Plain-language summary for non-launchers.** The curious-observer group (about 12% of the panel) asks whether they can understand it at all. One sentence at the top of the board and of /try results is enough.

These are model-predicted concerns, not real feedback. On real launches the panel's predicted themes are right about half the time (precision 52%) and cover about 61% of what commenters raise (recall), so treat the list as a checklist of likely questions, not a ranking of what matters most.

Files: `experiments/launch_plan/candidates.json` (all versions), `pitch_score.py`, `panel_try.py`, `cf_arm2_measured.py`, `cf_arm2_measured.json`.

---

# Appendix: superseded. Do not quote these numbers.

The sections below came before the review. They count organic coverage, a team of 3 and a company X account as settings, feed each
launch's predicted rank back in as if it had happened, and assume 3–4 week spacing. The plan above replaces them.

## (superseded) Stacking the levers: the first launch
The levers compound; they don't add up linearly.

| First launch | Median rank | P(top 3) | P(top 5) [95%] | P(top 10) |
|---|---|---|---|---|
| Everything you control: self-hunt, 3 makers, 9 media + video, pitch 75, company X, founder posts + organic coverage | 7 | 15.8 | **31.2 [26.5, 35.7]** | 63.0 |
| Same, posted by a top-10% hunter | 2 | 55.8 | **71.4 [68.8, 74.0]** | 90.3 |

### Day of week (the "everything you control" launch)

| Day | Launches that day | Median rank | P(top 5) | P(top 10) |
|---|---|---|---|---|
| Mon | 23 | 7 | 28.6 | 63.6 |
| Tue | 36 | 8 | 18.6 | 52.8 |
| Wed | 34 | 8 | 20.9 | 56.1 |
| Thu | 34 | 9 | 14.9 | 44.5 |
| Fri | 37 | 6.5 | 35.1 | 66.9 |
| **Sat** | 23 | **4** | **52.5** | **80.4** |
| **Sun** | 19 | 5.5 | 47.6 | 77.1 |

Weekends carry about 20 launches against about 35 on weekdays. A zero-follower maker's chance of top 5 roughly triples on a
Saturday compared with a Thursday. A weekend top 5 also gets less traffic than a Tuesday top 5.

## (superseded) The trajectory: each launch builds the hunter record for the next
You hunt your own launches, so each one adds to your own hunter record, which is the model's strongest input. The model's
prediction for each launch is fed in as the record of that launch.

That is optimistic: it assumes each launch lands where the model says. A launch that does worse slows every step after it.

| Step | When | What | Measured pitch score | Your hunter record going in | Median rank | P(top 5) [95%] | P(top 10) |
|---|---|---|---|---|---|---|---|
| 1 | Week 1, Saturday | **Launch Simulator (/try)**: free, instant, visual. The most "try it now" product. | 86 | none | 7 | 33.6 [28.4, 39.0] | 67.0 |
| 2 | Week 4–5, weekday or weekend | **PH Daily Forecast board**: a free daily product with a public accuracy number. | 88 | 1 launch | 4 | 58.8 [54.7, 63.0] | 84.6 |
| 3 | Week 8–9 | **Synthetic launch audience**: the 24-persona panel, as its own product. | 75 | 2 launches | 2 | 69.5 [66.7, 71.7] | 90.5 |
| 4 | Week 12–14 | **Launch Pack / Pro**: the paid product, launched once the free products have built your record. Or a major v2 of /try. | 80 | 3 launches | 2 | 71.5 [69.7, 73.2] | 91.8 |
| 5 | Later | **API** for agencies and tools | not scored here | 4 | ≈ step 4 | — | — |

The table now uses the measured Gemini pitch score of each product's best version (section "Pitch versions" below) in place of the assumed 75. It was rerun with `experiments/launch_plan/cf_arm2_measured.py` on E5's rebuild of the same model, because the pipeline VM could not be reached from E5's container. The rebuild trains on days before Sep 18 and tests on Sep 18 – Nov 12 2026 (56 days, 8 of each weekday); the tables above this one are from the VM run (Sep 21 – Nov 15) and are unchanged. The two runs agree: with the assumed score of 75 the rebuild gives P(top 5) 32.3 / 57.8 / 69.5 / 72.6 for steps 1–4, against 31.2 / 60.4 / 71.5 / 75.0 on the VM.

**The measured scores change almost nothing.** All four products score 75 or more, and the model's response to pitch is flat above about 75: in the base case, P(top 5) is 2.7% at a score of 55, 6.2% at 75 and 6.4% at 85. So the pitch lever is "do not have a weak pitch"; polishing a good one further buys nothing in this model.

**Fastest path:** the "everything you control" launch on a Saturday, and a second launch 3–4 weeks later. After 2 launches
your own record puts you at about the level of an active hunter. Getting a top-10% hunter to post launch 1 starts you near
step 3, at P(top 5) 71%, and saves about 2 months.

### Why /try goes first
- It is the most demo-able product: paste a URL and get a result.
- Every visitor who tries it on their own launch is a prospect for the Launch Pack.
- The board (step 2) needs a few weeks of public live accuracy before it is credible.

Each launch is a distinct product. Re-launching the same product needs a major update. That rule sets the 3–4 week spacing,
together with the time to ship a real v1 of the next product.

## (superseded) What "everything you control" means in practice
- **3 makers on the page:** real team members or contributors, each with a complete profile.
- **Pitch score 75 or higher:** test tagline and description variants through the pitch scorer before launch day. This one is
  cheap to raise.
- **9 images plus a video.**
- **Launch-day reach:**
  - founder posts on X and LinkedIn that show the product;
  - one honest write-up each on HN (Show HN), a relevant subreddit and one newsletter or press outlet.
  - Share what the product does and invite people to try it. Never ask for upvotes; Product Hunt penalizes that, and it is
    against the rules.
- **A Product Hunt account that is older and active:** comment usefully on other launches in the weeks before.

## (superseded) Product definitions before Nov 17: Daily Forecast, Persona Panel, Launch Pack

Replaced by Competitor Radar, User Testing and the Market Simulator. Kept for the record.

### Answers to the four sequence questions [JUDGMENT]

1. **The line between launch 1 (/try) and launch 3 (Panel).** /try answers "where will this page land?": one URL, one
   fixed Product Hunt audience, one rank range, and the three most common reactions as a short summary. The Panel answers
   "what does each kind of person think, and which version is better?": reactions split by segment, two or more versions
   side by side, segments the user defines, follow-up questions, any page and not only a launch page. Held back from
   launch 1 until launch 3: the per-segment view, version comparison, custom segments, follow-up questions, export.
   /try's wording changes from "simulated reactions" to "the three reactions you are most likely to get", so launch 3 is
   not read as a feature of launch 1.
2. **Version comparison goes to launch 3.** It is the Panel's core job and its strongest reason to exist. It was the most
   requested feature, so /try says plainly that it is coming and collects emails for it. That list is launch 3's first
   audience. If the build for launch 1 has slack, it is not spent on this.
3. **The board runs publicly from day one, unlaunched.** It is already live and its public daily score is the proof
   launch 2 needs; taking it down would throw away two months of record. This bends principle 1 only for the bare board.
   What is held back for launch 2 is everything that makes it a product: the reason behind each forecast, the weekly
   and monthly forecasts, the before-votes-show forecast as a public feature, the full scored archive, and a daily email.
4. **The API is a fifth launch, not part of launch 4.** It has a different user (developers and agencies) and would dilute
   the Launch Pack's one job. Earliest date: August 2027. It is the first thing cut from this plan's scope.

**Challenge to the starting sequence:** none on the order. The data backs /try first (pitch 86, the easiest to try) and
the board second (pitch 88, and it needs the record). The one change is launch 4's day, decided by whether a hunter posts it.

### How feedback on product 1 defines products 2, 3 and 4

**State today.** Product 1 has no real users yet, so there is no real feedback. What exists is the persona panel's
feedback on the /try page [MODEL]: 24 personas from four voter groups (about 5,500 real people behind them). The table
below builds each later product from that. **On Dec 6 the real comments from launch 1 replace the "asked by" column**, and
the rules under the table decide what changes.

| What people asked of product 1 (/try) | Asked by [MODEL today, REAL after Dec 5] | Goes into | As |
|---|---|---|---|
| "How accurate is this, and how do you know?" Show the historical record, the margin of error | All four groups; first question in each | **Product 2, Daily Forecast** | The full scored archive: every forecast, hit and miss, since Nov 2026 |
| Which inputs carry the most weight? Does it count the hunter, the day, how many launches there are? | Tech innovators, launch veterans, product launchers | **Product 2** | The reason behind each forecast, launch by launch |
| What about launches that surge late in the day? | Tech innovators | **Product 2** | The before-votes-show forecast beside the midnight one, each scored |
| Can I compare two versions of my description? | Tech innovators, launch veterans; the most requested feature | **Product 3, Persona Panel** | Version comparison, side by side |
| Can I see reactions split by audience segment? Define my own segments? | Launch veterans, tech innovators | **Product 3** | Per-segment view and custom segments |
| Can I test headlines and calls to action? Are answers specific to my product? | Product launchers | **Product 3** | Follow-up questions on any page, not only a launch page |
| Does it look at screenshots and video, or only text? | Product launchers | **Product 3** | The panel reads the page's images |
| Will it suggest improvements? Are the fixes specific enough to act on today? | Product launchers, launch veterans | **Product 4, Launch Pack** | The pre-launch audit: named fixes, each with its expected effect |
| Does it account for my own network and community? | Launch veterans, product launchers | **Product 4** | The audit takes the maker's own reach and hunter as inputs |
| How is it validated after a launch? | Tech innovators | **Product 4** | The post-mortem: what we predicted against what happened |
| Is there an API? Can I export? | Tech innovators | Product 5, later | API |
| Is it understandable if I am not technical? Does it work for an unpolished product? | Curious observers | **Product 1, now** | Plain-language summary; a note on what it needs to work |
| How fresh are the profiles? What does it ignore? | Tech innovators | **Product 1, now** | The "what this uses and what it ignores" block |

**Rules once real feedback exists (applied in week 1 of each cycle).**
1. Every real comment, question and complaint from the launch and from /try users is tagged to a theme. Themes are ranked
   by how many different people raised them, not by how loud one person was.
2. The next product's scope is the top themes that fit its job. A theme that fits no planned product is added to the one
   it is closest to, or dropped with a written reason.
3. **The order can change.** If version comparison or segments is the top real theme after launch 1, by a clear margin
   over accuracy and reasons, product 2 becomes the Persona Panel and the Daily Forecast moves to April. The board loses
   nothing by waiting: it gains two more months of public record.
4. The panel's predictions for product 1 are scored against the real comments (theme recall and precision). That score is
   published, and it is product 3's proof.
5. Panel feedback is used only where real feedback is silent, and is marked as such.

**Competitors.** 30 competitors, 7–8 per product, are in Part 3 of this file: pitch score, real Product Hunt
finish from held data, /try range, the panel's concerns, what they do better and what we do better. Across all four:
none shows a daily accuracy score; several have custom segments, follow-up questions, version comparison and an instant
single number, which we lack today. The three that finished #1 were posted by hunters with 25, 33 and 286 prior launches.

**Real comments on the competitors' own launches [REAL, thin].** We hold comments for 12 launches from 2026 (9 of the 22
competitors plus 3 close relatives): 67 commenters on the /try job, 23 on the board job, 64 on the panel job, 57 on the
Launch Pack job. Most themes have 1–3 people, so they are leads, not findings. Details: Part 3 of this file.
- **Best-supported theme in the whole plan:** "how accurate is synthetic feedback compared with real users?" (6
  commenters across three panel-job launches, 5 on the /try job). The published accuracy record answers it.
- **Launch Pack has no real demand evidence yet.** Launch-tool users asked about brand voice and control over generated
  content (7, 4 and 3 commenters) and a free trial (3). Nobody asked for a forecast, an audit or a post-mortem.
- **Board job:** 4 commenters praised a competitor for helping pick a launch date; 2 asked what the product predicts for
  its own launch.
- **Planned features with no real comment behind them:** the before-votes-show forecast for late surges, follow-up
  questions on any page, the plain-language summary, the pre-launch audit with named fixes. Version comparison has 2.
- **Three things real comments raise that the plan lacked, now added:**
  1. A confidence score on each predicted theme (launches 1 and 3). One commenter called half of a competitor's themes noise.
  2. Our own forecast for our own launch, published in advance and scored afterwards (every launch, starting Dec 5).
  3. A fix for synthetic users that always agree. Our panel rated nearly every persona "high interest" for all four of our
     products, so this is a ship gate for launch 3.

**Pitch scores are not forecasts.** Re-scored outside its own launch day, a product's score moves by about ±15 points and
shows no relation to real rank (−0.13, n 22). Read our 75–88 as "at least 75"; the model is flat above 75 anyway.

### Launch 1. Launch Simulator (/try). Saturday Dec 5 2026

- **Job and user.** A maker pastes a URL and sees where the launch would land, before posting.
- **World-class claim (after the competitor run).** "The only launch rehearsal checked against real launches every day."
  **Test before launch day:** nightly forward score of the predicted reactions (theme recall and precision against a
  fixed question list) over 30 or more days, shown on the page. The rank range stays on the page with its 80% coverage
  [REAL, backtest] but is not the claim. No competitor publishes a daily accuracy score [30 competitors checked].
  Today's forward figures rest on 11 launches only, so the 30 days matter.
- **In.** One URL in; a rank range; the three most likely reactions; the measured accuracy with its limits above the fold;
  a "what this uses and what it ignores" block; a plain sentence for people who have never launched.
- **Held back.** Per-segment reactions, version comparison, custom segments, follow-up questions (launch 3). The reason
  behind a forecast, weekly and monthly views, email (launch 2). Reports, a pre-launch audit, post-mortem (launch 4).
- **Competitors** (Part 3 of this file): HuntOMeter, Roast My Landing Page AI, MockUsers, Wynter's free
  grader, and three Product Hunt launches. Closest real finishes: a simulated-persona message tester #3 of 21 (hunter
  with 479 prior launches); a launch-critique tool #9 of 29 [REAL].
- **Three things to beat [JUDGMENT from the run].** (1) A one-input, instant answer (HuntOMeter, Chaos Simulator): ours
  must answer in seconds from a URL alone. (2) A headline accuracy number: Articos claims 86% and ours has none above
  the fold; none publishes a score every day. (3) Output worth sharing: a founder shares a roast; nobody shares a rank
  range of 4 to 41.
- **Feedback that shaped it.** Real users: none yet, there has been no launch; 5–10 real makers test it in week 7 below.
  Panel [MODEL]: every voter group first asks "how accurate is this, and how do you know?"; then what the model does not
  see; the most requested feature is version comparison.
- **Significant-update case.** First post; none needed.
- **Day.** Saturday. Row A: 17.6% top 5 and 50.5% top 10 on a Saturday against 3.0% top 5 on Tue–Thu [MODEL]. Real
  zero-record launches: 19.9% top 5 on weekends against 6.9% overall (n 423 and 3,142) [REAL]. Cost: a Saturday has about
  62% of a Tuesday's votes [REAL].
- **Odds.** Top 5: 17.6 [10.7, 24.3] raw, 13.3 [8.9, 18.4] scaled. With an active hunter: 56.9. With 3 makers with reach: 30.2.
- **Ship gate (all true on Dec 2, go or no-go).**
  - "Free to try, no signup" is true, and the run limits are raised for launch day. Today /try allows 150 runs a day in
    total and 3 an hour per address; a launch day would hit that by mid-morning.
  - The accuracy number on the page is current and shows its day count.
  - Page fixes 1, 2, 5 (as "coming") and 8 from the fix list are live.
  - 5–10 real makers have used it and their unanswered questions are answered on the page.
- **Cut-line if the build runs late.** First to go: the plain-language summary, then visual polish of the result. Never
  cut: the accuracy block and the raised run limits. The date moves to Dec 12 only if the coverage test fails.
- **Fallback.** Outside the top 10 (about 50% likely): launch 2 keeps its date; the model gives it the same odds as no
  record. Not featured: treat the day as a soft launch, collect the comments, and file a relaunch request with the fixes.

### Launch 2. Daily Forecast. Saturday Feb 6 2027

- **Job and user.** Anyone who follows Product Hunt sees which launches will finish on top today, before votes are visible,
  with the reason for each.
- **World-class claim (candidate).** "Names the day's top 3 before any votes show, and has published every hit and miss
  since November 2026." **Test:** live top-3 hit over at least 75 scored live days, shown beside two named simple baselines.
  Closest competitor: hunted.space, the incumbent for live launch stats, which already has a predictor; ours is published
  before votes are visible and graded in public every day [JUDGMENT]. Real finishes: a Product Hunt analytics extension
  #15 of 18; a prediction benchmark #3 of 41 with a hunter with 279 prior launches [REAL]. Today: 73.8% over 14 live days at the before-votes point [REAL, forward]; backtest 72.2%
  over 12 days. Small n today; that is why this launch waits.
- **In.** The reason behind each forecast; weekly and monthly forecasts; the full scored archive; a daily email.
- **Held back.** Anything about the user's own page (that is /try) and segments (launch 3).
- **Feedback that shaped it.** Week 1 of this cycle collects every real comment from launch 1 and scores what the panel
  predicted against it. Panel today [MODEL]: worry that forecasts can be gamed or become self-fulfilling; the page states
  that forecasts use only public inputs and that we never help anyone collect votes.
- **Significant-update case.** A different user (watchers and investors, not makers testing a page) and a different job
  (today's ranking), delivered as a separate app surface.
- **Day.** Saturday, for rank. A watcher product also suits a calm day.
- **Odds.** Row A: 27.5 [19.0, 35.7] expected. By launch 1's finish: rank 1–3 68%, 4–5 53%, 6–10 27%, 11+ about 17%.
- **Ship gate.** 75+ scored live days on the page; every published number matches the store; the email works.
- **Cut-line.** First to go: monthly forecast, then the email. Never cut: the scored archive and the reasons.
- **Fallback.** If launch 1 missed the top 10, nothing changes here. If not featured, same as launch 1.

### Launch 3. Persona Panel. Saturday Apr 10 2027

- **Job and user.** A product or marketing team puts any page in front of audience segments built from real voting
  behaviour, compares versions, and defines its own segments.
- **World-class claim (after the competitor run).** "The only synthetic audience with a published score against what
  real people said." **Test:** theme precision against the real comments on our own launches 1 and 2 and on 100 or more
  other launches. One definition everywhere: **theme recall 61%, precision 52%, on 167 launches** [REAL, backtest].
  Precision beats pulling real comments from similar past launches (52% against 36%); recall does not (61% against 65%),
  so the claim is about precision and the published score, not recall.
- **Competitors.** Synthetic Users, Wynter (real people), and six Product Hunt launches. Real finishes: synthetic users
  inside dev tools #1 of 20 (hunter with 286 prior launches); synthetic-population research #25 of 26 (first-time hunter)
  [REAL]. They have custom segments, follow-up questions and version comparison; we must match those and add the score.
- **In.** Per-segment reactions; version comparison; custom segments; follow-up questions; export.
- **Held back.** Done-for-you reports and human review (launch 4); programmatic access (API, later).
- **Feedback that shaped it.** The email list from /try's "version comparison is coming"; the real comments from launches 1
  and 2 against the panel's predictions, published as the product's proof. Panel today [MODEL]: privacy of the people behind
  the personas; the page states that personas are groups of 20 or more built from public voting history.
- **Significant-update case.** A different user (teams doing user research on any page, not makers forecasting a launch)
  and new functionality that the earlier posts did not have.
- **Day.** Saturday, unless a hunter with a record posts it; then Tuesday for traffic, because buyers of research tools
  are at work.
- **Odds.** Row A: 31.6 [21.7, 40.8] expected; 20.9 / 43.5 / 62.7 after 0 / 1 / 2 earlier top-5 finishes.
- **Ship gate.** The recall and precision figures are current and on the page; version comparison gives the same answer
  when the two versions are swapped; the privacy statement is true of the data shown.
- **Cut-line.** First to go: export, then follow-up questions. Never cut: version comparison and the published score.
- **Fallback.** If launches 1 and 2 both missed the top 10, apply the stop rule below before building.

### Launch 4. Launch Pack (paid). Tuesday Jun 15 2027 with a hunter, else Saturday Jun 12

- **Job and user.** A founder pays for a full service across one launch: a pre-launch audit, the launch-day read, and a
  post-mortem.
- **World-class claim (after the competitor run).** "Tells you your odds before, and shows how right it was after."
  **Test:** the share of real finishes that fall inside the stated range, over 50 or more launches (20 of them pilots).
- **Competitors.** Launch toolkits, launch-kit generators and communities on Product Hunt, and one seller of upvotes.
  Real finishes: a social-posting agent #1 of 11; a launch toolkit #5 of 49; a launch-kit generator #13 of 21 [REAL].
  The page states that we never supply or solicit votes.
- **In.** The three reports; a real redacted sample; the price and the free tier. The tagline leads with what the founder
  gets (pitch score 80), never with "a paid package" (35) [MODEL].
- **Held back.** The API.
- **Feedback that shaped it.** The pilots' own results, and the questions real users asked on launches 1–3. Panel today
  [MODEL]: how specific is the "what to fix" advice.
- **Significant-update case.** A different job (a paid service with reports) for a different buyer.
- **Day.** The goal is traffic and buyers, so a weekday, but only if a hunter with a record posts it (24.2% top 5 on
  Tue–Thu with one, 13.8% without). Without one, Saturday (34.2%).
- **Odds.** Saturday 34.2 [23.6, 44.6]; Tue–Thu 13.8 [10.4, 17.6]; by record 21 / 37 / 56 / 62 on a Saturday after
  0 / 1 / 2 / 3 earlier top-5 finishes.
- **Ship gate.** 20 scored pilots; the sample report is real; every claim on the page has its number and day count.
- **Cut-line.** First to go: the post-mortem's automation (done by hand for the first customers). Never cut: the scoring.
- **Fallback.** If it is not featured, it still sells from launches 1–3's audience; the launch is not the only channel.

---

# Part 2. The feedback chain: each product built from feedback on the one before

E5, Nov 17 2026. Sequence: 1. Launch Simulator (/try), Dec 5 2026 → 2. Competitor Radar, Feb 6 2027 → 3. User Testing, Apr 10 → 4. Market Simulator, Jun 12/15.

The stages were run strictly in order. Product 2's pitches were written only after stage 1's feedback was ranked; product 3's only after product 2's own panel and its competitors' real comments were in; product 4's only after product 3's.

## How to read the numbers

- **Real outcome**: a competitor's own Product Hunt finish, and real comments on competitors' launches, both from our held data. No Product Hunt requests were made. We hold comments only for 2026 launches.
- **Model output**: pitch scores (deployed pitch prompt, Gemini, on 14 real line-ups), the persona panel, and the forced-choice panel.
- **Judgment**: product definitions, claims, "three things to beat", ship gates.
- **Real commenters (n)** counts distinct people who are not the hunter or a maker. **Panel groups** are the four voter groups behind the personas (tech innovators, launch veterans, product launchers, curious observers); each persona stands for 20 or more people.
- There is **no real feedback on any of our own products yet**. "Feedback on product N" means: real comments on the launches of competitors doing product N's job, first; the panel on product N's own page, second.
- Gemini cost for this run: $1.47.

## The panel fix: forced choice

**The problem.** The panel rated nearly every persona "high interest" for every product.

**What was tried.** Each persona sees the product inside a real day's line-up (3 days, 20–40 launches each), picks the 3 it would back, says where the product would sit in its own ordering of the whole line-up, and gives one reason it would not use it.

**First attempt failed the other way.** With all 24 personas in one call, every persona picked the same three products, and no test product was ever picked (0% for ours and for three competitors). The 24 personas are near-duplicates: 16 of 24 come from one voter group.

**What was used.** One persona per distinct segment (7–8 per product), weighted by the people behind it, plus the placement question. Chance of being picked is about 8%.

| Stage | Product | Whose | Picked in top 3 | Placed in top third | Mean place (0 = first, 100 = last) | Real finish |
|---|---|---|---|---|---|---|
| 1 | **Launch Simulator (/try)** | ours | 0% | 25% | 47 | not launched |
| 1 | Articos | competitor | 3% | 23% | 48 | #3 of 21 |
| 1 | Firstpass | competitor | 46% | 46% | 39 | #9 of 29 |
| 1 | HuntOMeter | competitor | 0% | 0% | 83 | none in our data |
| 2 | **Competitor Radar** | ours | 0% | 0% | 61 | not launched |
| 2 | HeadsUp | competitor | 8% | 35% | 40 | #1 of 8 |
| 2 | Glimpse | competitor | 0% | 0% | 57 | #14 of 15 |
| 2 | NODUS PH Radar for Product Hunt | competitor | 15% | 74% | 22 | #15 of 18 |
| 3 | **User Testing, end to end** | ours | 0% | 16% | 56 | not launched |
| 3 | TheySaid 4.0 | competitor | 33% | 100% | 7 | #1 of 20 |
| 3 | Jango | competitor | 0% | 39% | 40 | #12 of 67 |
| 3 | Synthetic Users (syntheticusers.com) | competitor | 0% | 0% | 52 | none in our data |
| 4 | **Market Simulator** | ours | 0% | 0% | 73 | not launched |
| 4 | Sapien | competitor | 0% | 0% | 61 | #25 of 26 |
| 4 | Plurai Simulation | competitor | 0% | 46% | 40 | #1 of 37 |
| 4 | Aaru | competitor | 0% | 12% | 55 | none in our data |

All model output; 7–8 segments × 3 days per product, so each row rests on 15–24 segment-days.

- **The share now varies**: from 0% to 46% picked, and mean place from 7 to 83.
- **It agrees with real finishes in part.** The competitor that really finished #1 of 20 gets the best placement (mean place 7, 33% picked). The two that really finished near the bottom (#14 of 15, #25 of 26) are never picked. But a Product Hunt analytics extension that really finished #15 of 18 is placed high (mean place 22), and a #1 finisher is never picked. Treat it as a rough ordering, not a forecast.
- **None of our four products was picked by any segment on any day.** Their mean places are 47, 61, 56 and 73. The Market Simulator is placed lowest although its pitch scored highest (82). The pitch judge and the forced-choice panel disagree; neither is validated for this.
- **By voter group there is little spread**: for our products every group picks 0%. The forced choice separates products, not groups.
- **The most useful output is the "reason not to use".** It gave the top theme for three of four products.

## Product 1. Launch Simulator (/try)

- **Job (judgment).** A maker pastes a URL and sees how the launch would land, before posting.
- **User.** Makers about to launch on Product Hunt.
- **World-class claim (candidate).** "The only launch rehearsal checked against real launches every day."
- **Test before launch day.** Nightly forward score: theme recall and precision of /try's predicted questions against real comments on that day's launches, 30+ consecutive days, against a fixed list of common questions. Today: recall 77% [67, 86], precision 51% [31, 70] on 11 launches (real outcome, small n).

### Stage 1 feedback, ranked (real commenters first, panel second)

**Real comments on 4 launches doing this job (67 commenters):** asked: how is accuracy quantified (4); does it work for non-English (2); how does it compare with real user testing (2); drafts, objections, pricing, images, personas from public data (1 each). Praised: seeing your launch as you build it (5).

**Panel on our /try page (model):** simulated reactions may not reflect real feedback or real outcomes (16 lines, all four groups); it is not a tool that builds or launches anything (5 lines, three groups); rank accuracy for unusual or crowded products (4, tech innovators); suggest improvements to the messaging (2, tech innovators and product launchers).

| Feature | The feedback theme it answers | From which feedback | Real commenters (n) | Panel groups |
|---|---|---|---|---|
| Measured accuracy with its limits, above the fold | How is accuracy quantified? | Competitors of product 1 | 4 | all four |
| A confidence mark on each predicted question | How does it compare with real user testing? | Competitors of product 1 | 2 | all four ("simulated may not reflect real") |
| Works from pasted draft text, and says so | Does it work on pre-launch drafts? | Competitors of product 1 | 1 | — |
| "What this uses and what it ignores" block | Rank accuracy for unusual or crowded products | Panel on /try | 0 | tech innovators |

**Held back, and the launch each belongs to:** Real comments on rivals (launch 2). Suggested fixes, version comparison, images (launch 3). Pricing and positioning tests (launch 4).

**Themes from earlier feedback this product does not answer:** First product; nothing earlier. Non-English pages (2 real commenters) are out of scope for all four launches: our voters and comments are English-language Product Hunt.

### Pitch (model output)

Best of three versions scored earlier: *Paste your URL, see how your launch would land*, 86 [83, 89].

### Competitors

| Competitor | Pitch score [95%] (model) | Real Product Hunt finish (real) | Forced choice: picked in top 3 / placed in top third / mean place, 100 = last (model) | Panel's top concerns (model) |
|---|---|---|---|---|
| **Articos**<br>*Launch with confidence, not gut instinct* | 56 [49, 61] | #3 of 21, 385 votes, 2026-09; hunter had 479 prior | 3% / 23% / 48 | How does Articos handle niche ICPs; How does Articos prevent bias in its simulated personas; What are the limitations of the simulated personas |
| **Firstpass**<br>*Actionable input so you nail every launch* | 67 [61, 74] | #9 of 29, 144 votes, 2026-07; hunter had 454 prior | 46% / 46% / 39 | Potential to add complexity to the launch process; The cost for small teams or individual makers; Accuracy of 'crit notes' and truncation simulation |
| **HuntOMeter** *(off Product Hunt; wording ours)*<br>*Predict your Product Hunt upvotes from your tagline* | 78 [71, 84] | none in our data | 0% / 0% / 83 | Accuracy of predictions is a concern; Tool might not account for external factors; Tool might encourage generic taglines |
| **ProductHunt Chaos Simulator**<br>*See what might happen on your Product Hunt launch day* | 76 [70, 81] | #4 of 6, 330 votes, 2025-02; hunter had 0 prior | — | How accurate are the predictions; How does it handle subjective human elements; Will the simulation be too generic |
| **Roast My Landing Page AI** *(off Product Hunt; wording ours)*<br>*Simulated target users roast your landing page* | 75 [71, 80] | none in our data | — | How does the AI ensure feedback is unbiased; How does the AI handle specific target audiences; How does the AI provide actionable feedback |

**The three things to beat (judgment):**
1. An instant single number from one input (a tagline-to-upvotes estimator).
2. A headline accuracy figure (a persona message-testing product claims 86%).
3. Output a founder wants to share (roast tools).

### Feedback on product 1 (this feeds the next product)

**Real comments on competitors' launches (real outcome):** 67 commenters on 4 held launches.
- Asked for: How is accuracy/effectiveness measured (4); Does it work for non-English languages (2); How does it compare to real user testing (2); Can it generate personas from public data (1); Can it help with pricing strategies (1); Can it identify customer objections (1); Can it 'look' at graphic illustrations (1); Can it refine buyer profiles over time (1); How does it stay updated with new LLMs (1); Can co-makers leave notes on drafts (1)
- Complained about or doubted: Confusing categories/tags/company info in editor (2); Lack of transparency on investment questions (2)
- Praised: Fast feedback/turnaround time (5); Seeing launch as you build it (5)

**Panel on our own page (model output), themes by number of lines and the groups raising them:**
- Simulated reactions may not fully capture nuanced real-world user feedback (8 lines; tech innovators, curious observers, launch veterans, product launchers)
- Simulated results may not reflect real-world launch outcomes (8 lines; tech innovators, curious observers, launch veterans, product launchers)
- Not a tool for building or launching products directly (5 lines; tech innovators, launch veterans, product launchers)
- Accuracy of rank prediction for unique or competitive products (4 lines; tech innovators)
- Simulator's ability to capture nuanced feedback or community 'vibe' (4 lines; tech innovators, launch veterans)
- Depth of technical questions for specialized products (3 lines; tech innovators, product launchers)
- Simulator's ability to handle niche or unusual products (2 lines; tech innovators, curious observers)

**Forced choice on our own page (model output):** picked by 0% of segments (chance about 8%); placed in the top third by 25%; mean place 47. By group: Tech Innovators: 0% picked, mean place 52 (n 12); Curious Observers: 0% picked, mean place 46 (n 3); Launch Veterans: 0% picked, mean place 42 (n 6); Product Launchers: 0% picked, mean place 37 (n 3).

- **Significant-update case (judgment).** First post; no significant-update case needed.
- **Ship gate.**
  - "Free to try, no signup" is true and run limits are raised for launch day.
  - The accuracy number on the page is current and shows its day count.
  - Our own forecast for this launch is published before the day.

## Product 2. Competitor Radar

- **Job (judgment).** A standing watch on your market: what launched in your space, how it landed, what real commenters asked for and complained about, and where your own backers are moving.
- **User.** Founders and product leads with named competitors; the same makers who used /try, after their launch.
- **World-class claim (candidate).** "The only competitor watch built from what real users said, counted by distinct people, with its tagging scored in public."
- **Test before launch day.** Before launch day, hand-label 300 real comments across 30 launches; publish the agreement of the automatic theme tagging with the hand labels, and the share of featured launches in a tracked space that appear in the digest within 24 hours. Neither number exists yet.

### Built from feedback on product 1

| Feature | The feedback theme it answers | From which product's feedback | Real commenters (n) | Panel groups |
|---|---|---|---|---|
| Real comments on rivals' launches, grouped into asked / complained / praised and counted by distinct people | Simulated reactions may not reflect real feedback | Product 1 (panel); product 1 competitors (real) | 2 ("how does it compare with real users") | all four (16 lines) |
| How each launch in your space finished, against its forecast | How is accuracy quantified? Rank accuracy for crowded products | Product 1 competitors (real); product 1 panel | 4 | tech innovators |
| Objections list: what users complained about on rivals | Can it identify customer objections? | Product 1 competitors | 1 | — |
| Which voter groups backed each rival, and where your backers are moving | Can personas come from public data? Niche products | Product 1 competitors; product 1 panel | 1 | tech innovators, curious observers |
| Daily and weekly digest; upcoming launches in your space | Real-time updates (2); upcoming-launch view praised (2) | Product 2's own competitors | 4 | tech innovators, launch veterans |
| Each theme shows its count and example wording, so noise is visible | Signal-to-noise worry (2); can it cluster recurring complaints (2) | Product 2's own competitors | 4 | tech innovators (accuracy of grouping, 5 lines) |

**Held back, and the launch each belongs to:** Acting on the findings: named fixes and task runs (launch 3). "What if we changed X" (launch 4). Other platforms than Product Hunt.

**Themes from earlier feedback this product does not answer:** **Suggest improvements** (panel, 2 lines): Radar reports, it does not prescribe; goes to launch 3. **Version comparison and images** (1–2 real commenters): launch 3. **Pricing tests** (1): launch 4. **Non-English** (2): out of scope.

### Pitch versions (model output)

| Version | Tagline | Pitch score [95%] (model) | Outscores this share of real launches |
|---|---|---|---|
| 1 | What launched in your space, and what real users said about it | 68 [62, 74] | 79% |
| 2 | Your competitors' launch day, read for you every morning | 75 [71, 79] | 87% |
| **3** | **See what users ask your competitors for, before you build it** | **75 [71, 79]** | 94% |

Best: *See what users ask your competitors for, before you build it.* Real comments on real launches are the cheapest user research there is. Radar reads them for every launch in your space, groups them into what users asked for, complained about and praised, counts distinct people, and shows which voter groups backed each rival. Updated daily. No simulated answers.

### Competitors

| Competitor | Pitch score [95%] (model) | Real Product Hunt finish (real) | Forced choice: picked in top 3 / placed in top third / mean place, 100 = last (model) | Panel's top concerns (model) |
|---|---|---|---|---|
| **HeadsUp**<br>*The first AI competitor monitoring agent* | 67 [63, 70] | #1 of 8, 598 votes, 2025-08; hunter had 2 prior | 8% / 35% / 40 | How does HeadsUp ensure data accuracy; How does HeadsUp handle data privacy and security; How does HeadsUp differentiate minor updates from strategic moves |
| **Glimpse**<br>*The competitive intelligence agent* | 71 [68, 74] | #14 of 15, 106 votes, 2026-07; hunter had 0 prior | 0% / 0% / 57 | How does Glimpse ensure data accuracy; How does Glimpse handle data privacy and security; How does Glimpse differentiate genuine moves from noise |
| **NODUS PH Radar for Product Hunt**<br>*Product Hunt analytics beyond the daily leaderboard* | 73 [62, 83] | #15 of 18, 97 votes, 2026-06; hunter had 1 prior | 15% / 74% / 22 | Browser support beyond Chrome; How accurate are launch predictions; How does it compare to other tools |
| **Competely AI Agent**<br>*Instantly find, analyze, and track your competitors with AI* | 68 [65, 72] | #5 of 16, 327 votes, 2025-04; hunter had 33 prior | — | How does the AI handle niche markets or specific competitor types; How does the tool ensure the accuracy and recency of competitive data; Are there any plans for a native Mac app or desktop client |
| **Fruitful**<br>*Track competitors instantly. Juicy insights every day.* | 51 [47, 56] | #2 of 8, 417 votes, 2025-10; hunter had 253 prior | — | accuracy of change detection; scalability for tracking competitors; potential for false positives |
| **Parano.ai**<br>*Never miss a competitor's move* | 68 [62, 73] | #33 of 39, 78 votes, 2026-06; hunter had 0 prior | — | How does it ensure data accuracy and reliability; How does it handle false positives or irrelevant activities; How does it ensure insights are relevant and actionable |
| **hunted.space** *(off Product Hunt; wording ours)*<br>*Real-time Product Hunt launch stats* | 85 [82, 89] | none in our data | — | AI predictor accuracy and validation; AI predictor handling of niche products/limited data; Pricing model and free trial availability |
| **Visualping** *(off Product Hunt; wording ours)*<br>*Website change monitoring with AI summaries* | 60 [54, 66] | none in our data | — | How does AI handle complex or JavaScript-heavy pages; How does AI differentiate between minor and significant changes; How does it handle pages behind a login |
| **Crayon** *(off Product Hunt; wording ours)*<br>*Competitive intelligence platform for go-to-market teams* | 31 [26, 35] | none in our data | — | Data accuracy and filtering irrelevant information; Seamless integration into existing sales processes; Usability and actionability of battlecards for sales reps |

**The three things to beat (judgment):**
1. A #1 finish: an AI competitor-monitoring agent took first place on an 8-launch day with 598 votes. Monitoring is a proven Product Hunt category.
2. Breadth: website-change monitors and enterprise platforms watch pricing pages, ads and emails. We watch launches and comments only.
3. The habit: makers already keep a live launch tracker open on launch day.

### Feedback on product 2 (this feeds the next product)

**Real comments on competitors' launches (real outcome):** 56 commenters on 8 held launches.
- Asked for: Does it support all app store categories or other platforms (3); What signals does it use for predictions and how are they weighted (3); How does it measure lost demand in AI answers (3); Can it group similar complaints or cluster recurring themes (2); How does it handle data ingestion and real-time updates (2); How does it identify trending posts early (2); Does it track comment velocity as a signal (2); Can it compare current trajectory to past launches by category (2); Can it generate content briefs or suggest actions based on findings (2); What are the differences from similar products (1); How does it track competitor pricing, especially hidden ones (1); How does it validate information for accuracy (1)
- Complained about or doubted: Worry about signal-to-noise ratio and filtering important changes (2); Worry about optimizing for signals corrupting the model (1)
- Praised: Smart angle/idea to mine low-star reviews for product ideas (4); Useful for problem identification and starting a startup (2); Upcoming launches and momentum view is genuinely useful (2); Genuinely useful tool for competitive intelligence (2); The AI analysis layer is a nice touch (1); Automatically surfacing pricing and messaging shifts is needed (1); Finding about team size and engagement being stronger signal is interesting (1); Benchmarking before launch is useful and often skipped (1); The value is in the threshold function, not just a stream (1); Great way to find hidden gems beyond popular AI tools (1); PH analytics beyond the daily leaderboard is something every founder needs (1); The AI search part is especially interesting (1); Positioning as an agent makes workflow easier to picture (1); The AI-answer-visibility signal is the freshest part (1)

**Panel on our own page (model output), themes by number of lines and the groups raising them:**
- Not a direct tool for building, launching, or personal use (21 lines; tech innovators, launch veterans, curious observers, product launchers)
- Accuracy and bias of AI in comment interpretation and grouping (5 lines; tech innovators)
- Data sources, filtering, and ethical implications of comment analysis (3 lines; tech innovators)
- Scalability, latency, and update frequency for competitor tracking (3 lines; tech innovators, launch veterans)
- Integration capabilities with existing product management tools (3 lines; tech innovators, product launchers)
- Granularity and detail of 'voter groups' analysis (3 lines; tech innovators)
- Pricing model, cost-effectiveness, and free trial availability (2 lines; tech innovators)

**Forced choice on our own page (model output):** picked by 0% of segments (chance about 8%); placed in the top third by 0%; mean place 61. By group: Tech Innovators: 0% picked, mean place 63 (n 12); Launch Veterans: 0% picked, mean place 55 (n 3); Curious Observers: 0% picked, mean place 59 (n 3); Product Launchers: 0% picked, mean place 62 (n 3).

- **Significant-update case (judgment).** A different use case and a different moment: /try is used once before a launch; Radar is a subscription used every week after it, on competitors' products, not your own.
- **Ship gate.**
  - Theme-tagging agreement with hand labels is measured and on the page.
  - Coverage: every featured launch in a tracked space appears within 24 hours, for 14 straight days.
  - Product 1's real comments have been tagged with it and published: that is the first Radar report.

## Product 3. User Testing, end to end

- **Job (judgment).** Simulated users do real tasks on your product and on two competitors; you get a side-by-side comparison report. The persona panel folds into it.
- **User.** Product teams and founders deciding what to fix next; agencies running audits.
- **World-class claim (candidate).** "The only user test that runs the same tasks on you and your competitors, and shows how often its findings match what real users later said."
- **Test before launch day.** On products with real launch comments, the share of real complaint themes that the task runs found (complaint recall) and the share of findings real users confirmed. Today the nearest figure is weak: complaint recall 24% [9, 38] on 11 launches (real outcome). The claim cannot be made until this is measured on at least 30 products and published as it is.

### Built from feedback on product 2

| Feature | The feedback theme it answers | From which product's feedback | Real commenters (n) | Panel groups |
|---|---|---|---|---|
| Task runs on your own product: sign up, search, compare, finish the job | "Not a tool that does anything for my product" | Product 2 (panel, reason not to use) | 0 | all four (21 lines; the top theme) |
| The report ends in named fixes, in order | Can it suggest actions from the findings? | Product 2 competitors (real); product 1 panel | 2 | tech innovators, product launchers |
| The same tasks on two competitors, side by side | Compare with similar products and past launches | Product 2 competitors | 3 | — |
| Every finding links to its log and screenshot | Signal-to-noise; accuracy and bias of grouping | Product 2 competitors (real); product 2 panel | 2 | tech innovators (5 lines) |
| Compare two versions of your own product | Compare versions; A/B test without running one | Product 1 competitors (carried over) | 2 | tech innovators |
| The simulated users see the page, images included | Can it look at images? | Product 1 competitors (carried over) | 1 | product launchers |
| Results by voter group (the old persona panel) | Granularity of voter groups | Product 2 panel | 0 | tech innovators (3 lines) |

**Held back, and the launch each belongs to:** Changing the market, not the page: price, positioning, competitor responses (launch 4). CI and API integration (after launch 4).

**Themes from earlier feedback this product does not answer:** **Which signals and how weighted** (3 real commenters), **coverage of other platforms** (3), **real-time updates** (2): these are Radar's own job and stay in product 2. **Pricing and a free trial** (panel, 2 lines): a pricing decision, not a feature.

### Pitch versions (model output)

| Version | Tagline | Pitch score [95%] (model) | Outscores this share of real launches |
|---|---|---|---|
| **1** | **Simulated users do real tasks on your product and your rivals'** | **69 [65, 74]** | 83% |
| 2 | A user test of you against your competitors, done overnight | 64 [59, 69] | 71% |
| 3 | Find where users pick your competitor, and what would change it | 68 [63, 72] | 76% |

Best: *Simulated users do real tasks on your product and your rivals'.* Give us your URL and two competitors. Six simulated users, built from real voter groups, each try six real tasks on all three products in a real browser. You get a side-by-side report: where each user got stuck, which product they would choose and why, and the named fixes that would change the result.

### Competitors

| Competitor | Pitch score [95%] (model) | Real Product Hunt finish (real) | Forced choice: picked in top 3 / placed in top third / mean place, 100 = last (model) | Panel's top concerns (model) |
|---|---|---|---|---|
| **TheySaid 4.0**<br>*See how users will react, right where you build.* | 65 [61, 69] | #1 of 20, 393 votes, 2026-10; hunter had 286 prior | 33% / 100% / 7 | How does this handle complex, multi-step user flows; What are the limitations of synthetic users; How does this ensure synthetic users reflect target audience |
| **Jango**<br>*Test multi-user apps with AI agents that act like real users* | 78 [75, 80] | #12 of 67, 75 votes, 2026-09; hunter had 1 prior | 0% / 39% / 40 | How does Jango handle complex user flows; What is the learning curve for complex scenarios; How does Jango handle data privacy |
| **Synthetic Users (syntheticusers.com)** *(off Product Hunt; wording ours)*<br>*User research without the users* | 70 [66, 73] | none in our data | 0% / 0% / 52 | How reliable is the feedback from synthetic users; How to prevent generic or biased feedback; How to ensure diverse user behaviors and biases |
| **Snap**<br>*Instant usability testing with AI personas* | 72 [67, 76] | #8 of 10, 203 votes, 2025-10; hunter had 168 prior | — | AI personas missing nuanced human behavior; Accuracy and depth of AI-generated recommendations; Potential for AI personas to provide superficial feedback |
| **Uxia**<br>*Validate your User flows UX & UI in seconds with AI* | 60 [57, 64] | #1 of 5, 535 votes, 2025-09; hunter had 25 prior | — | How does Uxia handle complex user flows; How accurate are synthetic users compared to real users; How customizable are the synthetic user personas |
| **Userology AI**<br>*The AI user research agent for busy product teams* | 74 [71, 78] | #2 of 11, 347 votes, 2025-12; hunter had 89 prior | — | How does AI ensure quality of recruited users; How does AI handle nuanced feedback; How does AI handle edge cases |
| **Velozity**<br>*AI-Powered instant user research tool* | 59 [52, 65] | #2 of 8, 284 votes, 2025-05; hunter had 0 prior | — | Accuracy and bias of AI-generated insights; Depth and realism of AI responses; Data privacy and security |
| **Testifly**<br>*Autonomous AI QA. Zero prompting. Zero maintenance.* | 73 [68, 78] | #3 of 38, 266 votes, 2026-11; hunter had 447 prior | — | AI might miss critical user paths or edge cases; Potential for false positives or missed edge cases; Difficulty integrating with less common web frameworks |
| **Articos**<br>*Launch with confidence, not gut instinct* | 56 [49, 61] | #3 of 21, 385 votes, 2026-09; hunter had 479 prior | — | How does Articos handle niche ICPs; How does Articos prevent bias in its simulated personas; What are the limitations of the simulated personas |

**The three things to beat (judgment):**
1. Real finishes: three products in this job finished #1, #1 and #2 (synthetic users inside dev tools; AI UX validation; an AI research agent with real users).
2. Autonomous QA: a zero-prompt AI tester finished #3 of 38. Users asked it about test failures and complex flows (4 and 3 commenters); ours must not get stuck.
3. Real humans: products that recruit real users set the standard. Ours is faster and cheaper, not equivalent.

### Feedback on product 3 (this feeds the next product)

**Real comments on competitors' launches (real outcome):** 93 commenters on 8 held launches.
- Asked for: How does the product compare to competitors (13); Can the product test specific elements or scenarios (13); How does the product work technically (7); Are there plans for integrations or scheduling features (5); How does the product handle test failures or changes (4); How does the product handle complex user flows or permissions (3); Can the product generate or refine personas (3); How to set up tests without existing written tests (1); How long does a synthetic test take (1)
- Complained about or doubted: Concerns about the accuracy of synthetic feedback/data (2); What happens if test descriptions are underspecified (1)
- Praised: The product helps with fast feedback loops and iteration (11); The product helps with testing before shipping/launching (9); The product provides detailed and useful insights/output (9)

**Panel on our own page (model output), themes by number of lines and the groups raising them:**
- simulated users cannot provide real-world, nuanced feedback (5 lines; tech innovators, launch veterans, curious observers)
- simulated users may not accurately reflect real user behavior (4 lines; tech innovators, launch veterans, curious observers)
- how to ensure simulated users reflect nuanced human behavior (3 lines; tech innovators, launch veterans)
- how to handle complex user flows or dynamic content (3 lines; tech innovators, launch veterans)
- how to prevent simulated users from getting stuck or errors (3 lines; tech innovators)
- how to ensure simulated users explore beyond predefined scripts (2 lines; tech innovators)
- integration with existing tools or CI/CD pipelines (2 lines; tech innovators, launch veterans)

**Forced choice on our own page (model output):** picked by 0% of segments (chance about 8%); placed in the top third by 16%; mean place 56. By group: Tech Innovators: 0% picked, mean place 56 (n 9); Launch Veterans: 0% picked, mean place 56 (n 3); Curious Observers: 0% picked, mean place 52 (n 3).

- **Significant-update case (judgment).** A different use case: products 1 and 2 read pages and comments; this one operates the product itself, and a competitor's, in a browser. A different user too: product teams after launch, not makers before it.
- **Ship gate.**
  - Complaint recall and confirmed-finding share are measured on 30+ products and published, whatever they are.
  - A run completes on 9 of 10 arbitrary sites without getting stuck.
  - The interest rating is gone from the panel, and no forced-choice score replaces it (it failed validation; see "Is the forced choice a real signal?").

## Product 4. Market Simulator

- **Job (judgment).** Propose a change (feature, price, positioning, launch) and see who adopts, who switches, who you lose and why; in War Game mode competitors respond over three rounds.
- **User.** Founders and strategy leads before a costly decision.
- **World-class claim (candidate).** "The only market simulator whose every prediction is scored in public afterwards."
- **Test before launch day.** One scored claim for June: for each new launch, the predicted share of backers by voter group against the real share, over the 30 days before launch day, published with its error. Today (numbers given by the orchestrator, not re-measured here): 89,027 complete people; person-level top-3 hit about 57%; backer recall 25–29%. Scope: Product Hunt market only, answers by group.

### Built from feedback on product 3

| Feature | The feedback theme it answers | From which product's feedback | Real commenters (n) | Panel groups |
|---|---|---|---|---|
| Every prediction scored in public | Simulated users may not reflect real behaviour | Product 3 (panel); product 3 competitors (real) | 2 ("accuracy of synthetic feedback") | tech innovators, launch veterans, curious observers (9 lines; the top theme) |
| You propose a specific change and test that scenario | Can it test specific elements or scenarios? | Product 3 competitors | 13 | — |
| Custom segments | Can it generate or refine personas? | Product 3 competitors (real); product 3 panel | 3 | tech innovators (2 lines) |
| Pricing and positioning as testable changes | Can it test pricing strategies and objections? | Product 1 and 3 competitors (carried over) | 2 | — |
| Answers come with a band, and can be "no clear signal" | Band or point estimate (4); does it ever return no signal (1) | Product 4's own competitors | 5 | — |
| You against named competitors; War Game responses | How does it compare with competitors? | Product 3 competitors | 13, but see note | — |

Note on the last row: the 13 commenters asked how the tool differs from alternatives, not for a competitor simulation. It is weak support for War Game mode, which has no direct real-comment support.

**Held back, and the launch each belongs to:** Markets beyond Product Hunt. Answers about individuals. More than one scored claim.

**Themes from earlier feedback this product does not answer:** **Complex flows, getting stuck, test failures** (4 + 3 real commenters): product 3's own reliability work. **Integrations and scheduling** (5): the API, after June. **How it works technically** (7): a methodology page, not a product.

### Pitch versions (model output)

| Version | Tagline | Pitch score [95%] (model) | Outscores this share of real launches |
|---|---|---|---|
| **1** | **Propose a change, see who adopts, who switches and who you lose** | **82 [78, 86]** | 96% |
| 2 | A war game for your next launch: you move, competitors respond | 74 [70, 79] | 91% |
| 3 | The market simulator that publishes its own score | 54 [45, 64] | 45% |

Best: *Propose a change, see who adopts, who switches and who you lose.* Test a feature, a price, a positioning or a launch against a modelled market before you ship it. Built on 89,027 real Product Hunt voters and every product they backed. See which voter groups move toward you, which stay with a competitor, and why. Product Hunt market only, answers by group, and every prediction is scored in public afterwards.

### Competitors

| Competitor | Pitch score [95%] (model) | Real Product Hunt finish (real) | Forced choice: picked in top 3 / placed in top third / mean place, 100 = last (model) | Panel's top concerns (model) |
|---|---|---|---|---|
| **Sapien**<br>*AI market research with synthetic populations* | 62 [59, 64] | #25 of 26, 65 votes, 2026-10; hunter had 0 prior | 0% / 0% / 61 | How to ensure synthetic populations accurately reflect real-world nuances; How to handle biases in synthetic population generation; How to validate the accuracy of synthetic audience responses |
| **Plurai Simulation**<br>*A simulated world that makes your agent improve on every run* | 65 [60, 70] | #1 of 37, 382 votes, 2026-11; hunter had 410 prior | 0% / 46% / 40 | overhead of running simulations; how to handle complexity of mocking APIs; how to ensure diverse synthetic data |
| **Aaru** *(off Product Hunt; wording ours)*<br>*Simulate populations to predict how they will respond* | 65 [60, 69] | none in our data | 0% / 12% / 55 | Potential for AI bias or misuse; Cost and accessibility for smaller businesses; Complexity and learning curve for users |
| **Artificial Societies** *(off Product Hunt; wording ours)*<br>*Simulate your audience as a society of AI personas* | 63 [57, 68] | none in our data | — | accuracy of the simulation; transparency of AI decision-making; scalability and resources required |
| **Simile** *(off Product Hunt; wording ours)*<br>*A foundation model for human behaviour* | 69 [66, 72] | none in our data | — | Accuracy and bias of 'trained on interviews' data; Potential for oversimplification of human interactions; Ethical implications of simulating human behavior |
| **AI Creative Insights by Decode**<br>*Predict which ad wins before you spend on media* | 73 [69, 76] | #9 of 27, 110 votes, 2026-09; hunter had 1 prior | — | How does the AI handle different ad contexts; How accurate is the AI for diverse audiences; What are the limitations of the AI |
| **Foresight by Lightning Rod**<br>*Predict anything with AI* | 65 [60, 70] | #3 of 19, 227 votes, 2026-06; hunter had 212 prior | — | How does the API handle biases in historical data; What's the pricing model for the API; How does the API handle ethical implications of forecasting |

**The three things to beat (judgment):**
1. Money and brand: the off-Product-Hunt leaders in population simulation have raised $100 million or are valued at $1 billion. We cannot beat them on breadth; only on a public score.
2. Calibration: a forecasting API finished #3 of 19, and users praised its focus on calibration and asked for bands (2 + 4 commenters).
3. Our own panel: "too niche, complex or abstract" is the top reason not to use it (24 lines, all four groups), and it has the lowest forced-choice placement of our four products.

### Feedback on product 4 (this feeds the next product)

**Real comments on competitors' launches (real outcome):** 19 commenters on 3 held launches.
- Asked for: Does it return a calibration band or just a point probability (2); Does the API expose confidence intervals or just point predictions (2); How to validate calibration before full migration (1); Use cases for cybersecurity risk prioritization (1); How does calibration hold up under regime shifts (1); How is calibration drift handled and validated (1); Which real-world domains perform well, and where are frontier models better (1); How much better than prompting Claude, any benchmarks (1); How close are calculations to real campaign results (1); What data does the tool base its ad evaluation on (1); Does it ever return no clear signal, or always produce something (1)
- Complained about or doubted: Correlated predictions if many agents use the same model (1); Inconsistent pricing for the same video across models (1)
- Praised: Forecasting as a dedicated capability, not just an LLM feature (5); OpenAI-compatible API for easy integration (4); Faster creative testing for small teams, shows attention loss (3); Focus on calibration, which other tools skip (2); Trained on real-world outcomes, not just text patterns (1); Open-ended framing, not boxed into one niche (1)

**Panel on our own page (model output), themes by number of lines and the groups raising them:**
- Product's market simulation focus is too niche/complex/abstract (24 lines; tech innovators, curious observers, launch veterans, product launchers)
- How does the model account for Product Hunt community dynamics (10 lines; tech innovators)
- Can we simulate different launch strategies and their impact (8 lines; tech innovators, curious observers, launch veterans, product launchers)
- What are the data export and integration options (6 lines; tech innovators, product launchers)
- How does the model handle novel or niche products (4 lines; tech innovators, launch veterans)
- What is the pricing model and availability of a free tier (3 lines; tech innovators, curious observers)
- What are the limitations of the 'Product Hunt only' scope (2 lines; tech innovators, launch veterans)

**Forced choice on our own page (model output):** picked by 0% of segments (chance about 8%); placed in the top third by 0%; mean place 73. By group: Tech Innovators: 0% picked, mean place 72 (n 12); Curious Observers: 0% picked, mean place 69 (n 3); Launch Veterans: 0% picked, mean place 76 (n 6); Product Launchers: 0% picked, mean place 74 (n 3).

- **Significant-update case (judgment).** A different use case: products 1–3 describe what is; this one answers "what if". No earlier product takes a proposed change as input.
- **Ship gate.**
  - The one scored claim has 30 days of public record.
  - Every answer is by group, with a band; "no clear signal" is a possible answer.
  - The page says: Product Hunt market only.

## What the chain shows

- **One doubt runs through all four products: is the simulated thing real?** It is the top panel theme for products 1 and 3 and the top real-comment question on product 1's competitors. Product 2 answers it by using only real comments; product 4 answers it by scoring every prediction in public. Product 3 is the one that cannot answer it yet (complaint recall 24%).
- **The top reason not to use product 2 is that it does nothing to your own product.** That is the feature-by-feature reason product 3 exists, and it comes from the panel only (model output); no real commenter said it.
- **The best real support for any feature in the chain is for testing a specific scenario** (13 real commenters on user-testing launches). It supports product 4's core input.
- **War Game mode has no direct real-comment support**, and the Market Simulator is the product our own panel places lowest. Its pitch scores highest. These signals conflict; product 3's real comments in April are the first real test of whether to build it.
- **Where real comments and the panel disagree, the real comments are thin.** Most real themes rest on 1–5 people. On Dec 6, product 1's own comments replace stage 1, and the chain should be rerun from there.

## Is the forced choice a real signal?

**No.** On 30 real days it does not order launches, it adds nothing to the ranking model, and it does not find a group's real backers better than chance. It should not shape product decisions or become the panel in User Testing in this form.

**What was run (E5, Nov 17).** Every featured launch in our held table on 30 days between Sep 18 and Nov 5 2026 (4–5 of each weekday): 913 launches, 889 scored (24 had too few same-topic backers for a panel). For each launch, the forced choice exactly as used above: one persona per distinct segment (median 7), the real line-up of that day, pick 3, place the launch in the ordering. 889 Gemini calls plus 167 for the rerun; cost $2.42. Intervals are bootstraps over days. Code and per-row results: `experiments/simlab/forced_choice_validation/`.

Two ways of reading the panel were scored:
- **Mean place**: where the launch's own panel put it (0 = first, 100 = last). This is the number reported for our four products.
- **Pick share**: how often the launch was among the 3 picks, counted over every panel call made for that day (each call sees the whole line-up).

### 1. Does it order launches like the real ranking?

| Signal | Daily rank correlation with the real rank [95%] |
|---|---|
| Mean place | 0.034 [-0.024, 0.088] |
| Share of the launch's own panel that picked it | 0.020 [-0.037, 0.077] |
| Pick share over all calls that day | 0.170 [0.112, 0.227] |
| Ranking model (arm 2), same days | 0.619 [0.543, 0.676] |

Mean place has no relation to the real rank. Pick share has a weak one. The ranking model is far stronger.

### 2. Top 3 / 5 / 10 hit of the panel's own ordering (%, paired with the ranking model on the same days)

| | Ranking model | Panel, by mean place | Panel, by pick share | Chance | Panel (pick share) minus model |
|---|---|---|---|---|---|
| Top 3 | 59 [52, 66] | 18 [12, 23] | 21 [13, 30] | 12 [10, 14] | -37.8 [-48.9, -26.7] |
| Top 5 | 64 [57, 70] | 28 [22, 35] | 28 [22, 34] | 20 [17, 23] | -36.0 [-44.7, -26.7] |
| Top 10 | 78 [75, 81] | 41 [35, 48] | 46 [40, 52] | 40 [34, 46] | -32.0 [-38.3, -25.3] |

The panel is a little above chance on the top 3 and top 5 and 32–41 points below the ranking model.

### 3. Does it add to the ranking model?

The model's prediction plus the panel's place (and pick share) as extra inputs, fitted on earlier months and tested on later ones (22 test days in October and November).

| | Model alone | + place | + place and pick share | Difference [95%] |
|---|---|---|---|---|
| Top 3 | 58 [50, 65] | 59 [52, 67] | 59 [52, 67] | +1.5 [+0.0, +4.5] |
| Top 5 | 67 [60, 74] | 68 [61, 76] | 68 [61, 76] | +0.9 [+0.0, +2.7] |
| Top 10 | 77 [74, 81] | 77 [74, 81] | 77 [74, 81] | +0.0 [+0.0, +0.0] |

No interval clears zero. The fitted weight on place is about zero. A leave-one-day-out version (not forward, 30 days) gives the same answer: top 3 +1.1 [-2.2, +4.4].

### 4. By voter group: does a group's pick predict that group's real backers?

Real backers are held people with a segment who voted on these days (8,678 people; 4,938 segment-launch pairs where the segment had 20 or more voters that day).

| Voter group | Segment-launch pairs | Real backing rate when the group's persona picked the launch [95%] | When it did not |
|---|---|---|---|
| Curious Observers | 757 | 6.3% [4.6, 8.2] | 4.2% [3.5, 5.0] |
| Launch Veterans | 942 | 9.8% [7.7, 12.0] | 7.9% [6.8, 9.3] |
| Tech Innovators | 3,239 | 8.8% [6.9, 10.8] | 7.1% [6.1, 8.1] |

- **A small real effect.** In every group, launches the persona picked were backed by a slightly larger share of that group's real voters (overall 7.5% against 5.6%). The intervals overlap in each group.
- **It is not group-specific.** Within one launch, the order of segments by place barely tracks which segments really backed it more than average: rank correlation 0.033 [-0.001, 0.069].
- **Recall at N is at chance.** Ranking that day's voters by their segment's place for the launch finds 8 [7, 9]% of the real backers, against 8 [7, 10]% at random. Even a perfect ordering of segments would reach only 11 [10, 12]%, because backers are spread across segments. The E5 backer line (25–29%) uses person-level scores over all held people, so it is not the same pool, but the conclusion does not depend on that: the panel does not beat random.

### 5. Stability: 5 days run twice (the second time with the line-up in a different order)

| | Mean place | Pick share |
|---|---|---|
| Top-3 overlap between the two runs | 27% | 87% |
| Rank correlation between the two runs | 0.50 | 0.84 |

Mean place is unstable: the same launch gets a different place on a rerun. Pick share is stable, but section 1 shows it is only weakly related to real results. A launch's "picked / not picked by anyone" verdict repeats 72% of the time.

### Leak checks

- **Line-up text:** name, tagline and the first 160 characters of the maker's own description. No votes, ranks or comments.
- **Persona pool and card history:** upvotes on launch days strictly before the test day. Of 114,926 product mentions in persona cards, 5 share a name with a launch of the same test day; these are earlier launches of the same product name (version updates), not the test-day launch, since card history stops the day before.
- **Known limitation:** the segment definitions and the one-paragraph segment profiles were fitted on Nov 16 2026 from all held data, so they postdate the test days. That could only help the panel, and it still shows no signal.
- **The language model's own knowledge** ends well before these launches.

### What this means for the plan

- **The placements reported above for our four products (47, 61, 56, 73) carry no information.** Mean place does not track real results and does not repeat on a rerun. "None of our products was picked" is also expected: on average a launch is picked by 14% of its panel, and most launches are picked by none.
- **The forced choice fixed the "everything is high interest" problem only in appearance.** The answers now vary, but the variation is noise.
- **Do not put it in User Testing as a ranking or a score.** What the panel has measured value for is unchanged: which themes come up (theme recall 61%, precision 52%). The "reason not to use" lines are of that kind and can stay, marked as model output.
- **If a pre-launch number is wanted, use the ranking model**, which hits 59% of the top 3 on these same days.

## Known problems in this run

- Held comments exist only for 2026 launches, so 2025 competitors contribute a finish but no comments.
- Two competitors share a name with unrelated 2026 products. Their comments were wrongly pulled in a first pass and removed before the stage 3 themes were recomputed. Product 4's pitches were written from the first pass; the corrected themes changed counts, not the ranking of the top two.
- Off-Product-Hunt competitors are described in our words from web search summaries; their pitch scores rate our wording.
- A pitch score outside a product's own launch day is noisy by about ±15 points.

Files: `experiments/launch_plan/chain_run.py`, `chain_comments_only.py`, `chain_stage1.json` to `chain_stage4.json`.

---

# Part 3. The first competitor run (30 competitors; made for the earlier product list: /try, Forecast board, Persona panel, Launch Pack)

E5, Nov 17 2026. One table per launch. Each column is marked as one of three kinds:

- **Real outcome**: the competitor's own Product Hunt launch, from our held data (day rank, launches that day, votes, date). No Product Hunt pages were fetched for this.
- **Model output**: produced by our models or by Gemini. Not a fact about the competitor.
- **Judgment**: E5's reading of the public description. Not measured.

## Method

- **Competitors.** 30 in all, 7–8 per launch. 22 are past Product Hunt launches found in our held data (Jan 2025 – Nov 2026) by searching names, taglines and descriptions. 8 are off Product Hunt or not in our data, found by web search; their tagline and description were written by us from the search summaries, so their pitch scores rate our wording, not theirs.
- **Pitch score (model output).** The deployed pitch prompt, Gemini 2.5 Flash. Each competitor's name, tagline, description and topics were placed in the same 14 real line-ups used for our own versions (2 of each weekday, Sep 18 – Nov 12 2026) and scored alongside that day's launches. The interval is a bootstrap over days. 399 of 420 calls returned.
- **/try band (model output).** The deployed /try code on the pitch text, not on the competitor's live site. It assumes a typical hunter and team.
- **Panel concerns (model output).** 24 personas built from people who backed same-topic launches in the 30 days before Nov 12; each persona stands for 20 or more people. The three most common concerns were summarised by a second Gemini call. Three competitors had too few same-topic backers to build a panel.
- **Cost.** Gemini $1.67 for this run.

## The pitch judge against real finishes

This is the bias check asked for in the plan review.

- **The judge does not inflate launch and Product Hunt tools.** The 22 competitors with a real launch average 64 on the same line-ups where our four best versions average 82.
- **Across these 22 the score does not predict the finish.** Rank correlation between pitch score and day rank is −0.13 (p = 0.55): no relation. Examples: a visual gallery scored 44 and finished 3rd; a launch-kit generator scored 74 and finished 13th; a platform update scored 37 and finished 2nd with 629 votes.
- **This differs from the stored scores.** For the 14 Product Hunt tools launched in 2026, the score stored at launch time correlates −0.75 with day rank. Two reasons the two checks disagree: this run moves 2025 launches into 2026 line-ups, and it re-scores some tools well above their stored score (one analytics extension: 30 stored, 73 here; a launch toolkit: 55 stored, 74 here).
- **What to take from it.** A pitch score on a line-up that is not the product's own day is noisy by about ±15 points. The pitch score is a weak input (7% of the rank model's gain). Who posted the launch explains these finishes far better: the three #1 finishes in these tables were posted by hunters with 25, 33 and 286 prior launches. Do not read our 75–88 as a forecast of anything.

## Launch 1 (month 0): Launch Simulator (/try)

**The job:** See how your page will land before you post.

**Ours (best version):** pitch score 86 [83, 89]; /try 35th percentile; likely rank 4–41 (median 15).

| Competitor | What it does (judgment, from its own description) | Pitch score [95%] and share of real launches it outscores (model output) | Real Product Hunt finish (real outcome) | /try band on its pitch text (model output) | Panel's top concerns (model output) | What it does better than us (judgment) | What we do better (judgment) |
|---|---|---|---|---|---|---|---|
| **ProductHunt Chaos Simulator**<br>*See what might happen on your Product Hunt launch day* | A free, playful Grok simulation of a launch day: upvotes, comments, plot twists. | 76 [70, 81]; 90% | #4 of 6, 330 votes, 2025-02-02 (hunter had 0 prior launches) | 98th percentile; likely rank 1–25 (median 7) | (no panel: too few backers of its topics) /try's predicted question: How accurate are the predictions from Grok? What kind of data is it trained on for these simulations | Fun and shareable; nobody has to believe it. It finished 4th on a quiet Sunday. | Ours is built on real voting data and is scored against real launches; theirs is a joke product with no accuracy claim. |
| **Firstpass**<br>*Actionable input so you nail every launch* | Shows every surface a stranger meets your launch on (PH page, leaderboard row) with hand-written critique notes. | 67 [61, 74]; 72% | #9 of 29, 144 votes, 2026-07-28 (hunter had 454 prior launches) | 67th percentile; likely rank 2–34 (median 12) | Potential to add complexity to the launch process; The cost for small teams or individual makers; Accuracy of 'crit notes' and truncation simulation | Visual and concrete: you see your truncated tagline. Human-quality notes. | We predict what voters will ask and where the launch lands; they only check presentation. |
| **Articos**<br>*Launch with confidence, not gut instinct* | Tests messaging, positioning and landing pages against simulated personas matched to your ICP. | 56 [49, 61]; 50% | #3 of 21, 385 votes, 2026-09-02 (hunter had 479 prior launches) | 79th percentile; likely rank 2–33 (median 10) | How does Articos handle niche ICPs; How does Articos prevent bias in its simulated personas; What are the limitations of the simulated personas | A headline accuracy claim ("86% human accuracy", peer-reviewed) and general B2B use beyond Product Hunt. | Our personas are built from real Product Hunt voters, and our accuracy is measured on the launch itself, not on a UX benchmark. |
| **HuntOMeter** *(wording ours)*<br>*Predict your Product Hunt upvotes from your tagline* | Estimates upvotes from a tagline by comparing it with about 19,500 past products. | 78 [71, 84]; 89% | no Product Hunt launch in our data | 93th percentile; likely rank 1–25 (median 7) | Accuracy of predictions is a concern; Tool might not account for external factors; Tool might encourage generic taglines | One input, one number, instant. | We use the whole page and the line-up, give a band with a published hit rate, and add the questions voters will ask. |
| **Roast My Landing Page AI** *(wording ours)*<br>*Simulated target users roast your landing page* | Simulated target users react to a landing page, in a quick roast mode or a structured mode. | 75 [71, 80]; 91% | no Product Hunt launch in our data | 65th percentile; likely rank 2–34 (median 12) | How does the AI ensure feedback is unbiased; How does the AI handle specific target audiences; How does the AI provide actionable feedback | Entertaining output and a clear free hook; 50+ ready personas. | Ours is specific to launch day and checked against real launch comments. |
| **MockUsers** *(wording ours)*<br>*AI personas browse your site and tell you why they would bounce* | Free AI personas generated from your page browse it and say why they would bounce. | 68 [63, 72]; 77% | no Product Hunt launch in our data | 42th percentile; likely rank 4–37 (median 14) | AI accuracy limited without real user data input; AI feedback might be too generic for niche products; AI might miss nuanced human emotional responses | Free, zero set-up, general to any site. | Personas grounded in real voters, plus a rank band; theirs are generated from the page itself. |
| **Wynter Message Test grader** *(wording ours)*<br>*Grade your B2B homepage with 15 simulated buyers* | A free AI grader: about 15 simulated B2B buyers score whether the page says what it does and for whom. | 58 [54, 62]; 51% | no Product Hunt launch in our data | 31th percentile; likely rank 4–41 (median 15) | How does AI handle nuances in B2B industries; Can simulated buyers truly replicate real B2B decision-making; How does AI prevent bias in its grading | A known brand in message testing, with a real human panel behind the paid product. | Launch-specific, with a rank band and voter questions; theirs is B2B homepage clarity only. |

**The three things we must beat (judgment):**
1. **A one-input, instant answer** (HuntOMeter, Chaos Simulator). Ours must return something in seconds from a URL alone.
2. **A headline accuracy number** (Articos claims 86%). Ours has none above the fold.
3. **Output worth sharing** (the roast tools). A founder shares a roast; nobody shares a rank band of 4 to 41.

**Candidate world-class claim (judgment):** "The only launch rehearsal checked against real launches every day: it names the questions your launch will get, and we publish how many it got right yesterday."

**How it would be measured before launch day:** Measured by the nightly forward score that already runs: theme recall and precision of /try's predicted questions against the real comments of that day's launches, for at least 30 consecutive days before launch day, against a fixed list of common questions as the named baseline. Current forward figures are from 11 launches only (recall 77% [67, 86], precision 51% [31, 70]); the claim needs the interval on the difference from the baseline to clear zero. The rank band should not be part of the claim: the text-only band has a top-3 hit of 29%.

## Launch 2 (month 2): Forecast board

**The job:** Today's Product Hunt ranking, forecast.

**Ours (best version):** pitch score 88 [86, 90]; /try 58th percentile; likely rank 3–38 (median 13).

| Competitor | What it does (judgment, from its own description) | Pitch score [95%] and share of real launches it outscores (model output) | Real Product Hunt finish (real outcome) | /try band on its pitch text (model output) | Panel's top concerns (model output) | What it does better than us (judgment) | What we do better (judgment) |
|---|---|---|---|---|---|---|---|
| **NODUS PH Radar for Product Hunt**<br>*Product Hunt analytics beyond the daily leaderboard* | A Chrome side panel for makers: vote velocity, race dynamics and historical patterns during launch day. | 73 [62, 83]; 76% | #15 of 18, 97 votes, 2026-06-12 (hunter had 1 prior launches) | 69th percentile; likely rank 2–34 (median 12) | (no panel: too few backers of its topics) /try's predicted question: What kind of 'watch rules' can I set up, and what insights do they provide | Live, in the browser, during the race. | We forecast before votes are visible and grade ourselves in public; they describe the race as it happens. |
| **PHBench**<br>*Predict the next Series A from a ProductHunt launch* | A public benchmark predicting Series A funding from Product Hunt launch signals (67,292 launches, 4.7× lift). | 79 [71, 85]; 93% | #3 of 41, 386 votes, 2026-05-15 (hunter had 279 prior launches) | 73th percentile; likely rank 2–33 (median 10) | (no panel: too few backers of its topics) /try's predicted question: What specific 'community engagement' metrics did you find most impactful in your model | A big, citable dataset and an investor audience; a clean headline number. | We predict the day's ranking, daily, with a public record; they predict funding, once. |
| **Product Huntr**<br>*Data analysis platform for Product hunt* | Analysis of 12,000+ launches to find validated ideas and market gaps. | 75 [69, 80]; 92% | #6 of 9, 151 votes, 2025-11-28 (hunter had 0 prior launches) | 80th percentile; likely rank 2–26 (median 9) | How accurate are the AI insights; How is data kept up-to-date; What is the pricing model | Idea-finding is a broader need than launch day. | A daily forecast with a track record; theirs is a static analysis. |
| **Product Hunt Topics by xTopics**<br>*Discover the topics that dominate Product Hunt* | Shows which topics dominate Product Hunt launches and which are saturated. | 40 [33, 46]; 15% | #19 of 32, 127 votes, 2025-06-25 (hunter had 0 prior launches) | 87th percentile; likely rank 2–26 (median 9) | How frequently is the data refreshed and updated; How does it handle topic categorization; Can I track the historical performance of topics | Simple and evergreen. | Per-launch predictions and public scoring. |
| **Product Hunt for Raycast**<br>*View the leaderboard directly in Raycast* | The leaderboard, with upvotes and comments, inside Raycast. | 76 [71, 80]; 92% | #6 of 21, 212 votes, 2025-05-01 (hunter had 98 prior launches) | 48th percentile; likely rank 4–37 (median 14) | How does this handle Product Hunt API rate limiting; What are the privacy implications of integrating Product Hunt data; Is this free to use, or are there subscription costs | Lives where developers already work. | We add a prediction; they show the current state only. |
| **VisualPH**<br>*A more visual way to experience Product Hunt* | A visual gallery of top products' landing pages and media. | 44 [38, 50]; 15% | #3 of 17, 403 votes, 2025-07-09 (hunter had 0 prior launches) | 93th percentile; likely rank 1–25 (median 7) | How to ensure images are up-to-date; How to handle dynamic/interactive landing pages; How to ensure quality and relevance of images | Pleasant to browse; design inspiration. | Different job; we forecast, they display. |
| **hunted.space** *(wording ours)*<br>*Real-time Product Hunt launch stats* | Hour-by-hour upvote, comment and rank tracking for every launch, with an AI predictor of launch odds. | 85 [82, 89]; 98% | no Product Hunt launch in our data | 49th percentile; likely rank 4–37 (median 14) | AI predictor accuracy and validation; AI predictor handling of niche products/limited data; Pricing model and free trial availability | The established place makers watch a launch live; years of history; it already has a predictor. | A forecast made at 12:05am before votes show, with every day graded in public. Their predictor publishes no accuracy that we found. |

**The three things we must beat (judgment):**
1. **hunted.space's habit.** Makers already keep it open on launch day. We need a reason to open ours first: the forecast exists before any votes show.
2. **A clean, citable number** (PHBench's 4.7× lift). Ours is "3.3 of 5", which needs a baseline beside it to mean anything.
3. **Being inside the workflow** (Raycast, the Chrome side panel). Ours is a web page to remember to visit.

**Candidate world-class claim (judgment):** "The only Product Hunt forecast that is published before votes are visible and graded in public every day."

**How it would be measured before launch day:** Measured by the public track record: top-3 hit rate of the 12:05am forecast over at least 60 consecutive live days, against two named baselines on the same days: (a) ranking by the hunter's past top-5 share, and (b) the order shown at the hour votes become visible. The back-test figure is 58% top-3 hit over 183 days; the live record is shorter and must be the one quoted. If hunted.space's predictor publishes picks, score it on the same days as a third baseline.

## Launch 3 (month 4): Persona panel

**The job:** Hear from audience segments, compare versions, define your own segments.

**Ours (best version):** pitch score 75 [71, 79]; /try 64th percentile; likely rank 2–34 (median 12).

| Competitor | What it does (judgment, from its own description) | Pitch score [95%] and share of real launches it outscores (model output) | Real Product Hunt finish (real outcome) | /try band on its pitch text (model output) | Panel's top concerns (model output) | What it does better than us (judgment) | What we do better (judgment) |
|---|---|---|---|---|---|---|---|
| **Sapien**<br>*AI market research with synthetic populations* | Simulated audiences to compare concepts, marketing, prices and strategies, with segment comparisons and follow-up questions. | 62 [59, 64]; 63% | #25 of 26, 65 votes, 2026-10-03 (hunter had 0 prior launches) | 22th percentile; likely rank 4–43 (median 17) | How to ensure synthetic populations accurately reflect real-world nuances; How to handle biases in synthetic population generation; How to validate the accuracy of synthetic audience responses | Custom audiences and follow-up questions on the same population: exactly the features our panel lacks. | Our segments come from real voting behaviour, and we publish recall and precision against real comments. |
| **TheySaid 4.0**<br>*See how users will react, right where you build.* | Real customers or synthetic users trained on them, inside Claude, Cursor or Jira. | 65 [61, 69]; 69% | #1 of 20, 393 votes, 2026-10-27 (hunter had 286 prior launches) | 92th percentile; likely rank 1–25 (median 7) | How does this handle complex, multi-step user flows; What are the limitations of synthetic users; How does this ensure synthetic users reflect target audience | Mixes real and synthetic users and lives inside the tools teams use. Finished 1st. | A ready audience with no customer data needed; measured accuracy on launch comments. |
| **Snap**<br>*Instant usability testing with AI personas* | Instant usability tests of a prototype or site with custom AI personas; transcripts and recordings. | 72 [67, 76]; 87% | #8 of 10, 203 votes, 2025-10-16 (hunter had 168 prior launches) | 20th percentile; likely rank 4–43 (median 17) | AI personas missing nuanced human behavior; Accuracy and depth of AI-generated recommendations; Potential for AI personas to provide superficial feedback | Tests the product flow itself, with recordings. | We test the pitch against the people who will actually vote; they test usability with invented personas. |
| **Uxia**<br>*Validate your User flows UX & UI in seconds with AI* | AI and synthetic users for fast UX and user-flow testing. | 60 [57, 64]; 65% | #1 of 5, 535 votes, 2025-09-07 (hunter had 25 prior launches) | 66th percentile; likely rank 2–34 (median 12) | How does Uxia handle complex user flows; How accurate are synthetic users compared to real users; How customizable are the synthetic user personas | Strong design-team positioning. Finished 1st on a 5-launch day. | Grounded in real people's behaviour; accuracy published. |
| **Userology AI**<br>*The AI user research agent for busy product teams* | An AI researcher that recruits real users, moderates sessions and writes insight reports. | 74 [71, 78]; 88% | #2 of 11, 347 votes, 2025-12-19 (hunter had 89 prior launches) | 32th percentile; likely rank 4–41 (median 15) | How does AI ensure quality of recruited users; How does AI handle nuanced feedback; How does AI handle edge cases | Real users, real sessions. | Minutes instead of days, and no recruiting. |
| **Velozity**<br>*AI-Powered instant user research tool* | AI personas built from your users, for focus groups and usability tests. | 59 [52, 65]; 56% | #2 of 8, 284 votes, 2025-05-03 (hunter had 0 prior launches) | 28th percentile; likely rank 4–43 (median 17) | Accuracy and bias of AI-generated insights; Depth and realism of AI responses; Data privacy and security | Personas built from the customer's own users, and fine-tunable. | No data needed from the founder; segments already built from 81,000 voters. |
| **Synthetic Users (syntheticusers.com)** *(wording ours)*<br>*User research without the users* | Interviews and surveys with synthetic personas, for early product and concept testing. | 70 [66, 73]; 80% | no Product Hunt launch in our data | 29th percentile; likely rank 4–43 (median 17) | How reliable is the feedback from synthetic users; How to prevent generic or biased feedback; How to ensure diverse user behaviors and biases | The category name and the best-known brand in it; full interview workflows. | Their personas are described, ours are derived from real behaviour; we publish how often the panel matches real comments. |
| **Wynter** *(wording ours)*<br>*On-demand messaging and market research* | B2B message testing with a panel of real, verified people from the target audience, in under 48 hours. | 50 [39, 61]; 33% | no Product Hunt launch in our data | 40th percentile; likely rank 4–37 (median 14) | How is the panel verified and kept unbiased; How is data privacy and security handled; How is the quality of feedback ensured | Real humans. That is the standard we are judged against. | Minutes and near-zero cost against 48 hours and hundreds of dollars a test; consumer and maker audiences. |

**The three things we must beat (judgment):**
1. **Custom audiences and follow-up questions** (Sapien, Velozity). Ours has fixed groups and one round.
2. **Real humans** (Wynter, Userology, FirstUser). The honest claim is speed and cost, not equivalence.
3. **Trust in synthetic answers.** The top concern for every competitor in this table is "how do you know the synthetic users are right?". Whoever answers that with a number wins the category.

**Candidate world-class claim (judgment):** "The only synthetic audience with a published score against what real people said: for each launch we show which predicted themes real commenters raised."

**How it would be measured before launch day:** Measured by theme recall and theme precision of the panel against real launch comments on held-out launches (now 61% and 52% on 167 launches), with two named baselines on the same launches: a persona-free prompt, and a sample of real comments from similar past launches. Our own test found the panel beats the real-comment baseline on precision (52% against 36%) and not on recall (61% against 65%), so the claim has to be the precision one.

## Launch 4 (month 6): Launch Pack

**The job:** A full service across one launch, with reports.

**Ours (best version):** pitch score 80 [75, 85]; /try 27th percentile; likely rank 4–43 (median 17).

| Competitor | What it does (judgment, from its own description) | Pitch score [95%] and share of real launches it outscores (model output) | Real Product Hunt finish (real outcome) | /try band on its pitch text (model output) | Panel's top concerns (model output) | What it does better than us (judgment) | What we do better (judgment) |
|---|---|---|---|---|---|---|---|
| **Submit.DIY**<br>*All-in-one AI launch platform for makers* | A toolkit to plan, run and track a launch, with AI copy for every channel. | 74 [70, 77]; 87% | #5 of 49, 225 votes, 2026-04-17 (hunter had 14 prior launches) | 94th percentile; likely rank 1–25 (median 7) | AI copy customization and brand voice; AI copy quality and originality; Collaboration and feedback loops | Covers the whole checklist and writes the copy. | We say how the launch will land and why; they organise tasks. |
| **LaunchForge**<br>*AI launches your product: page, posts, PH draft all in one* | AI generates a landing page, a social launch kit and a Product Hunt draft. | 74 [70, 79]; 92% | #13 of 21, 94 votes, 2025-10-29 (hunter had 0 prior launches) | 97th percentile; likely rank 1–25 (median 7) | How much control over AI output; How does it handle custom branding; Will the generated content be unique | Produces the assets a founder needs, in one go. | We evaluate and forecast; they generate. A founder could use both. |
| **Spira for Product Hunt Makers**<br>*Social media growth agents that build your momentum* | AI agents and persona clones that plan and publish launch-day social content. | 81 [78, 83]; 98% | #1 of 11, 415 votes, 2026-06-29 (hunter had 33 prior launches) | 98th percentile; likely rank 1–25 (median 7) | Ensuring AI content is authentic, not generic or automated; Control over AI content, tone, style, and brand voice; Data privacy and security for social media accounts | Does the launch-day posting for you. Finished 1st. | Insight only, no automated posting; a forecast and a post-mortem with real numbers. |
| **FirstUser.app**<br>*Guaranteed feedback on your product launch* | Makers review each other's launches: give feedback to earn it. | 68 [58, 76]; 68% | #8 of 22, 178 votes, 2025-08-14 (hunter had 0 prior launches) | 82th percentile; likely rank 2–26 (median 9) | Quality control for feedback; Value proposition vs. free alternatives; Applicability for non-commercial projects | Real human feedback, free. | Instant, private, and before anything is public; no reciprocity needed. |
| **IndieCrush - The Pre-Launch Playground**<br>*Get Feedback, First Users & Testimonials in Under 24h* | Connects indie makers with real beta testers for feedback and testimonials, with a token reward. | 56 [50, 62]; 42% | #8 of 29, 237 votes, 2025-05-28 (hunter had 0 prior launches) | 68th percentile; likely rank 2–34 (median 12) | Reliance on $indie token might be a barrier; Maintaining quality and authenticity of feedback; Lack of clarity on team collaboration features | Real testers and testimonials within 24 hours. | No token, no waiting, and a forecast. |
| **shippedit.me**<br>*Launch Platform with SEO, AEO & Growth Insights* | A launch directory with weekly launch battles, a permanent page, SEO audits and analytics. | 44 [38, 52]; 27% | #19 of 27, 73 votes, 2026-10-11 (hunter had 0 prior launches) | 22th percentile; likely rank 4–43 (median 17) | AI fix card accuracy and customization; Competitor monitoring data and sources; Dofollow backlink quality and relevance | Gives a backlink and a place to launch. | Different job: we report on a Product Hunt launch; they are another place to launch. |
| **Uneed Community**<br>*Launch, get seen, & grow alongside other makers* | An alternative launch platform with a community feed. | 37 [33, 42]; 10% | #2 of 16, 629 votes, 2025-11-04 (hunter had 0 prior launches) | 73th percentile; likely rank 2–33 (median 10) | Risk of the feed becoming noisy with too many daily marketing posts; Potential for the platform to become too focused on marketing; Potential for makers to feel pressured to constantly post updates | An audience of its own. Finished 2nd with 629 votes. | We are not a launch venue; we make the Product Hunt launch itself better informed. |
| **Uprows Hub** *(wording ours)*<br>*Product Hunt upvotes and engagement packages* | Sells packages of Product Hunt upvotes and engagement. | 3 [1, 5]; 0% | no Product Hunt launch in our data | 87th percentile; likely rank 2–26 (median 9) | Ethical implications of buying upvotes/engagement; Risk of Product Hunt cracking down or penalizing products; Potential for an uneven playing field/pay-to-win environment | Nothing we would copy. This breaks Product Hunt's rules. | We never supply or solicit votes; that line belongs on the Launch Pack page. |

**The three things we must beat (judgment):**
1. **Doing the work, not describing it** (LaunchForge, Submit.DIY, Spira). They hand over assets; we hand over reports.
2. **Real feedback from real people** (FirstUser, IndieCrush), which is free.
3. **An audience of their own** (Uneed). We bring no traffic.

**Candidate world-class claim (judgment):** "The only launch service that tells you your odds before you launch, and afterwards shows you how right it was."

**How it would be measured before launch day:** Measured on the Pack's own customers and, before there are any, on public launches: for every forecast issued, publish the forecast band and the real finish; report the share of launches that finished inside the stated band, against the band's stated coverage, over at least 50 launches. The pre-launch report is measured by the gap detector's hit rate: of the questions it said the page leaves open, the share real commenters asked.

## What real users said on competitors' launches

Product 1 has no users yet, so the nearest real feedback is what real people wrote on competitors' Product Hunt launches.

- **Source (real outcome).** Our held comment captures. No new Product Hunt requests were made, so only launches whose comments we already hold are covered: 12 launches, all from 2026. That is 9 of the 22 competitors in the tables above, plus 3 closely related launches found in the held comments (a second launch of the persona message-testing product, Product Hunt's own launch editor, and one more launch directory). The 13 competitors that launched in 2025 have no held comments and are not covered.
- **Who is counted.** Comments by the hunter and the makers are dropped. Each remaining commenter counts once per theme. No names or usernames are kept; only theme counts are saved.
- **Tagging (model output).** One Gemini call per launch job grouped the comments into themes of three kinds: asked for, complained or doubted, praised. Comments that only congratulate were ignored. Cost $0.03.
- **Size.** The counts are small. A theme raised by one or two people is a lead, not a finding.

| Launch | Competitor launches with held comments | Commenters (not team) |
|---|---|---|
| 1. /try | Firstpass, Articos, Articos MCP, Product Hunt Visual Launch Editor | 67 |
| 2. Forecast board | NODUS PH Radar for Product Hunt, PHBench | 23 |
| 3. Persona panel | Sapien, TheySaid 4.0, Articos, Articos MCP | 64 |
| 4. Launch Pack | Spira for Product Hunt Makers, Submit.DIY, shippedit.me, Scroll Launch | 57 |

The simulated-persona message-testing product and its second launch sit in both the /try and the panel tables, because they do both jobs.

### Top themes by number of distinct commenters (real comments, tagged by model)

| Launch | Asked for | Complained about or doubted | Praised |
|---|---|---|---|
| 1. /try | How is accuracy quantified and measured (3)<br>How does it handle non-english languages (2)<br>How different are results compared to actual users (2)<br>More transparency about investment questions (2)<br>Does it explain the principle behind the feedback (1)<br>Which surface kills the most taglines (1) | Confusing categories and tags (2)<br>Concerns about hidden costs of character limits (1)<br>Videos feel secondary (1)<br>Company info is confusing (1) | Fast turnaround time and improved messaging (7)<br>Editable on mobile, improved mobile experience (4)<br>Helped shape icp and positioning (3)<br>See your launch as you build it, reduces fear (3) |
| 2. Forecast board | Can it compare trajectory to similar past launches by category/follower size (2)<br>What is the product's own prediction for its success (2)<br>Does it surface comment velocity as a signal (1)<br>Does it include post-launch traction like follows and comments (1)<br>What signals does it use (upvote velocity, comment quality, founder background) (1)<br>Does it backtest against past launches (1) | Model might penalize solo founders or first-time founders (1)<br>High engagement vs. series a might be correlation, not causality (1)<br>No analysis on hunter impact (1)<br>Publishing the model might corrupt the signal over time (1) | Useful for understanding launch dynamics and picking launch dates (4)<br>Helps find hidden gems beyond popular ai tools (1) |
| 3. Persona panel | How accurate is synthetic feedback compared to real users (6)<br>How long does a synthetic test take (1)<br>Can it be tuned for specific customer audiences (1)<br>Can it help small teams with user research (1)<br>How are synthetic users created (1)<br>How are questions from synthetic users surfaced (1) | Pricing is unclear or inconsistent (1)<br>Scoring system is unclear and needs more detail (1)<br>Half of themes are noise, is there a confidence score (1) | Fast turnaround time for feedback (5)<br>Integrating feedback into existing workflows is good (3)<br>Helps shape icp and positioning (3)<br>Synthetic users going through the product is useful (2) |
| 4. Launch Pack | How to maintain brand voice and avoid generic ai content (7)<br>How does the ai learn a founder's voice (4)<br>How much control do makers have over content (3)<br>Is there a free trial or promo code (3)<br>Can it turn content ideas into posts (2)<br>How does it handle brand 'taste' and trends (2) | Bug/inconsistency with connecting social accounts (1)<br>Auto-scheduled posts felt template-y (1)<br>Paywall is scaring me away (1)<br>Website is not reachable (1) | Solves the problem of launch momentum dying (5)<br>Persona clone idea is smart (2)<br>Two-minute persona setup from url is slick (1)<br>Something people actually need (1) |

The full theme list is in `experiments/launch_plan/competitors_comment_themes.json`.

### What real users of competitors asked for, and which planned feature answers it

The request was for two columns on each competitor table. Real comments exist for only 12 launches and themes cut across competitors, so the two columns are given here per launch, by theme. "Not answered" is a judgment from the competitor's own pitch and the makers' absence of a feature in it; we did not test the competitors' products.

**Launch 1, /try**

| What real users asked for that the competitors' pitches do not answer (commenters) | Which of our planned features answers it |
|---|---|
| How is accuracy measured, and how different are results from real users? (3 + 2) | The accuracy block above the fold on /try, then the scored archive in product 2. This is the best-supported item in the plan. |
| A confidence score per theme; "half of the themes are noise" (1 + 1) | **Not planned. Add it.** We already measure theme precision (52%); showing a confidence next to each predicted question is cheap. |
| A demo or sample report before signing up (1) | Planned for the Launch Pack only (page fix 6). Move a sample result onto the /try page too. |
| Does it work on drafts, before anything is public? (1) | /try already works from pasted text. Say so on the page. |
| Does it work for other platforms (X, Hacker News) and for non-English pages? (1 + 2) | **Not planned.** We have a Show HN comparison in hand; state the scope plainly: Product Hunt, English. |

**Launch 2, Forecast board**

| What real users asked for (commenters) | Which planned feature answers it |
|---|---|
| Which signals are used, how are they weighted, and is the hunter's effect analysed? (1 + 1 + 1) | "The reason behind each forecast, launch by launch". Supported, thinly. |
| Is it back-tested, and what is the false-positive rate? (1 + 1) | The full scored archive. Supported. |
| What does the product predict for its own launch? (2) | **Not planned. Add it.** Publish our own forecast for each of our four launches before the day, and score it. It costs nothing and is the most direct proof. |
| Compare a launch's path with similar past launches by category and size (2) | Partly: /try's "similar launches" count exists. A side-by-side with look-alike launches is not planned. |
| Praised: useful for picking a launch date (4) | **Not planned as a feature.** We have the weekday result (weekends have weaker line-ups); a "best day for your launch" view would use it. |
| Does it penalise solo or first-time founders? (1) | The reasons view will show it does: the hunter's record is the largest input. Say it openly. |

**Launch 3, Persona panel**

| What real users asked for (commenters) | Which planned feature answers it |
|---|---|
| How accurate is synthetic feedback compared with real users? (6, across three launches) | The published recall and precision against real comments, and rule 4 in the plan (score the panel's product-1 predictions against product 1's real comments). The single best-supported feature in the whole plan. |
| How do you stop synthetic users from always agreeing? What happens when real and synthetic disagree? (1 + 1) | **Not planned, and it is our known weakness**: the panel rated nearly every persona "high interest" for all four of our products. Remove the interest rating or calibrate it before launch 3. |
| Can it be tuned to my audience, refined over time, and does feedback differ across personas? (1 + 1 + 1) | Per-segment view and custom segments. Supported, thinly. |
| Compare versions of a value proposition; A/B testing without running an A/B test (1 + 1) | Version comparison. Supported by 2 real commenters; our own panel called it the most requested feature, which is model output. |
| Can it look at images? (1) | "The panel reads the page's images". Supported by 1. |
| Does it hold for non-western audiences? (1) | **Not planned.** Our voters are Product Hunt voters; state that. |
| Praised: fast turnaround (5); fits into existing tools (3) | Speed is already there. Integration is the API, planned last; real praise suggests it matters earlier. |

**Launch 4, Launch Pack**

| What real users asked for (commenters) | Which planned feature answers it |
|---|---|
| How does generated content keep my brand voice, and how much control do I have? (7 + 4 + 3) | Nothing, by design: the Pack writes reports, not content. But it shows what buyers of launch tools care about most: control over what goes out under their name. Our reports should recommend, never auto-apply. |
| Is there a free trial or promo code? (3, on three different products) | **Not planned.** The Pack is paid with no trial. /try is the free trial; say so on the Pack page. |
| Which platforms first, and in what order? (2) | Not planned. The audit could include a channel order from our launch-day reach inputs, but the model shows founder posts alone move little; do not promise it. |
| Complaint: paywall before any value (1); site unreachable (1); onboarding stuck (1) | The ship gate already covers run limits. Show a sample report before payment. |
| Praised: solves launch momentum dying after day one (5) | Nothing in the Pack. The post-mortem is the only after-launch piece. |

### Planned features that no real competitor comment supports

Checked against the feature-to-product map in Part 1 of this file ("How feedback on product 1 defines products 2, 3 and 4"). That map is built from the persona panel, which is model output.

| Planned feature | Goes into | Real competitor comments that support it |
|---|---|---|
| The before-votes-show forecast beside the midnight one (late surges) | Product 2 | **None.** Nearest: 1 commenter asked whether comment velocity is used as a signal. |
| Follow-up questions on any page, not only a launch page | Product 3 | **None.** Nearest: 1 asked about testing pricing, 1 about finding objections. |
| Plain-language summary for non-launchers | Product 1 | **None.** |
| The pre-launch audit with named fixes and expected effect | Product 4 | **None among launch-tool users.** 1 commenter on a persona tool asked for a sample report. Users of launch tools asked about control and brand voice, not about audits. |
| The audit takes the maker's own reach and hunter as inputs | Product 4 | Thin: 1 complaint that a predictor ignores the hunter, 1 that it may penalise first-time founders. |
| "What this uses and what it ignores" block | Product 1 | Thin: 1 asked which signals are used, 1 how it keeps up with new models. |

Supported by real comments: the accuracy record (the strongest, 6 commenters on the panel job and 5 on the /try job), reasons behind a forecast, version comparison, segments, images, and integration. Every one of these is supported by 1 to 6 people, so none is settled.

**Three things real comments raise that the plan does not have:** a confidence score per predicted theme; our own forecast for our own launch, published in advance; and a fix for synthetic users that always agree.

**The Launch Pack is the least supported product.** No real commenter on a launch tool asked for a forecast, an audit or a post-mortem. They asked for content in their own voice, control over it, and a free trial. That does not show the Pack is wrong, since nobody asks for a thing they have not seen, but it has no real demand evidence yet. Product 1's real comments on Dec 5 are the first test.

## What the four tables say together

- **Every competitor that simulates people draws the same first concern from the panel: how accurate is it, and how is bias handled.** That is the same concern the panel raised about our own four pages. A published, daily accuracy score is the one thing none of these competitors shows, and it is the thing we already produce.
- **The competitors that finished #1 either do work for the founder or sit inside the founder's tools.** Reports and forecasts finished lower. The closest matches to our products finished 3rd (simulated-persona message testing, posted by a hunter with 479 prior launches), 15th (launch analytics extension) and 25th of 26 (synthetic-population research, first-time hunter).
- **The features competitors have and we lack:** custom segments and follow-up questions (panel), version comparison (/try and panel), and an instant single number (/try). Version comparison was also the most requested feature in our own panel run.
- **The line we should draw in public:** one competitor sells upvotes. The pitch judge scored it 3 out of 100, and the panel's first concern was the ethics. Saying plainly that we never supply or solicit votes costs nothing and separates us from the worst of the category.

Files: `experiments/launch_plan/competitors_build.py`, `competitors_run.py`, `competitors_results.json`, `competitors_comments.py`, `competitors_comment_themes.json`.
