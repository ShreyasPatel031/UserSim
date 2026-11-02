# people_v3f run — DRAFT (unverified until fetch-ladder reviews it)
- Code: claude/fetch-ladder-handover @ 98224e7c, unmodified. Flags as v3e: --x-fallback --x-fallback-sim 0.5 --x-lookup x_lookup.json. Run 20261102T0850Z by Data Feeder.
- Inputs: v3e inputs plus raw/x_promoted_posts/, added additively.
  - New shards: raw/x_people_promoted.jsonl.gz (29 profiles, posts=[]) and raw/x_posts_promoted.jsonl.gz (30 rows, 539 posts). Both are in this folder.
  - Originals kept byte-identical as x_people.base.jsonl.gz (5,195 rows, sha256 39da5990…) and x_posts.base.jsonl.gz (996 rows, sha256 af486365…).
  - The builder reads only raw/x_people.jsonl.gz and raw/x_posts.jsonl.gz, so those two are now concatenations: base + shard. To revert, copy each .base file back.
## Validate: OVERALL PASS 41/41 (validate.log)
## Deltas vs v3e
- persons 20,947 (0), handles 46,998 (0).
- events 309,661 -> 310,200 (+539, as expected; X posts 24,242 -> 24,781).
- profiles 26,384 -> 26,401 (**+17, not the expected +29**).
  - Why: 12 of the 29 handles already had an X profile in v3e (base x_people had their profile but 0 posts). For those 12, the shard row comes later in the file and replaces the older profile, so the row count doesn't change but the profile data is newer. The other 17 are new profiles. All 29 are now present.
- x_field_promoted_dead_link 53 (unchanged).
