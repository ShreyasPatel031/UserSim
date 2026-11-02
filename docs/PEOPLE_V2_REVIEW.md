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

## Update, Nov 2: results of the read-only checks

**Source and what "checked" means here.** `docs/people_v2_results/` (commit `de1d1b87`, from Data Feeder, who ran
`scripts/people_v2_checks.py` against the bucket). I read the committed files and cross-checked them against each other and against
the earlier PR #142 files. I did **not** recompute anything from the raw bucket data (still no bucket access), so "checked" means
consistent and plausible, not independently reproduced. The earlier counts for claims 1-5 (poisoned names, 4,208 searches, 329
mismatches, 13,615 links) are not in this JSON; they remain "reported by Grok Bot" and match the PR's own `count_claims_output.json`.
The audit sheet `x_handle_audit_100.csv` has no human labels yet (0 of 100).

### A. Re-fetch of `ph_profiles_rest`: checked

| Item | Result |
|---|---|
| Coverage | 16,528 records, 16,528 unique usernames, `rest_people` = 16,528, 0 missing, 0 extra, 0 duplicates. |
| Status | 200: 16,518; 404: 7; -1: 2; 403: 1. The 7 are deleted users to drop; the 2 + 1 are the 3 to retry. |
| Acceptance rule | 10 rows fail, exactly the 10 non-200 rows. All 16,518 others have a numeric `user_id`, a name and a `joined`. |
| Poison | 0 poisoned ids or names; no `user_id` shared by two usernames; 0 UUID ids. |
| Old non-poisoned fields | Agreement with the old parse: headline 99.87% (15,166 pairs), followings 99.13%, is_maker 99.91%, followers 95.42% (expected drift over time), **twitter 100% (5,374 pairs)**. |
| Fetch date | present on 100% of rows. |

Gate met: rebuild v2 from the re-fetch for the 16,518 good rows. Remaining gaps:
- **No parser version** is recorded (all 16,528 are `None`). Add one before the next fetch.
- 329 rows have `name` equal to the username. That may be normal (people who never set a display name); I did not check it, and the number coincides with the 329 twitter mismatches, so confirm it is not an artifact.
- The old `ph_profiles_rest` twitter field agreed 100% with the re-fetch. The 329 field-vs-link mismatches are therefore **PH data inconsistency, not parser damage**, which settles the open question under claim 4 (which side is right is still unknown).

### B. `tables_v2` as built Oct 30-31: checked

| Check | Result | Effect on my earlier review |
|---|---|---|
| Size | persons 20,671; handles 46,397; profiles 26,600; events 309,328 (PH 277,733, X 31,595) | – |
| Keys | persons unique; no duplicate event keys; no null `ts`; no null X `event_id` | the null-id concern is unfounded |
| Foreign keys | handles and profiles: 0 orphans; **events: 541 whose `person_id` is not in `persons`** | confirmed gap (see below) |
| `observed_on` | **every handle and profile row = 2026-10-31** | confirms the temporal-leakage issue |
| `ph_user_id` | 4,252 numeric, **2,918 UUID**, 13,501 null | confirms mixed id spaces; the re-fetch fixes it |
| `display_name` | 11,681 null (56.5%), 0 poisoned | as expected |
| X handles at confidence >= 0.8 | 8,930 people; **35 have more than one**; **21 handles are shared by 2-3 people** | `validate_v2.py` reported "0 issues", so it missed both |
| X handle sources | 7,689 from own links (0.95); 1,588 from the PH field (0.2-0.8); 312 demoted | 312 confirmed; the 329 vs 312 gap is still unexplained |
| Wispr leakage | **502** profile `extra` rows mention Wispr, of which **486 are `segments`**; also 9 names and 6 bios; the 1 LinkedIn row is `ph:constanza_hasselmann` | the segments contamination is far larger than the README's "1 LinkedIn row" |
| GitHub slug check | `github_url_with_repo_path` = 0 | **uninformative**: the builder constructs the URL from the slug, so a repo path can never appear |

Reading of the Wispr numbers: a segment mentioning Wispr is not proof of poisoning (a few people really work there), but 486 is
far above that. Together with the 879 'Wispr Flow' LinkedIn companies, it strongly suggests v1 `segments` were built from poisoned text.
Treat `segments` as contaminated until rebuilt.

### Orphan events: 541 events, 167 persons, from `orphan_event_person_ids.csv` (checked)

- The CSV sums to 541 events over 167 ids, as the JSON says. All are PH events from `tables/events`; none are X or HN.
- Top ids: `ph:jcbuilds` 56, `ph:vijayanandkailash` 23, `ph:dahvid_nessaiver` 21, `ph:freyam7` 21, `ph:upasana_sahu` 21.
- They look like ordinary PH usernames. They are not in `persons` because `build_v2.py` builds the person list from the profile
  captures plus v1 `people` (`users = old | p2 | v1.index`), so a person with events but no captured profile is missing.
  **That cause is inferred from the code; the CSV alone does not prove it.**
- Size: 541 of 309,328 events (0.17%). Dropping them is small in volume but silently loses these people's whole history.

### Fixes added or changed by these results
1. Rebuild v2 from the re-fetch (16,518 good rows) and drop the 7 deleted users; retry the 3.
2. Build `persons` from the union of **events**, profiles and v1, with `has_profile=false` where there is no capture, and add the
   167 ids; re-fetch their profiles (167 pages, trivial cost).
3. Rebuild `segments` from the re-fetched profiles, or drop them; 486 mention Wispr.
4. Resolve the 35 multi-X people and 21 shared handles by link `kind` and a personal-vs-company label before attributing posts.
5. Stamp the real fetch date (the re-fetch rows already have `fetched_at`) and add a parser version.
6. Label the 100-row audit sheet. As a crude hint only: 17 of the 100 handles share no 4-character run with the person's name or
   username, which suggests company or unrelated accounts. This is not a verdict.
7. Extend `validate_v2.py` with the orphan-event, multi-handle, shared-handle and Wispr-in-segments checks above.

### Status of the fixes: implemented, tested on synthetic data only

`experiments/people_v2/build_v3.py` and `validate_v3.py` implement fixes 1-5 of the list above (PR #142's files are untouched).
**They have not been run on the real data**: this session has no bucket access, and the schema of
`raw/ph_profiles2_refetch/profiles.jsonl.gz` beyond the fields in `people_v2_checks_final_only.json` (status, user_id, name, joined,
headline, followers, followings, is_maker, twitter, fetched_at) is assumed to match `ph_profiles2`. Tested on an 8-person synthetic
fixture (poisoned row repaired by the re-fetch, 404 user, retry user, event-only person, shared X handle, two X links, an x.com URL under a
`website` link, legacy UUID id): all 30 checks pass. What the code does:

| Fix | Implemented as |
|---|---|
| Rebuild from the re-fetch; drop the 7 deleted, retry 3 | Status-200 rows with numeric id and name replace legacy rows. 404 users stay as `persons` with `gone=true` and no profile (their events are real history); other failures get `retry_pending=true`. |
| 541 orphan events | `persons` is the union of events, captures and v1 people, with `has_profile`, `in_events`, `profile_parser`. |
| Contaminated `segments` | Not carried over. Rebuilding them from the re-fetched profiles needs a model run and is **not done**. |
| Multiple / shared / wrong-kind X handles | Handles only from links of the matching kind; first-listed link is primary, later ones 0.5; an X handle claimed by several people is 0.5 for all, with no posts attributed. |
| Build-date stamping | `observed_on` is the row's `fetched_at`, else null with `observed_on_quality='unknown'`. Only re-fetched PH rows are dated; everything else is honestly undated, so time-split use of those features needs the original capture dates. |
| Mixed ids, parser version | Numeric `ph_user_id` only; `parser_version` stored per PH profile. |
| Weak validator | `validate_v3.py`: 30 checks that can fail on real data (orphan events vs the source events, shared and multiple X handles, UUID ids, Wispr text, undated rows, re-fetch coverage); exit code 1 on failure. |

Still open: personal-vs-company labelling of X handles, rebuilding `segments`, and real capture dates for the legacy rows.

To run on the real data (Data Feeder, read-only inputs; output to a new directory, nothing in the bucket is overwritten):
```bash
python experiments/people_v2/build_v3.py --root work --out v2b
python experiments/people_v2/validate_v3.py --dir work/v2b --refetch work/raw/ph_profiles2_refetch/profiles.jsonl.gz --events 'work/ev/*.parquet'
```

## Real-data run of build_v3 / validate_v3 (Nov 2) and follow-up

**Reported by Grok Bot** (Data Feeder ran `bbb10429` unmodified; outputs in `gs://…/raw/people_v3/`, which I cannot read): build exit 0;
persons 20,945, handles 46,688, profiles 26,588, events 316,913; re-fetch used 16,521, gone 7; 281 events-only persons; validate 29 pass,
1 fail; `no_orphan_events` 0 (was 541); `display_name` null for 280 (was 11,681); handles dated 0.779, profiles 0.621.
My read of these numbers (arithmetic and logic only, not the files): 16,521 + 7 = 16,528, so the 3 retries succeeded; the events are now
7,585 above the earlier build (316,913 vs 309,328) while the people table is only the initial 2026-10-28 file, which explains why the
events-only persons rose from 167 to 281.

**Decision on the failed check.** The failure was `no_wispr_in_ph_text` on `ph:mswulinski` ("I lead growth at Wispr Flow…") and
`ph:sarthakmalhotra`, reported as genuine re-fetched bios. I agree the check was too strict, but I did not simply allow all re-fetch bios.
It is now `no_wispr_in_ph_text_on_suspect_rows`: a Wispr mention fails only on a row the old parser could have written (legacy parser, a
poisoned id 606339/109827, or a poisoned name). Clean fixed-parser rows are listed under `wispr_bios_on_clean_fixed_rows` for a hand
check, and a new `no_poisoned_ph_user_id` check was added. Tested on a synthetic fixture: the genuine bio passes, a poisoned legacy row with
a Wispr bio still fails. I have not read the two real bios; "genuine" rests on the reporter.

**Builder changes (also synthetic-tested):** `build_v3.py` now merges all `tables/people` parts (`t/people*.parquet` or
`t/people/*.parquet`, newest `updated_at` per person) and reads every `raw/ph_profiles2_refetch*/profiles.jsonl*` file (a 200 beats a 404 beats
a failure). `validate_v3.py --refetch` takes a glob for the same reason.

**Next runs requested (read-only unless stated):**
1. Merge the 6 later incremental `tables/people` parts into `t/` (the run used only `initial-2026-10-28`), keeping the `ev/*.parquet` set unchanged.
2. Re-fetch profiles for the 281 events-only people (output `raw/ph_profiles2_refetch2/profiles.jsonl.gz`, same fetcher; about $0.02 at the
   ~$1 per 16.5k pages measured for the first re-fetch, which is my arithmetic, not a quote).
3. Rebuild and validate with the new globs: `build_v3.py --root work --out v3b`, then
   `validate_v3.py --dir work/v3b --refetch 'work/raw/ph_profiles2_refetch*/profiles.jsonl.gz' --events 'work/ev/*.parquet'`. Expected: events-only
   persons and null `display_name` near zero, all other checks pass.
4. Hand check, printing PH headline/bio and LinkedIn `extra` for `ph:constanza_hasselmann`, `ph:mswulinski`, `ph:sarthakmalhotra`:
   ```python
   import pandas as pd, json
   Pr = pd.read_parquet("work/v3b/profiles.parquet")
   for u in ["constanza_hasselmann", "mswulinski", "sarthakmalhotra"]:
       print(Pr[Pr.person_id == "ph:" + u][["platform", "source", "name", "bio", "extra"]].to_string(max_colwidth=300))
   ```
5. Dates: print the key list of one `ph_profiles2` record and the GCS creation times (`gcloud storage ls -l`) of `ph_profiles2`, `x_people`,
   `x_posts`, `li_apify`, so the 21-38% undated rows can be given a `file_date` quality instead of null.
6. Still a human job: fill `label_personal_or_company_or_wrong` in `x_handle_audit_100.csv`.

### Dating the legacy rows (Oct 28 upper bound), and what is still to run

Reported by Grok Bot: `ph_profiles2` records have no `fetched_at` (keys: about, badges, badges_total, collections, community_rank_year,
current_product, followers, followings, headline, hunted, is_maker, joined, links, name, products_made, reviews_count, stacks_count, twitter,
upvotes_total, user_id, username, verified, visit_streak_days, voted_recent). GCS creation times under `raw/ph_predict_data/` are all 2026-10-28
13:41-13:42 UTC (`li_apify`, `ph_profiles2`, `x_people`, `x_posts`), which looks like one bulk upload.

`build_v3.py` now reads an optional `root/file_dates.json` (example: `experiments/people_v2/file_dates.example.json`) and gives rows without
their own date that file's upload date with `observed_on_quality='upper_bound'`. This direction is safe for as-of use: the true fetch was at or
before the upload, so a time-split feature that requires `observed_on < D` can only lose data, never leak it. Quality values are now
`fetched` (own `fetched_at`; re-fetched PH rows), `upper_bound` (`ph_profiles2`, X profiles, LinkedIn Apify profiles) and `unknown` (null:
the LinkedIn search rows, profile tabs). Tested on a synthetic fixture; `validate_v3.py` checks the three values and the date format.
Rows dated `upper_bound` are the only truthful way to date these captures; do not present them as exact fetch times.

Runs still to do by someone with bucket access (this session has none), in order: merge the incremental people parts into `t/`; re-fetch the 281
events-only people into `raw/ph_profiles2_refetch2/`; copy `file_dates.example.json` to `work/file_dates.json`; rebuild with `--out v3b`; validate.
Send back `build_report.json`, `validation_v3.json`, and the hand-check output for `constanza_hasselmann`, `mswulinski`, `sarthakmalhotra`.

## people_v3 results as committed (57d330f1) and the X-handle audit summary

**Checked against the committed files** (`docs/people_v3_results/`): `build_report.json` and `validation_v3.json` match what Grok Bot reported -
persons 20,945, handles 46,688, profiles 26,588, events 316,913, refetch 16,521 used / 7 gone / 0 retry, 281 events-only, 29 pass and 1 fail.
This is a read of Data Feeder's output; I have not recomputed it from the raw data.

- **That run used the old validator** (`bbb10429`), so the one failure is the old strict `no_wispr_in_ph_text`, already replaced by the scoped check. The rerun with `cfbe8d62` is still needed to confirm.
- **Stats consistent with the earlier review:** 312 X field/link conflicts (same as the `tables_v2` run), 44 rows demoted for shared X handles
  (about 21 handles x 2-3 people, matching the 21 shared handles found before), 48 extra self-links demoted.
- **Re-fetch list is 274, not 281 (derived).** 20,945 - 20,671 = 274 new persons. The other 7 of the 281 events-only persons are the 7 deleted (404)
  users, who already existed and have events but no profile. Re-fetch the 274; the 7 will 404 again.
- **README quirk:** the input list says `ev/*.parquet - 0 files, 1273205 bytes`, which is a listing error (316,913 events were read).
- **Dates:** `file_dates.json` was not used, hence handles dated 0.779 and profiles 0.621; expect higher with the upper-bound dates.

**X-handle audit, reported by Grok Bot (labeled file not on the branch; I have not seen it):** 72 match (55 high, 17 medium), 13 mismatch
(12 company or product accounts, 1 reassigned handle `@soodadityab`), 15 unsure (9 suspended, 6 not found). The counts add up (72 + 13 + 15 = 100;
55 + 17 = 72; 9 + 6 = 15). The 9 suspended handles are a cluster of fake-looking PH profiles with Turkish names, and 8 similar non-suspended
handles were labelled match/medium on the name alone, so they are suspect. Reading, assuming those counts: only 55 of 100 handles are high-confidence
matches (about 64 if the 8 name-only matches are dropped from the 72), and about 12% are company or product accounts. The labels come from an
automated draft, not a human, and "match on name alone" is not ground truth.

**Needed to decide the X rule:** commit `x_handle_audit_100_labeled.csv` and its README to the branch (e.g. `docs/people_v2_results/`). I want to
split the labels by `source` (`ph_self_link` 0.95 vs `ph_twitter_field` 0.8), since the question is whether the free-text link or PH's
`twitterUsername` is the more reliable handle, and the 8 suspect cluster rows need excluding from that comparison. Until then the rule is unchanged.

## people_v3b results (eb644776): checked, one real bug found

**Checked against the committed files** (`docs/people_v3b_results/`; still not recomputed from raw data). Build report and `validation_v3.json` agree
with the README: 36 of 36 checks pass; persons 20,947, handles 46,998, profiles 26,861, events 316,910; re-fetch used 16,794 / gone 7 / retry 1.
The arithmetic holds: 16,521 + 273 = 16,794; 273 + 7 + 1 = 281 re-fetched; events-only persons 8 = 7 gone + 1 retry; handle dates
36,933 + 10,051 + 14 = 46,998 and profile dates 16,794 + 7,081 + 2,986 = 26,861. Null display names went 280 to 9. The earlier derivation that only
274 of the 281 needed a re-fetch is consistent with the result (273 ok + 1 error; the 7 known-deleted users 404'd again).

**Hand check: resolved.** From `handcheck.txt`: `ph:mswulinski` ("I lead growth at Wispr Flow…", numeric id, joined 2017) and
`ph:sarthakmalhotra` ("Now I'm at Wispr Flow as an AI Agent Engineer…") are genuine re-fetched bios of real Wispr employees.
`ph:constanza_hasselmann`'s LinkedIn row is tied to her own PH link (`li_search_url_matches_self_link`) and lists Wispr Flow among her roles. So the
earlier Wispr flags were not poison, and the scoped check (`no_wispr_in_ph_text_on_suspect_rows` = 0) is the right design.

**Bug found in the output: missing values stored as the text "NaN".** `handcheck.txt` shows `bio: 'NaN'` on constanza's LinkedIn row and `location: 'NaN'` on
mswulinski's PH row, while other cells are real nulls. Cause (build_v3 line 319, inherited from build_v2): a missing v1 value (`about`, `joined`) arrives as a
float NaN and `json.dumps(nan)` turns it into the string `"NaN"`. All 36 checks passed anyway because none looked for it. Impact is unmeasured: any text
feature built from `bio`/`location` would read "NaN" as content. Fixed in the builder (`nn()` helper on every v1 read and in the string normalisation)
and two checks were added: `no_literal_NaN_text` and `extra_json_has_no_bare_NaN`. Tested on a synthetic fixture (a v1 NaN now gives null), and the
new check fails when a cell is set to "NaN". **Not yet run on the real data**, so the v3b parquet still contains the bad strings.

**Two smaller points, both unverified:**
- Events fell 316,913 to 316,910. The README says "after dedup with merged people parts", which cannot be right: event dedup uses only the events
  files. A more likely cause (my inference) is that two more X handle rows became shared (44 to 46 demoted), so 3 X posts lost their owner.
  Check: PH events should be identical between v3 and v3b and only X posts should differ.
- The re-fetch is labelled route 4 (Camoufox), but 21 MB over 281 pages is about 75 KB per page, which matches route 3 (curl via residential, 55-85 KB) and
  the first re-fetch's ~$0.00006 per page, not a browser load (0.4-1.8 MB measured). Cost is negligible either way (about $0.05 total as reported), but the
  route label in the run notes is probably wrong.

**Next run (Data Feeder):** rebuild as v3c with the current branch (the `NaN` fix) and the same inputs, validate, and send back (1) the count of
`"NaN"` strings per profile column in v3b (`(Pr[c]=="NaN").sum()`), (2) the v3c validation, (3) the events count by `platform, kind` for v3 versus v3b.
Still open: the X-handle rule (needs the labeled audit CSV on the branch), real labels, and segments.
