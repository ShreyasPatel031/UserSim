# Next throughput levers for K8 (draft: full19 candidate)

Drafted on top of the `full18` candidate. **Not deployed, not audited.** The code lives only in the
candidate tarball (`raw/_pacetest/_code/bsit_full19_candidate.tgz`) for the population agent to review
after full18 clears; this file is the prose summary.

## Lever 1 — move comment/thread lookups from page loads to direct GraphQL

The slow tail of a person pull is the per-comment / per-thread **page navigations** (open the post or
thread page and scroll). Replacing those with a direct persisted-query GraphQL call (as is already done
for the profile tabs) would cut `mean_T_person` and *also* reduce the number of requests per person —
raising complete-people/hour while lowering the per-person request footprint.

**Blocker, and what full19 does about it:** Product Hunt uses persisted queries, so issuing those calls
directly needs each op's `operationName` **+ sha256 hash + variables shape**. No run captured the
comment/thread ops — the runs ended before reaching comment-heavy profiles, and the earlier `op_seen`
logging stored only the name and hash, not the variables. full19 therefore does **not** yet contain the
migration itself (writing a non-working call would only mislead review). Instead it **harvests the op**:
- `op_seen` now also captures the **variables**, and for any op not already known it records one full
  example `{operationName, hash, variables, method}`.
- `dump_discovered()` flushes those examples (once each) to `…/_discovered_ops/<op>.json`.

Once a single comment-heavy and a single thread-heavy profile are pulled, the real op shapes are on
disk, and the direct-GraphQL call can be written and audited. The migration is one captured example away.

## Lever 2 — deleted-account pre-filter (functional now)

Deleted/renamed accounts return "no profile in SSR" only *after* occupying a worker slot. full19:
- `_full_queue` skips handles listed under `…/deleted/` (empty by default → no-op).
- On a "no profile" result, the handle is marked under `…/deleted/` (a race-free per-handle marker,
  same pattern as claims), so the list self-builds across runs and later runs stop re-pulling the dead.

Re-pull requests bypass the filter (explicit requests always win).

## Local tests (this session)

- `op_seen` captures a GET and a POST migratable op with their variables; a known profile op is **not**
  double-recorded as "discovered". `dump_discovered` writes one file per op and does not re-flush.
- Deleted-filter set logic excludes `have`, `deep`, `deleted`, and routes re-pull requests separately.
- Both edited modules compile.

## Status

- Builds on the **unaudited** full18 candidate; must be re-audited by the population agent after full18
  clears, before any use. No VMs, no deploy, no Product Hunt traffic were involved in drafting it.
- Lever 1's throughput gain is pending a run that harvests the comment/thread op examples (fleet is
  currently down / on hold).
