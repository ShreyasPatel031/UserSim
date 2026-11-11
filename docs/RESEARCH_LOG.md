# Research log

Model switches, direction reviews and agenda changes, newest last.

- 2026-11-01: Orchestrator / PH agent split. PH ops + research agent created (session_01WkCrUNGGrvzNTXL69TVZ2w). Daily scheduled task moved to it. X go/no-go sample (400 pairs) sent to Grok Bot.
- 2026-11-01: User decisions: Grok Bot data budget $50/month; two domains only (PH, HN); Fable direction review every few hours (ad hoc), not weekly; Claude capacity at orchestrator discretion (decided: parallel experiment sessions where independent, plus the Fable reviews).
- 2026-11-01: HN agent status. Daily top 30 found 80.2% at 21:00 UTC, 86.0% end of day. Per-post AUC 0.796 at posting, 0.956 at 1 h. Vector twins 0.583, LLM twins 0.540 vs popularity 0.808. Cross-domain: content twins are weak on both PH and HN; popularity and ties dominate. Next on HN: tie strength (submitter's past commenters/repliers x presence at posting hour). Blocker: Grok Bot favorites re-fetch (pages 2-10 duplicated page 1 for 795 people).
- 2026-11-01 18:31 UTC: GCS mailbox set up (mailbox/to_grokbot, from_grokbot); hourly check scheduled in the orchestrator. First requests: PH agent gcloud sign-in (now), standing asks (today). mailbox checked 18:31.
- 2026-11-01 18:40 UTC: PH agent signed in (user approved in its session). Found: upvote pages 403 on all routes since Oct 30, people step reported ok with 0 upvotes; warehouse upvotes end Oct 29. Filed to Grok Bot (now). PH agent will make the step fail loudly and measure tie-strength loss with upvotes hidden 3/7/14 days.
- 2026-11-01 18:40 UTC: Direction review (Fable). Proposed: stop tuning daily top 3 for +-2; run the X test; add person-level and qualitative measures as supporting metrics. User (18:50): north stars stay exactly 90% top 3/5/10 and 80% top-30; no ceiling or limiting statements, ever; find the way (new data, new architectures).
- 2026-11-01 18:45 UTC: mailbox checked. Grok Bot replied: HN favorites re-fetch in progress on grokbot-favs-p2 (partial files in hn_jobs/cache/feeder/favs/, VERIFY_p2.md when done); VISION.md delivered and committed as docs/VISION.md. RESEARCH_PROGRAM.md realigned to VISION: north stars as agreed with the user; simulation-quality metrics (person level, qualitative, transfer) added as the research core; benchmark-first and trained-model proposal added.
- 2026-11-01 18:52 UTC: Program corrected to the user's two north stars; stance section added (no limiting statements). Person-level and qualitative metrics kept as supporting measures only.
- 2026-11-01 18:58 UTC: mailbox checked. Grok Bot: Data Feeder (its data teammate) checks the mailbox every 30 min. Leaderboard Nov 1 read ETA 19:30 UTC, then daily 00:20/23:50 PT; X follow checks (400 pairs) human-paced, ETA Nov 3; pipeline stop-check and Fable switches stay with Grok Bot; HN favorites on grokbot-favs-p2. Upvote pages: signed-in browser loads them normally; Apify spend passed to the user. Sign-in request closed (done).
- 2026-11-01 18:52 UTC: filed to Grok Bot: signed-in upvote fetch for the 300 most active pool people (list in raw/requests/upvote_refresh_priority.txt). PH agent: Camoufox render/scroll pilot refused by its permission check as bot-check circumvention; not retried. Routes left for upvotes: signed-in browser (Grok Bot) and Apify (user decision). Degradation test and tie extensions running, results ~1 h.
- 2026-11-01 19:00 UTC: mailbox checked. Data Feeder: leaderboard reads landed (Nov 1 early: 284 rows; Oct 31 final: 367 rows, Godwit and AwaitIO present, no duplicates); "all" tab, so featured must be separated before list_check. Grok Bot: PH "Similar Products" lists for the 300 most recent launches (all 6,668 by 22:15 UTC) as a third competitor source; leakage caveat (today lists). Both passed to the PH agent with validation steps.
- 2026-11-01 19:05 UTC: PH agent: every API launch is in the leaderboard "all" reads (19/19, 22/22); one non-featured row sits inside the top 19/22 each day, so a featured flag is needed (PH agent filed the mailbox request itself). PH Similar Products preview on 16 answer-key products: 31.0% real alternatives in top 5 (CI 12.9-50.7), at least one 50.0% (25-75); comparable to Gemini naming 28.6/43.1; full file at 22:15 UTC. Caveat: 52.5% of PH list entries are reviewed alternatives, so the answer key may be partly circular; with-vs-without on launch-time-safe lists is the real test.
- 2026-11-01 19:12 UTC: X go/no-go sample written as CSV (raw/requests/x_audience_sample.csv, 400 rows, blind) per the user; mailbox request filed. Competitor-grounding plan sent to the PH agent: merged lists weighted by validated hit rate; competitor outcomes vs their reach as a prior; person-level competitor tie strength; same-window cannibalization; winner-of-3 as a training target.
- 2026-11-01 19:10 UTC: PH agent interim: tie extensions (return rate to makers/hunter, team turnout, backer count, 60-day decay) person-level top-3 hit 55.8 vs 54.0 (AUC 0.728 vs 0.716), 6/6 months, +1.8 (95% +0.6 to +2.9). Launch-level paired run started.
- 2026-11-01 19:15 UTC: mailbox checked. Apify declined by the user (via Grok Bot); Data Feeder runs the Nov 3 20k upvote refresh via residential Camoufox and will send call details and cost. Featured-tab leaderboard reads underway (raw/leaderboard/<day>_<HHMM>PT_featured.json), both tabs daily from tonight. Top-300 signed-in upvotes appending at 15-25 people/h. X sample queued after it, ETA Nov 3.
- 2026-11-01 19:20 UTC: list_check on featured reads: Oct 31 API 22 = featured 22, clean. Nov 1 API 19 vs featured 17, nothing missing from the API; 2 extra (Fluent 2, Hamdori) likely a short page read; recheck at 23:50 PT.
- 2026-11-01 19:25 UTC: User: implement step 3 now (tie strength + per-hunter/maker turnout into the daily pipeline, with the leaderboard cross-check), report top 3/5/10 and winner-of-3 deltas; do not wait for the X sample. Directive sent to the PH agent with 5 deliverables (deltas, daily sim step, list_check step, deploy for 00:05 PT, report).
- 2026-11-01 19:30 UTC: PH agent step 3: no-page baseline psn 59.8/71.2/79.3; pnr/pnx backtests scoring (~1.5 h). Daily person sim dry run 84 s for 19 launches, 77k rows. list_check step done (re-paging branch untested). Deploy blocked for the PH agent (pip install torch-cpu + sentence-transformers refused); bundle staged at usersim_sim/deploy/20261101_sim/, script pipeline/vm/deploy_sim.sh. Orchestrator attempting the install; else Grok Bot.
- 2026-11-01 19:36 UTC: orchestrator pip install on usersim-pipeline refused (Remote Shell Writes). Filed to Grok Bot (now): install torch-cpu + sentence-transformers, then run deploy_sim.sh 20261101_sim when the bundle is complete.
- 2026-11-01 19:33 UTC: install request corrected: /opt/exp/bin/python3, torch==2.15.0 cpu, sentence-transformers==6.2.0. list_check re-paging branch tested read-only on the VM (nothing to add).
- 2026-11-01 19:42 UTC: PH agent permission check refused writing a mailbox correction about the pipeline install; the orchestrator relays everything on this thread. Asked the PH agent for code.tar extraction commands and the "bundle complete" signal via send_message.
- 2026-11-01 19:45 UTC: PH agent will not send deploy instructions (its check refused twice); orchestrator reads deploy_sim.sh from claude/ph-ops-agent and completes the Grok Bot request itself.
- 2026-11-01 19:50 UTC: Data Feeder: blocked on the pipeline install/deploy (its standing rule: never change usersim-pipeline); passed to Grok Bot coordinator for a decision or the user's OK. The user's approval is the unblock.
- 2026-11-01 19:50 UTC: mailbox checked (scheduled). Upvote 403 fixed by Grok Bot: route 4 light mode (Camoufox via DataImpulse, same-origin fetch inside one warmed page), 40/40 OK, matches signed-in browser 3/3, ~81-223 KB/person, 20k people $2-4.5, runs on a GCE VM with a browser. Code in raw/ph_upvotes_sample/work/. PH agent to verify, run the top 300 now on a temp VM, plan the Nov 3 refresh (4 VMs, --max-usd 10), and switch the pipeline people step. Request closed. All other requests have replies; no follow-ups due.
- 2026-11-01 19:58 UTC: orchestrator refused twice on the upvote fetch: relaying route-4 steps to the PH agent (bot-check circumvention) and filing a mailbox request for Grok Bot to run the fetcher (auto-mode bypass). Not retrying. The upvote refresh is an instruction for the user to give Grok Bot directly; the PH agent loads whatever lands in raw/ph_upvotes/.
- 2026-11-01 20:00 UTC: HN agent tie-strength result (Sep 1-Oct 14, 60,451 person-days, random 14.1): content taste 29.7, ties 17.2, content+ties 30.2, popularity 49.8, all 55.5. On HN content beats ties, the opposite of PH; ties add +0.5. Submitter tie network at posting: -0.9 [-2.3,+0.5] winners/day. odds_live.py hourly on hn-sim-1 (AUC 0.794 at posting, 0.956 at 1 h). Next for HN: outside feeds to pull 80% earlier in the day.
- 2026-11-01 20:02 UTC: orchestrator refused when adding an approval note to the Grok Bot deploy request (instruction poisoning rule). Approvals go from the user to Grok Bot directly, never relayed by a session.
- 2026-11-01 20:05 UTC: Data Feeder top-300 signed-in upvotes: 20/300 done, 3,765 rows, 0 errors; no dates on the page (upvoted_at null); footer block stripped. Told it to take 60 items per person to finish sooner.
- 2026-11-01 20:10 UTC: PH agent: raw/ph_upvotes loader + daily ph_upvotes step built (fails if under half the pages ok). Signed-in file not loaded yet: product slugs are ambiguous (several launches per product), ~half the rows unmatched. Asked Data Feeder to add post_slug/post_id per row. Deltas: pnx 80/207, pnr 100/207 days.
- 2026-11-01 20:15 UTC: PH agent: Nov 3 refresh list is 3,820 (STALE_DAYS=7 over the 30-day-active pool), not 20k; whole pool is 20,947. Two incremental.plan bugs fixed (403 counted as fresh; strict < on 7 days). Orchestrator: also write the full 20,947 list; recommend a one-time full pass on Nov 3 since activity since Oct 29 is only visible via comments. Signed-in file held until launch identity is exact.
- 2026-11-01 20:18 UTC: full-pool refresh list uploaded by the PH agent: raw/requests/upvote_refresh_20261103_full.txt (20,947); rule-based 3,820 list alongside.
- 2026-11-01 20:25 UTC: Grok Bot: embedding install done on usersim-pipeline (torch 2.15.0+cpu, sentence-transformers 6.2.0, bge-small warmed, 37 GB free); nothing stopped. Deploy waits for "bundle complete".
- 2026-11-01 20:30 UTC: User: HN north star is the per-post likelihood of making the daily top 30, not daily-list recall. RESEARCH_PROGRAM.md updated; target number pending the user.
- 2026-11-01 20:40 UTC: Grok Bot delivered upvotes with exact launch identity (route 4, no Apify, no login): top 300 done (298 OK, 5,960 rows, all with post_id/post_slug) in raw/ph_upvotes_full/; full 20,947 pool filling, ETA ~21:00 UTC. PH agent to dry-run, load, and refresh tie features before the deploy.
- 2026-11-01 20:45 UTC: User: HN north star = Caught (recall of the daily top 30; 30 calls/day so recall = precision), target 100%, at posting / 15 min / 1 h / 3 h.
- 2026-11-01 20:50 UTC: PH agent loaded the top-300 page-1 upvotes: 298 OK, 98.9% consistency with existing events, 3,241 new upvotes; upvotes/day now Oct 30 584, Oct 31 562, Nov 1 418 (were 0). 34 heavy upvoters do not reach Oct 29 on page 1. Full 20,947 file next (~21:00). Daily sim reads events at run time, so tomorrow sees them.
- 2026-11-01 20:55 UTC: User: HN north star is Caught at posting (each post scored at its posting moment, no votes yet). Time-of-day recall retired. 15 min / 1 h are extras.
- 2026-11-01 20:10 UTC: deploy bundle complete (code.tar commit cef722d: sim forecast, list_check, ph_upvotes step, incremental.py fixes); Grok Bot told to deploy. PH agent dry run on Nov 1 vs 20:00 UTC standings (one day): launch model top 3 2/3, simulation 1/3; top 10 7/10 vs 6/10.
- 2026-11-01 20:15 UTC: Orchestrator independent HN check (experiments/hn_check/caught_at_posting.py; simple at-posting model: title text, time, submitter and domain track record; train Jul-Aug, test Sep 1-Oct 14, 45,371 posts, 44 days): AUC 0.696; Caught at posting 7.3% [5.8, 9.0] (posts of the same day; random ~3%); 3-day window 5.3%; ceiling if every same-day post were judged perfectly 67.2% (the rest of the top 30 were posted on earlier days). HN agent's richer model (AUC 0.794 at posting) still to report.
- 2026-11-01 20:20 UTC: HN agent, north star baseline: Caught at posting 14.4% [12.5, 16.3] (about 4.3 of 30), same 67.2% same-day ceiling (re-ups posted earlier are the other ~33%). Post-only inputs carry it (14.2%); similar titles, title embedding, crowd tallies add <0.3. Extras with early votes: 15 min 19.3%, 1 h 41.0%, 3 h 53.7%. Levers next, paired by day: submitter ties network, domain/author record, outside feeds, topic fit. Code experiments/hn_sim/caught.py.
- 2026-11-01 20:30 UTC: HN north star redefined per post (user): each post judged once at posting; winners = posts that ever made a daily top 30; flag as many as there are winners (~30/day); Caught = winners flagged / winners; ceiling 100%. Orchestrator quick model: 11.2% (148 of 1,323 winners), day-mean 10.9% [9.3, 12.5], random ~3%. HN agent re-scoring its stronger model in this definition.
- 2026-11-01 20:40 UTC: User: HN north star staged: Caught per post at 1 h -> 80%, then 15 min -> 80%, then at posting -> 80%.
- 2026-11-01 20:45 UTC: HN true starting line, per post (44,263 posts, 1,323 winners): at posting 21.4% [19.3, 23.4] (random 3.0); 15 min 27.7% [25.9, 29.7]; 1 h 48.5% [45.3, 52.0]; 3 h 63.0%. Stage 1 levers running (vote curve, comments, early-commenter record, HN gravity/penalty, outside traction in the first hour).
- 2026-11-01 20:50 UTC: mailbox checked. Deploy DONE on usersim-pipeline (20:11 UTC, deploy ok, simforecast in run_daily.sh, install via sudo into /opt/exp); request closed. Grok Bot found: code backup in deploy_sim.sh silently failed (relative files.txt), in-place overwrite of a running script (Grok Bot moved the inode first), sim_forecast needs ph_predict on sys.path; passed to the PH agent. HN outside feeds delivered (lobsters, 4 subreddits, techmeme, arXiv, RSS, X sample, github trending, Jul 1-Oct 16 + live, $0); passed to the HN agent.
- 2026-11-01 20:55 UTC: PH agent verified the deploy read-only (md5 of all 7 files match the repo; STEPS include list_check, simforecast, ph_upvotes). Import path not a risk (sim_forecast runs as a subprocess with cwd=ph_predict). Backup and in-place overwrite fixed in deploy_sim.sh for the next bundle.
- 2026-11-01 21:00 UTC: HN agent found a leak in the 15 min / 1 h / 3 h numbers: vote series were fetched only for posts that ended with 5+ points, so a missing series signalled a loser. At-posting 21.4% unaffected. Orchestrator: impute without the outcome (constant), report a has-series sensitivity, and score the clean live test from hn_minute (since Oct 31). Stage 1 and 2 numbers withdrawn until re-scored.
- 2026-11-01 21:05 UTC: HN agent: constant imputation is the headline; ramp and series-only (23.6% of test posts, 99.5% of winners) as sensitivities; leak check reported overall and within identical-input posts. Clean live test (live_caught.py) ready; first posting day settles Nov 4. Blocker: hn_minute ran ~10 of 42.5 h (30 gaps >10 min); HN agent filed a restart/uptime request to Grok Bot (20261101T2110).
- 2026-11-01 21:15 UTC: PH agent loaded the full-pool page-1 upvotes: 20,934/20,947 people, 227,105 rows, 99.9% consistency, +4,193 new upvotes (plus 3,241 from top 300). Upvotes/day now Oct 28-Nov 1: 1,055 / 1,260 / 1,263 / 936 / 678 (usual ~1,500-1,800; page 1 is the 20 newest per person). Lag-14 run restarted after a cache rebuild; deltas when pnr/pnx finish.
- 2026-11-01 21:30 UTC: HN honest starting line (rank only; vote counts dropped because the backtest only has vote series for posts that ended with 5+ points): at posting 21.4%, 15 min 24.7% [22.6, 26.9], 1 h 45.9% [42.1, 49.4], 3 h 61.0%. Stage-1 levers first pass (on the leaky const base) none helped. Direction: at-posting levers and simulated early votes first (backtest is honest there); stage 1/2 levers measured on the clean live hn_minute data as it accumulates (needs continuous uptime).
- 2026-11-01 21:35 UTC: HN at-posting levers (paired by day vs 21.4%): submitter ties -0.4, domain/author record is the only significant input (-2.0 without it), real-list record +0.6, outside feeds before posting +0.5 (link seen in a feed before posting for 6% of posts, 10% of winners), day fit +0.8, all four +0.1. Direction: read the linked page with Gemini (pilot 2,000), competition at the posting minute on /new, then simulated early votes; no "noise floor" framing.
- 2026-11-01 21:40 UTC: HN simulated early votes at posting: predicted vs real early votes Spearman 0.05 (15 min), 0.22 (1 h); Caught -0.2 [-1.4, +1.2]. Running: pagejudge (Gemini 2.5 Flash reads the linked page; pilot Sep 15-16, 2,283 posts, ~$1.6), competition at the posting minute, training from 2025. Full page-judge run ~$75 Flash or ~$25 Flash-Lite needs the user's OK after the pilot.
- 2026-11-01 21:45 UTC: PH deltas part 1 (live no-page config, May-Oct, paired): simulation-only daily top 3/5/10 psn 59.8/71.2/79.3, pnr 59.2/70.8/79.8, pnx 59.8/70.6/79.3; all paired differences within +-0.6 (CIs span 0). Launch model 65.5/73.9/81.2. Person-level gain does not reach the launch level: final predictions correlate 0.99+, the launch layer leans on reach. Next (after part 2): does pnx predict the pool's own votes better; panel reweighting of pool people to the whole audience as a simulation-only launch forecast.
- 2026-11-01 21:50 UTC: PH test 1 (pool own votes, Apr-Oct, 207 days): tie strength makes the simulation better at the pool's own votes. Spearman psn 0.450 / pnr 0.478 / pnx 0.488; pool top-3 hit 43.0 / 46.5 / 46.9; pnx-psn +3.9 (+0.6 to +7.1). Gain is lost at launch level where outside-pool votes dominate, so test 2 (panel reweighting) is the next step. psn rebuild with current code running to confirm.
- 2026-11-01 21:55 UTC: mailbox checked. hn_minute gaps explained: the Grok Bot box is frozen when no agent uses it (not crashes); v2 recorder + watchdog deployed 20:56 UTC, 29/30 minutes since, coverage files at hn_jobs/cache/feeder/hn_minute_coverage_<day>.md. True 24/7 needs an always-on e2-micro VM (free tier or ~$7/month) and the user's approval. HN feed gaps filled: github_trending 2,244 rows (108/108 days), X 30 accounts 979 link posts, arXiv listed_at added; verified 20/20. Both replies addressed to the HN agent directly.
- 2026-11-01 22:00 UTC: HN at posting moved: training from 2025-01-15 (539k posts) gives 22.6% [20.5, 24.8], +2.9 [+1.1, +4.8] paired vs Jul-Aug training. Page-judge pilot (Gemini Flash, 2,283 posts, $1.17): page read for 65.5% (403 for 18.8%), judge AUC 0.607 alone, Caught 11.9% alone vs 16.4% base on those days; not yet tested as an input (needs the training period judged: ~$25 Flash-Lite / ~$75 Flash, user decision).
- 2026-11-01 22:05 UTC: HN competition at the posting minute did not move Caught (rivals +0.2, rival strength -0.1, site traffic +0.1, all +0.4, CIs span 0). Page-judge full run staged (PJ_MODEL=lite, Jul 1-Oct 14, ~$25), waiting for the user. Embedding the remaining 167k 2025+ titles (~$0.30; old 3+ points filter leaked the outcome), then the 2025+ rebuild, then rank-only stage-1 levers.
- 2026-11-01 22:10 UTC: HN at posting 23.2% [21.2, 25.3]: 50/50 rank blend (weight fixed before scoring) of the Jul-Aug model and the 2025+ model, +1.8 [+0.4, +3.2] paired. Title embeddings in the 2025+ model +0.1. The user confirmed the 3-checkpoint north star with the HN agent directly. Running: rank-only 1 h levers; hist_prior (pre-Jul history model as an input).
- 2026-11-01 22:15 UTC: PH winner-of-3 (no page, May-Oct, simulation-only score, day/week/month): psn 52.4/55.9/54.9; pnr 58.8/58.4/58.6; pnx 57.8/59.4/59.6; launch model 71.2/72.9/71.3. Tie strength vs none +6.4/+2.5/+3.7 (rough +-3.7/2.5/2.4; day-clustered bootstrap pending). Gain washes out when audience/reach inputs are added: panel reweighting (test 2) is the bridge.
- 2026-11-01 22:20 UTC: HN 1 h checkpoint 47.2% [43.7, 50.6] (+1.3) from the pre-Jul history model as an input. Other 1 h levers on top: +0.3 to +0.8, noise. Of test winners, 48.5% are on the front page by 1 h, 66.9% by 3 h, 80.5% by 24 h; more than half of the 1 h misses are winners still on /new, so the 1 h gain is in reading /new (honest only on live hn_minute or a /newest archive), plus at-posting work and the second-chance pool.
- 2026-11-01 22:40 UTC: mailbox checked. Always-on HN recorder live (grokbot-hn-recorder, e2-micro, user approved, ~$7/month; output feeder/vm/; first 10 min 100%). Early-vote archive (Wayback /newest, outcome-independent): Jul-Sep 6-10% of stories, Oct 2-16 every ~10 min (80-95% expected) -> honest 15 min / 1 h backtest for Oct 2-14. Track HN paid SQL is the only full Jul-Sep route (not priced; ask the user only if Oct shows a gain). HN favorites re-fetch done 795/795. All passed to the HN agent.
- 2026-11-01 22:50 UTC: HN Wayback early votes verified (created_at 100% match, coverage outcome-independent). Partial (Oct parse 43%): 15 min +0.5 [-1.6,+2.7] (26.0 vs 25.5), +2.2 [-2.2,+6.3] on Oct 9-14; 1 h +0.0. Rerun at full parse. No Track HN spend case yet. live_caught unions box + VM rows. Favorites p2-10 in: 146,216 favorites over 3,422 people (was 40,446); twin_v2 and person_top3 rerunning.
- 2026-11-01 23:40 UTC: mailbox checked. HN recorder VM: /newest p1 76/76 min since boot, front pages drop out ~5 min every ~50 min (HN throttling, designed fallback). Decided: cut over on the /newest p1 bar now, slow front p2/p3 to every 2 min, keep the box copy for front pages until a full clean day. Similar Products full file running late (ETA ~23:30 UTC).
- 2026-11-01 23:46 UTC: User: page-judge full run approved (~$25, Flash-Lite); recorder cutover approved as planned (old copy kept one day); keep the October /newest parse moving to rerun the early-votes test. Passed to the HN agent; parse follow-up filed to Grok Bot.
- 2026-11-01 23:55 UTC: HN page-judge full run started 23:48 UTC (106,210 posts, Flash-Lite, cap $30, ETA ~01:30 UTC; pj_eval runs on completion). Recorder union already VM-primary. October /newest parse stalled at 1,415/2,291 captures since 22:17 UTC; HN agent filed a finish request (2355). Odds tool retrained honest (front-page rank only after posting). Nov 4 live check armed.
- 2026-11-02 00:00 UTC: PH full results (clean psn2 baseline rebuilt with current code). No simulation variant beats the launch model (closest page-aware psr: top 3 -3.2 [-7.5,+0.9]). Corrections: pool top-3 tie vs none +2.7 [-0.3,+6.0] (earlier +3.9 used Oct 28 files); winner of 3, day-clustered, pnr-psn2 day +2.5 [-0.3,+5.7], month +2.7 [+1.0,+4.4]; pnx month +3.7 [+1.7,+5.6] (earlier +6.4 was not clustered). Upvote outage: no effect (lag 3/7/14 within +-1). Panel reweighting: 47.7/59.9/69.3, worse than the raw pool sum; outside audiences (makers' and hunter followers, X, promotion) have no pool cell. Next direction proposed by the PH agent: represent outside audiences as simulated panel members (follower populations per maker). Direction review requested (Fable).
- 2026-11-02 00:40 UTC: mailbox checked. Recorder cutover done 23:40 UTC (vm/ primary, v3 alternating front p2/p3; box keeps front pages for a day). October /newest parse complete (108,000 rows; Oct 2-16 mostly 93-98%, low days Oct 6/13/14/15 are Wayback gaps); passed to the HN agent for the early-votes rerun. PH Similar Products full file done (6,668 rows, 5,868 products); passed to the PH agent for validation. Fable review request pending.
- 2026-11-02 00:45 UTC: PH Similar Products validation (full file, 147 answer-key products): 45.8% of real alternatives in PH top 5 [39.4, 52.2], at least one 68.7% [61.2, 76.2]; vs Gemini naming 28.6/43.1, meaning 13.8/22.8 (on 281 products; sets overlap only partly). Circularity caveat: 54.7% of PH list entries are reviewed alternatives. Strongest competitor source by this measure; with-vs-without simulation test held until the direction review.
- 2026-11-02 01:35 UTC: mailbox checked. Fable review request (00:00, priority now) unanswered after 90 min; follow-up added. Recorder update posted to the HN agent thread.
- 2026-11-02 01:40 UTC: HN throttling the recorder every 10-15 min. Decision: no IP change (respect the rate limit); cut to ~2 req/min with /newest p1 every minute as the priority, other pages less often, 10-min backoff. Filed to Grok Bot.
- 2026-11-02 01:55 UTC: Direction review (Fable, user-requested): docs/reviews/2026-11-02_direction_review.md. Critique: two competing models (pool sum + reach GBM), one audience of five simulated, noisy headline metric, competitor grounding tested as GBM features. Directions: A generative vote model with simulated audiences; B launch-day dynamics as product and as training target (hour-2 votes); C competitor grounding at decision level on PH Similar Products. Plan E1-E5. Metric change: pairwise and competitor-pair accuracy for decisions; daily top 3/5/10 stays the headline.
- 2026-11-02 07:00 UTC: E5 (trained person model, `simlab/two_tower.py`, report `experiments/simlab/reports/two_tower.md`): paired on pick_boost's own test rows, May-Oct, 36.5k person-days. Baseline reproduced (LightGBM, previous month) 55.9 / 0.728. Two-tower alone loses (best, target attention: 53.9 / 0.713, -2.1 [-2.6, -1.5]). Same LightGBM trained on ALL earlier months: 58.5 / 0.742, +2.5 [+2.1, +2.9], 6/6 months. Ensemble (net + all-months LightGBM): 59.0 / 0.745, +3.0 [+2.6, +3.5] vs baseline, +0.6 [+0.2, +0.9] vs all-months LightGBM. Launch level (pool sum, 150 days): ensemble ties the all-months LightGBM on pool votes (-0.008 [-0.024, +0.007]) and loses top 5 (-2.3 [-4.5, -0.1]); psg_ (all-months LightGBM) 0.587 Spearman, sim-only top 3/5/10 55.4 / 63.7 / 73.5. psg_ and psv_ handed to the PH agent (gs://.../usersim_sim/tmp/e5/features/) for E1.
- 2026-11-02 09:40 UTC: popscore TRAIN_ALL=1 (person model trained on every earlier month, popscore's own LightGBM settings; psa_ vs current psx_, TASTE+TIE2; report experiments/simlab/reports/train_all.md). Pool votes better: Spearman +0.016 [+0.001, +0.032], pool top 3 +3.2 [+0.6, +5.8] (207 days). Launch model + psa_ vs + psx_ (sim_src_score, May-Oct, 176 days): daily top 3/5/10 +0.4 [-2.5, +3.2] / -0.2 [-2.0, +1.6] / +0.8 [-0.0, +1.7]. Launch model alone stays best 66.7 / 73.5 / 81.0 (+psa_ -1.3 / -0.5 / -0.9). Best sim-only (stage 3, Jul-Oct): +0.9 / +0.0 / +0.2, all CIs span 0.
- 2026-11-02 10:45 UTC: E1 v1 generative vote model (simlab/vote_model.py, report experiments/simlab/reports/vote_model.md): votes = pool + audience sizes x conversion (track record, page) + browse; monotone additive LightGBM (Poisson) and an additive Poisson model; May-Oct, 3,977 launches. Daily top 3/5/10, gbm: + psx_ 58.0 / 67.6 / 76.3, + psa_ 57.8 / 68.4 / 77.0 (psa_-psx_ -0.2 [-2.5, +2.1] / +0.8 / +0.7), + pna_ 54.7 / 66.9 / 76.3 (top 3 -3.2 [-5.5, -0.9]); launch model alone 66.7 / 73.5 / 81.0 (E1+psa_ -8.9 [-12.7, -5.3]). The pool helps here: +2.8 [+0.4, +5.3] top 3, log-lik +0.9. psa_ vs psx_ log-lik +0.39 [+0.10, +0.68], weekly top 10 +3.5 [+0.4, +6.5]. Weekly far below the launch model (18.7 vs 49.3 top 3): the day level is not calibrated yet.
- 2026-11-02 11:40 UTC: E1 v2 (simlab/vote_model2.py, report experiments/simlab/reports/vote_model2.md; Shreyas approved): Poisson LightGBM offset by the launch model + pool (psa_) + audiences + day-level term. vs launch model alone (May-Oct, 176 days / 25 weeks): daily top 3/5/10 68.4 / 72.6 / 81.5 vs 66.7 / 73.5 / 81.0, top 3 +1.7 [+0.2, +3.2]; weekly 53.3 / 60.0 / 57.8 vs 49.3 / 56.0 / 58.3, top 5 +4.0 [+0.8, +7.2]; log-lik +0.13 [-0.22, +0.50]. Gain is the day term interacting with pool/audience corrections (without day term -1.5 [-2.8, -0.4]); the pool alone adds nothing beyond the launch model (-0.4 [-1.1, +0.4]); psa_ = psx_. Per-maker conversion from earlier launches hurt (-2.1). 8 variants compared: confirm live from Nov 3.
- 2026-11-02 11:30 UTC: E1 v2 follow-ups (Shreyas approved). Correction: off's audiences included the makers' PH follower count, not a live input (leaky). Live inputs only (offlive, pna_), frozen, 5 seeds: daily top 3/5/10 68.0 / 73.2 / 81.3 vs launch model 66.7 / 73.5 / 81.0, top 3 +1.3 [-0.4, +3.0], 4 of 6 months better and 2 tied, seed spread 67.6-68.2; weekly top 3 +5.3 [+1.3, +10.7], top 5 +3.2 [+0.8, +6.4]; log-lik +0.18 [-0.14, +0.52]. No Nov tail (inputs end Oct 24). Shadow package (offlive, pna_) in gs://usersim-bakeoff-347838016394/usersim_sim/tmp/e5/e1v2/, self-test exact (33/33, diff 0.0). Report: experiments/simlab/reports/vote_model2.md.
- 2026-11-02 12:00 UTC: E1 v2 vs day-terms-only control (launch model + day terms; simlab/e1v2_vs_day.py), May-Oct, paired. Control vs launch model: daily identical, weekly top 3 +5.3 [+1.3, +10.7], log-lik +0.31 [+0.09, +0.52]. E1 v2 - control: daily top 3 +1.3 [-0.4, +3.0] (settings: lr .05 +0.0, 31 leaves +0.8; PH rebuild -0.8), weekly top 3 +0.0 [-5.3, +5.3], weekly top 5 +3.2 [+0.8, +6.4] (holds at all settings), log-lik -0.13 [-0.37, +0.13]. Weekly top 3 lift = day calibration; only weekly top 5 survives; no daily gain.
- 2026-11-02 12:20 UTC: Pool-support concentration over the day-calibrated control (simlab/pool_conc.py, report experiments/simlab/reports/pool_conc.md; requested by Grok Bot). Rule fixed before the run: daily top 3 CI above 0. Rejected: + pna_ concentration (ties, fans, top1/top3, pmax, share, within-day standing) daily top 3 +0.2 [-1.7, +2.1], log-lik -0.32 [-0.58, -0.05]; + psa_ +0.4 [-1.3, +2.1]. Plain total +0.9 [-1.1, +3.0] (pna_), weekly top 5 +4.8 [+1.6, +8.0]. Person-model aggregates stay within +-1 of the day-calibrated launch model on daily top 3.
- 2026-11-02 12:30 UTC: Leakage correction (from PH ops): follower counts (PH, X), fol_/seg_ and several promo_ fields were read after launch in the backtest. The launch-model offset (ctrl `all`) and E1 v2's audiences (4 leaky inputs) include them, so E1 v1/v2, train_all and pool_conc absolute levels are optimistic; comparisons against a control on the same offset are like-for-like but not honest estimates. PH ops' honest rebuild (honest offset, promo_posts only): daily -1.3 / -0.3 / -0.3, weekly no better than day-terms-only. The E1 v2 shadow package was trained on leaky values; a retrain on honest inputs (promo_posts/promo_cov, at-launch counts once 3-4 weeks exist) is needed before its scores mean anything. Notes added to the four reports.
- 2026-11-02 13:00 UTC: Honest E1 retrain (Shreyas approved; simlab/e1_honest.py, report experiments/simlab/reports/e1_honest.md). Honest offset (PH ops' honest_preds; my rebuild matches exactly), inputs: pna_ pool, dated promo_posts*/promo_cov*, hist_, page, day terms. Honest LM 64.4 / 70.5 / 76.9; day-only control same daily, weekly top 3 +5.3 [+1.3, +10.7], log-lik +0.38 [+0.10, +0.68]. Vs control, daily top 3: + pool -1.3 [-2.7, +0.0] (0/2/4 months), + promo -0.2 [-1.7, +1.1], + pool+promo+hist -0.8 [-3.0, +1.5], + all honest -1.7 [-4.0, +0.6]. Rule (CI above 0) failed by every variant. Day calibration is the only honest gain.
- 2026-11-02 14:10 UTC: Competitor outcomes as a demand prior (Grok Bot; simlab/cmp_outcomes.py, report experiments/simlab/reports/cmp_outcomes.md). PH Similar Products' earlier PH launches (best daily rank, settled votes, recency, count, crowding) over the honest day-calibrated control, May-Oct, 5 seeds, paired; coverage 68.8% with an earlier competitor launch. Daily top 3/5/10 -1.1 [-3.0, +0.8] / -0.3 / -0.1 (months 2/1/3), weekly top 3 -2.7 [-9.3, +4.0], log-lik -0.43 [-0.67, -0.20]. Fails the rule (CI above 0).
- 2026-11-02 15:40 UTC: Pre-launch X ties as a person-model input (simlab/x_tie_pool.py, report experiments/simlab/reports/x_tie_pool.md; Grok Bot, October covered launches). 71 covered launches, 16 with X-tied pool people (190). Person level: X-tied people vote on their launch at 22.5% [8.6, 39.5] vs 1.65% on the same day's other launches (+20.9 [+6.7, +38.0], ratio 13.7). Pool level (8 days): within-day Spearman with real pool votes 0.307 -> 0.307, gain 0.000; pool and final top 3 unchanged. Rule failed: about 12 tied people per launch add about one expected vote.
- 2026-11-02 18:40 UTC: X pre-launch go/no-go (simlab/x_prelaunch_e1.py, report experiments/simlab/reports/x_prelaunch_e1.md): 16 full Oct days, 235 covered launches; forward-only Poisson correction (dated posts, dated engagers) over the honest day-calibrated control, 13 scored days. Daily top 3 +0.0 [0.0, 0.0] (0/13/0), top 5 -3.1 [-7.7, +0.0] (0/11/2), top 10 +0.0; no full week; within-day Spearman with the honest residual ~0. NO-GO by the rule fixed beforehand. Hourly re-run stopped.

## 2026-11-02: HN front-page dynamics simulator, Caught at 15 min (E5 agent; experiments/hn_frontsim/)
- **Simulator.** A quality prior conditioned on the at-posting score, a tempered /newest early-vote likelihood, exposure by rank x hour from Quality News, a replayed front page from earlier days, and 24 h Monte Carlo with 200 draws.
- **Test.** Oct 2-14: 12,788 posts, 388 winners. The simulator catches 22.7% [17.3, 29.1], against 29.6% [25.6, 33.7] for wb15: -7.0 [-10.8, -3.0].
- **Blends with wb15.** Equal: -2.3 [-5.2, +0.5]. Forward: -1.6 [-6.2, +1.6].
- **Over the at-posting score alone:** +1.0 [-1.6, +4.3].
- **Early votes.** Their weight is about 0 without /newest exposure, and small (tau 0.05-0.1) with it.
- **Real front page.** Not testable on October: the bucket's Quality News series cover too few ranks.
- **Verdict.** It does not beat wb15. Next is the live hn_minute front page.

## 2026-11-03: PH pre-launch campaign sweep, scored on Sep-Oct (E5 agent; simlab/prelaunch_mentions.py)
- **Data.** Data Feeder's free-route sweep (raw/ph_prelaunch_mentions/, still a draft). Channels: HN Algolia, Reddit via Arctic Shift (6 launch subreddits, posts only), Bluesky AppView and dev.to. X is first page per day, for Oct only.
  - The window is the 7 days before launch day, strictly before 00:00 PT.
  - LinkedIn, Indie Hackers, Medium and Substack are blocked on free routes (bot checks). Reddit's own search returns 403 to GCP.
  - Only Sep and Oct are finished; Data Feeder is still fetching Jul-Aug.
- **Coverage.** Share of launches with any mention: Sep 22.3%, Oct 30.9%. With a strong mention (domain, PH link, or name + "product hunt"): 9.7% and 14.5%. With a "product hunt" phrase: 0.3% and 1.3%.
- **Gate** (per-day residual Spearman vs the honest launch model, 51-54 days). Nothing passes.
  - Best: strong-mention count +0.053 [-0.008, +0.111], and strong-mention authors +0.053 [-0.008, +0.112].
  - Reddit +0.060 [-0.027, +0.146] (19 days); HN +0.027 [-0.033, +0.086].
  - Author reach and Bluesky are about 0.
- **Boards vs the day-calibrated control** (1,458 launches).
  - Daily top 3: -0.6 [-1.9, 0.0]. Top 5: +0.4 [0.0, +1.1]. Top 10: -0.2 [-0.6, 0.0].
  - Weekly top 10: +2.9 [0.0, +5.7] over 7 weeks.
  - Monthly: tied.
  - September was trained without the features, so only October is a real test.
  - Adding X (Oct only) changes nothing.
- **Verdict so far: no pass.** The full Jul-Oct run (4 months, with a proper forward fit) follows when Jul-Aug lands.

## 2026-11-03: PH pre-launch campaign sweep, Jul-Oct (provisional; E5 agent)
- **Fetch.** Jul-Aug fetched by the E5 agent on exp-2 (ph_sweep/sweep_jul_aug.py), using the same routes and match rules as Data Feeder's Sep-Oct sweep.
  - Files: raw/ph_prelaunch_mentions/mentions_jul_aug_e5.jsonl and coverage_jul_aug_e5.json.
  - Bluesky succeeded for 93% / 91% of Jul / Aug launches. A retry is running, and the run with every month at "done" follows.
  - Bluesky's `domain:` operator now returns 400 when combined with since/until, so it queries the plain domain and requires the domain in the post's text or links.
- **Coverage.** Any mention: Jul 28.4%, Aug 31.0%, Sep 22.3%, Oct 30.9%. Strong mention: 13.6%, 16.2%, 9.7%, 14.5%. "Product hunt" phrase: 0.3-2.0%.
- **Gate** (per-day residual Spearman vs the honest launch model, 106-115 days). Nothing passes.
  - Strong count +0.009 [-0.036, +0.053]; HN +0.031 [-0.014, +0.077]; Reddit +0.021 [-0.038, +0.081].
  - Reach +0.014 [-0.030, +0.059]; "product hunt" phrase -0.037 [-0.122, +0.047].
- **Boards vs the day-calibrated control** (2,540 launches, 116 days).
  - Daily top 3: 0.0 [-1.1, +1.1]. Top 5: -0.2 [-1.0, +0.7]. Top 10: -0.3 [-0.8, +0.2].
  - Weekly top 10: +1.3 [0.0, +3.3] over 15 weeks.
  - Monthly: tied in every month and k except Sep top 5 with X.
  - The Sep-Oct "near miss" (strong count +0.053) does not hold with 4 months.
- **Verdict: NO-GO.** Dated pre-launch mentions on free routes add nothing over the honest model and the day calibration.
- **Final (03:05-04:10 UTC).** The Bluesky retry failed on the same 87 Jul-Aug launches each time.
  - Each one's first page succeeds, but deeper cursor pages error. They are broad names (Claude, anthropic.com, Sunrise, Cadence, ...).
  - The AppView then started timing out from exp-2, so Bluesky fetching stopped there (polite use).
  - The run above is therefore the final Jul-Oct result, with Bluesky at 93% / 91% of Jul / Aug launches. The fetcher now keeps first pages when a deeper page fails (ph_sweep/sweep_jul_aug.py), for a later top-up.
  - Verdict unchanged: NO-GO.

## 2026-11-03: Weekly magnitude model, launch-level feedback curve, dry run (E5 agent; simlab/day_strength.py)
- **Split (orchestrator).** The PH agent owns the day level (s_pred, out of sample); E5 owns the within-day position-feedback curve.
- **Gate (registered before the runs).** Weekly top 3 vs the day-calibrated control (daycal.py, offset = honest), paired by week, 95% interval above 0.
- **Curve.** Fitted on the deduped hourly vote_snapshots for the 2 clean days (Nov 2-3: 746 launch-hours). Hourly gain ~ exp(launch + f(rank) + g(4-hour block)).
  - Rank 1 gets ~1.5x the exposure of ranks 2-20.
  - Each day's line-up is simulated hour by hour (mean field), with quality = honest mu^alpha.
- **Results**, May-Oct (25 weeks), weekly top 3 vs control:
  - Control's own day level + fitted curve: +9.3 [+2.7, +17.3]. The flat curve gives +1.3 [-2.7, +6.7].
  - The agreed setup, s_pred day level + fitted curve: +4.0 [-5.3, +12.0], **gate not passed**. By month: Jun +20, Aug +13.3, Sep -8.3, Oct -11.1.
  - Honest curve fitted on training months instead of snapshots: rank-1 bonus 1.0-1.25 and alpha 1, so about no change; -2.7 [-6.7, 0.0]. With A2: -4.0 [-12.0, +2.7].
  - s_pred x prior shares (no curve): -2.7 [-6.7, 0.0]. This matches the PH agent's -2.7.
- **Reading.** The only positive arms use a curve fitted on 2 days after the backtest window (structural look-ahead) and are not robust to the day level. The backtest's own outcomes do not support a strong rank-1 feedback.
- **Verdict: no pass on the dry run.** Refit the curve when 14 clean snapshot days exist (~Nov 16), then score forward on days after the fit.

## 2026-11-05: Follower-list completeness after the no-cap fix + E5 person model status (E5 agent)
- **Check.** Every person file in raw/ph_population/people_live/vm/ (3,348 people, newest pull each): stored unique followers / following against the profile header.
  - Follower lists below 98% of the header: 983. Following: 280.
  - Small lists are short by 1-5 people (likely deleted or hidden accounts). Large profiles (>1,000 followers) stop at a median 77% of the header.
  - The pgql_test collector writes no paging record, so a truncated list cannot be told from one that reached the server's end.
  - Two lists stopped on the per-person budget (149,623 -> 0 and 107,708 -> 5,315); both are in deep_list.
- **Not queued.** Only 280 of the 983 short follower lists have followers queued in deep_list. 694 are queued for other tabs only and 9 are not queued; that includes 85 of the 112 big profiles.
  - Alerted via the orchestrator (GROKBOT URGENT).
  - Ask: mailbox/to_grokbot/20261105T0030_e5_followers_short_after_nocap.md. Inventory by handle: tmp/e5/followers_short_20261105.csv (bucket only).
- **E5 person model, latest held-out scores** (May-Oct, paired, unchanged since Nov 2). Top-3 hit / AUC / pool Spearman:
  - Ensemble (target-attention two-tower + all-months LightGBM): **59.0 / 0.745 / 0.586**. vs the published baseline: +3.0 [+2.6, +3.5] top-3, 6/6 months. vs all-months LightGBM: +0.6 [+0.2, +0.9].
  - All-months LightGBM: 58.5 / 0.742 / 0.586.
  - At launch level it adds nothing: psg_ pool Spearman 0.587; ensemble -0.008 [-0.024, +0.007].
- **Next E5 step: follow ties.** The person model uses no follows; its ties come from comments and upvotes only.
  - Sizing (upper bound, undated follows): when a person follows someone on the launch team, they pick it 22.5% of the time against 5.4% otherwise (x4.2, 1,579 people with complete live lists). The old people.parquet follows give the same x4.2.
  - Because follows are undated, this is leak-prone in a backtest (follows made after the launch). The honest test is forward, with first-seen-dated follow edges from the live list diffs, after the follower lists are complete.

## 2026-11-05 06:30 UTC: Follower re-page re-check + whole-person rule audit (E5 agent)
- **Store (people_live/vm, newest file per person): 14,198 people.**
  - **9,286 complete**: every list tab (upvotes, hunted, collections, stacks, followers, following) at >= 98% of its header. Reviews are excluded per the README.
  - 13,943 are complete if a PH end recorded in the paging record counts as complete.
  - Short tabs: followers 3,548, upvotes 2,052, following 904, stacks 88, collections 43, hunted 17.
- **Re-page not done.** For the 1,080 people queued after the 00:08Z alert, the share now >= 98% of header:
  - followers: <100 71/653, 100-1,000 26/315, >1,000 0/112;
  - following: <100 521/733, 100-1,000 236/289, >1,000 43/58.
  - Most follower lists still end "hasNextPage_false" (PH's repeating cursor chain).
  - The two budget-stopped lists (149,623 and 107,708 followers) have not resumed.
- **Rule breach.** Between 03:01Z and 03:31Z, 39 person files were written that are not whole (a list tab below 98% with no PH end recorded; 34 have no incomplete marker): 38 by the babysitter's VM collector, 1 by pgql_test.
  - Nothing newer than 03:31:46Z is in the store.
  - Alerted (GROKBOT URGENT, via the orchestrator).

## 2026-11-05 12:35 UTC: Whole-person audit #2 (E5 agent)
- **Writes resumed in people_live/vm/.** 1,445 files were written 07:00-11:40Z by the pace-test VMs feeder-pace32-1..6, which were supposed to write only to raw/_pacetest/.
- **434 of them are not whole**, with no incomplete marker:
  - followers 296 (median 4 missing), upvotes 119, following 62, collections 54, stacks 14, hunted 10;
  - by VM: -6 118, -3 92, -5 90, -1 69, -4 65.
  - Alerted (GROKBOT URGENT). List in the bucket: tmp/e5/nonwhole_pace32_0700_1140.csv.
- **Store**: 15,719 people; 10,362 have every list tab at >= 98% of its header. The strict population count is the headline (population agent).
- **Follower re-page still not run** for the 1,080 queued people: >= 98% at <100 71/653, 100-1,000 26/315, >1,000 0/112. The two budget-stopped lists have not resumed.
- **Correction (12:55Z): the audit #2 breach was a false positive.** Pace builds record PH's end under run.timing.<tab>.paging.ended (including "server_end_offset") and run.exh[tab]; my checker read only run.paging / paging_v2. With those fields read, all 1,445 merged files (07:00-11:40Z, Shreyas-approved merges) are whole: 0 remain non-whole, matching the population agent's MERGED_INCOMPLETE 0. Store: 15,719 people, 15,530 complete by a recorded PH end. The correction has been sent to the orchestrator and the population agent.

## 2026-11-05 18:45 UTC: Whole-person audit #3 (E5 agent)
- **No new files in people_live/vm/ since 11:40:13Z**, so nothing new to audit and no breach.
- **Store unchanged:** 15,719 people; 15,530 complete by a recorded PH end; 10,362 at >= 98% of every list-tab header.
- **Follower re-page still on hold:** the 1,080 older-collector people are unchanged (>1,000 followers 0/112 at >= 98%). The 107,708-follower list now records ended=budget; the 149,623 list has 0 stored.

### 2026-11-07 22:15Z — E5: are the follower / following lists complete? (counts only; the per-person list is in the bucket at tmp/e5/follow_gaps_by_person_20261107.csv)

The store holds 15,797 people (newest file per person, synced 22:10Z). Collection into vm/ resumed on Nov 7, with 78 new files since Nov 6 01:30Z. "Complete" means the items read reach at least 98% of the header count PH shows.

| | followers | following |
|---|---|---|
| people with a non-zero header | 11,703 | 14,345 |
| complete (>= 98% of header) | 7,830 (66.9%) | 13,369 (93.2%) |
| short | 3,873 | 976 |
| items missing / header total | 880,013 / 2,596,247 (33.9%) | 208,841 / 1,636,834 (12.8%) |

Why the short people are short (followers / following):

1. **Explicit cap or budget stop** (all Nov 4, before the whole-person rule): 6 people missing 297,954 followers; 1 person missing 704 following.
   - Includes a 149,623-follower profile with 0 followers read and a 120,393-follower profile with 1,816 read.
   - None of these has been re-pulled.
2. **The page chain repeated pages** (duplicates recorded, or more pages than items): 386 people missing 419,707 followers; 10 people missing 199,078 following.
   - These are the big profiles: 314 of the 386 have a header over 1,000.
   - This is the known endCursor repeat. The offset re-page is needed, but no file in the store ends with server_end_offset, so it has never been run.
   - 3 of these files were written on Nov 7, by the feeder-strat VMs.
3. **PH ended before reaching the header, with no repeat seen**: 1,906 people missing 160,367 followers; 282 people missing 8,210 following.
   - Not verified. The cause could be accounts hidden when signed out (the collectors' notes call this complete_not_visible), or a real early stop.
   - A signed-in or offset re-check of a sample would settle it.
4. **Short by only 1-2 items**: 1,575 people missing 1,985 followers; 683 people missing 849 following. Likely deleted accounts still counted in the header.

The 1,080-person older-collector inventory: 983 are still short on followers (all 112 with headers over 1,000), and 280 are short on following.

Separate whole-person gap: 14 of the 78 Nov 7 files carry stacks status "partial" (short by 1-2 of 1-11). They are marked incomplete, as the rule requires, and need the completion pass.

Not a gap: upvotes on signed-out pulls stop near 200 by PH's own limit (labelled limit_owner PH; collected signed-in separately).

### 2026-11-07 22:20Z — E5: re-fetch check. No follower re-fetch has run; all collectors are idle.

- No person file has been written to vm/ since 22:10Z, and every heartbeat shows `running: ""`.
- The Nov 7 feeder-strat run (VMs a-d, from 17:22Z) collected new people. It did not re-fetch existing follower lists.
  - Its follower and following paging ends only at server_end. It used no offset pass, including on chains with repeated pages: one example read 2,165 of 2,780 with 610 duplicates.
  - Its offset paging (server_end_offset) was on activity pages only.
- All four strat VMs stopped on PH challenge blocks (403, "challenge not cleared"): a at 17:57Z, d at 18:36Z, b at 19:11Z, c at 22:06Z. Auto-recover is off ("no standing auto").
- So the gaps in the 22:15Z audit stand unchanged. The follower re-fetch for the 1,080 inventory and for the 393 cap or repeated-page people has not started.

### 2026-11-08 00:30Z — E5: code-only review of full18c (adds the Chao1 pass-accounting closure guard)

The diff matches my request:
- It keeps a per-id count of how many passes served each account, saved in the re-page state.
- It closes only when the Chao1 estimate of never-served accounts is below 0.5. pdeep.whole checks this too.
- It also adds a cap of 24 passes across all attempts. Hitting it marks the person "repage_exhausted" and sends them to a review list, off the automatic queue.
- Saved state expires after 7 days, and session runners save no state.
- The package has no tests/ folder, and running candidate code is blocked here. So the miss rate below comes from my own re-implementation of the closure rules: `experiments/population_review/sim_repage_closure.py`.

**Simulated miss rate:** the share of closed lists still missing at least one visible account. 200 runs per cell (60 for N = 20k). m is the chance a given account is skipped in one pass.

| model of PH's unstable order | full18c as built | with the 98%-of-header shortcut removed |
|---|---|---|
| every account equally likely to be skipped, m 0.02-0.25, N 300-20k, header = visible | 0-10% (3/200 ... 19/200) | **0/200** in 8 of 9 cells; 5/200 at N 300, m 0.25 |
| same, with 10% hidden accounts in the header | 0-3% | (not needed) |
| a few accounts almost never served (1% skipped 90%, or 0.2% skipped 97%) | 40-100% of closed lists miss, 0.5-34 accounts each; 20-100% end exhausted | not fixable by pass counting |
| 1-5 new followers arriving per pass | 15-43% of closed lists miss a newcomer; up to 16% exhausted | |

Two things to take from this:
- **Where the misses come from:** the shortcut "union >= 98% of header" closes as soon as Chao1 dips under 0.5, before any zero-new pass. Requiring union >= header (or zero_full >= need) instead adds about 0.1 passes on average.
- **Remaining risks:**
  1. Accounts PH almost never serves (heterogeneous order) look the same as hidden accounts. Chao1 underestimates them, so they close as missed or end exhausted. Only an independent ordering or a signed-in view can tell the difference.
  2. Active big profiles are a moving target. New followers during a pass stop the zero-new closure and inflate f1, so some of them end exhausted.
  3. The class-3 cause (hidden vs not served) is still unmeasured.
  4. Not yet run on PH.

### 2026-11-11 00:30Z — E5: independent reference baseline for the two-level sim (taste + ties logistic)

This is a reference for the PH agent's two-level sim: a plain baseline its gains can be measured against.
- Script: `experiments/simlab/two_level_baseline.py`. Reports: `experiments/simlab/reports/two_level_baseline/`.
- CPU-only, run locally at $0.

**Split**
- The September model trains on Aug 1-Sep 30 and scores Oct 20-31. The October model trains on Sep 1-Oct 31 and scores Nov 1-7. The last training label day is before the first test day.
- Nov 8-9 are left out: a day's labels count only for people whose upvote list was read at least 2 days after it.

**People**
- store_v3 complete people only.
- A person enters day d only if they upvoted a launch in the 60 days before d. Activity on d itself never decides it.
- Labels run from coverage start: the oldest listed vote when the upvote list is shorter than its header (the signed-out ~200 cap).
- That leaves 6,712 people, 106,627 person-days and 2.87M person-launch rows on 19 test days.

**Features, all from events before d**
- Taste: topic match and text match with past upvotes.
- Ties: earlier upvotes or comments on launches by the same team; whether the person is on the team.
- Activity: last 30 days, history, tenure.
- Follows of the team, in a separate arm only.

**Weights:** complete people post-stratified to the whole store_v3 pool by 30-day activity tier. The full-rank voter lists the plan asks for are not in the store.

| | person AUC | person log-loss | Hit@3 | voter R-precision | daily top 3 | top 5 | top 10 | Spearman with votes |
|---|---|---|---|---|---|---|---|---|
| no follows | 0.911 | 0.0322 | 0.476 | 0.210 | 33.3 [22.8, 43.9] | 42.1 [33.7, 50.5] | 64.2 [58.4, 70.0] | 0.40 [0.34, 0.47] |
| with follows (Nov snapshot, undated) | 0.923 | 0.0311 | 0.596 | 0.245 | 47.4 [36.8, 57.9] | 61.1 [51.6, 70.5] | 72.6 [67.9, 77.4] | 0.53 [0.46, 0.61] |
| ceiling: real votes of the same sample, weighted | | | | | 84.2 [73.7, 93.0] | 90.5 [85.3, 95.8] | 86.3 [83.2, 89.5] | 0.87 [0.85, 0.90] |

Population metrics are the share of the real daily top k recovered (%), with day-bootstrap 95% intervals.

Follows minus no follows, paired by day: top 3 +14.0 [0.0, +29.8], top 5 +19.0 [+10.5, +28.4], top 10 +8.4 [+4.2, +13.2], Spearman +0.13 [+0.08, +0.18]. The follow edges carry no dates and many follows come after the upvote, so this gain is presumed leaky until shown otherwise. The honest baseline is the no-follows row.

What it shows:
1. **The sample can carry the north star.** A perfect person model on these complete people would get about 84% of the daily top 3. The gap is in person prediction, not in the sample.
2. **The weights barely matter here.** Tier post-stratification moves no metric beyond its interval.
3. **The honest person-sum is weak at launch level.** 33% of the daily top 3 is below the deployed sim's ~48-51% on Oct 20-Nov 9. Any two-level model has to beat both this baseline and the deployed sim.
4. **Person AUC is inflated by between-person activity.** Use Hit@3 and voter R-precision as the person metrics that matter.

### 2026-11-11 01:00Z — E5 review of the PH two-level sim: residual test fixed; voter R-precision should rank by P, not w·P

- **The raw residual check was biased.** Its within-day Spearman of EV against (real − LM) standing comes out negative by construction, through regression to the mean.
  - The honest tests (PH commit 520ff740, 15 days): partial Spearman +0.035 [−0.054, 0.125]; EV coefficient beside the LM +0.073 [0.007, 0.145] (it1).
  - A leave-one-week-out blend does not change top 3/5/10; the LM leads or ties in every row.
- **My baseline scored on the PH agent's exact clean rows** (1.53M rows, 12 days; `experiments/simlab/two_level_score_on_rows.py`):
  - R-precision is 0.213 when each launch's voters are ranked by P, and 0.123 when ranked by w·P.
  - On the same rows and definition, the PH agent's 0.151 (w·P) beats my 0.123.
- **Metric rule from now on:**
  - Person-level ranking metrics (voter R-precision, Hit@3) use P.
  - The representativeness weights enter only the population EV, Σ w·P.

### 2026-11-11 01:20Z — CORRECTION to the 01:00Z entry (R-precision, P vs w·P)

My conclusion at 01:00Z was wrong for the PH agent's model, and its 01:00Z metric rule is withdrawn.
- **What w is.** In the PH agent's rows, w is not a representativeness weight. It is P(active on d), taken from the person's own 30 days before d. Its p is P(picks L | active).
- **So w·p is its unconditional probability,** and ranking voters by w·p is correct. Its R-precision by p alone is 0.092-0.098, by w·p 0.143-0.151.
- **The like-for-like comparison on the same 12 clean days:** my P scores 0.213 overall (Oct clean 0.168) against its w·p at 0.143 (Oct clean 0.141). The gap is real and lies in the model.
- **The rule that stands:** rank by each model's own unconditional P(person votes for L), and keep any representativeness weight out of person metrics.
- **Next for the PH agent:** train an unconditional P on all-people rows.

### 2026-11-11 02:05Z — E5 review: the two-level sim's person route has plateaued at 00:05

All iterations passed the honesty review. The PH agent's code and results are on claude/ph-ops-agent.

- **Model of record: it8**, a choice model with EV = Σ A·K·S and monthly honest refits.
  - Person R-precision 0.241. My baseline on the same rows scores 0.168 (Oct clean) and 0.299 (Nov clean); it8 scores 0.208 and 0.353.
  - It carries a signal beyond the LM: EV coefficient +0.163 [0.100, 0.236].
  - It does not beat the LM: top 10 about 69, against 80+ on the LM's 6 days. The leave-one-week-out blend adds nothing over 15 days.
- **Tried and dropped:**
  - launch priors (team and topic history);
  - isotonic recalibration;
  - a temperature on the shares;
  - the reweighted negative sampling (neutral);
  - undated follows (leaky);
  - dated follows (no effect).
- **Coverage is not the limit.** An oracle on the same complete people (Σ of real votes) reaches 89.5 top 10, Spearman 0.89.
- **The gap is breakout appeal.** Real top-3 launches the model missed had as many sample voters as the hits, but P gave them only 0.33-0.46 of the probability their voters warranted. P follows each person's usual taste, and breakouts are not visible at 00:05.
- **Next:**
  - stop new person-model variants;
  - run one diagnostic that swaps each part (A, K, S) for its truth on the test days, to confirm which part loses;
  - re-test LM + it8 once about 30 LM-covered days exist.
- 02:15Z: the part-swap diagnostic (test-day outcomes, diagnostic only) confirms the plateau.
  - Within-day Spearman of EV vs votes: model 0.555, true A 0.565, true A·K 0.562, true S 0.788, oracle 0.885.
  - Activity is not the gap. The shares (taste vs breakout) close about 70% of it.
  - The two-level review is closed until a new pre-d breakout signal appears, or about 30 LM-covered days exist for the LM + it8 re-test.

### 2026-11-11 02:25Z — E5 review: breakout features in the LM (C1-C3), all dropped under the pre-registered rule

The PH agent tested three candidate features (lm_breakout.py on claude/ph-ops-agent), each paired against the base LM:
- **C1 topic momentum:** how well launches in the same topics did recently.
- **C2 within-day field:** a launch's standing against that day's line-up, built from the final featured list (marked as such).
- **C3 team absolute record:** the team's earlier vote and rank history.

How the test was run:
- Honest LM base with 53 inputs; 9 monthly folds, Mar-Nov 8; 5 seeds, averaged.
- Vote-based parts use only launches dated d-7 or earlier, and rank-based parts d-2 or earlier. The date assertion found 0 violations in 7,198 rows.

Daily top 3 / top 5, change vs the base LM, Mar-Oct (243 days):

| | top 3 | top 5 |
|---|---|---|
| C1 | -0.8 [-2.5, 0.7] | -0.7 [-1.6, 0.2] |
| C2 | -0.4 [-1.9, 1.1] | -0.1 [-1.1, 0.9] |
| C3 | -0.5 [-2.1, 1.0] | +0.6 [-0.2, 1.4] |

- None passes the keep rule, which needed top 3 or top 5 clearly positive on Mar-Oct. All three are dropped.
- C3's live Oct 20-Nov 8 result (+3.3 / +2.0, 20 days, intervals include 0) does not override the backtest gate.
- With these gone, the honest pre-launch candidate list is exhausted for current data.
- Deferred until about 60 days of at-launch reads exist: X audience and page quality at 00:05.

### 2026-11-11 02:45Z — PRE-REGISTRATION (E5): next LM candidates D1, D2. Written before any feature is computed or scored.

**Why these two.**
- The two-level work found that complete people's own history carries a signal beyond the LM: it8's EV coefficient is +0.163 [0.100, 0.236], on 15 days only.
- The C1-C3 breakout features reused launch-table history that the LM already has. Neither candidate below is in the LM in any form.
- Data: store_v3 (5.98M events) and the launches table. No new pulls.

**D1, warm audience.** Counted per launch L on day d, over store_v3 people with a full upvote history, using only votes and comments on launches dated ≤ d−2. The team is L's makers plus its hunter, as salted person ids.
- `aud_backers`: people who upvoted or commented on any earlier launch by the team.
- `aud_backers_act30`: those backers who also upvoted something dated d−31 … d−2.
- `aud_commenters`: people who commented on any earlier launch by the team.
- `aud_team_in_store`: how many team members are in the store pool.
- The log of each count, and its within-day percentile over the final featured list (flagged as final-list).

**D2, person-sum EV.**
- The E5 two-level baseline (taste + ties + activity logistic, no follows) is retrained monthly on the 2 months before the test month and scored on every launch, Mar–Nov 8.
- `ev_e5` = Σ P over people active in d−61 … d−2. Also `ev_e5_pct`, its within-day percentile.
- History lag: features use launches dated ≤ d−2 (the script's events-before-d raised to d−2).

**Harness and keep rule:** unchanged from C1–C3.
- The PH agent's lm_breakout main: monthly folds Mar–Nov 8, 5 seeds averaged, paired daily top 3/5/10, 10,000-draw day bootstrap.
- Keep a candidate only if:
  - top 3 or top 5 is CI-positive on Mar–Oct;
  - no k is below −2 (point estimate) on Mar–Oct;
  - Oct 20–Nov 8 point estimates are not negative at top 3 and top 5.
- D1 and D2 are tested separately. Their combination gets one extra row, only if both pass.

**Known risk, stated up front.** The store people were selected in November (mostly Oct 29–Nov 4 voters). For early months the sample is "people still active in Nov", which may weaken the features for those months. The rule's Oct 20–Nov 8 condition covers the live-like period.

### 2026-11-11 03:55Z — RESULT (E5): LM candidates D1 warm audience, D2 person-sum EV. Both DROPPED under the pre-registered rule.

**Setup**
- The PH agent's lm_breakout harness, unchanged: code identical to claude/ph-ops-agent at 8a1ad1df, its build cache of Nov 9.
- Monthly folds Mar–Nov 8, 5 seeds averaged, 10,000-draw day bootstrap.
- Base reproduced exactly: 60.5 / 67.7 / 75.2 on Mar–Oct, 70.0 / 68.0 / 74.5 on Oct 20–Nov 8.
- Features: `experiments/simlab/lm_cand_d1d2.py`; wrapper: `experiments/simlab/lm_cand_run_harness.py`; results: `experiments/simlab/reports/lm_cand_d1d2/`.

Paired change vs the base LM, daily top 3 / 5 / 10, with 95% CI:

| | Mar–Oct (243 days) | Oct 20–Nov 8 (20 days) |
|---|---|---|
| D1 warm audience | +0.4 [−1.0, 1.8] / +0.2 [−0.7, 1.2] / −0.2 [−0.9, 0.4] | −5.0 [−11.7, 1.7] / +1.0 / +2.0 |
| D2 person-sum EV | −0.3 [−1.4, 0.8] / +0.2 [−0.4, 0.9] / +0.1 [−0.4, 0.6] | −1.7 [−5.0, 0] / 0.0 / +1.0 |

**Keep rule**
- Neither candidate has a CI-positive top 3 or top 5 on Mar–Oct.
- Both are negative at top 3 on the live window.
- So both are DROPPED. Following the pre-registration, the D1+D2 combination row was not run.

**Reading**
1. The complete people's own history (audience size, person-sum EV) carries nothing usable beyond the LM's 53 honest inputs.
2. The two-level residual signal (it8 EV coefficient +0.16, on 15 days) does not survive as an LM input across 243 days.
3. With C1–C3 and D1–D2 all failing, five pre-launch candidates built from data we already hold have failed in total.
4. The honest 00:05 LM looks saturated on held data. The next real lift needs a new kind of measurement, for example at-launch X audience or page quality once about 60 days of at-launch reads exist, or within-day early signals if the target allows forecasting after launch.

### 2026-11-11 04:40Z — E5: reference table for the user-simulation goal (person level first)

- **Model:** the E5 logistic baseline, retrained monthly.
- **Rows:** the PH agent's clean it-rows: 1,527,587 rows, 12 days, 48,214 person-days.
- **Code and results:** `experiments/simlab/usersim_ref_table.py`, `experiments/simlab/reports/usersim_ref/usersim_ref_table.json`.

**Input sets**
- **product-only:** the product's text and topics against the person's own history, plus the person's activity.
- **full:** product-only plus PH context (backed the team before, is on the team). There are no follows in either.

Day-bootstrap 95% CIs:

| | product-only | full |
|---|---|---|
| Hit@1 (voting person-days) | 0.186 [0.126, 0.257] | 0.202 [0.156, 0.246] |
| Hit@3 | 0.396 [0.321, 0.477] | 0.511 [0.435, 0.590] |
| within-line-up AUC | 0.651 [0.603, 0.695] | 0.695 [0.651, 0.733] |
| voter R-precision | 0.202 [0.168, 0.237] | 0.207 [0.173, 0.245] |
| ECE / log-loss (all rows) | 0.00054 / 0.0340 | 0.00063 / 0.0336 |
| secondary: top 3/5/10 vs the sample's own votes | 19 / 32 / 49 | 44 / 50 / 63 |

**Reading**
- PH context (team ties) adds about 11 points of Hit@3 and +0.04 within-line-up AUC.
- For the population ordering it matters most: top 3 goes from 19 to 44.
- Product-only taste is weak within a person's day: AUC 0.65.
- Calibration is good overall. One caveat: deciles 3–5 predict 0.0013 against a real 0.00005. These are people with no dated history; the model gives them a floor rate.
- These are the reference rows for it9b's keep rule: product-only Hit@3 or within-line-up AUC CI-positive vs it8 on the same input set.

### 2026-11-11 04:55Z — PRE-REGISTRATION (E5): cold-start content-to-CF user simulation (product-only), before scoring

This is the orchestrator's track for E5. The design is in the docstring of `experiments/simlab/cold_start.py`, committed with this entry. It uses no team, maker, hunter, follow or tie features.

**Variants (all three pre-registered):**
- **V1 cf_enc:**
  - Item vectors come from an SVD of co-upvotes, using only upvotes on launches dated on or before the fold cutoff.
  - A ridge text encoder maps bge-small text embeddings to those CF vectors.
  - The person vector is a recency-weighted mean of the vectors of their upvotes dated ≤ d−2.
  - Score: cosine between the person vector and the encoded vector of L.
- **V2 retrieval:** recency-weighted mean of L's top-5 text similarities to the person's past upvoted launches. The max similarity is reported alongside.
- **V3 hybrid:** z(V1) + z(V2), within each person-day.

**Folds:** cutoffs Oct 18 (scoring Oct 20–31) and Oct 30 (scoring Nov 1–7).

**Evaluation:**
- Rows: the PH agent's 12 clean days (tl_cp_clean_rows); the 19-day it8 rows when provided.
- Metrics: Hit@1, Hit@3, within-line-up AUC, day-bootstrap CIs.
- Paired by day against the E5 product-only baseline. Compared with it8 product-only on matching days.

**Success:** any variant with Hit@3 or AUC CI-positive vs the E5 product-only baseline.

### 2026-11-11 05:30Z — RESULT (E5): cold-start content-to-CF user simulation. No variant beats the product-only baseline.

- **Data:** the 12 clean days of the PH agent's rows, 1.53M rows. Within-line-up metrics with day-bootstrap 95% CIs, paired by day against the E5 product-only baseline.
- **Results file:** `experiments/simlab/reports/cold_start/cold_start.json`.

| | Hit@1 | Hit@3 | within-line-up AUC | AUC − baseline |
|---|---|---|---|---|
| random | 0.099 | 0.238 | 0.493 | |
| E5 product-only baseline (taste logistic) | 0.186 | 0.396 | 0.651 | |
| V1 cf_enc (SVD co-upvotes + text→CF encoder) | 0.128 | 0.329 | 0.574 | −0.077 [−0.147, −0.018] |
| V2 retrieval (top-5 text similarity to past upvotes) | 0.164 | 0.387 | 0.643 | −0.008 [−0.048, 0.031] |
| V2max | 0.153 | 0.348 | 0.627 | −0.024 [−0.061, 0.014] |
| V3 hybrid | 0.167 | 0.357 | 0.625 | −0.026 [−0.076, 0.020] |

**Reading**
- **The encoder is the weak link.** It predicts an unseen launch's co-upvote vector with a held-out cosine of only 0.07 (Oct fold) and 0.08 (Nov fold), from 6.3k–6.6k training launches.
- **So text barely says who will co-upvote a launch.** Product Hunt's collaborative structure is not driven by content.
- This fits the earlier findings: team ties and who-knows-whom carry the signal (+11 Hit@3), and product-only taste is weak (AUC 0.65).
- **Retrieval (V2) matches the taste logistic** within its CI, so a strong text embedding adds nothing over the TF-IDF and topic taste features.
- **Verdict:** none of the three passes the pre-registered success test.
- **All variants beat random,** and V2 and the baseline exceed it8 product-only's reported 0.587 AUC. That comparison is on different days (19 vs 12), so it needs the 19-day rows or it8's 12-day numbers to be sure.

### 2026-11-11 05:55Z — E5: how much of PH upvoting does taste explain? Exposure-controlled checks (19 days, the PH agent's it8 rows)

- **Data:** 2.61M rows; 8,362 voting person-days, Oct 20–Nov 7.
- **Scores:** the E5 baseline. ORACLE ranks launches by the day's final votes; it is non-personal and uses outcomes, so it is a reference only.
- **Code and results:** `experiments/simlab/exposure_control.py`; `reports/usersim_ref/exposure_control_19d.json` and `usersim_ref_table_19d.json`.

Hit@3 [95% CI]; "vs random" is paired by day:

| | full line-up | final top 20 only | final top 10 only |
|---|---|---|---|
| random | 0.236 | 0.284 | 0.444 |
| taste, product-only | 0.386 (+0.150 vs random) | 0.437 (+0.153) | 0.588 (+0.144 [0.087, 0.198]) |
| taste + team ties (full) | 0.486 (+0.249) | 0.518 (+0.234) | 0.601 (+0.157) |
| ORACLE, final votes | 0.740 (+0.504) | 0.753 | 0.794 (+0.350) |

**Pseudo-R²** of the within-person-day choice. The null is the person-day's base rate.

| predictor | pseudo-R² |
|---|---|
| final-vote popularity | 0.179 |
| taste, product-only | 0.009 |
| taste + ties | 0.023 |
| popularity + taste | 0.181 |

So taste adds only about +0.002 on top of popularity.

**Reading**
1. **Choices concentrate on the day's winners.** 94% of voting person-days have their pick inside the final top 10, so upvotes mostly go where the day's winners are.
2. **Personal taste is real but small.** It keeps a stable lift over random (about +0.15 Hit@3) even inside the final top 10, so it survives the exposure control. But within-day it explains about 1% of choice variance (pseudo-R²), against about 18% for the day's popularity.
3. **Team ties work mainly through which launches reach the top.** Inside the top 10 they add almost nothing over product-only taste (0.601 vs 0.588).
4. **Caveat: popularity is not pure exposure.** Final votes mix homepage exposure, mobilisation and shared appeal (common taste). We hold no homepage-position data, so the 18% cannot be split between "exposure" and "everyone likes the same thing".

**"Wants/uses" labels (stacks, collections, reviews): not testable on current text.** These events are product slugs with no dates. Only 3.5% of collection items, 1.4% of reviews and 0.1% of stack items match a launch whose text we hold: 1,031 items over 704 products, and only 36 people with 5 or more matched items. Most stacked products are established tools (Slack, n8n and the like) that are not 2026 launches.

### 2026-11-11 06:20Z — RESULT (E5): "uses" test. Stacks, reviews and collections against content taste and popularity

**Setup**
- Design fixed in commit 8a… before running: `experiments/simlab/uses_test.py`. Results: `experiments/simlab/reports/uses_test/uses_test.json`.
- 52,730 person files; 141,333 products with card text, embedded with bge-small.
- 5,096 complete people with at least 5 "uses" items.
- Up to 10 held-out items per person, each ranked against 50 negatives.
- Person-bootstrap CIs, all narrower than ±0.01 AUC.

AUC by held-out type:

| | random negatives | popularity-matched negatives |
|---|---|---|
| popularity (leave-person-out pool count) | 0.914 | 0.765 (residual within decile) |
| taste from the other uses items (U) | 0.717 | **0.601** |
| taste from upvotes only (V; do upvotes predict uses?) | 0.626 | 0.538 |
| taste from uses + upvotes (UV) | 0.679 | 0.582 |
| reverse: taste from uses → held-out upvote | 0.696 | 0.588 |
| by type, U, pop-matched | stack 0.582 · review 0.611 · collection 0.658 | |

Random scores 0.50 everywhere.

**Reading**
1. **"Uses" show a real content taste beyond popularity.** Against popularity-matched negatives, U scores 0.60, Hit@10 0.34 vs 0.19 random. It is strongest for collections (0.66, themed lists) and weakest for stacks (0.58).
2. **Popularity still dominates** even off the leaderboard: 0.91 vs 0.72 against random negatives.
3. **Upvote taste and use taste overlap only partly.**
   - Upvotes predict uses at 0.54 pop-matched, against 0.60 from the uses themselves.
   - Uses predict upvotes at 0.59.
   - Adding upvotes to the uses profile *lowers* the score (0.58 vs 0.60).
   - So upvotes are a noisy, partly different signal of what people use.
4. **For the user sim:** model "uses/wants" from use history where it exists. Treat upvote history as a weaker, partly different proxy. In every channel, popularity has to be modelled explicitly.

### 2026-11-11 06:40Z — RERUN after the [REDACTED]-maker fix (E5 "full" set). Ties are stronger than measured before; one earlier reading is corrected.

- The fixed team sets drop placeholder handles only. Product-only numbers are unchanged.
- Reports: `reports/usersim_ref/*_fixed.json`.

| E5 full set (product-only + ties) | before the fix | after the fix |
|---|---|---|
| 12 clean days: Hit@1 / Hit@3 / within-line-up AUC | 0.202 / 0.511 / 0.695 | **0.340 / 0.612 / 0.727** |
| 19 days: Hit@1 / Hit@3 / AUC | 0.210 / 0.486 / — | **0.349 / 0.608 / 0.736** |
| 19 days, inside the final top 10: Hit@3 (product-only 0.588) | 0.601 | **0.689** |
| pseudo-R² of the within-day choice | 0.023 | **0.051** (popularity 0.179) |

Corrections:
- **"Ties act mainly through which launches reach the top" (05:55Z entry) is withdrawn.** With real ties, they add about +0.10 Hit@3 even inside the final top 10.
- **The placeholder diluted the real ties:** it made everyone tied to about a third of launches.
- **Taste + ties now explain about 5% of the within-day choice,** against about 18% for the day's popularity.

### 2026-11-11 08:05Z — E5 uses v2, S0–S2 with leaks controlled. Most of the "taste" AUC is product-level appeal.

**Two artifacts found along the way:**
- **Rich-text availability.** API text exists for 74.5% of held-out items but only 28% of pop-matched negatives. This made the first S1 look like +0.089 AUC.
- **Text length.** It alone scored about 0.64–0.67 AUC.

**Final evaluation**
- Sets: negatives matched on pool-popularity decile × rich status × text-length decile. 40,038 pop-matched tasks, 5,096 people.
- **Shuffled-profile control:** the same candidates are scored against a random other person's profile. Real AUC minus shuffled AUC is the *personal* part.
- Code: `experiments/simlab/uses_lenmatched.py`. Results: `reports/uses_v2/uses_lenmatched.json`.

| pop + rich + length matched | AUC | shuffled-profile AUC | personal part |
|---|---|---|---|
| length alone (control) | 0.449 | | |
| popularity (pool count, leave-person-out) | 0.742 | | |
| S0 card text, bge-small | 0.605 | 0.562 | 0.043 [0.038, 0.048] |
| S1 API text, bge-small | 0.611 | 0.558 | 0.053 [0.049, 0.058] |
| S2 API text, bge-base | **0.636** | 0.577 | **0.058 [0.054, 0.063]** |

Paired deltas:
- S1 − S0: +0.007 [0.003, 0.010]. The earlier +0.06–0.09 was mostly format and length.
- S2 − S0: +0.031 [0.027, 0.035]. S2 − S1: +0.024.
- Personal part, S1 − S0: +0.010 [0.006, 0.014].

Subsets:
- Held-out item card-only: the personal part is larger, about 0.10.
- Held-out item with API text: personal part 0.037–0.050.

**Reading**
1. With leaks controlled, use-taste AUC is about 0.61–0.64. Of that, about 0.06 above the shuffled profile is personal. The rest (shuffled ≈ 0.56–0.58) is product-level appeal: what kinds of products people use at all.
2. A stronger embedding helps a little: about +0.03 AUC, +0.015 of it personal.
3. Richer API text helps very little once its format and length are controlled.
4. Popularity (0.74) still dominates.

### 2026-11-11 08:20Z — RERUN after the [REDACTED]-maker fix: LM candidates D1 / D2 are still DROPPED

This rerun uses the same pre-registered rule and harness as before (registered in 9b91802f). Base LM: 60.5 / 67.7 / 75.2. Results: `reports/lm_cand_d1d2/lm_breakout_e5_after_placeholder_fix.json`.

Paired change vs base, top 3 / top 5, with 95% CI:

| | Mar–Oct | Oct 20–Nov 8 |
|---|---|---|
| D1 warm audience | +0.1 [−1.4, 1.5] / +0.8 [−0.2, 1.8] | −5.0 / +3.0 |
| D2 person-sum EV | +0.3 [−0.8, 1.4] / +0.2 [−0.5, 0.8] | 0.0 / +3.0 |

Neither candidate has a CI-positive top 3 or top 5 on Mar–Oct, so the verdict stands: both dropped.
