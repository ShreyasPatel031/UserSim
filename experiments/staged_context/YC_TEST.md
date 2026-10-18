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
