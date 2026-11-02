# Review of PR #142 (`experiments/people_v2/`): verdicts and fixes

Reviewer: Claude, Nov 2 2026. PR #142 is a draft and was not merged or modified.

**Evidence labels.**
- **Checked** = I verified it myself from the PR's files, 30 raw sample records, 200-row v2 samples, arithmetic on its counts, or the older code on `claude/cool-volta-l5nuo4`.
- **Reported by Grok Bot** = taken from Grok Bot's message of Nov 2 (run of `count_claims.py` and `validate_v2.py` from `experiments/people_v2` on `cursor/people-v2-review-eb35@9e6a2348`, both exit 0; results at `gs://usersim-bakeoff-347838016394/usersim_sim/mailbox/from_grokbot/20261102_fetch-ladder_validation.md` plus `.count_claims.log` and `.validate_v2.log`). I have **no bucket access** (the environment token is rejected with a 401, `GOOGLE_APPLICATION_CREDENTIALS_B64` is not set), so I did not read those files and did not re-run anything. Those numbers stay "reported by Grok Bot" until someone gives me a read-only credential.

## Claim verdicts

| # | Claim | Verdict | Checked | Reported by Grok Bot |
|---|---|---|---|---|
| 1 | The old parser wrote 'Wispr Flow' into 13,286 of 20,671 records (12,951 from user_id 606339, most of the rest from 109827), plus 215 'Lovable' | **CONFIRMED** (symptom and counts); cause **not proven** | 13,286 + 215 = 13,501 equals the poisoned count in `ph_profiles_rest`; 13,286 / 20,671 = 64.3%; 7 of 10 `ph_profiles` and 8 of 10 `ph_profiles_rest` sample records carry id 606339 and the wrong name. Raw HTML was never saved, so `rec()`'s loose username fallback is plausible, not demonstrated. | 13,286 + 215 confirmed, ids 606339 and 109827. |
| 2 | `ph_profiles2` parses correctly; `ph_profiles_rest` still has the bug | **CONFIRMED** | `ph_profiles2`: 0 poisoned of 4,143, owner correct in every sampled pair. `ph_profiles_rest`: 13,501 of 16,528 (82%). | Same split; `ph_profiles` has 3,493 poisoned. |
| 3 | 1,674 of 2,989 LinkedIn rows (56%) are wrong because they were searched with the bad name | **PARTLY** | 1,674 / 2,989 = 56.0%. Only the 879 rows whose company is 'Wispr Flow' are demonstrably wrong; the other ~795 are tainted (queried with the bad name) but not shown wrong. | 4,208 poisoned searches and 1,674 of 2,989 v1 rows confirmed. "Almost always a Wispr employee" and "most Google rows come from poisoning" reported **unclear**; I agree. |
| 4 | 329 of 5,132 X handles (6.4%) are wrong | **PARTLY** | 329 / 5,132 = 6.4% counts *mismatches* between PH's `twitter` field and the person's own X link, not which side is wrong. `nao_yukawa`: field `NaoYukawa` vs link `nyneurotech` (field looks personal). Mismatches also occur in non-poisoned rows, so this is PH data inconsistency, not parser damage. 329 (count script) vs 312 (v2 demotions) is unexplained: the script compares the last URL path segment without stripping queries. | 329 mismatched twitter fields confirmed (as a count). |
| 5 | 13,615 self-linked accounts are dropped (7,160 LinkedIn, 713 GitHub, 5,529 websites) | **PARTLY** | Per-kind counts match the output file. 13,615 is people with *any* link of any kind; the parenthetical sums to 13,402 and the groups overlap. "Dropped" holds for the v1 `people` table only; the raw files kept the links. | 13,615 self-added links confirmed. |
| 6 | Guessed LinkedIn URLs are unreliable | **PARTLY** | No precision measurement exists on clean queries. v2 accepted 0 name-match rows, so the clean case was never measured. Discarding them is conservative, not proven necessary. | – |

"The v2 fix works" is **reported by Grok Bot as confirmed on the Oct 30 box build only**. I have not verified it.

## Review of `build_v2.py` and `validate_v2.py`

Checked (static reading plus samples):

1. **Temporal leakage.** `observed_on` is the build date on every handle and profile (2026-10-31 in the samples). Followers, headline, badges, recent upvotes and LinkedIn employer are as of that scrape. Any backtest on earlier launches sees the future. This violates the "every fact is dated" rule in `experiments/pipeline/DATA.md`.
2. **Poisoned segments carried over.** `profiles.extra.segments` is copied from v1. `segments2.py` built them from the LinkedIn search result (`headline`, `role`, `company`) with no poison gate.
3. **Mixed `ph_user_id` spaces.** `ph_profiles2` ids are numeric; non-poisoned old-parser ids are UUIDs (chrismessina: `161499e4-…` vs `18280`). In the sample, 25 non-null ids are numeric and 18 are UUIDs.
4. **Link handling.**
   - Link `kind` is ignored: any URL on x or github becomes the person's own handle at 0.95; a GitHub repo link becomes the owner or org slug.
   - With several X links the primary is `sorted(...)[0]`, alphabetical.
   - Company accounts are treated as personal (`eodly_io`, `interactaidev`, `nyneurotech` in the samples).
   - `drop_duplicates('handle')` gives all posts of a shared handle to one arbitrary person.
5. **Twitter conflict rule.** The free-text link (0.95) beats PH's `twitterUsername` field (0.2) with no validation; for `nao_yukawa` it appears to pick the wrong account.
6. **Poisoned-record detection** keys only on id 606339 and the names 'Wispr Flow' and 'Lovable'. A third bad object under another name would pass. A sturdier check: any UUID-format `user_id` on a row that `ph_profiles2` also covers.
7. **Missing names.** `display_name` is null for 11,681 of 20,671 people (56%) until the re-fetch lands.
8. **`validate_v2.py` is circular.** It checks invariants the builder enforces (no poisoned name, one X handle at ≥0.8, X profile matches the accepted handle), so "0 issues" on 7 + 50 people is guaranteed and measures no precision. It reads `reconcile_sample.json`, which is not in the PR; `pidset` is unused, so events for people outside `persons` pass; one LinkedIn row still mentions Wispr and the output doesn't say whose; there are no null, uniqueness or foreign-key checks.
9. **Reproducibility.** Both scripts need undocumented relative directories (`t/`, `ev/`, `li/`, `v2/`, `raw/`). `count_claims.py` reads `li_search.jsonl` only; the builder also reads `li_search_retry.jsonl`, so the 7,013-search denominator may differ.
10. **Minor.** X posts are labelled `ts_quality='day'`; posts with a null id collapse to one through the `seenp` dedupe.

## Is tables_v2 safe for training?

**Not yet, except a restricted subset.**

Usable now:
- `ph_username` identity.
- Handles at 0.95 whose link `kind` matches the platform.
- PH fields for the 4,143 `ph_profiles2` people.

Exclude until fixed: `display_name`, `ph_user_id`, `segments`, 0.8 `ph_twitter_field` handles, X posts attributed through company handles, and every profile feature in time-split backtests.

## Re-fetch: what is and isn't affected

The poisoned rows are in `ph_profiles_rest` (13,501 of 16,528) and in `ph_profiles` (3,493), whose 4,143 people `ph_profiles2` already covers. `ph_profiles` therefore needs no re-fetch.

**Recommendation: re-fetch all 16,528 `ph_profiles_rest` profiles, not just the 13,501 poisoned ones.** The 3,027 clean old-parser rows are also incomplete: UUID `user_id`, and empty `joined` and `current_product`. Status, **reported by Grok Bot**: about 3.3k of ~16.5k done, none with poisoned names.

When it finishes, require all of these on the new rows, not only "no poisoned names":
- numeric `user_id`;
- a real `name`;
- a non-null `joined`;
- the parser version recorded per row;
- the real fetch date stored as `observed_on`.

## Fixes, in priority order
1. Stamp real fetch dates; enforce `observed_on < day` in time-split use.
2. Rebuild `segments` without poisoned LinkedIn text, or drop them.
3. Normalise or null the legacy UUID `ph_user_id`.
4. Choose links by `kind`; flag company and shared handles; don't attribute shared-handle posts to one person.
5. Validate the twitter conflict rule on about 100 hand-labelled people.
6. Replace `validate_v2.py` with a precision audit against hand-labelled people, plus null, uniqueness and foreign-key checks.
7. Document inputs and paths; align `count_claims.py` with the builder.
8. Complete the full 16,528-profile re-fetch with the fixed parser, then rebuild v2.

## Open
- Verify Grok Bot's numbers: needs a read-only bucket credential (not available in this session).
- Whether the 'Wispr' LinkedIn rows are "almost always employees" and whether "most Google rows trace to poisoning": unresolved; the evidence (a check of 104 of 302 Google rows) is too thin.

## Update, Nov 2: results of the read-only checks (NOT YET VERIFIED)

Everything in this section is **reported by Grok Bot**. The files (`people_v2_checks_final_only.json`, `x_handle_audit_100.csv`,
`orphan_event_person_ids.csv`) were not on this branch when this was written, and the reviewer cannot read the bucket (401).
Nothing below has been checked against the files.

| Item | Reported by Grok Bot | Note |
|---|---|---|
| Re-fetch of `ph_profiles_rest` | 16,518 good, 10 failed (7 deleted users to drop, 3 being retried), cost about $1 | 16,518 + 10 = 16,528, which matches the expected total. |
| Poisoned names / duplicate ids in the re-fetch | none | Still needs `rows_failing_acceptance` (numeric `user_id`, real `name`, non-null `joined`) and `rest_people = 16,528`. |
| Orphan events in `tables_v2` | 541 events point to persons missing from `persons`, from 167 person ids; top id `ph:jcbuilds` with 56 events | Cause unknown. To check: PH users dropped by the poisoned-profile filter, versus people outside the 20,671 (HN or other sources). |
| Which run is valid | `people_v2_checks_final_only.json` (the shard copies blank section A) | – |

To close this out, after the files land on the branch:
1. Check section A against the acceptance rule and `rest_people`.
2. Classify the 167 orphan ids and decide whether events for real PH users were silently dropped.
3. Compare the empty-field counts with `validation.json`.
4. Change "reported by Grok Bot" to "verified" only where the file supports it.
