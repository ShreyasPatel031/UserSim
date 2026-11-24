# people_v3c run — DRAFT (unverified until fetch-ladder reviews it)
- Code: branch claude/fetch-ladder-handover @ 131d379e (build_v3.py / validate_v3.py incl. a3a1d637 NaN fix), unmodified. Local file I/O only.
- Inputs: identical to raw/people_v3b/ (same t/, raw/ incl. ph_profiles2_refetch2, ev/, file_dates.json).
- Run 20261102T0655Z by Data Feeder: python3 build_v3.py --root . --out v3c; python3 validate_v3.py --dir v3c --refetch 'raw/ph_profiles2_refetch*/profiles.jsonl.gz' --events 'ev/*.parquet'
## Result
Build: persons 20,947 · handles 46,998 · profiles 26,861 · events 316,910 · x_field_conflict 316 (same as v3b).
Validate: OVERALL PASS, 38/38 checks (36 old + no_literal_NaN_text + extra_json_has_no_bare_NaN), NaN counts all 0.
v3b had literal 'NaN' in profiles: name 139, bio 3,263, location 23,901, extra 2,283 (whole cell); now 0.
Files: {persons,handles,profiles,events}.parquet, build_report.json, validation_v3.json, build.log, validate.log
