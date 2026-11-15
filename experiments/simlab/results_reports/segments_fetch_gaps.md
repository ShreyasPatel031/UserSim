# Profile fields: what we hold vs what would separate kinds of users better (Nov 15)

Held store: `raw/population/store_v3`, 81,131 held people.

## Already used by the segments (store has them)
- **Taste:** dated upvotes on 2025–26 launches with topics.
  - This is only 34% of all held upvotes: the warehouse starts at 2026-01 and the 2025 daily files cover featured launches only.
- **Profile header (≥ 91% filled):** followers, following, products, hunted, reviews, stacks, collections, lifetime upvotes. Plus joined, badges_count and maker_history.
- **Links (66% have any):** X / LinkedIn / GitHub / website presence.
- **Comments:** text for 30.6k of 383k comment ids, matched from the launch-page dump. Exact times for all comments.
- **Role keywords:** from headline and bio.

## Gaps, ranked by expected value for separating kinds of users

| # | Field | Status | Why it matters |
|---|---|---|---|
| 1 | Topics for pre-2025 / non-featured launches that held people upvoted (launch id → topics, day) | 66% of held upvotes have no topic | Taste for the 39k "rare voters" whose only upvotes are on older launches. Launch metadata only, no person pull. |
| 2 | Comment bodies by comment id | 92% of 383k comment ids lack text | "What they say" is grounded in only about 8% of people's comments. |
| 3 | Upvote timestamps | Only 9% known (day-level from the launch) | Recency and activity tiers are dated by launch day, not vote time. |
| 4 | Review text and star ratings | 19k review events, no text or rating | A post-use voice: what users say after trying a product. |
| 5 | X profile (followers, posts, verified) | Store has link presence only. tables_v2 has 2.3k X profiles but keys them by `ph:`+username, with no join to store ids without the salt map. | Outside audience size. |
| 6 | LinkedIn role, company, seniority | tables_v2 has 3.6k rows, role/company mostly null (authwall) | Separates investors, PMs, enterprise buyers. |
| 7 | Badge names | badges_json is 93% filled in the store but unused | Community behaviour types (curator, reviewer, early adopter). Free: we already have it. |
| 8 | Community rank and visit streak | ranks_text_json is empty; streak is 0.1% filled | A "PH regular" signal. Extended PH fields exist for only 4.1k people (tables_v2 ph_profiles2). |
| 9 | Stacks and collections contents with dates | Events exist, no timestamps | What tools people actually use, dated. |
| 10 | GitHub (repos, languages, stars) | 712 handles in tables_v2, smoke-tested only | Separates kinds of developers. |

Items 1 and 7 need no person pull: 1 is launch metadata and 7 is already held. Items 2–6 and 8–10 would be a whole-person pull for the fleet.
