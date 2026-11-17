# Launch plan for a maker with 0 followers and no launches (UserSim as its own customer)

Run Nov 17 03:10–03:25Z on the pipeline VM, read-only. Code: `experiments/launch_plan/counterfactual_arm2.py`. Raw output:
`counterfactual_arm2.out`.

## Revised plan after review (Nov 17, 04:10Z). Read this first; it replaces the stacked-row and trajectory numbers below.

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

6. **Product Hunt's own rule breaks the 14-week trajectory.** Its help centre asks makers to wait **at least six months
   between posts for the same product or from the same company**, and requires a significant update; earlier posts get extra
   scrutiny and may not be featured. Four launches from one company in 14 weeks is not available. Whether a clearly distinct
   product from the same company can go sooner is not stated; the team can be asked before launch.
   Sources: https://help.producthunt.com/en/articles/484934-can-i-relaunch-my-product and
   https://www.producthunt.com/p/producthunt/how-often-should-you-launch-on-product-hunt

### The revised plan
- **One launch now, built to count: /try**, with the daily board and the persona panel shown inside it as features, not held
  back as later launches.
- **Goal of launch 1: rank and record, plus /try users.** Launch on a **Saturday**. Planned odds (row A): top 5 17.6%,
  top 10 50.5%. A Tuesday gives 60% more votes on the day but a 3% chance of the top 5.
- **The two things worth working on before the date**, because they are the largest real levers:
  - **A hunter with a record.** One-change effect: 2.3% to 17.6–21.7% on all days. How: ask hunters who have posted
    launch-analytics or maker tools, show them /try run on a launch they hunted, and ask only whether they would post it.
    If none agrees within two weeks, self-hunt on the planned Saturday.
  - **Makers with real reach on the page** (row C): people who actually worked on it and will post about it themselves.
- **Launch 2 is about six months later** (or sooner only with Product Hunt's written yes): the Launch Pack, as the paid
  product, on a **weekday** for traffic. Expected top 5 with a self-hunted record: 27.5% on a Saturday, 17.4% on any day.
- **If launch 1 finishes outside the top 10** (about 50% likely on row A): nothing is lost for launch 2 in the model (same
  odds as no record). Keep the date for launch 2, and fix the page from the comments it drew.
- **Pre-launch checklist (owner: Shreyas):** "Free to try, no signup" is true on the day; the accuracy number and its day
  count are on the page and current; the page fixes below are done.

### What in the older sections is now superseded
- "Stacking the levers" (31.2% / 71.4%), its day table, and the 4-step trajectory (34 / 59 / 70 / 72%).
- "After 2 launches your own record puts you at about the level of an active hunter."
- "Weekends carry about 20 launches against about 35" as the reason weekends win.
- The base case's median rank is 25.5 (the text said 25).

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
| Pitch score 85 (Gemini read of the tagline and description) | 15.5 | 2.1 | 6.0 [4.3, 8.0] | 23.6 |
| Pitch score 75 | 16 | 1.9 | 5.4 [3.8, 7.3] | 21.3 |
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

## Stacking the levers: the first launch
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

## The trajectory: each launch builds the hunter record for the next
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

## What "everything you control" means in practice
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

## Pitch versions and their measured scores (E5)

Three tagline and description versions were written for each product. Every claim in them is a number we have already published; "free, no signup" in /try version 1 must be true on launch day or be cut.

Each version was scored with the deployed pitch prompt (Gemini 2.5 Flash, the same listwise prompt that produces the model's `llm_pitch` input). The version was placed in the real line-up of 14 days (2 of each weekday, Sep 18 – Nov 12) and scored alongside that day's real launches. The interval is a bootstrap over the 14 days. 208 of 210 calls returned; cost $0.73. As a check, the real launches in the same calls averaged 55.5, against 55.4 for their stored scores.

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
- **Caution.** The judge is a language model scoring products about Product Hunt for a Product Hunt audience. It may favour them. Scores at the 96th–100th percentile of real line-ups are probably too kind. Because the rank model is flat above 75, this does not change the trajectory.

## Persona panel and /try band on each best version (E5)

**Persona panel.** The live panel prompt, with 24 personas per product. A new maker has no team history, so the personas were built from the people who backed same-topic launches in the 30 days before Nov 12 (5,726 people for the first three products). Each persona stands for at least 20 people; no individual is shown. One Gemini call per product; cost $0.04.

**/try band.** The deployed /try code, with the pitch text pasted in. /try knows nothing about the hunter, team or day, so it assumes the population median for each. Its band is therefore not comparable to the table above, which sets those inputs explicitly.

| Product (best version) | /try percentile among similar launches | /try likely rank band (median) | /try share reaching top 3 / top 10 | Panel interest: high / medium (of 24) |
|---|---|---|---|---|
| Launch Simulator (/try) | 35 | 4–41 (15) | 7% / 33% | 21 / 3 |
| Forecast board | 58 | 3–38 (13) | 13% / 41% | 20 / 4 |
| Persona panel | 64 | 2–34 (12) | 17% / 45% | 21 / 3 |
| Launch Pack | 27 | 4–43 (17) | 7% / 27% | 23 / 1 |

The /try bands are wide (roughly rank 3 to 40) and differ little between products. From the text alone, /try places the panel and board pitches a little above the /try and Launch Pack pitches, which is the reverse of the Gemini pitch scores. Neither signal separates the four products reliably.

The panel rates nearly every persona "high" interest for all four products. That is not informative: the panel is known to be agreeable, and it has measured value for *which themes come up* (about 50% precision, 60–75% recall on real launches), not for how much people like something. Read the concerns and questions below, not the interest levels.

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
   - Panel: show the 63% theme figure and say what it is not (it does not predict individual votes or how much people will like the product).
2. **Say what the model does not see.** Three of four groups ask about the hunter, the maker's network, late surges and images or video. Add one short "what this uses and what it ignores" block to each page. For /try, say that it reads text only, and that the hunter and team are assumed typical.
3. **Answer the "gaming" and "self-fulfilling" worry on the Forecast board.** State that the forecast is published after launches are live, uses only public inputs, and that we do not help anyone collect votes.
4. **Answer the privacy question on the panel page.** State that personas are groups of 20 or more people built from public voting history, and that no individual is shown or sold.
5. **Add version comparison to /try, or say it is coming.** "Can I test two descriptions against each other?" came from three groups and for three products. It is the most requested feature and is cheap to build on what exists.
6. **Launch Pack: show a sample report.** Every group asks how specific the "what to fix" advice is. A real, redacted sample of the three reports answers it. Lead with what the founder gets, not with "paid package" (pitch score 80 against 35).
7. **State the price and the free tier on every page.** Cost and "is there a free tier" came up for the panel, and for the API in a separate run.
8. **Plain-language summary for non-launchers.** The curious-observer group (about 12% of the panel) asks whether they can understand it at all. One sentence at the top of the board and of /try results is enough.

These are model-predicted concerns, not real feedback. On real launches the panel's predicted themes are right about half the time and cover 60–75% of what commenters raise, so treat the list as a checklist of likely questions, not a ranking of what matters most.

Files: `experiments/launch_plan/candidates.json` (all versions), `pitch_score.py`, `panel_try.py`, `cf_arm2_measured.py`, `cf_arm2_measured.json`.
