# Caps audit of the VM people code, 2026-11-04 20:30 UTC

Package: vm/_code/reuse.tgz md5 KSkCQvRomzj6fzif1u001g== (Data Feeder "nocap" build, 20:17Z). Rule: no caps; only PH's own limits.

| # | Where (code) | What stops short | Verdict |
|---|---|---|---|
| 0 | ph_batch.py fcap/mark_capped | followers 500 / 2,000 role cap (added 16:50Z) | **removed** in this build; 377 people pulled under it 16:50–20:17Z need re-pull (only 3–5 are on deep_list) |
| 1 | ph_batch.py `--threads 20`, `fitems[:a.threads]`; enrich.py same | only the first 20 forum threads get full body + replies; the rest `thread_full=False` | **CAP: FAIL** |
| 2 | ph_batch.py thread(): `for k in range(25)` | at most 25 "more replies" clicks per thread | **CAP: FAIL** on long threads |
| 3 | paging_v2.py `maxp = goal//20+10 if goal else 500` | lists with no header (activity) stop at 500 pages = 10,000 items, `ended=max_pages`; deep pass re-pulls non-follow tabs from page 1, so it hits the same wall forever | **CAP: FAIL** for activity > 10k |
| 4 | ph_batch.py more_stacks(): `range(40)` scroll rounds | stacks beyond 40 scroll rounds | **CAP** (low risk) |
| 5 | ph_batch.py BUDGET 1200 s / 15 MB, `--person-timeout 1500`; deep DEEP_SECS 3600 / 60 MB | lists cut mid-way; resumed by cursor for followers/following only; other tabs restart from page 1 and can loop | **partial: OK only if deep pass finishes**; verify per person |
| 6 | ph_batch.py `CAP = 5.5e9` (weekly STOP.budget) | all pulls stop at 5.5 GB; Shreyas raised the cap to $30 / ~29 GB | **stale: must be raised to ~29e9** |
| 7 | ph_batch.py budget skips: `product_pages`, `forum_threads` truncated_budget | maker product pages / threads skipped when over budget | **FAIL** unless the deep pass re-pulls them |
| 8 | Half mode skips deep_list people | heavy people never finished in half mode | **FAIL** unless deep mode runs |
| 9 | ph_person.py `--followers-cap 10000` default | legacy single-person script | **CAP** if anything still calls it |
| — | paging_v2.py upvotes: endCursor chain to hasNextPage=false, `complete_not_visible` | ~200 signed out | PH's own limit, **allowed** |
