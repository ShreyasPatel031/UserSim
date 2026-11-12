# Evidence notes (for the reviewer)
- Every count can be reproduced by running `counts/count_claims.py` on the raw GCS files; the output is in `counts/count_claims_output.json`.
- **Correction to claim 1:** 13,286 people have `name='Wispr Flow'`, but only 12,951 of them have `user_id=606339`. Across the raw records, the Wispr-named ones carry user_id 606339 (16,364 records) or 109827 (393 records). So two non-owner objects are involved, not one.
- **Correction:** the fixed parser is `ph_profiles2` (4,143 records, 0 poisoned). `ph_profiles_rest` is still poisoned (13,501 of 16,528 records).
- **Gap:** the pipeline never saved the raw page HTML or the embedded Apollo JSON, so the snippet itself isn't available. `raw_samples/owner_vs_wispr_object.json` shows the same username parsed by the buggy and fixed parsers.
- `raw_samples/*.jsonl` contain 10 records per file (30 in total), with `about` cut to 300 characters and `voted_recent` cut to 5 items.
- `v2_samples/*.csv` contain 200 random rows per table (seed 0), with text cut to 300 characters.
- Two claims are still unverified: "almost always a Wispr Flow employee" (claim 2) and "most of the 302 Google rows trace back to the poisoned name". The second rests on a check of 104 of the Google LinkedIn matches. Both should be treated as unconfirmed.
