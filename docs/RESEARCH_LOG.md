# Research log

Model switches, direction reviews and agenda changes, newest last.

- 2026-11-01: Orchestrator / PH agent split. PH ops + research agent created (session_01WkCrUNGGrvzNTXL69TVZ2w). Daily scheduled task moved to it. X go/no-go sample (400 pairs) sent to Grok Bot.
- 2026-11-01: User decisions: Grok Bot data budget $50/month; two domains only (PH, HN); Fable direction review every few hours (ad hoc), not weekly; Claude capacity at orchestrator discretion (decided: parallel experiment sessions where independent, plus the Fable reviews).
- 2026-11-01: HN agent status. Daily top 30 found 80.2% at 21:00 UTC, 86.0% end of day. Per-post AUC 0.796 at posting, 0.956 at 1 h. Vector twins 0.583, LLM twins 0.540 vs popularity 0.808. Cross-domain: content twins are weak on both PH and HN; popularity and ties dominate. Next on HN: tie strength (submitter's past commenters/repliers x presence at posting hour). Blocker: Grok Bot favorites re-fetch (pages 2-10 duplicated page 1 for 795 people).
- 2026-11-01 18:31 UTC: GCS mailbox set up (mailbox/to_grokbot, from_grokbot); hourly check scheduled in the orchestrator. First requests: PH agent gcloud sign-in (now), standing asks (today). mailbox checked 18:31.
- 2026-11-01 18:40 UTC: PH agent signed in (user approved in its session). Found: upvote pages 403 on all routes since Oct 30, people step reported ok with 0 upvotes; warehouse upvotes end Oct 29. Filed to Grok Bot (now). PH agent will make the step fail loudly and measure tie-strength loss with upvotes hidden 3/7/14 days.
- 2026-11-01 18:40 UTC: Direction review (Fable). Proposed: stop tuning daily top 3 for +-2; settle the pre-launch ceiling with the X test; make person-level accuracy and a qualitative test (simulated reactions vs real comments/reviews) the simulation north star; treat the launch-day forecast as product value, not simulation; infrastructure on two domains is the deliverable. Awaiting user confirmation before changing RESEARCH_PROGRAM.md.
