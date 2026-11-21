# people_v3d run — DRAFT (unverified until fetch-ladder reviews it)
- Code: branch claude/fetch-ladder-handover @ 38f849e4 (includes c2118d47: field-only X handles at 0.6 + conflict sampler), unmodified. Local file I/O only.
- Inputs identical to v3b/v3c. Run 20261102T0657Z by Data Feeder; same commands as v3c with --out v3d / --dir v3d.
## Validate: OVERALL PASS 40/40
The code now has 40 checks: the 38 from v3c plus field_only_x_handles_below_threshold and x_profiles_only_for_confident_handles. Full output: validate.log.
## Counts (v3c -> v3d, delta)
persons 20,947 -> 20,947 (0) · handles 46,998 -> 46,998 (0) · profiles 26,861 -> 26,358 (-503) · events 316,910 -> 309,089 (-7,821)
x_field_conflict 316 (0) · shared_x_handle_rows_demoted 46 -> 40 (-6) · new x_field_only_below_threshold 1,294
X handles from the twitter field alone: 1,291 rows at 0.8 + 3 at 0.5 -> 1,294 at 0.6. Self links at 0.95: 7,678 -> 7,681.
## Events
PH comment 51,353 (0) · PH upvote 234,066 (0) · X post 31,491 -> 23,670 (-7,821): posts from handles that come only from the twitter field are no longer attached to the person.
Files: parquets, build_report.json, validation_v3.json, build.log, validate.log, events_by_platform_kind.csv, deltas_vs_v3c.txt
