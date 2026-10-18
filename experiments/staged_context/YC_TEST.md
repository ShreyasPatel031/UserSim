# YC test: competitors, customers and tasks for 20 new startups (18 Oct 2026)

Twenty B2B companies from YC Spring and Summer 2026 were picked by hash (`out/yc/yc20.json`). Each one went through
the production path:

1. Competitors from the study planner (`mvp/fast_plan.py`, which also checks that each URL is live). Agent mode uses
   the same planner.
2. Live G2 / Capterra / TrustRadius / Gartner reviews of each competitor and of the startup itself.
3. A model check per competitor: are the reviews of the named product, and is it a direct competitor?
4. Customers: the roles and company sizes of the usable competitors' reviewers.
5. Tasks: the competitors' users' top use cases and the `usersim_plan_human_run` task.

`yc_test.py`; full output in `out/yc/yc_report.json`.

## Update: with more competitors, 16 of 20 have usable data

The first pass used only the study planner's 2 competitors per startup. For the 10 flagged startups, a model then
named 6 established products listed on G2 / Capterra / TrustRadius / Gartner (`out/yc/more_rivals.json`). Those were
scraped and judged the same way (`yc_test.py more`, `out/yc/more_rivals_report.json`).

- **6 of the 10 recover**, with 3–5 usable competitors and 270–500 reviewers each.
- **That makes 16 of 20 YC startups with usable competitor data**, against 10 with the planner alone.
- **The fix belongs in discovery:** ask for established products listed on review sites, not the 2 nearest look-alikes.
  The agent-mode session's wider discovery (PR #98) does this.
- **The 4 left are real gaps, not tool failures:**
  - Parasma (brain-cell compute) and MusicArena (AI-music benchmark): no product on any of the four sites does the
    same job.
  - transload (freight measurement from cameras): its true rivals (Cubiscan, FreightSnap) have no reviews.
  - Dock ("AI agents run your business"): every candidate was judged "no". Zapier and UiPath are arguably partial;
    the judge is strict.

| Startup | What it does | Usable competitors (judged, reviews) | Reviewers | Top use case |
| --- | --- | --- | --- | --- |
| TryNearby | Local creators for local businesses | Grin (partly, 100), Aspire (partly, 99), Upfluence (partly, 99), HypeAuditor (partly, 99), Fiverr (partly, 100) | 497 | Manage influencer relationships and communications. |
| transload | Measure freight with security cameras | **none** | 0 | – |
| Parasma | Replacing GPUs with human brain cells | **none** | 0 | – |
| Amorphic Labs | OpenRouter for Agent Tools | Zapier (partly, 100), Kong Gateway (partly, 71), Workato (partly, 100) | 271 | Automate workflows between business apps |
| MusicArena | The crowdsourced benchmark for AI-generated music and music production | **none** | 0 | – |
| Enjamb Labs | The AI Workforce for Biopharma | UiPath (partly, 100), Workato (partly, 100), SAS (partly, 98) | 298 | Automate repetitive business processes |
| Mentlio | Engineering Intelligence and Token Optimization for the AI-Coding Era | PromptLayer (partly, 22), Arize AI (partly, 77), Datadog (partly, 100), LinearB (partly, 98) | 297 | Track and version prompts |
| Fuchsia | Vanta for hardware | PTC Windchill (partly, 88), Siemens Teamcenter (partly, 100), Arena PLM (partly, 100), MasterControl (partly, 100), ETQ Reliance (partly, 100) | 488 | Manage document versions and revisions |
| Dock | Hire AI agents to start and run your business | **none** | 0 | – |
| HyperProbe | AI engineer that debugs and fixes production incidents in realtime | Datadog (partly, 100), New Relic (partly, 42), Dynatrace (partly, 100), Lightrun (yes, 95), PagerDuty (partly, 100) | 437 | Monitor applications |

## Results first

- **10 of 20 startups get usable data**: at least one real competitor ("yes" or "partly") with 20+ reviews of the
  right product. For those 10 the tool produced:
  - a customer mix (for example Alkera AI: 78% software/IT/engineering roles);
  - the competitors' users' top use cases;
  - a human-mode run task.
- **The other 10 are flagged instead of guessed.** Either the planner's competitors aren't real competitors, or they
  have no reviews on any of the four sites. Most are deep-tech or very new categories:
  - brain-cell compute;
  - an AI-music benchmark;
  - hardware compliance;
  - a freight camera;
  - local creators.
- **Planner competitors:** 40 named.
  - Judged direct competitors: 5 "yes", 16 "partly", 19 "no".
  - 21 had 20+ reviews of the right product; 14 had none.
  - The planner was URL-verified (every competitor site is live), but being live doesn't mean being a competitor.
    For example, it named Glean and Turing for an AI-spend optimiser, and Adept and Cognition for "AI agents that
    run your business".
- **Own reviews:**
  - 19 of 20 startups have none on any of the four sites, so agent mode has only competitors to go on.
  - **Bug risk:** "Dock" pulled 99 reviews of *other* products named Dock (Dock Health on Capterra, a sales tool on
    G2). Agent mode would use them as the startup's own reviews.
  - The scraper searches by name, and `review_context._same_product` checks only the name. An own-review identity
    check (domain, or a relevance check like the one here) is needed before using own reviews.
- **Review-site coverage is the limit for new AI infrastructure companies.** Their real competitors (Deepgram,
  Shoreline, Superagent, vLLM, Cubiscan) often have no reviews. Human mode, a browser run on the startup itself, is
  the only first-hand source for them.

## Per startup

| Startup | What it does | Planner competitors (judged direct?, reviews) | Usable | Top customer roles | Top competitor use case |
| --- | --- | --- | --- | --- | --- |
| TryNearby | Local creators for local businesses | Reef (no, 2 rev); Influencer Marketing Hub (no, 0 rev) | **no** | – | – |
| transload | Measure freight with security cameras | Cubiscan (yes, 0 rev); FreightSnap (partly, 0 rev) | **no** | – | – |
| Miso Labs | Emotive foundation voice models | Eleven Labs (yes, 100 rev); Play.ht (no, 100 rev) | yes | software 22%, marketing 22% | Generate voiceovers for videos and content. |
| Luca IQ | API-first tax engine for CPA firms and developers | UltraTax CS (no, 86 rev); Intuit ProConnect Tax (partly, 100 rev) | yes | executive 38% | Prepare and file individual and business tax returns |
| Parasma | Replacing GPUs with human brain cells | FinalSpark (no, 0 rev); Innoskel (no, 0 rev) | **no** | – | – |
| Amorphic Labs | OpenRouter for Agent Tools | Superagent (no, 0 rev); ToolJet (no, 54 rev) | **no** | – | – |
| Alkera AI | Reliable and safe data engineering and data science agents | Atlan (partly, 99 rev); Collibra (partly, 96 rev) | yes | software 78%, general 5% | Discover and understand data assets |
| MusicArena | The crowdsourced benchmark for AI-generated music and music production | Splice (no, 5 rev); Loopcloud (no, 0 rev) | **no** | – | – |
| Speko | OpenRouter for Voice AI: one API, every call on the best speech model | Deepgram (partly, 0 rev); AssemblyAI (partly, 39 rev) | yes | software 52%, education 12% | Transcribe audio to text accurately. |
| AgentPhone | Phone Numbers for AI Agents | Twilio (partly, 100 rev); Vonage (no, 100 rev) | yes | executive 26%, software 23% | Send SMS messages to customers and users |
| Ooak Data | We turn company data into training data | Scale AI (yes, 13 rev); Labelbox (partly, 48 rev) | yes | software 49% | Label data for AI/ML models. |
| Conifer | Least cost routing system to reduce 70%+ token spend | Anyscale (partly, 27 rev); vLLM (no, 0 rev) | yes | software 45% | Scale AI/ML workloads efficiently |
| RASPIRE | Autonomous Runtime Security | Guardsquare (partly, 0 rev); Appdome (partly, 99 rev) | yes | software 34% | Secure mobile applications |
| Enjamb Labs | The AI Workforce for Biopharma | Benchling (no, 83 rev); LabVantage (no, 22 rev) | **no** | – | – |
| Netter | AI agents for data science (enterprise) | DataRobot (partly, 100 rev); H2O.ai (partly, 35 rev) | yes | software 51%, general 9% | Build predictive models automatically |
| Executor | The open source tool gateway | Composio (yes, 23 rev); Superagent (partly, 0 rev) | yes | executive 47%, software 40% | Automate repetitive tasks and workflows |
| Mentlio | Engineering Intelligence and Token Optimization for the AI-Coding Era | Glean (no, 100 rev); Turing (no, 22 rev) | **no** | – | – |
| Fuchsia | Vanta for hardware | ComplianceGate (partly, 0 rev); CE-Check (no, 0 rev) | **no** | – | – |
| Dock | Hire AI agents to start and run your business | Adept (no, 99 rev); Cognition Labs (no, 2 rev) | **no** | – | – |
| HyperProbe | AI engineer that debugs and fixes production incidents in realtime | Shoreline.io (yes, 0 rev); Blameless (partly, 1 rev) | **no** | – | – |
