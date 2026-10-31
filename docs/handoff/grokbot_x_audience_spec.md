# Spec for Grok Bot: X audience data for the Product Hunt simulation (Oct 31, 2026)

## Why
The simulation predicts about 62% of each day's real top 3; the launch model about 66%. Every lever on public pre-launch
data lands within ±2 points. The information missing is **who the makers reach on launch day**: about half of real
votes come from people with no Product Hunt tie to the team, and public X endpoints without a login showed only
replies (0.2% of voters). Likes, reposts and follower lists need a signed-in account, which you have.

Everything below is read-only. Please don't follow, like, post or message anyone.

## Keys to match on
- `data/days/<date>.json` (branch `claude/cool-volta-l5nuo4`, `experiments/ph_predict/`): every launch, with each
  maker's and the hunter's `twitterUsername`. October alone: 762 launches, 359 with at least one X handle, 300
  distinct handles.
- Pool people: 8,939 Product Hunt usernames with an X handle. I'll put the mapping at
  `gs://usersim-bakeoff-347838016394/usersim_sim/raw/x_handles_pool.json` (`{ph_username: x_handle}`). It comes from
  the `twitter` field of Product Hunt profiles, which the profile-parsing bug did not touch (all handles distinct,
  70% contain the PH username).

## Deliverables, in priority order
Write each as JSONL to `gs://usersim-bakeoff-347838016394/usersim_sim/raw/x/`. One row per record, UTF-8, the fields
named below. Add a `fetched_at` ISO timestamp to every row. Partial files are fine; I'll merge by key.

### 1. Launch-post engagement (highest value): `engagement.jsonl`
For every maker/hunter X handle of launches from Oct 1 onward (300 handles in October; new ones daily):
- Find the account's posts from launch day −2 to launch day +1 that mention the launch or Product Hunt.
- For each post: who **liked**, who **reposted**, who **quoted**, who **replied**.

```
{"launch_id": "1289449", "day": "2026-10-24", "handle": "maker_handle", "post_id": "...", "post_at": "...",
 "kind": "like|repost|quote|reply", "user": "engaging_handle", "user_followers": 1234}
```
Limit: the first 1,000 engagers per post is enough. **Test it buys:** share of a launch's real Product Hunt voters who
engaged with the maker's post, vs people active that day who didn't vote. The free pilot found 1.1% of voters via
replies alone; the question is whether likes/reposts take it to 10%+.

### 2. Makers' follower lists: `followers.jsonl`
For the same handles: every follower (handle, follower count, bio), capped at 20,000 per account.
```
{"handle": "maker_handle", "follower": "x_handle", "follower_followers": 321, "bio": "..."}
```
**Test it buys:** how many of a maker's followers are in our pool (via `x_handles_pool.json`), and whether a launch's
reach into the pool predicts its votes beyond Product Hunt followers. Also the audience-size prior for first-time teams.

### 3. Pool people's follows: `pool_following.jsonl`
For the 8,939 pool handles: who they follow (handle only), capped at 5,000 each. Start with the ~2,000 most active
pool people; I'll put that list at `raw/x_handles_pool_priority.txt`.
```
{"handle": "pool_handle", "follows": "x_handle"}
```
**Test it buys:** "person follows the maker on X before launch" as a tie, like "backed the team before" on Product Hunt
(the strongest input we have). Dated where X shows a follow date; undated otherwise, flagged.

### 4. Launch-day timeline sample: `timeline_sample.jsonl`
For 200 pool people (same priority list), their X home timeline on one launch day at 09:00 and 15:00 Pacific: which
launch posts appeared. Format: `{"handle": ..., "at": ..., "post_id": ..., "author": ..., "mentions_launch_id": ...}`.
**Test it buys:** whether a launch reaching a person's feed predicts their vote. Small sample on purpose.

## Volume and pacing
- Rough sizes: 1 ≈ 300 posts × up to 1,000 engagers; 2 ≈ 300 × up to 20,000; 3 ≈ 2,000 × up to 5,000. Do 1 first, then
  2 for October's launches, then 3.
- Please stay within whatever rate X allows a normal signed-in user; a week for the full set is fine.
- Note any account that blocks or hides its lists as a row with `"error": "..."` so coverage is measurable.

## What I'll do with it
Each file gets the same test: the simulation with and without the new tie, out of sample (train earlier months,
test the next), with a confidence interval. Results go to `experiments/simlab/reports/x_audience.md`. If a tie
explains votes the pool can't, it becomes a standing input and the daily pipeline asks for a daily refresh of 1 and 2
for that day's launches.

## Not asked for
DMs, email, private communities: not accessible and not wanted.
