# Launch plan as a chain: each product built from feedback on the one before

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
  - The interest rating is gone from the panel; forced choice or nothing.

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

## Known problems in this run

- Held comments exist only for 2026 launches, so 2025 competitors contribute a finish but no comments.
- Two competitors share a name with unrelated 2026 products. Their comments were wrongly pulled in a first pass and removed before the stage 3 themes were recomputed. Product 4's pitches were written from the first pass; the corrected themes changed counts, not the ranking of the top two.
- Off-Product-Hunt competitors are described in our words from web search summaries; their pitch scores rate our wording.
- A pitch score outside a product's own launch day is noisy by about ±15 points.

Files: `experiments/launch_plan/chain_run.py`, `chain_comments_only.py`, `chain_stage1.json` to `chain_stage4.json`.
