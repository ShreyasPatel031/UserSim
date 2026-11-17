# Six-month launch plan: 4 Product Hunt launches, two months apart (UserSim as its own customer)

Written Nov 17 2026 for a maker with 0 followers and no launches. Plan first, method and evidence after, superseded numbers
in the appendix.

**How to read the labels.** [MODEL] = output of the midnight forecast model (arm 2) on 56 real line-ups, Sep 21 – Nov 15
2026. [REAL] = outcomes of real launches. [JUDGMENT] = my call, not measured. Intervals are 95%, bootstrapped over days.

## The four launches

| # | Date | Product | Job and user | Different under Product Hunt's rule because | Day and reason | P(top 5) this launch [MODEL, row A] | At least one top 5 by now: raw / scaled |
|---|---|---|---|---|---|---|---|
| 1 | **Sat Dec 5 2026** | Launch Simulator (/try) | A maker sees how one page will land before posting | First launch | Saturday: rank and record | 17.6 [10.7, 24.3] | 18 / 13 |
| 2 | **Sat Feb 6 2027** | Daily Forecast | Anyone watching Product Hunt sees today's ranking before votes show | Different user (watchers, not only makers) and a different job (today's ranking, not my page) | Saturday: rank and record | 27.5 [19.0, 35.7] | 35 / 27 |
| 3 | **Sat Apr 10 2027** | Persona Panel | A product or marketing team hears from audience segments, compares versions, defines its own segments | Different user (teams doing user research, on any page) and a new app surface | Saturday: rank | 31.6 [21.7, 40.8] | 49 / 39 |
| 4 | **Tue Jun 15 2027** if a hunter with a record posts it, else **Sat Jun 12** | Launch Pack (paid) | A founder buys a full service across one launch, with scored reports | Different job (a paid service with reports), different buyer | Weekday for traffic only with a hunter; Saturday otherwise | Sat 34.2 [23.6, 44.6]; Tue–Thu 13.8 [10.4, 17.6] | Sat 60 / 49; Tue–Thu 51 / 41 |

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

## Answers to the four sequence questions [JUDGMENT]

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

## How feedback on product 1 defines products 2, 3 and 4

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

**Competitors.** Each product is also defined against its 5–8 closest competitors: their pitch score, their real Product
Hunt finish, what real users said on their launches, what they do better and what we do better. That run is with E5
(`docs/LAUNCH_PLAN_COMPETITORS.md`, due about 07:00Z Nov 17); it is not in this document yet, and the world-class claims
below stay candidates until it is.

## Launch 1. Launch Simulator (/try). Saturday Dec 5 2026

- **Job and user.** A maker pastes a URL and sees where the launch would land, before posting.
- **World-class claim (candidate).** "The only launch predictor that publishes its own score: the range it gives covers
  80% of real results." **Test before launch day:** the 10–90% range's coverage on the latest 60 days of real launches is
  between 76% and 84%, and that number with its day count is on the page. Today: 80% [REAL, backtest]. E5's competitor
  run will confirm or replace this claim.
- **In.** One URL in; a rank range; the three most likely reactions; the measured accuracy with its limits above the fold;
  a "what this uses and what it ignores" block; a plain sentence for people who have never launched.
- **Held back.** Per-segment reactions, version comparison, custom segments, follow-up questions (launch 3). The reason
  behind a forecast, weekly and monthly views, email (launch 2). Reports, a pre-launch audit, post-mortem (launch 4).
- **Competitors and the three things to beat.** Pending E5's run (`docs/LAUNCH_PLAN_COMPETITORS.md`).
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

## Launch 2. Daily Forecast. Saturday Feb 6 2027

- **Job and user.** Anyone who follows Product Hunt sees which launches will finish on top today, before votes are visible,
  with the reason for each.
- **World-class claim (candidate).** "Names the day's top 3 before any votes show, and has published every hit and miss
  since November 2026." **Test:** live top-3 hit over at least 75 scored live days, shown beside a named simple baseline
  (the hunter's record alone). Today: 73.8% over 14 live days at the before-votes point [REAL, forward]; backtest 72.2%
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

## Launch 3. Persona Panel. Saturday Apr 10 2027

- **Job and user.** A product or marketing team puts any page in front of audience segments built from real voting
  behaviour, compares versions, and defines its own segments.
- **World-class claim (candidate).** "Predicts what real people will say: it names about 6 in 10 of the themes real
  commenters raise, and we publish the score." **Test:** theme recall and precision against the real comments on our own
  launches 1 and 2 and on at least 100 other launches. One definition everywhere: **theme recall 61–63%, precision about
  50%** [REAL, backtest]; it beats pulling real comments from similar past launches (F1 0.52 against 0.43).
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

## Launch 4. Launch Pack (paid). Tuesday Jun 15 2027 with a hunter, else Saturday Jun 12

- **Job and user.** A founder pays for a full service across one launch: a pre-launch audit, the launch-day read, and a
  post-mortem.
- **World-class claim (candidate).** "Every report is scored afterwards against what happened, and the scores are public."
  **Test:** at least 20 pilot launches with the audit's predicted themes and rank range scored against the real result.
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
  | 1 /try | 500 runs | 100 for version comparison | 10 Launch Pack pilot conversations |
  | 2 Forecast | 1,000 visitors on launch week | 200 daily-email subscribers | 10 more pilots |
  | 3 Panel | 150 teams running a comparison | 300 | 20 pilots completed in total |
  | 4 Launch Pack | — | — | 10 paid at full price in 30 days |

- **Stop rule after launch 2.** Change the sequence or the product if, after Feb 6, both launches finished outside the top
  10 **and** /try has under 50 runs a week. Then launch 3 becomes whichever product real users asked for most, and the
  Panel waits. If rank missed but usage met its targets, keep the sequence and put the effort into the hunter. If the
  panel's recall against our own launches' real comments is under 50%, launch 3's claim is rewritten before it is built.

## Still open
- Competitor tables, the three things to beat per launch, and a check of whether the pitch scorer favours Product Hunt
  tools: E5, due about 07:00Z Nov 17.
- In E5's sections below: the 168 against 210 scoring calls, and labelling the pitch 75 against 85 figures by run
  (5.4 / 6.0 is the server model; 6.2 / 6.4 is E5's rebuild).
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

