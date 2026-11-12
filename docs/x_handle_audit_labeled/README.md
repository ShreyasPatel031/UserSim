# x_handle_audit_labeled — DRAFT (not yet verified by fetch-ladder)

Labeled copy of mailbox/from_grokbot/x_handle_audit_100.csv (100 rows, 101 handles). Produced by Data Feeder 20261102T0602Z.

## Method
- PH side: local refetch profiles (raw/ph_profiles2_refetch/profiles.jsonl.gz + pv2 refetch_final): name, headline, about, links, twitter field. No live PH page fetches were needed.
- X side: public X users lookup (get_users_by_usernames), 5 calls of <=25 handles: name, bio, url, bio links, followers.
- No sign-ins, no Apify/Browserbase. Labels assigned by rule + manual review of each row.

## Rules
- match/high: X name matches PH name AND a shared website/product/employer (or PH lists this handle and bio clearly matches).
- match/med: name matches but X profile sparse (often 0-follower, empty bio) or bio drifted (job change, other product).
- mismatch/high: handle is a company/product/brand account rather than the person (label_personal_or_company_or_wrong=company), or an unrelated person (=wrong).
- unsure/low: X account suspended (API "Forbidden") or not found (deleted/renamed) — cannot verify.

## Counts
- match 72 (55 high, 17 med); mismatch 13 (12 company accounts, 1 wrong person); unsure 15 (9 suspended, 6 not found).
- By source: ph_self_link 63 match / 8 mismatch / 13 unsure; ph_twitter_field 9 / 5 / 2.

## Caveats
- One labeler pass, not double-checked; treat as draft.
- 'company' rows: the founder linked the company handle from PH. Whether to keep those as an X identity for the person is a policy call for fetch-ladder.
- ph:curiouskitty -> @producthunt is PH's own persona; excluded as mismatch.
- ph:agentdm is itself an org PH account, so @agentdmai labeled match/med (kind=company).
- 9 suspended handles all belong to a cluster of Turkish-name PH accounts with motto headlines and 0-follower X links (likely a bot/sockpuppet farm); several similar non-suspended ones (alperen397545, ahmet4316897505, kranur594186, c_kurtar55949, mutugantan82154, ceylanm63067, alparslan273712, veyselzpnf) are labeled match/med on name only but probably share that pattern.
- ph:soodadityab -> @soodadityab is now a Chinese stock account: handle likely reassigned (wrong).
- ph:subhh: PH twitter field (that_webdev_guy) disagrees with the self-link (subhadipdev); the self-link matches.
