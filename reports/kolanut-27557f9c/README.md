# Kolanut comparison study `27557f9c` (Sep 26 2026)

Live page: https://usersim.vercel.app/report?study=27557f9c-babd-4387-832f-7bccdcedf31a

100 agents: 5 buyer personas × 5 tasks × Kolanut + 3 competitors. All 100 ran; none stopped by the harness. First value 4.97s. Total 579.6s (limit 480s; the last agents wait about 7 min for one of 25 browsers). Kolanut signups: 20/20 live Gmail aliases (5 pricing runs needed no account). Competitors are demo-only, so they're scored from their websites.

## Buyer picks

Kolanut: 2, Gainsight: 0, ChurnZero: 3, Catalyst: 0 (of 5 buyers)

| Buyer | Kolanut | Gainsight | ChurnZero | Catalyst | Pick | Expected |
|---|---|---|---|---|---|---|
| Sarah Chen | 6.2 | 2.8 | 5.0 | 3.6 | Kolanut |  |
| David Lee | 4.4 | 3.4 | 5.0 | 3.2 | ChurnZero |  |
| Maria Rodriguez | 4.6 | 3.4 | 5.0 | 3.2 | ChurnZero |  |
| James Wilson | 7.0 | 3.8 | 5.0 | 3.2 | Kolanut |  |
| Emily White | 3.8 | 4.2 | 5.0 | 4.4 | ChurnZero |  |

## Tasks × site (0–10)

| Task | Kolanut | Gainsight | ChurnZero | Catalyst | Winner | Kolanut rank |
|---|---|---|---|---|---|---|
| Identify at-risk customer accounts | 4.6 | 4.0 | 6.0 | 6.0 | Catalyst | 3 |
| Draft outreach for inactive users | 7.8 | 1.8 | 6.0 | 4.8 | Kolanut | 1 |
| View overall customer health scores | 5.0 | 6.0 | 6.0 | 4.0 | Gainsight | 3 |
| Set up automated onboarding workflows | 2.6 | 1.0 | 6.0 | 2.0 | ChurnZero | 2 |
| Compare pricing for 50 customer accounts | 6.0 | 4.8 | 1.0 | 0.8 | Kolanut | 1 |

## Wins

- vs Gainsight: Draft outreach for inactive users (Sarah Chen): Kolanut 8.0 vs 1.0. The agent successfully drafted an outreach email for inactive users within the product's campaign editor.
- vs Catalyst: Set up automated onboarding workflows (James Wilson): Kolanut 7.0 vs 0.0. The AI chat feature provided a detailed, step-by-step guide on how to set up automated onboarding workflows.
- vs Gainsight: Identify at-risk customer accounts (Sarah Chen): Kolanut 7.0 vs 1.0. The agent successfully searched for 'at-risk' customers within the product, but no contacts were found.
- vs Gainsight: Set up automated onboarding workflows (James Wilson): Kolanut 7.0 vs 1.0. The AI chat feature provided a detailed, step-by-step guide on how to set up automated onboarding workflows.
- vs Catalyst: Compare pricing for 50 customer accounts (David Lee): Kolanut 6.0 vs 0.0. The pricing page clearly outlines different plans with varying features and user limits, allowing the persona to compare options for 50 customer accounts.

## Losses

- vs Gainsight: Identify at-risk customer accounts (Emily White): Kolanut 1.0 vs 6.0. The page clearly describes how Gainsight helps identify at-risk accounts using AI-powered forecasts and likelihood scores.
- vs Gainsight: View overall customer health scores (Maria Rodriguez): Kolanut 1.0 vs 6.0. The page clearly describes how Gainsight provides customer health scores and 360-degree views, with a relevant screenshot.
- vs ChurnZero: Identify at-risk customer accounts (David Lee): Kolanut 1.0 vs 6.0. The page clearly explains how ChurnZero's health scores identify at-risk accounts using various data points.
- vs ChurnZero: View overall customer health scores (Maria Rodriguez): Kolanut 1.0 vs 6.0. The page clearly describes how ChurnZero provides customer health scores, including the types of data used and benefits.
- vs ChurnZero: Set up automated onboarding workflows (David Lee): Kolanut 1.0 vs 6.0. The page clearly describes automated playbooks and workflows for customer success, which aligns with setting up automated onboarding workflows.

## Fixes for Kolanut

- 'Coming Soon' features for automated onboarding workflows (buyers hurt: 4). Fix: Either remove 'Coming Soon' features or provide a clear timeline for their release.
- Lack of real data or functionality for identifying at-risk accounts (buyers hurt: 3). Fix: Provide real data or clear instructions for importing data to identify at-risk accounts.
- Difficulty viewing overall customer health scores (buyers hurt: 3). Fix: Ensure customer health scores are visible and easily accessible within the product.
- Pricing page doesn't directly address pricing for 50 customer accounts (buyers hurt: 1). Fix: Clarify pricing for specific customer account numbers, like 50, on the pricing page.

## First impression

- **Kolanut** (clarity 8): AI engagement management for SaaS to identify at-risk accounts and draft outreach. For: SaaS teams, agencies, and large teams. Price: Plans start at $199/month for Enterprise, with options for up to 100 users or unlimited. Proof: none shown
- **Gainsight** (clarity 6): A customer retention platform using AI to help teams retain and grow customers. For: Teams that take customer retention seriously. Price: not shown Proof: Trusted by teams that take retention seriously
- **ChurnZero** (clarity 7): AI-powered customer success software to fight churn and drive customer growth. For: Customer success teams looking to scale engagements and proactively manage customer health. Price: not shown Proof: none shown
- **Catalyst** (clarity 6): A customer growth solution that monitors customer health and automates outreach. For: CS and sales teams looking to drive positive business outcomes and revenue growth. Price: not shown Proof: none shown

## Known issues
- Grade fails on total time (579.6s vs 480s) and product task completion (10/25; most misses hit 'Coming Soon' features or an empty new account).
- ChurnZero scored exactly 5.0 for every buyer (website-only scoring is coarse).
- Page wording: only 1 of 4 headline sentences links evidence; onboarding described as 'performs well' at 2.6; rival cards say 0/25 signups (should be 0/20).

Files: `comparison.json`, `agents_summary.txt`, `judge_grade.log`, `report_top.png`, `report_full.png`.
