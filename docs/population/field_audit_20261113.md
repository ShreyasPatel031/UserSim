# Field audit: per-person files vs store_v3 (population agent, 76,197 files; counts only)

Distinct key paths in the files: 1,464. Carried by store_v3 (persons/tabs/events/x_timelines): 135. **Not carried: 1,329.**

## Not carried, by section (distinct paths; most people carrying one path in the section)

| section | paths | people (max) |
|---|---|---|
| reviews | 350 | 67,263 |
| earlier_records | 319 | 16,394 |
| activity | 192 | 37,473 |
| run | 175 | 76,196 |
| forums | 55 | 76,175 |
| about | 30 | 76,196 |
| upvotes | 27 | 65,033 |
| dashboard | 26 | 1 |
| followers | 25 | 66,739 |
| stacks | 25 | 13,245 |
| following | 21 | 72,322 |
| hunted | 18 | 19,488 |
| slots | 16 | 1 |
| collections | 14 | 9,933 |
| provenance | 7 | 27,215 |
| f1fix | 3 | 140 |
| draft | 1 | 76,074 |
| signed_in | 1 | 76,196 |
| name | 1 | 76,196 |
| ph_user_id | 1 | 76,196 |
| notes | 1 | 28,608 |
| pull_history | 1 | 16,394 |
| deep_pending | 1 | 8,920 |
| header_source | 1 | 8,920 |
| fetched_at | 1 | 27 |
| truncated_budget | 1 | 15 |
| productive_vms | 1 | 1 |
| metric_note | 1 | 1 |
| target_hi | 1 | 1 |
| avg_ppm_productive | 1 | 1 |
| vms_needed_for_20 | 1 | 1 |
| stale_vms | 1 | 1 |
| complete_ppm | 1 | 1 |
| cold_vms | 1 | 1 |
| attempt_ppm | 1 | 1 |
| run_id | 1 | 1 |
| target_lo | 1 | 1 |
| rerun_ppm | 1 | 1 |
| realized_ppm | 1 | 1 |
| active_vms | 1 | 1 |
| vms | 1 | 1 |
| utc | 1 | 1 |

## Most common fields not carried (people carrying it)

| field path | people |
|---|---|
| `signed_in` | 76,196 |
| `name` | 76,196 |
| `run.requests` | 76,196 |
| `ph_user_id` | 76,196 |
| `about.maker_history` | 76,196 |
| `about.joined` | 76,196 |
| `about.bio` | 76,196 |
| `about.badges_count` | 76,196 |
| `about.count` | 76,196 |
| `about.headline` | 76,196 |
| `forums.note` | 76,175 |
| `draft` | 76,074 |
| `following.items[].headline` | 72,322 |
| `following.items[].followers` | 72,322 |
| `following.items[].name` | 72,322 |
| `following.items[].ph_user_id` | 72,322 |
| `run.timing.collections` | 67,276 |
| `run.timing.upvotes` | 67,276 |
| `run.blocks` | 67,276 |
| `run.timing.activity` | 67,276 |
| `about.links` | 67,276 |
| `run.timing.forums` | 67,276 |
| `run.timing.followers` | 67,276 |
| `about.ranks_text` | 67,276 |
| `run.wall_seconds` | 67,276 |
| `run.timing` | 67,276 |
| `about.streak` | 67,276 |
| `about.badges` | 67,276 |
| `run.timing.following` | 67,276 |
| `run.timing.hunted` | 67,276 |
| `run.timing.forums.seconds` | 67,275 |
| `run.timing.forums.items` | 67,275 |
| `run.timing.collections.items` | 67,275 |
| `run.timing.collections.requests` | 67,275 |
| `run.timing.collections.seconds` | 67,275 |
| `run.timing.forums.requests` | 67,275 |
| `reviews.note` | 67,263 |
| `run.timing.followers.requests` | 67,208 |
| `run.timing.followers.seconds` | 67,208 |
| `run.timing.followers.items` | 67,208 |
| `run.timing.following.requests` | 67,200 |
| `run.timing.upvotes.seconds` | 67,200 |
| `run.timing.following.items` | 67,200 |
| `run.timing.upvotes.items` | 67,200 |
| `run.timing.hunted.items` | 67,200 |
| `run.timing.hunted.seconds` | 67,200 |
| `run.timing.hunted.requests` | 67,200 |
| `run.timing.upvotes.requests` | 67,200 |
| `run.timing.following.seconds` | 67,200 |
| `run.timing.activity.items` | 67,199 |
| `run.timing.activity.requests` | 67,199 |
| `run.timing.activity.seconds` | 67,199 |
| `run.gql_calls` | 67,155 |
| `run.thread_navs` | 67,155 |
| `run.html_fetches` | 67,155 |
| `run.clicks` | 67,154 |
| `run.timing.forums.paging.pages` | 66,833 |
| `run.timing.forums.paging.method` | 66,833 |
| `run.timing.forums.paging.ended` | 66,833 |
| `run.timing.forums.paging.dups` | 66,833 |
| `run.timing.forums.paging` | 66,833 |
| `run.timing.forums.paging.trail_tail` | 66,833 |
| `run.timing.forums.paging.resumed_from` | 66,802 |
| `run.timing.forums.paging.next_cursor` | 66,802 |
| `run.timing.forums.paging.resume_overlap_from_offset` | 66,792 |
| `run.timing.activity.paging.method` | 66,757 |
| `run.timing.activity.paging.pages` | 66,757 |
| `run.timing.activity.paging.trail_tail` | 66,757 |
| `run.timing.activity.paging` | 66,757 |
| `run.timing.activity.paging.dups` | 66,757 |
| `run.timing.activity.paging.ended` | 66,757 |
| `followers.role` | 66,739 |
| `run.timing.activity.paging.resumed_from` | 66,725 |
| `run.timing.activity.paging.next_cursor` | 66,725 |
| `run.timing.activity.paging.resume_overlap_from_offset` | 66,715 |
| `upvotes.items[].product_url` | 65,033 |
| `upvotes.items[].name` | 65,033 |
| `upvotes.items[].votes` | 65,033 |
| `upvotes.items[].date` | 65,033 |
| `upvotes.items[].tagline` | 65,033 |
