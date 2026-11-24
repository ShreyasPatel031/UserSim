# people_v3g run — DRAFT (unverified until fetch-ladder reviews it)
- Code: claude/fetch-ladder-handover @ b02e9649 (fetch-ladder's fix: X profile rows use their own fetched_at), unmodified. Same flags as v3f: --x-fallback --x-fallback-sim 0.5 --x-lookup x_lookup.json. Built 2026-11-02T09:35:50Z by Data Feeder.
- Timestamp source: the scrape logs have no per-row times. Every row in x_people_promoted (29) and x_posts_promoted (30 rows, 539 posts) gets fetched_at = 2026-11-02T08:48:35Z, which is the shard's GCS upload time in raw/x_promoted_posts/. The scrape ran about 08:40–08:48Z, so this is an upper bound at most ~8 min late. Rows are marked fetched_at_source=shard_upload_time.
- Inputs: raw/x_people.jsonl.gz and raw/x_posts.jsonl.gz regenerated as base + stamped shard. The .base files are byte-identical (sha256 checked before and after).
## Validate: OVERALL PASS 41/41 (validate.log). test_build_v3.py: 11 passed.
## Deltas vs v3f (deltas_vs_v3f.txt)
- persons 20,947, handles 46,998, profiles 26,401, events 310,200: all 0 change. handles, profiles (apart from timestamps) and events are identical.
- The only changes: 29 promoted X profiles go from observed_on 2026-10-28 (upper_bound) to 2026-11-02 (fetched), plus built_at on persons. No other profile changed.
