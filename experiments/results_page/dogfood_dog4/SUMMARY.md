# Report page user test: 3 simulated users

- **Product:** the v4 report page (https://raw.githack.com/ShreyasPatel031/UserSim/506ae11753a478a5099a0a81adf62cdcb2ae2602/v4/index.html)
- **Task:** play Excalidraw's head of product. Use the report to choose this week's changes, approve them on the page, then compare the report with the feedback tools you normally use.

Each tester's full run is in `runs/`. UserSim's judge said all 3 completed the task, and all proof checks passed.

| Persona | Actions | Approved | Not now | Enjoyment | Would pay |
|---|---|---|---|---|---|
| founder-design | 25 | #1, #2, #3, #5 | #4 | 7/10 | $49–99/mo |
| founder-saas | 29 | #1, #2, #3, #5 | #4, #6 | 8/10 | $200–400/mo per team, if it ran on every deploy with real analytics; otherwise $50–100 per study |
| dev-marketer | 30 | #1, #3 | #4, #5 | 7/10 | $49–99/mo, if it ran on staging and exported to GitHub |

**Where they agree:**
- **Best feature:** clicking a quote jumps to the exact replay frame. All 3 picked it.
- **Approvals:** all 3 approved #1 (put "Share" on the Share button) and #3 (say the snapshot won't update). All 3 held back #4 because it needs a privacy check.
- **Biggest confusion:** the step counts don't match. The headline says "7 to 16", but sections show 7/8 and 16/17.
- **Method section:** all 3 read its accuracy line (65% of broad points, 9% of exact issues) as "use this for hypotheses, not ground truth".

---

## founder-design
*Design-focused Product Hunt founder; skims and short on time.*

### Preferences
- **First look:** the headline "Excalidraw wins the job. Its Share step is where people hesitate." It gives the verdict in 3 seconds, like a good Product Hunt tagline. Then the race bars.
- **Enjoyed:**
  - The headline verdict.
  - The collapsed ranked list, with effort tags and Approve / Not now on each row.
  - Clicking a quote jumps to that replay moment and shows the tester's thought large.
  - The Friction filter and the "what each persona expected" chips in Voices.
  - Copy as Markdown.
  - The honest Method section.
- **Confusing:**
  - The headline says 7 to 16 actions, but the first rows all show 16.
  - A yellow tick on a step tagged Friction + Split, when the key says red means friction.
  - The 9-colour legend on the race chart.
  - #2's evidence quotes a tester saying the dialog *already* says "no account needed".
  - #5, the hero shortcut, is filed under lower priority.
- **Skipped:**
  - Most of the legend and the full replay.
  - Evidence for #3, #4, #6 and #7.
  - The raw JSON, and the tldraw and side-by-side views.
- **Missing:**
  - The Decide section should open on the collapsed list, and a row should collapse once approved.
  - Variation mocks as polished as a Figma frame.
  - A way to merge #2 and #3.
  - Real motion, or faster scrubbing, in the replay.
  - A confidence level for each change.
  - Sending the approved list straight to Linear or Notion.
- **Would use again:** yes, as a fast first pass. They would still check anything bigger than a copy change against real Hotjar sessions.
- **Compared to usual:** faster and more decisive than Hotjar or UserTesting videos. It's closer to a Maze summary but with the reasoning in words and a ship list built in. It's less trustworthy than real recordings, and the page says so. It's far better than a Google Doc write-up.
- **Enjoyment:** 7/10.
- **Would pay:** yes, about $49–99 a month for a small team. Not Maze or UserTesting prices until it gets better at spotting exact issues (the page says it caught about 9% of them).

### 3 most telling thoughts
- **Step 8:** "It jumped straight to Makers step 14 … This is better than Hotjar: Hotjar shows me the mouse wiggle, this shows me what they were thinking. One snag: the sticky 'approved' bar sits right over the player controls."
- **Step 15:** "'65% of broad points, about 9% of exact issues' … treat this as a gut-check, not ground truth. I'd want a real Hotjar session before shipping anything bigger than copy."
- **Step 17:** "THIS collapsed view is what should greet me first: four rows, effort tags, Approve buttons, done in 30 seconds."

---

## founder-saas
*SaaS founder with many launches; wants the answer first, then the evidence.*

### Preferences
- **First look:** the answer-first headline, then the race chart, which shows tldraw's sign-in wall at a glance.
- **Enjoyed:**
  - The ranked change list with effort, audience and risk tags.
  - A quote's "watch" link lands on the exact frame, with a "Back to the decision" button.
  - The "why" box on each change.
  - Copy for Claude Code / Copy as Markdown.
  - Red risk tags such as "needs a privacy check".
  - The honest accuracy line in Method.
- **Confusing:**
  - The headline says Share is where people hesitate, but the race chart shows labelling uses most of the actions.
  - Step counts don't match across sections (7/16 vs 8/17) until Method explains that opening the page is step 0.
  - The #1 before/after frame is mostly empty white, and the current icon sits behind the slider handle.
  - The yellow and red ticks in the replay are hard to read.
  - The Approve button scrolls under the sticky nav while you type the "why".
- **Skipped:**
  - #7.
  - Most of Voices, which repeats the quotes from Decide.
  - The Side by side and Highlights views.
  - The tldraw replays and the raw JSON.
- **Missing:**
  - Ranking by business impact, such as activation or revenue.
  - Real usage numbers to size each issue.
  - An expected lift per change and a metric to watch after shipping.
  - "No account needed" on the landing page, not only inside the share dialog.
  - A confidence level for each finding.
  - Export straight to Linear or Jira.
- **Would use again:** yes, as a cheap way to generate hypotheses. They went from the report to 4 reasoned approvals in about 5 minutes, against an afternoon of UserTesting videos. Not for pricing or revenue calls.
- **Compared to usual:** much faster than UserTesting.com, FullStory or Hotjar, where most of the time goes on scrubbing to find the 10 seconds that matter. Tighter than a Google Doc, because you approve on the same page. Weaker on scale and truth: Maze gives numbers from real users, this gives reasons from simulated ones.
- **Enjoyment:** 8/10.
- **Would pay:** about $200–400 a month per team if it ran on every deploy and pulled in real analytics. Otherwise about $50–100 per study.

### 3 most telling thoughts
- **Step 6:** "Clicking the quote dropped me on the exact frame... In FullStory I'd be scrubbing a 4-minute session to find this. That's the thing I've wanted for years."
- **Steps 22–23:** #5 (8 vs 17 steps, tagged activation speed) is buried under lower priority. "The ranker weights 'how many testers hit it', but for me 'activation speed' at S effort beats a findability nit everyone got past on first click... I'd actually rank it #1."
- **Step 26:** "I'm not putting an upsell into the core share flow off one AI tester... What I really want here is: how many real users click Excalidraw+ from that dialog today. The report can't tell me that."

---

## dev-marketer
*Developer-marketer and engineer; wants to see the raw evidence and how the numbers were made.*

### Preferences
- **First look:** the verdict headline and the SIMULATED badge. Then the numbers: the headline said "7 to 16", but every Excalidraw row they could see said 16.
- **Enjoyed:**
  - Clicking a block in the race chart opens that moment in the replay.
  - Clicking a quote jumps to its exact frame, with "Back to the decision".
  - The "done in 7 actions ✓" overlay in the side-by-side view.
  - Change cards that show size, audience and risk flags.
  - Copy for Claude Code / Copy as Markdown.
  - The honest Method accuracy line and the raw JSON.
  - The Voices filters.
- **Confusing:**
  - The "7" in the headline comes from a run that never labelled its boxes, which the task required.
  - "4 of 4 hesitated", when all 4 quotes show a first-try click.
  - "3 of 4 unsure", with only 2 quotes shown.
  - Step counts that differ by one between sections (7/8, 16/17).
  - A "Split" tag on the plain tester's own run.
  - #2 uses tldraw data as evidence for an Excalidraw change.
- **Skipped:**
  - The tldraw full runs and the Highlights tab.
  - The evidence for #2, #6 and #7.
  - The JSON download.
- **Missing:**
  - The caveats next to the headline, not only at the bottom in Method.
  - Which model played the testers, and how the judge decides a pass.
  - Readable names in the JSON instead of ids like `group-1__comp1`.
  - A preview of what Copy puts on the clipboard, and a GitHub issue export.
  - Real DOM replay instead of stepped screenshots.
  - A change for the "Is it open source?" question.
  - More than one run per persona.
- **Would use again:** yes, as a fast first pass. Linking each claim to its evidence beats their current tools, but they'd treat every count as a guess until the counts match the quotes.
- **Compared to usual:** faster to a decision than scrubbing PostHog or FullStory replays, and it gives each tester's thought at each step. That beats a Google Doc because every claim links to its frame. It's weaker on ground truth: simulated people, one run each, screenshots rather than DOM replay, and some summaries overstate their evidence.
- **Enjoyment:** 7/10.
- **Would pay:** yes, about $49–99 a month, if it ran against staging builds and exported to GitHub. Not more until the numbers are checkable and match the quotes.

### 3 most telling thoughts
- **Step 8:** "the Observers quote literally says 'Didn't bother labeling, it's a sketch', so the 7-action 'success' did NOT meet the task… and the headline '7 to 16' rests on it… '4 of 4 testers hesitated', but all 4 quotes say 'looks like a share icon… clicking it'. Nobody actually got stuck."
- **Step 10:** "The quote-to-frame link is the killer feature, exactly what I want: claim -> raw frame. And the frame proves my point: three EMPTY boxes."
- **Step 24:** "the Method section answers my two gripes… But that admission belongs next to the headline '7 to 16', not at the very bottom… 9% is low, so I should treat specific counts like '4 of 4 hesitated' as hypotheses."

---

## Notes on the run files
- **Not checked:** I couldn't confirm the 3 files in `runs/` parse as JSON, because running a shell command needed approval.
- **Steps shortened:** in founder-saas and dev-marketer, the `report` block points to the top-level `steps` array instead of repeating it. The text is the same.
- **Scratch files:** founder-saas left 2 scratch files (`meta.json` and `report.json`) in the session scratchpad, outside the repo.
