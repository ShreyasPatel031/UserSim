# people_v3b run — DRAFT (unverified until the fetch-ladder session reviews it)

- Code: branch claude/fetch-ladder-handover @ 1528e5ccae59205a8031edc7dcc851288d80ad47 (build_v3.py, validate_v3.py from cfbe8d62), unmodified; read first: local file I/O only, no GCS writes, no network, no secrets.
- Run 2026-11-02 ~06:33 UTC by Data Feeder on the box.

## Steps (per docs/PEOPLE_V2_REVIEW.md)
1. Merge: all 7 tables/people parts (initial-2026-10-28 + 6 incrementals, 276 rows) copied into t/people/.
2. Re-fetch: the 281 events-only persons (list from a pre-build) via route 4 (Camoufox + DataImpulse residential, light mode, anonymous, read-only) on one spot e2-standard-4 VM (feeder-pv3b-refetch, deleted). Result: 273 x 200, 7 x 404 (the known deleted users), 1 error (abhay_singh_dahiya, left as retry). Output raw/ph_profiles2_refetch2/ (same row schema as ph_profiles2_refetch).
3. file_dates.json = experiments/people_v2/file_dates.example.json.
4. python3 build_v3.py --root . --out v3b
5. python3 validate_v3.py --dir v3b --refetch 'raw/ph_profiles2_refetch*/profiles.jsonl.gz' --events 'ev/*.parquet'
Other inputs identical to raw/people_v3/ (see its README).

## Build
persons 20,947 · handles 46,998 · profiles 26,861 · events 316,910 · refetch used 16,794 / gone 7 / retry 1 · events-only persons 8 (7 gone + 1 retry) · x_field_conflict 316 · extra_self_link_demoted 52 · shared_x_handle_rows_demoted 46.
observed_on_quality: handles fetched 36,933 / upper_bound 10,051 / unknown 14; profiles fetched 16,794 / upper_bound 7,081 / unknown 2,986.
Note: events 316,910 vs 316,913 in v3 (3 fewer after dedup with merged people parts; not investigated).

## Validate: OVERALL PASS, 36/36
display_name_null 9 (was 280); handles_dated_share 0.786, profiles_dated_share 0.625; wispr_bios_on_clean_fixed_rows [mswulinski, sarthakmalhotra]; linkedin_rows_mentioning_wispr [constanza_hasselmann]. Hand-check dump: handcheck.txt.

## Cost
Proxy ~21 MB page bytes (NIC rx 24.6 MB) ≈ $0.03 DataImpulse; VM ~10 min spot ≈ $0.02.

## Files
v3b/{persons,handles,profiles,events}.parquet, build_report.json, validation_v3.json, build.log, validate.log, handcheck.txt
