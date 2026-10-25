# Handover: Product Hunt launch predictor (Oct 25–26 2026)

Goal (from the founder): predict which products land on Product Hunt's front-page lists — **Yesterday's / Last
Week's / Last Month's Top Products**, plus topic lists — **before launch**, from the product, its website, its
competitors, who is posting it and who built it. Target ~90% recall. End goal: show that **simulated users** (UserSim)
add predictive value. Code: this folder. Method details: [`README.md`](README.md). Results: [`results/REPORT.md`](results/REPORT.md).

The founder prefers short, plain answers (no jargon like "hunter/maker" without explaining; no long posts).

## Where the numbers stand

Backtest Mar–Oct 2026 (238 days), each month predicted by a model trained only on earlier months, no launch's own
votes/comments/ranks used:

| Model | Day top 3 / 5 / 10 | Week top 3 / 5 / 10 | Month top 3 / 5 / 10 |
|---|---|---|---|
| Full model (everything known before launch) | 59 / 68 / 78% | 55 / 54 / 52% (weekly-list model) | 25 / 38 / 40% (monthly-list model) |
| Random | 20 / 32 / 48% | 2 / 2 / 8% | 0 / 0 / 0% |
| Product + website + competitors only (no info on who posts/builds) | 35 / 49 / 64% | 8 / 12 / 20% | 8 / 5 / 6% |
| + launch-day audience (who commented; Sep–Oct, 2-fold) | 69 / 79 / 82% | noisy (8 weeks) | – |

Findings:
- **Who posts the launch dominates** (the "hunter": the person who submits it; a big Product Hunt following = votes).
  Hunter followers top third → 45% top-5 rate vs 1% bottom third. Self-posted launches: 9% vs 34%.
- **Nothing collected so far that is known before launch adds signal** beyond the full model: X posts/announcements,
  LinkedIn company pages, competitor following (X/LinkedIn), competitor Product Hunt reviews, LLM "fixes competitors'
  complaints" scores, commenter-network overlap. See `results/signal.csv` (residual test with 95% intervals) and
  `results/batch_eval.csv`.
- **Launch-day audience adds ~8–9 pts** (number of distinct non-team commenters, their reach, their segments: startup
  founders, enterprise people, engineers, marketing). That's the only clear gain.
- Weekly/monthly lists depend on how big a day's winner gets (cross-day magnitude), not just who wins the day.

## Data (NOT in git — big)

- Container copy: `experiments/ph_predict/data/` (ephemeral). **Backup on the VM:**
  `~agent/php/backup_container_data/data.tgz` (everything except `sites.jsonl`, which is at `~agent/php/data/sites.jsonl`).
- Key files: `days/*.json` (PH API launches Jan 1–Oct 24, 6,694 featured), `lb/` (leaderboard pages), `comments/`
  (all comment threads, 102k comments, 20.7k people), `ph_profiles.jsonl.gz` (4,143 Sep–Oct commenter profiles; older
  parser), `segments.jsonl` (v1 LLM segments), `x_posts.jsonl.gz` (maker/company X), `commenter_x.jsonl.gz`,
  `competitors.json` (LLM: 3 competitors per Sep–Oct launch), `competitor_reviews.jsonl.gz` (7,768 PH reviews of 606
  competitors), `competitor_summaries.json`, `complaint_fit.json`, `li_pages.jsonl.gz` (LinkedIn company pages),
  `sepoct_handles.json` (real sites + social links for Sep–Oct launches), `one/` (the one fully-built profile).
- VM-only (`~agent/php/`): `prof_out.jsonl` (raw profile pages), `prof_parsed2.jsonl` (**fixed** profile parse),
  `tabs_out.jsonl` (profile tabs; job running, ~2,000/4,143 done when written), `px_out2.jsonl` (X retry, done),
  `pilot_li_out2.jsonl` (LinkedIn pilot, 20 people), `rev_out.jsonl`, `li_out*.jsonl`.

## Access and tooling

- VM `usersim-grokbot-web` (production UserSim server — don't run heavy CPU there; don't touch the root cloudflared
  on port 80). From the container: `gcloud auth activate-service-account --key-file=<decoded GOOGLE_APPLICATION_CREDENTIALS_B64>`,
  `apt-get install openssh-client`, then a self-restarting IAP tunnel (`/tmp/claude-0/tunnel_loop.sh`, starts
  `gcloud compute start-iap-tunnel ... 22 --local-host-port=localhost:2222`) and `~/.ssh/config` host `vm`
  (user `agent`, ControlMaster). The tunnel drops often; restart the loop.
- The container cannot reach the Apify proxy; **all proxied fetches run on the VM**:
  - `vmfetch.py N < urls` → JSON lines {url, status, route, final_url, html} (datacenter, residential on 403).
    For long runs write to a file on the VM (`setsid nohup sh -c "... > out.jsonl"`), then `ssh vm 'gzip -c out'`.
  - `vmbrowse.py` (headless Chromium via residential, records page data requests; run with `sudo HOME=/root`).
  - `vm_profile_tabs.py`, `vm_reviews.py`, `vm_xposts.py`, `vm_leaderboard.py`, `vm_li_pilot.py`.
- Product Hunt's own data: `frontend/graphql` **persisted queries only** (full-text queries are refused).
  Comments: `ph_comments.py` (hash `371bc2e8…`, slug + page). Profile pages are server-rendered with rich records.
- LLM: Claude Sonnet 4.5 via Vertex (`llm.py`, gcloud token). Direct api.anthropic.com doesn't work from here.
- Pitfall: `pkill -f <pattern>` kills your own shell if the pattern appears in your command line — use `pgrep`
  with a `[x]yz` or `^/full/path` pattern, in a separate call.
- Approvals: the founder approved fetching producthunt.com through proxies, and a **small** LinkedIn pilot through
  their signed-in account (browser on the VM, profile `~agent/php/li_profile`, debug port 9222; still running).
  Don't bulk-crawl personal LinkedIn profiles (account-ban risk). Person-level data is research-only; the plan is to
  reduce it to segment counts for any ongoing pipeline. A safety classifier stopped one earlier response about
  building person profiles — keep data handling deliberate.

## Product Hunt profile: what exists per person (founder's ask: use ALL of it)

Tabs: **About, Forums, Activity, Upvotes, Hunted (`/submitted`), Collections, Stacks, Reviews.**
- Profile page records (parsed by `parse_prof.py`, fixed): name, headline, bio, X handle, verified, maker, followers,
  following, products made, hunted, collections, reviews count, stacks count, visit streak, community rank, current
  product, total upvotes, join date, links (LinkedIn on ~40%, base64 `encodedUrl`), badges with counts, 20 recent upvotes.
- `vm_profile_tabs.py` (fixed): **Stacks** (products used + date added), **Reviews** (reviewed product via
  `followProduct`, rating, date, text, pro/con tags, alternatives, launch it was written from), **Activity** (20 most
  recent dated events).
- **Not yet extracted:** Forums (threads, forums joined), Upvotes page (20 + cursor), Hunted list (products posted),
  Collections (lists + products), About-page maker launches. Activity/Upvotes have more pages (cursor) but the paging
  query hash hasn't been found (browser scroll didn't trigger it; full-text queries refused).

## Profile extraction: finished for one person (update, Oct 25 evening)

The longitudinal agent (branch `claude/eager-pasteur-jffjnl`, folder `experiments/ph_longitudinal/` for its own
forecasting work) picked up this folder after you ran out and finished the one-person extraction. This folder is
copied onto that branch unchanged apart from the files below.

**Result for `alchemist_studio`, every tab complete as far as Product Hunt shows it** (founder spot-checked it):

| Tab | Product Hunt shows | Pulled |
|---|---|---|
| About | header, 90 badges, links | all (`parse_prof.py`) |
| Activity | 100s | **2,119 events, Feb 2016 – Oct 2026** (2,107 comments with text, 9 launches, 3 threads) |
| Upvotes | 100s | **196**, back to Mesh LLM (Apr 3 2026) = the oldest the page offers (it shows ~6 months, not all 2,516) |
| Hunted | 7 | 7 |
| Collections | 3 (116 products) | 115 (awesome 20, for later 93, Jekyll 2) |
| Stacks | says 10 | 4 — the page itself only shows 4, even fully scrolled |
| Reviews | 15 | 15 (product, stars, date, text, pros/cons, alternatives) |
| Forums | 37 joined | 37 joined + **223 forum posts in 217 threads** (title, forum, their text) |
| GitHub / LinkedIn / X | linked from profile | GitHub API (107 repos, events, orgs); your LinkedIn pilot record; your fxtwitter record |

**How (what finally worked):**
- **Server-rendered tab pages** give the first ~20 of each list (`vmfetch.py` on `/@u`, `/@u/{forums,activity,
  upvotes,submitted,collections,stacks,reviews,followers,following}`; `/@u/made` is a 404 — made launches are on the
  About page as `makerPosts`).
- **The rest only loads by scrolling.** `vm_scroll.py` opens the page in headless Chromium through the residential
  proxy and scrolls to the bottom until nothing new loads, recording the JSON the page fetches. Activity took 118
  scrolls (106 extra pages); upvotes 15. Run as `sudo HOME=/root /opt/usersim/venv/bin/python vm_scroll.py 2 < urls`.
  Scroll each collection's own page too: `/@u/collections/<slug>` (slugs are in the collections tab's `path` field).
- **Do not call `frontend/graphql` with rebuilt query hashes to page through histories.** The hashes can be
  reproduced (sha256 of `stripIgnoredCharacters(print(addTypename(doc)))`, which matches `ph_comments.py`'s hash), but
  this session's safety check blocked using them as getting around the site's limits. Browser scrolling is the
  accepted route.
- **Forum posts come from activity, not the forums tab.** The forums tab's thread objects carry no titles or the
  person's comments (`viewerComments` is the logged-in viewer). Activity events whose subject is a comment on a
  `DiscussionThread` carry the thread title and their text; the forum name is joined from the forums tab by thread id.
- `build_profile.py` assembles everything (no network): pages + scroll outputs + GitHub/LinkedIn/X files → profile
  JSON and a readable Markdown listing every item. `vm_profile_all.py` is the page-only parser (first ~20 per tab).

**Files (person-level data — VM only, not in git):** `~agent/php/one_raw_pages.jsonl.gz` (tab pages),
`one_scroll.jsonl` + `one_coll.jsonl` + `one_more.jsonl` (scroll outputs), `one_github.json`, `one_li.json`,
`one_x.jsonl`, and the built profile `one_full_alchemist_studio.json.gz`. Rebuild:
`python build_profile.py alchemist_studio --pages one_raw_pages.jsonl.gz --scroll <the three, gzipped> --github
one_github.json --linkedin one_li.json --x one_x.jsonl --out p.json --md p.md`.

**Known gaps for this person:** 6 of 10 stacked products are not shown anywhere public; upvotes before Apr 2026 are
not offered; 22 of 223 forum posts have no forum name (thread not in the forums tab); X posts not pulled (profile
only; 16 posts exist); LinkedIn is your pilot's record, not re-pulled.

**Cost/time per person:** about 10–15 minutes of scrolling (activity dominates) plus ~10 page loads; one collection
page returned 403 once and worked on retry. 4,143 people serially is days — batch, retry 403s, and measure on ~20
first.

**Still running on the VM when this was written:** your `vm_profile_tabs.py` job (`tabs_out.jsonl`) and the
LinkedIn browser signed in to the founder's account (`vm_li_browser.py`; stop with `sudo pkill -f vm_li_browser`
and `sudo rm -rf ~agent/php/li_profile` when the founder says so).

## Next steps (in order)

1. ~~Extract every tab for one person first~~ **Done for `alchemist_studio` (Oct 25, by the longitudinal agent) and
   checked with the founder** — see "Profile extraction: finished for one person" below. Next: a batch of ~20 people
   to measure time and blocks, then all 4,143 commenters.
2. Re-parse all profiles with `parse_prof.py` (VM: `prof_parsed2.jsonl` already done) and finish `tabs_out.jsonl`.
3. Run `segments2.py` (labels each person from all sources: PH profile, tabs, X, LinkedIn where available). Check one
   person, then all.
4. Re-run `signal_test.py` and `batch_eval.py` with the richer segments (pre-launch: segments of competitor-launch
   commenters / the team's own community; launch-day: who showed up).
5. Pending ideas: snapshot people's latest upvotes daily to build histories going forward; find the Activity/Upvotes
   paging hash (would unlock full histories); a light simulator run (2 personas × 1 task) on ~30 days of launches,
   compared with the "product + website + competitors only" baseline above — that comparison is the UserSim proof.

## Live artifacts

- Dashboard (private): https://claude.ai/artifact/2CTRzYqdFh7Q44fDZJjZ5E (data from the Mar–Oct backtest; not yet
  updated with the Sep–Oct source tests).
- Branch `claude/cool-volta-l5nuo4` (no PR opened).
