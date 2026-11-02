# x_lookup — DRAFT (Data Feeder, 20261102T0735Z)
x_lookup.json: {handle_lower: {exists, name, username, id, protected, followers}} for found accounts; {exists:false, name:null, status: not_found|suspended, detail} otherwise. build_v3.py reads exists and name.
Handles: all 632 from sample_conflicts.py --dir v3d --lookup-list (code @ 581c4235; that's 316 conflicts × 2 handles).
Source: public X users lookup (get_users_by_usernames). 22 new calls of ≤25 handles, plus 100 handles reused from the 4 calls of the earlier 50-row audit. No sign-ins.
Resolved: exists 438 (11 protected) · not_found 188 · suspended 6. "not_found" can also mean a renamed account.
x_lookup_raw.json holds the raw API responses.
Builder check: put it at root/x_lookup.json and ran build_v3 + validate_v3 on the v3b/v3c inputs (scratch out v3e, not uploaded). Result: "x_field_promoted_dead_link": 53; OVERALL PASS, 41 checks.
