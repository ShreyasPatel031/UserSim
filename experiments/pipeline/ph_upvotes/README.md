# ph_upvotes: Product Hunt /@user/upvotes via fetch-ladder route 4 (residential Camoufox)

Since Oct 30 2026 anonymous fetches of `producthunt.com/@<user>/upvotes` get Cloudflare 403 on routes 1-3
(VM IP, VM Camoufox, curl_cffi via DataImpulse). Route 4 (Camoufox through DataImpulse residential, US exit) passes.
Never Apify (Shreyas said no). Read-only: anonymous page loads, no login, no posting.

## Files
- `fetch_upvotes.py`: the fetcher. N worker processes, one Camoufox each (reused across people), 3 attempts per person
  with 5/15/45 s backoff. A failed attempt closes the browser and opens a fresh one, which gets a new residential exit IP.
  Resumable: rows with status 200/404 already in the output are skipped. `--max-usd` stops when the metered bytes reach that much.
- `vm_startup.sh`: runs it on a GCE VM. Metadata keys: `mode` (run name), `workers`, `people` (gs:// list), `proxy` (PROXY_URL),
  `phup_mode` (`light` default | `goto`). It uploads `out_<mode>.jsonl` + `progress_<mode>.log` every 60 s to the work dir and resumes from it, then shuts down.
- `people_sample.txt`: the 40-person validation sample.

## Modes
- `light` (default): the first person in each browser is a real navigation, which passes Cloudflare and warms the cookies. Every later person
  is a same-origin `fetch()` of the HTML document from inside that page, so the scripts and XHRs aren't downloaded again.
  If the fetch is challenged, it falls back to a navigation.
- `goto`: a full navigation per person (~1 MB each). Use it only if `light` starts failing.

## Output row (superset of ph_predict/parse_upvotes.py)
`{username, status, route:"residential_camoufox", via:"fetch"|"goto", votes_total, has_more, end_cursor,
upvotes:[post ids newest first, ~20 = page 1], upvote_slugs, wire_bytes, secs, attempts, worker, fetched_at}`.
status: 200 ok, 404 no such user, 403 still challenged after 3 tries, -1 error. `wire_bytes` comes from Playwright's request
sizes (headers + encoded bodies) and is what DataImpulse bills (~$1/GB). Deeper pages: `end_cursor` is returned, but paging past page 1
is not implemented (the weekly refresh only uses page 1).

## Run (on a VM, the box's IP is refused by DataImpulse: CONNECT 403)
```bash
W=gs://usersim-bakeoff-347838016394/usersim_sim/raw/ph_upvotes_sample/work   # or your own work dir
gsutil cp fetch_upvotes.py people.txt $W/
gcloud compute instances create ph-upv-1 --zone=us-central1-a --machine-type=e2-standard-4 --subnet=primary-subnet \
  --image-family=debian-12 --image-project=debian-cloud --scopes=storage-rw \
  --metadata-from-file=startup-script=vm_startup.sh \
  --metadata=mode=w1,workers=4,people=$W/people.txt,proxy="$PROXY_URL"
```
Spot VMs were preempted within ~10 min twice on Nov 1, so use on-demand, or rely on the resume. Split big lists over VMs (one `mode` per shard).
Delete the VMs afterwards.

## Following mode and daily refresh (added 2026-11-02 by Data Feeder)
- `PHUP_PAGE=following` fetches `/@<user>/following` page 1 instead of upvotes. The row adds `{page, ph_user_id, followings, has_more, end_cursor,
  following:[[username, followersCount], ...]}`, the same fields as ph_predict/parse_following.py. The default is `PHUP_PAGE=upvotes`, which is unchanged.
- `make_lists.py D outdir`: builds today's upvotes and following lists from the warehouse, using the same rules as pipeline/incremental.plan.
- `vm_daily.sh`: VM startup script. It runs a 5-person following test (aborts with FAILED if fewer than 3 succeed), then upvotes, then following,
  each with its own `--max-usd`, and writes DONE.
- `summarize_daily.py`: writes upvotes_page1.jsonl, following_page1.jsonl, fetch_state_rows.jsonl and README into raw/ph_people_daily/D/.
- `run_daily.sh [D]`: the box wrapper (lists, then VM, wait, summarize). It always deletes the VM via a trap. This is the proposed routine entrypoint.
