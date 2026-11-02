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

## X-handle audit: checked against the labeled file (`docs/x_handle_audit_labeled/`, commit eaf1e8ae)

The CSV matches its README and Grok Bot's summary: 100 rows, match 72 (55 high, 17 med), mismatch 13, unsure 15 (9 suspended, 6 not found).
Labels are one automated pass by rule plus manual review, not double-checked, so this is draft evidence. My split by source (computed from the CSV):

| Rows | Source | n | match | mismatch | unsure | match among decided |
|---|---|---|---|---|---|---|
| all | own PH link (0.95) | 84 | 63 | 8 | 13 | 63 / 71 = 89% |
| all | PH `twitter` field only (0.8) | 16 | 9 | 5 | 2 | 9 / 14 = 64% |
| without suspended and the 8 suspect-cluster handles | own PH link | 67 | 55 | 8 | 4 | 55 / 63 = 87% |
| same | PH `twitter` field only | 16 | 9 | 5 | 2 | 9 / 14 = 64% |

What this supports and what it does not:
- **Own links are more reliable than the field-only handles** (87-89% against 64% of decided rows). The field-only group is small (14 decided), so
  its interval is wide (roughly 40-85%). Suggestion, a policy call: give field-only handles a confidence below the 0.8 threshold until validated,
  so downstream agents using `>= 0.8` get own links only. Not implemented.
- **It does not test the conflict rule.** The 312-316 conflicts (own link and PH field disagree) are demoted to 0.2 and are not in this sample. The only evidence
  is one anecdote, `ph:subhh`, where the self-link matched. To decide the rule, label about 50 random conflict cases.
- **Company accounts are real**: the `label_personal_or_company_or_wrong` column has 13 `company` and 1 `wrong` (reassigned handle `@soodadityab`). Three of the company
  accounts carry the person's own name (`ph:baronnotary`, `ph:davidee`, `ph:shuaiguan`, name similarity 1.0). Own links include these accounts.
- **The suspended cluster** (9 suspended, plus 8 name-only matches) is likely a sockpuppet group. It should be flagged and excluded from X-derived training
  features, not just from this comparison.
- **A cheap automatic company filter does not work.** Tested on the labels: `namesim(PH display name, X name)` at 0.5 would drop 26 of 72 true matches to catch
  10 of 13 mismatches, and the 3 company accounts that share the person's name pass at any threshold. A usable filter needs the X bio or a model, and labels beyond 100.

## Decision: field-only X handles below 0.8 (Shreyas, Nov 2) and the conflict sampler

**Implemented** in `build_v3.py` / `validate_v3.py`, tested on a synthetic fixture only (not yet on the real data):
- An X handle that comes only from PH's `twitter` field (no own link) is stored at confidence **0.6** (was 0.8) with the note
  "PH twitter field only, no own link; unvalidated". It is a policy call based on the 100-row audit (9 of 14 decided matched, against 55 of 63 for own
  links), which is thin evidence, so the setting is a constant (`FIELD_ONLY_CONF`) to revisit when more labels exist.
- Those handles also get **no X profile row and no X posts**; otherwise a downstream agent filtering on 0.8 would still receive their X data through
  the profile and event tables. Own-link handles are unchanged (0.95, profile and posts kept). Own-link-versus-field conflicts stay at 0.2.
- Two new checks, `field_only_x_handles_below_threshold` and `x_profiles_only_for_confident_handles`. Effect on the real data: the ~1,588 field-only X handles
  leave the confident set, so `x_hi_conf` people will drop by about that many (expect, not measured). The name-similarity filter stays out, as decided.

**Conflict sampler:** `experiments/people_v2/sample_conflicts.py --dir work/v3c --n 50 --out work/out/x_conflict_audit_50.csv` draws a seeded sample of
people whose own link and PH field name different X handles (about 316 in v3b) with both handles, the PH name, headline and bio side by side, and an empty
`label_link_field_both_neither_unsure` column. Tested on a synthetic dataset. After about 50 labels: if link is right in clearly more cases than field, keep
the 0.95/0.2 rule; if it is close to even, both should be kept at a middle confidence; if the field wins, swap them.

## people_v3d and the 50 labeled X-field conflicts: checked

**people_v3d (`docs/people_v3d_results/`), checked against the committed files.** 40 of 40 checks pass. The numbers are internally consistent:
events 51,353 + 234,066 + 23,670 = 309,089; X posts 31,491 to 23,670 is exactly -7,821; handles unchanged at 46,998 (only confidences moved);
the 1,294 field-only X handles are all at 0.6 (1,291 were at 0.8, 3 at 0.5); profiles 26,861 to 26,358 (-503, the field-only handles that had an X profile).
The same files show the v3b NaN bug was widespread, which I could not size before: in v3b `location` was the text "NaN" in 23,901 of 26,861 profile rows,
`bio` in 3,263, `name` in 139, and 2,283 `extra` cells. v3c and v3d have 0. Not recomputed from raw data.

**Conflict labels (`docs/x_handle_conflict_labeled/`), checked from the CSV.** 50 conflicts; the correct handle is the self-link in 24, the twitter field in 14, neither in 9,
both in 3 (sums to 50). In 12 of the 14 field-correct rows the self-link does not resolve on X; in 2 it does (people with two accounts). So "the self-link is dead
and the field is right" holds for 12 of 50 (24%), not 14 of 50 (28%); the other 2 are live-link cases. 19 of the 50 self-links do not resolve at all.
One labeler pass; "not found" cannot tell a rename from a deletion.

**The suggested fallback works on these labels, in-sample.** Rule: when the self-link handle does not resolve on X, the twitter field does, and the X name matches the PH name
(similarity >= 0.5), use the field. Scored against the labels (a pick is right if it equals the correct handle or the correct handle is "both"; 9 "neither" rows cannot be fixed):

| Rule | right | wrong | neither |
|---|---|---|---|
| always self-link (current) | 27 | 14 | 9 |
| always twitter field | 17 | 24 | 9 |
| **fallback (name >= 0.5)** | **39** | **2** | 9 |

All 12 flips are correct; the 2 wrong are the live-link two-account cases. This is in-sample (the same 50 rows motivated the rule) and small, so it is provisional.

**Implemented, opt-in, synthetic-tested only.** `build_v3.py` reads an optional `root/x_lookup.json` (`{handle_lower: {"exists": bool, "name": str}}`). Without it, behaviour is unchanged.
With it, a qualifying conflict gets the field handle at 0.8 (`source=ph_twitter_field_live_fallback`) with its X profile and posts, and the dead link is demoted to 0.2.
New check: `fallback_handles_confident_and_replace_a_dead_link`. Fixture: only the dead-link person changed; a live-link person, a name-mismatch person and a person with no field lookup were untouched.

**To use it (needs X lookups, which only Data Feeder can run):**
```bash
python experiments/people_v2/sample_conflicts.py --dir work/v3d --out work/out/x_conflict_audit_50.csv --lookup-list work/out/x_lookup_handles.txt
```
then resolve every handle in `x_lookup_handles.txt` (about 630, roughly 26 lookups of 25 handles) with the same read-only X users lookup used for the audit, write
`x_lookup.json` as above into the build root, rebuild, and validate. Decision for Shreyas: adopt the fallback after that run, or keep own-link-wins. I would adopt it only
if a fresh, non-overlapping sample of about 30 conflicts agrees, since the evidence so far is in-sample.

## Fallback wired behind a flag (decision: adopt, gated on a fresh ~30-conflict sample)

Decision (Shreyas, Nov 2): adopt the dead-own-link fallback (use PH's twitter field when the own-link handle does not resolve on X and the field handle does,
with name similarity >= 0.5), **only after** a fresh, non-overlapping sample of about 30 conflicts agrees. Until then it is off.

`build_v3.py` now has an explicit switch:
```bash
python experiments/people_v2/build_v3.py --root work --out v3e                                              # default: own-link-wins, unchanged
python experiments/people_v2/build_v3.py --root work --out v3e --x-fallback --x-lookup x_lookup.json          # adopted rule (threshold: --x-fallback-sim 0.5)
```
- **Off by default**, even when `x_lookup.json` is present in the build folder (a change from the earlier version, where the file alone switched it on).
- With the flag on and no lookup file the build **fails** with an error. There is no silent skip.
- `x_lookup.json` format: `{handle_lowercase: {"exists": true|false, "name": "X display name"}}` for every handle in `x_lookup_handles.txt`.

**Tests:** `experiments/people_v2/test_build_v3.py` (10 tests, `python -m pytest experiments/people_v2/test_build_v3.py`, needs pandas and pyarrow; synthetic data only). It covers
off-by-default with a lookup file present; the flag flipping only the qualifying dead-link person (a live link, a name mismatch and an unlooked-up field stay as they were);
the similarity threshold; the missing-file error; field-only handles at 0.6 with no X profile or posts; first-listed link as primary and wrong-kind links not becoming handles;
a poisoned legacy row repaired by the re-fetch and an event-only person kept; no "NaN" text; and `validate_v3.py` passing in both modes.
The tests can fail: setting the field-only confidence to 0.8 failed 3 tests, and making the fallback default to on failed the off-by-default test (the code was restored; 10 of 10 pass).

**To adopt it** once the ~30-label sample agrees: rebuild with `--x-fallback --x-lookup x_lookup.json`, run `validate_v3.py`, and compare `stats.x_field_promoted_dead_link` in
`build_report.json` with the number of dead-link conflicts in the lookup (the first 50-row sample suggests about 24% of conflicts). Pending from Data Feeder: `x_lookup.json` (~630 handles) and the 30-conflict labels.

## Fallback gate check on the fresh 30 labels, and the rebuild request (Nov 2)

**Checked against the committed files** (`docs/x_lookup/`, `docs/x_handle_conflict_labeled2/`, commit 180d7819):
- `x_lookup.json` has 632 handles, all lowercase keys: 438 exist (11 protected), 194 do not (188 `not_found`, 6 `suspended`); every existing account has a name. 438 + 188 + 6 = 632.
- The 30 new labels tally as the README says: link 15, field 7, neither 5, both 2, unsure 1. None of the 30 person_ids is in the earlier 50.
- Suspended accounts count as dead in the builder (`exists: false`), which is what we want for a self-link. `not_found` can also be a renamed account.

**Scoring the rule with the builder's own `namesim` (a pick is right if it equals the correct handle or the answer is "both"):**

| Set | rule | right | wrong | neither/unsure | promotions made | wrong-person promotions |
|---|---|---|---|---|---|---|
| new 30 (out of sample) | always self-link | 17 | 7 | 6 | – | – |
| new 30 | fallback, name sim >= 0.5 | **20** | 4 | 6 | 3 (all correct) | **0** |
| new 30 | fallback, no gate | 21 | 3 | 6 | 6 (4 correct) | **2** (`ph:ahmetsulek`, `ph:its_me_imad`) |
| old 50 (in sample) | fallback, sim >= 0.5 | 39 | 2 | 9 | 12 (all correct) | 0 |
| all 80 | fallback, sim >= 0.5 | 59 | 6 | 15 | 15, all correct | 0 |

- **The gate stays at 0.5.** The ungated rule looks slightly better on "right", but my score treats "neither" rows as neutral, and that hides the real cost: an ungated promotion
  that lands on a stranger attaches the stranger's X profile and posts to the person, while a dead self-link attaches nothing. Gated promotions: 15 of 15 correct over 80 labels
  (3 of 3 out of sample), 0 wrong-person. The gate misses one correct case (`ph:amanj203`, name similarity 0.14), so recall on the dead-link cases is 3 of 4 out of sample.
- Data Feeder's "fired on 6 rows, 4 right, 2 a different person" is the ungated count; I reproduce it. The README's remark that the gate should block the 2 is confirmed.
- **Gate condition met, with thin evidence:** the fresh sample agrees in direction, but it contains only 3 promotions. A 15-of-15 record has a 95% lower bound of roughly 80% precision.
  Adopted as decided; revisit if the rebuilt data shows more wrong-person cases.

**Rebuild with the fallback on: not done by me (no bucket inputs).** Request for Data Feeder, same inputs as v3d, code at the current branch head:
```bash
python3 build_v3.py --root . --out v3e --x-fallback --x-lookup x_lookup.json
python3 validate_v3.py --dir v3e --refetch 'raw/ph_profiles2_refetch*/profiles.jsonl.gz' --events 'ev/*.parquet'
python3 -m pytest experiments/people_v2/test_build_v3.py -q     # optional, synthetic
```
Report: `build_report.json` (expect `x_field_promoted_dead_link` = 53, the count Data Feeder got on the earlier auto-on version with the same lookup and inputs; a different number means something changed,
so investigate before using v3e), the validation output (expect all checks to pass, including `fallback_handles_confident_and_replace_a_dead_link`), and v3d versus v3e:
handles at confidence >= 0.8 by source, X profile rows, and X posts by platform. Expected direction (not measured): about 53 persons swap their X handle; their X profile
and posts change only where `x_people` / `x_posts` hold data for the field handle, which they may not (those handles were looked up, not scraped). If posts for promoted handles are missing,
the next step is scraping those ~50 accounts, not changing the rule.
The pooled label rate (15 of 80) predicts about 59 promotions of 316 conflicts; 53 is in line.

## people_v3e / v3f (98224e7c, 2014ae52): checked

**Checked against the committed files** (`docs/people_v3e_results/`, `docs/people_v3f_results/`; not recomputed from raw data). v3f: 41 of 41 checks pass; `x_field_promoted_dead_link` 53 in
both v3e and v3f, as predicted from the lookup. Arithmetic: events 51,353 + 234,066 + 24,781 = 310,200; X posts 24,242 to 24,781 is exactly +539; profiles 26,384 to 26,401 is +17,
and Data Feeder's explanation (12 of the 29 scraped handles already had a profile, which the later shard row replaces; 12 + 17 = 29) matches how the builder loads X rows (a later row for the
same handle wins). v3e: 53 promoted, 42 appear in the X inputs, 22 people gained 572 X events; the 31 promoted accounts with no posts were then scraped for v3f (30 rows, 539 posts).
Persons and handles are unchanged (20,947 / 46,998). The two shard files are not in the folder although the README says they are, so I could not inspect them.

**Problem found: dates on the 29 newly scraped X profiles.** The builder stamped every X profile row with `file_dates.json` `x_people` = 2026-10-28 as an *upper bound*. The 29 shard
profiles were scraped on Nov 2, after that date, so the label claims they were fetched no later than Oct 28, which is false and breaks the as-of guarantee (the label says a profile
existed on a day it did not). Fixed in `build_v3.py`: an X row's own `fetched_at` (top level or inside `profile`) is used with quality `fetched`; the file date stays the upper bound only
for rows without one. New test `test_x_profile_rows_use_their_own_fetch_date_not_the_older_file_date` (11 tests pass; it fails when the fix is removed).
**Needed:** the shard profile rows need a `fetched_at` (or tell me the scrape date and I will add it to the loader), then rebuild as v3g. The posts are unaffected: their date is the tweet's own `created_at`.

**Open risk: the 53 promotions have not been reviewed one by one.** The gate's measured record is 15 of 15 correct over 80 labels, which only bounds precision at roughly 80% from below, so a handful of the 53 could
be wrong-person promotions, and 539 posts from 30 promoted accounts are now attached to people. `promoted_x_handles.csv` has the X name but not the PH name, so I cannot re-score the margins from it.
Request: from v3f, list the 53 promoted people with PH display name, X name and name similarity, lowest first, and hand-check those below 0.75:
```python
import pandas as pd, importlib.util
b = importlib.util.module_from_spec(s := importlib.util.spec_from_file_location("b", "experiments/people_v2/build_v3.py")); s.loader.exec_module(b)
H = pd.read_parquet("v3f/handles.parquet"); P = pd.read_parquet("v3f/persons.parquet"); Pr = pd.read_parquet("v3f/profiles.parquet")
f = H[H.source == "ph_twitter_field_live_fallback"][["person_id", "handle"]].merge(P[["person_id", "display_name"]], on="person_id")
x = Pr[Pr.platform == "x"][["person_id", "handle", "name"]].rename(columns={"name": "x_name"})
f = f.merge(x, on=["person_id", "handle"], how="left"); f["sim"] = [b.namesim(a, c) for a, c in zip(f.display_name, f.x_name)]
f.sort_values("sim").to_csv("promoted_name_margin.csv", index=False)
```
(Promoted handles without an X profile have no `x_name` there; take the name from `x_lookup.json`.)

**Use of v3f:** usable now for work that does not depend on dates of X profile rows. For any time-split use, exclude the 29 shard profiles until v3g, or wait for it. The 53 promotions stay "adopted, provisional" until the margin list is reviewed.

## people_v3g (f88add97): checked

**Checked against the committed files** (`docs/people_v3g_results/`; not recomputed from raw data). v3g keeps the v3f counts (persons 20,947, handles 46,998, profiles 26,401, events 310,200;
`build_report.json` identical apart from `built_at`), 41 of 41 checks pass, and `validation_v3.json` equals v3f's except `profiles_dated_share` 0.636 to 0.637, which is exactly the 29 rows that
moved from `upper_bound` to `fetched` (29 / 26,401 = 0.0011). The events table is identical to v3f. The delta file shows the only data change: the 29 promoted X profiles go from
`observed_on 2026-10-28 (upper_bound)` to `2026-11-02 (fetched)`. (The "3,015 profiles with changed observed_on" line is a raw null-versus-null comparison artefact; the null-aware count is 29.)
The builder code used is `b02e9649`, my fix, and Data Feeder reports its 11 tests pass.

**One remaining wrinkle, minor:** the shard rows have no per-row time, so all 29 get the shard's GCS upload time (2026-11-02T08:48:35Z), recorded as `fetched_at_source=shard_upload_time`. The scrape ran
about 08:40-08:48Z, so the stamp is at most about 8 minutes late. That errs in the safe direction for as-of use, but the quality label says `fetched` where it is strictly an upper bound at the minute level;
immaterial at day granularity.

**Verdict:** v3g supersedes v3f and is the current best build. The date problem I found is fixed. Still open from before: the hand-check of the 53 promotions by name margin (script in the v3e/v3f section),
labelling segments (dropped), and the personal-versus-company question for X handles.

**Unrelated code on this branch.** Commit `8e641102` (Grok Bot, "ph_upvotes: following mode ... daily people refresh runner") adds 8 files under `experiments/pipeline/ph_upvotes/`: a route-4 scraper of PH
`/@user/upvotes` and `/following` pages and scripts that create a GCE VM, run it, and delete it. It is not part of this review and sits in a docs PR; I only skimmed it. Things for Shreyas to decide:
(1) it belongs in its own PR; (2) `PROXY_URL` is passed as instance metadata (`--metadata=...proxy="$PROXY_URL"`), which anyone with read access to the VM or project can see, so use Secret Manager at runtime instead,
and the proxy password is already on the rotation list; (3) `run_daily.sh` is proposed as a daily routine with caps of $0.3 (upvotes) and $4.0 (following) per run, up to about $130 a month if it runs every day,
which needs explicit approval; (4) volume and the sites' terms: anonymous residential-proxy scraping of PH profile pages at daily scale is a different level from the low-volume, cached use assumed in the ladder docs.

## Housekeeping and the 53-promotion hand check (partial)

- **ph_upvotes moved out.** The daily-refresh commit is reverted from this branch (`8634b865`, a revert commit, history not rewritten) and lives in draft PR #144 (`claude/ph-upvotes-daily`) with the
  $1/week cap and Secret Manager read. Grok Bot will create the `usersim-PROXY_URL` secret and grant the compute service account access.
- **#144's failing check is not a code failure.** The only failing status is Vercel: "Deployment rate limited - retry in 24 hours" (a build-rate limit on the Vercel account; #141 passed the same check at 10:04, #144 hit the limit
  at 11:37). The PR touches only `experiments/pipeline/ph_upvotes/`, nothing Vercel deploys, and GitGuardian passed. No code change fixes it and an empty commit to retrigger is not allowed, so it clears when the limit lifts.
  Optional, not done: an `ignoreCommand` in `vercel.json` so PRs touching only docs, experiments or scripts do not spend deployments; that changes deployment config for the whole repo, so it needs Shreyas.
- **Promotions: 15 of 53 checked, all correct.** Joining `promoted_x_handles.csv` to the two labeled conflict sets gives 15 promoted people with a PH display name and a hand label, and the label is
  "the twitter field is right" for every one (names such as Charlie Clark / Charlie Clark, Giacomo Melzi, Om Gupta, Omar Ghandour; the weakest is `ph:cushmachine`, "Charles C." versus "Charles Cushing", similarity 0.75). These are the same
  rows that built the gate, so they are in-sample.
- **The other 38 cannot be scored by name from the repo**: the committed promotion list has the X name but not the PH display name, which lives in `persons.parquet`. Still needed: Data Feeder runs the
  `promoted_name_margin.csv` script from the v3e/v3f section on the current build and commits the CSV. A weak stand-in (similarity between the PH *username* and the X name or handle, which is not a name) suggests glancing first at:
  `ph:typefoweb` to `mmiszy` (0 followers), `ph:worklab` to `thedeepflux` (X name "Deepak", 3,338 followers), `ph:anvevoice` to `adarshknt1` ("Adarsh Kant"), `ph:greenparrotnow` to `simonfounder`, `ph:slyfirefox` to `peterfox`.
  These are where to look first, not evidence of error: a username such as `worklab` is a product name, so the proxy says nothing about it.
- Other facts from the list: 1 of the 53 is protected, and 22 of the 53 people had X posts attached in v3e.

## run_build.sh output on the v3g inputs (`docs/people_v2_build_20261102/`, 930441fb): checked

**Checked against the committed files** (not recomputed from raw data; built from `5b003cac`, today's new people/events parquet excluded, as reported).
- **Reproduces v3g exactly.** `deltas.txt` shows no change in any row count (persons 20,947, handles 46,998, profiles 26,401, events 310,200), persons added/removed 0/0, every stat equal (53 promoted, 263 conflicts, 1,294 field-only, 52 extra self-links, 40 shared handles), events by platform/kind equal (X posts 24,781), no changed handle rows, and the same profile date-quality table (PH 16,794 fetched + 4,143 upper_bound; X 29 fetched + 1,794 upper_bound; LinkedIn 655 upper_bound + 2,986 unknown). 41 of 41 checks pass; `no_literal_NaN_text` is 0 in every column; `display_name` null 9.
- **Small unexplained number, harmless:** the PH profile rows total 20,937 (16,794 + 4,143), so 10 persons have no PH profile, while `persons_with_events_only` is 8 (the 7 deleted users + the retry). The other 2 have neither a profile nor events (probably people in the newer people parts); `has_profile_matches_profiles` passes, so this is consistent, just worth knowing.

**Promotion list (`promoted_name_margin.csv`): the same 53 people and handles as v3e**, now with PH names for all 53 (the v3e list lacked them). Name similarity: 52 of 53 at 0.75 or above, 1 at 0.52, none below 0.5. The 15 already hand-labelled are in the list and all were labelled correct.
The gate score is generous, though: a one-word X name equal to the PH first name scores 1.0. Re-reading the 53 with a stricter test (X name covers two PH-name words, or the surname appears in the handle or X name) leaves 42 strong and 11 resting on a first name, initials or the handle shape:
- already hand-labelled correct: `cushmachine`, `dragos_bulugean`, `lmadrzak`
- plausible from the handle shape (not proof): `typefoweb` to `mmiszy` ("Michał Miszczyszyn", X name is only the handle), `arth_tyagi` to `arthty`, `ilyasesmail` to `ilyesm`, `seyedia` to `aminsydi`, `yitong_zhang` to `yitong`
- **look at these first:** `i_dino` to `dineshxr` (PH "Dinesh P" against X "Dinesh Rao": the surname initials conflict, so this could be a different Dinesh), `worklab` to `thedeepflux` (PH "Deepak Yadav", X "Deepak", 3,338 followers), `mukulhjoshi` to `muk_l_` (X name is only "Mukul")

**Should the gate be tightened? No evidence for it.** On the 19 dead-link/live-field cases among the 80 hand labels the current gate (name similarity >= 0.5) promotes 15, all correct, and misses 1 (`amanj203`). The stricter test above promotes 12, all correct, and would miss 4, including the 3 hand-verified ones, so it buys nothing in the labels and costs recall. Keep the gate; have a person check the three "look first" rows, and add a surname-initial conflict check only if one of them proves wrong.

## Failing checks on #141, #144, #145 (Nov 2, 14:40 UTC)
- **#141 and #144: the Vercel build-rate limit** ("Deployment rate limited - retry in 24 hours"); GitGuardian passes. Not code, nothing to fix. The same limit is why #145 below cannot be retried now.
- **#145 is different and I cannot diagnose it:** its Vercel status says "Deployment has failed" with an inspect command (`npx vercel inspect dpl_4eSdZScyXah2iC8QgYPr3gd41U9u --logs`), not the rate-limit message, and the PR changes `vercel.json`. This session has no Vercel credentials, so the log is unreadable, and the GitHub check runs (GitGuardian, Vercel Preview Comments) carry no detail.
  What I verified: `vercel.json` parses, `ignoreCommand` is a documented property (a string), the command exits only 0 or 1, and 15 local tests pass. What I cannot rule out: that the new property is what broke the build, or that the failure came from the account hitting its build limit two minutes before #144 was rate-limited (13:40 and 13:42 UTC; this is a coincidence of timing, not evidence).
  **Needed from someone with Vercel access:** run the inspect command above (or open the deployment) and paste the error. I have not changed #145 on a guess, and pushing a retry commit is blocked by the rate limit and not allowed. Do not merge #145 until the log is understood.
