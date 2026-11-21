# people_v3 run — DRAFT (unverified until the fetch-ladder session reviews it)

- Code: ShreyasPatel031/UserSim branch claude/fetch-ladder-handover @ bbb10429b182c473a5c61ac7bd7664a4702c1b88 (experiments/people_v2/build_v3.py, validate_v3.py), unmodified. Both read in full first: local file I/O only, no GCS writes, no network, no secrets.
- Run: 2026-11-02 05:42 UTC by Grok Bot (Data Feeder), on the box.

## Commands
```
cd work
python3 build_v3.py --root . --out out
python3 validate_v3.py --dir out --refetch raw/ph_profiles2_refetch/profiles.jsonl.gz --events 'ev/*.parquet'
```

## Inputs (copied read-only with gcloud storage cp)
- raw/*.jsonl.gz ← usersim_sim/raw/ph_predict_data/ (ph_profiles, ph_profiles_rest, ph_profiles2, profile_tabs, x_people, x_posts)
- raw/ph_profiles2_refetch/profiles.jsonl.gz ← usersim_sim/raw/ph_profiles2_refetch/ (final, 16,521 ok + 7 gone)
- li/* ← usersim_sim/raw/ph_predict_data/ (li_search, li_search_retry, li_apify)
- t/people.parquet ← usersim_sim/tables/people/initial-2026-10-28.parquet (v1 people; has first_seen. raw/simlab_data_v2/people.parquet lacks first_seen so was not used. The 6 small incremental tables/people files after Oct 28 were NOT merged — builder reads one file.)
- ev/*.parquet ← usersim_sim/tables/events/*.parquet (all 11 files)
- raw/ph_profiles.jsonl.gz — 618939 bytes
- raw/ph_profiles2.jsonl.gz — 764837 bytes
- raw/ph_profiles_rest.jsonl.gz — 2205538 bytes
- raw/profile_tabs.jsonl.gz — 1151766 bytes
- raw/x_people.jsonl.gz — 6172980 bytes
- raw/x_posts.jsonl.gz — 1834701 bytes
- raw/ph_profiles2_refetch/profiles.jsonl.gz — 3010794 bytes
- li/li_apify.jsonl — 30747188 bytes
- li/li_search.jsonl — 2088714 bytes
- li/li_search_retry.jsonl — 29426 bytes
- t/people.parquet — 4382630 bytes
- ev/*.parquet — 0 files, 1273205 bytes

## Build (exit 0)
persons 20,945 · handles 46,688 · profiles 26,588 · events 316,913 · refetch used 16,521 / gone 7 / retry 0 · events-only persons 281 · missing_inputs none · segments dropped.

## Validate (exit 1): 29 PASS, 1 FAIL
- FAIL no_wispr_in_ph_text [2]: ph:mswulinski ("I lead growth at Wispr Flow…") and ph:sarthakmalhotra — both are genuine re-fetched bios (parser refetch-2026-11), so this looks like a false positive of the check, not leftover poison. Not patched.
- Notable passes: no_orphan_events [0] (was 541), all_source_event_people_in_persons, no_poison_names, no_uuid_ph_user_id, every_good_refetch_row_used, no_shared_confident_x_handle, gone_have_no_profile [7].
- Info: handles dated share 0.779, profiles 0.621, display_name null 280, linkedin_rows_mentioning_wispr [ph:constanza_hasselmann] (inspect by hand).

## Files
out/{persons,handles,profiles,events}.parquet, build_report.json, validation_v3.json, build.log, validate.log
