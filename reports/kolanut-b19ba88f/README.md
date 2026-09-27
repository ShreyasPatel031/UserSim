> **Superseded** by [`kolanut-27557f9c`](../kolanut-27557f9c/README.md). This run had 17 dead agents and a biased 5–0 pick.

# Kolanut comparison study `b19ba88f` (Sep 26 2026, work in progress)

Live page: https://usersim.vercel.app/report?study=b19ba88f-22b2-4b1a-ba05-aa6e17554b04

**Status: grade FAIL, not final.** 100 agents (5 personas × 5 tasks × Kolanut + ChurnZero, Gainsight, Catalyst). Known problems, fixes in progress:

- 17/100 agents never acted (8 session ended, 9 study budget) because of the 25-browser queue. These are infra, not product results.
- Persona picks came out Kolanut 5 / others 0, but persona 1 scored ChurnZero 4.6 vs Kolanut 4.4, so the pick step is biased. Don't trust the headline yet.
- Time to first value 119.5s (limit 10s); total 655s (limit 480s).
- 20/25 Kolanut agents signed up live with Gmail aliases; 5 never reached signup.

## Average score by site (0–10)

| Kolanut | ChurnZero | Gainsight | Catalyst |
|---|---|---|---|
| 5.1 | 3.9 | 3.9 | 2.4 |

## Tasks × site

| Task | Kolanut | ChurnZero | Gainsight | Catalyst | Winner | Why |
|---|---|---|---|---|---|---|
| Identify at-risk customer accounts | 4.6 | 5.0 | 6.0 | 2.4 | Gainsight | The page clearly describes how Gainsight uses AI to identify at-risk accounts with likelihood scores and forecast amounts. |
| Draft personalized customer outreach messages | 8.2 | 5.4 | 1.0 | 1.0 | Kolanut | The persona successfully drafted a personalized customer outreach message using the AI writing assistant within the product. |
| Automate customer health score updates | 1.0 | 5.6 | 3.8 | 3.6 | ChurnZero | The website clearly lists 'Customer health scoring' as a feature, indicating the product can automate health score updates. |
| Analyze customer journey touchpoints | 5.8 | 3.4 | 4.2 | 3.4 | Kolanut | The product allows viewing individual customer activity, which is a key part of analyzing customer journey touchpoints, but the demo data is limited. |
| Compare pricing for 50 customer accounts | 6.0 | 0.2 | 4.4 | 1.8 | Kolanut | The pricing page clearly outlines features for different plans, including 'Accounts explorer' and 'user metadata' which would help compare customer accounts. |

## Personas × site

| Persona | Kolanut | ChurnZero | Gainsight | Catalyst | Pick |
|---|---|---|---|---|---|
| p1 | 4.4 | 4.6 | 4.0 | 2.8 | Kolanut |
| p2 | 5.8 | 3.6 | 4.0 | 1.4 | Kolanut |
| p3 | 4.6 | 3.6 | 3.6 | 1.4 | Kolanut |
| p4 | 6.0 | 4.8 | 3.6 | 2.4 | Kolanut |
| p5 | 4.8 | 3.0 | 4.2 | 4.2 | Kolanut |

## Wins

- vs Gainsight: Draft personalized customer outreach messages (Jessica Kim): Kolanut 9.0 vs 1.0. The persona successfully drafted a personalized customer outreach message using the AI writing assistant within the product. (t2__p5__product step 18)
- vs Catalyst: Draft personalized customer outreach messages (Sarah Chen): Kolanut 8.0 vs 0.0. The agent successfully drafted a personalized customer outreach message within the product's campaign editor. (t2__p1__product step 10)
- vs ChurnZero: Analyze customer journey touchpoints (Emily White): Kolanut 7.0 vs 0.0. The product allows viewing individual customer activity, which is a key part of analyzing customer journey touchpoints, but the demo data is limited. (t4__p3__product step 13)
- vs Catalyst: Identify at-risk customer accounts (David Lee): Kolanut 7.0 vs 0.0. The agent successfully searched for 'at-risk' customers within the product, demonstrating the ability to identify them. (t1__p2__product step 6)
- vs ChurnZero: Identify at-risk customer accounts (David Lee): Kolanut 7.0 vs 1.0. The agent successfully searched for 'at-risk' customers within the product, demonstrating the ability to identify them. (t1__p2__product step 6)

## Losses

- vs ChurnZero: Identify at-risk customer accounts (Emily White): Kolanut 1.0 vs 6.0. The page clearly describes how ChurnZero's health scores help identify at-risk customers and provides a screenshot of the dashboard.
- vs ChurnZero: Automate customer health score updates (Sarah Chen): Kolanut 1.0 vs 6.0. The website clearly lists 'Customer health scoring' as a feature, indicating the product can automate health score updates.
- vs Gainsight: Identify at-risk customer accounts (Emily White): Kolanut 1.0 vs 6.0. The page clearly describes how Gainsight helps identify at-risk customers with features like Renewal Center and in-product data science.
- vs Gainsight: Automate customer health score updates (Sarah Chen): Kolanut 1.0 vs 6.0. The page clearly describes how Gainsight automates customer health scores with AI-optimized scorecards and comprehensive health scoring.
- vs Catalyst: Identify at-risk customer accounts (Jessica Kim): Kolanut 1.0 vs 6.0. The help documentation clearly describes how Catalyst monitors customer health and identifies at-risk accounts using health scores.

## Fixes for Kolanut

- Automation features for customer health score updates are 'Coming Soon' (personas hurt: 5). Fix: Implement Zapier and Webhooks integrations for automation features.
- Product requires authentication provider integration to identify at-risk customers (personas hurt: 2). Fix: Streamline authentication provider integration for identifying at-risk customers.
- Website gets stuck in a loop when identifying at-risk customer accounts (personas hurt: 1). Fix: Fix the website navigation loop when identifying at-risk customer accounts.
- Analytics integrations for customer journey analysis are 'Coming Soon' (personas hurt: 1). Fix: Expedite the release of analytics integrations for customer journey analysis.
- Repeated clicks on 'Connect Firebase Auth' without progress (personas hurt: 1). Fix: Resolve the issue with 'Connect Firebase Auth' button functionality.

## First impression

- **Kolanut** (clarity 8): A tool to identify at-risk SaaS accounts and automate outreach. For: SaaS teams looking to retain customers. Price: Starts at $199/month for Enterprise, with other plans available. Proof: none shown
- **ChurnZero** (clarity 6): AI-powered customer success software to fight churn and drive customer growth. For: Customer success teams looking to manage and grow customer accounts. Price: not shown Proof: none shown
- **Gainsight** (clarity 7): An AI-powered customer retention platform to help teams retain and grow customers. For: Teams that take customer retention seriously and want to grow their customer base. Price: Pricing is available, with features compared for different plans based on included customers per user. Proof: none shown
- **Catalyst** (clarity 6): A customer growth solution for CS and sales teams. For: CS and sales teams looking to drive positive business outcomes and revenue growth. Price: Starts at $500 / month Proof: none shown

Files: `comparison.json` (full data), `agents_summary.txt` (every agent's actions and stop reason), `judge_grade.log`, `report_top.png`, `report_full.png`.
