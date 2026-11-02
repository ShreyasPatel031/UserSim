# people_v2: next build, staged for Grok Bot / Data Feeder

Staged Nov 2, branch `claude/fetch-ladder-handover` (PR #141). Local files only: nothing here uploads, deletes or writes to the bucket, and no secrets are needed.
**Not run on the real data by the author** (no bucket access); the runner and scripts are tested on the synthetic dataset only (`python -m pytest experiments/people_v2`, 13 tests).

## What is in the bundle (all under `experiments/people_v2/`)
| File | What |
|---|---|
| `run_build.sh` | One reproducible build: checks inputs, runs the tests, builds with the adopted flags, validates, lists the promotions, compares with the previous build |
| `build_v3.py`, `validate_v3.py` | The builder and its 42 checks (same logic as the v3g build, `b02e9649`; no code change since) |
| `compare_builds.py` | Rows, stats, events by platform/kind, changed handle rows and profile date quality between two builds |
| `promoted_margin.py` | The people whose X handle was promoted by the dead-link fallback, with PH name, X name, similarity, lowest first (the hand-check list) |
| `test_build_v3.py`, `test_run_build.py` | 13 tests on a synthetic dataset |

## Run
```bash
# WORKDIR holds the same inputs as the v3g run, plus anything newer (see checklist). PREV = the v3g output directory.
bash experiments/people_v2/run_build.sh WORKDIR v3h WORKDIR/v3g
```
Needs python3 with pandas, pyarrow and pytest. Exit 2 = a missing input (it names the file); exit 1 = a test, the build or a validation check failed (it stops there).
It uses `--x-fallback --x-fallback-sim 0.5 --x-lookup x_lookup.json`, the adopted rule.

## Input checklist (WORKDIR layout)
`raw/ph_profiles.jsonl.gz`, `raw/ph_profiles2.jsonl.gz`, `raw/ph_profiles_rest.jsonl.gz`, `raw/ph_profiles2_refetch*/profiles.jsonl.gz` (every re-fetch directory),
`raw/x_people.jsonl.gz` and `raw/x_posts.jsonl.gz` (base plus the stamped promoted shard, each shard row carrying `fetched_at`), `raw/profile_tabs.jsonl.gz`, `li/*`,
`t/people*.parquet` or `t/people/*.parquet` (**all** tables/people parts), `ev/*.parquet`, `file_dates.json`, `x_lookup.json`.
Record the sha256 of the two X files in the run note; the runner prints it.

## What to send back
`build_report.json`, `validation_v3.json`, `validate.log`, `deltas.txt`, `promoted_name_margin.csv` (and the runner's console output if it stopped early).

## What to expect
- **Inputs unchanged since v3g:** `deltas.txt` shows no change (persons 20,947, handles 46,998, profiles 26,401, events 310,200; `x_field_promoted_dead_link` 53), all checks pass. Any difference means an input changed; find out which before using the build.
- **New inputs** (more people parts, new re-fetches, newer events): rows rise; the checks to watch are `no_orphan_events` (new event people need a profile or will appear as events-only persons), `no_literal_NaN_text`, `no_shared_confident_x_handle` and the promotion count. If `x_lookup.json` is older than the new conflicts, handles without a lookup entry simply are not promoted.
- **Daily refresh data (PR #144)** feeds the build only once it has been merged into `tables/events` / `fetch_state` by the warehouse code; the builder does not read `ph_people_daily` directly.

## Not in this bundle (open)
- Hand review of the promotions: `promoted_name_margin.csv` is the input; someone fills `label_correct_wrong_unsure`, starting with the lowest similarity (the 15 already hand-labelled are all correct; 38 are not yet checked individually).
- `segments` (dropped in this build), a personal-versus-company label for X handles, and real capture dates for the legacy PH rows (they carry the Oct 28 upper bound).
