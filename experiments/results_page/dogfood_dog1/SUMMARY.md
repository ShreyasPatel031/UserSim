# Report dogfood: 3 sim-user cells

Product: Excalidraw user-test report (`v1/index.html` @ 1a8c33a). All cells had the same task: decide what to ship this week, approve it on the page, and compare the report with the usual feedback tools.

| Cell | Status | Steps | Approved | Raw run |
|---|---|---|---|---|
| founder-design | completed. UserSim judge: goal reached, proof checks passed | 26 actions | 4 of 7 | `runs/founder-design.json` |
| founder-saas | completed. UserSim judge said **not** reached ("no changes approved"), which looks wrong: screenshots at steps 15/20/22/26 show green Approve buttons, and the Ship list reads "4 of 7 approved" | 30 | 4 of 7 | `runs/founder-saas.json` |
| dev-marketer | **stopped early.** Anthropic's safeguards flagged a message and ended the agent before its final write. The file is a partial draft: it has a `notes` summary and steps 1 to 8, but no `preferences` block | ≥8 recorded | 3 of 7 (per its notes) | `runs/dev-marketer.json` (truncated) |

## What each persona shipped

| Variation | design | saas | dev |
|---|---|---|---|
| "No account needed" on link option | ✅ | ✅ | ✅ |
| "Share" label on Share button | ✅ | ✅ | ✅ |
| "Snapshot won't update" line | ❌ | ✅ | ✅ |
| Rename "Start session" to "Copy live link" | ✅ | ❌ (behaviour change, privacy review) | ❌ (label misdescribes the action) |
| Flowchart shortcut chip | ✅ | ❌ (quote shows testers saw the hint) | ❌ (confounded) |
| Excalidraw+ plans link in dialog | ❌ | ✅ | ❌ |
| Fold style panel | ❌ | ❌ | ❌ |

All three approved the two cheap copy changes and rejected the style-panel change. They split on everything that changes behaviour or monetization.

---

## 1. founder-design

**preferences**
- **first_look:** The headline "Excalidraw wins the job. Its Share step is where people hesitate." plus the 4x2 results table. Verdict and problem area within five seconds, like a well-written Notion TL;DR.
- **enjoyed:**
  - Opinionated headline and results table
  - Replay with the tester's thought beside each screen, plus friction/split tags (Hotjar plus think-aloud)
  - Voices: four columns of tagged quotes
  - Clicking a quote jumps to that moment in the replay
  - Before/after slider on every change
  - "No account needed" as positioning against tldraw
  - Ship list at the end
- **confusing:**
  - Where an approval goes and who sees it
  - How HIGH/MEDIUM/LOW are decided (Share label is MEDIUM despite 4/4)
  - The flowchart variation's description and mock disagree
  - An Observers quote contradicts the "nobody was told" claim
  - Two overlapping variations under one card
  - Similar greens in the path colours, and one legend item with no swatch
- **skipped:**
  - Clicking Paths squares
  - Watching autoplay to the end
  - The tldraw and Side-by-side tabs
  - Sliders on the snapshot and style-panel cards
  - Most per-run "How it ended" text
- **missing:**
  - Export of the Ship list (Linear/Notion/Slack) with a "why" per decision
  - Effort/cost per variation
  - Confidence or sample size per finding
  - Polished, correctly cropped mocks
  - A fix for the replay sidebar overflow
- **would_use_again:** Yes. It went from "what happened" to a 4-item ship list in about 25 actions without an hour of video. Before trusting it alone, they'd want polished mocks, an exportable ship list and visible evidence weight.
- **compared_to_usual:** Faster and more decision-shaped. Hotjar and FullStory are silent recordings, UserTesting costs an hour of video, Maze gives paths without the why, and Docs give conclusions without proof. This page puts the verdict, paths, quotes, jump-to-moment and before/after on one page. The trade-off is that the testers are simulated with one run per group, so it's a first pass. They'd still watch one or two real Hotjar sessions before a bigger change.

**Most telling thoughts**
- **Step 9:** "The quote click jumped me straight to the Makers run at step 16… like clicking a Dovetail highlight and landing on the video timestamp. But the right sidebar is broken: it spills off the right edge… That's the kind of thing that makes a report feel unfinished."
- **Step 22:** "Approving… But the mock doesn't match the description: the text says a chip next to the first box after it's drawn, the mock shows a blue pill under the toolbar… Which one am I approving?"
- **Step 26:** "There's a Ship list at the bottom: '4 of 7 variations approved'… That's the payoff… But there's no button to export it, copy it, or send it to the team, and no place to write my 'why' for each decision. It just ends."

## 2. founder-saas

**preferences**
- **first_look:** The headline sentence, then the 4x2 outcome grid: answer first, evidence second, exactly the order they want.
- **enjoyed:**
  - A headline that states the conclusion
  - Coloured timeline ticks to jump to the moment that matters instead of watching video
  - The Paths chart as a funnel at a glance
  - Voices quotes that jump to the exact frame
  - Before/after sliders
  - Approve / Not now with a live Ship list
  - The honest "How far to trust this" caveat
- **confusing:**
  - Whether the "4 testers" were real people (only disclosed in the footer)
  - "Product Makers · 6,500 people" reads like a sample size
  - Priority scoring is unexplained and looks inverted
  - Off-by-one between the tick label and the step counter
  - A quote contradicts its own card
  - Whether a replay frame shows the moment before or after the action
- **skipped:**
  - Watching any run end to end
  - The tldraw replays and other tester tabs
  - Most Paths squares
  - Sliders on the last three cards
- **missing:**
  - Ship list or recommendations at the top, or sticky
  - Effort/risk per variation
  - An expected-impact metric per variation
  - Export to Linear/Jira/Slack
  - A conflict warning when two approved variations use the same UI slot
  - Simulated-tester disclosure and sample size next to the headline
  - An explanation of priority scoring
- **would_use_again:** Yes, as a fast first pass before a real experiment. It went from report to a defensible ship list with evidence in about 30 actions. It's not validation; they would A/B the copy changes they picked.
- **compared_to_usual:** Far faster to act on than UserTesting videos or FullStory/Hotjar recordings, because it jumps to flagged moments with the thought written next to them. More actionable than a Google Doc or an Intercom export, since every recommendation has a mock and an Approve button. Less trustworthy than real users: one simulated session per segment, disclosed only at the bottom. It lacks Maze's summary-first layout and a PM-tool hand-off.

**Most telling thoughts**
- **Step 30:** "This footnote changes how I read everything above: these are SIMULATED testers, '65% of broad points but only ~9% of exact issues'… it belongs next to the headline, not at the very bottom after I've approved 4 changes… I'd never have guessed '4 testers' meant AI agents."
- **Step 24:** "Here the evidence undercuts the recommendation, and I like that the page lets me see it: the Makers quote says 'Nice, there's a hint: Ctrl+arrow… Let me label this box first.' They SAW the hint… 'Not now'."
- **Step 26:** "Approving even though it's marked LOW… But note: it occupies the exact same footer slot as the 'snapshot won't update · Share live instead' line I already approved. The page doesn't warn me that two approved variations collide."

## 3. dev-marketer (partial run)

**preferences:** not recorded. Safeguards stopped the agent before it wrote the final file. Below is what its saved `notes` field says, mapped onto the preference fields as closely as it allows. This is not the persona's own preferences block.
- **first_look (step 2):** Headline and grid. Clear claim, but "Product Makers · 6,500 people" is unexplained, and they wanted the methodology before trusting anything.
- **enjoyed:**
  - Headline and outcome grid
  - The replay with thoughts ("PostHog never tells me WHY")
  - Quote-to-moment deep links
  - The Paths grid
  - Before/after sliders
  - The automatic ship list
- **confusing:**
  - The "6,500 people" chips
  - The methodology hidden at the bottom in small grey text
  - Evidence contradicts claims twice
  - A split tag on a Makers step talks about Observers
  - Side-by-side aligns by step index rather than by milestone
- **skipped:** not recorded
- **missing:**
  - Export to GitHub/Linear
  - A way to comment on Not now
  - Raw logs
- **would_use_again / compared_to_usual:** The per-step "why" is something PostHog replays never give, and it's far faster to scan than UserTesting videos. But with simulated testers (n=1 per group) it is hypothesis generation only, to be checked against real PostHog data before shipping anything bigger than copy.

**Most telling thoughts (from the recorded steps)**
- **Step 3:** "So '6,500 people' is unexplained — is one simulated agent standing in for 6,500 people? That's a big leap n=1 per group."
- **Step 6:** "The thought log is actually nice — PostHog never tells me WHY. But 'like in Miro' is suspiciously articulate for a user."
- **Step 8:** "Side by side syncs by step index (15/17 vs 15/34), not by milestone, so tldraw is mid-drawing while Excalidraw is in the share modal. Aligning by 'reached share' would be more useful."

---

## Themes shared by all three
1. **The simulated-tester disclosure is buried.** All three found the methodology late and trusted the page less once they did (saas step 30, dev step 3).
2. **The Ship list is the deliverable, but it sits at the bottom with no export.** All three asked for Linear/Notion/GitHub hand-off and a "why" field.
3. **Evidence contradicts claims in places.** The Observers "no account needed" quote was flagged by all three. The flowchart mock and description mismatch, and the flowchart hint was already seen by testers.
4. **Priority labels are unexplained.** Share is MEDIUM at 4/4 while the snapshot line is HIGH.
5. **Layout bugs at 1280px:** the replay sidebar overflows, mock button text clips, and a legend swatch is missing.
6. **What everyone praised:** the answer-first headline, quote-to-moment jumps, think-aloud next to the replay, and before/after sliders. All three said it was much faster than their usual video and recording tools.
