# UserSim MCP: Product Hunt prediction

Give a product's link (or its name and description) and get a Product Hunt-style read on it, the same way the UserSim website does. You learn who on Product Hunt it resembles, where it may land, what visitors will say and ask, and talking points for the founder.

You need your personal **admin token** from the UserSim owner. Keep it private.

## 1. Connect (one time)

The server address is `https://35-202-98-224.sslip.io/mcp`. Replace `TOKEN` with your own token.

**Claude Code**
```bash
claude mcp add --transport http usersim https://35-202-98-224.sslip.io/mcp --header "Authorization: Bearer TOKEN"
```

**Cursor** (`~/.cursor/mcp.json`)
```json
{"mcpServers": {"usersim": {"url": "https://35-202-98-224.sslip.io/mcp", "headers": {"Authorization": "Bearer TOKEN"}}}}
```

**Claude Desktop** (`claude_desktop_config.json`, then restart the app)
```json
{"mcpServers": {"usersim": {"command": "npx", "args": ["-y", "mcp-remote", "https://35-202-98-224.sslip.io/mcp", "--header", "Authorization: Bearer TOKEN"]}}}
```

Check it: ask your assistant to *"run usersim_admin_overview"*. If it answers, your token works.

## 2. Two ways to get a prediction

| You have | Use | Takes |
|---|---|---|
| A product that is **not on Product Hunt yet** (any link) | `usersim_ph_quick_run` | about 10–20 seconds |
| A product that **is on today's Product Hunt line-up** (or a recent day's) | `usersim_launch_card` | a few seconds |

### A. Quick run, for any product (pre-launch)

Ask your assistant:

> Use usersim_ph_quick_run on https://buttondown.com and show me the card.

If the page can't be read (some sites need JavaScript or block readers), give the details instead:

> Use usersim_ph_quick_run with name "Acme", tagline "…" and description "…".

You get:
- **Overview**:
  - the top worry visitors will have;
  - where it may land, as a likely rank range, a likely vote range and its percentile among past launches;
  - how many Product Hunt members it resembles.
- **Who votes**: the groups of members it resembles most, with how strongly.
- **What they'll say**: simulated reactions, by type of member.
- **Talking points for the founder**: what to answer in the first comment and what to put on the page.
- **The full data behind it** in the same reply: every reaction, every group, the likely questions, and the tested accuracy of the rank estimate.

A pre-launch run can't include the team's Product Hunt network or how competitors finished. Those only exist once a product is on Product Hunt's line-up.

**Example (Buttondown, a real run):**
```
# Buttondown
Newsletter software built for your success, not to bleed you dry.

## Overview
- Top worry: Pricing is unclear or too high.
- Where it may land: likely rank 2–32 (median 10), likely votes 72–373 (80th percentile of past launches)
- Members it resembles: 1,359 of 13,581 people we hold (10%)

## Who votes
- SaaS / Analytics: 396 of 459 resemble it (8.6× their usual share)
- Marketing / SEO: 295 of 569 resemble it (5.2× their usual share)
- API / Developer Tools: 71 of 447 resemble it (1.6× their usual share)

## What they'll say
- Product Hunt visitors are most likely to be drawn to Buttondown's promise of user-centricity and ethical
  pricing, while also seeking clarity on advanced features, scalability, and long-term differentiation.

## Talking points for the founder
1. We can't see your team's Product Hunt network until you launch, so most early votes will come from
   people who don't know you yet. The pitch and the first comment carry the launch.
2. Answer this worry in the first comment, before anyone asks: "Pricing is unclear or too high."
3. Put this answer on the page: "Details on export and data portability"
4. Treat the rank band as a wide guide: pre-launch rank prediction from a page alone is weak.
```

### B. Launch card, for a product on Product Hunt now

Ask your assistant:

> Use usersim_launch_card for Webless Agents and show me the card.

You can give the product's name or link. It looks in today's line-up, then the two days before. Add a day (`2026-11-21`) to look at a specific day.

You get the same card the UserSim website shows for that launch:
- **Overview**:
  - the top worry;
  - the biggest boost, meaning the factor that helps it most in our model, such as team size;
  - the closest past launch and how it finished;
  - heavy upvoters in its audience compared with a typical launch that day.
- **Talking points for the founder**, including:
  - the size of the team's network;
  - who backed their earlier launches;
  - what to answer first;
  - what people disliked in a similar product.
- **Who votes, What they'll say, Competitors, Why**, with each tab's own notes on how reliable it is.
- A link to the launch on Product Hunt.

**Example (Webless Agents, Nov 22):**
```
## Overview
- Top worry: How does it handle content updates and version control for the published content it's trained on?
- Biggest boost: team size (+28% votes)
- Closest past launch: Agent Builder by Thesys, finished #2
- Heavy upvoters in its audience: 11% (typical launch today: 17%)

## Talking points for the founder
1. You have one of today's biggest networks: 21,686 people we hold follow the hunter or makers
   (#1 of the 7 launches whose network we can see). Make sure they know it's live.
2. People who voted for your earlier launches lean towards Developer-Marketers / Developer Founders
   (3.0× their usual share). Speak to them first.
3. Answer this worry in the first comment, before anyone asks: "How does it handle content updates…?"
4. Put this answer on the page: "…how quickly do the agents update their answers when the source content changes…?"
5. People disliked this in a similar product (Superflow AI): "One user found the installation process
   unclear and got stuck." Show how this one avoids it.
```

## 3. Other things your token can pull

- `usersim_ph_page`: the information on UserSim's Product Hunt page. That's today's launches with live ranks and votes, the midnight forecast and its accuracy record. Add a day to see a past one.
- `usersim_list_studies` and `usersim_get_report`: every saved simulated-user study and its full report.
- Your own simulated-user runs and studies (see GETTING_STARTED), with no daily limit.

## 4. Limits

- **Quick run:** 3 runs an hour and 10 a day per address, 150 a day in total. Everyone using the server shares one address, so if it says the caps are used up, wait and try later.
- **Launch card:** no extra limit. It only covers products on Product Hunt's line-up (today and the two days before, or the day you name).

## 5. How much to trust it

- These are simulations, not real comments or votes. People appear as anonymous types; no one is named.
- **Rank before launch is the weakest part.** From a page alone, the estimate put 29% of the real top 3, and 60% of the real top 10, in its own top 3 and top 10, on 222 test days. Read it as "roughly where", not as a forecast.
- The worries, questions and audience groups are the more useful parts. Use them to fix the page and plan the first comment.
- Each result carries its own accuracy and honesty notes. Read those before quoting a number.

## 6. If something goes wrong

| What you see | What to do |
|---|---|
| `Could not load that page` | Use name + tagline + description instead of the link |
| `caps are used up` | The shared hourly or daily quick-run limit is reached. Try later |
| `not among the launches on …` (launch card) | The product isn't on that day's line-up. Use the quick run, or give the right day |
| `this tool needs a reader token` / HTTP 401 | Your token is missing or wrong. Check the `Authorization: Bearer` header, or ask the owner |
