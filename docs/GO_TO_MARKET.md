# Atelier go-to-market plan (Product Hunt wedge)

Written Nov 17 2026. The product is live at [usersim.vercel.app/ph](https://usersim.vercel.app/ph) and [/try](https://usersim.vercel.app/try). Every accuracy number here comes from our own backtests and live logs (docs/RESEARCH_LOG.md). Every market number is cited. Prices are hypotheses to test, not findings.

## 1. Executive summary

1. **Wedge:** a paid **Launch Pack** for funded, first-time teams preparing a featured PH launch. It covers a pre-launch audit (simulated reactions, expected rank band, audience groups), a day-picking report, a private launch-day read and a post-mortem. The free public forecasts are the top of the funnel.
2. **Why us:** a 3:45 PT before-reveal forecast that hit 73.8% top-3 live over 14 days, a calibrated rank band, and a persona panel that recovers 54–63% of the themes real commenters raise. We do not sell votes or voters.
3. **Days 1–30:** ask PH for written commercial permission, get a legal read on the data, post the daily forecast in public with every miss shown, and run 20 free pilot audits with makers of upcoming launches.
4. **Days 31–60:** turn on payments ($149 pilot price, then $299), launch Atelier on PH on a day our own model picks, and publish the scored accuracy ledger.
5. **Days 61–90:** add Pro ($79/mo) and Agency ($499/mo) tiers, and extend /try into general pre-launch synthetic research, the bigger market. Hold any API or data licence until PH agrees in writing.

## 2. What we have that is defensible

| Asset | Measured number | Honest limit |
|---|---|---|
| Before-reveal forecast (03:45 PT) | 73.8% top-3 hit over 14 live days; 12-day replay 72.2 / 75.0 / 77.5 (top 3 / 5 / 10) | Small sample. Most of its edge is early-vote signal, so it does not help a founder before launch. |
| Midnight forecast (00:05 PT) | 184-day backtest 58.0 / 65.2 / 76.5. Arm 3 adds +1.5 top 5 and +0.9 top 10 (paired, clear of noise) but −1.1 top 3 | Pre-launch accuracy plateaus around 60% top 3. |
| Weekly board forecast | +2.6 / +5.1 / +7.1 points over the plain board | |
| /try rank band | Calibrated: the 10–90% band contains 80% of outcomes | It is a band, not a rank. |
| "Say" persona panel (24 personas) | Covers 54–63% of real commenter themes at about 50% precision (167–285 launches); catches about 1 in 4 real complaints, +15 recall over generic LLM simulation | Predicts what people say, **not** rank. It adds nothing to rank prediction. |
| "Who" audience mix (5 groups, 19 subgroups) | Beats the base mix at subgroup level, paired −0.063 [−0.086, −0.041] | Person-level likely-voter list is weak: precision 17%, recall 25% vs a 21% baseline, not clear of noise. |
| People store | About 89,000 fully pulled profiles. These people cast about 56% of October votes and 87% of top-3 launch votes. | **Provenance risk; see §8.** Shown only as groups of 20+. |

The defensible part is the combination: a scored, public track record, a people graph that covers most top-3 voting, and persona voices checked against real comments. Prompt-only "synthetic user" tools have none of these.

## 3. Market facts

- **Volume:** PH saw 82,669 launches in 2025 and 196,841 in 2026 up to mid-November. Only 5,267 (2025) and 7,145 (2026) were featured, about 4–6% ([hunted.space Pulse](https://hunted.space/product-hunt-pulse)). The busiest day had 1,613 launches but only 50 featured. In practice the buyers are the roughly 20–25 featured launches a day (about 8,000 a year), not the long tail.
- **Spend on launch help:** we found no reliable survey of what share of founders pay for help. Public prices: boutique launch agencies $1,000–5,000 ([launch checklist](https://launch-checklist-cw5.pages.dev/compare/paid-launch-services-vs-diy/)); Fiverr gigs around $50 ([Fiverr](https://fiverr.com/hamzabutt40/launch-your-product-on-product-hunt)); one reported $500 hunter fee ([dev.to](https://dev.to/holiney/is-product-hunt-dead-or-what-results-can-you-expect-from-product-hunt-launch-4j3d)); a $10k PH ads test ([Indie Hackers](https://www.indiehackers.com/post/we-spent-10-000-on-product-hunt-here-are-the-results-2abf041937)); paid launch communities $99–249/mo ([Launch Club](https://kensavage.gumroad.com/l/launchclubmembershipindiv)); guides around €39 ([Innmind](https://innmind.com/downloads/product-hunt-launch-guide-2026/)). Banned upvote sellers charge about $1–2.50 per vote ([Smales](https://smales.com/blog/how-much-does-it-cost-to-hit-1-on-product-hunt-in-2026.html)). We will measure the paying share ourselves in pilots.
- **Size check:** about 8,000 featured launches a year × 53% first-time teams (our data) × 5–10% buying at $299 gives roughly **$65–130k a year**. That is enough to prove the product but not enough for a company. The PH wedge exists to earn a public track record and proof. The money is in adjacent markets.
- **Adjacent markets:** synthetic user research is funded and priced high. Simile raised $200M at a $2B valuation ([Renascence](https://www.renascence.io/news/30097/simile-raises-200m-at-2b-valuation-for-synthetic-user-ai-testing)). Synthetic Users' enterprise plans ran $23k–200k a year ([archived pricing](https://legal.syntheticusers.com/product-documentation/pricing-old)). Artificial Societies (YC W25) reportedly charges about $40/mo for Pro ([Toolradar](https://toolradar.com/tools/artificial-societies/pricing)). Wynter's message tests cost a few hundred dollars each pay-as-you-go, or $20k a year on Pro ([Wynter](https://www.wynter.com/pricing)). In VC deal sourcing, Harmonic costs an estimated ~$10k per seat per year ([Prospeo](https://prospeo.io/s/harmonic-pricing-reviews-pros-and-cons)). PH rank is linked to later funding ([Cao, HBS](https://www.jbs.cam.ac.uk/wp-content/uploads/2020/08/paper-cao-informationfrictions.pdf); [PHBench](https://www.producthunt.com/p/vela-terminal/phbench-2)).

## 4. Target segments, ranked

| # | Segment | Pain | Willingness to pay | How to reach | What they use |
|---|---|---|---|---|---|
| 1 | **Funded first-time teams planning a featured launch** (seed, 2–15 people) | One shot and no feedback until it is too late. They don't know which day to pick, whether the pitch lands, or what objections will come. | $150–500 one-off. This sits under agencies ($1–5k) and above guides (€39). | PH "coming soon" pages and public launch announcements on X, with one-to-one personal messages. Also accelerator cohorts. | /try audit, rank band, "say" panel, "who" groups, day pick, post-mortem |
| 2 | **Launch agencies and PH consultants** | They need evidence for clients and a repeatable audit. | $300–500/mo; price against their $1–5k fee | Direct outreach and agency directories | Agency tier, white-label audit PDF |
| 3 | **Product and marketing teams testing messaging before any launch** (not only PH) | Real user research is slow and costly (Wynter tests cost hundreds of dollars each). | $50–100/mo self-serve; $5–20k/yr for teams | Content showing "say" accuracy vs real comments; communities of PMs | /try generalized, persona panel, competitor comparison |
| 4 | **VCs and accelerators** sourcing from PH | Early signal before a company appears in deal databases | High ($10k+/seat benchmark) | Warm intros, PHBench community | Weekly forecasts and group-level momentum. **Blocked until PH permits commercial data use (RED).** |

## 5. Offer and pricing

Risk flags: **GREEN** = insight about the founder's own product. **AMBER** = depends on PH permission for commercial use of API or site data. **RED** = do not ship.

| Tier | Price | Contents | Flag |
|---|---|---|---|
| Free | $0 | Public 00:05 and 03:45 forecasts, live board, weekly forecast, per-launch "why" and group-level "who", 1 /try run a week | AMBER (commercial use of PH API for a funnel) |
| **Launch Pack** (core offer) | $299 one-off; first 20 pilots $149, paid after delivery | (a) Pre-launch audit: 2 /try iterations on the draft pitch, rank band, persona reactions, top predicted objections, audience groups, competitor comparison. (b) Day-pick report: expected competition on candidate days. (c) Private launch-day read at 00:05 and 03:45. (d) Post-mortem within 48 h: forecast vs actual, which themes real commenters raised that the panel missed. | GREEN for content; AMBER for data provenance |
| Pro | $79/mo | Unlimited /try, weekly forecasts, competitor watch, for repeat launchers and PMs | AMBER |
| Agency | $499/mo | 10 audits a month, white-label PDF, client workspace | AMBER |
| Group-level API or data licence (VCs, analytics) | $10k+/yr benchmark | Aggregate forecasts and group trends only | **RED until PH agrees in writing** |
| Likely-voter lists, "who to contact" lists, any person-level output, vote guarantees | Never sold | | **RED** (vote-ring risk, privacy; also weak at 17% precision) |

Rules for every offer: we never promise a rank. We never tell a founder to contact specific people or groups to vote. All audience output stays at group level with 20+ people per group. We show the measured accuracy next to every number.

## 6. Positioning and messaging

**One line:** *"See how Product Hunt will react before you launch: what people will say, who it will reach, and where it will likely land."*

Three proof points, each stated with its limit:
1. "Our 3:45 am forecast called 73.8% of top-3 finishers over the last 14 live days. Before launch we call about 6 in 10, and we publish every miss."
2. "Our 24 simulated reviewers raise 54–63% of the themes real PH commenters later raised, across 167–285 past launches. That is 15 points more of the real complaints than a generic AI panel."
3. "Our rank band is calibrated: the 10–90% range held the real outcome 80% of the time."

Never say "guarantee", "get to #1", "voters", "supporters" or "upvote". Say "reactions", "audience", "expected range".

## 7. Channels and 30/60/90-day plan

**Channels.** The main channel is X: post the forecast daily and score it daily, misses included. Second, direct outreach to makers of upcoming launches. We offer a free pre-launch read about their own product, one to one, sent through public contacts only. Per PH's rules, mass DMs and scraped lists are spam ([PH help](https://help.producthunt.com/en/articles/17734384-5-how-to-promote-your-launch-and-what-to-avoid)). Third, Indie Hackers and r/SideProject posts on what we learned (data stories, no pitch). Fourth, our own PH launch.

| Week | Actions |
|---|---|
| 1 | Email hello@producthunt.com asking for commercial API and data permission (send the draft in docs/outreach/ph_data_access_request.md, updated for commercial use). Book a legal read on the ToS and data. Start a daily forecast and score thread on X. |
| 2 | Add an accuracy ledger page (live scored days). Add a waitlist and email capture to /ph and /try. Write the pilot audit template. |
| 3–4 | Contact 40 makers of launches scheduled 1–3 weeks out and deliver 20 free pilot audits. Ask each for a post-mortem quote. Publish 2 Indie Hackers data stories, such as "what the 24 personas got wrong". |
| 5–6 | Stripe checkout and private report pages. Paid Launch Pack at $149. Launch Atelier on PH on the day our model picks, asking for feedback, never upvotes. Post the launch's own post-mortem in public. |
| 7–8 | Raise the price to $299 if pilot conversion is ≥ 20%. Pitch 10 launch agencies on the Agency tier. Run 1 accelerator demo-day cohort. |
| 9–10 | Ship Pro ($79/mo). Extend /try to non-PH concept tests (landing-page reactions without a rank). |
| 11–12 | Review: paying customers, accuracy ledger, the PH answer. Decide whether to double down on the PH wedge or move the main motion to synthetic research (segment 3). If PH has agreed, open VC conversations. |

**Targets by day 90:** 60 audits delivered, 25 paid, 3 agencies, 1,000 waitlist sign-ups, zero PH rule complaints.

## 8. Competitive landscape

| Player | What | Price (public) | Our difference |
|---|---|---|---|
| [hunted.space](https://hunted.space/product-hunt-pulse) | Launch analytics, history, calendars | Free / unclear | Looks back; we forecast and simulate |
| [LaunchList forecaster](https://app.getlaunchlist.com/tools/launch-day-forecaster) | Category-level launch-day tips | Free | Ours is per launch with a scored record |
| [Open Launches](https://www.producthunt.com/products/open-launches-for-product-hunt) | Upcoming-launch deconfliction | Free | We forecast the competition on each day |
| Boutique launch agencies | Done-for-you launch | $1–5k ([source](https://launch-checklist-cw5.pages.dev/compare/paid-launch-services-vs-diy/)) | Cheaper, evidence-based; also a channel (Agency tier) |
| Launch communities ([Launch Club](https://kensavage.gumroad.com/l/launchclubmembershipindiv)) | Community and coaching | $99–249/mo | Data, not network; we never coordinate votes |
| Upvote sellers ([Uprows](https://www.g2.com/products/uprows-hub/pricing), [Smales](https://smales.com/blog/how-much-does-it-cost-to-hit-1-on-product-hunt-in-2026.html)) | Paid votes | $17+, ~$1–2.50/vote | **Banned by PH.** We are the opposite and say so. |
| PH Ads ([source](https://www.producthunt.com/p/producthunt/product-hunt-tldr-a-comparison-guide)) | Display and newsletter | From $10k; not on launch day | Complementary |
| [Artificial Societies](https://toolradar.com/tools/artificial-societies/pricing), [Synthetic Users](https://legal.syntheticusers.com/product-documentation/pricing-old), Simile, Aaru | Synthetic audiences | ~$40/mo to $100k+/yr | We publish accuracy against real outcomes |
| [Wynter](https://www.wynter.com/pricing) | Real-panel message testing | Hundreds per test; $20k/yr Pro | Minutes instead of days, cheaper; less certain |
| [Harmonic](https://prospeo.io/s/harmonic-pricing-reviews-pros-and-cons), [PHBench](https://www.producthunt.com/p/vela-terminal/phbench-2) | VC sourcing / PH-based funding prediction | ~$10k/seat; open benchmark | PH-native audience signal (gated by PH terms) |

## 9. Risks and mitigations

| Risk | Detail | Mitigation |
|---|---|---|
| **PH Terms of Service (highest)** | The terms ban anything that "crawls, scrapes, or spiders" the services, storing "any significant portion of the Content", and any non-personal commercial use ([PH legal](https://www.producthunt.com/legal)). Our 89k-profile store was pulled from site pages. A PH objection could remove the data asset and the product. | Ask PH for a data partnership in week 1. Get a legal read before charging. Sell only derived, aggregate insight, never raw data. Keep a fallback plan: models retrained on permitted API data plus customer-provided data. Do not license data without written consent. |
| **PH API terms** | "The Product Hunt API must not be used for commercial purposes" without contacting PH ([API docs](https://www.producthunt.com/v2/docs)). The live board and paid tiers use it. | Same week-1 request. Attribute PH on every page and keep "not affiliated with Product Hunt". Be ready to rebuild the live board from a permitted source. |
| **Seen as vote-ring help** | PH bans asking for, paying for or rewarding upvotes, and mass DMs ([PH help](https://help.producthunt.com/en/articles/17734384-5-how-to-promote-your-launch-and-what-to-avoid)) | No person-level output. Groups of 20+ only. No "who to contact". Outreach is one to one and offers insight only. Review copy before it ships. Invite PH to inspect what we offer. |
| **Accuracy limits** | Pre-launch top-3 hit is about 60%. Arm 3 trails by 1.1 on top 3. Person-level "who" is weak. "Say" does not predict rank. The live before-reveal sample is 14 days. | The accuracy ledger is public. Every number carries its measurement. Sell the audit as "reactions + range", never as a rank promise. Refund if the post-mortem shows we did not deliver what was described. |
| **Privacy** | Profiles of real people; GDPR and CCPA duties regardless of public origin | Show groups of 20+ only. Never show usernames. Delete on request. Keep a data-retention policy. Run an automated check that no output names a person. |
| **Small wedge** | PH founders worth about $65–130k a year | Use the PH wedge for proof and move to segment 3 by day 90 |

## 10. GTM metrics

- **Funnel:** /try runs a week, waitlist sign-ups, pilot-to-paid conversion (target ≥ 20%), Launch Pack sales, Pro/Agency MRR, CAC by channel.
- **Proof:** live scored days, rolling 30-day top-3/5/10 for 00:05 and 03:45, rank-band coverage (target 80%), post-mortem theme recall on customer launches.
- **Trust:** PH complaints (target 0), privacy requests handled within 30 days, outputs with any group under 20 (target 0).
- **Value:** customer-reported changes made from the audit; repeat or referral rate.
- **Product north stars kept beside these:** coverage and backer-prediction recall (AGENTS.md).

## 11. Product gaps to close before charging (ranked)

1. **Written PH permission and a legal read** on data provenance and API use. Without them we cannot charge safely.
2. **Accounts, checkout and private reports.** The site has no sign-up, pricing or private view today, and /ph renders "Loading…" to crawlers and link previews.
3. **Draft-mode /try:** audit an unlaunched product from a tagline, description and screenshots, not only a live URL.
4. **Public accuracy ledger page** that scores live days (required by the AGENTS.md "measured predictive value" rule).
5. **Post-mortem generator:** forecast vs actual, plus real comment themes vs the simulated ones.
6. **Day-pick report** from scheduled and upcoming launches, with its backtest accuracy.
7. **Group-size and no-person guard** as an automated check on every output, including the PDF export.
8. **Turn the "why" drivers into advice carefully.** They are correlations. Label them as such, and test any advice with forward A/B before claiming lift.
