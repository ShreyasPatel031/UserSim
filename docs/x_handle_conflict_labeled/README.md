# x_handle_conflict_labeled — DRAFT (not yet verified by fetch-ladder)
50 of the 316 people_v3c handles rows with note "conflicts with self link; not used" (pandas sample, random_state=141). Each row: PH self-link X handle (kept by build) vs PH twitter field (demoted, conf 0.2).
## Method
PH side from v3c profiles (name, headline, bio). X side: public X users lookup (get_users_by_usernames), 4 calls x 25 handles, raw in x_lookup.json. No sign-ins, no site scraping.
Labels per handle follow x_handle_audit_labeled rules (match high/med, mismatch company/wrong, unsure = not found/suspended or no evidence); correct_handle = self_link | twitter_field | both | neither.
## Tallies
correct_handle: self_link 24, twitter_field 14, neither 9, both 3.
self link: match 27 / mismatch 3 / unsure 20 (19 not found on X). twitter field: match 17 / mismatch 10 (6 company, 4+ wrong person) / unsure 23 (21 not found).
## Takeaway
The self-link-wins rule is right in 24+3 of 41 decidable rows, but in 14 (28%) the self link is dead (renamed/deleted) and the twitter field is the live, correct account. Suggest: when the self-link handle does not resolve on X and the twitter field does with a name match, prefer the field.
## Caveats
One labeler pass. "Not found" may be rename/suspension (the API returned Not Found for all). Rows 6/19/22 are people with two real accounts.
