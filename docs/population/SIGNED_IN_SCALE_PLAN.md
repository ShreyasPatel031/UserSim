# Signed-in Product Hunt person pulls: scale plan (DRAFT, orchestrator, 2026-11-04)

Status: waiting on the first signed-in test (to_grokbot/20261104T1600_orchestrator_signed_in_test.md;
reply due in from_grokbot/20261104T1605_signed_in_profile.reply.md). Nothing below runs until gate 0 passes.
Authority: Shreyas approved signed-in extraction on the Camoufox PH account on Nov 4 and made scaling it the priority
(via Grok Bot). He accepts that the account may get blocked.

## Why
Signed out, PH serves at most ~200 upvotes per profile (hasNextPage=false at ~200; measured on 5 heavy profiles and
on VM-2 today). Heavy upvoters, who are a large share of launch-day votes, lose most of their history. Upvotes are the
person model's core tab.

## Gates
| Gate | Pass condition | If it fails |
|---|---|---|
| 0. Signed-in test (15 people) | upvotes go past 200 on most capped people, other tabs at least as complete as signed out, no account warning | stay signed out; upvotes_capped stays the record; close this plan |
| 1. Day 1 at the starting cap | 300 people, 0 account warnings, block rate no worse than signed out | halve the cap, rest a day, retry once |
| 2. Day 2–3 | same at 300/day | hold at 300 |
| 3. Raise | 500/day per account after 2 clean days | — |
| 4. More accounts | only with Shreyas's yes (new accounts are his call) | — |

## Shape
- 1 account = 1 persistent Camoufox profile = 1 fixed sticky port and exit IP. The account is never used from two IPs.
- Read-only. No votes, follows, comments or any other write.
- Pace: 1 person per 3 min per session (clean today on 10003 over ~4 h). Per-person budget 20 min / 15 MB; budget checked
  between pages inside a tab.
- Stop at the first 403, challenge, captcha or account warning. Report, and don't retry the same day.
- The account's exit IP is chosen once and never rotated. Port pre-screening and skipping 403 ports are still Shreyas's call.

## What goes signed in, in order
1. Likely voters (1,572) whose upvotes were capped signed out: upvotes tab only (~N/20 requests; ~1.5 MB for 3k upvotes).
2. The nightly 00:02 PT maker/hunter headers, if signed in shows fields that signed out hides.
3. Active pool (2,639): upvotes tab for anyone capped.
4. Everything else stays on the signed-out people VMs, which keep running in parallel.

## Throughput and cost (estimates, to be replaced by gate-0 numbers)
| Item | Estimate |
|---|---|
| People per account per day | 300 to start (cap), up to ~480 at 1 person / 3 min |
| Upvotes-only pull | ~1.2 s per page, ~3 min for a 3,000-upvote person |
| Bytes | ~18 KB per 20-item page, ~1.5 MB per heavy person |
| Proxy cost | ~$0.002 per person at ~$1/GB; inside the $6/week people budget |
| Likely voters, capped subset | ~2–4 days with one account at 300/day |

## Risks
- Account ban or rate limit (accepted by Shreyas). Mitigation: read-only, daily cap, stop on first warning.
- Logged-in traffic tied to one IP: if that exit IP goes bad (as 10002 did today), the account stops until Shreyas
  picks a new IP.

## Verification
The babysitter verifies gate 0 and each day: items vs header per tab, signed-in-only fields, MB/requests/minutes per
person, account warnings. Its results go in docs/babysitter/signed_in_diff.md.
