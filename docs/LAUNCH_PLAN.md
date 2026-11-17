# Six-month launch plan: 4 Product Hunt launches, two months apart (UserSim as its own customer)

Written Nov 17 2026 for a maker with 0 followers and no launches. The plan comes first, then each product in
detail, then the method and evidence. This is the only launch-plan file.

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

This is the summary. The full feature tables, pitch versions and competitors for each product are in "The four products in detail" below.

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
1. **The panel cannot rank products.** Its forced-choice ordering failed its test on 889 real launches (see "The
   panel's forced choice failed its test"), so no panel score is used here. The panel is used only for which themes
   come up. For a pre-launch number, use the forecast model.
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

# The four products in detail

Each product is defined from the feedback on the one before. Real = real comments on competitors doing that job; panel = our simulated personas.

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

| Competitor | Pitch score [95%] (model) | Real Product Hunt finish (real) | Panel's top concerns (model) |
|---|---|---|---|
| **Articos**<br>*Launch with confidence, not gut instinct* | 56 [49, 61] | #3 of 21, 385 votes, 2026-09; hunter had 479 prior | How does Articos handle niche ICPs; How does Articos prevent bias in its simulated personas; What are the limitations of the simulated personas |
| **Firstpass**<br>*Actionable input so you nail every launch* | 67 [61, 74] | #9 of 29, 144 votes, 2026-07; hunter had 454 prior | Potential to add complexity to the launch process; The cost for small teams or individual makers; Accuracy of 'crit notes' and truncation simulation |
| **HuntOMeter** *(off Product Hunt; wording ours)*<br>*Predict your Product Hunt upvotes from your tagline* | 78 [71, 84] | none in our data | Accuracy of predictions is a concern; Tool might not account for external factors; Tool might encourage generic taglines |
| **ProductHunt Chaos Simulator**<br>*See what might happen on your Product Hunt launch day* | 76 [70, 81] | #4 of 6, 330 votes, 2025-02; hunter had 0 prior | How accurate are the predictions; How does it handle subjective human elements; Will the simulation be too generic |
| **Roast My Landing Page AI** *(off Product Hunt; wording ours)*<br>*Simulated target users roast your landing page* | 75 [71, 80] | none in our data | How does the AI ensure feedback is unbiased; How does the AI handle specific target audiences; How does the AI provide actionable feedback |

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

| Competitor | Pitch score [95%] (model) | Real Product Hunt finish (real) | Panel's top concerns (model) |
|---|---|---|---|
| **HeadsUp**<br>*The first AI competitor monitoring agent* | 67 [63, 70] | #1 of 8, 598 votes, 2025-08; hunter had 2 prior | How does HeadsUp ensure data accuracy; How does HeadsUp handle data privacy and security; How does HeadsUp differentiate minor updates from strategic moves |
| **Glimpse**<br>*The competitive intelligence agent* | 71 [68, 74] | #14 of 15, 106 votes, 2026-07; hunter had 0 prior | How does Glimpse ensure data accuracy; How does Glimpse handle data privacy and security; How does Glimpse differentiate genuine moves from noise |
| **NODUS PH Radar for Product Hunt**<br>*Product Hunt analytics beyond the daily leaderboard* | 73 [62, 83] | #15 of 18, 97 votes, 2026-06; hunter had 1 prior | Browser support beyond Chrome; How accurate are launch predictions; How does it compare to other tools |
| **Competely AI Agent**<br>*Instantly find, analyze, and track your competitors with AI* | 68 [65, 72] | #5 of 16, 327 votes, 2025-04; hunter had 33 prior | How does the AI handle niche markets or specific competitor types; How does the tool ensure the accuracy and recency of competitive data; Are there any plans for a native Mac app or desktop client |
| **Fruitful**<br>*Track competitors instantly. Juicy insights every day.* | 51 [47, 56] | #2 of 8, 417 votes, 2025-10; hunter had 253 prior | accuracy of change detection; scalability for tracking competitors; potential for false positives |
| **Parano.ai**<br>*Never miss a competitor's move* | 68 [62, 73] | #33 of 39, 78 votes, 2026-06; hunter had 0 prior | How does it ensure data accuracy and reliability; How does it handle false positives or irrelevant activities; How does it ensure insights are relevant and actionable |
| **hunted.space** *(off Product Hunt; wording ours)*<br>*Real-time Product Hunt launch stats* | 85 [82, 89] | none in our data | AI predictor accuracy and validation; AI predictor handling of niche products/limited data; Pricing model and free trial availability |
| **Visualping** *(off Product Hunt; wording ours)*<br>*Website change monitoring with AI summaries* | 60 [54, 66] | none in our data | How does AI handle complex or JavaScript-heavy pages; How does AI differentiate between minor and significant changes; How does it handle pages behind a login |
| **Crayon** *(off Product Hunt; wording ours)*<br>*Competitive intelligence platform for go-to-market teams* | 31 [26, 35] | none in our data | Data accuracy and filtering irrelevant information; Seamless integration into existing sales processes; Usability and actionability of battlecards for sales reps |

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

| Competitor | Pitch score [95%] (model) | Real Product Hunt finish (real) | Panel's top concerns (model) |
|---|---|---|---|
| **TheySaid 4.0**<br>*See how users will react, right where you build.* | 65 [61, 69] | #1 of 20, 393 votes, 2026-10; hunter had 286 prior | How does this handle complex, multi-step user flows; What are the limitations of synthetic users; How does this ensure synthetic users reflect target audience |
| **Jango**<br>*Test multi-user apps with AI agents that act like real users* | 78 [75, 80] | #12 of 67, 75 votes, 2026-09; hunter had 1 prior | How does Jango handle complex user flows; What is the learning curve for complex scenarios; How does Jango handle data privacy |
| **Synthetic Users (syntheticusers.com)** *(off Product Hunt; wording ours)*<br>*User research without the users* | 70 [66, 73] | none in our data | How reliable is the feedback from synthetic users; How to prevent generic or biased feedback; How to ensure diverse user behaviors and biases |
| **Snap**<br>*Instant usability testing with AI personas* | 72 [67, 76] | #8 of 10, 203 votes, 2025-10; hunter had 168 prior | AI personas missing nuanced human behavior; Accuracy and depth of AI-generated recommendations; Potential for AI personas to provide superficial feedback |
| **Uxia**<br>*Validate your User flows UX & UI in seconds with AI* | 60 [57, 64] | #1 of 5, 535 votes, 2025-09; hunter had 25 prior | How does Uxia handle complex user flows; How accurate are synthetic users compared to real users; How customizable are the synthetic user personas |
| **Userology AI**<br>*The AI user research agent for busy product teams* | 74 [71, 78] | #2 of 11, 347 votes, 2025-12; hunter had 89 prior | How does AI ensure quality of recruited users; How does AI handle nuanced feedback; How does AI handle edge cases |
| **Velozity**<br>*AI-Powered instant user research tool* | 59 [52, 65] | #2 of 8, 284 votes, 2025-05; hunter had 0 prior | Accuracy and bias of AI-generated insights; Depth and realism of AI responses; Data privacy and security |
| **Testifly**<br>*Autonomous AI QA. Zero prompting. Zero maintenance.* | 73 [68, 78] | #3 of 38, 266 votes, 2026-11; hunter had 447 prior | AI might miss critical user paths or edge cases; Potential for false positives or missed edge cases; Difficulty integrating with less common web frameworks |
| **Articos**<br>*Launch with confidence, not gut instinct* | 56 [49, 61] | #3 of 21, 385 votes, 2026-09; hunter had 479 prior | How does Articos handle niche ICPs; How does Articos prevent bias in its simulated personas; What are the limitations of the simulated personas |

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

- **Significant-update case (judgment).** A different use case: products 1 and 2 read pages and comments; this one operates the product itself, and a competitor's, in a browser. A different user too: product teams after launch, not makers before it.
- **Ship gate.**
  - Complaint recall and confirmed-finding share are measured on 30+ products and published, whatever they are.
  - A run completes on 9 of 10 arbitrary sites without getting stuck.
  - The interest rating is gone from the panel, and no forced-choice score replaces it (it failed its test; see "The panel's forced choice failed its test").

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

| Competitor | Pitch score [95%] (model) | Real Product Hunt finish (real) | Panel's top concerns (model) |
|---|---|---|---|
| **Sapien**<br>*AI market research with synthetic populations* | 62 [59, 64] | #25 of 26, 65 votes, 2026-10; hunter had 0 prior | How to ensure synthetic populations accurately reflect real-world nuances; How to handle biases in synthetic population generation; How to validate the accuracy of synthetic audience responses |
| **Plurai Simulation**<br>*A simulated world that makes your agent improve on every run* | 65 [60, 70] | #1 of 37, 382 votes, 2026-11; hunter had 410 prior | overhead of running simulations; how to handle complexity of mocking APIs; how to ensure diverse synthetic data |
| **Aaru** *(off Product Hunt; wording ours)*<br>*Simulate populations to predict how they will respond* | 65 [60, 69] | none in our data | Potential for AI bias or misuse; Cost and accessibility for smaller businesses; Complexity and learning curve for users |
| **Artificial Societies** *(off Product Hunt; wording ours)*<br>*Simulate your audience as a society of AI personas* | 63 [57, 68] | none in our data | accuracy of the simulation; transparency of AI decision-making; scalability and resources required |
| **Simile** *(off Product Hunt; wording ours)*<br>*A foundation model for human behaviour* | 69 [66, 72] | none in our data | Accuracy and bias of 'trained on interviews' data; Potential for oversimplification of human interactions; Ethical implications of simulating human behavior |
| **AI Creative Insights by Decode**<br>*Predict which ad wins before you spend on media* | 73 [69, 76] | #9 of 27, 110 votes, 2026-09; hunter had 1 prior | How does the AI handle different ad contexts; How accurate is the AI for diverse audiences; What are the limitations of the AI |
| **Foresight by Lightning Rod**<br>*Predict anything with AI* | 65 [60, 70] | #3 of 19, 227 votes, 2026-06; hunter had 212 prior | How does the API handle biases in historical data; What's the pricing model for the API; How does the API handle ethical implications of forecasting |

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

- **Significant-update case (judgment).** A different use case: products 1–3 describe what is; this one answers "what if". No earlier product takes a proposed change as input.
- **Ship gate.**
  - The one scored claim has 30 days of public record.
  - Every answer is by group, with a band; "no clear signal" is a possible answer.
  - The page says: Product Hunt market only.

## What the chain shows

- **One doubt runs through all four products: is the simulated thing real?** It is the top panel theme for products 1 and 3 and the top real-comment question on product 1's competitors. Product 2 answers it by using only real comments; product 4 answers it by scoring every prediction in public. Product 3 is the one that cannot answer it yet (complaint recall 24%).
- **The top reason not to use product 2 is that it does nothing to your own product.** That is the feature-by-feature reason product 3 exists, and it comes from the panel only (model output); no real commenter said it.
- **The best real support for any feature in the chain is for testing a specific scenario** (13 real commenters on user-testing launches). It supports product 4's core input.
- **Where real comments and the panel disagree, the real comments are thin.** Most real themes rest on 1–5 people. On Dec 6, product 1's own comments replace stage 1, and the chain should be rerun from there.

---

# Method and evidence

Code and raw output for everything here: `experiments/launch_plan/`.

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

## The panel's forced choice failed its test

To stop the panel rating everything "high interest", each persona was made to pick 3 launches from a real line-up. Scored
on 889 real launches over 30 days [REAL], that ordering has no relation to real rank (0.03 [−0.02, 0.09] for mean place,
0.17 [0.11, 0.23] for pick share, against 0.62 for the forecast model); its top-3 hit is 21% against 59%; it adds nothing
to the forecast model (+1.5 [0.0, +4.5]); and it does not find a group's real backers better than chance (7.9% against
8.4%). It is not used as a score anywhere in this plan. The panel's measured value is which themes come up: recall 61%,
precision 52%, on 167 launches. Code and results: `experiments/simlab/forced_choice_validation/`.

## The pitch judge against real finishes

This is the bias check asked for in the plan review.

- **The judge does not inflate launch and Product Hunt tools.** The 22 competitors with a real launch average 64 on the same line-ups where our four best versions average 82.
- **Across these 22 the score does not predict the finish.** Rank correlation between pitch score and day rank is −0.13 (p = 0.55): no relation. Examples: a visual gallery scored 44 and finished 3rd; a launch-kit generator scored 74 and finished 13th; a platform update scored 37 and finished 2nd with 629 votes.
- **This differs from the stored scores.** For the 14 Product Hunt tools launched in 2026, the score stored at launch time correlates −0.75 with day rank. Two reasons the two checks disagree: this run moves 2025 launches into 2026 line-ups, and it re-scores some tools well above their stored score (one analytics extension: 30 stored, 73 here; a launch toolkit: 55 stored, 74 here).
- **What to take from it.** A pitch score on a line-up that is not the product's own day is noisy by about ±15 points. The pitch score is a weak input (7% of the rank model's gain). Who posted the launch explains these finishes far better: the three #1 finishes in these tables were posted by hunters with 25, 33 and 286 prior launches. Do not read our 75–88 as a forecast of anything.

## Known problems in this run

- Held comments exist only for 2026 launches, so 2025 competitors contribute a finish but no comments.
- Two competitors share a name with unrelated 2026 products. Their comments were wrongly pulled in a first pass and removed before the stage 3 themes were recomputed. Product 4's pitches were written from the first pass; the corrected themes changed counts, not the ranking of the top two.
- Off-Product-Hunt competitors are described in our words from web search summaries; their pitch scores rate our wording.
- A pitch score outside a product's own launch day is noisy by about ±15 points.
