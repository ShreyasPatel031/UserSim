# Competitor run for the four launches

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

Checked against the feature-to-product map in `docs/LAUNCH_PLAN_SELF.md` ("How feedback on product 1 defines products 2, 3 and 4"). That map is built from the persona panel, which is model output.

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
