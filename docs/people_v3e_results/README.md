# people_v3e run — DRAFT (unverified until fetch-ladder reviews it)
- Code: claude/fetch-ladder-handover @ 622888b1, unmodified. Inputs same as v3b/v3c/v3d, plus raw/x_lookup/x_lookup.json (632 handles; copy saved as x_lookup_used.json).
- Run 20261102T0843Z by Data Feeder: python3 build_v3.py --root . --out v3e --x-fallback --x-fallback-sim 0.5 --x-lookup x_lookup.json; then validate_v3.py with the same args as before.
## Result
- x_field_promoted_dead_link = 53, as expected.
- Validation: OVERALL PASS, 41/41 checks. Full output in validate.log.
## Deltas vs v3d
- persons 20,947 (0), handles 46,998 (0).
- profiles 26,358 -> 26,384 (+26).
- events 309,089 -> 309,661 (+572; all X posts: 23,670 -> 24,242). PH comments and upvotes unchanged.
- x_field_conflict 316 -> 263 (-53).
## Promoted handles and their X posts (promoted_x_handles.csv)
- 53 promoted. 42 appear in the X inputs (raw/x_people, raw/x_posts): 28 with a profile, 19 with posts.
- 22 people now have X events (572 events).
- missing_promoted_x_posts.csv: 31 promoted accounts with 0 X events in v3e (1 protected; 21 appear in the inputs with 0 posts, 10 are not in the inputs at all). Queued for a later paced scrape; nothing scraped now.
