# Product Hunt person-pull VMs: implementation notes (2026-11-05)

A high-level record of how the person-pull test VMs were set up and what the pull build does.
The puller source, the VM wrapper script, and the operational/measurement logs are intentionally
not included here.

## VM creation

- **Machine:** e2-standard-4 in us-central1-a, network `main-vpc`, subnet `primary-subnet`, Debian 12, 20 GB disk.
- **Service account:** `usersim-cloud-agent`, scope `cloud-platform`.
- **Metadata:** a startup script, plus keys for the build tarball name and its md5, and runtime config.
- **Control files** in `gs://usersim-bakeoff-347838016394/usersim_sim/raw/ph_population/people_live/vm/`:
  - `_ports/port.<port>` — a one-line claim file per proxy port.
  - `GO.<vm>` — the pull runs only while this file exists.
  - `STOP_ALL`, `STOP.budget`, `STOP.<vm>` — halts.
  - `status/<vm>.jsonl` — append-only run log.
- **Startup:** the VM verifies the build tarball against its md5 before running, writes whole-person
  JSON to `raw/_pacetest/shared/`, and appends run events to its status file.
- **Retiring a VM:** delete the instance, remove `GO.<vm>`, and mark the port file free.

## Build pipeline (full7 → full17)

Each build was reviewed by the population agent before it ran. The audited tarballs are in
`raw/_pacetest/_code/`. The changes across the pipeline, all about completeness of the data pulled:

| Area | Change |
|---|---|
| Single writer | Only the gated whole-person pull writes. Saves, claims, the already-saved set and the work queues are rooted at a configurable base (`PH_SAVE_B`); kill-switch, `GO`, status and the weekly byte budget stay on the live path. |
| Byte accounting | Each status row carries NIC bytes so the shared weekly budget can see the run. |
| Concurrency hygiene | A sized thread pool; the weekly-bytes and control-file checks are each refreshed by one worker at a time and cached briefly; status uploads happen off the event loop from a snapshot, and on SIGTERM. |
| Comment times | For "left a comment" activity items whose timestamp came only from a launch date, the comment's own page is opened and `Comment.createdAt` is read by comment id; lookups are grouped by post page. |
| Stacks | The first stacks page is read from the `ProfileStacksPage` GraphQL op (page SSR as fallback); a server-side end-of-list is recorded in `stacks.paging`. |
| Queue order | Re-pull requests first, then a priority list, then the general need list. |
| Instrumentation | Each person's build md5 is written into its JSON; the GraphQL operation names the pages themselves call are logged. |

Credentials, the puller source, the VM wrapper, and files containing Product Hunt usernames are not included.
