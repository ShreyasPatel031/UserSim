# Request to Data Feeder: read-only people_v2 checks

Copy this file and `scripts/people_v2_checks.py` to `gs://usersim-bakeoff-347838016394/usersim_sim/mailbox/to_grokbot/`.
Everything is read-only against `raw/` and `tables_v2/`. The only writes are the output files in `mailbox/from_grokbot/`.
The exact commands are in the script's docstring. Needs `pandas` and `pyarrow`.

Return `people_v2_checks.json` and `x_handle_audit_100.csv`. The script was smoke-tested only on synthetic data, so real
runs may expose bugs: send the traceback, don't patch the numbers. `ph_profiles2_refetch/` file names and field names
are unknown to me; the script globs `*.jsonl*` and reads `username`, `user_id`, `name`, `joined`, `headline`, `followers`.

## What it answers
A. Re-fetch (`raw/ph_profiles2_refetch/`, draft data): all 16,528 `ph_profiles_rest` usernames present (missing list); one
   record per username; every row passes the acceptance rule (numeric `user_id`, real `name`, non-null `joined`, not Wispr/Lovable);
   no `user_id` shared by several usernames; old-vs-new agreement for headline, followers, twitter (were old non-poisoned fields right?);
   agreement with `ph_profiles2` on overlapping people; whether a parser version and fetch date are recorded.
B. `tables_v2`: row counts and schema; unique keys and foreign keys; duplicate events; null event ids and timestamps;
   `observed_on` values; `ph_user_id` formats; X handles per person and handles shared by several people; GitHub URLs with a repo
   path; conflicts demoted (312 vs 329); any Wispr mention in profiles or segments; and a seeded 100-person X-handle audit
   sheet for a human to label personal / company / wrong.

## Decisions the results drive
- Rebuild v2 from the re-fetch only if section A has 0 failing rows.
- Drop or rebuild `segments` if any mention Wispr.
- Use the audit sheet to choose between the X link and PH's `twitterUsername` field.
