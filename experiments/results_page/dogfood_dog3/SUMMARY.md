# Sim-user run: Excalidraw user-test report (v3)

Product: https://raw.githack.com/ShreyasPatel031/UserSim/4751b8286f5b735c85f6489dabfd42034671fe86/v3/index.html
Task (same for all 3): use the report to decide what to ship this week, approve it on the page, then compare the report with usual feedback tools.

| Persona | Steps | Approved | Not now | Enjoyment | Would pay | UserSim judge |
|---|---|---|---|---|---|---|
| founder-design | 27 | #1, #2, #3 | #4 | 8/10 | $49–99/mo | goal_reached=false (wrong, see note) |
| founder-saas | 28 | #1, #2, #3, #5 | #4 | 7/10 | $200–400/mo | goal_reached=false (wrong, see note) |
| dev-marketer | 33 | #1, #3, #5 | #4 | 7/10 | $50–150/mo | goal_reached=true |

**Judge note:** for both founders the judge said nothing was approved. That is wrong. The step screenshots show green "Approved" states and the sticky "N approved" bar: steps 16/20/21 for founder-design and steps 16–26 for founder-saas. The judge seems to look only at the final frame.

**What all 3 hit:**
- The Decide section sits between the race chart and Watch, and anchor jumps (race block, quote, "How this was made") skip past it. Every persona went to the bottom looking for decisions and had to scroll back up.
- Copy as Markdown and Copy for Claude Code show no "copied" confirmation.
- "Not now" isn't shown in the sticky bar or the export.
- The layout shifts under the cursor when a row expands or playback ends, so clicks miss.
- The Hide toggle changes its label but the panel stays open (both founders).
- All three put #4 on Not now because of its privacy flag.
- Every persona called the 65% / 9% accuracy note honest, but it pushed them to treat findings as hypotheses.

---

## 1. founder-design (design-focused PH founder)

**Preferences**
- **First look:** the verdict headline ("Excalidraw wins the job. Its Share step is where people hesitate.") and the colour-coded race chart. Within 5 seconds they knew who won and where the problem was.
- **Enjoyed:**
  - The verdict-first, PH-tagline-style headline
  - The race chart: one glance shows 7–16 steps vs 30–35 behind a sign-in wall
  - The replay with the tester's thought next to each screenshot (Hotjar plus the inner monologue)
  - The Highlights tab: 7 captioned moments instead of 8 full runs
  - Clicking a quote jumps to the exact moment
  - The before/after drag slider, especially #3's one-line snapshot note
  - Evidence, size and audience chips on each change
  - The sticky "N approved" bar with Copy as Markdown / Copy for Claude Code
- **Confusing:**
  - Where the decisions live; clicking the race chart skips past Decide
  - Hide doesn't collapse the panel
  - The layout shifts under the cursor
  - No confirmation after Copy as Markdown
  - Split vs Friction took a second to work out
- **Skipped:**
  - Full runs beyond one play-through
  - tldraw highlights and replays
  - Side by side
  - Most of Voices
  - Raw run data
  - The "why" boxes for #2 and #3
- **Missing:**
  - A sticky table of contents or "Jump to decisions" link
  - Real-user signal next to the simulated one (e.g. how many Hotjar sessions hit the same icon)
  - On-brand mocks
  - Push to Linear/Notion
  - A one-line "ship this week" recommendation at the top that can be approved in one click
- **Would use again:** Yes. From opening the page to a 3-item ship list in about 25 actions, faster than watching one UserTesting video. They'd use it as a first pass before a launch, then confirm with real recordings.
- **Compared to usual:** Faster and more decisive than Hotjar/FullStory, and more actionable than a Google Doc. Weaker than UserTesting.com or Intercom on trust: simulated personas with one run each, and a 9% exact-issue accuracy note. Maze gives numbers across many real users; this gives the why in depth for a few simulated ones.
- **Enjoyment:** 8/10
- **Would pay:** Yes, $49–99/mo, if it runs on their own product before each launch. Not UserTesting-level prices, because it's simulated.

**Most telling thoughts**
- **Step 3:** "This is the Hotjar recording but with the tester's inner monologue, the thing Hotjar never gives me. The friction 'Share is an icon with no label' is crisp."
- **Step 10:** "Wait, that's the bottom… no list of changes or Approve buttons. Where's the ship list?… mildly annoying, I expected the decisions at the end like a Notion doc's 'Next steps'."
- **Step 14:** "The slider makes the change obvious in 2 seconds… The mock is a bit crude (a blue pill pasted over our purple, off-brand), but the point lands. 4 of 4 hesitated + S-size copy = no-brainer."

## 2. founder-saas (experienced SaaS founder)

**Preferences**
- **First look:** the headline, then the race chart, where tldraw's purple/red sign-in wall jumps out. Then the SIMULATED badge, which made them discount everything a notch.
- **Enjoyed:**
  - The answer-first headline: the verdict in 10 seconds
  - The race chart, which makes the competitor's sign-in wall obvious
  - The ranked list with S/M size, audience and red risk flags next to Approve/Not now
  - Quote → exact replay step with thought, friction and split tags
  - The "How it ended" text recap (a 20-second read instead of a 16-step watch)
  - The Voices filters and per-persona expectation chips
  - The Why box plus Copy as Markdown / Copy for Claude Code
  - The honest 65% / 9% trust section
- **Confusing:**
  - The #1 slider looks identical until dragged to the far edge
  - A quote click silently jumps you down to Watch
  - The player grows when playback ends, so clicks miss
  - The Hide label and panel state disagree
  - #2 says nothing mentions "no account needed", but an Observers quote says the dialog does
  - Whether Copy as Markdown copied anything
  - "Persona from 6,500 users" reads like 6,500 testers
- **Skipped:**
  - Evidence for #3 (approved on the badge alone), #6 and #7
  - Highlights
  - tldraw full runs
  - Raw data
- **Missing:**
  - Impact estimates in activation, share-rate and upgrade terms
  - Sort by activation or revenue impact
  - A bigger sample, confidence intervals, or a path to validate with real users (A/B or Maze)
  - Not now and its reasons in the export, plus a copied confirmation
  - A sticky mini-nav and a "back to decision" link
  - Push to Linear/Jira/GitHub
  - A pricing/monetisation lens
- **Would use again:** Yes, as a fast first pass before paying for real-user tests. They got to four approved changes with reasons in about 4 minutes, which no FullStory or UserTesting project has done. Not the final word, at n=4 and 9% accuracy.
- **Compared to usual:** Much faster to a decision than FullStory/Hotjar or UserTesting videos ("hours of footage and nobody watches it"). The clickable slideshow with thoughts is something they actually used. It's closer to a senior researcher's Google Doc, but with linked evidence and approve buttons. Weaker than Maze on quantitative confidence and weaker than Intercom on real customer voice.
- **Enjoyment:** 7/10
- **Would pay:** Yes, $200–400/mo per product team for continuous runs. Above $500/mo only with validation against real A/B outcomes and a Linear/Jira integration.

**Most telling thoughts**
- **Step 7:** "The quote click did work. It jumped me to the replay at 'Plain tester, Excalidraw, step 14'… a lot faster than scrubbing a FullStory session to the right timestamp. The jump scrolled the page away from the decision list though, which is a bit disorienting."
- **Step 12:** "'About 9% of exact issues'… tells me to treat this as hypotheses to A/B, not truth… no sticky nav or 'back to decisions' link, so I have to scroll."
- **Step 24:** "#5 is the one I'd argue is underranked: halving time-to-first-diagram is an activation lever, and it's S-size… I'm approving it, ranked or not."

## 3. dev-marketer (developer-marketer / engineer)

**Preferences**
- **First look:** the headline, then the black SIMULATED badge, so they went straight to "How this was made" before trusting any number. The race chart was the first visual that pulled them in.
- **Enjoyed:**
  - The replay with click rings and verbatim thoughts ("PostHog replays with the user's monologue attached")
  - Quote → exact frame
  - Synced side-by-side
  - The honest method section
  - Raw run JSON inline
  - Effort, type and risk tags
  - The before/after slider
  - Copy for Claude Code / Copy as Markdown
  - The Ctrl+arrow insight
- **Confusing:**
  - Step counts differ by one (7/16 in the race chart vs 8/17 in the cards), and "step" is never defined
  - An unlabelled flowchart counted as a success
  - "4 of 4 hesitated" isn't backed by every quote
  - Split vs Friction is jargon
  - #2 mixes competitor and own-product counts
  - The Variation label stays on when the slider shows only "Now"
  - No feedback after Copy for Claude Code, and no idea what Approve writes to
- **Skipped:**
  - Highlights
  - Most tldraw frames
  - The Voices filters
  - Evidence for #2, #4, #6 and #7
  - Why notes for #3 and #5
- **Missing:**
  - A downloadable JSON/CSV with screenshot URLs per step
  - A link to the repo or commit, and the prompts and persona definitions
  - An explicit success criterion, and n=4 shown next to every "x of 4"
  - Export to GitHub issues
  - A preview of what Copy for Claude Code produces, plus a copied toast
  - A recommendation for the "Is it open source?" question
  - Variance across multiple runs
  - Comparison with real PostHog funnel numbers
- **Would use again:** Yes, as a fast pre-filter before shipping UI changes: it got them to three cheap, evidence-linked changes in minutes. Not alone for behaviour or privacy changes; they'd validate those with PostHog experiments.
- **Compared to usual:** Faster and more decision-shaped than PostHog/FullStory/Hotjar replays, and more inspectable than a Google Doc. Less trustworthy than UserTesting.com or Intercom, because the users are simulated and the small counting inconsistencies make them double-check numbers. "Maze gives cleaner success metrics; this gives better 'why'."
- **Enjoyment:** 7/10
- **Would pay:** Yes, $50–150/mo for a small team if it runs on preview deploys per PR (CI-style) and exports to GitHub issues.

**Most telling thoughts**
- **Step 12:** "Confirmed: 'I didn't add labels because the task didn't ask for them.'… the race chart still shows it as a clean check. Also a number mismatch: the Observers card says 'a link in 8 steps', the race chart says 7… the kind of inconsistency that makes me distrust every number."
- **Step 19:** "Skeptic hat: the badge says '4 of 4 testers hesitated', but the Observer quote just says 'Clicking it.' That reads like recognition, not hesitation."
- **Step 33:** "Clicked Copy for Claude Code and… nothing visible. No 'Copied' toast… ironic given the report flags exactly this ('No Copied message') as Excalidraw friction."

---

## File status
- `runs/founder-design.json` and `runs/founder-saas.json` are complete. The repeated per-step thoughts were trimmed from the embedded `report.steps`.
- `runs/dev-marketer.json` is **incomplete**: the agent's write was cut off partway through. Running `python3 -I <scratchpad>/build.py <scratchpad>` (in the session scratchpad) rebuilds it from the saved steps and meta. The full report is also available via `usersim_get_report` with study `e8987f1f-223d-42a5-a0cc-f8bbe33f2060`.
